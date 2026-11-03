// Real WebGL, synthetic heightfields/municipal records, isolated offline backend.
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {environment,aircraft,snapshot,bus,busSnapshot,root}=require('./helpers/vehicle3d_browser.cjs');
async function source(page,{fail=false,failBuildings=false,terrainHeight=110,terrainDelay=0}={}) {
  const calls=[];
  await page.route('**/api/scene3d/**',async route=>{
    const url=new URL(route.request().url());calls.push(url.pathname);
    if(fail)return route.fulfill({json:{status:'unavailable',message:'Syntetyczna awaria'}});
    if(url.pathname.includes('/terrain/')){if(terrainDelay)await new Promise(resolve=>setTimeout(resolve,terrainDelay));return route.fulfill({json:{status:'ready',size:65,heights:Array(65*65).fill(terrainHeight)}});}
    const [x,y]=url.pathname.split('/').slice(-2).map(Number),step=180/2**14;
    if(url.pathname.includes('/buildings/')){
      if(failBuildings)return route.fulfill({json:{status:'unavailable'}});
      const point=(u,v)=>[(x+u)/2**14*360-180,Math.atan(Math.sinh(Math.PI*(1-2*(y+v)/2**14)))*180/Math.PI];
      const ring=(u,v,r)=>[point(u-r,v-r),point(u+r,v-r),point(u+r,v+r),point(u-r,v+r),point(u-r,v-r)];
      return route.fulfill({json:{status:'ready',items:Array.from({length:100},(_,i)=>{
        const u=.02+(i%10)*.1,v=.02+Math.floor(i/10)*.1;
        return{id:`synthetic-building-${x}-${y}-${i}`,rings:[ring(u,v,.012),...(i===0?[ring(u,v,.004)]:[])],height:30,min_height:0};
      })}});
    }
    return route.fulfill({json:{status:'ready',source:'Urząd m.st. Warszawy',source_dates:['01.01.2026'],fetched_at:'2026-11-03T12:00:00Z',
      items:Array.from({length:12},(_,i)=>({id:`synthetic-${x}-${y}-${i}`,longitude:-180+(x+.3+i*.03)*step,latitude:90-(y+.5)*step,height:10,diameter:5,estimated:i%2===0}))}});
  });
  return calls;
}
const treePrimitive=()=>{
  const v=window.__vehicleViewers.at(-1);
  return v && Array.from({length:v.scene.primitives.length},(_,i)=>v.scene.primitives.get(i)).some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.flat&&p.ready);
};

const buildingPrimitive=()=>{
  const v=window.__vehicleViewers.at(-1);
  return v&&Array.from({length:v.scene.primitives.length},(_,i)=>v.scene.primitives.get(i)).some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed&&p.ready);
};
async function buildingsVisible(page){
  // Terrain arrival can change the camera's ground target and replace an old
  // ready batch. Wait for the current terrain/environment, and sample atomically.
  const handle=await page.waitForFunction(()=>{
    const v=window.__vehicleViewers.at(-1);
    if(!v||!v.scene.globe.tilesLoaded)return false;
    const status=document.querySelector(document.querySelector('#aircraft3d-dialog').open?'#aircraft3d-environment-status':'#atlas3d-status').textContent;
    if(status.includes('ładowanie'))return false;
    const batches=Array.from({length:v.scene.primitives.length},(_,i)=>v.scene.primitives.get(i)).filter(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed&&p.ready);
    return batches.length&&{batches:batches.length,instances:batches[0]._instanceIds.length,entities:v.entities.values.length,status};
  });
  const metrics=await handle.jsonValue();await handle.dispose();
  assert.equal(metrics.batches,1,'Buildings must use one GPU batch');
  assert.ok(metrics.instances>0&&metrics.instances<=3000,`Visible building budget: ${metrics.instances}`);
  return metrics;
}

