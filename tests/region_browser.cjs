// Full app + real Leaflet/Chromium; isolated temporary demo with fixture-backed GIOŚ only.
// NODE_PATH=/path/to/node_modules node --test tests/gios_browser.cjs
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const {once}=require('node:events');
const net=require('node:net');
const path=require('node:path');
const {chromium}=require('playwright');
const {setTestTheme}=require('./browser_theme.cjs');
const root=path.resolve(__dirname,'..');
const theme=process.env.WICI_TEST_THEME||'light';
assert.ok(['light','dark'].includes(theme),'WICI_TEST_THEME must be light or dark');

async function server(){
 const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
 const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
 const python=spawnSync('uv',['run','python','-c','import sys; print(sys.executable)'],{cwd:root,encoding:'utf8'});
 assert.equal(python.status,0,python.stderr);
 const process=spawn(python.stdout.trim(),['-u','-c',`
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
import json
import httpx
from datetime import UTC, datetime
from wici.gios import GiosService
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-gios-regression-') as root:
    app=create_app(demo=True, root=Path(root), config=Config(port=${port}))
    original=app.router.lifespan_context
    fixtures=Path('tests/fixtures/gios')
    def handler(request):
        name=('stations' if 'findAll' in request.url.path else 'sensors' if '/sensors/' in request.url.path
              else 'index' if '/getIndex/' in request.url.path else 'manual' if request.url.path.endswith('/9100') else 'data')
        return httpx.Response(400 if name=='manual' else 200, json=json.loads((fixtures/(name+'.json')).read_text()))
    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                app.state.gios=GiosService(client, lambda:datetime(2026,10,17,6,30,tzinfo=UTC))
                yield
    app.router.lifespan_context=lifespan
    uvicorn.run(app,
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

test('saved region, independent progress, scoped GIOS indices, polygon clipping and mobile', {timeout:60000},async()=>{
 const app=await server();let browser,release;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});await setTestTheme(page);page.setDefaultTimeout(15000);
  const errors=[],indices=[],communications=[],held=new Promise(resolve=>release=resolve);page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{if(!localStorage.getItem('region-test-init')){localStorage.setItem('wici.region.v1','02');localStorage.setItem('region-test-init','1');}});
  const now=new Date().toISOString(),base={enabled:true,status:'ready',items:[],fetched_at:now,refresh_seconds:300};
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());if(url.origin!==app.url)return route.abort();
   if(url.pathname==='/api/communications')communications.push(url.searchParams.get('voivodeship'));
   if(url.pathname==='/api/hydro'){await held;return route.continue();}
   if(url.pathname==='/api/gios'){
    const kind=url.searchParams.get('kind');
    if(!kind||kind==='stations')return route.fulfill({json:{...base,items:[{id:1,name:'Wrocław',latitude:51.11,longitude:17.04},{id:2,name:'Warszawa',latitude:52.23,longitude:21.01},{id:3,name:'Opole',latitude:50.67,longitude:17.92},{id:4,name:'Bez punktu',latitude:null,longitude:null}]}});
    if(kind==='index'){indices.push(Number(url.searchParams.get('id')));return route.fulfill({json:{...base,refresh_seconds:1800,items:[{name:'Dobry',value:1,observed_at:now,calculated:{observed_at:now}}]}});}
   }
   return route.continue();
  });
  await page.goto(app.url);await page.waitForFunction(()=>window.WiciRegion?.ready());assert.equal(await page.locator('#province').inputValue(),'02');
  await page.evaluate(()=>{for(const id of ['gios-enabled','hydro-stations']){const el=document.getElementById(id);el.checked=true;el.dispatchEvent(new Event('change'));}});
  await page.waitForFunction(()=>document.getElementById('gios-index-status').textContent.includes('Odczytano 1/1'));
  assert.deepEqual(indices,[1]);assert.equal(communications[0],'02');assert.equal(await page.locator('#gios-station option').count(),2);
  assert.match(await page.locator('[data-layer="hydro-stations"]').getAttribute('data-state'),/Wczytywanie/);
  assert.equal(await page.locator('[data-layer="gios-enabled"]').getAttribute('data-state'),'Odczyt zakończony');
  const clipping=await page.evaluate(async()=>{
   state.map.fitBounds([[49,14],[55,24]],{animate:false});
   state.map.createPane('regionTest').style.zIndex='500';
   const inside=L.circleMarker([51.11,17.04],{pane:'regionTest',radius:12}).addTo(state.map),outside=L.circleMarker([52.23,21.01],{pane:'regionTest',radius:12}).addTo(state.map);
   await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
   const hit=layer=>{const r=layer.getElement().getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===layer.getElement();};
   const result={supported:CSS.supports('clip-path',state.map.getPane('regionTest').style.clipPath),inside:hit(inside),outside:hit(outside)};inside.remove();outside.remove();return result;
  });
  assert.deepEqual(clipping,{supported:true,inside:true,outside:false});
  release();await page.waitForFunction(()=>document.querySelector('[data-layer="hydro-stations"]').dataset.state!=='Wczytywanie');
  await page.locator('#province').selectOption('14');await page.waitForFunction(()=>document.getElementById('gios-index-status').textContent.includes('Odczytano 1/1'));assert.deepEqual(indices,[1,2]);
  await page.reload();await page.waitForFunction(()=>window.WiciRegion?.ready());assert.equal(await page.locator('#province').inputValue(),'14');
  await page.locator('#province').selectOption('');await page.evaluate(()=>{const el=document.getElementById('gios-enabled');el.checked=true;el.dispatchEvent(new Event('change'));});
  await page.waitForFunction(()=>document.getElementById('gios-index-status').textContent.includes('Odczytano 3/3'));assert.equal(await page.locator('#gios-station option').count(),5);
  await page.locator('#province').selectOption('02');await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'tmp/region-mobile.png',fullPage:true});assert.deepEqual(errors,[]);
 }finally{release?.();await browser?.close();await app.stop();}
});

test('changing region during imagery and Sentinel-2 searches removes old point and ignores late results', {timeout:60000},async()=>{
 const app=await server();let browser,release;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});await setTestTheme(page);page.setDefaultTimeout(15000);
  const errors=[],held=new Promise(resolve=>release=resolve);let imageryStarted,s2Started;const imageryEntered=new Promise(resolve=>imageryStarted=resolve),s2Entered=new Promise(resolve=>s2Started=resolve);page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());if(url.origin!==app.url)return route.abort();
   if(url.pathname==='/api/imagery'||url.pathname==='/api/sentinel2/search'){
    if(url.pathname==='/api/imagery')imageryStarted();else s2Started();await held;
    try{return await route.fulfill({json:url.pathname==='/api/imagery'?{enabled:true,status:'ready',items:[{title:'Old Wrocław',bounds:[[51,17],[51.2,17.2]]}],providers:[]}:{status:'ready',items:[{id:'old',observed_at:'2026-10-01T10:00:00Z'}],grid:{bounds:[[51,17],[51.2,17.2]]}}});}catch{return;}
   }
   return route.continue();
  });
  await page.goto(app.url);await page.waitForFunction(()=>window.WiciRegion?.ready());await page.locator('#province').selectOption('02');
  await page.evaluate(()=>{
   state.map.setView([51.11,17.04],10,{animate:false});
   for(const id of ['imagery-enabled','s2-enabled']){const el=document.getElementById(id);el.checked=true;el.dispatchEvent(new Event('change'));}
   document.getElementById('imagery-center').click();document.getElementById('s2-center').click();document.getElementById('s2-search').click();
  });
  await Promise.all([imageryEntered,s2Entered]);await page.locator('#province').selectOption('14');
  const center=await page.evaluate(()=>{const p=state.map.getCenter();return [p.lat,p.lng];});release();
  await page.waitForFunction(()=>document.querySelector('[data-layer="imagery-enabled"]').dataset.state!=='Wczytywanie');
  assert.equal(await page.locator('#imagery-location').textContent(),'Nie wybrano miejsca.');assert.equal(await page.locator('#imagery-gallery > *').count(),0);
  assert.equal(await page.locator('#s2-point').textContent(),'Nie wybrano punktu.');assert.equal(await page.locator('#s2-before option').count(),1);
  assert.deepEqual(await page.evaluate(()=>{const p=state.map.getCenter();return [p.lat,p.lng];}),center);
  await page.waitForFunction(()=>!document.querySelector('.imagery-selected-point,.imagery-footprint,.leaflet-s2Point-pane path'));
  await page.locator('#province').selectOption('02');assert.equal(await page.locator('#imagery-gallery > *').count(),0);assert.equal(await page.locator('#s2-before option').count(),1);assert.deepEqual(errors,[]);
 }finally{release?.();await browser?.close();await app.stop();}
});
