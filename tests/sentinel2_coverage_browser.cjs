// Full offline app and real Chromium: desktop and mobile touch viewport.
'use strict';
const {setTestTheme} = require('./browser_theme.cjs');
const test=require('node:test'),assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const {once}=require('node:events');
const net=require('node:net'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
async function server(){
 const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
 const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
 const python=spawnSync('uv',['run','python','-c','import sys; print(sys.executable)'],{cwd:root,encoding:'utf8'});
 assert.equal(python.status,0,python.stderr);
 const process=spawn(python.stdout.trim(),['-u','-c',`
import tempfile
from pathlib import Path
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-s2-coverage-regression-') as root:
    uvicorn.run(create_app(demo=True, root=Path(root), config=Config(port=${port})),
                host='127.0.0.1', port=${port}, log_level='error')
`],{cwd:root,stdio:['ignore','pipe','pipe']});
 let logs='';process.stdout.on('data',chunk=>logs+=chunk);process.stderr.on('data',chunk=>logs+=chunk);
 const url=`http://127.0.0.1:${port}`;
 try{
  for(let i=0;i<200;i++){
   if(process.exitCode!==null)throw new Error(logs);
   try{if((await fetch(url+'/api/health')).ok)return {url,async stop(){const exited=once(process,'exit');process.kill('SIGTERM');await exited;}};}catch{}
   await new Promise(resolve=>setTimeout(resolve,50));
  }
  throw new Error('Demo startup timeout: '+logs);
 }catch(error){process.kill('SIGTERM');throw error;}
}
// Generate a small, deterministic PNG fixture locally; no archived LIVE evidence or network dependency.
const fixture=spawnSync('uv',['run','python','-c',`
import json
import numpy as np
from wici.sentinel2 import geometry, images
data=np.zeros((5,4,4),dtype='uint8')
data[0]=65; data[1]=120; data[2]=60; data[3]=255; data[4]=4
print(json.dumps(images(data, {'id':'fixture'}, geometry(52.02,19.12,4))))
`],{cwd:root,encoding:'utf8'});
assert.equal(fixture.status,0,fixture.stderr);
const renderedFixture=JSON.parse(fixture.stdout),rgb=renderedFixture.image,mask=renderedFixture.mask;
const item=(id,day,coverage)=>({id,observed_at:`2026-10-${day}T10:00:00+00:00`,cloud_cover:0,catalog_coverage_percent:coverage});
const observations=[item('full-before','01',100),item('full-after','16',100),item('partial','05',50),item('unknown','06',null)];
for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
 test(`Sentinel-2 coverage ${name}: default filter, missing percentages, recovery and stale responses`,{timeout:45000},async()=>{
  const app=await server();let browser;
  try{
   browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport,hasTouch:name==='mobile',isMobile:name==='mobile'});await setTestTheme(page);
   const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
   let coverage=[75,0],renderCalls=0,onlyPartial=false,hold=null,release,entered;
   await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==app.url){external.push(url.href);return route.abort();}
    if(url.pathname==='/api/sentinel2/search'){
     const full=url.searchParams.get('full_only');assert.ok(full==='true'||full==='false');
     const all=onlyPartial?observations.slice(2):observations;
     const items=full==='true'?all.filter(i=>i.catalog_coverage_percent===100):all;
     return route.fulfill({json:{status:'ready',items,grid:renderedFixture.grid,total_items:all.length,
      excluded_partial_count:full==='true'?1:0,excluded_unknown_count:full==='true'?1:0}});
    }
    if(url.pathname==='/api/sentinel2/render'){
     renderCalls++;const id=url.searchParams.get('identifier'),chosen=observations.find(i=>i.id===id);
     assert.ok(chosen);if(hold){entered();await hold;}
     const valid=id==='full-before'?coverage[0]:id==='full-after'?coverage[1]:50;
     return route.fulfill({json:{...renderedFixture,item:chosen,image:rgb,mask,
      status:valid===100?'ready':valid===0?'no_coverage':'partial_coverage',
      quality:{coverage:valid,missing_percent:100-valid,cloud:0,shadow:0,snow:0}}});
    }
    return route.continue();
   });
   await page.goto(app.url);await page.waitForFunction(()=>state.geometries.has('PL')&&!state.map._animatingZoom);
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#s2-group').evaluate(e=>e.open=true);
   await page.locator('#s2-enabled').check();await page.locator('#s2-center').click();
   assert.ok(await page.locator('#s2-full-only').isChecked());
   await page.locator('#s2-search').click();await page.waitForFunction(()=>document.querySelector('#s2-before').options.length===3);
   assert.match(await page.locator('#s2-status').textContent(),/Ukryto: 1 częściowych, 1 o nieznanym/);
   assert.equal(await page.locator('#s2-before option[value="partial"]').count(),0);
   await page.locator('#s2-before').selectOption('full-before');await page.locator('#s2-after').selectOption('full-after');
   await page.locator('#s2-compare').click();await page.locator('.s2-warning').waitFor();
   assert.match(await page.locator('#s2-status').textContent(),/przed: brak 25%; po: brak 100%/);
   assert.doesNotMatch(await page.locator('#s2-status').textContent(),/Porównanie gotowe/);
   assert.match(await page.locator('#s2-detail').textContent(),/Brakuje 25% obrazu/);
   await page.locator('#layer-panel').evaluate(e=>e.open=false);
   assert.ok(await page.locator('.s2-warning').isVisible());
   const geometry=await page.locator('.s2-swipe').evaluate(e=>{
    const a=e.getBoundingClientRect(),b=document.querySelector('#map').getBoundingClientRect();
    return {inside:a.left>=b.left&&a.right<=b.right&&a.top>=b.top&&a.bottom<=b.bottom};
   });assert.ok(geometry.inside);
   await page.screenshot({path:`tmp/browser-evidence/sentinel2/${name}-coverage-warning.png`,fullPage:true});
   const requests=renderCalls;await page.getByRole('slider',{name:'Porównanie przed i po'}).fill('80');assert.equal(renderCalls,requests);
   // A subsequent complete pair must remove all previous missing-data warnings.
   coverage=[100,100];await page.locator('#layer-panel').evaluate(e=>e.open=true);
   await page.locator('#s2-compare').click();await page.waitForFunction(()=>document.querySelector('#s2-status').textContent.includes('Porównanie gotowe'));
   assert.equal(await page.locator('.s2-warning').count(),0);
   assert.doesNotMatch(await page.locator('#s2-status').textContent(),/Niepełny|Brak pokrycia/);
   // A tiny real gap must never be displayed as a complete image or 0% missing.
   coverage=[99.9997,100];await page.locator('#s2-compare').click();await page.locator('.s2-warning').waitFor();
   assert.match(await page.locator('.s2-warning').textContent(),/przed: brak <0,01%; po: brak 0%/);
   coverage=[100,100];
   // Partial and unknown observations require explicit opt-in and carry their own labels.
   await page.locator('#s2-full-only').uncheck();assert.equal(await page.locator('.s2-swipe').count(),0);
   await page.locator('#s2-search').click();await page.waitForFunction(()=>document.querySelector('#s2-before').options.length===5);
   assert.match(await page.locator('#s2-before option[value="partial"]').textContent(),/UWAGA:.*brakuje 50%/);
   assert.match(await page.locator('#s2-before option[value="unknown"]').textContent(),/UWAGA: nieznane pokrycie/);
   await page.locator('#s2-before').selectOption('partial');await page.locator('#s2-after').selectOption('full-after');
   await page.locator('#s2-compare').click();await page.locator('.s2-warning').waitFor();
   assert.match(await page.locator('.s2-warning').textContent(),/Niepełny obraz.*przed: brak 50%; po: brak 0%/);
   // Changing coverage policy cancels a pending comparison and late warnings cannot return.
   hold=new Promise(r=>release=r);const started=new Promise(r=>entered=r);
   await page.locator('#s2-compare').click();await started;await page.locator('#s2-full-only').check();release();hold=null;
   await page.waitForTimeout(150);assert.equal(await page.locator('.s2-warning').count(),0);assert.equal(await page.locator('.s2-swipe').count(),0);
   onlyPartial=true;await page.locator('#s2-search').click();
   await page.waitForFunction(()=>document.querySelector('#s2-status').textContent.includes('Brak obserwacji z pełnym'));
   assert.match(await page.locator('#s2-status').textContent(),/odznacz.*Tylko pełny/);
   assert.equal(await page.locator('#s2-before option').count(),1);
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  }finally{if(browser)await browser.close();await app.stop();}
 });
}
