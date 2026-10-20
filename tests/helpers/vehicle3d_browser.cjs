// Real Cesium/WebGL + Leaflet, synthetic aircraft feed, network-forbidden DEMO backend.
// NODE_PATH=/path/to/node_modules node --test tests/aircraft3d_browser.cjs
'use strict';
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{once}=require('node:events');
const net=require('node:net'),path=require('node:path'),fs=require('node:fs');
const {chromium}=require('playwright');
const {PNG}=require('pngjs');
const root=path.resolve(__dirname,'../..');

async function server(){
  const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
  const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
  const child=spawn(path.join(root,'.venv/bin/python'),['-u','-c',`
import tempfile
from pathlib import Path
import httpx,uvicorn
from wici.app import create_app
from wici.config import Config
def forbidden(request):
    raise AssertionError('External network forbidden: '+str(request.url))
with tempfile.TemporaryDirectory(prefix='wici-aircraft3d-browser-') as directory:
    client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    app=create_app(demo=True,root=Path(directory),config=Config(port=${port}),client=client)
    uvicorn.run(app,host='127.0.0.1',port=${port},log_level='error')
`],{cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stdout.on('data',b=>logs+=b);child.stderr.on('data',b=>logs+=b);
  const url=`http://127.0.0.1:${port}`;
  try{
    for(let i=0;i<200;i++){
      if(child.exitCode!==null)throw Error(logs);
      try{if((await fetch(url+'/api/health')).ok)return{url,logs:()=>logs,async stop(){const ended=once(child,'exit');child.kill('SIGTERM');await ended;}};}catch{}
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    throw Error('DEMO startup timed out: '+logs);
  }catch(error){child.kill('SIGTERM');throw error;}
}
function aircraft(at=Date.now()-18000,overrides={}){
  return{hex:'48abcd',id:'TEST3D',registration:'SP-TEST',type_code:'E75S',military:false,
    latitude:52.22,longitude:20.95,altitude_m:8500,speed_kmh:720,track:90,
    position_at:new Date(at).toISOString(),...overrides};
}
const snapshot=items=>({items,stale:false,status:'ready',message:'DANE SYNTETYCZNE — test 3D',refresh_seconds:10});
const tile=new PNG({width:256,height:256});
for(let i=0;i<tile.data.length;i+=4){tile.data[i]=80;tile.data[i+1]=110;tile.data[i+2]=90;tile.data[i+3]=255;}
const syntheticTile=PNG.sync.write(tile);
function bus(at=Date.now()-18000,overrides={}){
  return{id:'szczecin:test3d',line:'75',vehicle_number:'TEST3D',model:'Solaris Urbino 12',
    operator:'Operator syntetyczny',headsign:'Dworzec testowy',latitude:53.4285,longitude:14.5528,
    speed_kmh:36,bearing:90,delay_seconds:0,low_floor:true,position_at:new Date(at).toISOString(),...overrides};
}
const busSnapshot=items=>({...snapshot(items),enabled:true});
async function environment({kind='aircraft',viewport={width:1440,height:1000},theme='light',noWebgl=false,holdVendor=false,liveMapPolicy=false,name}={}){
  const isBus=kind==='bus',evidence=path.join(root,`tmp/${isBus?'buses':'aircraft'}3d-evidence`);
  fs.mkdirSync(evidence,{recursive:true});
  const app=await server();
  let browser,releaseVendor,enteredVendor;
  try{
  browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport,isMobile:viewport.width<600,hasTouch:viewport.width<600});
  page.setDefaultTimeout(20000);
  const observations={errors:[],consoleErrors:[],external:[],tiles:[],vendor:[],aircraftReads:0,aircraftTimestamps:[],busReads:0,busCities:[],busTimestamps:[],models:[],failedRequests:[],renderChecks:[]};
  const feed={live:false,body:isBus?busSnapshot([bus()]):snapshot([aircraft()]),fail:false,aircraftBody:snapshot([aircraft()])};
  const vendorHeld=holdVendor?new Promise(resolve=>releaseVendor=resolve):null;
  const vendorEntered=holdVendor?new Promise(resolve=>enteredVendor=resolve):null;
  page.on('pageerror',error=>observations.errors.push(error.stack||error.message));
  page.on('console',message=>{if(message.type()==='error')observations.consoleErrors.push(message.text());});
  page.on('requestfailed',request=>observations.failedRequests.push({url:request.url(),failure:request.failure()?.errorText}));
  await page.addInitScript(({theme,noWebgl})=>{
    localStorage.setItem('wici.ui.theme.v1',theme);
    window.__csp=[];window.__vehicleViewers=[];window.__aircraftViewers=window.__vehicleViewers;
    window.__busFetchCallers=[];const read=window.fetch;
    window.fetch=function(input,...args){
      if(String(input).startsWith('/api/buses'))window.__busFetchCallers.push(new Error().stack);
      return read.call(this,input,...args);
    };
    document.addEventListener('securitypolicyviolation',event=>window.__csp.push({directive:event.violatedDirective,blocked:event.blockedURI,source:event.sourceFile,line:event.lineNumber,column:event.columnNumber}));
    // Preserve production scheduling; shorten only the two ten-second feed refreshes.
    const schedule=window.setTimeout;
    window.setTimeout=(callback,delay,...args)=>schedule(callback,delay===10000?400:delay,...args);
    let engine;
    Object.defineProperty(window,'Cesium',{configurable:true,get:()=>engine,set(value){
      const Viewer=new Proxy(value.Viewer,{construct(target,args){const viewer=Reflect.construct(target,args);window.__aircraftViewers.push(viewer);return viewer;}});
      engine=new Proxy(value,{get(target,key,receiver){return key==='Viewer'?Viewer:Reflect.get(target,key,receiver);}});
    }});
    if(noWebgl){
      const getContext=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(kind,...args){return /^(webgl2?|experimental-webgl)$/.test(kind)?null:getContext.call(this,kind,...args);};
    }
  },{theme,noWebgl});
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==app.url){
      if(liveMapPolicy&&url.origin==='https://tile.openstreetmap.org'){
        observations.tiles.push(url.href);return route.fulfill({contentType:'image/png',body:syntheticTile});
      }
      observations.external.push(url.href);return route.abort();
    }
    if(url.pathname==='/'&&liveMapPolicy){
      const response=await route.fetch(),headers=response.headers();
      // Match LIVE's map allowance while retaining the isolated DEMO backend and all script/worker policy.
      headers['content-security-policy']=headers['content-security-policy']
        .replace("connect-src 'self'","connect-src 'self' https://tile.openstreetmap.org")
        .replace("img-src 'self' data:","img-src 'self' data: https://tile.openstreetmap.org");
      return route.fulfill({response,headers});
    }
    if(url.pathname==='/api/health'&&feed.live){const response=await route.fetch();return route.fulfill({json:{...await response.json(),mode:'live'}});}
    if(url.pathname==='/api/aircraft'){
      observations.aircraftReads++;
      const body=isBus?feed.aircraftBody:feed.body;
      observations.aircraftTimestamps.push(body.items[0]?.position_at||null);
      return !isBus&&feed.fail?route.fulfill({status:503,json:{detail:'Syntetyczna awaria źródła'}}):route.fulfill({json:body});
    }
    if(url.pathname==='/api/buses'){
      observations.busReads++;observations.busCities.push(url.searchParams.get('city'));
      observations.busTimestamps.push(feed.body.items[0]?.position_at||null);
      return isBus&&feed.fail?route.fulfill({status:503,json:{detail:'Syntetyczna awaria źródła'}}):route.fulfill({json:isBus?feed.body:busSnapshot([])});
    }
    if(url.pathname.startsWith('/static/models/'))observations.models.push(url.pathname);
    if(url.pathname.startsWith('/static/vendor/cesium/')){
      observations.vendor.push(url.pathname);
      if(url.pathname.endsWith('/Cesium.js')&&vendorHeld){enteredVendor();await vendorHeld;}
    }
    return route.continue();
  });
  await page.goto(app.url);
  await page.locator('.province-card').first().waitFor();
  await page.waitForFunction(()=>state.map&&!state.map._animatingZoom);
  // The real backend stays DEMO; only browser responses use a synthetic LIVE contract.
  feed.live=true;
  await page.evaluate(async()=>{document.querySelector('#osm-enabled').checked=false;await loadHealth();});
  await page.locator('#layer-panel').evaluate(element=>element.open=true);
  await page.locator('.layer-group').filter({has:page.locator(isBus?'#buses-enabled':'#aircraft-enabled')}).evaluate(element=>element.open=true);
  await page.locator(isBus?'#buses-enabled':'#aircraft-enabled').check();
  await page.locator(isBus?'.buses-marker':'.aircraft-marker').first().waitFor();
  await page.locator('#layer-panel').evaluate(element=>element.open=false);
  await page.evaluate(isBus=>state.map.setView(isBus?[53.4285,14.5528]:[52.22,20.95],7,{animate:false}),isBus);
  const button=page.getByRole('button',{name:'Podążaj w 3D',exact:true});
  async function open(beforeFollow){
    await page.locator(isBus?'.buses-marker':'.aircraft-marker').first().click();
    // Leaflet retains a closing popup for its short fade animation after a view change.
    await page.waitForFunction(()=>[...document.querySelectorAll('.leaflet-popup button')].filter(button=>button.textContent==='Podążaj w 3D').length===1);
    await beforeFollow?.();await button.click();await page.locator('#aircraft3d-dialog').waitFor({state:'visible'});
  }
  async function rendered(){
    try{
      await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='error'||(window.__aircraftViewers.length&&document.querySelector('#aircraft3d-scene canvas')&&document.querySelector('#aircraft3d-telemetry').textContent));
      assert.notEqual(await page.locator('#aircraft3d-dialog').getAttribute('data-state'),'error',await page.locator('#aircraft3d-status').textContent());
      await page.waitForFunction(()=>{const view=window.__aircraftViewers.at(-1);return view.dataSources.length>0&&view.entities.values.length>=9&&view.scene.globe.tilesLoaded;});
      const png=PNG.sync.read(await page.locator('#aircraft3d-scene').screenshot());let total=0,groundPixels=0;
      for(let y=20;y<png.height-40;y+=8)for(let x=20;x<png.width-20;x+=8){
        const index=(y*png.width+x)*4,r=png.data[index],g=png.data[index+1],b=png.data[index+2];
        total++;if(g>r+8&&g>25&&b>20)groundPixels++;
      }
      observations.renderChecks.push({width:png.width,height:png.height,groundFraction:groundPixels/total});
      assert.ok(groundPixels/total>.2,'Real globe ground must render; a blank or black canvas cannot pass');
    }
    catch(error){
      await page.screenshot({path:path.join(evidence,'render-failure.png'),fullPage:true});
      const detail=await page.evaluate(()=>({state:document.querySelector('#aircraft3d-dialog').dataset.state,status:document.querySelector('#aircraft3d-status').textContent,viewers:window.__aircraftViewers.length,engine:Boolean(window.Cesium),csp:window.__csp}));
      fs.writeFileSync(path.join(evidence,'render-failure.json'),JSON.stringify({detail,observations},null,2));
      throw Error(error.message+' '+JSON.stringify({detail,observations}));
    }
    assert.notEqual(await page.locator('#aircraft3d-dialog').getAttribute('data-state'),'error',await page.locator('#aircraft3d-status').textContent());
  }
  async function next(body,{fail=false}={}){
    const key=isBus?'busReads':'aircraftReads',before=observations[key];feed.body=body;feed.fail=fail;
    await new Promise((resolve,reject)=>{
      const started=Date.now();const check=()=>observations[key]>before?resolve():Date.now()-started>10000?reject(Error(`${kind} poll did not run`)):setTimeout(check,20);check();
    });
  }
  async function saveRuntime(){
    const csp=await page.evaluate(()=>window.__csp);
    fs.writeFileSync(path.join(evidence,`${name||`${viewport.width}-${theme}`}-runtime.json`),JSON.stringify({observations,csp},null,2));
    return csp;
  }
  async function clean(){
    const csp=await saveRuntime();
    assert.deepEqual(observations.errors,[]);assert.deepEqual(observations.external,[]);assert.deepEqual(csp,[]);assert.doesNotMatch(app.logs(),/External network forbidden/);
  }
  return{app,browser,page,feed,observations,button,open,rendered,next,clean,saveRuntime,vendorEntered,releaseVendor,evidence,
    async stop(){releaseVendor?.();await browser.close();await app.stop();}};
  }catch(error){releaseVendor?.();if(browser)await browser.close();await app.stop();throw error;}
}
const camera=page=>page.evaluate(()=>{const view=window.__aircraftViewers.at(-1),p=view.camera.positionWC;return{x:p.x,y:p.y,z:p.z,heading:view.camera.heading,pitch:view.camera.pitch};});
const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);

module.exports={environment,aircraft,snapshot,bus,busSnapshot,camera,distance,root};
