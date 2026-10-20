'use strict';
window.WiciRadar = (() => {
  const $ = id => document.getElementById(`radar-${id}`);
  let map, api, data, layer, pending, visible = true, generation = 0, request = 0, fetching = false;
  let refresh = null, playback = null, wantsPlay = false, shownTime = null, failed = false;
  const shown = () => visible && !document.hidden && $('enabled').checked;
  const time = value => new Intl.DateTimeFormat('pl-PL', {timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'short'}).format(new Date(value));
  function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('notice', error); }
  function pause() { wantsPlay = false; if (playback !== null) clearInterval(playback); playback = null; $('play').textContent = '▶ Odtwarzaj radar'; $('play').setAttribute('aria-pressed','false'); }
  function clearPending() { request++; if (pending) map.removeLayer(pending); pending = null; }
  function frameLabel(frame) { $('time').textContent = frame ? `Klatka: ${time(frame.time)} · Warszawa` : 'Brak klatki'; }
  function report() {
    if (!shown()) { status($('enabled').checked ? 'Radar wstrzymany poza widoczną mapą.' : 'Radar wyłączony.'); return; }
    if (!data?.enabled) { status(data?.message || 'Wczytywanie radaru…', !!data); return; }
    const frame = data.frames.find(f => f.timestamp === shownTime);
    status(`${data.frames.length} klatek · ${frame ? time(frame.time) : 'wczytywanie obrazu'}${data.stale ? ' · dane nieaktualne' : ''}${failed ? ' · nie udało się wczytać wybranej klatki' : ''}${data.message ? ` · ${data.message}` : ''}`, data.stale || failed || data.status === 'error');
  }
  function controls() {
    const count = data?.frames?.length || 0;
    $('hour').max = Math.max(0, count-1);
    $('hour').disabled = !shown() || !count;
    $('opacity').disabled = !shown();
    $('legend').hidden = !shown() || !data?.enabled || !layer;
  }
  function startPlay() {
    if (!shown() || !data?.enabled || data.frames.length < 2 || playback !== null) return;
    wantsPlay = false; $('play').textContent = 'Ⅱ Wstrzymaj radar'; $('play').setAttribute('aria-pressed','true');
    playback = setInterval(() => { if (!pending) { $('hour').value = (Number($('hour').value)+1)%data.frames.length; draw(); } }, 1100);
  }
  function draw() {
    clearPending(); controls();
    if (!shown() || !data?.enabled || !data.frames.length) { report(); return; }
    if (!map.getBounds().intersects(L.latLngBounds(data.bounds))) { pause(); status('Radar obejmuje Polskę i najbliższe otoczenie. Przesuń mapę do Polski.'); return; }
    const frame = data.frames[Number($('hour').value)];
    const token = request, run = generation;
    const next = L.tileLayer(frame.tile_url, {pane:'radarPrecipitation',tileSize:256,bounds:data.bounds,
      minZoom:3,maxNativeZoom:data.max_native_zoom,maxZoom:18,noWrap:true,keepBuffer:0,
      updateWhenIdle:true,updateWhenZooming:false,opacity:0,
      attribution:'Weather data by <a href="https://www.rainviewer.com/" target="_blank" rel="noopener noreferrer">RainViewer</a>'});
    pending = next; let loaded = 0, errors = 0;
    next.on('tileload', () => loaded++); next.on('tileerror', () => errors++);
    // Leaflet still reads the layer after emitting load; defer removal until it finishes.
    next.on('load', () => queueMicrotask(() => {
      if (run !== generation || token !== request || !shown()) return;
      pending = null;
      if (errors || !loaded) {
        map.removeLayer(next); pause(); failed = true;
        const old = data.frames.findIndex(f => f.timestamp === shownTime);
        if (old >= 0) $('hour').value = old;
        controls(); report(); return;
      }
      if (layer) map.removeLayer(layer); layer = next; shownTime = frame.timestamp; failed = false;
      next.setOpacity(Number($('opacity').value)/100); frameLabel(frame); controls(); report();
      if (wantsPlay) startPlay();
    }));
    status(`Wczytywanie klatki ${time(frame.time)}${layer ? ' · poprzednia klatka pozostaje widoczna' : ''}…`);
    next.addTo(map);
  }
  function schedule() { if (refresh !== null) clearTimeout(refresh); refresh = null; if (shown()) refresh = setTimeout(() => load(), 300000); }
  async function load() {
    if (!shown() || fetching) return;
    fetching = true; const run = generation;
    if (!data) status('Wczytywanie radaru…');
    try {
      const result = await api('/radar');
      if (run !== generation || !shown()) return;
      const previous = data?.frames?.[Number($('hour').value)]?.timestamp;
      const followLatest = previous === data?.frames?.at(-1)?.timestamp;
      data = result; controls();
      const index = followLatest ? -1 : data.frames.findIndex(f => f.timestamp === previous);
      $('hour').value = index >= 0 ? index : Math.max(0,data.frames.length-1);
      if (!data.enabled || !data.frames.length) { pause(); clearPending(); if (layer) map.removeLayer(layer); layer = null; frameLabel(null); }
      draw();
    } catch {
      if (run !== generation || !shown()) return;
      pause(); failed = true; if (data) data = {...data,stale:true}; status('Nie udało się odświeżyć radaru; zachowano ostatni obraz, jeśli był dostępny.', true);
    } finally { if (run === generation) { fetching = false; schedule(); } }
  }
  function sync(options = {}) {
    if (!map) return;
    if (options.visible !== undefined) visible = options.visible;
    if (!shown()) {
      generation++; fetching = false; pause(); clearPending();
      if (refresh !== null) clearTimeout(refresh); refresh = null;
      if (layer) map.removeLayer(layer); layer = null; controls(); report(); return;
    }
    if (!data || refresh === null) load();
    if (!layer && data && !pending) draw();
  }
  function init(options) {
    if (map || !options.map) return;
    map = options.map; api = options.api;
    map.createPane('radarPrecipitation').style.zIndex = '370'; map.getPane('radarPrecipitation').style.pointerEvents = 'none';
    $('enabled').addEventListener('change', () => sync());
    $('hour').addEventListener('input', () => { pause(); draw(); });
    $('opacity').addEventListener('input', () => { if (layer) layer.setOpacity(Number($('opacity').value)/100); });
    $('play').addEventListener('click', () => {
      if (playback !== null || wantsPlay) { pause(); return; }
      $('enabled').checked = true;
      window.WiciPreferences?.remember($('enabled'));
      sync(); wantsPlay = true;
      $('play').textContent = 'Ⅱ Anuluj odtwarzanie'; $('play').setAttribute('aria-pressed','true');
      if (layer && !pending) startPlay();
      window.WiciLayers?.update();
    });
    map.on('moveend', () => { if (shown() && !pending) draw(); });
    sync({visible:options.visible !== false});
  }
  return {init,sync};
})();
