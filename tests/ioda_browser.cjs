// Full application + bundled Leaflet regression. Starts its own isolated offline demo server.
// NODE_PATH=/path/to/node_modules node --test tests/ioda_browser.cjs
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
with tempfile.TemporaryDirectory(prefix='wici-ioda-regression-') as root:
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

async function counts(page){return page.evaluate(()=>{let polygons=0,markers=0;state.map.eachLayer(l=>{if(l instanceof L.Polygon&&l.options.pane==='iodaDetections')polygons++;if(l instanceof L.Marker)markers++;});return {polygons,markers};});}
async function publicationLayers(page){return page.evaluate(()=>({
 areas:state.layers.filter(({layer})=>state.map.hasLayer(layer)).length,
 cards:state.cards.filter(layer=>state.map.hasLayer(layer)).length,
 records:document.querySelectorAll('#communication-list [data-communication-id]').length
}));}
async function openIodaControls(page){
 await page.locator('#layer-panel').evaluate(e=>e.open=true);
 await page.locator('#ioda-group').evaluate(e=>e.open=true);
}
async function refreshView(page){
 const refreshed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/communications');
 await page.locator('#refresh').click();await refreshed;
 await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
}
test('IODA real UI: offline demo, level/province/day filters, stale data, no ASN point', {timeout:45000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
    await setTestTheme(page);
  const errors=[],external=[],reads=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!==app.url){external.push(u.href);return route.abort();}if(u.pathname==='/api/ioda')reads.push(u.href);return route.continue();});
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();
  assert.equal(await page.locator('#ioda-enabled').isChecked(),false);assert.equal(reads.length,0);
  assert.equal(await page.locator('#ioda-hours').inputValue(),'48');
  await page.locator('#layer-panel > summary').click();await page.locator('#ioda-group > summary').click();
  await page.locator('#ioda-enabled').check();await page.locator('#ioda-list > details').first().waitFor();
  assert.equal(await page.locator('#ioda-list > details').count(),3);
  assert.match(await page.locator('#ioda-status').textContent(),/DEMO.*nieaktualne/);
  assert.equal(await page.locator('#ioda-signals svg').count(),1);
  await page.locator('#ioda-list > details').first().locator('summary').click();
  assert.match(await page.locator('#ioda-list').textContent(),/Wskaźnik.*IODA/);
  assert.match(await page.locator('#ioda-note').textContent(),/Brak (?:zdarzeń|detekcji) nie potwierdza/);
  await page.locator('#ioda-entity').selectOption('region/4849');
  assert.equal(await page.locator('#ioda-signals svg').count(),0);
  assert.match(await page.locator('#ioda-signals').textContent(),/Brak pomiarów/);
  const beforeAsn=await counts(page);
  await page.locator('#ioda-level').selectOption('asn');await page.waitForFunction(()=>document.querySelectorAll('#ioda-list > details').length===1);
  assert.equal((await counts(page)).polygons,0);assert.equal((await counts(page)).markers,beforeAsn.markers);
  assert.match(await page.locator('#ioda-list').textContent(),/pomiary mogą obejmować inne kraje/);
  await page.locator('#ioda-level').selectOption('region');await page.waitForFunction(()=>document.querySelector('#ioda-list')?.textContent.includes('Masovian'));
  assert.equal((await counts(page)).polygons,1);
  await page.locator('#ioda-hours').selectOption('48');await page.waitForFunction(()=>document.querySelector('#ioda-status')?.textContent.includes('1 zapisanych'));
  const screen=path.join(root,'tmp/ioda-ui-desktop.png');await page.screenshot({path:screen,fullPage:true});
  await page.locator('#layer-panel > summary').click();
  await page.locator('.filter-options > summary').click();await page.locator('#province').selectOption('02');
  await page.waitForFunction(()=>document.querySelector('#ioda-list')?.textContent.includes('Brak zapisanych zdarzeń'));
  await page.locator('#previous-day').click();await page.waitForFunction(()=>document.querySelector('#selected-day').value==='2026-10-10');
  assert.ok(reads.some(u=>u.includes('voivodeship=02')&&u.includes('hours=48')));
  await page.getByRole('button',{name:'Źródła',exact:true}).click();
  assert.match(await page.locator('#source-list').textContent(),/Ostatni pomiar IODA/);
  await page.getByRole('button',{name:'Sytuacja',exact:true}).click();
  await page.locator('#layer-panel > summary').click();await page.locator('#ioda-enabled').uncheck();
  assert.equal(await page.locator('#ioda-content').isVisible(),false);
  await page.setViewportSize({width:390,height:844});await page.locator('#ioda-enabled').check();
  await page.screenshot({path:path.join(root,'tmp/ioda-ui-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});

test('minute reload preserves IODA interactions while fresh, stale and ended detection styles update', {timeout:45000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
    await setTestTheme(page);
  const response=await page.request.get(app.url+'/api/ioda');
  let snapshot=await response.json(),healthNow='2026-10-11T12:00:00Z',reads=0;
  const region=snapshot.items.find(i=>i.entity_type==='region'&&i.entity_code==='3297');
  const id=region.id,endedAt=region.ended_at,originalAlerts=structuredClone(region.raw.alerts);
  region.ended_at=null;region.measurement_age_seconds=600;
  region.raw.alerts=region.raw.alerts.filter(alert=>alert.level!=='normal');
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install({time:new Date(healthNow)});await page.clock.pauseAt(new Date(healthNow));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin!==app.url)throw new Error('Offline regression attempted external read: '+url.href);
   if(url.pathname==='/api/health'){
    const upstream=await route.fetch();return route.fulfill({json:{...await upstream.json(),now:healthNow}});
   }
   if(url.pathname==='/api/ioda'){
    reads++;const result=structuredClone(snapshot),level=url.searchParams.get('level');
    if(level){result.items=result.items.filter(i=>i.entity_type===level);result.entities=result.entities.filter(e=>e.type===level);result.total=result.items.length;}
    return route.fulfill({json:result});
   }
   return route.continue();
  });
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();
  await page.locator('#layer-panel > summary').click();await page.locator('#ioda-group > summary').click();
  await page.locator('#ioda-enabled').check();
  const detail=page.locator(`[data-ioda-id="${id}"]`);
  await detail.locator('summary').click();
  await page.evaluate(id=>{
   window.iodaDetail=document.querySelector(`[data-ioda-id="${id}"]`);
   window.iodaSummary=window.iodaDetail.querySelector('summary');
   state.map.eachLayer(l=>{if(l instanceof L.Polygon&&l.options.pane==='iodaDetections'&&l.feature?.properties.admin_code==='14')window.iodaPolygon=l;});
   if(!window.iodaPolygon)throw new Error('Missing IODA region polygon');
   state.map.eachLayer(l=>{if(l instanceof L.GeoJSON&&l.hasLayer(window.iodaPolygon))window.iodaPopupOwner=l;});
   window.iodaPopup=window.iodaPopupOwner.getPopup();window.iodaPopupOwner.openPopup();
   window.iodaPopupOwner.openTooltip();
   window.iodaRenderCount=0;
   new MutationObserver(()=>window.iodaRenderCount++).observe(document.getElementById('ioda-status'),{childList:true});
  },id);
  assert.equal(await page.evaluate(()=>window.iodaPopupOwner.isPopupOpen()),true);
  assert.match(await detail.locator('summary').textContent(),/Koniec niepotwierdzony/);
  assert.doesNotMatch(await detail.locator('summary').textContent(),/stary alert/);
  const freshStyle=await page.evaluate(()=>({color:window.iodaPolygon.options.color,fill:window.iodaPolygon.options.fill,
   dashed:Boolean(window.iodaPolygon.options.dashArray),classes:window.iodaPolygon.getElement().getAttribute('class')}));
  assert.equal(freshStyle.color,'#6d28d9');assert.equal(freshStyle.fill,true);assert.equal(freshStyle.dashed,false);
  assert.match(freshStyle.classes,/ioda-area-unconfirmed/);assert.doesNotMatch(freshStyle.classes,/ioda-area-stale|ioda-area-ended/);
  // Exercise the real app.js interval and health-driven refresh, not a direct render call.
  const initialReads=reads;
  healthNow='2026-10-11T12:01:00Z';
  region.score=4321;region.measurement_age_seconds=3601;
  await page.clock.runFor(60000);
  await page.waitForFunction(()=>window.iodaDetail.textContent.includes('Wskaźnik: 4321'));
  assert.ok(reads>initialReads);
  const retained=await page.evaluate(id=>({
   sameDetail:document.querySelector(`[data-ioda-id="${id}"]`)===window.iodaDetail,
   sameSummary:window.iodaDetail.querySelector('summary')===window.iodaSummary,
   focused:document.activeElement===window.iodaSummary,open:window.iodaDetail.open,
   samePopup:window.iodaPopupOwner.getPopup()===window.iodaPopup,
   popupOpen:window.iodaPopupOwner.isPopupOpen(),layerRetained:state.map.hasLayer(window.iodaPolygon),
   popupContent:window.iodaPopup.getElement()?.textContent||''
  }),id);
  assert.equal(retained.sameDetail,true);assert.equal(retained.sameSummary,true);assert.equal(retained.focused,true);
  assert.equal(retained.open,true);assert.equal(retained.samePopup,true);assert.equal(retained.popupOpen,true);
  assert.equal(retained.layerRetained,true);assert.match(retained.popupContent,/Wskaźnik: 4321/);
  assert.match(await detail.locator('summary').textContent(),/Koniec niepotwierdzony · stary alert/);
  assert.match(retained.popupContent,/Koniec niepotwierdzony · stary alert/);
  assert.match(await page.evaluate(()=>window.iodaPopupOwner.getTooltip().getElement().textContent),/Koniec niepotwierdzony · stary alert/);
  const staleStyle=await page.evaluate(()=>({color:window.iodaPolygon.options.color,dashed:Boolean(window.iodaPolygon.options.dashArray),
   classes:window.iodaPolygon.getElement().getAttribute('class')}));
  assert.equal(staleStyle.color,freshStyle.color);assert.equal(staleStyle.dashed,true);
  assert.match(staleStyle.classes,/ioda-area-stale/);assert.doesNotMatch(staleStyle.classes,/ioda-area-ended/);
  // An unchanged response must preserve the same interaction state too.
  healthNow='2026-10-11T12:02:00Z';const previousReads=reads;
  const previousRender=await page.evaluate(()=>window.iodaRenderCount);
  await page.clock.runFor(60000);await page.waitForFunction(()=>state.health.now==='2026-10-11T12:02:00Z');
  await page.waitForFunction(previous=>window.iodaRenderCount>previous,previousRender);
  assert.ok(reads>previousReads);
  assert.equal(await detail.evaluate(e=>e.open),true);
  assert.equal(await page.evaluate(()=>window.iodaPopupOwner.isPopupOpen()&&window.iodaPopupOwner.getPopup()===window.iodaPopup),true);
  // A normal alert changes the existing polygon to a visible neutral area; an old age must not override its end.
  region.ended_at=endedAt;region.raw.alerts=originalAlerts;
  healthNow='2026-10-11T12:03:00Z';await page.clock.runFor(60000);
  await page.waitForFunction(()=>window.iodaDetail.querySelector('summary').textContent.includes('Zakończona'));
  const endedStyle=await page.evaluate(()=>({color:window.iodaPolygon.options.color,fill:window.iodaPolygon.options.fill,
   fillColor:window.iodaPolygon.options.fillColor,fillOpacity:window.iodaPolygon.options.fillOpacity,
   weight:window.iodaPolygon.options.weight,dashArray:window.iodaPolygon.options.dashArray,
   classes:window.iodaPolygon.getElement().getAttribute('class'),retained:state.map.hasLayer(window.iodaPolygon),
   popupRetained:window.iodaPopupOwner.isPopupOpen()&&window.iodaPopupOwner.getPopup()===window.iodaPopup,
   popupText:window.iodaPopup.getElement().textContent}));
  assert.equal(endedStyle.color,'#475569');assert.equal(endedStyle.fill,true);
  assert.equal(endedStyle.fillColor,'#64748b');assert.equal(endedStyle.fillOpacity,.16);
  assert.equal(endedStyle.weight,3);assert.equal(endedStyle.dashArray,'4 4');
  assert.equal(endedStyle.retained,true);assert.equal(endedStyle.popupRetained,true);
  assert.match(endedStyle.classes,/ioda-area-ended/);assert.doesNotMatch(endedStyle.classes,/ioda-area-unconfirmed|ioda-area-stale/);
  assert.match(endedStyle.popupText,/Zakończona/);
  assert.match(await page.evaluate(()=>window.iodaPopupOwner.getTooltip().getElement().textContent),/Zakończona/);
  assert.doesNotMatch(await detail.locator('summary').textContent(),/Koniec niepotwierdzony/);
  // Explicitly closed details and popup must not reopen on the next poll.
  await detail.locator('summary').click();await page.evaluate(()=>state.map.closePopup());
  const closedRender=await page.evaluate(()=>window.iodaRenderCount);
  region.score=5678;
  healthNow='2026-10-11T12:04:00Z';await page.clock.runFor(60000);
  await page.waitForFunction(previous=>window.iodaRenderCount>previous,closedRender);
  assert.equal(await detail.evaluate(e=>e.open),false);
  assert.equal(await page.evaluate(()=>window.iodaPopupOwner.isPopupOpen()),false);
  // Leaving the selected scope removes its layer and open detail instead of preserving ghosts.
  await detail.locator('summary').click();await page.evaluate(()=>window.iodaPopupOwner.openPopup());
  assert.match(await page.evaluate(()=>window.iodaPopup.getElement()?.textContent||''),/Wskaźnik: 5678/);
  await page.locator('#ioda-level').selectOption('asn');
  await page.waitForFunction(()=>!document.querySelector('#ioda-list')?.textContent.includes('Masovian'));
  assert.equal(await detail.count(),0);
  assert.equal(await page.evaluate(()=>state.map.hasLayer(window.iodaPolygon)||window.iodaPopupOwner.isPopupOpen()),false);
  await page.locator('#ioda-level').selectOption('');await detail.waitFor();
  assert.equal(await detail.evaluate(e=>e.open),false);
  assert.deepEqual(errors,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});

test('IODA isolates publication areas and cards; overlay choice survives refresh and publication selection', {timeout:45000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
    await setTestTheme(page);
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!==app.url){external.push(u.href);return route.abort();}return route.continue();});
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();
  const initial=await publicationLayers(page);
  assert.ok(initial.areas>0&&initial.cards>0&&initial.records>0);
  await openIodaControls(page);assert.equal(await page.locator('#ioda-communications').isChecked(),false);
  await page.locator('#ioda-enabled').check();await page.locator('#ioda-list > details').first().waitFor();
  assert.deepEqual(await publicationLayers(page),{areas:0,cards:0,records:initial.records});
  assert.equal(await page.locator('.province-card').count(),0);
  assert.ok((await counts(page)).polygons>0);
  await page.locator('#layer-panel > summary').click();
  const legend=page.locator('#ioda-map-legend');assert.equal(await legend.isVisible(),true);
  assert.equal(await legend.evaluate(e=>e.closest('#layer-panel')===null),true);
  const legendText=await legend.textContent();
  assert.match(legendText,/Zakończona/);assert.match(legendText,/Koniec niepotwierdzony/);
  assert.match(legendText,/Brak detekcji nie potwierdza sprawności łączności/);
  assert.doesNotMatch(legendText,/\bOK\b|łączność działa/i);
  // Refreshing publications must keep them out of the map until the user opts in.
  await refreshView(page);
  assert.deepEqual(await publicationLayers(page),{areas:0,cards:0,records:initial.records});
  assert.equal(await page.locator('#ioda-communications').isChecked(),false);
  await openIodaControls(page);await page.locator('#ioda-communications').check();
  assert.deepEqual(await publicationLayers(page),initial);assert.ok((await counts(page)).polygons>0);
  await refreshView(page);
  assert.equal(await page.locator('#ioda-communications').isChecked(),true);
  assert.deepEqual(await publicationLayers(page),initial);assert.ok((await counts(page)).polygons>0);
  await openIodaControls(page);await page.locator('#ioda-communications').uncheck();
  assert.deepEqual(await publicationLayers(page),{areas:0,cards:0,records:initial.records});
  // Choosing a publication explicitly reveals its geography and records that overlay choice.
  const selected=await page.evaluate(()=>state.communications.find(item=>locations(item).some(loc=>geometryFor(loc)))?.id);
  assert.ok(selected);
  const record=page.locator(`[data-communication-id="${selected}"]`);
  await record.evaluate(e=>{for(let p=e.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});
  await record.click();await page.locator('#detail-panel').waitFor();
  await page.waitForFunction(()=>document.getElementById('ioda-communications').checked);
  assert.equal(await record.getAttribute('aria-pressed'),'true');
  assert.ok(await page.evaluate(id=>state.layers.some(({layer,events})=>events.includes(id)&&state.map.hasLayer(layer)),selected));
  assert.ok((await counts(page)).polygons>0);
  await page.locator('#close-details').click();await openIodaControls(page);
  await page.locator('#ioda-communications').uncheck();await page.locator('#ioda-enabled').uncheck();
  assert.deepEqual(await publicationLayers(page),initial);assert.equal((await counts(page)).polygons,0);
  assert.equal(await legend.isVisible(),false);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});

