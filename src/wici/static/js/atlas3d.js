'use strict';
window.WiciAtlas3D = (() => {
  const $ = id => document.getElementById(id);
  let map, health, viewer, context, run = 0, active = false;
  function target() {
    const C = window.Cesium;
    if (!viewer || viewer.isDestroyed()) return null;
    const point = viewer.camera.pickEllipsoid(new C.Cartesian2(viewer.canvas.clientWidth/2,viewer.canvas.clientHeight/2),C.Ellipsoid.WGS84);
    return point ? C.Cartographic.fromCartesian(point) : viewer.camera.positionCartographic;
  }
  function update() {
    const point = target();
    if (point) context?.update(window.Cesium.Math.toDegrees(point.longitude),window.Cesium.Math.toDegrees(point.latitude),viewer.camera.positionCartographic.height);
  }
  function close({restore = true} = {}) {
    run++; active = false;
    const point = restore ? target() : null;
    context?.destroy(); context = null;
    if (viewer && !viewer.isDestroyed()) viewer.destroy();
    viewer = null;
    $('atlas3d-scene').replaceChildren(); $('atlas3d-scene').hidden = true;
    $('atlas3d-info').hidden = true; $('atlas3d-toggle').setAttribute('aria-pressed','false');
    $('atlas3d-toggle').textContent = 'Widok 3D';
    delete $('map').parentElement.dataset.view3d;
    if (point && map) {
      const C = window.Cesium;
      map.setView([C.Math.toDegrees(point.latitude),C.Math.toDegrees(point.longitude)],map.getZoom(),{animate:false});
    }
    map?.invalidateSize({pan:false});
  }
  async function open() {
    if (!map) return;
    const current = ++run;
    active = true; $('atlas3d-toggle').setAttribute('aria-pressed','true');
    $('atlas3d-toggle').textContent = 'Wróć do 2D';
    $('atlas3d-info').hidden = false;
    $('atlas3d-status').textContent = 'Ładowanie lokalnego silnika 3D…';
    try {
      const C = await window.WiciScene3D.loadEngine();
      if (current !== run) return;
      window.CESIUM_WORKERS = undefined;
      $('atlas3d-scene').hidden = false;
      viewer = new C.Viewer($('atlas3d-scene'), {
        animation:false,timeline:false,baseLayerPicker:false,fullscreenButton:false,vrButton:false,
        geocoder:false,homeButton:false,infoBox:false,sceneModePicker:false,navigationHelpButton:false,
        selectionIndicator:false,baseLayer:false,skyBox:false,scene3DOnly:true,
        requestRenderMode:true,maximumRenderTimeChange:Infinity,showRenderLoopErrors:false
      });
      viewer.resolutionScale = Math.min(1,1.5/(window.devicePixelRatio||1));
      viewer.scene.globe.baseColor = C.Color.fromCssColorString('#203d3c');
      viewer.scene.globe.enableLighting = false;
      viewer.scene.screenSpaceCameraController.minimumZoomDistance = 15;
      const center = map.getCenter(), height = Math.max(180,Math.min(1600000,24000000/2**map.getZoom()));
      viewer.camera.setView({destination:C.Cartesian3.fromDegrees(center.lng,center.lat,height),orientation:{heading:0,pitch:C.Math.toRadians(-55),roll:0}});
      // Aim at the existing map centre, rather than shifting the initial footprint
      // when pitching a camera placed directly above it.
      viewer.camera.lookAt(C.Cartesian3.fromDegrees(center.lng,center.lat),new C.HeadingPitchRange(0,C.Math.toRadians(-55),height));
      viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
      if (health()?.mode === 'live' && $('osm-enabled').checked) {
        const provider = new C.OpenStreetMapImageryProvider({url:'https://tile.openstreetmap.org/',maximumLevel:19});
        provider.errorEvent.addEventListener(()=>{if(current===run)$('atlas3d-imagery').textContent='Kafelki OSM chwilowo niedostępne.';});
        viewer.imageryLayers.addImageryProvider(provider);
        $('atlas3d-imagery').textContent = 'OpenStreetMap';
      } else $('atlas3d-imagery').textContent = 'Podkład lokalny · OSM włączysz w Warstwach w trybie LIVE';
      context = window.WiciScene3D.environment(viewer,text=>{if(current===run)$('atlas3d-status').textContent=text;});
      let userMoved=false;
      for(const event of ['pointerdown','wheel','keydown'])viewer.canvas.addEventListener(event,()=>{userMoved=true;},{once:true});
      // Ground elevation can exceed a close camera's nominal range (e.g. in
      // mountains). Lift the initial frame once NMT arrives, unless the user
      // has already moved the camera in the meantime.
      context.height(center.lng,center.lat).then(elevation=>{
        if(current!==run||!viewer||userMoved)return;
        viewer.camera.lookAt(C.Cartesian3.fromDegrees(center.lng,center.lat,elevation),new C.HeadingPitchRange(0,C.Math.toRadians(-55),height));
        viewer.camera.lookAtTransform(C.Matrix4.IDENTITY); update(); viewer.scene.requestRender();
      }).catch(()=>{});
      viewer.camera.moveEnd.addEventListener(update);
      viewer.scene.renderError.addEventListener(()=>{if(current===run){$('atlas3d-status').textContent='Renderowanie przerwane. Wróć do 2D i otwórz widok ponownie.';context?.destroy();}});
      viewer.canvas.addEventListener('webglcontextlost',()=>{if(current===run)$('atlas3d-status').textContent='Utracono dostęp do grafiki. Wróć do 2D.';});
      $('map').parentElement.dataset.view3d = 'true';
      update();
      // Request-render mode sleeps when idle; data arrival and camera changes
      // wake it. Hidden tabs stop both rendering and environmental requests.
      if (document.hidden) viewer.useDefaultRenderLoop = false;
    } catch {
      if (current !== run) return;
      close({restore:false});
      $('atlas3d-info').hidden = false;
      $('atlas3d-status').textContent = 'Widok 3D wymaga WebGL 2 i lokalnego silnika Cesium. Mapa 2D pozostaje dostępna.';
    }
  }
  function init(options) {
    if (map || !$('atlas3d-toggle')) return;
    map = options.map; health = options.health;
    $('atlas3d-toggle').addEventListener('click',()=>active?close():open());
    document.addEventListener('visibilitychange',()=>{if(viewer&&!viewer.isDestroyed()){viewer.useDefaultRenderLoop=!document.hidden;if(!document.hidden){update();viewer.scene.requestRender();}}});
    document.addEventListener('wici:regionchange',()=>{if(active)close({restore:false});});
    $('osm-enabled').addEventListener('change',()=>{if(active){close({restore:false});open();}});
  }
  return {init,close,sync({visible}={}){if(!visible&&active)close({restore:false});}};
})();
