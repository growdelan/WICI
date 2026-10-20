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
for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
 test(`Sentinel-2 ${name}: offline comparison, touch, keyboard, geometry and stale responses`,{timeout:60000},async()=>{
  const app=await server();let browser;
  try{
   browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport,hasTouch:name==='mobile',isMobile:name==='mobile'});
    await setTestTheme(page);
   const errors=[],external=[];let searches=0,renders=0,hold=null,release,searchMode='',holdSearch=null,releaseSearch,searchEntered;
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin!==app.url){external.push(url.href);return route.abort();}
    if(url.pathname==='/api/sentinel2/search'){
     searches++;
     if(searchMode==='empty')return route.fulfill({json:{status:'ready',items:[]}});
     if(searchMode==='error')return route.fulfill({status:503,json:{detail:'Testowa awaria CDSE.'},headers:{'Retry-After':'3'}});
     if(holdSearch){const response=await route.fetch();searchEntered();await holdSearch;return route.fulfill({response});}
    }
    if(url.pathname==='/api/sentinel2/render'){renders++;if(hold)await hold;}
    return route.continue();
   });
   await page.goto(app.url);await page.locator('.province-card').first().waitFor();
   await page.waitForFunction(()=>state.geometries.has('PL')&&!state.map._animatingZoom);
   assert.equal(searches,0);assert.equal(renders,0);
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#s2-group').evaluate(e=>e.open=true);
   assert.equal(await page.locator('#s2-enabled').isChecked(),false);
   await page.locator('#s2-enabled').check();await page.waitForFunction(()=>document.querySelector('#s2-status').textContent.includes('DEMO'));
   await page.locator('#s2-pick').click();assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'true');
   await page.keyboard.press('Escape');assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'false');
   await page.locator('#layer-panel').evaluate(e=>e.open=true);
   await page.locator('#s2-center').click();
   for(const [side,year] of [['before','2020'],['after','2026']]){await page.locator(`#s2-${side}-start`).fill(year+'-10-01');await page.locator(`#s2-${side}-end`).fill(year+'-10-16');}
   for(const id of ['before-start','before-end','after-start','after-end']){
    const fits=await page.locator('#s2-'+id).evaluate(e=>{
     const a=e.getBoundingClientRect(),b=e.closest('.layer-panel-body').getBoundingClientRect();
     return a.width>0&&a.left>=b.left&&a.right<=b.right;
    });assert.ok(fits,`${id} must fit inside the layer panel`);
   }
   await page.locator('#s2-controls fieldset').first().scrollIntoViewIfNeeded();
   await page.screenshot({path:`tmp/browser-evidence/sentinel2/${name}-date-ranges.png`,fullPage:true});
   await page.locator('#s2-search').click();await page.waitForFunction(()=>document.querySelector('#s2-before').options.length===3);
   assert.equal(searches,2);assert.equal(renders,0);
   assert.equal(await page.locator('#s2-before option[value*="2026"]').count(),0);
   assert.equal(await page.locator('#s2-after option[value*="2020"]').count(),0);
   await page.locator('#s2-before').selectOption('DEMO-0-2020-10-01');await page.locator('#s2-after').selectOption('DEMO-1-2026-10-16');
   await page.locator('#s2-compare').click();await page.locator('.s2-swipe').waitFor();
   assert.equal(renders,2);assert.match(await page.locator('.s2-dates').textContent(),/2020-10-01.*2026-10-16/);
   const range=page.getByRole('slider',{name:'Porównanie przed i po'});
   await page.locator('#layer-panel').evaluate(e=>e.open=false);
   await range.focus();await page.keyboard.press('ArrowRight');assert.equal(await range.inputValue(),'51');
   assert.match(await page.locator('.leaflet-s2Before-pane img').evaluate(e=>e.style.clipPath),/49%/);
   if(name==='mobile')await range.tap();else await range.click();
   await range.evaluate(e=>{e.value='25';e.dispatchEvent(new Event('input'));});
   assert.match(await page.locator('.leaflet-s2BeforeQuality-pane img').evaluate(e=>e.style.clipPath),/75%/);
   assert.match(await page.locator('.leaflet-s2AfterQuality-pane img').evaluate(e=>e.style.clipPath),/25%/);
   assert.equal(renders,2);
   // Both rasters have identical pixel placement after pan and zoom.
   await page.evaluate(()=>{state.map.panBy([24,12],{animate:false});state.map.setZoom(13,{animate:false});});
   await page.waitForTimeout(100);
   const rectangles=await page.locator('.leaflet-s2Before-pane img,.leaflet-s2After-pane img').evaluateAll(images=>images.map(i=>{const r=i.getBoundingClientRect();return [r.x,r.y,r.width,r.height];}));
   assert.deepEqual(rectangles[0],rectangles[1]);
   assert.ok(await range.isVisible());
   await page.screenshot({path:`tmp/browser-evidence/sentinel2/${name}-map.png`,fullPage:true});
   await page.locator('#layer-panel').evaluate(e=>e.open=true);
   await page.locator('#s2-quality').check();assert.equal(await page.locator('.leaflet-s2BeforeQuality-pane img').evaluate(e=>e.style.opacity),'1');
   await page.locator('#s2-group').evaluate(e=>e.scrollIntoView());
   await page.screenshot({path:`tmp/browser-evidence/sentinel2/${name}-controls.png`,fullPage:true});
   // Changing only the before range removes the old comparison but retains the after choice.
   await page.locator('#s2-before-start').fill('2021-10-05');await page.locator('#s2-before-end').focus();
   assert.equal(await page.locator('.s2-swipe').count(),0);
   assert.equal(await page.locator('#s2-before').inputValue(),'');
   assert.equal(await page.locator('#s2-after').inputValue(),'DEMO-1-2026-10-16');
   // Re-render two different years at the same point with earlier renders still cached.
   for(const [side,year] of [['before','2021'],['after','2026']]){await page.locator(`#s2-${side}-start`).fill(year+'-10-05');await page.locator(`#s2-${side}-end`).fill(year+'-10-15');}
   await page.locator('#s2-search').click();await page.waitForFunction(()=>document.querySelector('#s2-before').options.length===3);
   await page.locator('#s2-before').selectOption('DEMO-0-2021-10-05');await page.locator('#s2-after').selectOption('DEMO-1-2026-10-15');
   await page.locator('#s2-compare').click();await page.locator('.s2-swipe').waitFor();
   assert.match(await page.locator('.s2-dates').textContent(),/2021-10-05.*2026-10-15/);
   const details=await page.locator('#s2-detail').textContent();
   assert.match(details,/Przed: 2021-10-05/);assert.match(details,/Po: 2026-10-15/);
   assert.doesNotMatch(details,/2020-10-01|2026-10-16/);
   // Selecting a different date removes the old image immediately.
   await page.locator('#s2-after').selectOption('');assert.equal(await page.locator('.s2-swipe').count(),0);
   assert.equal(await page.locator('.leaflet-s2Before-pane img').count(),0);
   await page.locator('#s2-after').selectOption('DEMO-1-2026-10-15');
   hold=new Promise(r=>release=r);await page.locator('#s2-compare').click();await page.waitForTimeout(100);
   await page.locator('#s2-enabled').uncheck();release();await page.waitForTimeout(250);
   assert.equal(await page.locator('.s2-swipe').count(),0);assert.equal(await page.locator('.leaflet-s2Before-pane img').count(),0);
   // New point invalidates all observations; a late search cannot re-populate them.
   await page.locator('#s2-enabled').check();await page.locator('#s2-center').click();
   assert.equal(await page.locator('#s2-before option').count(),1);
   hold=null;searchMode='empty';await page.locator('#s2-search').click();
   await page.waitForFunction(()=>document.querySelector('#s2-status').textContent.includes('Brak obserwacji'));
   searchMode='error';await page.locator('#s2-search').click();
   await page.waitForFunction(()=>document.querySelector('#s2-status').textContent.includes('awaria'));
   assert.match(await page.locator('#s2-status').textContent(),/Odczekaj 3 s/);
   searchMode='';
   for(const change of ['point','date']){
    holdSearch=new Promise(r=>releaseSearch=r);const entered=new Promise(r=>searchEntered=r);
    await page.locator('#s2-search').click();await entered;
    if(change==='point')await page.locator('#s2-center').click();
    else{await page.locator('#s2-before-start').fill('2026-10-02');await page.locator('#s2-cloud').focus();}
    releaseSearch();await page.waitForTimeout(150);holdSearch=null;
    assert.equal(await page.locator('#s2-before option').count(),1);
   }
   // Explicit picking uses a real map click rather than background browsing clicks.
   await page.locator('#s2-pick').click();
   await page.locator('#map').click({position:{x:viewport.width>600?430:190,y:220}});
   assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'false');
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }finally{if(browser)await browser.close();await app.stop();}
 });
}

