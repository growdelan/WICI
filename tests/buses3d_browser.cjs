// Real Cesium/WebGL + Leaflet, synthetic city feeds, network-forbidden DEMO backend.
// NODE_PATH=/path/to/node_modules node --test tests/buses3d_browser.cjs
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {environment,bus,busSnapshot,aircraft,snapshot,camera,distance,root}=require('./helpers/vehicle3d_browser.cjs');
const evidence=path.join(root,'tmp/buses3d-evidence');fs.mkdirSync(evidence,{recursive:true});
const create=options=>environment({kind:'bus',...options});
const data=(at,changes={})=>busSnapshot([bus(at,changes)]);
const status=page=>page.locator('#aircraft3d-status').textContent();
const state=page=>page.locator('#aircraft3d-dialog').getAttribute('data-state');
const setLayer=(page,enabled)=>page.evaluate(enabled=>{const input=document.querySelector('#buses-enabled');input.checked=enabled;input.dispatchEvent(new Event('change'));},enabled);
async function clock(page,now=Date.now()){
  await page.evaluate(now=>{window.__busRealNow=Date.now;window.__busClockOffset=now-window.__busRealNow();Date.now=()=>window.__busRealNow()+window.__busClockOffset;},now);return now;
}
const advance=(page,now)=>page.evaluate(now=>window.__busClockOffset=now-window.__busRealNow(),now);
const restore=page=>page.evaluate(()=>{if(window.__busRealNow)Date.now=window.__busRealNow;});
async function modelReady(page){
  await page.waitForFunction(()=>{
    const C=window.Cesium,view=window.__vehicleViewers.at(-1);
    return view.scene.primitives._primitives.some(primitive=>primitive instanceof C.Model&&primitive.ready);
  });
  return page.evaluate(()=>{
    const C=window.Cesium,view=window.__vehicleViewers.at(-1),entity=view.entities.values.find(entity=>entity.model);
    const uri=entity.model.uri.getValue(C.JulianDate.now());
    return{uri:typeof uri==='string'?uri:uri.url,height:C.Cartographic.fromCartesian(entity.position.getValue(C.JulianDate.now())).height};
  });
}
async function modelCourse(page){
  return page.evaluate(()=>{
    const C=window.Cesium,view=window.__vehicleViewers.at(-1);
    const model=view.scene.primitives._primitives.find(primitive=>primitive instanceof C.Model&&primitive.ready);
    // The authored glTF's front is +X. The scene-graph matrix includes Cesium's
    // glTF-axis correction, which an entity quaternion alone cannot verify.
    const matrix=model.sceneGraph.computedModelMatrix;
    const origin=C.Matrix4.multiplyByPoint(matrix,C.Cartesian3.ZERO,new C.Cartesian3());
    const front=C.Matrix4.multiplyByPoint(matrix,C.Cartesian3.UNIT_X,new C.Cartesian3());
    const local=C.Matrix4.multiplyByPoint(C.Matrix4.inverseTransformation(C.Transforms.eastNorthUpToFixedFrame(origin),new C.Matrix4()),front,new C.Cartesian3());
    return((C.Math.toDegrees(Math.atan2(local.x,local.y))%360)+360)%360;
  });
}
async function closed(page){
  assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),false);
  assert.equal(await page.evaluate(()=>window.__vehicleViewers.every(view=>view.isDestroyed())),true);
  assert.equal(await page.locator('#aircraft3d-scene canvas').count(),0);
}