test('Buildings cover viewport corners, follow zoom within the same tile and reuse cached tiles',{timeout:60000},async()=>{
  const env=await environment();const {page}=env;
  try{
    const calls=await source(page);
    await page.evaluate(()=>state.map.setView([50.82,16.28],16,{animate:false}));
    await page.locator('#atlas3d-toggle').click();await buildingsVisible(page);
    const inspect=()=>{
      const C=Cesium,v=window.__vehicleViewers.at(-1),point=window.WiciScene3D.groundTarget(v),p=C.Cartographic.fromCartesian(point);
      const lon=C.Math.toDegrees(p.longitude),lat=C.Math.toDegrees(p.latitude),region=window.WiciBuildings3D.coverage(v,lon,lat);
      const scheme=new C.WebMercatorTilingScheme(),tile=scheme.positionToTileXY(p,14),corners=[];
      for(const x of [0,v.canvas.clientWidth])for(const y of [0,v.canvas.clientHeight]){
        const ground=v.scene.globe.pick(v.camera.getPickRay(new C.Cartesian2(x,y)),v.scene);
        const t=scheme.positionToTileXY(C.Cartographic.fromCartesian(ground),14);corners.push(`${t.x}/${t.y}`);
      }
      return{key:region.key,tile:`${tile.x}/${tile.y}`,tiles:region.tiles.map(t=>t.key),required:region.tiles.filter(t=>t.required).map(t=>t.key),corners,limited:region.limited};
    };
    const close=await page.evaluate(inspect);
    // Keep exactly the same target; only the camera range changes.
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);window.__zoomGround=window.WiciScene3D.groundTarget(v);v.camera.lookAt(window.__zoomGround,new Cesium.HeadingPitchRange(0,-.8,1800));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('ładowanie'));
    await buildingsVisible(page);
    const wide=await page.evaluate(inspect);
    assert.equal(wide.tile,close.tile);assert.notEqual(wide.key,close.key);
    assert.equal(wide.limited,false);assert.ok(wide.tiles.length<=25);
    for(const corner of wide.corners)assert.ok(wide.required.includes(corner),`Missing corner tile ${corner}`);
    assert.ok(new Set(wide.corners).size>=4,'Fixture must straddle tile boundaries, including diagonal neighbours');
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);v.camera.lookAt(window.__zoomGround,new Cesium.HeadingPitchRange(0,-.8,700));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('ładowanie'));
    await buildingsVisible(page);
    const reads=calls.filter(url=>url.includes('/buildings/'));
    assert.equal(reads.length,new Set(reads).size,'Zooming back must reuse downloaded source tiles');
    const selected=await page.evaluate(()=>{
      const outside=Array.from({length:3100},(_,i)=>({id:`outside-${i}`,rings:[[[20,50],[20.001,50],[20.001,50.001],[20,50.001],[20,50]]]}));
      const inside={id:'visible-last',rings:[[[16.28,50.82],[16.281,50.82],[16.281,50.821],[16.28,50.821],[16.28,50.82]]]};
      return window.WiciBuildings3D.select([{items:[...outside,inside]}],[16.27,50.81,16.29,50.83],16.28,50.82).selected.map(v=>v.item.id);
    });
    assert.deepEqual(selected,['visible-last'],'Offscreen records must not exhaust the visible building budget');
    await page.locator('#atlas3d-toggle').click();await env.clean();
  }finally{await env.stop();}
});

