// Real API + SQLite + collector + Leaflet; synthetic feeds and blocked external network.
// NODE_PATH=/path/to/node_modules node --test tests/tracking_browser.cjs
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process'),{once}=require('node:events');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),evidence=path.join(root,'tmp/tracking-evidence');
fs.mkdirSync(evidence,{recursive:true});

async function server(){
  const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
  const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
  const child=spawn(path.join(root,'.venv/bin/python'),['tests/helpers/tracking_server.py',String(port)],
    {cwd:root,stdio:['ignore','pipe','pipe']});
  let logs='';child.stdout.on('data',b=>logs+=b);child.stderr.on('data',b=>logs+=b);
  const url=`http://127.0.0.1:${port}`;
  for(let i=0;i<200;i++){
    if(child.exitCode!==null)throw Error(logs);
    try{if((await fetch(url+'/api/health')).ok)return{url,logs:()=>logs,async stop(){
      const done=once(child,'exit');child.kill('SIGTERM');await done;
    }};}catch{}
    await new Promise(resolve=>setTimeout(resolve,50));
  }
  child.kill('SIGTERM');throw Error('Fixture startup timeout: '+logs);
}

test('tracks persist without a browser, seek three hours, preserve cursor and replay aircraft/ships on mobile',
  {timeout:90000},async()=>{
  const app=await server();let browser,page;
  const errors=[],external=[];
  try{
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin!==app.url){external.push(url.href);return route.abort();}
      if(url.pathname==='/api/health'){
        const response=await route.fetch();
        return route.fulfill({json:{...await response.json(),mode:'live'}});
      }
      return route.continue();
    });
    async function open(){
      page=await context.newPage();page.setDefaultTimeout(15000);
      page.on('pageerror',error=>errors.push(error.stack||error.message));
      await page.goto(app.url);
      await page.waitForFunction(()=>window.WiciRegion?.ready()&&window.WiciTracking);
      return page;
    }
    await open();
    const csrf=await page.evaluate(()=>state.health.csrf_token);
    const headers={'Origin':app.url,'X-CSRF-Token':csrf};
    async function data(id){return (await context.request.get(`${app.url}/api/tracks/${id}`)).json();}
    async function seed(id){
      const response=await context.request.post(`${app.url}/_test/history/${id}`,{headers});
      assert.equal(response.status(),200);
      const body=await response.json();
      await page.evaluate(()=>{WiciTracking.sync({visible:false});WiciTracking.sync({visible:true});});
      await page.waitForFunction(count=>document.getElementById('tracking-metrics').textContent.includes(String(count)),
        body.points.length);
      return body;
    }
    async function enable(id){
      await page.evaluate(id=>{const input=document.getElementById(id);input.checked=true;input.dispatchEvent(new Event('change'));},id);
    }
    await enable('aircraft-enabled');
    const originalColor=await page.locator('.aircraft-marker .aircraft-military')
      .evaluate(element=>getComputedStyle(element).color);
    assert.equal(originalColor,'rgb(180, 83, 9)');
    async function aircraftColor(){
      // A refresh replaces the marker DOM; read the current element and style atomically.
      const color=await page.waitForFunction(()=>{
        const element=document.querySelector('.tracking-object .aircraft-symbol');
        return element&&getComputedStyle(element).color;
      });
      return color.jsonValue();
    }
    await page.locator('.aircraft-marker').first().click();
    await page.getByRole('button',{name:'Śledź trasę',exact:true}).click();
    await page.waitForFunction(()=>document.getElementById('tracking-session').value);
    const aircraftId=await page.locator('#tracking-session').inputValue();
    assert.equal(await page.locator('.tracking-reticle').count(),1);
    assert.equal(await aircraftColor(),originalColor,'Starting tracking must preserve the military aircraft color');
    assert.notEqual(await page.locator('.tracking-reticle > i').first()
      .evaluate(element=>getComputedStyle(element).borderColor),originalColor,
      'The selection frame must keep its own state color');
    const history=await seed(aircraftId);
    assert.equal(history.track.military,true);
    assert.ok(history.points.length>800);
    const from=Date.parse(history.points[0].position_at),until=Date.parse(history.points.at(-1).position_at);
    assert.equal(until-from,3*3600000);
    async function seek(at){
      await page.locator('#tracking-timeline').fill(String(at));
      await page.locator('#tracking-timeline').dispatchEvent('input');
    }
    await seek(from+3600000);
    assert.equal(await page.locator('.tracking-history').count(),1);
    assert.equal(await aircraftColor(),originalColor,'History must preserve the aircraft classification color');
    const routeSize=await page.evaluate(()=>Object.values(state.map._layers)
      .find(layer=>layer instanceof L.Polyline&&layer.options.pane==='trackingRoutes').getLatLngs().flat().length);
    assert.ok(routeSize>1&&routeSize<history.points.length,'History must not draw future observations');
    const held=await page.locator('#tracking-timeline').inputValue();
    await page.evaluate(()=>{WiciTracking.sync({visible:false});WiciTracking.sync({visible:true});});
    await page.waitForTimeout(500);
    assert.equal(await page.locator('#tracking-timeline').inputValue(),held);
    await seek(from+90*60000);
    assert.match(await page.locator('#tracking-status').textContent(),/Przerwa w obserwacji/);
    await page.locator('#tracking-speed').selectOption('300');
    await page.locator('#tracking-play').click();
    await page.waitForFunction(value=>Number(document.getElementById('tracking-timeline').value)>value,
      from+90*60000);
    assert.equal(await aircraftColor(),originalColor,'Playback must preserve the military aircraft color');
    await page.locator('#tracking-play').click();
    assert.equal(await page.locator('#tracking-play').textContent(),'Odtwórz');
    await page.locator('#province').selectOption('02');
    assert.equal(await page.evaluate(()=>state.map.getPane('trackingCursor').style.clipPath),'');
    await page.locator('#tracking-fit').click();
    await page.screenshot({path:path.join(evidence,'desktop-history.png'),fullPage:true});
    await page.locator('#tracking-live').click();
    assert.equal(await page.locator('.tracking-history').count(),0);
    await enable('ships-enabled');
    await page.evaluate(()=>{const input=document.getElementById('aircraft-enabled');input.checked=false;input.dispatchEvent(new Event('change'));});
    const beforeClose=(await data(aircraftId)).points.length;
    await page.close();
    let background;
    for(let i=0;i<60;i++){
      background=await data(aircraftId);
      if(background.points.length>beforeClose)break;
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    assert.ok(background.points.length>beforeClose,'The backend must record with no browser page open');
    await open();
    await page.waitForFunction(id=>document.getElementById('tracking-session').value===id,aircraftId);
    assert.equal(await aircraftColor(),originalColor,'Reopening the page must restore the saved classification');
    await page.locator('#tracking-panel > summary').click();
    await page.locator('#tracking-stop').click();
    await page.waitForFunction(()=>document.getElementById('tracking-recording').textContent==='ZAPIS ZAKOŃCZONY');
    assert.equal((await data(aircraftId)).track.active,false);
    assert.equal(await aircraftColor(),originalColor,'An archived track must preserve the military aircraft color');
    assert.ok((await data(aircraftId)).points.length>800);
    await page.locator('#province').selectOption('');
    await enable('ships-enabled');
    await page.evaluate(()=>state.map.fitBounds([[54.5,17.5],[55.8,18.8]],{animate:false}));
    await page.locator('.ship-marker').first().click();
    await page.getByRole('button',{name:'Śledź trasę',exact:true}).click();
    await page.waitForFunction(id=>document.getElementById('tracking-session').value!==id,aircraftId);
    const shipId=await page.locator('#tracking-session').inputValue();
    assert.equal((await data(shipId)).track.kind,'ship');
    await seed(shipId);
    await page.setViewportSize({width:390,height:844});
    await page.evaluate(()=>document.documentElement.dataset.theme='dark');
    await page.locator('#tracking-panel').scrollIntoViewIfNeeded();
    await page.locator('#tracking-fit').click();
    await page.waitForTimeout(350);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const dimensions=await page.locator('#tracking-panel').boundingBox();
    assert.ok(dimensions.width<=390&&dimensions.height<400);
    const target=await page.locator('.tracking-reticle').boundingBox();
    const mapBounds=await page.locator('#map').boundingBox();
    fs.writeFileSync(path.join(evidence,'mobile-layout.json'),JSON.stringify({dimensions,target,mapBounds},null,2));
    assert.ok(target.y>=mapBounds.y&&target.x>=mapBounds.x&&target.x+target.width<=mapBounds.x+mapBounds.width,
      'The selected object must fit inside the mobile map');
    assert.ok(target.y+target.height<=dimensions.y,'The selected object must remain visible above the mobile dock');
    await page.screenshot({path:path.join(evidence,'mobile-ship.png'),fullPage:true});
    await page.locator('#tracking-stop').click();
    await page.waitForFunction(()=>document.getElementById('tracking-recording').textContent==='ZAPIS ZAKOŃCZONY');
    assert.equal((await data(shipId)).track.active,false);
    await page.getByRole('button',{name:'Wyjdź ze śledzenia',exact:true}).click();
    assert.equal(await page.locator('.tracking-reticle').count(),0);
    assert.equal(await page.locator('#tracking-session').inputValue(),'');
    assert.equal(await page.locator('#tracking-panel').evaluate(element=>element.open),false);
    await page.reload();
    await page.waitForFunction(()=>document.getElementById('tracking-session').options.length>1);
    assert.equal(await page.locator('.tracking-reticle').count(),0);
    assert.equal(await page.locator('#tracking-session').inputValue(),'');
    await page.locator('#tracking-heading').click();
    await page.locator('#tracking-session').selectOption(shipId);
    await page.locator('.tracking-reticle').waitFor();
    assert.ok((await data(shipId)).points.length>800);
    assert.deepEqual(errors,[]);
    assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify({aircraftId,shipId,
      historyPoints:history.points.length,backgroundPoints:background.points.length,errors,external},null,2));
  }finally{
    if(page&&!page.isClosed())await page.screenshot({path:path.join(evidence,'last-state.png'),fullPage:true}).catch(()=>{});
    if(browser)await browser.close();await app.stop();
    fs.writeFileSync(path.join(evidence,'server.log'),app.logs());
  }
});

