// Real Cesium/WebGL + Leaflet, synthetic aircraft feed, network-forbidden DEMO backend.
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {environment,aircraft,snapshot,camera,distance,root}=require('./helpers/vehicle3d_browser.cjs');
const evidence=path.join(root,'tmp/aircraft3d-evidence');
fs.mkdirSync(evidence,{recursive:true});

test('aircraft 3D: lazy real WebGL, existing feed, cameras, held states, recovery and Atlas return',{timeout:90000},async()=>{
  const env=await environment();const {page,feed,observations}=env;
  try{
    assert.deepEqual(observations.vendor,[]);
    let atlas;
    const mapState=()=>page.evaluate(()=>({center:[state.map.getCenter().lat,state.map.getCenter().lng],zoom:state.map.getZoom(),layers:Object.entries(state.map._layers).filter(([,layer])=>!(layer instanceof L.Tooltip)&&!(layer instanceof L.Popup)).map(([id])=>id)}));
    const assertMapCenter=async expected=>assert.ok(await page.evaluate(center=>state.map.project(center).distanceTo(state.map.project(state.map.getCenter()))<1,expected),'Atlas center changed by more than one screen pixel');
    await env.open(async()=>{atlas=await mapState();});await env.rendered();
    assert.equal(await page.locator('#aircraft3d-osm').isChecked(),false);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.at(-1).scene.context.webgl2),true);
    assert.equal(await page.locator('#aircraft3d-follow').getAttribute('aria-pressed'),'true');
    // Engine startup can exceed the thirty-second continuity window of the first report.
    // Seed a recent observation after loading so the next report exercises interpolation.
    await env.next(snapshot([aircraft(Date.now()-18000)]));
    const before=await camera(page);
    await env.next(snapshot([aircraft(Date.now(),{longitude:20.98})]));
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='interpolated');
    await page.waitForFunction(before=>{const p=window.__aircraftViewers.at(-1).camera.positionWC;return Math.hypot(p.x-before.x,p.y-before.y,p.z-before.z)>100;},before);
    const moving=await camera(page);assert.ok(distance(before,moving)>100,'Camera must follow the changed world position');
    await page.locator('#aircraft3d-pov').click();await page.waitForTimeout(100);
    assert.equal(await page.locator('#aircraft3d-pov').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#aircraft3d-distance-control').isVisible(),false);
    const pov=await camera(page);assert.ok(distance(moving,pov)>100,'POV must use a different camera offset');
    await page.screenshot({path:path.join(evidence,'desktop-pov.png'),fullPage:true});
    await page.locator('#aircraft3d-follow').click();
    await page.locator('#aircraft3d-distance').fill('3000');await page.locator('#aircraft3d-distance').dispatchEvent('input');
    assert.equal(await page.locator('#aircraft3d-distance-value').textContent(),'3000 m');
    await page.screenshot({path:path.join(evidence,'desktop-follow.png'),fullPage:true});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    assert.equal(await env.button.evaluate(button=>document.activeElement===button),true);
    assert.equal(await page.evaluate(()=>Object.values(state.map._layers).find(layer=>layer.aircraft?.hex==='48abcd').getPopup().options.autoPan),true,'A retained visible popup must regain its original auto-pan behavior');
    const returned=await mapState();assert.equal(returned.zoom,atlas.zoom);assert.deepEqual(returned.layers,atlas.layers);await assertMapCenter(atlas.center);
    await env.button.click();await env.rendered();
    const accepted=feed.body.items[0],report=await page.locator('#aircraft3d-time').textContent();
    await env.next(snapshot([aircraft(Date.parse(accepted.position_at)-1000,{altitude_m:null,track:null})]));
    await page.waitForTimeout(1100);
    assert.equal((await page.locator('#aircraft3d-time').textContent()).split(' · ')[0],report.split(' · ')[0]);
    assert.match(await page.locator('#aircraft3d-telemetry').textContent(),/Kurs 90°/);
    assert.equal(await page.locator('#aircraft3d-pov').isEnabled(),true);
    assert.doesNotMatch(await page.locator('#aircraft3d-status').textContent(),/Brak świeżej pozycji lub wysokości/);
    await env.next({...feed.body,stale:true,status:'error'});
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Odczyt niedostępny'));
    const held=await camera(page);await page.waitForTimeout(200);assert.ok(distance(held,await camera(page))<1);
    await env.next(snapshot([]));await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Brak samolotu'));
    await env.next(snapshot([aircraft(Date.now())]),{fail:true});
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Odczyt niedostępny'));
    await env.next(snapshot([aircraft(Date.now(),{altitude_m:null})]));
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Brak świeżej pozycji lub wysokości'));
    await env.next(snapshot([aircraft(Date.now())]));
    await page.waitForFunction(()=>!['holding','stale','error'].includes(document.querySelector('#aircraft3d-dialog').dataset.state));
    // Temporarily hide the tab without closing the modal, then resume the same viewer.
    await page.evaluate(()=>window.WiciAircraft3D.sync({visible:false,enabled:true,mode:'live',hidden:true}));
    assert.equal(await page.locator('#aircraft3d-dialog').evaluate(element=>element.open),true);
    await page.evaluate(()=>window.WiciAircraft3D.sync({visible:true,enabled:true,mode:'live',hidden:false}));
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.every(view=>view.isDestroyed())),true);
    assert.equal(await page.locator('#aircraft3d-scene canvas').count(),0);
    assert.equal(await page.locator('#map').evaluate(element=>document.activeElement===element),true);
    await assertMapCenter(atlas.center);assert.equal((await mapState()).zoom,atlas.zoom);
    await env.clean();
    fs.writeFileSync(path.join(evidence,'desktop-report.json'),JSON.stringify({observations,camera:{before,moving,pov},atlas},null,2));
  }finally{await env.saveRuntime();await env.stop();}
});