test('Buildings retain ready geometry through slow downloads and failure, then retry the same view without gaps',{timeout:90000},async()=>{
  const env=await environment();const {page}=env;
  let release;
  try{
    await source(page);
    await page.evaluate(()=>state.map.setView([52.225,21.006],16,{animate:false}));
    await page.locator('#atlas3d-toggle').click();await buildingsVisible(page);
    await page.evaluate(()=>{
      const v=window.__vehicleViewers.at(-1);
      window.__oldBuildings=v.scene.primitives._primitives.find(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed&&p.ready);
      window.__emptyBuildingFrames=0;
      v.scene.postRender.addEventListener(()=>{if(!v.scene.primitives._primitives.some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed&&p.ready))window.__emptyBuildingFrames++;});
    });
    let fail=true;const reads=[];const gate=new Promise(resolve=>release=resolve);
    await page.route('**/api/scene3d/buildings/**',async route=>{
      reads.push(route.request().url());await gate;
      return fail?route.fulfill({json:{status:'unavailable'}}):route.fallback();
    });
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);v.camera.lookAt(Cesium.Cartesian3.fromDegrees(21.12,52.225,110),new Cesium.HeadingPitchRange(0,-.8,700));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('ładowanie'));
    assert.equal(await page.evaluate(()=>window.__oldBuildings.isDestroyed()),false,'Keep the previous batch during download');
    release();
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('część widoku niedostępna'));
    assert.equal(await page.evaluate(()=>window.__oldBuildings.isDestroyed()),false,'A failed tile must preserve the previous batch');
    fail=false;
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.match(/Budynki OSM: \d+ brył/) && window.__oldBuildings.isDestroyed(),null,{timeout:45000});
    await buildingsVisible(page);
    assert.ok(reads.length>new Set(reads).size,'Failed tiles must retry without a camera movement');
    assert.equal(await page.evaluate(()=>window.__emptyBuildingFrames),0,'Preparing/replacing GPU geometry must never leave an empty frame');
    await page.locator('#atlas3d-toggle').click();await env.clean();
  }finally{release?.();await env.stop();}
});

test('Atlas 3D: lazy engine, terrain, batched trees, zoom/pan, idle budget and return to 2D',{timeout:90000},async()=>{
  const env=await environment();const {page}=env;
  try{
    const calls=await source(page);
    assert.equal(env.observations.vendor.length,0);
    await page.evaluate(()=>state.map.setView([52.225,21.006],16,{animate:false}));
    await page.locator('#atlas3d-toggle').click();
    await page.waitForFunction(()=>window.__vehicleViewers.length&&window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    await page.waitForFunction(treePrimitive);
    await buildingsVisible(page);
    assert.match(await page.locator('#atlas3d-status').textContent(),/60 drzew/);
    assert.match(await page.locator('#atlas3d-status').textContent(),/wymiary szacowane: 30/);
    await page.waitForFunction(()=>Math.abs(window.__vehicleViewers.at(-1).scene.globe.getHeight(Cesium.Cartographic.fromDegrees(21.006,52.225))-110)<2);
    const view=await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);return{terrain:v.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(21.006,52.225)),requestRenderMode:v.scene.requestRenderMode};});
    assert.ok(Math.abs(view.terrain-110)<2,JSON.stringify(view));
    assert.equal(view.requestRenderMode,true);
    assert.equal(await page.locator('.map-panel > .map-legend').isVisible(),false);
    assert.equal(await page.locator('#atlas3d-scene .cesium-widget-credits').isVisible(),true);
    assert.match(await page.locator('#atlas3d-status').textContent(),/Budynki OSM: \d+ brył/);
    const idle=calls.length;await page.waitForTimeout(1200);assert.equal(calls.length,idle,'Idle map must not poll terrain/trees');
    const png=require('pngjs').PNG.sync.read(await page.locator('#atlas3d-scene').screenshot());
    let buildingPixels=0;for(let i=0;i<png.data.length;i+=4)if(png.data[i]>png.data[i+1]+8&&png.data[i+1]>png.data[i+2]+8)buildingPixels++;
    assert.ok(buildingPixels>50,`Extruded buildings must actually be visible: ${buildingPixels} pixels`);
    await page.screenshot({path:path.join(root,'tmp/scene3d-atlas.png'),fullPage:true});
    const originalBuilding=await page.evaluate(()=>window.__vehicleViewers.at(-1).scene.primitives._primitives.find(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed)._instanceIds[0]);
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);v.camera.lookAt(Cesium.Cartesian3.fromDegrees(21.04,52.225,110),new Cesium.HeadingPitchRange(0,-.8,700));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('60 drzew'));
    await page.waitForFunction(original=>window.__vehicleViewers.at(-1).scene.primitives._primitives.some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed&&p.ready&&p._instanceIds[0]!==original),originalBuilding);
    assert.ok(calls.length>idle);
    await page.locator('#atlas3d-toggle').click();
    assert.equal(await page.locator('#atlas3d-scene').isVisible(),false);
    assert.equal(await page.locator('.map-panel > .map-legend').isVisible(),true);
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.at(-1).isDestroyed()),true);
    assert.equal(await page.evaluate(()=>state.map.getZoom()),16);
    await env.clean();
  }finally{await env.stop();}
});