test('bus 3D: local model, both cameras, existing poller, held reports and recovery',{timeout:120000},async()=>{
  const env=await create({name:'desktop-follow-pov'}),{page,observations,feed}=env;
  try{
    assert.deepEqual(observations.vendor,[]);const existingReads=observations.busReads;
    await env.open();await env.rendered();
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.at(-1).scene.context.webgl2),true);
    const model=await modelReady(page);assert.equal(model.uri,'/static/models/bus.gltf');assert.ok(Math.abs(model.height)<.1,'A bus must remain on the surface rather than inheriting aircraft altitude');
    observations.modelFrontCourse=await modelCourse(page);
    assert.ok(Math.abs(observations.modelFrontCourse-90)<.1,`Rendered glTF front must face the source course, got ${observations.modelFrontCourse}°`);
    assert.match(await page.locator('#aircraft3d-title').textContent(),/75/);
    assert.equal(await page.locator('#aircraft3d-behind').textContent(),'Za autobusem');
    assert.equal(await page.locator('#aircraft3d-distance').getAttribute('min'),'15');
    assert.equal(await page.locator('#aircraft3d-distance').getAttribute('max'),'500');
    assert.equal(await page.locator('#aircraft3d-distance').inputValue(),'70');
    assert.equal(await page.locator('#aircraft3d-follow').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#aircraft3d-osm').isChecked(),false);
    assert.equal(observations.models.filter(uri=>uri==='/static/models/bus.gltf').length,1);
    const now=await clock(page);
    await env.next(data(now-18000));const before=await camera(page);
    await env.next(data(now-8000,{longitude:14.5543}));
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='interpolated');
    await page.waitForFunction(before=>{const p=window.__vehicleViewers.at(-1).camera.positionWC;return Math.hypot(p.x-before.x,p.y-before.y,p.z-before.z)>30;},before);
    const moving=await camera(page);assert.ok(distance(before,moving)>30);
    await page.locator('#aircraft3d-pov').click();await page.waitForTimeout(250);
    assert.equal(await page.locator('#aircraft3d-pov').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#aircraft3d-distance-control').isVisible(),false);
    const pov=await camera(page);assert.ok(distance(pov,moving)>30);
    const povHeight=await page.evaluate(()=>window.Cesium.Cartographic.fromCartesian(window.__vehicleViewers.at(-1).camera.positionWC).height);
    assert.ok(povHeight>2&&povHeight<2.5,`POV eye height must be ground level, got ${povHeight}`);
    assert.ok(Math.abs(pov.heading-Math.PI/2)<.02,'The driver view must face the source course');
    assert.ok(Math.abs(pov.heading*180/Math.PI-observations.modelFrontCourse)<1,'The visible bus front and driver camera must point in the same world direction');
    assert.doesNotMatch(await page.locator('#aircraft3d-telemetry').textContent(),/Wysokość barometryczna/);
    await page.screenshot({path:path.join(evidence,'desktop-pov.png'),fullPage:true});
    await page.locator('#aircraft3d-follow').click();await page.locator('#aircraft3d-distance').fill('200');await page.locator('#aircraft3d-distance').dispatchEvent('input');
    assert.equal(await page.locator('#aircraft3d-distance-value').textContent(),'200 m');
    await page.screenshot({path:path.join(evidence,'desktop-follow.png'),fullPage:true});
    // A bus stops at the last delayed report; it must never fly onward using aircraft prediction.
    await advance(page,now+15000);await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='holding');
    assert.doesNotMatch(await status(page),/predykcja|przewidywania/);
    await page.waitForTimeout(400);const parked=await camera(page);await page.waitForTimeout(350);assert.ok(distance(parked,await camera(page))<.1);
    await env.next({...feed.body,stale:true,status:'error'});await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Odczyt niedostępny'));
    const unavailable=await camera(page);await page.waitForTimeout(250);assert.ok(distance(unavailable,await camera(page))<.1);
    await env.next(busSnapshot([]));await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Brak autobusu'));
    await env.next(data(now+15000),{fail:true});await page.waitForFunction(()=>document.querySelector('#aircraft3d-status').textContent.includes('Odczyt niedostępny'));
    await env.next(data(now+15000,{longitude:14.5543}));await page.waitForFunction(()=>!['stale','error'].includes(document.querySelector('#aircraft3d-dialog').dataset.state)&&!document.querySelector('#aircraft3d-status').textContent.includes('Odczyt niedostępny'));
    await advance(page,now+76000);await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='stale');assert.match(await status(page),/60 s/);
    await env.next(data(now+76000,{longitude:14.5543}));await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='warming');
    await page.locator('#aircraft3d-close').click();await closed(page);
    assert.equal(observations.vendor.filter(uri=>uri.endsWith('/Cesium.js')).length,1);
    // Hundreds of render frames must reuse the one scheduled city reader.
    assert.ok(observations.busReads-existingReads<100,'3D must not add a per-frame poller');
    const callers=await page.evaluate(()=>window.__busFetchCallers);
    assert.ok(callers.length>1);assert.ok(callers.every(stack=>stack.includes('/static/js/buses.js:')),'Only the existing city layer reader may fetch the city feed');
    assert.ok(observations.busCities.every(city=>city==='szczecin'));
    await env.clean();
  }finally{await restore(page);await env.saveRuntime();await env.stop();}
});

