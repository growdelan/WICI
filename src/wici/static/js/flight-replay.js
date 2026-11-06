'use strict';
window.WiciFlightReplay = (() => {
  const $ = name => document.getElementById(`flight-replay-${name}`);
  const D = window.WiciFlightReplayData;
  const timeOfDay = new Intl.DateTimeFormat('pl-PL', {timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit'});
  const day = new Intl.DateTimeFormat('pl-PL', {timeZone: 'UTC', dateStyle: 'medium'});
  const clock = seconds => `${timeOfDay.format(seconds * 1000)} UTC`;
  const duration = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const color = value => window.Cesium.Color.fromCssColorString(value);
  const controls = ['time', 'speed', 'play', 'overview', 'follow'];
  let active = null;

  function pause(run) {
    cancelAnimationFrame(run.raf);
    run.playing = false;
    $('play').textContent = 'Odtwórz';
    $('play').setAttribute('aria-pressed', 'false');
    $('dialog').dataset.playing = 'false';
  }
  function release(run) {
    run.abort.abort();
    run.radarAbort?.abort();
    pause(run);
    run.removeError?.();
    if (run.viewer && !run.viewer.isDestroyed()) {
      try { run.viewer.destroy(); } catch { /* An already lost WebGL context may not cleanly destroy. */ }
    }
    run.viewer = null;
    $('scene').replaceChildren();
  }
  function close() {
    const run = active;
    if (!run) return;
    active = null;
    release(run);
    if ($('dialog').open) $('dialog').close();
    const target = run.trigger?.isConnected && run.trigger.getClientRects().length ? run.trigger : document.getElementById('map');
    target?.focus({preventScroll: true});
  }
  function fail(run, message) {
    if (active !== run || run.failed) return;
    run.failed = true;
    release(run);
    $('dialog').dataset.state = 'error';
    controls.forEach(id => { $(id).disabled = true; });
    $('status').textContent = message;
  }
  function position(point) {
    return window.Cesium.Cartesian3.fromDegrees(point.lon, point.lat, point.alt_m);
  }
  function addTerrainContext(run) {
    const C = window.Cesium, viewer = run.viewer;
    const land = viewer.imageryLayers.addImageryProvider(new C.UrlTemplateImageryProvider({
      url: '/static/vendor/cesium/Assets/Textures/NaturalEarthII/{z}/{x}/{reverseY}.jpg',
      tilingScheme: new C.GeographicTilingScheme(), minimumLevel: 0, maximumLevel: 2,
      credit: new C.Credit('Natural Earth')
    }));
    land.brightness = .43;
    land.saturation = .53;
    const rectangle = C.Rectangle.fromDegrees(13,48,25,56);
    const satellite = viewer.imageryLayers.addImageryProvider(new C.UrlTemplateImageryProvider({
      url:'/static/geo/flight-satellite/{x}-{y}.webp', rectangle,
      tilingScheme:new C.GeographicTilingScheme({rectangle, numberOfLevelZeroTilesX:6, numberOfLevelZeroTilesY:4}),
      minimumLevel:0, maximumLevel:0, tileWidth:1024, tileHeight:1024,
      credit:new C.Credit('© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium.')
    }));
    satellite.brightness = .91;
    satellite.saturation = .85;
    const cities = [['Warszawa',21.0122,52.2297], ['Łódź',19.456,51.7592], ['Poznań',16.9252,52.4064],
      ['Płock',19.7064,52.5468], ['Radom',21.1471,51.4027], ['Siedlce',22.2905,52.1677],
      ['Kraków',19.945,50.0647], ['Gdańsk',18.6466,54.352], ['Wrocław',17.0385,51.1079], ['Szczecin',14.5528,53.4285]];
    for (const [label, lon, lat] of cities) viewer.entities.add({position:C.Cartesian3.fromDegrees(lon, lat, 15),
      point:{pixelSize:3, color:color('#d6e3df')}, label:{text:label, font:'13px sans-serif', fillColor:color('#e1e9e6'),
        outlineColor:color('#0a1720'), outlineWidth:3, style:C.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin:C.VerticalOrigin.BOTTOM, pixelOffset:new C.Cartesian2(0,-6),
        distanceDisplayCondition:new C.DistanceDisplayCondition(0,1250000)}});
    loadBoundaries(run).catch(() => { /* The local raster and route remain available. */ });
  }
  async function loadBoundaries(run) {
    const res = await fetch('/static/geo/provinces.geojson', {signal: run.abort.signal});
    if (!res.ok) return;
    const geo = await res.json(), C = window.Cesium;
    if (active !== run || run.failed) return;
    for (const feature of geo.features) {
      const rings = feature.geometry.type === 'MultiPolygon' ? feature.geometry.coordinates.flat() : feature.geometry.coordinates;
      for (const ring of rings) run.viewer.entities.add({polyline:{positions:C.Cartesian3.fromDegreesArray(ring.flat()),
        width:1, material:color('#aabcd0').withAlpha(.42), arcType:C.ArcType.NONE}});
    }
    run.viewer.scene.requestRender();
  }
  function initScene(run, C) {
    // Force the separately vendored ESM workers. The bundle's classic worker
    // calls importScripts(blob:), which is outside WICI's script-src 'self'.
    window.CESIUM_WORKERS = undefined;
    const viewer = run.viewer = new C.Viewer($('scene'), {
      animation:false, timeline:false, baseLayerPicker:false, fullscreenButton:false, vrButton:false, geocoder:false,
      homeButton:false, infoBox:false, sceneModePicker:false, navigationHelpButton:false, selectionIndicator:false,
      baseLayer:false, terrainProvider:new C.EllipsoidTerrainProvider(), scene3DOnly:true, shouldAnimate:false,
      requestRenderMode:true, maximumRenderTimeChange:Infinity, skyBox:false, showRenderLoopErrors:false
    });
    viewer.resolutionScale = Math.min(1, 1.5 / (window.devicePixelRatio || 1));
    viewer.scene.globe.baseColor = color('#263e45');
    viewer.scene.globe.enableLighting = false;
    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.backgroundColor = color('#18334a');
    viewer.scene.globe.showGroundAtmosphere = true;
    viewer.scene.screenSpaceCameraController.minimumZoomDistance = 120;
    // Use a fixed daylight scene for legibility across recordings and playback speeds.
    viewer.scene.light = new C.DirectionalLight({direction:C.Cartesian3.normalize(new C.Cartesian3(-1,-.6,-.9),new C.Cartesian3()),intensity:2});
    run.removeError = viewer.scene.renderError.addEventListener(() => queueMicrotask(() => fail(run, 'Przerwano renderowanie 3D. Zamknij i ponownie otwórz odtworzenie.')));
    viewer.canvas.addEventListener('webglcontextlost', () => fail(run, 'Utracono dostęp do grafiki 3D. Zamknij i ponownie otwórz odtworzenie.'));
    addTerrainContext(run);
    const legs = D.legs(run.data.points);
    const pathMaterial = new C.PolylineDashMaterialProperty({color:color('#e8f2f0').withAlpha(.85),dashLength:14});
    for (const leg of legs) if (leg.length > 1) viewer.entities.add({polyline:{positions:leg.map(position),
      width:2, arcType:C.ArcType.NONE, material:pathMaterial}});
    run.sphere = C.BoundingSphere.fromPoints(run.data.points.map(position));
    run.trail = viewer.entities.add({id:'flight-replay-trail', polyline:{positions:[], width:9, arcType:C.ArcType.NONE,
      material:new C.PolylineGlowMaterialProperty({color:color('#51ffdc'),glowPower:.23})}});
    run.vertical = viewer.entities.add({polyline:{positions:[], width:1.5, arcType:C.ArcType.NONE,
      material:new C.PolylineDashMaterialProperty({color:color('#ffc771').withAlpha(.88),dashLength:9})}});
    run.aircraft = viewer.entities.add({id:'flight-replay-aircraft', name:run.data.label,
      model:{uri:'/static/models/aircraft.gltf', minimumPixelSize:50, maximumScale:2300,
        silhouetteColor:color('#f0c781'), silhouetteSize:1.3},
      point:{pixelSize:5,color:color('#fff1bd')}, label:{text:run.data.label, font:'bold 13px sans-serif',
        pixelOffset:new C.Cartesian2(0,-36), fillColor:color('#ffe8bb'),outlineColor:color('#15232a'),
        outlineWidth:4, style:C.LabelStyle.FILL_AND_OUTLINE}});
    setView(run, 'overview');
  }
  function setView(run, mode) {
    if (!run.viewer) return;
    run.mode = mode;
    run.aircraft.model.minimumPixelSize = mode === 'follow' ? 138 : 57;
    run.aircraft.label.pixelOffset = new window.Cesium.Cartesian2(0, mode === 'follow' ? -58 : -36);
    $('follow').setAttribute('aria-pressed', String(mode === 'follow'));
    $('overview').setAttribute('aria-pressed', String(mode === 'overview'));
    const C = window.Cesium, camera = run.viewer.camera;
    run.viewer.scene.screenSpaceCameraController.enableInputs = mode === 'overview';
    if (mode === 'overview') {
      camera.lookAtTransform(C.Matrix4.IDENTITY);
      const aspect = run.viewer.canvas.clientWidth / Math.max(1, run.viewer.canvas.clientHeight);
      const halfVertical = camera.frustum.fovy / 2;
      const halfHorizontal = Math.atan(Math.tan(halfVertical) * aspect);
      const distance = run.sphere.radius * 1.12 / Math.sin(Math.min(halfVertical, halfHorizontal));
      camera.viewBoundingSphere(run.sphere, new C.HeadingPitchRange(C.Math.toRadians(-18), C.Math.toRadians(-53), Math.max(14000, distance)));
      camera.lookAtTransform(C.Matrix4.IDENTITY);
    }
    draw(run);
  }
  function paintFlight(run, point) {
    const C = window.Cesium;
    run.aircraft.show = run.trail.show = run.vertical.show = Boolean(point);
    if (!point) return;
    const pos = position(point);
    const heading = Number.isFinite(point.heading) ? point.heading : 0;
    run.aircraft.position = pos;
    run.aircraft.model.show = Number.isFinite(point.heading);
    // Cesium's glTF axis correction aligns this authored +X nose to north at zero heading.
    run.aircraft.orientation = C.Transforms.headingPitchRollQuaternion(pos, new C.HeadingPitchRoll(C.Math.toRadians(heading),0,0));
    run.vertical.polyline.positions = [C.Cartesian3.fromDegrees(point.lon, point.lat), pos];
    const points = run.data.points, trail = [pos];
    for (let i = point.index; i >= 0 && point.time - points[i].time <= 300; i--) {
      if (i < point.index && points[i + 1].time - points[i].time > D.MAX_POSITION_GAP) break;
      if (points[i].time !== point.time) trail.push(position(points[i]));
    }
    run.trail.polyline.positions = trail.reverse();
    if (run.mode === 'follow') {
      // Frame the aircraft obliquely from the rear so its shape, the route and
      // horizon survive both the wide desktop viewport and a tall phone screen.
      const range = Math.min(22000, 3800 + Math.max(0,point.alt_m) * 1.2);
      const fovy = run.viewer.camera.frustum.fovy || C.Math.toRadians(40);
      const pitch = -Math.min(C.Math.toRadians(13), fovy * .22);
      run.viewer.camera.lookAt(pos, new C.HeadingPitchRange(C.Math.toRadians(heading + 30), pitch, range));
    }
  }
  function setText(id, value) {if ($(id).textContent !== value) $(id).textContent = value;}
  function draw(run) {
    if (!run.viewer || run.failed) return;
    const point = D.sample(run.data.points, run.time);
    paintFlight(run, point);
    $('time').value = String(Math.floor(run.time));
    const displayTime = clock(run.time);
    if ($('time').getAttribute('aria-valuetext') !== displayTime) $('time').setAttribute('aria-valuetext', displayTime);
    setText('clock', displayTime);
    setText('elapsed', `${duration(run.time - run.start)} / ${duration(run.end - run.start)}`);
    setText('date', day.format(run.time * 1000));
    setText('altitude', point ? `${Math.round(point.alt_m).toLocaleString('pl-PL')} m` : '—');
    setText('heading', Number.isFinite(point?.heading) ? `${Math.round(point.heading) % 360}°` : '—');
    setText('status', !point ? 'Luka w zapisie pozycji.' : point.measured ? 'Pozycja z zapisu.' : 'Pozycja między zapisanymi pomiarami.');
    updateRadar(run);
    run.viewer.scene.requestRender();
  }
  function tick(run, now) {
    if (active !== run || !run.playing || document.hidden) return;
    const delta = Math.max(0, (now - run.last) / 1000);
    run.last = now;
    run.time = Math.min(run.end, run.time + delta * Number($('speed').value));
    draw(run);
    if (run.time >= run.end) pause(run);
    else run.raf = requestAnimationFrame(next => tick(run, next));
  }
  function play() {
    const run = active;
    if (!run?.viewer || run.failed) return;
    if (run.playing) { pause(run); return; }
    if (run.time >= run.end) run.time = run.start;
    run.playing = true;
    run.last = performance.now();
    $('dialog').dataset.playing = 'true';
    $('play').textContent = 'Pauza';
    $('play').setAttribute('aria-pressed', 'true');
    run.raf = requestAnimationFrame(next => tick(run, next));
  }
  function renderProfile(run) {
    const points = run.data.points;
    let max = -Infinity, min = Infinity;
    for (const point of points) {min = Math.min(min, point.alt_m); max = Math.max(max, point.alt_m);}
    const x = point => 1000 * (point.time - run.start) / (run.end - run.start);
    const y = point => 29 - 25 * (point.alt_m - min) / Math.max(1, max - min);
    const path = D.legs(points).map(leg => leg.map((p,i) => `${i ? 'L' : 'M'}${x(p).toFixed(1)} ${y(p).toFixed(1)}`).join(' ')).join(' ');
    $('profile').setAttribute('d', path);
    const changes = run.data.frames.filter(frame => frame.time > run.start && frame.time <= run.end);
    $('marks').setAttribute('d', changes.map(frame => `M${x(frame).toFixed(1)} 23v7`).join(' '));
  }
  function sources(data) {
    const p = $('sources'); p.replaceChildren();
    if (data.demo) p.append('Dane syntetyczne · ');
    for (const [label, name, href] of [['Lot', data.flight_source, data.flight_source_url], ['Radar', data.radar_source, data.radar_source_url]]) {
      p.append(`${label}: `);
      if (href && /^https:\/\//i.test(href)) {
        const link = document.createElement('a'); link.href = href; link.textContent = name;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; p.append(link);
      } else p.append(name || 'nie podano');
      p.append(' · ');
    }
    const satellite = document.createElement('a');
    satellite.href = 'https://esa-worldcover.org/en/data-access';
    satellite.target = '_blank'; satellite.rel = 'noopener noreferrer';
    satellite.textContent = 'Podkład satelitarny z 2021 r.';
    p.append(satellite);
    $('note').hidden = false;
    $('note').querySelector('p').textContent = [data.note,
      '© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium.',
      'Granice: PRG / GUGiK. Podkład ogólny: Natural Earth.'].filter(Boolean).join(' ');
  }
  async function readTile(tile, signal) {
    const url = new URL(tile.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/flight-replay/tiles/')) throw Error('Nieprawidłowa ścieżka kafla.');
    const res = await fetch(url, {signal});
    if (!res.ok) throw Error('Brak kafla radaru.');
    const blob = await res.blob(), objectUrl = URL.createObjectURL(blob);
    try {
      const image = new Image(); image.src = objectUrl; await image.decode();
      return {tile, image};
    } finally {URL.revokeObjectURL(objectUrl);}
  }
  function addRadar(run, items) {
    const C = window.Cesium, scheme = new C.WebMercatorTilingScheme();
    const groups = new Map();
    for (const item of items) {
      if (!groups.has(item.tile.z)) groups.set(item.tile.z, []);
      groups.get(item.tile.z).push(item);
    }
    for (const [z, group] of [...groups].sort(([a],[b]) => a-b)) {
      const images = new Map(); let bounds;
      for (const {tile, image} of group) {
        images.set(`${tile.x}/${tile.y}`, image);
        const rect = scheme.tileXYToRectangle(tile.x, tile.y, z);
        bounds = bounds ? C.Rectangle.union(bounds, rect) : rect;
      }
      // Serve original XYZ pixels through their own Web Mercator projection. Cesium
      // reprojects the raster, including interior rows, before draping it on the globe.
      const provider = {tilingScheme:scheme, rectangle:bounds, minimumLevel:z, maximumLevel:z,
        tileWidth:group[0].image.naturalWidth, tileHeight:group[0].image.naturalHeight,
        hasAlphaChannel:true, errorEvent:new C.Event(), getTileCredits() {return undefined;},
        requestImage(x, y, level) {return Promise.resolve(level === z && images.get(`${x}/${y}`) || run.emptyTile);}};
      const layer = run.viewer.imageryLayers.addImageryProvider(provider);
      layer.alpha = .86;
      run.radarLayers.push(layer);
    }
    run.viewer.scene.requestRender();
  }
  async function updateRadar(run) {
    const {frame, usable} = D.radarAt(run.data.frames, run.time);
    if (frame === run.radar && usable === run.radarUsable) return;
    run.radar = frame;
    run.radarUsable = usable;
    run.radarAbort?.abort();
    for (const layer of run.radarLayers) run.viewer.imageryLayers.remove(layer, true);
    run.radarLayers = [];
    if (!usable || !frame.tiles.length) {
      setText('radar-time', frame && !usable ? `Radar · ostatnia klatka ${clock(frame.time)} jest starsza niż 15 min` : 'Radar · brak klatki dla tej chwili');
      return;
    }
    const prefix = `Radar ${run.data.frames.indexOf(frame) + 1}/${run.data.frames.length} · ${clock(frame.time)}`;
    setText('radar-time', `${prefix} · wczytywanie`);
    const controller = run.radarAbort = new AbortController();
    try {
      const items = [], queue = frame.tiles.values();
      async function load() {
        for (const tile of queue) {
          if (controller.signal.aborted) return;
          try {items.push(await readTile(tile, controller.signal));} catch { /* A missing tile leaves its area transparent. */ }
        }
      }
      await Promise.all(Array.from({length: Math.min(4, frame.tiles.length)}, load));
      if (controller.signal.aborted || active !== run || run.failed) return;
      if (items.length) addRadar(run, items);
      setText('radar-time', !items.length ? `${prefix} · kafle niedostępne` : items.length < frame.tiles.length ?
        `${prefix} · ${items.length}/${frame.tiles.length} kafli` : prefix);
    } catch {
      if (active === run && !controller.signal.aborted) setText('radar-time', `${prefix} · kafle niedostępne`);
    }
  }
  async function open(trigger = document.activeElement, episodeUrl = '/api/flight-replay') {
    if (active) return;
    const run = active = {trigger, abort:new AbortController(), radarLayers:[], radar:undefined,
      playing:false, emptyTile:document.createElement('canvas')};
    run.emptyTile.width = run.emptyTile.height = 256;
    const dialog = $('dialog');
    dialog.dataset.state = 'loading'; dialog.dataset.playing = 'false';
    controls.forEach(id => { $(id).disabled = true; });
    $('time').min = '0'; $('time').max = '1'; $('time').value = '0'; $('time').removeAttribute('aria-valuetext');
    $('speed').value = '10'; $('profile').removeAttribute('d'); $('marks').removeAttribute('d'); $('sources').replaceChildren();
    setText('elapsed', '');
    $('note').hidden = true; $('note').open = false;
    for (const id of ['clock', 'altitude', 'heading']) setText(id, '—');
    setText('date', ''); setText('radar-time', 'Radar · —');
    setText('title', 'Lot z radarem opadów'); setText('status', 'Wczytywanie lokalnego zapisu…');
    $('overview').setAttribute('aria-pressed','true'); $('follow').setAttribute('aria-pressed','false');
    dialog.showModal(); $('close').focus({preventScroll:true});
    try {
      const res = await fetch(episodeUrl, {signal:run.abort.signal});
      if (res.status === 404) {
        const message = (await res.json().catch(() => ({}))).detail;
        throw Error(typeof message === 'string' ? message : 'Brak lokalnego zapisu lotu z radarem.');
      }
      if (!res.ok) throw Error('Nie udało się wczytać lokalnego zapisu lotu.');
      const data = await res.json();
      if (active !== run) return;
      if (!Array.isArray(data.points) || data.points.length < 2 || !Array.isArray(data.frames)) throw Error('Niepełne dane odtworzenia.');
      run.data = data; run.start = data.points[0].time; run.end = data.points.at(-1).time; run.time = run.start;
      setText('title', data.label); sources(data); renderProfile(run);
      setText('status','Wczytywanie lokalnego silnika 3D…');
      const C = await window.WiciScene3D.loadEngine();
      if (active !== run) return;
      $('time').min = String(run.start); $('time').max = String(run.end); $('time').step = '1';
      initScene(run, C);
      if (run.failed) return;
      controls.forEach(id => { $(id).disabled = false; });
      dialog.dataset.state = 'ready';
    } catch (error) {
      if (active === run) fail(run, run.viewer || error.name === 'RuntimeError' ? 'Widok wymaga działającej grafiki WebGL 2. Zamknij i ponownie otwórz odtworzenie.' : error.message);
    }
  }
  $('play').addEventListener('click', play);
  $('time').addEventListener('input', () => {
    if (!active?.viewer || active.failed) return;
    active.time = Number($('time').value); active.last = performance.now(); draw(active);
  });
  for (const mode of ['follow', 'overview']) $(mode).addEventListener('click', () => { if (active?.viewer) setView(active, mode); });
  $('close').addEventListener('click', close);
  // Atlas treats any click outside its layer panel as a dismissal. Keep the
  // originating panel open and focusable throughout this separate modal.
  $('dialog').addEventListener('click', event => event.stopPropagation());
  $('dialog').addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault(); event.stopPropagation(); close();
  });
  $('dialog').addEventListener('cancel', event => { event.preventDefault(); close(); });
  $('dialog').addEventListener('close', () => { if (!$('dialog').open) close(); });
  document.addEventListener('visibilitychange', () => {
    if (!active?.viewer) return;
    if (document.hidden) pause(active);
    active.viewer.useDefaultRenderLoop = !document.hidden;
    if (!document.hidden) active.viewer.scene.requestRender();
  });
  return {open, close};
})();