for(const kind of ['aircraft','bus'])test(`${kind}: 3D environment and camera ground clearance, cleanup`,{timeout:90000},async()=>{
  const env=await environment({kind});const {page}=env;
  try{
    await source(page);
    await env.next(kind==='bus'?busSnapshot([bus(Date.now()-18000,{longitude:21.006,latitude:52.225})]):snapshot([aircraft(Date.now()-18000,{longitude:21.006,latitude:52.225,altitude_m:2000})]));
    await page.evaluate(()=>state.map.setView([52.225,21.006],13,{animate:false}));
    await env.open();
    await page.waitForFunction(treePrimitive);
    const buildingMetrics=await buildingsVisible(page);
    await page.waitForFunction(()=>window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    assert.match(await page.locator('#aircraft3d-environment-status').textContent(),/60 drzew/);
    assert.match(buildingMetrics.status,/Budynki OSM: \d+ brył/);
    if(kind==='bus'){
      const altitude=await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1),e=v.entities.values.find(e=>e.model);return Cesium.Cartographic.fromCartesian(e.position.getValue(Cesium.JulianDate.now())).height;});
      assert.ok(Math.abs(altitude-110)<2,`Bus must stand on terrain: ${altitude}`);
      await page.locator('#aircraft3d-pov').click();
      await page.waitForTimeout(100);
      const eye=await page.evaluate(()=>window.__vehicleViewers.at(-1).camera.positionCartographic.height);
      assert.ok(eye>111&&eye<115,`POV above ground: ${eye}`);
    }
    await page.locator('#aircraft3d-pov').click();
    await buildingsVisible(page);
    await page.screenshot({path:path.join(root,`tmp/scene3d-${kind}.png`),fullPage:true});
    await page.locator('#aircraft3d-close').click();
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.at(-1).isDestroyed()),true);
    await env.clean();
  }finally{await env.stop();}
});

test('Atlas keeps 3D and 2D usable when environment sources fail',{timeout:60000},async()=>{
  const env=await environment();const {page}=env;
  try{
    await source(page,{fail:true});
    await page.evaluate(()=>state.map.setView([52.225,21.006],16,{animate:false}));
    await page.locator('#atlas3d-toggle').click();
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('niedostępn'));
    assert.equal(await page.locator('#atlas3d-scene canvas').isVisible(),true);
    await page.locator('#atlas3d-toggle').click();
    assert.equal(await page.locator('#map').isVisible(),true);
    await env.clean();
  }finally{await env.stop();}
});

test('Atlas 3D: mobile map control remains accessible and releases graphics',{timeout:60000},async()=>{
  const env=await environment({viewport:{width:390,height:844},theme:'dark'});const {page}=env;
  try{
    await source(page);
    await page.evaluate(()=>state.map.setView([52.225,21.006],14,{animate:false}));
    await page.locator('#atlas3d-toggle').click();
    await page.waitForFunction(treePrimitive);
    await buildingsVisible(page);
    assert.equal(await page.locator('#atlas3d-toggle').isVisible(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.waitForFunction(()=>window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    await page.screenshot({path:path.join(root,'tmp/scene3d-mobile.png'),fullPage:true});
    await page.locator('#atlas3d-toggle').click();
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.at(-1).isDestroyed()),true);
    await env.clean();
  }finally{await env.stop();}
});


test('Buildings source failure preserves terrain and trees; distant view releases building batches',{timeout:60000},async()=>{
  const env=await environment();const {page}=env;
  try{
    await source(page,{failBuildings:true});
    await page.evaluate(()=>state.map.setView([52.225,21.006],16,{animate:false}));
    await page.locator('#atlas3d-toggle').click();
    await page.waitForFunction(treePrimitive);
    await page.waitForFunction(()=>window.__vehicleViewers.at(-1).scene.globe.tilesLoaded&&document.querySelector('#atlas3d-status').textContent.includes('część widoku niedostępna')&&document.querySelector('#atlas3d-status').textContent.includes('60 drzew'));
    assert.match(await page.locator('#atlas3d-status').textContent(),/60 drzew/);
    await source(page); // New fixture response for the next camera area.
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);v.camera.lookAt(Cesium.Cartesian3.fromDegrees(21.12,52.225,110),new Cesium.HeadingPitchRange(0,-.8,700));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await buildingsVisible(page);
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);v.camera.lookAt(Cesium.Cartesian3.fromDegrees(21.12,52.225,110),new Cesium.HeadingPitchRange(0,-.8,30000));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('Budynki: przybliż mapę'));
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.at(-1).scene.primitives._primitives.some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed)),false);
    await page.locator('#atlas3d-toggle').click();await env.clean();
  }finally{await env.stop();}
});