test('aircraft 3D: close during lazy loading cannot create an orphaned viewer',{timeout:60000},async()=>{
  const env=await environment({holdVendor:true,name:'lazy-cancel'});const {page}=env;
  try{
    await env.open();await env.vendorEntered;
    await page.locator('#aircraft3d-close').click();env.releaseVendor();
    await page.waitForFunction(()=>Boolean(window.Cesium));await page.waitForTimeout(150);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.length),0);
    assert.equal(await page.locator('#aircraft3d-scene canvas').count(),0);
    await env.button.click();await env.rendered();assert.equal(await page.evaluate(()=>window.__aircraftViewers.length),1);
    await page.locator('#aircraft3d-close').click();
    assert.equal(await page.evaluate(()=>window.__aircraftViewers[0].isDestroyed()),true);
    await env.clean();
  }finally{await env.stop();}
});

test('aircraft 3D: unavailable WebGL leaves an accessible error and return to Atlas',{timeout:60000},async()=>{
  const env=await environment({noWebgl:true,name:'webgl-unavailable'});const {page}=env;
  try{
    await env.open();await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='error');
    assert.match(await page.locator('#aircraft3d-status').textContent(),/WebGL 2/);
    assert.equal(await page.locator('#aircraft3d-close').isEnabled(),true);
    await page.screenshot({path:path.join(evidence,'webgl-unavailable.png'),fullPage:true});
    await page.keyboard.press('Escape');assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    assert.equal(await env.button.evaluate(button=>document.activeElement===button),true);
    await env.clean();
  }finally{await env.stop();}
});

for(const theme of ['light','dark'])test(`aircraft 3D: mobile 390 ${theme} real rendering and controls`,{timeout:60000},async()=>{
  const env=await environment({viewport:{width:390,height:844},theme});const {page}=env;
  try{
    await env.open();await env.rendered();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const bounds=await page.locator('#aircraft3d-dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=391);
    await page.screenshot({path:path.join(evidence,`mobile-${theme}-follow.png`)});
    await page.locator('#aircraft3d-pov').click();await page.waitForTimeout(100);
    await page.screenshot({path:path.join(evidence,`mobile-${theme}-pov.png`)});
    await page.locator('#aircraft3d-close').click();assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    await env.clean();
  }finally{await env.stop();}
});

test('aircraft 3D: OSM is an explicit opt-in and all map requests can be served offline',{timeout:60000},async()=>{
  const env=await environment({liveMapPolicy:true,name:'osm-opt-in'});const {page,observations}=env;
  try{
    await env.open();await env.rendered();
    assert.deepEqual(observations.tiles,[]);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.at(-1).imageryLayers.length),0);
    await page.locator('#aircraft3d-osm').check();
    await page.waitForFunction(()=>window.__aircraftViewers.at(-1).imageryLayers.length===1);
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-scene a[href="https://www.openstreetmap.org/copyright"]'));
    assert.equal(await page.locator('#aircraft3d-scene a[href="https://www.openstreetmap.org/copyright"]').isVisible(),true);
    await page.waitForFunction(()=>window.__aircraftViewers.at(-1).scene.globe.tilesLoaded);
    assert.ok(observations.tiles.length>0,'OSM opt-in must request the synthetic map tiles');
    await page.screenshot({path:path.join(evidence,'osm-synthetic-tiles.png'),fullPage:true});
    await page.locator('#aircraft3d-osm').uncheck();
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.at(-1).imageryLayers.length),0);
    await page.waitForTimeout(300);const stopped=observations.tiles.length;await page.waitForTimeout(600);
    assert.equal(observations.tiles.length,stopped,'No tile requests may continue after disabling OSM');
    await page.locator('#aircraft3d-close').click();await env.clean();
  }finally{await env.stop();}
});