test('IODA defaults to 48 hours and explains empty 24-hour and ASN-only maps', {timeout:45000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
    await setTestTheme(page);
  const response=await page.request.get(app.url+'/api/ioda?hours=48');
  const snapshot=await response.json(),initialEpoch=Date.parse('2026-10-11T12:00:00Z')/1000;
  let healthNow='2026-10-11T12:00:00Z';
  // Both detections ended 30 hours ago: they overlap 48 hours, but neither overlaps 24 hours.
  snapshot.items=snapshot.items.filter(item=>item.entity_type==='region'||item.entity_type==='asn');
  assert.equal(snapshot.items.length,2);
  for(const item of snapshot.items){
   item.started_at=initialEpoch-32*3600;item.ended_at=initialEpoch-30*3600;
   item.source_until=item.ended_at;item.measured_at=item.ended_at;item.measurement_age_seconds=30*3600;
   item.raw.from=item.started_at;item.raw.until=item.ended_at;
   const alert=item.raw.alerts[0];
   item.raw.alerts=[{...alert,time:item.started_at},{...alert,time:item.ended_at,level:'normal',condition:'normal',value:alert.historyValue}];
  }
  const errors=[],external=[],reads=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin!==app.url){external.push(url.href);return route.abort();}
   if(url.pathname==='/api/health'){
    const upstream=await route.fetch();return route.fulfill({json:{...await upstream.json(),now:healthNow}});
   }
   if(url.pathname==='/api/ioda'){
    reads.push(url.href);
    const result=structuredClone(snapshot),hours=Number(url.searchParams.get('hours')||24),level=url.searchParams.get('level');
    const end=Date.parse(healthNow)/1000,start=end-hours*3600;
    result.hours=hours;result.window_start=new Date(start*1000).toISOString();result.window_end=new Date(end*1000).toISOString();
    result.items=result.items.filter(item=>item.started_at<end&&item.ended_at>start&&(!level||item.entity_type===level));
    if(level)result.entities=result.entities.filter(entity=>entity.type===level);
    result.total=result.items.length;result.limited=false;
    return route.fulfill({json:result});
   }
   return route.continue();
  });
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();
  const publications=await publicationLayers(page);
  assert.equal(await page.locator('#ioda-hours').inputValue(),'48');
  await openIodaControls(page);await page.locator('#ioda-enabled').check();
  await page.waitForFunction(()=>document.querySelectorAll('#ioda-list > details').length===2);
  assert.equal(new URL(reads[0]).searchParams.get('hours'),'48');
  assert.equal((await counts(page)).polygons,1);
  const area=await page.evaluate(()=>{
   let polygon;state.map.eachLayer(layer=>{if(layer instanceof L.Polygon&&layer.options.pane==='iodaDetections')polygon=layer;});
   return {color:polygon.options.color,fill:polygon.options.fill,fillColor:polygon.options.fillColor,
    opacity:Number(polygon.getElement().getAttribute('fill-opacity')),svgFill:polygon.getElement().getAttribute('fill'),
    classes:polygon.getElement().getAttribute('class')};
  });
  assert.equal(area.color,'#475569');assert.equal(area.fill,true);assert.equal(area.fillColor,'#64748b');
  assert.equal(area.svgFill,'#64748b');assert.equal(area.opacity,.16);assert.match(area.classes,/ioda-area-ended/);
  assert.equal((await publicationLayers(page)).records,publications.records);
  await page.locator('#layer-panel > summary').click();
  const windowText=await page.locator('#ioda-map-window').textContent();
  assert.match(windowText,/48/);assert.match(windowText,/0?9\.10\.(?:20)?26/);assert.match(windowText,/11\.10\.(?:20)?26/);
  assert.match(await page.locator('#ioda-map-label').textContent(),/48.*1.*na mapie/);
  assert.equal(await page.locator('#ioda-map-empty').isVisible(),false);
  assert.equal(await page.locator('#ioda-map-expand').isVisible(),false);
  await openIodaControls(page);await page.locator('#ioda-hours').selectOption('24');
  await page.waitForFunction(()=>document.querySelectorAll('#ioda-list > details').length===0);
  await page.locator('#layer-panel > summary').click();
  assert.equal((await counts(page)).polygons,0);
  assert.equal(await page.locator('#ioda-map-empty').isVisible(),true);
  assert.match(await page.locator('#ioda-map-empty').textContent(),/Brak.*detekcji/i);
  assert.match(await page.locator('#ioda-map-window').textContent(),/24/);
  assert.match(await page.locator('#ioda-map-label').textContent(),/24.*0.*na mapie/);
  const expand=page.locator('#ioda-map-expand');
  assert.equal(await expand.isVisible(),true);assert.equal(await expand.textContent(),'Sprawdź 48 godzin');
  // Manual refresh changes the snapshot time, without overriding an explicit 24-hour choice.
  healthNow='2026-10-11T12:01:00Z';
  const refreshedIoda=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/ioda');
  await refreshView(page);await refreshedIoda;
  await page.waitForFunction(()=>document.getElementById('ioda-map-window').textContent.includes('14:01'));
  assert.equal(await page.locator('#ioda-hours').inputValue(),'24');
  assert.equal(new URL(reads.at(-1)).searchParams.get('hours'),'24');
  assert.equal((await counts(page)).polygons,0);assert.equal(await expand.isVisible(),true);
  await expand.click();await page.waitForFunction(()=>document.querySelectorAll('#ioda-list > details').length===2);
  assert.equal(await page.locator('#ioda-hours').inputValue(),'48');assert.equal((await counts(page)).polygons,1);
  assert.equal(await page.locator('#ioda-map-empty').isVisible(),false);assert.equal(await expand.isVisible(),false);
  assert.match(await page.locator('#ioda-map-label').textContent(),/48.*1.*na mapie/);
  const beforeAsn=await counts(page);
  await openIodaControls(page);await page.locator('#ioda-level').selectOption('asn');
  await page.waitForFunction(()=>document.querySelectorAll('#ioda-list > details').length===1);
  await page.locator('#layer-panel > summary').click();
  assert.equal((await counts(page)).polygons,0);assert.equal((await counts(page)).markers,beforeAsn.markers);
  assert.equal(await page.locator('#ioda-map-empty').isVisible(),true);
  assert.match(await page.locator('#ioda-map-empty').textContent(),/geometri/i);
  assert.match(await page.locator('#ioda-map-empty').textContent(),/liście/i);
  assert.match(await page.locator('#ioda-map-label').textContent(),/48.*0.*na mapie/);
  assert.equal(await expand.isVisible(),false);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});