test('Podzamcze: delayed mountain terrain preserves camera range and detailed street imagery',{timeout:60000},async()=>{
  const env=await environment({liveMapPolicy:true});const {page}=env;
  try{
    const calls=await source(page,{terrainHeight:400,terrainDelay:300});
    await page.evaluate(()=>{document.querySelector('#osm-enabled').checked=true;state.map.setView([50.82,16.28],16,{animate:false});});
    await page.locator('#atlas3d-toggle').click();
    await buildingsVisible(page);
    await page.waitForFunction(()=>{const v=window.__vehicleViewers.at(-1);return v.scene.globe._surface._tilesToRender.some(t=>t.data?.imagery?.some(i=>i.readyImagery?.level>=14));});
    const view=await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);return{camera:v.camera.positionCartographic.height,ground:v.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(16.28,50.82)),error:v.terrainProvider.getLevelMaximumGeometricError(14)};});
    assert.ok(view.error>0,'Zero geometric error makes imagery select zoom 0');
    assert.ok(view.camera>650,`Terrain loading must preserve the initial viewing distance: ${JSON.stringify(view)}`);
    assert.ok(Math.abs(view.ground-400)<2,JSON.stringify(view));
    const terrainCalls=calls.filter(url=>url.includes('/terrain/'));
    assert.ok(terrainCalls.length>0&&terrainCalls.length<=12,`Bounded shared NMT grids: ${terrainCalls.length}`);
    assert.ok(terrainCalls.every(url=>url.startsWith('/api/scene3d/terrain/12/')));
    await page.screenshot({path:path.join(root,'tmp/podzamcze-regression.png'),fullPage:true});
    await page.locator('#atlas3d-toggle').click();await env.clean();
  }finally{await env.stop();}
});


test('Atlas retains the same scene and camera while a hidden tab pauses rendering',{timeout:60000},async()=>{
  const env=await environment();const {page}=env;
  try{
    const calls=await source(page);
    await page.evaluate(()=>state.map.setView([52.225,21.006],15,{animate:false}));
    await page.locator('#atlas3d-toggle').click();await buildingsVisible(page);
    await page.waitForFunction(()=>window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    const before=await page.evaluate(()=>{
      const v=window.__vehicleViewers.at(-1);
      window.__retainedAtlasViewer=v;window.__atlasFrames=0;
      v.scene.postRender.addEventListener(()=>window.__atlasFrames++);
      return{count:window.__vehicleViewers.length,position:[v.camera.positionWC.x,v.camera.positionWC.y,v.camera.positionWC.z],direction:[v.camera.directionWC.x,v.camera.directionWC.y,v.camera.directionWC.z]};
    });
    await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForTimeout(150);
    assert.equal(await page.locator('#atlas3d-toggle').getAttribute('aria-pressed'),'true');
    assert.equal(await page.evaluate(()=>window.__retainedAtlasViewer.isDestroyed()),false);
    assert.equal(await page.evaluate(()=>window.__retainedAtlasViewer.useDefaultRenderLoop),false);
    const frames=await page.evaluate(()=>window.__atlasFrames),reads=calls.length;
    await page.waitForTimeout(600);
    assert.equal(await page.evaluate(()=>window.__atlasFrames),frames);
    assert.equal(calls.length,reads,'Hidden Atlas must not load environment tiles');
    await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForFunction(()=>window.__retainedAtlasViewer.useDefaultRenderLoop&&window.__atlasFrames>0);
    const resumed=await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);return{same:v===window.__retainedAtlasViewer,count:window.__vehicleViewers.length,position:[v.camera.positionWC.x,v.camera.positionWC.y,v.camera.positionWC.z],direction:[v.camera.directionWC.x,v.camera.directionWC.y,v.camera.directionWC.z]};});
    assert.equal(resumed.same,true);assert.equal(resumed.count,before.count);
    assert.ok(Math.hypot(...resumed.position.map((v,i)=>v-before.position[i]))<.01,'Hidden tab must retain the camera position');
    assert.ok(Math.hypot(...resumed.direction.map((v,i)=>v-before.direction[i]))<1e-8,'Hidden tab must retain the camera direction');
    await page.locator('.tab[data-view="sources"]').click();
    assert.equal(await page.evaluate(()=>window.__retainedAtlasViewer.isDestroyed()),true,'Leaving Situation still releases the scene');
    assert.equal(await page.locator('#atlas3d-toggle').getAttribute('aria-pressed'),'false');
    await env.clean();
  }finally{await env.stop();}
});


