// Real WebGL, synthetic heightfields/municipal records, isolated offline backend.
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {environment,aircraft,snapshot,bus,busSnapshot,root}=require('./helpers/vehicle3d_browser.cjs');
async function source(page,{fail=false}={}) {
  const calls=[];
  await page.route('**/api/scene3d/**',async route=>{
    const url=new URL(route.request().url());calls.push(url.pathname);
    if(fail)return route.fulfill({json:{status:'unavailable',message:'Syntetyczna awaria'}});
    if(url.pathname.includes('/terrain/'))return route.fulfill({json:{status:'ready',size:65,heights:Array(65*65).fill(110)}});
    const [x,y]=url.pathname.split('/').slice(-2).map(Number),step=180/2**14;
    return route.fulfill({json:{status:'ready',source:'Urząd m.st. Warszawy',source_dates:['01.01.2026'],fetched_at:'2026-11-03T12:00:00Z',
      items:Array.from({length:12},(_,i)=>({id:`synthetic-${x}-${y}-${i}`,longitude:-180+(x+.3+i*.03)*step,latitude:90-(y+.5)*step,height:10,diameter:5,estimated:i%2===0}))}});
  });
  return calls;
}
const treePrimitive=()=>{
  const v=window.__vehicleViewers.at(-1);
  return v && Array.from({length:v.scene.primitives.length},(_,i)=>v.scene.primitives.get(i)).some(p=>p.appearance instanceof Cesium.PerInstanceColorAppearance&&p.ready);
};

test('Atlas 3D: lazy engine, terrain, batched trees, zoom/pan, idle budget and return to 2D',{timeout:90000},async()=>{
  const env=await environment();const {page}=env;
  try{
    const calls=await source(page);
    assert.equal(env.observations.vendor.length,0);
    await page.evaluate(()=>state.map.setView([52.225,21.006],16,{animate:false}));
    await page.locator('#atlas3d-toggle').click();
    await page.waitForFunction(()=>window.__vehicleViewers.length&&window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    await page.waitForFunction(treePrimitive);
    assert.match(await page.locator('#atlas3d-status').textContent(),/60 drzew/);
    assert.match(await page.locator('#atlas3d-status').textContent(),/wymiary szacowane: 30/);
    await page.waitForFunction(()=>Math.abs(window.__vehicleViewers.at(-1).scene.globe.getHeight(Cesium.Cartographic.fromDegrees(21.006,52.225))-110)<2);
    const view=await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);return{terrain:v.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(21.006,52.225)),requestRenderMode:v.scene.requestRenderMode};});
    assert.ok(Math.abs(view.terrain-110)<2,JSON.stringify(view));
    assert.equal(view.requestRenderMode,true);
    const idle=calls.length;await page.waitForTimeout(1200);assert.equal(calls.length,idle,'Idle map must not poll terrain/trees');
    await page.screenshot({path:path.join(root,'tmp/scene3d-atlas.png'),fullPage:true});
    await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1);v.camera.lookAt(Cesium.Cartesian3.fromDegrees(21.04,52.225,110),new Cesium.HeadingPitchRange(0,-.8,700));v.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);});
    await page.waitForFunction(()=>document.querySelector('#atlas3d-status').textContent.includes('60 drzew'));
    await page.waitForTimeout(1000);assert.ok(calls.length>idle);
    await page.locator('#atlas3d-toggle').click();
    assert.equal(await page.locator('#atlas3d-scene').isVisible(),false);
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
    await page.waitForFunction(()=>window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    assert.match(await page.locator('#aircraft3d-environment-status').textContent(),/60 drzew/);
    if(kind==='bus'){
      const altitude=await page.evaluate(()=>{const v=window.__vehicleViewers.at(-1),e=v.entities.values.find(e=>e.model);return Cesium.Cartographic.fromCartesian(e.position.getValue(Cesium.JulianDate.now())).height;});
      assert.ok(Math.abs(altitude-110)<2,`Bus must stand on terrain: ${altitude}`);
      await page.locator('#aircraft3d-pov').click();
      await page.waitForTimeout(100);
      const eye=await page.evaluate(()=>window.__vehicleViewers.at(-1).camera.positionCartographic.height);
      assert.ok(eye>111&&eye<115,`POV above ground: ${eye}`);
    }
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
    assert.equal(await page.locator('#atlas3d-toggle').isVisible(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(root,'tmp/scene3d-mobile.png'),fullPage:true});
    await page.locator('#atlas3d-toggle').click();
    assert.equal(await page.evaluate(()=>window.__vehicleViewers.at(-1).isDestroyed()),true);
    await env.clean();
  }finally{await env.stop();}
});