test('IODA mobile popup stays inside the map with a reachable close button', {timeout:45000},async()=>{
 const app=await server();let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    await setTestTheme(page);
  const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!==app.url){external.push(u.href);return route.abort();}return route.continue();});
  await page.goto(app.url);await page.locator('.province-card').first().waitFor();
  await openIodaControls(page);await page.locator('#ioda-enabled').check();
  await page.locator('#ioda-list > details').first().waitFor();await page.locator('#ioda-level').selectOption('region');
  await page.waitForFunction(()=>document.querySelectorAll('#ioda-list > details').length===1);
  await page.locator('#layer-panel > summary').click();await page.locator('#map').scrollIntoViewIfNeeded();
  // Let the initial fitBounds zoom settle before explicitly positioning the map.
  await page.waitForFunction(()=>!state.map._animatingZoom&&!state.map._panAnim?._inProgress);
  await page.evaluate(()=>{
   let polygon,owner;
   state.map.eachLayer(l=>{if(l instanceof L.Polygon&&l.options.pane==='iodaDetections')polygon=l;});
   if(!polygon)throw new Error('Missing mobile IODA polygon');
   state.map.eachLayer(l=>{if(l instanceof L.GeoJSON&&l.hasLayer(polygon))owner=l;});
   state.map.setView(polygon.getBounds().getCenter(),6,{animate:false});owner.openPopup(polygon.getBounds().getCenter());
  });
  await page.locator('.leaflet-popup').waitFor();
  await page.waitForFunction(()=>!state.map._animatingZoom&&!state.map._panAnim?._inProgress&&getComputedStyle(document.querySelector('.leaflet-popup')).opacity==='1');
  await page.waitForFunction(()=>{
   const map=document.getElementById('map').getBoundingClientRect(),popup=document.querySelector('.leaflet-popup')?.getBoundingClientRect();
   return popup&&popup.left>=map.left-1&&popup.right<=map.right+1&&popup.top>=map.top-1&&popup.bottom<=map.bottom+1;
  });
  const popup=page.locator('.leaflet-popup'),close=popup.locator('.leaflet-popup-close-button');
  assert.match(await popup.textContent(),/Zakończona/);
  assert.equal(await close.isVisible(),true);
  assert.equal(await close.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),true);
  assert.equal(await page.locator('#ioda-map-legend').isVisible(),false,'legend must not obscure popup content');
  assert.equal(await popup.locator('.ioda-state').evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),true,'zoom controls must not obscure the status');
  await page.screenshot({path:path.join(root,'tmp/ioda-popup-mobile.png'),fullPage:true});
  await close.tap();await popup.waitFor({state:'detached'});assert.equal(await popup.count(),0);
  assert.equal(await page.locator('#ioda-map-legend').isVisible(),true);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{if(browser)await browser.close();await app.stop();}
});