test('Terrain at 2000 m selects visible ground buildings and preserves the 2D return centre',{timeout:60000},async()=>{
  const env=await environment();const {page}=env;
  try{
    await source(page,{terrainHeight:2000});
    await page.evaluate(()=>state.map.setView([50.82,16.28],15,{animate:false}));
    await page.locator('#atlas3d-toggle').click();
    await page.waitForFunction(()=>{const v=window.__vehicleViewers.at(-1);return v?.camera.positionCartographic.height>2500&&v.scene.globe.tilesLoaded;});
    const target=await page.evaluate(()=>{
      const C=Cesium,v=window.__vehicleViewers.at(-1),pixel=new C.Cartesian2(v.canvas.clientWidth/2,v.canvas.clientHeight/2);
      const ground=v.scene.globe.pick(v.camera.getPickRay(pixel),v.scene),ellipsoid=v.camera.pickEllipsoid(pixel);
      const carto=C.Cartographic.fromCartesian(ground),other=C.Cartographic.fromCartesian(ellipsoid);
      const tile=new C.WebMercatorTilingScheme().positionToTileXY(carto,14);
      return{longitude:C.Math.toDegrees(carto.longitude),latitude:C.Math.toDegrees(carto.latitude),height:carto.height,
        distanceFromEllipsoid:new C.EllipsoidGeodesic(carto,other).surfaceDistance,
        helperError:C.Cartesian3.distance(window.WiciScene3D.groundTarget(v),ground),
        buildingPrefix:`building:synthetic-building-${tile.x}-${tile.y}-`};
    });
    assert.ok(Math.abs(target.height-2000)<2,JSON.stringify(target));
    assert.ok(target.distanceFromEllipsoid>1000,'The fixture must expose the kilometre-scale ellipsoid targeting error');
    assert.ok(target.helperError<.001,'Shared target must be the ray/terrain intersection');
    await page.waitForFunction(id=>window.__vehicleViewers.at(-1).scene.primitives._primitives.some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.appearance.closed&&p.ready&&p._instanceIds.some(value=>value.startsWith(id))),target.buildingPrefix);
    const fallbackError=await page.evaluate(()=>{
      const C=Cesium,v=window.__vehicleViewers.at(-1),pick=v.scene.globe.pick;
      try{
        v.scene.globe.pick=()=>undefined;
        const pixel=new C.Cartesian2(v.canvas.clientWidth/2,v.canvas.clientHeight/2);
        return C.Cartesian3.distance(window.WiciScene3D.groundTarget(v),v.camera.pickEllipsoid(pixel));
      }finally{v.scene.globe.pick=pick;}
    });
    assert.ok(fallbackError<.001,'Missing terrain must fall back to the ellipsoid');
    await page.locator('#atlas3d-toggle').click();
    const drift=await page.evaluate(target=>state.map.getCenter().distanceTo([target.latitude,target.longitude]),target);
    assert.ok(drift<2,`Return to 2D must keep the visible ground centre, drift=${drift} m`);
    await env.clean();
  }finally{await env.stop();}
});
