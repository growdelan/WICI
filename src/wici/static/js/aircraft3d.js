'use strict';
// One viewer owns both vehicle cameras and consumes the existing layer feeds.
window.WiciVehicle3D = (() => {
  const $ = id => document.getElementById(`aircraft3d-${id}`);
  const FRAME_MS = 1000 / 30;
  const profiles = {
    aircraft: {maxAgeMs:30000,key:'hex',noun:'samolotu',model:'aircraft',height:100,
      distance:{min:300,max:12000,step:100,value:1800},groundRadius:250,
      followBack:.57,followUp:.82,eyeAhead:7,eyeHeight:3,pitch:-12,modelHeadingOffset:-Math.PI/2,
      label:item=>item?.id || item?.registration || item?.hex || 'Samolot'},
    buses: {maxAgeMs:60000,key:'id',noun:'autobusu',model:'bus',height:0,
      distance:{min:15,max:500,step:5,value:70},groundRadius:6,
      followBack:.8,followUp:.6,eyeAhead:4.5,eyeHeight:2.2,pitch:-5,modelHeadingOffset:0,
      label:item=>`Autobus · linia ${item?.line || '—'} · ${item?.vehicle_number || item?.id || 'pojazd'}`}
  };
  let activeKind = null, profile = profiles.aircraft, scope = {};
  let map, initialized = false, enginePromise, engineCssReady = false, viewer, entity, ground, track, follower, selected;
  let session = 0, frame = null, lastFrame = 0, lastHud = 0, mode = 'follow';
  let snapshot, returnFocus, display, frozen = '', paused = false, orbit = 0, imagery;
  let renderFailed = false, removeRenderError = null, renderedCourse = null;
  let atlasPopupState = null;
  const scratch = {};
  const label = item => profile.label(item);
  const fresh = (item, settings = profile) => {
    const time = Date.parse(item?.position_at), age = Date.now() - time;
    return Number.isFinite(time) && age >= -30000 && age <= settings.maxAgeMs
      && Number.isFinite(item?.latitude) && Number.isFinite(item?.longitude)
      && Math.abs(item.latitude) <= 90 && Math.abs(item.longitude) <= 180
      && (settings === profiles.buses || Number.isFinite(item?.altitude_m));
  };
  function configure() {
    const bus = activeKind === 'buses', distance = profile.distance;
    $('eyebrow').textContent = bus ? `WICI · komunikacja miejska · ${scope.source?.name || scope.city || ''}` : 'WICI · lotnictwo';
    $('scene').setAttribute('aria-label', `Globus 3D podążający za ${bus ? 'autobusem' : 'samolotem'}`);
    $('distance').min = String(distance.min); $('distance').max = String(distance.max);
    $('distance').step = String(distance.step); $('distance').value = String(distance.value);
    $('distance-value').textContent = `${distance.value} m`;
    $('behind').textContent = bus ? 'Za autobusem' : 'Za samolotem';
    $('description').textContent = bus
      ? 'Wirtualny widok z pozycji autobusu, około 2,2 m nad uproszczoną powierzchnią WGS84. Animacja opóźniona o 12 s, bez przewidywania dalszej jazdy. Między raportami pozycja jest interpolowana, bez dopasowania do dróg. Kierunek kamery pochodzi ze źródła lub jest szacowany z kolejnych pozycji i wtedy oznaczony. Brak pomiaru wysokości, rzeczywistej kabiny, rzeźby terenu i budynków.'
      : 'Wirtualny widok z pozycji samolotu. Animacja opóźniona o 12 s, krótka predykcja do 5 s; wstrzymywana przy braku aktualnych danych. Wysokość barometryczna jest przybliżeniem położenia nad powierzchnią. Kurs względem ziemi wyznacza kierunek kamery; przechylenie i pochylenie kadłuba są nieznane. Powierzchnia uproszczona, bez rzeźby terenu i budynków.';
    $('source').textContent = bus ? scope.source?.source || 'Źródło pozycji autobusów' : 'adsb.fi';
    $('source').href = bus ? scope.source?.url || '/notices' : 'https://adsb.fi/';
    $('source-note').textContent = bus ? `${scope.source?.license || ''} · dane przetworzone przez WICI` : ' · użytek osobisty, niekomercyjny';
    $('model-note').textContent = bus ? 'Model autobusu: schematyczny, nie przedstawia konkretnego typu.' : 'Model samolotu: schematyczny, nie przedstawia konkretnego typu.';
  }
  function status(text, state = '') {
    if ($('status').textContent !== text) $('status').textContent = text;
    $('dialog').dataset.state = state;
  }
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
  function stopFrame() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
  }
  function updatePovAvailability(sample, pose = sample) {
    renderedCourse = !renderFailed && Number.isFinite(sample?.track) && Number.isFinite(pose?.track)
      ? pose.track : null;
    $('pov').disabled = renderedCourse === null;
    $('pov').title = $('pov').disabled ? 'Pierwsza osoba wymaga znanego kursu wyświetlanej pozycji.'
      : 'Widok zgodny z kursem wyświetlanej pozycji.';
    if (mode === 'pov' && $('pov').disabled) setMode('follow');
  }
  function failRendering(message) {
    if (renderFailed) return;
    renderFailed = true;
    stopFrame(); updatePovAvailability(null);
    status(message, 'error');
  }
  function holdAtlasPopup(popup) {
    if (!popup?.isOpen()) return;
    atlasPopupState = {popup, autoPan: popup.options.autoPan};
    // Leaflet moves an open popup on every marker update, even under a modal.
    popup.options.autoPan = false;
    map.stop();
  }
  function releaseAtlasPopup() {
    if (!atlasPopupState) return;
    const {popup, autoPan} = atlasPopupState;
    atlasPopupState = null;
    if (popup.isOpen()) {
      const element = popup.getElement(), box = element.getBoundingClientRect();
      const bounds = map.getContainer().getBoundingClientRect();
      const topLeft = window.L.point(popup.options.autoPanPaddingTopLeft || popup.options.autoPanPadding);
      const bottomRight = window.L.point(popup.options.autoPanPaddingBottomRight || popup.options.autoPanPadding);
      const margin = parseFloat(window.getComputedStyle(element).marginBottom) || 0;
      // Closing an offscreen popup before restoring autoPan also prevents the
      // next feed update or focus restoration from pulling Atlas away again.
      if (box.left < bounds.left + topLeft.x || box.right > bounds.right - bottomRight.x
          || box.top < bounds.top + topLeft.y || box.bottom + margin > bounds.bottom - bottomRight.y) popup.close();
    }
    if (!popup.isOpen()) returnFocus = null;
    popup.options.autoPan = autoPan;
  }
  function close({restoreFocus = true} = {}) {
    session++; stopFrame();
    removeRenderError?.(); removeRenderError = null;
    try { if (viewer && !viewer.isDestroyed()) viewer.destroy(); }
    catch { /* A lost GPU must not prevent leaving the viewer. */ }
    viewer = entity = ground = imagery = null; selected = track = follower = display = null;
    activeKind = null; scope = {};
    snapshot = null; frozen = '';
    renderFailed = false; renderedCourse = null;
    $('scene')?.replaceChildren();
    releaseAtlasPopup();
    if ($('dialog')?.open) $('dialog').close();
    map?.invalidateSize({pan: false});
    if (restoreFocus) {
      const target = returnFocus?.isConnected && !returnFocus.disabled ? returnFocus : document.getElementById('map');
      target?.focus({preventScroll: true});
    }
    returnFocus = null;
  }
  function sync({visible, enabled, mode: appMode, hidden, city, line} = {}) {
    if (!selected) return;
    if (!enabled || appMode !== 'live' || (!visible && !hidden)
        || (activeKind === 'buses' && ((city && city !== scope.city) || (line && String(selected.line) !== String(line))))) {
      close({restoreFocus: false}); return;
    }
    paused = Boolean(hidden);
    if (paused) stopFrame();
    else if (viewer && !renderFailed && frame === null) { lastFrame = 0; frame = requestAnimationFrame(animate); }
  }
  function update(data, context = {}) {
    if (!selected) return;
    if (activeKind === 'buses' && context.city !== scope.city) return;
    snapshot = data;
    if (data?.stale || data?.status === 'error') {
      frozen = 'Odczyt niedostępny. Ruch wstrzymany do otrzymania świeżych danych.';
      return;
    }
    const item = data?.items?.find(item => item[profile.key] === selected[profile.key]);
    if (!item) {
      frozen = activeKind === 'buses' ? 'Brak autobusu w ostatnim odczycie. Ruch wstrzymany.'
        : 'Brak samolotu w ostatnim odczycie. Mógł opuścić Polskę lub zasięg źródła. Ruch wstrzymany.';
      return;
    }
    // A late provider snapshot must not roll back the source clock, altitude,
    // camera availability or an already accepted observation.
    if (Date.parse(item.position_at) < Date.parse(selected.position_at)) return;
    if (!fresh(item)) {
      frozen = activeKind === 'buses' ? 'Brak świeżej pozycji. Ruch wstrzymany.' : 'Brak świeżej pozycji lub wysokości. Ruch wstrzymany.';
      return;
    }
    selected = item; track.push(item); frozen = '';
    const name = label(item);
    $('title').textContent = `${name} · śledzenie 3D`;
    if (entity) { entity.name = name; entity.label.text = name; }
  }
  function setMode(next) {
    if (next === 'pov' && (renderFailed || !Number.isFinite(renderedCourse))) return;
    mode = next;
    $('follow').setAttribute('aria-pressed', String(mode === 'follow'));
    $('pov').setAttribute('aria-pressed', String(mode === 'pov'));
    $('distance-control').hidden = mode !== 'follow';
    $('orbit-controls').hidden = mode !== 'follow';
    $('reticle').hidden = mode !== 'pov';
    if (entity) entity.show = mode === 'follow';
    $('view-note').textContent = mode === 'pov'
      ? activeKind === 'buses' ? 'Pierwsza osoba · wirtualny widok zgodny z kierunkiem jazdy, bez wnętrza kabiny.'
        : 'Pierwsza osoba · widok zgodny z kursem lotu, lekko poniżej horyzontu.'
      : 'Kamera zewnętrzna · odległość i obrót regulujesz poniżej.';
  }
  function hud(sample, now) {
    const age = Math.max(0, Math.floor((now - Date.parse(selected.position_at)) / 1000));
    const sourceTime = new Intl.DateTimeFormat('pl-PL', {timeZone: 'Europe/Warsaw', timeStyle: 'medium'})
      .format(new Date(selected.position_at));
    const altitude = activeKind === 'aircraft' ? `Wysokość barometryczna ${Math.round(selected.altitude_m).toLocaleString('pl-PL')} m · ` : '';
    const course = sample.course_source === 'estimated' ? 'Kurs szacowany z pozycji ' : 'Kurs ';
    $('telemetry').textContent = altitude
      + `${Number.isFinite(sample.speed_kmh) ? Math.round(sample.speed_kmh) + ' km/h' : 'Prędkość nieznana'} · `
      + `${Number.isFinite(sample.track) ? course + Math.round(sample.track) + '°' : 'Kurs nieznany'}`;
    $('time').textContent = `Raport ${sourceTime} · ${age} s temu · Europe/Warsaw`;
    if (frozen) status(frozen, 'holding');
    else if (sample.state === 'stale') status(`Pozycja starsza niż ${profile.maxAgeMs / 1000} s. Ruch wstrzymany; oczekiwanie na aktualizację.`, 'stale');
    else if (sample.state === 'holding') status(activeKind === 'buses' ? 'Oczekiwanie na kolejną pozycję. Ruch wstrzymany.'
      : 'Oczekiwanie na kolejną pozycję. Ruch wstrzymany po limicie przewidywania.', 'holding');
    else if (sample.state === 'warming') status('Oczekiwanie na kolejną pozycję do płynnej animacji.', 'warming');
    else status(sample.state === 'predicted' ? 'Krótka predykcja ruchu · maksymalnie 5 s poza ostatni raport.'
      : 'Płynne śledzenie · obraz opóźniony o 12 s względem czasu raportów.', sample.state);
  }
  function place(sample) {
    const C = window.Cesium;
    const height = Math.max(profile.height, sample.altitude_m);
    const position = C.Cartesian3.fromDegrees(sample.longitude, sample.latitude, height, C.Ellipsoid.WGS84, scratch.position);
    const heading = C.Math.toRadians(sample.track ?? 0);
    entity.position = position;
    // Include the model's axes after Cesium's glTF axis correction.
    entity.orientation = C.Transforms.headingPitchRollQuaternion(position, new C.HeadingPitchRoll(heading + profile.modelHeadingOffset, 0, 0));
    ground.position = C.Cartesian3.fromDegrees(sample.longitude, sample.latitude, 0);
    const transform = C.Transforms.eastNorthUpToFixedFrame(position, C.Ellipsoid.WGS84, scratch.transform);
    if (mode === 'follow') {
      const distance = Number($('distance').value), angle = heading + orbit;
      const offset = new C.Cartesian3(-Math.sin(angle) * distance * profile.followBack, -Math.cos(angle) * distance * profile.followBack, distance * profile.followUp);
      viewer.camera.lookAtTransform(transform, offset);
    } else {
      // Untracked world-space placement avoids a competing EntityView camera.
      const destination = C.Matrix4.multiplyByPoint(transform, new C.Cartesian3(Math.sin(heading) * profile.eyeAhead, Math.cos(heading) * profile.eyeAhead, profile.eyeHeight), scratch.camera);
      viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
      viewer.camera.setView({destination, orientation: {heading, pitch: C.Math.toRadians(profile.pitch), roll: 0}});
    }
    entity.show = mode === 'follow';
  }
  function animate(time) {
    frame = null;
    if (!viewer || renderFailed || paused || !selected) return;
    try {
      if (time - lastFrame >= FRAME_MS) {
        lastFrame = time;
        const now = Date.now(), sampled = track.sample(now);
        if (sampled) {
          if (display && display.segment !== sampled.segment) follower.clear();
          // API failures/missing contacts hold the last displayed position immediately.
          display = follower.step(sampled, time, {freeze:Boolean(frozen) || sampled.state === 'stale'});
          updatePovAvailability(sampled, display);
          place(display);
          if (now - lastHud >= 1000) { hud({...display, track:renderedCourse, state: sampled.state}, now); lastHud = now; }
        }
        viewer.resize(); viewer.render();
      }
      if (!renderFailed) frame = requestAnimationFrame(animate);
    } catch {
      failRendering('Renderowanie 3D zostało przerwane. Wróć do Atlasu i spróbuj ponownie.');
    }
  }
  async function basemap() {
    if (!viewer) return;
    if (imagery) { viewer.imageryLayers.remove(imagery, true); imagery = null; }
    $('map-status').textContent = 'Lokalne granice Polski · powierzchnia uproszczona, bez rzeźby terenu i budynków.';
    if (!$('osm').checked) return;
    const current = viewer;
    try {
      const provider = new window.Cesium.OpenStreetMapImageryProvider({
        url: 'https://tile.openstreetmap.org/', maximumLevel: 17,
        credit: new window.Cesium.Credit('<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>', true)
      });
      provider.errorEvent.addEventListener(() => {
        if (viewer === current) $('map-status').textContent = 'Kafelki OSM niedostępne. Lokalne granice i śledzenie pozostają dostępne.';
      });
      imagery = viewer.imageryLayers.addImageryProvider(provider);
      $('map-status').textContent = 'OpenStreetMap · powierzchnia uproszczona, bez rzeźby terenu i budynków.';
    } catch {
      $('map-status').textContent = 'Nie udało się włączyć OSM. Dostępne są lokalne granice Polski.';
    }
  }
  async function localContext(current, run) {
    try {
      const response = await fetch('/static/geo/provinces.geojson');
      if (!response.ok) throw new Error();
      const geo = await response.json();
      if (run !== session || current !== viewer) return;
      const C = window.Cesium;
      const bus = activeKind === 'buses', gridHeight = bus ? .03 : 20;
      // A fine coordinate grid gives the local surface scale even inside a
      // province, where there may be no nearby border or city in the frame.
      const grid = current.entities.add({name:'Siatka współrzędnych'});
      const gridColor = C.Color.fromCssColorString('#aec4bb').withAlpha(.12);
      for (let lon = 14; lon <= 24.5; lon += .1) current.entities.add({parent:grid,
        polyline:{positions:C.Cartesian3.fromDegreesArrayHeights([lon,49,gridHeight,lon,55,gridHeight]),
          width:1,arcType:C.ArcType.RHUMB,material:gridColor}});
      for (let lat = 49; lat <= 55; lat += .1) current.entities.add({parent:grid,
        polyline:{positions:C.Cartesian3.fromDegreesArrayHeights([14,lat,gridHeight,24.5,lat,gridHeight]),
          width:1,arcType:C.ArcType.RHUMB,material:gridColor}});
      // Explicitly local GeoJSON; no Cesium ion/imagery/terrain defaults.
      const data = await C.GeoJsonDataSource.load(geo, {
        stroke: C.Color.fromCssColorString('#aec4bb'), strokeWidth: 2,
        fill: C.Color.fromCssColorString('#385852').withAlpha(.58), clampToGround: false
      });
      if (run !== session || current !== viewer) { data.entities.removeAll(); return; }
      current.dataSources.add(data);
      const places = [['Warszawa',21.0122,52.2297],['Kraków',19.945,50.0647],['Gdańsk',18.6466,54.352],
        ['Poznań',16.9252,52.4064],['Wrocław',17.0385,51.1079],['Szczecin',14.5528,53.4285],['Łódź',19.456,51.7592]];
      for (const [name,lon,lat] of places) current.entities.add({position:C.Cartesian3.fromDegrees(lon,lat,bus ? 2 : 100),
        label:{text:name,font:'14px sans-serif',fillColor:C.Color.WHITE,outlineColor:C.Color.BLACK,
          outlineWidth:3,style:C.LabelStyle.FILL_AND_OUTLINE,distanceDisplayCondition:new C.DistanceDisplayCondition(0,bus ? 15000 : 300000)}});
    } catch {
      if (run === session) $('map-status').textContent = 'Brak lokalnych granic. Śledzenie pozostaje dostępne; możesz włączyć OSM.';
    }
  }
  async function open(kind, item, data, focus, popup, context = {}) {
    const settings = profiles[kind];
    if (!initialized || !fresh(item, settings) || data?.stale || data?.status === 'error'
        || (kind === 'buses' && !context.city)) return;
    if ($('dialog').open) close({restoreFocus:false});
    const run = ++session;
    activeKind = kind; profile = settings; scope = context;
    selected = item; snapshot = data; returnFocus = focus;
    track = kind === 'buses' ? window.WiciBusMotion.createTrack() : window.WiciAircraftMotion.createTrack();
    track.push(item);
    follower = window.WiciAircraftCameraMotion.createFollower();
    display = null; frozen = ''; paused = false; orbit = 0; lastFrame = lastHud = 0;
    renderFailed = false; renderedCourse = null;
    $('title').textContent = `${label(item)} · śledzenie 3D`;
    $('telemetry').textContent = ''; $('time').textContent = '';
    $('scene').replaceChildren();
    configure();
    updatePovAvailability(null);
    setMode('follow'); status('Wczytywanie lokalnego silnika 3D…', 'loading');
    holdAtlasPopup(popup);
    $('dialog').showModal(); $('close').focus();
    try {
      const C = await loadEngine();
      if (run !== session) return;
      // The standalone IIFE embeds a classic-worker blob which importScripts
      // another blob. Use the separately vendored ESM workers instead, keeping
      // script-src restricted to same-origin JavaScript.
      window.CESIUM_WORKERS = undefined;
      viewer = new C.Viewer($('scene'), {
        animation:false,timeline:false,baseLayerPicker:false,fullscreenButton:false,vrButton:false,
        geocoder:false,homeButton:false,infoBox:false,sceneModePicker:false,navigationHelpButton:false,
        selectionIndicator:false,projectionPicker:false,baseLayer:false,
        terrainProvider:new C.EllipsoidTerrainProvider(),useDefaultRenderLoop:false,
        shouldAnimate:false,scene3DOnly:true,skyBox:false,showRenderLoopErrors:false,
        contextOptions:{webgl:{alpha:false,antialias:true,preserveDrawingBuffer:false}}
      });
      // Cesium emits renderError without throwing by default. Its built-in
      // loop is disabled, so the WICI loop must stop itself and stay stopped.
      removeRenderError = viewer.scene.renderError.addEventListener(() => {
        if (run !== session) return;
        failRendering('Renderowanie 3D zostało przerwane. Wróć do Atlasu i spróbuj ponownie.');
      });
      viewer.scene.globe.baseColor = C.Color.fromCssColorString('#203d3c');
      viewer.scene.globe.enableLighting = false;
      viewer.scene.screenSpaceCameraController.enableInputs = false;
      viewer.scene.fog.enabled = false;
      viewer.scene.globe.maximumScreenSpaceError = 4;
      viewer.resolutionScale = Math.min(1, 1.5 / (window.devicePixelRatio || 1));
      scratch.position = new C.Cartesian3(); scratch.transform = new C.Matrix4(); scratch.camera = new C.Cartesian3();
      // Feed updates can arrive while the engine loads, including a later
      // failure that makes update(snapshot) keep the last accepted selection.
      const entityName = label(selected);
      entity = viewer.entities.add({name:entityName,position:C.Cartesian3.fromDegrees(item.longitude,item.latitude,kind === 'buses' ? 0 : item.altitude_m),
        model:{uri:`/static/models/${profile.model}.gltf`,minimumPixelSize:kind === 'buses' ? 36 : 42,maximumScale:kind === 'buses' ? 1 : 30},
        point:{pixelSize:6,color:C.Color.fromCssColorString('#ffd377'),outlineColor:C.Color.BLACK,outlineWidth:1},
        label:{text:entityName,font:'14px sans-serif',pixelOffset:new C.Cartesian2(0,-35),
          fillColor:C.Color.WHITE,outlineColor:C.Color.BLACK,outlineWidth:3,style:C.LabelStyle.FILL_AND_OUTLINE}});
      ground = viewer.entities.add({position:C.Cartesian3.fromDegrees(item.longitude,item.latitude),
        ellipse:{semiMajorAxis:profile.groundRadius,semiMinorAxis:profile.groundRadius,
          material:C.Color.fromCssColorString('#ffc36b').withAlpha(.3),height:kind === 'buses' ? .04 : 2}});
      update(snapshot, scope); basemap(); localContext(viewer, run);
      // Losing the GPU must leave a usable exit, never a stuck modal.
      viewer.canvas.addEventListener('webglcontextlost', () => {
        if (run !== session) return;
        failRendering('Utracono dostęp do grafiki 3D. Wróć do Atlasu i otwórz widok ponownie.');
      });
      frame = requestAnimationFrame(animate);
    } catch (error) {
      if (run !== session) return;
      removeRenderError?.(); removeRenderError = null;
      try { if (viewer && !viewer.isDestroyed()) viewer.destroy(); }
      catch { /* The error message and exit remain available after GPU failure. */ }
      viewer = null; $('scene').replaceChildren();
      failRendering(error?.message?.startsWith('Nie udało') ? error.message : 'Widok 3D wymaga dostępnego WebGL 2. Atlas pozostaje dostępny.');
    }
  }
  function init(options) {
    if (initialized || !$('dialog')) return;
    initialized = true; map = options.map;
    $('close').addEventListener('click', () => close());
    $('dialog').addEventListener('cancel', event => { event.preventDefault(); close(); });
    $('follow').addEventListener('click', () => setMode('follow'));
    $('pov').addEventListener('click', () => setMode('pov'));
    $('distance').addEventListener('input', () => { $('distance-value').textContent = `${$('distance').value} m`; });
    $('left').addEventListener('click', () => { orbit -= Math.PI / 6; });
    $('right').addEventListener('click', () => { orbit += Math.PI / 6; });
    $('behind').addEventListener('click', () => { orbit = 0; });
    $('osm').addEventListener('change', basemap);
    document.addEventListener('wici:regionchange', () => { if (selected) close({restoreFocus:false}); });
    // Capture Escape before Atlas panels behind the modal can consume it.
    document.addEventListener('keydown', event => {
      if (!$('dialog').open || event.key !== 'Escape') return;
      event.preventDefault(); event.stopImmediatePropagation(); close();
    }, true);
  }
  function adapter(kind) {
    return {
      init,
      open: (item, data, focus, popup, context) => open(kind, item, data, focus, popup, context),
      update: (data, context) => { if (activeKind === kind) update(data, context); },
      sync: options => { if (activeKind === kind) sync(options); },
      close: options => { if (activeKind === kind) close(options); }
    };
  }
  return {aircraft:adapter('aircraft'),buses:adapter('buses')};
})();
window.WiciAircraft3D = window.WiciVehicle3D.aircraft;
window.WiciBuses3D = window.WiciVehicle3D.buses;