test('bus 3D: all-lines tracking refreshes the same model label in both cameras and ignores older reports',{timeout:90000},async()=>{
  const env=await create({holdVendor:true,name:'all-lines-model-label'}),{page,observations}=env;
  async function assertLabel(line){
    const actual=await page.evaluate(()=>{
      const C=window.Cesium,saved=window.__busLabelRegression,view=window.__vehicleViewers.at(-1);
      const entity=view.entities.values.find(entity=>entity.model);
      return{
        name:entity.name,text:entity.label.text.getValue(C.JulianDate.now()),
        sameViewer:view===saved.viewer,sameEntity:entity===saved.entity,
        sameModel:view.scene.primitives._primitives.includes(saved.model),
        viewerCount:window.__vehicleViewers.length
      };
    });
    const expected=`Autobus · linia ${line} · TEST3D`;
    assert.equal(actual.text,expected,'The Cesium label must follow the accepted line without reopening 3D');
    assert.equal(actual.name,expected,'The existing Cesium entity name must follow the accepted line');
    assert.equal(await page.locator('#aircraft3d-title').textContent(),`${expected} · śledzenie 3D`);
    assert.equal(actual.sameViewer,true);assert.equal(actual.sameEntity,true);assert.equal(actual.sameModel,true);
    assert.equal(actual.viewerCount,1);assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),true);
    assert.equal(await page.locator('#buses-line').inputValue(),'','Tracking must remain outside any line filter');
  }
  try{
    assert.equal(await page.locator('#buses-line').inputValue(),'');
    await env.next(data(Date.now()-18000,{line:'74'}));
    await page.waitForFunction(()=>Object.values(state.map._layers).some(marker=>marker.bus?.line==='74'));
    await env.open();await env.vendorEntered;
    // A feed error during engine loading must not restore the label captured by open().
    const loadingReport=data(Date.now()-8000,{line:'75'});
    await env.next(loadingReport);
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-title').textContent.includes('linia 75'));
    await env.next({...loadingReport,stale:true,status:'error'});
    await page.waitForFunction(()=>document.querySelector('#buses-status').textContent.includes('dane nieaktualne'));
    env.releaseVendor();await env.rendered();await modelReady(page);
    await page.evaluate(()=>{
      const C=window.Cesium,viewer=window.__vehicleViewers.at(-1);
      window.__busLabelRegression={viewer,entity:viewer.entities.values.find(entity=>entity.model),
        model:viewer.scene.primitives._primitives.find(primitive=>primitive instanceof C.Model&&primitive.ready)};
    });
    await assertLabel('75');const now=await clock(page);
    await env.next(data(now-18000));
    await env.next(data(now-8000,{line:'80',longitude:14.5543}));
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-title').textContent.includes('linia 80'));
    await assertLabel('80');
    await page.waitForFunction(()=>!document.querySelector('#aircraft3d-pov').disabled);
    await page.locator('#aircraft3d-pov').click();
    await env.next(data(now+2000,{line:'81',longitude:14.5553}));
    await page.waitForFunction(()=>document.querySelector('#aircraft3d-title').textContent.includes('linia 81'));
    assert.equal(await page.locator('#aircraft3d-pov').getAttribute('aria-pressed'),'true');
    await assertLabel('81');
    // The city layer accepts this late snapshot, but 3D must retain its newer identity label.
    await env.next(data(now-3000,{line:'79',longitude:14.5548}));
    await page.waitForFunction(()=>Object.values(state.map._layers).some(marker=>marker.bus?.id==='szczecin:test3d'&&marker.bus.line==='79'));
    await assertLabel('81');
    await page.locator('#aircraft3d-follow').click();
    assert.equal(await page.locator('#aircraft3d-follow').getAttribute('aria-pressed'),'true');
    await assertLabel('81');assert.equal(observations.models.filter(uri=>uri==='/static/models/bus.gltf').length,1);
    await page.locator('#aircraft3d-close').click();await closed(page);await env.clean();
  }finally{await restore(page);await env.saveRuntime();await env.stop();}
});

