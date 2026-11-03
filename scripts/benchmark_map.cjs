// Offline browser benchmark: synthetic data, temporary backend, no provider requests.
// node scripts/benchmark_map.cjs (requires Playwright and its Chromium).
// WICI_CHROMIUM_EXECUTABLE optionally selects an existing Chromium executable.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const net = require('node:net');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
(async () => {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(r => socket.close(r));
  const server = spawn(root+'/.venv/bin/python', ['-u', '-c', `
import tempfile
from pathlib import Path
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-map-benchmark-') as directory:
    uvicorn.run(create_app(demo=True,root=Path(directory),config=Config(port=${port})),host='127.0.0.1',port=${port},log_level='error')
`], {cwd:root, stdio:['ignore','pipe','pipe']});
  let logs=''; server.stderr.on('data', x=>logs+=x);
  let browser;
  const url = `http://127.0.0.1:${port}`;
  try {
    for (let i=0;i<200;i++) {if(server.exitCode!==null)throw Error(logs); try {if((await fetch(url+'/api/health')).ok)break;}catch{} await new Promise(r=>setTimeout(r,50));}
    browser=await chromium.launch({headless:true,...(process.env.WICI_CHROMIUM_EXECUTABLE ? {executablePath:process.env.WICI_CHROMIUM_EXECUTABLE} : {})});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{window.__intervals=[];const original=window.setInterval;window.setInterval=(fn,ms,...args)=>{const id=original(fn,ms,...args);__intervals.push({fn,ms,id});return id;};});
    await page.route('**/*',route=>{
      const request=route.request(), target=new URL(request.url());
      if(target.origin!==url)return route.abort();
      if(target.pathname==='/api/buses'){
        const now=new Date().toISOString();
        const items=Array.from({length:500},(_,i)=>({id:`szczecin:${i}`,line:'75',headsign:'Syntetyczny autobus',latitude:52.20+(i%25)*0.0005,longitude:21.00+Math.floor(i/25)*0.0005,position_at:now,heading:90,speed_kmh:20}));
        return route.fulfill({json:{items,status:'ready',enabled:true,stale:false,refresh_seconds:10}});
      }
      return route.continue();
    });
    await page.goto(url);
    await page.waitForFunction(()=>typeof state!=='undefined'&&state.map&&!document.getElementById('refresh').disabled);
    await page.locator('[data-view="analysis"]').click();
    await page.waitForFunction(()=>WiciWorkspace.getData()?.total>0&&!WiciWorkspace.getState().loading);
    const map=await page.evaluate(async()=>{
      const count=1000, now=new Date().toISOString(), measure={observed_at:now,value:200,unit:'cm',metric:'water_level',quality:'valid',thresholds:{warning_level_cm:300,alarm_level_cm:400}};
      const points=Array.from({length:count},(_,i)=>({ref:`hydro_station:imgw:perf-${i}`,type:'hydro_station',label:`Stacja ${i}`,latitude:52.15+(i%40)*.002,longitude:20.9+Math.floor(i/40)*.003,measurement:measure,metadata:{}}));
      const data={as_of:now,map:{points,areas:[],aggregates:[]}}, uiState={...WiciWorkspace.getState(),query:{time:{mode:'live'}},detailOpen:false};
      const view=WiciWorkspaceMap({map:state.map,geometries:state.geometries,select(){},narrow(){}});view.setActive(true);
      const counters={created:0,styles:0,tooltips:0,removed:0};
      const circle=L.circleMarker; L.circleMarker=(...args)=>{counters.created++;const marker=circle(...args),style=marker.setStyle,tooltip=marker.setTooltipContent;marker.setStyle=function(...args){counters.styles++;return style.apply(this,args);};marker.setTooltipContent=function(...args){counters.tooltips++;return tooltip.apply(this,args);};return marker;};
      const remove=state.map.removeLayer;state.map.removeLayer=function(...args){counters.removed++;return remove.apply(this,args);};
      const sample=async(fn,runs)=>{const times=[];for(let i=0;i<runs;i++){await new Promise(requestAnimationFrame);const t=performance.now();fn();void state.map.getContainer().offsetHeight;times.push(performance.now()-t);}times.sort((a,b)=>a-b);return {median_ms:+times[Math.floor(times.length/2)].toFixed(2),p95_ms:+times[Math.min(times.length-1,Math.floor(times.length*.95))].toFixed(2)};};
      const initial=await sample(()=>view.render(data,uiState),1);for(const k in counters)counters[k]=0;
      const unchanged=await sample(()=>view.render(data,uiState),20), unchangedOps={...counters};for(const k in counters)counters[k]=0;
      const refreshed=await sample(()=>view.render({...data,map:{...data.map,points:[...points]}},uiState),10), refreshOps={...counters};
      L.circleMarker=circle;state.map.removeLayer=remove;view.destroy();
      return {points:count,initial,unchanged,unchangedOps,refreshed,refreshOps};
    });
    await page.locator('[data-view="situation"]').click();
    await page.evaluate(()=>{WiciRegion.select('14',{fit:false});const enabled=document.getElementById('buses-enabled');enabled.checked=true;WiciBuses.sync({visible:true,health:{mode:'live'}});});
    await page.waitForFunction(()=>document.querySelectorAll('.buses-marker').length>=500);
    const bus=await page.evaluate(async()=>{
      const timer=__intervals.filter(x=>x.ms===1000&&x.fn.name==='render').at(-1);if(!timer)throw Error('Missing bus timer');
      clearInterval(timer.id);let icons=0,positions=0;const icon=L.Marker.prototype.setIcon,position=L.Marker.prototype.setLatLng;
      L.Marker.prototype.setIcon=function(...args){icons++;return icon.apply(this,args);};L.Marker.prototype.setLatLng=function(...args){positions++;return position.apply(this,args);};
      const times=[];for(let i=0;i<10;i++){await new Promise(requestAnimationFrame);const t=performance.now();timer.fn();void state.map.getContainer().offsetHeight;times.push(performance.now()-t);}times.sort((a,b)=>a-b);
      L.Marker.prototype.setIcon=icon;L.Marker.prototype.setLatLng=position;
      document.getElementById('buses-enabled').checked=false;WiciBuses.sync();
      return {buses:500,ticks:10,icons,positions,median_ms:+times[5].toFixed(2),p95_ms:+times[9].toFixed(2)};
    });
    console.log(JSON.stringify({scope:'Synthetic offline DOM update benchmark; timings are not GPU FPS.',browser:browser.version(),map,bus,errors},null,2));
  } finally {if(browser)await browser.close();if(server.exitCode===null){const done=once(server,'exit');server.kill('SIGTERM');await done;}}
})().catch(e=>{console.error(e);process.exitCode=1;});