test('aircraft 3D: layer, main view and region changes close the viewer and release graphics',{timeout:60000},async()=>{
  const env=await environment({name:'lifecycle-close'});const {page,feed,observations}=env;
  const setLayer=enabled=>page.evaluate(enabled=>{const input=document.querySelector('#aircraft-enabled');input.checked=enabled;input.dispatchEvent(new Event('change'));},enabled);
  try{
    await env.open();await env.rendered();
    await setLayer(false);assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    await page.waitForTimeout(200);const stopped=observations.aircraftReads;await page.waitForTimeout(600);assert.equal(observations.aircraftReads,stopped);
    feed.body=snapshot([aircraft(Date.now()-2000)]);await setLayer(true);await page.locator('.aircraft-marker').waitFor();
    await env.open();await env.rendered();
    await page.evaluate(()=>document.querySelector('.tab[data-view="sources"]').click());
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    feed.body=snapshot([aircraft(Date.now()-2000)]);
    await page.locator('.tab[data-view="situation"]').click();await page.locator('.aircraft-marker').waitFor();
    await env.open();await env.rendered();
    await page.evaluate(()=>document.dispatchEvent(new Event('wici:regionchange')));
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.length),3);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.every(view=>view.isDestroyed())),true);
    assert.equal(await page.locator('#aircraft3d-scene canvas').count(),0);await env.clean();
  }finally{await env.stop();}
});

test('aircraft 3D: render errors latch until closing and reopening a new viewer',{timeout:60000},async()=>{
  const env=await environment({name:'render-error-latch'});const {page,observations}=env;
  try{
    await env.open();await env.rendered();
    await page.evaluate(()=>{
      const viewer=window.__aircraftViewers.at(-1);window.__renderErrors=0;
      viewer.scene.renderError.addEventListener(()=>window.__renderErrors++);
      viewer.scene.primitives.add({update(){throw new Error('Syntetyczny błąd regresji');},isDestroyed(){return false;},destroy(){}});
    });
    await page.waitForTimeout(700);
    observations.injectedRenderError=await page.evaluate(()=>({
      events:window.__renderErrors,panels:document.querySelectorAll('.cesium-widget-errorPanel').length,
      state:document.querySelector('#aircraft3d-dialog').dataset.state,status:document.querySelector('#aircraft3d-status').textContent
    }));
    assert.equal(observations.injectedRenderError.state,'error',JSON.stringify(observations.injectedRenderError));
    assert.match(observations.injectedRenderError.status,/Renderowanie 3D zostało przerwane/);
    assert.equal(observations.injectedRenderError.events,1);
    assert.equal(observations.injectedRenderError.panels,0);
    await page.screenshot({path:path.join(evidence,'render-error-latched.png'),fullPage:true});
    await page.waitForTimeout(600);assert.equal(await page.evaluate(()=>window.__renderErrors),1);
    await page.evaluate(()=>window.WiciAircraft3D.sync({visible:true,enabled:true,mode:'live',hidden:false}));
    await env.next(snapshot([aircraft(Date.now()-2000)]));
    await page.waitForTimeout(600);
    assert.equal(await page.evaluate(()=>window.__renderErrors),1,'Neither visibility sync nor fresh reports may restart a failed scene');
    assert.equal(await page.locator('#aircraft3d-dialog').getAttribute('data-state'),'error');
    await page.locator('#aircraft3d-close').click();
    assert.equal(await page.evaluate(()=>window.__aircraftViewers[0].isDestroyed()),true);
    assert.equal(await page.locator('#aircraft3d-scene canvas').count(),0);
    await env.button.click();await env.rendered();
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.length),2);
    assert.equal(await page.evaluate(()=>window.__aircraftViewers.at(-1).isDestroyed()),false);
    assert.notEqual(await page.locator('#aircraft3d-dialog').getAttribute('data-state'),'error');
    await page.locator('#aircraft3d-close').click();await env.clean();
  }finally{await env.saveRuntime();await env.stop();}
});