test('bus 3D: estimated course belongs to delayed playback and rejected reports cannot turn the camera',{timeout:90000},async()=>{
  const env=await create({name:'estimated-course'}),{page,observations}=env;
  try{
    await env.next(data(Date.now()-2000,{bearing:null,speed_kmh:null}));await env.open();await env.rendered();
    const now=await clock(page);await env.next(data(now-4000,{bearing:null,speed_kmh:null}));
    assert.equal(await page.locator('#aircraft3d-pov').isDisabled(),true);assert.match(await page.locator('#aircraft3d-telemetry').textContent(),/Kurs nieznany/);
    const newer=bus(now,{bearing:null,speed_kmh:null,longitude:14.5533});
    await env.next(busSnapshot([newer]));await page.waitForTimeout(1100);
    assert.equal(await page.locator('#aircraft3d-pov').isDisabled(),true,'A newer estimated bearing must not unlock POV before the delayed position has reached it');
    await page.locator('#aircraft3d-pov').dispatchEvent('click');assert.equal(await page.locator('#aircraft3d-follow').getAttribute('aria-pressed'),'true');
    const sourceTimestamp=newer.position_at;
    await advance(page,now+14000);await page.waitForFunction(()=>!document.querySelector('#aircraft3d-pov').disabled);
    assert.equal(observations.busTimestamps.at(-1),sourceTimestamp,'POV must unlock without needing another observation');
    await page.waitForTimeout(1100);assert.match(await page.locator('#aircraft3d-telemetry').textContent(),/Kurs szacowany z pozycji 90°/);
    await page.locator('#aircraft3d-pov').click();await page.waitForTimeout(150);const east=await camera(page);assert.ok(Math.abs(east.heading-Math.PI/2)<.02);
    const acceptedTime=(await page.locator('#aircraft3d-time').textContent()).split(' · ')[0];
    // Equal-time replacement and reverse-time observations must not rewrite accepted position/course.
    await env.next(data(now,{bearing:270,longitude:14.4}));await env.next(data(now-1000,{bearing:180,longitude:14.3}));await page.waitForTimeout(1100);
    assert.equal((await page.locator('#aircraft3d-time').textContent()).split(' · ')[0],acceptedTime);
    assert.ok(distance(east,await camera(page))<.1);assert.match(await page.locator('#aircraft3d-telemetry').textContent(),/Kurs szacowany z pozycji 90°/);
    // A discontinuous report must reanchor instead of drawing a fictitious route across the city.
    await env.next(data(now+14000,{bearing:null,speed_kmh:null,longitude:14.7}));await page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='warming');
    assert.equal(await page.locator('#aircraft3d-pov').isDisabled(),true);assert.equal(await page.locator('#aircraft3d-follow').getAttribute('aria-pressed'),'true');
    await page.screenshot({path:path.join(evidence,'estimated-course.png'),fullPage:true});await page.locator('#aircraft3d-close').click();await env.clean();
  }finally{await restore(page);await env.saveRuntime();await env.stop();}
});

