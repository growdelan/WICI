// Full application + bundled Leaflet regression. Starts its own isolated offline demo server.
// NODE_PATH=/path/to/node_modules node --test tests/hydro_browser.cjs
'use strict';
const {setTestTheme} = require('./browser_theme.cjs');
const test=require('node:test'),assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const {once}=require('node:events');
const net=require('node:net');
const path=require('node:path');
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
with tempfile.TemporaryDirectory(prefix='wici-gfm-regression-') as root:
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
const fs=require('node:fs');
const synthetic=JSON.parse(fs.readFileSync('tests/fixtures/gfm/browser.json'));
synthetic.image=fs.readFileSync('tests/fixtures/gfm/synthetic.png').toString('base64');
const search=synthetic.verification.search;
const flush=()=>new Promise(r=>setTimeout(r,100));
for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}],['wide',{width:2804,height:1756}]]){
 test(`GFM ${name}: raster, IMGW popup, changing observations and disabling`,{timeout:45000},async()=>{
  const app=await server();let browser;
  try{
   browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport});
    await setTestTheme(page);
   const errors=[],external=[];let searches=0,renders=0,delay=null;
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==app.url){external.push(url.href);return route.abort();}
    if(url.pathname==='/api/gfm'){searches++;assert.equal(url.searchParams.get('bbox'),'16.55,50.35,16.75,50.55');return route.fulfill({json:{...search,items:[...search.items,{...search.items[0],id:'incomplete-ui',renderable:false,missing_assets:['exclusion_mask']}]}});}
    if(url.pathname.startsWith('/api/gfm/render/')){renders++;if(delay&&url.pathname.endsWith('/'+search.items.find(i=>i.id!==synthetic.product.id).id)){await delay;}return route.fulfill({json:synthetic});}
    if(url.pathname==='/api/hydro'){
     if(url.searchParams.get('kind')==='stations'){
      const m={value:340,unit:'cm',observed_at:new Date().toISOString()};
      return route.fulfill({json:{enabled:true,status:'ready',fetched_at:new Date().toISOString(),
       source_url:'https://danepubliczne.imgw.pl/api/data/hydro/',items:[{id:'ui-test',name:'Test IMGW',
       river:'Nysa Kłodzka',province:'dolnośląskie',latitude:50.44,longitude:16.65,
       warning_level_cm:300,alarm_level_cm:340,measurements:{water_level:m,discharge:m,temperature:m}}]}});
     }
     return route.fulfill({json:{enabled:true,status:'ready',fetched_at:new Date().toISOString(),items:[{
      id:'warning-test',event:'Ostrzeżenie testowe',severity:1,areas:[],description:'Dane testowe UI',
      valid_from:'2024-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z'}]}});
    }
    return route.continue();
   });
   await page.goto(app.url);await page.locator('.province-card').first().waitFor();
   await page.waitForFunction(()=>state.geometries.has('PL')&&document.querySelector('#province').options.length>1&&!state.map._animatingZoom);
   assert.equal(searches,0);assert.equal(renders,0);
   await page.locator('#layer-panel').evaluate(e=>e.open=true);
   await page.locator('#gfm-group').evaluate(e=>e.open=true);
   await page.locator('#gfm-enabled').check();assert.equal(searches,0);
   assert.equal(await page.locator('#gfm-end').inputValue(),await page.evaluate(()=>new Date().toISOString().slice(0,10)));
   await page.locator('#gfm-mode').selectOption('manual');
   await page.locator('#gfm-recent').click();assert.equal(searches,0);
   await page.locator('#gfm-klodzko').click();
   await page.waitForFunction(()=>document.querySelector('#gfm-observation').options.length>1);
   assert.equal(await page.locator('#gfm-observation option[value="incomplete-ui"]').evaluate(e=>e.disabled),true);
   await page.waitForFunction(()=>document.querySelector('#gfm-status').textContent.includes('Wykryto zalanie'));
   await page.waitForFunction(()=>!!document.querySelector('.leaflet-gfmPixels-pane img')?.complete);
   assert.equal(await page.locator('#gfm-observation').inputValue(),synthetic.product.id);
   assert.equal(searches,1);assert.equal(renders,1);
   if(name==='wide')assert.ok(await page.evaluate(()=>state.map.getBounds().getEast()-state.map.getBounds().getWest()>.5));
   assert.match(await page.locator('#gfm-detail').textContent(),/GFM v3.1.0/);
   assert.match(await page.locator('#gfm-status').textContent(),/ARCHIWALNA/);
   await page.locator('#gfm-opacity').fill('0.3');
   assert.equal(await page.locator('.leaflet-gfmPixels-pane img').evaluate(e=>e.style.opacity),'0.3');
   // Hydrology controls are inside their own outer group.
   await page.locator('#hydro-stations').evaluate(e=>{let p=e.parentElement;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}});
   await page.locator('#hydro-stations').check();await page.locator('#hydro-warnings').check();
   await page.waitForFunction(()=>document.querySelector('#hydro-station').options.length>1);
   await page.evaluate(()=>{
    state.map.eachLayer(l=>{if(l.hydroItem&&l.hydroItem.latitude){window.testStation=l;}});
    const marker=window.testStation;state.map.setView(marker.getLatLng(),12);marker.openPopup();
   });
   assert.ok(await page.locator('.hydro-station-popup').isVisible());
   assert.equal(await page.locator('.leaflet-gfmPixels-pane').evaluate(e=>e.style.pointerEvents),'none');
   await page.locator('#hydro-warning-list details').first().waitFor();
   assert.ok(await page.locator('#hydro-warning-list details').count()>0);
   await page.evaluate(()=>state.map.setView([50.44,16.65],12));
   await page.locator('#gfm-group').evaluate(e=>e.scrollIntoView());
   await page.screenshot({path:`tmp/browser-evidence/gfm/${name}.png`,fullPage:true});
   await page.locator('#layer-panel').evaluate(e=>e.open=false);
   await page.screenshot({path:`tmp/browser-evidence/gfm/${name}-map.png`,fullPage:true});
   await page.locator('#layer-panel').evaluate(e=>e.open=true);
   let release;delay=new Promise(r=>release=r);
   const next=search.items.find(i=>i.id!==synthetic.product.id).id;
   await page.locator('#gfm-observation').selectOption(next);await flush();
   await page.locator('#gfm-observation').selectOption(synthetic.product.id);
   await page.waitForFunction(()=>!!document.querySelector('.leaflet-gfmPixels-pane img'));
   release();await flush();assert.match(await page.locator('#gfm-detail').textContent(),new RegExp(synthetic.product.id));
   delay=new Promise(r=>release=r);await page.locator('#gfm-observation').selectOption(next);await flush();
   await page.locator('#gfm-enabled').uncheck();release();await flush();await flush();
   assert.equal(await page.locator('.leaflet-gfmPixels-pane img').count(),0);
   assert.match(await page.locator('#gfm-status').textContent(),/wyłączona/);
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }finally{if(browser)await browser.close();await app.stop();}
 });
}