for(const width of [700,800,900]){
 test(`Sentinel-2 ${width}px: labels and full slider remain inside map after resize`,{timeout:30000},async()=>{
  const app=await server();let browser;
  try{
   browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width,height:1000}});
    await setTestTheme(page);
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>new URL(route.request().url()).origin===app.url?route.continue():route.abort());
   await page.goto(app.url);await page.locator('.province-card').first().waitFor();
   await page.waitForFunction(()=>state.geometries.has('PL')&&!state.map._animatingZoom);
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#s2-group').evaluate(e=>e.open=true);
   await page.locator('#s2-enabled').check();await page.locator('#s2-center').click();
   for(const side of ['before','after']){await page.locator(`#s2-${side}-start`).fill('2026-10-01');await page.locator(`#s2-${side}-end`).fill('2026-10-16');}
   await page.locator('#s2-search').click();await page.waitForFunction(()=>document.querySelector('#s2-before').options.length===3);
   const before=await page.locator('#s2-before option').nth(1).getAttribute('value');
   const after=await page.locator('#s2-after option').nth(2).getAttribute('value');
   await page.locator('#s2-before').selectOption(before);await page.locator('#s2-after').selectOption(after);
   await page.locator('#s2-compare').click();await page.locator('.s2-swipe').waitFor();
   await page.locator('#layer-panel').evaluate(e=>e.open=false);
   // Exercise both initial layout and resizing an already rendered comparison.
   for(const resized of [width,1440,width]){
    await page.setViewportSize({width:resized,height:1000});
    const boxes=await page.evaluate(()=>{
     const rect=e=>{const b=e.getBoundingClientRect();return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width};};
     return {map:rect(document.querySelector('#map')),parts:[...document.querySelectorAll('.s2-swipe,.s2-dates span,.s2-swipe input')].map(rect)};
    });
    for(const part of boxes.parts){
     assert.ok(part.width>0);
     assert.ok(part.left>=boxes.map.left&&part.right<=boxes.map.right,JSON.stringify({resized,part,map:boxes.map}));
     assert.ok(part.top>=boxes.map.top&&part.bottom<=boxes.map.bottom);
    }
    const range=page.getByRole('slider',{name:'Porównanie przed i po'});
    const slider=await range.boundingBox();
    await page.mouse.click(slider.x+slider.width-2,slider.y+slider.height/2);
    assert.equal(await range.inputValue(),'100');
    await page.mouse.click(slider.x+2,slider.y+slider.height/2);
    assert.equal(await range.inputValue(),'0');
   }
   assert.deepEqual(errors,[]);
  }finally{if(browser)await browser.close();await app.stop();}
 });
}