test('bus 3D: city, line, layer, view and region transitions close graphics; hidden tab pauses',{timeout:120000},async()=>{
  const env=await create({name:'lifecycle'}),{page,feed,observations}=env;
  async function reopen(){feed.body=data(Date.now()-2000);feed.fail=false;await page.locator('.buses-marker').first().waitFor();await env.open();await env.rendered();}
  try{
    await env.open();await env.rendered();
    const busViewerCount=await page.evaluate(()=>window.__vehicleViewers.length);
    await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
    const paused=await camera(page);feed.body=data(Date.now(),{longitude:14.5533});
    await page.waitForTimeout(200);const hiddenReads=observations.busReads;await page.waitForTimeout(650);
    assert.ok(distance(paused,await camera(page))<.1);assert.equal(observations.busReads,hiddenReads,'A hidden tab must stop the existing city reader');
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),true);
    await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForFunction(()=>document.querySelector('.buses-marker'));
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.length),busViewerCount);
    await page.evaluate(()=>{const line=document.querySelector('#buses-line');line.append(new Option('80','80'));line.value='80';line.dispatchEvent(new Event('change'));});await closed(page);
    await page.evaluate(()=>{const line=document.querySelector('#buses-line');line.value='';line.dispatchEvent(new Event('change'));});await reopen();
    await setLayer(page,false);await closed(page);await page.waitForTimeout(200);const stopped=observations.busReads;await page.waitForTimeout(650);assert.equal(observations.busReads,stopped);
    feed.body=data(Date.now()-2000);await setLayer(page,true);await reopen();
    // City identity is part of the selection: a coincident vehicle id cannot continue in another city.
    feed.body=data(Date.now()-2000,{id:'krakow:test3d',latitude:50.0647,longitude:19.945,line:'179'});
    await page.evaluate(()=>{const city=document.querySelector('#buses-city');city.value='krakow';city.dispatchEvent(new Event('change'));});await closed(page);
    await page.waitForFunction(()=>Object.values(state.map._layers).some(marker=>marker.bus?.id==='krakow:test3d'));
    await page.evaluate(()=>state.map.setView([50.0647,19.945],7,{animate:false}));await env.open();await env.rendered();assert.equal(observations.busCities.at(-1),'krakow');
    await page.evaluate(()=>document.querySelector('.tab[data-view="sources"]').click());await closed(page);
    feed.body=data(Date.now()-2000,{id:'krakow:test3d',latitude:50.0647,longitude:19.945,line:'179'});
    await page.locator('.tab[data-view="situation"]').click();await page.locator('.buses-marker').first().waitFor();await env.open();await env.rendered();
    await page.evaluate(()=>document.dispatchEvent(new Event('wici:regionchange')));await closed(page);
    assert.equal(observations.vendor.filter(uri=>uri.endsWith('/Cesium.js')).length,1);await env.clean();
  }finally{await env.saveRuntime();await env.stop();}
});

