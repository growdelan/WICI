'use strict';
// Shared, lazy Cesium engine and bounded environment for Atlas and both vehicle cameras.
window.WiciScene3D = (() => {
  let enginePromise, engineCssReady = false;
  function loadEngine() {
    if (window.Cesium && engineCssReady) return Promise.resolve(window.Cesium);
    if (enginePromise) return enginePromise;
    window.CESIUM_BASE_URL = '/static/vendor/cesium/';
    enginePromise = new Promise((resolve, reject) => {
      const script = document.createElement('script'), css = document.createElement('link');
      script.src = '/static/vendor/cesium/Cesium.js'; script.async = true;
      css.rel = 'stylesheet'; css.href = '/static/vendor/cesium/Widgets/widgets.css';
      let loaded = 0, settled = false;
      const finish = () => {
        if (settled) return;
        if (++loaded !== 2) return;
        if (!window.Cesium) { fail(); return; }
        settled = true;
        clearTimeout(timeout);
        resolve(window.Cesium);
      };
      const fail = () => {
        if (settled) return;
        settled = true; engineCssReady = false;
        clearTimeout(timeout); script.remove(); css.remove(); enginePromise = null;
        reject(new Error('Nie udało się wczytać lokalnego silnika 3D. Wróć do mapy i spróbuj ponownie.'));
      };
      const timeout = setTimeout(fail, 20000);
      script.onload = finish; css.onload = () => { if (!settled) { engineCssReady = true; finish(); } };
      script.onerror = fail; css.onerror = fail;
      document.head.append(css, script);
    });
    return enginePromise;
  }
  const MAX_LEVEL = 14, SIZE = 65, MAX_TREES = 1800;
  function environment(viewer, report = () => {}) {
    const C = window.Cesium, controller = new AbortController(), terrainCache = new Map();
    const scheme = new C.GeographicTilingScheme();
    let dead = false, pending = 0, treeKey = '', treeRun = 0, trees, terrainNote = 'NMT GUGiK: ładowanie przy zbliżeniu', treeNote = 'Drzewa miejskie: przybliż mapę';
    let lastReport = '';
    const notify = () => { const text = `${terrainNote} · ${treeNote}`; if (!dead && text !== lastReport) {lastReport = text; report(text);} };
    const flat = () => new Float32Array(SIZE * SIZE);
    async function read(url) {
      const response = await fetch(url, {signal:controller.signal});
      if (!response.ok) throw Error('Dane otoczenia niedostępne');
      return response.json();
    }
    function heightmap(x, y, level) {
      const rectangle = scheme.tileXYToRectangle(x,y,level);
      if (level < 10 || rectangle.east < C.Math.toRadians(14) || rectangle.west > C.Math.toRadians(24.5)
          || rectangle.north < C.Math.toRadians(49) || rectangle.south > C.Math.toRadians(55)) return Promise.resolve(flat());
      const key = `${level}/${x}/${y}`;
      if (terrainCache.has(key)) return terrainCache.get(key);
      if (pending >= 4 || dead || document.hidden) return undefined;
      pending++;
      const result = read(`/api/scene3d/terrain/${key}`).then(data => {
        if (data.status !== 'ready' || data.heights?.length !== SIZE*SIZE || !data.heights.every(Number.isFinite)) {
          terrainNote = data.status === 'empty' ? 'NMT: brak danych dla obszaru lub trybu' : 'NMT chwilowo niedostępny; powierzchnia zastępcza';
          notify(); return flat();
        }
        terrainNote = 'Teren: NMT / LiDAR GUGiK (wysokości przybliżone)'; notify();
        return new Float32Array(data.heights);
      }).catch(() => { terrainNote = 'NMT niedostępny; powierzchnia zastępcza'; notify(); return flat(); })
        .finally(() => { pending--; });
      terrainCache.set(key,result);
      if (terrainCache.size > 96) terrainCache.delete(terrainCache.keys().next().value);
      return result;
    }
    const terrain = new C.CustomHeightmapTerrainProvider({width:SIZE,height:SIZE,tilingScheme:scheme,
      callback:heightmap, credit:new C.Credit('NMT / GUGiK · PL-KRON86-NH',true)});
    // Stop subdivision at ~20 m grid spacing; extra sub-metre tiles would add
    // network/mesh work without helping these approximate vehicle positions.
    terrain.requestTileGeometry = (x,y,level) => {
      const result = heightmap(x,y,level);
      return result && Promise.resolve(result).then(buffer => new C.HeightmapTerrainData({buffer,width:SIZE,height:SIZE,childTileMask:level >= MAX_LEVEL ? 0 : 15}));
    };
    terrain.getTileDataAvailable = (x,y,level) => level <= MAX_LEVEL;
    const geometricError = terrain.getLevelMaximumGeometricError.bind(terrain);
    // Quadtree traversal selects an SSE level before loading its ancestors.
    // Cap traversal as well as availability, otherwise a close camera can wait
    // forever for level 16 while the level-14 parent has never been loaded.
    terrain.getLevelMaximumGeometricError = level => level >= MAX_LEVEL ? 0 : geometricError(level);
    viewer.terrainProvider = terrain;
    // Native fetch/heightmap promises do not signal Cesium's Resource scheduler.
    // Keep refinement awake until meshes are ready, then let the Atlas sleep.
    const removeWake = viewer.scene.postRender.addEventListener(()=>{if(!dead&&!document.hidden&&!viewer.scene.globe.tilesLoaded)viewer.scene.requestRender();});
    viewer.scene.globe.maximumScreenSpaceError = 4;
    viewer.scene.globe.tileCacheSize = 64;
    viewer.scene.globe.preloadAncestors = false;
    viewer.scene.globe.preloadSiblings = false;
    const credit = new C.Credit('<a href="https://mapa.um.warszawa.pl/strony/Warunki-ponownego-wykorzystania-informacji-publicznej" target="_blank" rel="noopener noreferrer">Drzewa: Urząd m.st. Warszawy</a> · schematyczne bryły; brakujące wymiary szacowane',true);
    function clearTrees() { if (trees && !viewer.isDestroyed()) viewer.scene.primitives.remove(trees); trees = null; }
    async function updateTrees(longitude, latitude, height = 0) {
      if (dead || document.hidden) return;
      if (height > 6000 || longitude < 20.75 || longitude > 21.28 || latitude < 52.09 || latitude > 52.39) {
        treeRun++; treeKey = ''; clearTrees();
        treeNote = height > 6000 ? 'Drzewa: przybliż mapę (poniżej 6 km)' : 'Miejska baza drzew: pokrycie Warszawy'; notify(); return;
      }
      const center = scheme.positionToTileXY(C.Cartographic.fromDegrees(longitude,latitude),MAX_LEVEL);
      const key = `${center.x}/${center.y}`;
      if (key === treeKey) return;
      treeKey = key;
      const run = ++treeRun;
      treeNote = 'Miejska baza drzew: ładowanie…'; notify();
      try {
        // Five neighbouring tiles cover the immediate view; a fixed cap also
        // bounds CPU/GPU work in dense parks. No entity or per-frame tree loop.
        const offsets = [[0,0],[-1,0],[1,0],[0,-1],[0,1]];
        const data = await Promise.all(offsets.map(([dx,dy]) => read(`/api/scene3d/trees/${center.x+dx}/${center.y+dy}`)));
        if (dead || run !== treeRun) return;
        const items = data.flatMap(tile => tile.items || []).slice(0,MAX_TREES);
        if (!items.length) {
          clearTrees();
          treeNote = data.some(tile => tile.status === 'unavailable') ? 'Miejska baza drzew chwilowo niedostępna' : data[0].message || 'Brak zinwentaryzowanych drzew w tym miejscu';
          notify(); return;
        }
        const positions = items.map(item => C.Cartographic.fromDegrees(item.longitude,item.latitude));
        // Uses the same bounded terrain cache as the globe, never the scene depth
        // (which may include tree crowns). One sample per loaded tree, not/frame.
        await C.sampleTerrain(terrain,MAX_LEVEL,positions);
        if (dead || run !== treeRun) return;
        const instances = [], appearance = new C.PerInstanceColorAppearance({flat:true,translucent:false});
        const crown = new C.EllipsoidGeometry({radii:new C.Cartesian3(1,1,1),stackPartitions:4,slicePartitions:6,vertexFormat:C.PerInstanceColorAppearance.VERTEX_FORMAT});
        const trunk = new C.CylinderGeometry({length:1,topRadius:.18,bottomRadius:.24,slices:5,vertexFormat:C.PerInstanceColorAppearance.VERTEX_FORMAT});
        items.forEach((item,index) => {
          const elevation = Number.isFinite(positions[index].height) ? positions[index].height : 0;
          const h = Math.min(65,Math.max(1,item.height)), radius = Math.min(20,Math.max(.25,item.diameter/2));
          const transform = (z,scale) => C.Matrix4.multiplyByScale(C.Transforms.eastNorthUpToFixedFrame(C.Cartesian3.fromDegrees(item.longitude,item.latitude,elevation+z)),scale,new C.Matrix4());
          instances.push(new C.GeometryInstance({geometry:crown,modelMatrix:transform(h*.68,new C.Cartesian3(radius,radius,h*.32)),attributes:{color:C.ColorGeometryInstanceAttribute.fromColor(C.Color.fromCssColorString(item.estimated?'#60894d':'#397956'))}}));
          instances.push(new C.GeometryInstance({geometry:trunk,modelMatrix:transform(h*.3,new C.Cartesian3(1,1,h*.6)),attributes:{color:C.ColorGeometryInstanceAttribute.fromColor(C.Color.fromCssColorString('#745c45'))}}));
        });
        clearTrees();
        trees = viewer.scene.primitives.add(new C.Primitive({geometryInstances:instances,appearance,asynchronous:true,allowPicking:false}));
        viewer.scene.frameState.creditDisplay.addStaticCredit(credit);
        viewer.scene.requestRender();
        const estimated = items.filter(item => item.estimated).length;
        const dates = [...new Set(data.flatMap(tile => tile.source_dates || []))].sort((a,b)=>a.split('.').reverse().join('').localeCompare(b.split('.').reverse().join('')));
        const dateRange = !dates.length ? 'niepodana' : dates.length === 1 ? dates[0] : `${dates[0]} – ${dates.at(-1)}`;
        const fetched = data.find(tile=>tile.fetched_at)?.fetched_at;
        treeNote = `Urząd m.st. Warszawy: ${items.length} drzew · wymiary szacowane: ${estimated} · bryły uproszczone${items.length===MAX_TREES||data.some(tile=>tile.truncated)?' · limit widoczności':''} · aktualność wpisów: ${dateRange} · pobrano: ${fetched ? new Date(fetched).toLocaleString('pl-PL') : '—'}`;
        notify();
      } catch {
        if (dead || run !== treeRun) return;
        clearTrees(); treeKey = ''; treeNote = 'Drzewa niedostępne; mapa i śledzenie działają'; notify();
      }
    }
    notify();
    return {update:updateTrees, async height(longitude,latitude) {
      const positions = [C.Cartographic.fromDegrees(longitude,latitude)];
      await C.sampleTerrain(terrain,MAX_LEVEL,positions);
      return Number.isFinite(positions[0].height) ? positions[0].height : 0;
    }, destroy() {dead=true; treeRun++; removeWake(); controller.abort(); clearTrees(); terrainCache.clear();}};
  }
  return {loadEngine,environment};
})();