for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
 test(`Sentinel-2 picking ${name}: publication cards and non-bubbling layers select a visible point`,{timeout:30000},async()=>{
  const app=await server();let browser;
  try{
   browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport,hasTouch:name==='mobile',isMobile:name==='mobile'});
    await setTestTheme(page);
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>new URL(route.request().url()).origin===app.url?route.continue():route.abort());
   await page.goto(app.url);await page.waitForFunction(()=>state.geometries.has('PL')&&state.cards.length&&!state.map._animatingZoom);
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#s2-group').evaluate(e=>e.open=true);
   await page.locator('#s2-enabled').check();await page.locator('#s2-center').click();
   const initial=await page.locator('#s2-point').textContent();
   await page.locator('#s2-pick').click();
   if(name==='mobile')await page.locator('.province-card').first().tap();else await page.locator('.province-card').first().click();
   assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'false');
   assert.notEqual(await page.locator('#s2-point').textContent(),initial);
   assert.equal(await page.locator('.leaflet-popup').count(),0);
   assert.equal(await page.locator('.leaflet-s2Point-pane path').count(),1);
   await page.waitForFunction(()=>[...document.querySelectorAll('.leaflet-tooltip')].filter(e=>e.textContent==='Sentinel-2 · wybrany punkt').length===1);
   assert.ok(await page.getByText('Sentinel-2 · wybrany punkt',{exact:true}).isVisible());
   // An ordinary click retains the chosen point and still opens the publication popup.
   const selected=await page.locator('#s2-point').textContent();
   await page.locator('.province-card').first().click();await page.locator('.leaflet-popup').waitFor();
   assert.equal(await page.locator('#s2-point').textContent(),selected);
   await page.evaluate(()=>state.map.closePopup());
   await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#s2-pick').click();
   await page.locator('.leaflet-control-zoom-in').click();
   await page.waitForFunction(()=>!state.map._animatingZoom);
   assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'true');
   assert.equal(await page.locator('#s2-point').textContent(),selected);
   if(name==='desktop'){
    const area=await page.locator('#map').boundingBox(),x=area.x+area.width*.8,y=area.y+area.height*.45;
    await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+30,y+40,{steps:8});await page.mouse.up();
    assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#s2-point').textContent(),selected);
   }
   for(const shape of ['marker','polygon']){
    // Both blocked marker propagation and popup-bound polygons must yield to explicit picking.
    await page.evaluate(shape=>{
     window.s2PickingFixture?.remove();
     const center=state.map.getCenter();
     window.s2PickingFixture=(shape==='marker'
       ?L.circleMarker(center,{pane:'markerPane',radius:18,bubblingMouseEvents:false})
       :L.rectangle([[center.lat-.02,center.lng-.02],[center.lat+.02,center.lng+.02]],{pane:'markerPane'}))
       .bindPopup('Testowa warstwa interaktywna').addTo(state.map);
    },shape);
    if(shape==='polygon'){
     await page.locator('#layer-panel').evaluate(e=>e.open=true);await page.locator('#s2-pick').click();
    }
    const target=await page.evaluate(()=>{
     const layer=window.s2PickingFixture,ll=layer.getLatLng?layer.getLatLng():layer.getBounds().getCenter();
     const p=state.map.latLngToContainerPoint(ll),r=state.map.getContainer().getBoundingClientRect();
     return {x:p.x+r.left,y:p.y+r.top};
    });
    if(name==='mobile')await page.touchscreen.tap(target.x,target.y);else await page.mouse.click(target.x,target.y);
    assert.equal(await page.locator('#s2-pick').getAttribute('aria-pressed'),'false');
    assert.equal(await page.locator('.leaflet-popup').count(),0);
    const marker=await page.locator('.leaflet-s2Point-pane path').boundingBox();
    assert.ok(Math.abs(marker.x+marker.width/2-target.x)<2);
    assert.ok(Math.abs(marker.y+marker.height/2-target.y)<2);
   }
   assert.equal(await page.locator('.leaflet-s2Point-pane').evaluate(e=>e.style.pointerEvents),'none');
   await page.waitForFunction(()=>[...document.querySelectorAll('.leaflet-tooltip')].filter(e=>e.textContent==='Sentinel-2 · wybrany punkt').length===1);
   await page.screenshot({path:`tmp/browser-evidence/sentinel2/picking-${name}.png`,fullPage:true});
   assert.deepEqual(errors,[]);
  }finally{if(browser)await browser.close();await app.stop();}
 });
}