test('bus and aircraft 3D: switching owns one renderer and unrelated feed/sync cannot change its selection',{timeout:120000},async()=>{
  const env=await create({name:'shared-owner'}),{page,feed,observations}=env;
  try{
    await env.open();await env.rendered();await modelReady(page);
    const busTitle=await page.locator('#aircraft3d-title').textContent();
    feed.aircraftBody=snapshot([aircraft(Date.now()-2000)]);
    await page.evaluate(()=>{const input=document.querySelector('#aircraft-enabled');input.checked=true;input.dispatchEvent(new Event('change'));});
    await page.waitForFunction(()=>document.querySelector('.aircraft-marker'));
    await page.waitForTimeout(500);assert.ok(observations.aircraftReads>0);
    await page.evaluate(payload=>{window.WiciAircraft3D.update(payload);window.WiciAircraft3D.sync({visible:false,enabled:false,mode:'demo',hidden:false});},snapshot([aircraft()]));
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),true);assert.equal(await page.locator('#aircraft3d-title').textContent(),busTitle);
    feed.aircraftBody=snapshot([aircraft(Date.now()-2000)]);
    await page.evaluate(payload=>window.WiciAircraft3D.open(payload.items[0],payload,document.querySelector('#map')),feed.aircraftBody);await env.rendered();
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.length),2);assert.equal(await page.evaluate(()=>window.__vehicleViewers[0].isDestroyed()),true);
    assert.equal((await modelReady(page)).uri,'/static/models/aircraft.gltf');assert.equal(await page.locator('#aircraft3d-behind').textContent(),'Za samolotem');const aircraftTitle=await page.locator('#aircraft3d-title').textContent();
    await env.next(data(Date.now()-2000,{line:'99'}));await page.evaluate(()=>window.WiciBuses3D.sync({visible:false,enabled:false,mode:'demo',hidden:false,city:'krakow',line:'80'}));
    assert.equal(await page.locator('#aircraft3d-dialog').isVisible(),true);assert.equal(await page.locator('#aircraft3d-title').textContent(),aircraftTitle);
    const fresh=data(Date.now()-2000,{line:'75'});feed.body=fresh;
    await page.evaluate(payload=>window.WiciBuses3D.open(payload.items[0],payload,document.querySelector('#map'),null,{city:'szczecin',source:{name:'Szczecin',source:'ZDiTM Szczecin'}}),fresh);await env.rendered();
    assert.equal((await modelReady(page)).uri,'/static/models/bus.gltf');assert.equal(await page.evaluate(()=>window.__vehicleViewers.length),3);
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.filter(view=>!view.isDestroyed()).length),1);
    assert.equal(await page.locator('#aircraft3d-scene canvas').count(),1);assert.equal(observations.vendor.filter(uri=>uri.endsWith('/Cesium.js')).length,1);
    await page.locator('#aircraft3d-close').click();await closed(page);await env.clean();
  }finally{await env.saveRuntime();await env.stop();}
});

test('bus 3D: high zoom Atlas keeps its frame and restores offscreen popup behavior and focus',{timeout:90000},async()=>{
  const env=await create({name:'atlas-high-zoom'}),{page,observations}=env;
  let atlas;
  async function assertFrame(stage){
    await page.waitForFunction(()=>!state.map._panAnim?._inProgress);
    const actual=await page.evaluate(center=>({zoom:state.map.getZoom(),shift:state.map.project(center).distanceTo(state.map.project(state.map.getCenter()))}),atlas.center);
    (observations.atlasFraming||=[]).push({stage,...actual});assert.equal(actual.zoom,14);assert.ok(actual.shift<1,`Atlas shifted ${actual.shift}px ${stage}`);
  }
  try{
    await page.evaluate(()=>state.map.setView([53.4285,14.5528],14,{animate:false}));
    await env.open(async()=>{
      await page.waitForFunction(()=>!state.map._panAnim?._inProgress);
      atlas=await page.evaluate(()=>{const marker=Object.values(state.map._layers).find(marker=>marker.bus?.id==='szczecin:test3d');window.__busPopup=marker.getPopup();return{center:[state.map.getCenter().lat,state.map.getCenter().lng],autoPan:window.__busPopup.options.autoPan};});
    });await env.rendered();const now=await clock(page);
    await env.next(data(now-18000));const before=await camera(page);
    await env.next(data(now-8000,{longitude:14.5553}));await page.waitForFunction(()=>Object.values(state.map._layers).some(marker=>marker.bus?.longitude===14.5553));await assertFrame('during 3D first update');
    await advance(page,now+50000);await env.next(data(now+42000,{longitude:14.5853}));await page.waitForFunction(()=>Object.values(state.map._layers).some(marker=>marker.bus?.longitude===14.5853));await assertFrame('during 3D offscreen update');
    await page.waitForFunction(before=>{const p=window.__vehicleViewers.at(-1).camera.positionWC;return Math.hypot(p.x-before.x,p.y-before.y,p.z-before.z)>30;},before);
    observations.followDistance=distance(before,await camera(page));await page.screenshot({path:path.join(evidence,'atlas-high-zoom-tracking.png'),fullPage:true});
    await page.locator('#aircraft3d-close').click();await closed(page);
    assert.equal(await page.evaluate(()=>state.map.hasLayer(window.__busPopup)),false);assert.equal(await page.evaluate(()=>window.__busPopup.options.autoPan),atlas.autoPan);
    assert.equal(await page.locator('#map').evaluate(element=>document.activeElement===element),true);await assertFrame('after closing 3D');
    await advance(page,now+70000);await env.next(data(now+62000,{longitude:14.5863}));await page.waitForFunction(()=>Object.values(state.map._layers).some(marker=>marker.bus?.longitude===14.5863));await assertFrame('after ordinary Atlas refresh');
    const center=await page.evaluate(()=>{const marker=Object.values(state.map._layers).find(marker=>marker.bus?.id==='szczecin:test3d'),point=state.map.project(marker.getLatLng()),offset=L.point(state.map.getSize().x/2-30,0);state.map.setView(state.map.unproject(point.subtract(offset)),14,{animate:false});return[state.map.getCenter().lat,state.map.getCenter().lng];});
    await page.evaluate(()=>Object.values(state.map._layers).find(marker=>marker.bus?.id==='szczecin:test3d').openPopup());await page.waitForFunction(()=>!state.map._panAnim?._inProgress);
    observations.restoredAutoPanShift=await page.evaluate(center=>state.map.project(center).distanceTo(state.map.project(state.map.getCenter())),center);assert.ok(observations.restoredAutoPanShift>20);
    await env.clean();
  }finally{await restore(page);await env.saveRuntime();await env.stop();}
});

