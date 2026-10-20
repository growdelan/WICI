'use strict';
// Values are point observations/model samples; no spatial interpolation is implied.
window.WiciWeather = (() => {
  const byId = id => document.getElementById(id);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const toDirection = from => ((from + 180) % 360 + 360) % 360;
  const windColor = speed => speed < 10 ? '#287fac' : speed < 30 ? '#168575' : speed < 50 ? '#bb7214' : '#b73252';
  const rainColor = amount => amount < 1 ? '#71b9ec' : amount < 5 ? '#327ad5' : '#6745b7';
  const node = (tag, text, cls) => { const item = document.createElement(tag); if (text != null) item.textContent = text; if (cls) item.className = cls; return item; };
  const timestamp = value => { if (!value) return 'Nie podano'; const d = new Date(value); return Number.isNaN(d.getTime()) ? 'Nie podano' : new Intl.DateTimeFormat('pl-PL', {timeZone:'Europe/Warsaw', dateStyle:'short', timeStyle:'short'}).format(d); };
  const number = (value, suffix) => finite(value) ? `${value.toLocaleString('pl-PL', {maximumFractionDigits:1})} ${suffix}` : 'Brak pomiaru / wartości';
  let map, api, health = {}, visible = true, data = null, currentMode = 'measurement';
  let activePopup = null;
  let group, canvas, raf = null, playback = null, refresh = null, generation = 0, fetching = false, active = false, pendingPlay = false, lastError = '', streaks = [];
  const controls = {};
  const enabled = () => controls.wind.checked || controls.rain.checked;
  const shown = () => visible && !document.hidden && enabled();
  const sampleAt = point => point.samples?.[currentMode === 'forecast' ? Number(controls.hour.value) : 0];
  function status(message, problem = false) { if (controls.status.textContent !== message) controls.status.textContent = message; controls.status.classList.toggle('notice', problem); }
  function stopPlayback() {
    pendingPlay = false;
    if (playback !== null) clearInterval(playback); playback = null;
    controls.play.textContent = '▶ Odtwarzaj prognozę'; controls.play.setAttribute('aria-pressed', 'false');
  }
  function stopMotion() {
    stopPlayback();
    if (raf !== null) cancelAnimationFrame(raf); raf = null;
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  }
  function stopRefresh() { if (refresh !== null) clearTimeout(refresh); refresh = null; }
  function popup(point, sample) {
    const box = node('div', null, 'weather-popup');
    box.append(node('h3', point.name || point.id || 'Punkt pogody'));
    box.append(node('p', currentMode === 'forecast' ? 'Prognoza modelowa Open-Meteo; nie pomiar.' : 'Pomiar na stacji IMGW.'));
    if (health.mode === 'demo' || data.status === 'demo' || data.demo) box.append(node('p', 'DEMO · dane syntetyczne', 'notice'));
    if (data.stale || lastError) box.append(node('p', 'Zachowane dane mogą być nieaktualne.', 'notice'));
    const dl = node('dl');
    const direction = finite(sample.wind_direction_deg) ? `${Math.round(sample.wind_direction_deg)}° z · ${Math.round(toDirection(sample.wind_direction_deg))}° do` : 'Brak kierunku';
    const rows = [[currentMode === 'forecast' ? 'Czas prognozy' : 'Najnowszy pomiar w zestawie', timestamp(sample.time)], ['Wiatr', number(sample.wind_speed_kmh, 'km/h')], ['Kierunek', direction], ['Porywy', number(sample.wind_gust_kmh, 'km/h')], ['Czas porywów', timestamp(sample.wind_gust_time || (currentMode === 'forecast' ? sample.time : null))], ['Czas kierunku', timestamp(sample.wind_direction_time || (currentMode === 'forecast' ? sample.time : null))], ['Czas wiatru', timestamp(sample.wind_time || (currentMode === 'forecast' ? sample.time : null))], ['Opad', number(sample.precipitation_mm, `mm / ${data.precipitation_period_minutes || (currentMode === 'measurement' ? 10 : 60)} min`)], ['Okres opadu', `${data.precipitation_period_minutes || (currentMode === 'measurement' ? 10 : 60)} min kończące się o ${timestamp(sample.precipitation_time || (currentMode === 'forecast' ? sample.time : null))}`], ['Pobrano lokalnie', timestamp(data.fetched_at)]];
    for (const [name, value] of rows) dl.append(node('dt', name), node('dd', value));
    box.append(dl, node('p', 'Opad całkowity, także śnieg. Suma za okres kończący się w podanym czasie.'));
    try { const url = new URL(data.source_url); if (['http:', 'https:'].includes(url.protocol)) { const link = node('a', data.source_name || 'Źródło danych'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; box.append(link); } } catch { /* A missing link must not prevent point details. */ }
    return box;
  }
  function report() {
    if (!shown()) { status(enabled() ? 'Pogoda wstrzymana, gdy mapa jest ukryta.' : 'Warstwy pogody wyłączone.'); return; }
    if (!data) { status(lastError ? `Nie udało się pobrać pogody: ${lastError}` : 'Wczytywanie pogody…', !!lastError); return; }
    const warning = data.stale || lastError;
    const prefix = health.mode === 'demo' || data.status === 'demo' || data.demo ? 'DEMO · dane syntetyczne · ' : '';
    status(`${prefix}${currentMode === 'forecast' ? 'Prognoza modelowa' : 'Pomiary punktowe'} · ${(data.points||[]).filter(p=>!window.WiciRegion||window.WiciRegion.contains(p.latitude,p.longitude)).length} punktów w obszarze · pobrano ${timestamp(data.fetched_at)}${warning ? ' · dane nieaktualne / zachowane' : ''}${data.message ? ` · ${data.message}` : ''}${lastError ? ` · błąd odświeżenia: ${lastError}` : ''}`, !!warning || data.enabled === false || ['error','disabled'].includes(data.status));
  }
  function timeline() {
    const count = data?.times?.length || 0;
    controls.hour.max = Math.max(0, count - 1);
    controls.hour.value = Math.min(Number(controls.hour.value), Math.max(0, count - 1));
    const forecast = currentMode === 'forecast';
    controls.hour.disabled = !forecast || count < 2 || !shown();
    controls.play.disabled = !visible || document.hidden;
    controls.play.title = currentMode === 'measurement' ? 'Przełącz na prognozę i odtwarzaj kolejne godziny.' : 'Odtwarzaj kolejne godziny prognozy.';
    controls.time.textContent = forecast && count ? `${timestamp(data.times[Number(controls.hour.value)])} · Warszawa` : 'Bieżące pomiary';
    controls.range.textContent = forecast && count ? `${timestamp(data.times[0])} → ${timestamp(data.times[count - 1])} · krok 1 godzina` : forecast ? 'Prognoza do 48 godzin · krok 1 godzina' : 'Najnowsza próbka każdej stacji; czasy pomiarów mogą się różnić.';
    controls.legend.hidden = !enabled();
    controls.windLegend.hidden = !controls.wind.checked;
    controls.rainLegend.hidden = !controls.rain.checked;
    controls.rainUnit.textContent = `Opad · mm / ${currentMode === 'forecast' ? 'godzinę' : '10 min'}`;
  }
  function drawMotion(time) {
    raf = null;
    if (!shown() || !controls.wind.checked || !controls.animation.checked || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    canvas.setAttribute('data-motion-frame', String(Math.floor(time / 100)));
    canvas.setAttribute('data-motion-points', String(streaks.length));
    const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const item of streaks) {
      const point = map.latLngToContainerPoint(item.latlng);
      const phase = ((time / (2400 / Math.max(0.4, Math.min(2, item.speed / 20))) + item.phase) % 1);
      const offset = (phase - 0.5) * 36;
      const dx = Math.sin(item.direction), dy = -Math.cos(item.direction);
      ctx.globalAlpha = Math.sin(phase * Math.PI) * 0.7;
      ctx.strokeStyle = item.color; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(point.x + dx * (offset - 8), point.y + dy * (offset - 8)); ctx.lineTo(point.x + dx * offset, point.y + dy * offset); ctx.stroke();
    }
    ctx.globalAlpha = 1; raf = requestAnimationFrame(drawMotion);
  }
  function render(preservePopup = false) {
    const retainedPopup = preservePopup === true ? activePopup : null;
    if (!retainedPopup && activePopup) map.closePopup(activePopup);
    group.clearLayers(); streaks = [];
    if (raf !== null) cancelAnimationFrame(raf); raf = null;
    const size = map.getSize(); canvas.width = size.x; canvas.height = size.y;
    L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
    timeline(); report();
    if (!shown() || !data || data.enabled === false) return;
    const occupied = new Set();
    for (const [index, point] of (data.points || []).entries()) {
      if (window.WiciRegion && !window.WiciRegion.contains(point.latitude, point.longitude)) continue;
      if (!finite(point.latitude) || !finite(point.longitude)) continue;
      const sample = sampleAt(point); if (!sample) continue;
      const latlng = [point.latitude, point.longitude];
      const position = map.latLngToContainerPoint(latlng);
      if (position.x < -40 || position.y < -40 || position.x > size.x + 40 || position.y > size.y + 40) continue;
      const details = () => popup(point, sample);
      if (controls.rain.checked && finite(sample.precipitation_mm) && sample.precipitation_mm > 0) {
        L.circleMarker(latlng, {pane:'weatherRain', radius:Math.min(14, 5 + Math.sqrt(sample.precipitation_mm) * 2), color:rainColor(sample.precipitation_mm), weight:1, fillColor:rainColor(sample.precipitation_mm), fillOpacity:0.35, bubblingMouseEvents:false}).bindPopup(details, {maxWidth:340,maxHeight:340}).bindTooltip(node('span', `${point.name || 'Punkt'} · ${number(sample.precipitation_mm, 'mm')}`)).addTo(group);
      }
      if (!controls.wind.checked || !finite(sample.wind_speed_kmh) || sample.wind_speed_kmh < 0 || (sample.wind_speed_kmh > 0 && !finite(sample.wind_direction_deg))) continue;
      const key = `${Math.floor(position.x / 38)}:${Math.floor(position.y / 38)}`;
      if (occupied.has(key)) continue; occupied.add(key);
      const color = windColor(sample.wind_speed_kmh);
      const arrow = node('span', sample.wind_speed_kmh === 0 ? '○' : '↑', 'weather-arrow');
      arrow.style.color = color; arrow.style.transform = `rotate(${toDirection(sample.wind_direction_deg || 0)}deg)`;
      arrow.setAttribute('aria-hidden', 'true');
      const title = `${point.name || 'Punkt'} · ${number(sample.wind_speed_kmh, 'km/h')}`;
      L.marker(latlng, {pane:'weatherWind', icon:L.divIcon({html:arrow, className:'weather-wind-icon', iconSize:[28,28], iconAnchor:[14,14]}), title, keyboard:true, bubblingMouseEvents:false, riseOnHover:true}).bindPopup(details, {maxWidth:340,maxHeight:340}).bindTooltip(node('span',title)).addTo(group);
      if (sample.wind_speed_kmh > 0) streaks.push({latlng, direction:toDirection(sample.wind_direction_deg) * Math.PI / 180, speed:sample.wind_speed_kmh, color, phase:index * 0.618 % 1});
    }
    if (controls.animation.checked && controls.wind.checked) raf = requestAnimationFrame(drawMotion);
    if (retainedPopup) { retainedPopup.options.autoPan = false; retainedPopup.openOn(map); }
  }
  function schedule() {
    stopRefresh();
    if (shown()) refresh = setTimeout(() => load(), Math.max(60, Number(data?.refresh_seconds) || 600) * 1000);
  }
  async function load() {
    if (!shown() || fetching) return;
    const token = generation, mode = currentMode; fetching = true;
    if (!data) status('Wczytywanie pogody…');
    try {
      const result = await api(`/weather?mode=${mode}${window.WiciRegion?.code()?'&voivodeship='+window.WiciRegion.code():''}`);
      if (token !== generation || !shown() || mode !== currentMode) return;
      data = result; lastError = ''; render();
      if (pendingPlay) { pendingPlay = false; if (data.enabled !== false && data.times?.length > 1) startPlayback(); else stopPlayback(); }
    } catch (err) {
      if (token !== generation || !shown() || mode !== currentMode) return;
      lastError = err.message || String(err); stopPlayback(); render();
    } finally {
      if (token === generation) { fetching = false; schedule(); }
    }
  }
  function sync(options = {}) {
    if (!map) return;
    const modeChanged = options.health && health.mode !== options.health.mode;
    if (options.health) health = options.health;
    if (options.visible !== undefined) visible = options.visible;
    const next = shown();
    // Periodic parent health updates must not rebuild layers and close popups.
    const explicitSync = options.visible !== undefined || options.health !== undefined;
    if (explicitSync && !modeChanged && next === active) return;
    if (modeChanged || next !== active) {
      generation++; fetching = false; stopRefresh(); stopMotion();
      if (modeChanged) data = null;
    }
    active = next;
    render();
    if (next && (refresh === null && !fetching)) load();
  }
  function selectMode(mode) {
    generation++; fetching = false; stopRefresh(); stopMotion(); data = null; lastError = '';
    currentMode = mode; controls.mode.value = mode; controls.hour.value = 0; sync();
  }
  function startPlayback() {
    if (playback !== null) return;
    controls.play.textContent = 'Ⅱ Wstrzymaj'; controls.play.setAttribute('aria-pressed','true');
    playback = setInterval(() => { controls.hour.value = (Number(controls.hour.value) + 1) % (Number(controls.hour.max) + 1); render(); }, 1100);
  }
  function init(options) {
    if (map || !options.map) return;
    map = options.map; api = options.api; health = options.health || {};
    for (const [key, suffix] of Object.entries({wind:'wind', rain:'rain', animation:'animation', mode:'mode', hour:'hour', time:'time', range:'range', play:'play', status:'status', legend:'legend', windLegend:'wind-legend', rainLegend:'rain-legend', rainUnit:'rain-unit'})) controls[key] = byId(`weather-${suffix}`);
    for (const [name, z] of [['weatherRain',420],['weatherAnimation',425],['weatherWind',430]]) map.createPane(name).style.zIndex = String(z);
    map.getPane('weatherAnimation').style.pointerEvents = 'none';
    canvas = node('canvas', null, 'weather-animation-canvas'); canvas.setAttribute('aria-hidden','true'); map.getPane('weatherAnimation').append(canvas);
    group = L.layerGroup().addTo(map);
    controls.wind.addEventListener('change', () => sync()); controls.rain.addEventListener('change', () => sync());
    controls.mode.addEventListener('change', () => selectMode(controls.mode.value));
    controls.animation.addEventListener('change', render);
    controls.hour.addEventListener('input', render);
    controls.play.addEventListener('click', () => {
      if (playback !== null || pendingPlay) { stopPlayback(); return; }
      if (!visible || document.hidden) return;
      if (!enabled()) {
        controls.wind.checked = true;
        window.WiciPreferences?.remember(controls.wind);
      }
      window.WiciLayers?.update();
      if (currentMode !== 'forecast') selectMode('forecast');
      if (data?.enabled !== false && data?.times?.length > 1) { sync(); startPlayback(); return; }
      stopRefresh(); sync();
      pendingPlay = true;
      controls.play.textContent = 'Ⅱ Anuluj odtwarzanie'; controls.play.setAttribute('aria-pressed','true');
    });
    map.on('popupopen', event => { if (event.popup.getElement()?.querySelector('.weather-popup')) activePopup = event.popup; });
    map.on('popupclose', event => { if (event.popup === activePopup) activePopup = null; });
    map.on('moveend resize zoomend', () => render(true));
    map.on('movestart', () => { if (raf !== null) cancelAnimationFrame(raf); raf = null; canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height); });
    document.addEventListener('visibilitychange', () => sync());
    sync({visible:options.visible !== false});
  }
  document.addEventListener('wici:regionchange', () => {if(!map)return;if(currentMode==='forecast'){generation++;fetching=false;stopRefresh();stopMotion();data=null;lastError='';sync();}else render();});
  return {init, sync, helpers:{toDirection, windColor, rainColor}};
})();
