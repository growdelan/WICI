'use strict';
// This UTC acquisition day is independent of publication filters and GIOŚ readings.
window.WiciSentinel5P = (() => {
  const $ = name => document.getElementById('s5p-' + name);
  const text = (tag, value) => {const node = document.createElement(tag); node.textContent = value; return node;};
  const when = value => value ? String(value).replace('T', ' ').replace(/(?:\+00:00|Z)$/, ' UTC') : 'nieustalony';
  const percent = value => Number.isFinite(value) ? `${value.toFixed(1)}%` : 'nieustalony';
  const synthetic = data => data.demo || data.status === 'demo' || data.item?.id?.startsWith('DEMO');
  let map, visible = true, generation = 0, controller = null, items = [], layers = [], clock = null, result = null, wasActive = false;
  const active = () => !!map && visible && !document.hidden && $('enabled').checked;
  const status = value => {$('status').textContent = value;};
  const selected = () => ({parameter: $('parameter').value, day: $('day').value});
  const current = run => run === generation && active();

  function clear() {
    generation++; controller?.abort(); controller = null;
    if (clock !== null) clearInterval(clock); clock = null; result = null;
    for (const layer of layers) map.removeLayer(layer);
    layers = []; $('detail').replaceChildren(); $('legend').hidden = true;
    $('map-key').hidden = true;
  }
  function reset() {
    clear(); items = [];
    $('observation').replaceChildren(new Option('Najpierw wyszukaj obserwacje', ''));
    $('observation').disabled = true;
  }
  async function request(path, params, signal) {
    const response = await (window.WiciRegion?.fetch || fetch)('/api/sentinel5p/' + path + '?' + new URLSearchParams(params), {signal});
    const data = await response.json();
    if (!response.ok) {
      const message = typeof data.detail === 'string' ? data.detail : data.message || 'Nie udało się pobrać danych Sentinel-5P.';
      throw new Error(message + (response.headers.has('Retry-After') ? ` Ponów po ${response.headers.get('Retry-After')} s (Retry-After).` : ''));
    }
    return data;
  }
  function renderLegend(parameter) {
    const title = `${parameter.label} · ${parameter.unit}`;
    $('legend-title').textContent = title; $('map-title').textContent = title;
    $('legend-description').textContent = parameter.description || '';
    const stops = parameter.legend?.stops || [];
    $('legend-items').replaceChildren();
    for (const stop of stops) {
      const entry = text('span', ''), color = text('i', '');
      color.style.backgroundColor = stop.color;
      entry.append(color, text('span', stop.label || String(stop.value)));
      $('legend-items').append(entry);
    }
    $('map-scale').textContent = stops.length ? `≤ ${stops[0].label || stops[0].value} → ≥ ${stops.at(-1).label || stops.at(-1).value}` : '';
    // The same server scale drives pixels, the panel and the compact map key.
    const min = parameter.legend?.min, max = parameter.legend?.max;
    $('map-colorbar').style.background = stops.length && Number.isFinite(min) && max > min
      ? `linear-gradient(to right, ${stops.map(stop => `${stop.color} ${Number((100 * (stop.value - min) / (max - min)).toFixed(4))}%`).join(',')})` : '';
    $('legend').hidden = false;
  }
  function age() {
    if (!result || !active()) return;
    const timestamp = Date.parse(result.item.observation_end || result.item.observed_at);
    const hours = (Date.now() - timestamp) / 3600000;
    $('age').textContent = Number.isFinite(hours) && hours >= 0
      ? `Wiek od końca obserwacji: ${hours.toFixed(1)} h. Czas pobrania: ${when(result.fetched_at)}.`
      : `Wiek obserwacji nieustalony. Czas pobrania: ${when(result.fetched_at)}.`;
  }
  function details(data) {
    const item = data.item, quality = data.quality || {};
    const interval = `${when(item.observation_start || item.observed_at)} — ${when(item.observation_end || item.observed_at)}`;
    $('detail').replaceChildren(
      text('p', `${synthetic(data) ? 'DEMO — dane syntetyczne. ' : ''}Obserwacja: ${interval}. Tryb: ${item.mode || 'nieustalony'}.`),
      text('p', `Czas: ${item.time_basis || 'UTC; przedział produktu, nie dokładny czas każdego piksela'}.`),
      text('p', `Produkt: ${item.id}`),
      text('p', `Udział pikseli siatki mapy: ważne ${percent(quality.valid_percent)}; brak pokrycia ${percent(quality.no_coverage_percent)}; odrzucone jakościowo ${percent(quality.rejected_percent)}; NoData ${percent(quality.nodata_percent)}.`),
      text('p', `Prawidłowe zera: ${percent(quality.zero_percent)}. Ważne wartości ujemne: ${percent(quality.negative_percent)}. Zera i ujemne wartości nie są brakami danych.`),
      text('p', `Filtr produktu: ${data.parameter.quality_filter || 'nieustalony'}`),
      text('p', data.pixel_selection || 'Jeden wybrany produkt. Bez mozaiki innych obserwacji i bez interpolacji luk.')
    );
    if (item.product_ids?.some(id => id !== item.id)) $('detail').append(text('p', `Identyfikatory źródłowe: ${item.product_ids.join(', ')}`));
    if (item.processor_version) $('detail').append(text('p', `Wersja procesora: ${item.processor_version}.`));
    if (item.product_generated_at) $('detail').append(text('p', `Wygenerowano produkt: ${when(item.product_generated_at)}.${Number.isFinite(item.product_generation_delay_hours) ? ` Od końca obserwacji do generacji: ${item.product_generation_delay_hours.toFixed(1)} h.` : ''} Czas generacji nie jest czasem publikacji ani dostępności w CDSE.`));
    if (quality.coverage_basis) $('detail').append(text('p', quality.coverage_basis));
    if (Number.isFinite(quality.valid_of_covered_percent)) $('detail').append(text('p', `Ważne piksele w przybliżonym pokryciu: ${percent(quality.valid_of_covered_percent)}.`));
    if (Number.isFinite(quality.minimum) && Number.isFinite(quality.maximum)) $('detail').append(text('p', `Zakres ważnych wartości: ${quality.minimum} — ${quality.maximum} ${data.parameter.unit}. Wartości poza skalą barw pozostają zachowane.`));
    if (quality.mask_legend?.length) {
      $('mask-legend').replaceChildren();
      for (const entry of quality.mask_legend) {
        const label = text('span', ''), swatch = text('i', ''); swatch.style.backgroundColor = entry.color;
        label.append(swatch, text('span', entry.label)); $('mask-legend').append(label);
      }
    }
    const ageNode = text('p', ''); ageNode.id = 's5p-age'; $('detail').append(ageNode);
    if (item.attribution) $('detail').append(text('p', item.attribution));
    $('map-time').textContent = `${synthetic(data) ? 'DEMO · syntetyczne · ' : ''}${interval} · ${item.mode || 'tryb nieustalony'}`;
    $('map-key').hidden = false;
    renderLegend(data.parameter); result = data; age();
    const run = generation; clock = setInterval(() => {if (current(run)) age();}, 60000);
  }
  function opacity() {
    const value = Number($('opacity').value);
    $('opacity-value').textContent = `${value}%`;
    layers[0]?.setOpacity(value / 100);
    layers[1]?.setOpacity($('quality').checked ? value / 100 : 0);
  }
  function decode(encoded) {
    return new Promise((resolve, reject) => {
      const image = new Image(); image.onload = resolve;
      image.onerror = () => reject(new Error('Błąd dekodowania obrazu Sentinel-5P.'));
      image.src = 'data:image/png;base64,' + encoded;
    });
  }
  async function loadStatus() {
    if (!active()) return;
    clear(); const run = generation; controller = new AbortController();
    status('Sprawdzanie dostępu do Sentinel-5P…');
    try {
      const data = await request('status', {}, controller.signal);
      if (!current(run)) return;
      if (data.min_day) $('day').min = data.min_day;
      if (data.max_day) $('day').max = data.max_day;
      $('date-limits').textContent = data.min_day && data.max_day ? `Dostępny zakres WICI: ${data.min_day} — ${data.max_day}. Dzień UTC.` : 'Wyszukiwanie jednego dnia UTC.';
      if (data.latency_note) $('latency-note').textContent = data.latency_note;
      status(data.message || 'Wybierz dzień UTC i wyszukaj obserwacje.');
    } catch (error) {if (current(run) && error.name !== 'AbortError') status(error.message);}
  }
  async function search() {
    if (!active()) return;
    reset(); const run = generation, params = selected(); controller = new AbortController();
    status(`Wyszukiwanie obserwacji ${params.day} UTC…`);
    try {
      const data = await request('search', params, controller.signal);
      if (!current(run)) return;
      if ((data.day && data.day !== params.day) || (data.parameter?.id && data.parameter.id !== params.parameter)) throw new Error('Niezgodny dzień lub parametr odpowiedzi Sentinel-5P.');
      items = data.items || [];
      $('observation').replaceChildren(new Option(items.length ? 'Wybierz obserwację — czas UTC' : 'Brak obserwacji tego dnia', ''));
      for (const item of items) $('observation').append(new Option(`${when(item.observed_at)} · ${item.mode || 'tryb nieustalony'} · ${item.id}`, item.id));
      $('observation').disabled = !items.length;
      const summary = data.status === 'unconfigured' ? '' : items.length
        ? `${items.length} obserwacji dla ${params.day} UTC. Wybierz jedną.`
        : `Brak obserwacji dla ${params.day} UTC. Nie zastąpiono dnia innym.`;
      status(`${synthetic(data) ? 'DEMO — dane syntetyczne. ' : ''}${summary}${data.message ? ' ' + data.message : ''}${data.truncated ? ' Lista ograniczona przez limit wyników.' : ''}`.trim());
    } catch (error) {if (current(run) && error.name !== 'AbortError') status(error.message);}
  }
  async function render() {
    clear(); if (!active()) return;
    const item = items.find(entry => entry.id === $('observation').value);
    if (!item) {status('Wybierz dostępną obserwację.'); return;}
    const run = generation, params = {...selected(), identifier: item.id}; controller = new AbortController();
    status('Pobieranie obserwacji i masek jakości…');
    try {
      const data = await request('render', params, controller.signal);
      if (!current(run)) return;
      if (data.item?.id !== item.id || data.day !== params.day || data.parameter?.id !== params.parameter
          || data.item.observed_at !== item.observed_at) throw new Error('Niezgodna obserwacja, dzień lub parametr rastra Sentinel-5P.');
      if (!data.image) {status(data.message || 'Brak rastra dla wybranej obserwacji.'); return;}
      await Promise.all([data.image, data.mask].filter(Boolean).map(decode));
      if (!current(run)) return;
      for (const [key, pane] of [['image', 's5pData'], ['mask', 's5pQuality']]) {
        if (!data[key]) continue;
        const layer = L.imageOverlay('data:image/png;base64,' + data[key], data.bounds, {pane, interactive: false, className: 's5p-raster', attribution: data.item.attribution});
        layer.on('error', () => {if (current(run)) {clear(); status('Błąd wyświetlania obrazu Sentinel-5P. Wybierz obserwację ponownie.');}});
        layers.push(layer.addTo(map));
      }
      opacity(); details(data);
      status(`${synthetic(data) ? 'DEMO — dane syntetyczne. ' : ''}${['no_coverage', 'quality_rejected', 'nodata'].includes(data.status) ? 'Brak ważnych danych w tej obserwacji. ' : 'Wyświetlono wybraną obserwację. '}${data.message || ''} Brak sygnału nie oznacza czystego powietrza.`);
    } catch (error) {if (current(run) && error.name !== 'AbortError') {clear(); status(error.message);}}
  }
  function sync(options = {}) {
    if (!map) return;
    if (options.visible !== undefined) visible = options.visible;
    const enabled = active(); $('controls').hidden = !enabled;
    if (!enabled && wasActive) {reset(); status($('enabled').checked ? 'Warstwa Sentinel-5P wstrzymana poza widoczną mapą. Wyszukaj po powrocie.' : 'Warstwa Sentinel-5P wyłączona.');}
    if (enabled && !wasActive) status('Wybierz dzień UTC i wyszukaj obserwacje.');
    wasActive = enabled;
  }
  function init(options) {
    if (map || !options.map) return;
    map = options.map; if (options.visible !== undefined) visible = options.visible;
    for (const [name, z] of [['s5pData', 365], ['s5pQuality', 366]]) {const pane = map.createPane(name); pane.style.zIndex = z; pane.style.pointerEvents = 'none';}
    const day = new Date(); day.setUTCDate(day.getUTCDate() - 1); $('day').value = day.toISOString().slice(0, 10);
    $('enabled').addEventListener('change', () => {sync(); if (active()) loadStatus();});
    $('search').addEventListener('click', search); $('observation').addEventListener('change', render);
    for (const name of ['parameter', 'day']) $(name).addEventListener('change', () => {reset(); if (active()) status('Parametry zmienione. Wyszukaj obserwacje dla wybranego dnia UTC.');});
    $('opacity').addEventListener('input', opacity); $('quality').addEventListener('change', opacity);
    $('extent').addEventListener('click', () => {if (active()) map.fitBounds([[48, 12], [56, 26]], {maxZoom: 7});});
    document.addEventListener('visibilitychange', () => sync()); sync(); opacity();
  }
  return {init, sync};
})();