test('bus 3D: lazy cancellation leaves no viewer and missing WebGL retains an accessible exit',{timeout:120000},async()=>{
  const loading=await create({holdVendor:true,name:'lazy-cancel'});
  try{
    await loading.open();await loading.vendorEntered;await loading.page.locator('#aircraft3d-close').click();loading.releaseVendor();await loading.page.waitForFunction(()=>Boolean(window.Cesium));await loading.page.waitForTimeout(150);
    assert.equal(await loading.page.evaluate(()=>window.__vehicleViewers.length),0);assert.equal(await loading.page.locator('#aircraft3d-scene canvas').count(),0);
    await loading.button.click();await loading.rendered();await modelReady(loading.page);await loading.page.locator('#aircraft3d-close').click();await closed(loading.page);await loading.clean();
  }finally{await loading.saveRuntime();await loading.stop();}
  const unavailable=await create({noWebgl:true,name:'webgl-unavailable'});
  try{
    await unavailable.open();await unavailable.page.waitForFunction(()=>document.querySelector('#aircraft3d-dialog').dataset.state==='error');assert.match(await status(unavailable.page),/WebGL 2/);assert.equal(await unavailable.page.locator('#aircraft3d-close').isEnabled(),true);
    await unavailable.page.keyboard.press('Escape');assert.equal(await unavailable.page.locator('#aircraft3d-dialog').isVisible(),false);assert.equal(await unavailable.button.evaluate(button=>document.activeElement===button),true);await unavailable.clean();
  }finally{await unavailable.saveRuntime();await unavailable.stop();}
});

test('bus 3D: mobile 390px light and dark themes render both camera controls without overflow',{timeout:120000},async()=>{
  for(const theme of ['light','dark']){
    const env=await create({viewport:{width:390,height:844},theme,name:`mobile-${theme}`}),{page}=env;
    try{
      await env.open();await env.rendered();await modelReady(page);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      const bounds=await page.locator('#aircraft3d-dialog').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=391);
      await page.screenshot({path:path.join(evidence,`mobile-${theme}-follow.png`)});await page.locator('#aircraft3d-pov').click();await page.waitForTimeout(150);assert.equal(await page.locator('#aircraft3d-pov').getAttribute('aria-pressed'),'true');await page.screenshot({path:path.join(evidence,`mobile-${theme}-pov.png`)});
      await page.locator('#aircraft3d-close').click();await closed(page);await env.clean();
    }finally{await env.saveRuntime();await env.stop();}
  }
});