test('aircraft 3D: POV follows the displayed course and unlocks when playback reaches it',{timeout:60000},async()=>{
  const env=await environment({name:'displayed-course'});const {page,observations}=env;
  try{
    await env.next(snapshot([aircraft(Date.now()-2000,{track:null})]));
    await env.open();await env.rendered();
    // Keep both course-transition reports recent even when the first engine load is slow.
    await env.next(snapshot([aircraft(Date.now()-2000,{track:null})]));
    assert.equal(await page.locator('#aircraft3d-pov').isDisabled(),true);
    const known=aircraft(Date.now()-2000,{track:90});
    await env.next(snapshot([known]));await page.waitForTimeout(1100);
    assert.match(await page.locator('#aircraft3d-telemetry').textContent(),/Kurs nieznany/);
    assert.equal(await page.locator('#aircraft3d-pov').isDisabled(),true,'A newer source heading cannot authorize POV while delayed playback still has no heading');
    // Exercise the UI handler too, rather than relying only on the disabled attribute.
    await page.locator('#aircraft3d-pov').evaluate(button=>button.dispatchEvent(new MouseEvent('click',{bubbles:true})));
    assert.equal(await page.locator('#aircraft3d-pov').getAttribute('aria-pressed'),'false');
    const repeatedFrom=observations.aircraftTimestamps.length;
    await page.evaluate(()=>{window.__testRealNow=Date.now;Date.now=()=>window.__testRealNow()+14000;});
    await page.waitForFunction(()=>!document.querySelector('#aircraft3d-pov').disabled);
    await page.waitForTimeout(600);
    assert.ok(observations.aircraftTimestamps.length>repeatedFrom,'The ordinary poller must continue while the playback clock advances');
    assert.ok(observations.aircraftTimestamps.slice(repeatedFrom).every(timestamp=>timestamp===known.position_at),'POV must unlock with no newer observation');
    await page.locator('#aircraft3d-pov').click();
    await page.waitForFunction(()=>Math.abs(window.__aircraftViewers.at(-1).camera.heading-Math.PI/2)<.01);
    assert.equal(await page.locator('#aircraft3d-pov').getAttribute('aria-pressed'),'true');
    const pose=await camera(page);assert.ok(Math.abs(pose.heading-Math.PI/2)<.01,'POV must face the displayed eastward course rather than north');
    await page.screenshot({path:path.join(evidence,'displayed-course-pov.png'),fullPage:true});
    await page.locator('#aircraft3d-close').click();await env.clean();
  }finally{
    await page.evaluate(()=>{if(window.__testRealNow)Date.now=window.__testRealNow;});
    await env.saveRuntime();await env.stop();
  }
});

