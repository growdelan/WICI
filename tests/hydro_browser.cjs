// Full application + bundled Leaflet regression. Starts its own isolated offline demo server.
// NODE_PATH=/path/to/node_modules node --test tests/hydro_browser.cjs
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
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-hydro-regression-') as root:
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
const initial=Date.parse('2026-10-17T06:00:00Z');
function snapshot(){
 const measurement={value:340,unit:'cm',observed_at:'2026-10-17T03:01:00Z'};
 return {enabled:true,status:'ready',fetched_at:new Date(initial).toISOString(),stale:false,
  source_url:'https://danepubliczne.imgw.pl/api/data/hydro/',items:[{id:'regression',name:'Wodowskaz regresyjny',
   river:'Wisła',province:'mazowieckie',latitude:52.2,longitude:21.1,warning_level_cm:300,alarm_level_cm:340,
   measurements:{water_level:measurement,discharge:measurement,temperature:measurement}}]};
}
async function markerState(page){
 return page.evaluate(()=>{
  const marker=window.hydroMarker,popup=marker.getPopup();
  return {same:state.map.hasLayer(marker),open:marker.isPopupOpen(),color:marker.options.color,
   content:popup.getElement()?.textContent||'',identity:popup===window.originalHydroPopup};
 });
}

test('main reload scheduler, real Leaflet hit ordering and open hydrology popup refresh', {timeout:45000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await setTestTheme(page);
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  let healthReads=0,stationReads=0,reply=snapshot(),fail=false;
  page.on('request',r=>{if(new URL(r.url()).pathname==='/api/health')healthReads++;});
  await page.clock.install({time:new Date(initial)});await page.clock.pauseAt(new Date(initial+1000));
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());
   if(url.origin!==app.url){external.push(url.href);return route.abort();}
   if(url.pathname==='/api/hydro'){
    if(url.searchParams.get('kind')==='stations'){
     stationReads++;return fail?route.abort():route.fulfill({json:reply});
    }
    return route.fulfill({json:{enabled:true,status:'ready',fetched_at:new Date(initial).toISOString(),items:[{
     id:'warning',event:'Ostrzeżenie regresyjne',severity:1,valid_from:'2026-10-17T05:00:00Z',
     valid_until:'2026-10-17T06:01:00Z',published_at:'2026-10-17T05:00:00Z',description:'Treść',areas:[]}]}});
   }
   return route.continue();
  });
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();
  assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
  assert.equal(stationReads,0);
  await page.locator('#layer-panel > summary').click();
  await page.locator('.layer-group').filter({has:page.locator('#hydro-stations')}).locator(':scope > summary').click();
  await page.locator('#hydro-stations').check();await page.locator('#hydro-warnings').check();
  await page.locator('#hydro-station option[value="regression"]').waitFor({state:'attached'});
  await page.locator('#hydro-warning-list summary').waitFor({state:'attached'});
  await page.waitForFunction(()=>state.map.getPane('hydroStations')?.querySelector('path'));
  // Use the actual publication redraw path, including bringing a publication to the front.
  const click=await page.evaluate(()=>{
   state.map.setView([52.2,21.1],9,{animate:false});renderMap();
   for(const entry of state.layers)entry.layer.bringToFront();
   let marker;state.map.eachLayer(l=>{if(l instanceof L.CircleMarker&&l.options.pane==='hydroStations')marker=l;});
   if(!marker)throw new Error('No hydrology marker');window.hydroMarker=marker;window.originalHydroPopup=marker.getPopup();
   const p=state.map.latLngToContainerPoint(marker.getLatLng()),r=state.map.getContainer().getBoundingClientRect();
   const x=r.left+p.x,y=r.top+p.y;
   return {x,y,topIsMarker:document.elementFromPoint(x,y)===marker.getElement(),publications:state.layers.length};
  });
  assert.ok(click.publications>0);assert.equal(click.topIsMarker,true);
  await page.mouse.click(click.x,click.y);assert.equal((await markerState(page)).open,true);
  // Real app.js registered reload's interval before hydrology was enabled. Both now run normally.
  await page.clock.runFor(120000);
  await page.waitForFunction(()=>document.getElementById('hydro-stations-status').textContent.includes('1 bez aktualnego'));
  assert.ok(healthReads>=3,'main app reload ran at least twice');assert.equal(stationReads,1);
  let stateNow=await markerState(page);assert.equal(stateNow.same,true);assert.equal(stateNow.identity,true);
  assert.equal(stateNow.open,true);assert.equal(stateNow.color,'#6b7780');assert.match(stateNow.content,/NIEAKTUALNY POMIAR/);
  assert.match(await page.locator('#hydro-warning-list').textContent(),/Ważność upłynęła/);
  reply=snapshot();reply.fetched_at='2026-10-17T06:05:00Z';reply.items[0].measurements.water_level={value:410,unit:'cm',observed_at:reply.fetched_at};
  await page.clock.runFor(181000);await page.waitForFunction(()=>window.hydroMarker.hydroItem.measurements.water_level.value===410);
  stateNow=await markerState(page);assert.equal(stateNow.same,true);assert.equal(stateNow.identity,true);assert.equal(stateNow.open,true);assert.match(stateNow.content,/410 cm/);
  assert.equal(stationReads,2);
  // Updating a previously opened but now closed popup must keep its content factory live.
  await page.evaluate(()=>state.map.closePopup());
  reply.items[0].measurements.water_level={value:420,unit:'cm',observed_at:'2026-10-17T06:10:00Z'};
  await page.clock.runFor(300000);
  await page.waitForFunction(()=>window.hydroMarker.hydroItem.measurements.water_level.value===420);
  await page.evaluate(()=>window.hydroMarker.openPopup());
  stateNow=await markerState(page);assert.equal(stateNow.identity,true);assert.match(stateNow.content,/420 cm/);
  // Transport failure retains the same popup, with the error disclosed in its content.
  fail=true;await page.clock.runFor(300000);
  await page.waitForFunction(()=>window.hydroMarker.getPopup().getElement()?.textContent.includes('aktualność niepotwierdzona'));
  stateNow=await markerState(page);assert.equal(stateNow.open,true);assert.equal(stateNow.identity,true);assert.equal(stateNow.color,'#6b7780');
  fail=false;reply={...reply,items:[]};await page.clock.runFor(300000);
  await page.waitForFunction(()=>!state.map.hasLayer(window.hydroMarker));assert.equal((await markerState(page)).open,false);
  if(!await page.locator('#hydro-stations').isVisible())await page.locator('#layer-panel > summary').click();
  await page.locator('#hydro-stations').uncheck();await page.locator('#hydro-warnings').uncheck();
  // Leaflet removes a fading popup after 200ms; the browser clock is paused.
  await page.clock.runFor(250);
  assert.equal(await page.locator('.leaflet-popup').count(),0);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});