for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
 test(`GFM auto ${name}: Poland, native geometry, new data, disable`,{timeout:45000},async()=>{
  const app=await server();let browser;
  try{
   browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport});
    await setTestTheme(page);
   const errors=[],requestedBoxes=[];page.on('pageerror',e=>errors.push(e.message));let polls=0,revision=1,release=null;
   const product={id:'test-auto',observed_at:new Date().toISOString(),processed_at:new Date().toISOString(),
    fetched_at:new Date().toISOString(),source_url:'https://stac.eodc.eu/api/v1/collections/GFM/items/test-auto',
    version:'synthetic UI fixture',attribution:'Contains modified Copernicus Emergency Management Service information [2026]'};
   const properties={product,pixels:1,flags:[0],likelihood:[90]};
   const point={type:'Feature',geometry:{type:'Point',coordinates:[16.65,50.44]},properties};
   const pixel={type:'Feature',geometry:{type:'Polygon',coordinates:[[[16.65,50.44],[16.65028,50.44],[16.65028,50.44018],[16.65,50.44018],[16.65,50.44]]]},properties};
   await page.route('**/api/gfm/monitor*',async route=>{
    polls++;if(release)await release;
    const query=new URL(route.request().url()).searchParams;requestedBoxes.push(query.get('bbox'));
    const detail=query.has('bbox');
    await route.fulfill({json:{enabled:true,status:'ready',checked_at:new Date().toISOString(),revision,
     products:1,processed:1,pixels:revision===1?1:0,clusters:revision===1?[point]:[],
     features:detail&&revision===1?[pixel]:[],poll_after_seconds:3}});
   });
   await page.goto(app.url);await page.locator('.province-card').first().waitFor();
   await page.waitForFunction(()=>state.geometries.has('PL')&&document.querySelector('#province').options.length>1&&!state.map._animatingZoom);assert.equal(polls,0);
   await page.locator('#province').selectOption('02');
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#gfm-group').evaluate(e=>e.open=true);
   await page.locator('#gfm-enabled').check();assert.equal(await page.locator('#gfm-mode').inputValue(),'auto');
   await page.waitForFunction(()=>document.querySelector('#gfm-status').textContent.includes('Przetworzono 1/1'));
   assert.ok(polls>=1);assert.equal(await page.locator('#gfm-manual').isVisible(),false);
   await page.evaluate(()=>state.map.setView([50.44,16.65],13,{animate:false}));
   await page.waitForFunction(()=>{const pane=document.querySelector('.leaflet-gfmDetections-pane');return !!pane?.querySelector('canvas');});
   await page.waitForFunction(()=>{let found=false;state.map.eachLayer(g=>{if(g.eachLayer)g.eachLayer(l=>{if(l.options?.pane==='gfmDetections'&&l.feature?.geometry.type==='Polygon')found=true;});});return found;},{},{timeout:10000});
   const box=requestedBoxes.at(-1).split(',').map(Number);assert.ok(box[2]-box[0]<.5&&box[3]-box[1]<.5,'Regional detail keeps the small visible viewport');assert.ok(requestedBoxes[0],'Regional overview includes bbox');
   await page.locator('#layer-panel').evaluate(e=>e.open=false);
   await page.screenshot({path:`tmp/browser-evidence/gfm/auto-${name}.png`,fullPage:true});
   revision=2;
   await page.waitForFunction(()=>document.querySelector('#gfm-status').textContent.includes('Brak wykryć'),{},{timeout:8000});
   assert.equal(await page.evaluate(()=>{let n=0;state.map.eachLayer(g=>{if(g.eachLayer)g.eachLayer(l=>{if(l.options?.pane==='gfmDetections'&&l.feature)n++;});});return n;}),0);
   revision=1;let finish;release=new Promise(r=>finish=r);
   const before=polls;await page.waitForFunction(()=>true);await page.waitForTimeout(3300);assert.ok(polls>before);
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#gfm-enabled').uncheck();finish();await flush();
   const stopped=polls;await page.waitForTimeout(3300);assert.equal(polls,stopped);
   assert.match(await page.locator('#gfm-status').textContent(),/wyłączona/);assert.deepEqual(errors,[]);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }finally{if(browser)await browser.close();await app.stop();}
 });
}