test('aircraft 3D: high zoom Atlas framing stays fixed while the tracked aircraft leaves the viewport',{timeout:60000},async()=>{
  const env=await environment({name:'atlas-high-zoom'});const {page,observations}=env;
  const mapState=()=>page.evaluate(()=>({center:[state.map.getCenter().lat,state.map.getCenter().lng],zoom:state.map.getZoom()}));
  async function assertFraming(expected,stage,{check=true}={}){
    await page.waitForFunction(()=>!state.map._panAnim?._inProgress);
    const actual=await mapState();
    const pixelShift=await page.evaluate(center=>state.map.project(center).distanceTo(state.map.project(state.map.getCenter())),expected.center);
    (observations.atlasFraming||=[]).push({stage,expected,actual,pixelShift});
    assert.equal(actual.zoom,expected.zoom,`Atlas zoom changed ${stage}`);
    if(check)assert.ok(pixelShift<1,`Atlas center shifted ${pixelShift.toFixed(2)} pixels ${stage}`);
    return pixelShift;
  }
  try{
    await page.evaluate(()=>state.map.setView([52.22,20.95],14,{animate:false}));
    let atlas;await env.open(async()=>{
      await page.waitForFunction(()=>!state.map._panAnim?._inProgress);atlas=await mapState();
      await page.evaluate(()=>{
        const marker=Object.values(state.map._layers).find(layer=>layer.aircraft?.hex==='48abcd');
        window.__atlasPopup=marker.getPopup();window.__atlasAutoPan=window.__atlasPopup.options.autoPan;
      });
    });await env.rendered();
    assert.equal(atlas.zoom,14);
    // Source time is fixed after lazy engine loading, so both ten-second report
    // intervals remain fresh and continuous even on slow software WebGL hosts.
    const base=Date.now();
    await page.evaluate(base=>{window.__atlasRealNow=Date.now;window.__atlasClock=base;Date.now=()=>window.__atlasClock;},base);
    await env.next(snapshot([aircraft(base-18000)]));
    const before=await camera(page);
    await env.next(snapshot([aircraft(base-8000,{longitude:20.98})]));
    await page.waitForFunction(()=>Object.values(state.map._layers).some(layer=>layer.aircraft?.longitude===20.98));
    await page.waitForFunction(before=>{const p=window.__aircraftViewers.at(-1).camera.positionWC;return Math.hypot(p.x-before.x,p.y-before.y,p.z-before.z)>100;},before);
    const updateShifts=[await assertFraming(atlas,'during 3D after the first position update',{check:false})];
    await page.evaluate(base=>window.__atlasClock=base+2000,base);
    await env.next(snapshot([aircraft(base+2000,{longitude:21.01})]));
    await page.waitForFunction(()=>Object.values(state.map._layers).some(layer=>layer.aircraft?.longitude===21.01));
    updateShifts.push(await assertFraming(atlas,'during 3D after the second position update',{check:false}));
    assert.ok(updateShifts.every(shift=>shift<1),`Atlas center shifted up to ${Math.max(...updateShifts).toFixed(2)} pixels during 3D; report shifts: ${updateShifts.map(shift=>shift.toFixed(2)).join(', ')}`);
    observations.followDistance=distance(before,await camera(page));
    assert.ok(observations.followDistance>100,'The real 3D camera must still follow the moving aircraft');
    await page.screenshot({path:path.join(evidence,'atlas-high-zoom-tracking.png'),fullPage:true});
    await page.locator('#aircraft3d-close').click();
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
    assert.equal(await page.evaluate(()=>state.map.hasLayer(window.__atlasPopup)),false,'An offscreen popup must close before focus returns to Atlas');
    assert.equal(await page.locator('#map').evaluate(element=>document.activeElement===element),true,'Returning focus to an offscreen popup button must not pan Atlas');
    assert.equal(await page.evaluate(()=>window.__atlasPopup.options.autoPan),await page.evaluate(()=>window.__atlasAutoPan),'The original popup auto-pan option must be restored');
    await assertFraming(atlas,'after returning from 3D');
    await page.evaluate(base=>window.__atlasClock=base+12000,base);
    await env.next(snapshot([aircraft(base+12000,{longitude:21.04})]));
    await page.waitForFunction(()=>Object.values(state.map._layers).some(layer=>layer.aircraft?.longitude===21.04));
    await assertFraming(atlas,'after the next ordinary Atlas feed update');
    await page.screenshot({path:path.join(evidence,'atlas-high-zoom-return.png'),fullPage:true});
    // A later explicit popup opening should retain Leaflet's normal auto-pan.
    // Place the marker near the right edge so the popup really needs more room.
    const beforeReopen=await page.evaluate(()=>{
      const marker=Object.values(state.map._layers).find(layer=>layer.aircraft?.hex==='48abcd');
      const point=state.map.project(marker.getLatLng()),offset=L.point(state.map.getSize().x/2-30,0);
      state.map.setView(state.map.unproject(point.subtract(offset)),14,{animate:false});
      return [state.map.getCenter().lat,state.map.getCenter().lng];
    });
    await page.evaluate(()=>Object.values(state.map._layers).find(layer=>layer.aircraft?.hex==='48abcd').openPopup());
    await page.waitForFunction(()=>!state.map._panAnim?._inProgress);
    observations.restoredAutoPanShift=await page.evaluate(center=>state.map.project(center).distanceTo(state.map.project(state.map.getCenter())),beforeReopen);
    assert.ok(observations.restoredAutoPanShift>20,'Explicitly reopening the popup must restore normal Leaflet auto-pan');
    await env.clean();
  }finally{
    await page.evaluate(()=>{if(window.__atlasRealNow)Date.now=window.__atlasRealNow;});
    await env.saveRuntime();await env.stop();
  }
});
