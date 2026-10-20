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
const initial=Date.parse('2026-10-17T06:30:00Z');
test('real map, selection, manual state, hourly history, popup preservation and mobile', {timeout:60000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await setTestTheme(page);
  const errors=[],external=[],reads=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install({time:new Date(initial)});await page.clock.pauseAt(new Date(initial+1000));
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());if(url.origin!==app.url){external.push(url.href);return route.abort();}
   if(url.pathname==='/api/gios')reads.push(url.search);return route.continue();
  });
  await page.addInitScript(()=>{
   window.giosIndexReads=[];const original=window.fetch;
   window.fetch=function(input,options){
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.pathname==='/api/gios'&&url.searchParams.get('kind')==='index'){
     const id=Number(url.searchParams.get('id'));let visible=false;
     state.map.eachLayer(l=>{if(l.giosItem?.id===id)visible=state.map.getBounds().contains(l.getLatLng());});
     window.giosIndexReads.push({id,visible,enabled:document.getElementById('gios-enabled').checked&&!document.hidden&&state.view==='situation'});
    }
    return original.call(this,input,options);
   };
  });
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();assert.equal(reads.length,0);
  assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
  await page.locator('#layer-panel > summary').click();
  await page.locator('.layer-group').filter({has:page.locator('#gios-enabled')}).locator(':scope > summary').click();
  await page.locator('#gios-enabled').check();
  await page.locator('#gios-station option[value="9001"]').waitFor({state:'attached'});
  assert.equal(reads.length,1);await page.locator('#gios-station').selectOption('9001');
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('Stanowisko manualne'));
  await page.locator('#gios-sensor').selectOption('9101');
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('12.5 µg/m³'));
  await page.locator('#gios-history > summary').click();assert.ok(await page.locator('#gios-history tr').count()>24);
  assert.match(await page.locator('#gios-detail').textContent(),/Oficjalny polski indeks jakości powietrza/);
  await page.evaluate(()=>{
   let m;state.map.eachLayer(l=>{if(l instanceof L.CircleMarker&&l.options.pane==='giosStations'&&l.giosItem.id===9001)m=l;});
   if(!m)throw new Error('No GIOS marker');window.giosMarker=m;window.giosPopup=m.getPopup();
  });
  await page.clock.runFor(1000);
  const point=await page.evaluate(()=>{
   const m=window.giosMarker;state.map.stop();state.map.setView(m.getLatLng(),10,{animate:false});m.bringToFront();
   const p=state.map.latLngToContainerPoint(m.getLatLng()),r=state.map.getContainer().getBoundingClientRect();
   return {x:r.left+p.x,y:r.top+p.y,hit:document.elementFromPoint(r.left+p.x,r.top+p.y)===m.getElement()};
  });
  assert.equal(point.hit,true);await page.mouse.click(point.x,point.y);
  await page.waitForFunction(()=>window.giosMarker.isPopupOpen());
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('Stanowisko manualne'));
  if(!await page.locator('#gios-sensor').isVisible())await page.locator('#layer-panel > summary').click();
  await page.locator('#gios-sensor').selectOption('9101');
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('12.5 µg/m³'));
  await page.clock.runFor(1200);
  await page.waitForFunction(()=>window.giosMarker.options.fillColor==='#b0dd10');
  assert.equal(await page.locator('#gios-legend-items > span').count(),7);
  assert.match(await page.locator('#gios-legend').textContent(),/Bardzo dobry.*Dobry.*Umiarkowany.*Dostateczny.*Zły.*Bardzo zły/s);
  // Refresh clocks update the existing marker and popup, preserving the expanded table.
  await page.clock.runFor(301000);
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('12.5 µg/m³'));
  assert.equal(await page.evaluate(()=>window.giosMarker.isPopupOpen()&&window.giosPopup===window.giosMarker.getPopup()),true);
  assert.equal(await page.locator('#gios-history').evaluate(e=>e.open),true);
  await page.evaluate(()=>state.map.closePopup());
  await page.locator('#gios-parameter').selectOption('CO');
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('CO: brak parametru na stacji'));
  await page.locator('#gios-parameter').selectOption('PM10');
  await page.locator('#gios-sensor').selectOption('9101');
  await page.waitForFunction(()=>document.getElementById('gios-detail').textContent.includes('12.5 µg/m³'));
  await page.locator('#gios-detail').scrollIntoViewIfNeeded();await page.screenshot({path:`tmp/gios-desktop${theme==='dark'?'-dark':''}.png`,fullPage:true});
  await page.locator('#gios-legend').scrollIntoViewIfNeeded();await page.screenshot({path:`tmp/gios-legend-desktop${theme==='dark'?'-dark':''}.png`,fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.locator('#gios-enabled').scrollIntoViewIfNeeded();
  assert.ok(await page.locator('#gios-station').isVisible());assert.ok(await page.locator('#gios-parameter').isVisible());
  await page.locator('#gios-detail').scrollIntoViewIfNeeded();await page.screenshot({path:`tmp/gios-mobile${theme==='dark'?'-dark':''}.png`,fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  await page.locator('#gios-legend').scrollIntoViewIfNeeded();await page.screenshot({path:`tmp/gios-legend-mobile${theme==='dark'?'-dark':''}.png`,fullPage:true});
  await page.locator('#gios-enabled').uncheck();const count=reads.length;await page.clock.runFor(600000);
  assert.equal(reads.length,count);assert.equal(await page.evaluate(()=>state.map.hasLayer(window.giosMarker)),false);
  const indexReads=await page.evaluate(()=>window.giosIndexReads);
  assert.ok(indexReads.length>0);assert.ok(indexReads.every(r=>r.visible&&r.enabled),JSON.stringify(indexReads));
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});