test('all AIS classification colors survive tracking, history, playback, reload and stopping',
  {timeout:60000},async()=>{
  const app=await server();let browser,page;
  const errors=[],external=[],results=[];
  try{
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin!==app.url){external.push(url.href);return route.abort();}
      if(url.pathname==='/api/health'){
        const response=await route.fetch();
        return route.fulfill({json:{...await response.json(),mode:'live'}});
      }
      return route.continue();
    });
    page=await context.newPage();page.setDefaultTimeout(10000);
    page.on('pageerror',error=>errors.push(error.stack||error.message));
    await page.goto(app.url);
    await page.waitForFunction(()=>window.WiciRegion?.ready()&&window.WiciTracking);
    const csrf=await page.evaluate(()=>state.health.csrf_token);
    const headers={'Origin':app.url,'X-CSRF-Token':csrf};
    async function shipColor(selector){
      const value=await page.waitForFunction(selector=>{
        const symbol=document.querySelector(selector);
        return symbol&&getComputedStyle(symbol).backgroundColor;
      },selector);
      return value.jsonValue();
    }
    const vessels=[
      {mmsi:'261000001',classification:'civilian',type:70,color:'rgb(18, 107, 120)',offset:0},
      {mmsi:'261000002',classification:'military',type:35,color:'rgb(132, 59, 167)',offset:.25},
      {mmsi:'261000003',classification:'unclassified',type:null,color:'rgb(101, 113, 126)',offset:.5}
    ];
    for(const vessel of vessels){
      await page.evaluate(offset=>{
        const input=document.getElementById('ships-enabled');input.checked=true;
        input.dispatchEvent(new Event('change'));
        document.getElementById('tracking-panel').open=false;
        state.map.setView([55.1+offset,18.1+offset],8,{animate:false});
      },vessel.offset);
      const liveSelector=`.ship-marker .ship-${vessel.classification}`;
      const originalColor=await shipColor(liveSelector);
      assert.equal(originalColor,vessel.color);
      await page.locator(`.ship-marker:has(.ship-${vessel.classification})`).click();
      await page.getByRole('button',{name:'Śledź trasę',exact:true}).click();
      await page.waitForFunction(name=>document.getElementById('tracking-title').textContent.includes(name),
        vessel.mmsi==='261000001'?'TEST STATEK':vessel.mmsi==='261000002'?'TEST WOJSKOWY':'TEST NIEUSTALONY');
      const id=await page.locator('#tracking-session').inputValue();
      const selector='.tracking-object .ship-symbol';
      assert.equal(await shipColor(selector),originalColor,`${vessel.classification}: tracking changed the source color`);
      const response=await context.request.post(`${app.url}/_test/history/${id}`,{headers});
      assert.equal(response.status(),200);
      const history=await response.json();
      assert.equal(history.track.object_id,vessel.mmsi);
      assert.equal(history.track.ship_type_code,vessel.type);
      assert.ok(history.points.length>800);
      await page.evaluate(()=>{WiciTracking.sync({visible:false});WiciTracking.sync({visible:true});});
      await page.waitForFunction(count=>document.getElementById('tracking-metrics').textContent.includes(String(count)),
        history.points.length);
      const from=Date.parse(history.points[0].position_at),cursor=from+3600000;
      await page.locator('#tracking-timeline').fill(String(cursor));
      await page.locator('#tracking-timeline').dispatchEvent('input');
      assert.equal(await page.locator('.tracking-history').count(),1);
      assert.equal(await shipColor(selector),originalColor,`${vessel.classification}: seeking changed the source color`);
      await page.locator('#tracking-speed').selectOption('300');
      await page.locator('#tracking-play').click();
      await page.waitForFunction(cursor=>Number(document.getElementById('tracking-timeline').value)>cursor,cursor);
      assert.equal(await shipColor(selector),originalColor,`${vessel.classification}: playback changed the source color`);
      await page.locator('#tracking-play').click();
      await page.reload();
      await page.waitForFunction(id=>document.getElementById('tracking-session').value===id,id);
      assert.equal(await shipColor(selector),originalColor,`${vessel.classification}: reload lost the persisted color`);
      if(vessel.type===null){
        assert.equal(await page.locator('.tracking-object .ship-direction-unknown').count(),1,
          'Unknown heading must retain the live layer circular symbol');
      }
      await page.locator('#tracking-panel > summary').click();
      await page.locator('#tracking-stop').click();
      await page.waitForFunction(()=>document.getElementById('tracking-recording').textContent==='ZAPIS ZAKOŃCZONY');
      const stopped=await (await context.request.get(`${app.url}/api/tracks/${id}`)).json();
      assert.equal(stopped.track.active,false);
      assert.equal(stopped.track.ship_type_code,vessel.type);
      assert.equal(await shipColor(selector),originalColor,`${vessel.classification}: stopping changed the source color`);
      results.push({mmsi:vessel.mmsi,type:vessel.type,color:originalColor,points:history.points.length});
    }
    assert.deepEqual(errors,[]);
    assert.deepEqual(external,[]);
    fs.writeFileSync(path.join(evidence,'ship-classification-report.json'),
      JSON.stringify({results,errors,external},null,2));
  }finally{
    if(browser)await browser.close();
    await app.stop();
  }
});
