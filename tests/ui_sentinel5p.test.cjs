'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const initial = Date.parse('2026-10-17T12:00:00Z');
const flush = () => new Promise(resolve => setImmediate(resolve));
const allText = element => [element.textContent, ...element.children.map(allText)].join(' ');
function harness() {
  const controls = new Map(), requests = [], intervals = new Map(), images = [];
  let now = initial, timer = 0, manualImages = false;
  function element(tag) {
    const node = {tag, children: [], value: '', textContent: '', checked: false, hidden: false, disabled: false, style: {},
      addEventListener(name, callback) {this[name] = callback;},
      append(...children) {this.children.push(...children);},
      replaceChildren(...children) {this.children = [...children]; this.value = '';}};
    Object.defineProperty(node, 'id', {set(value) {controls.set(value, node);}});
    return node;
  }
  const document = {hidden: false, createElement: element, addEventListener(name, callback) {this[name] = callback;},
    getElementById(id) {if (!controls.has(id)) controls.set(id, element('div')); return controls.get(id);}};
  const map = {layers: new Set(), createPane() {return {style: {}};}, removeLayer(layer) {this.layers.delete(layer);}, fitBounds(bounds) {this.bounds = bounds;}};
  const L = {imageOverlay(source, bounds, options) {return {source, bounds, options, handlers: {},
    addTo(target) {target.layers.add(this); return this;}, on(name, callback) {this.handlers[name] = callback; return this;}, setOpacity(value) {this.opacity = value;}};}};
  class Clock extends Date {constructor(...args) {super(...(args.length ? args : [now]));} static now() {return now;}}
  class Image {set src(value) {this.source = value; images.push(this); if (!manualImages) queueMicrotask(() => this.onload());}}
  function Option(label, value) {const node = element('option'); node.textContent = label; node.value = value; return node;}
  const window = {};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/sentinel5p.js', 'utf8'), {
    window, document, L, URLSearchParams, Date: Clock, AbortController, Image, Option,
    fetch(url, options) {return new Promise((resolve, reject) => requests.push({url, signal: options.signal, reject,
      resolve(data, status = 200, headers = {}) {resolve({ok: status < 400, json: async () => data, headers: {has: name => name in headers, get: name => headers[name]}});}}));},
    setInterval(callback, delay) {assert.equal(delay, 60000); intervals.set(++timer, callback); return timer;}, clearInterval(id) {intervals.delete(id);}
  });
  const control = name => document.getElementById('s5p-' + name);
  control('parameter').value = 'no2'; control('opacity').value = '65'; control('observation').disabled = true;
  window.WiciSentinel5P.init({map});
  return {ui: window.WiciSentinel5P, document, map, requests, intervals, images, control,
    advance(ms) {now += ms;}, tick() {for (const callback of intervals.values()) callback();}, holdImages() {manualImages = true;}};
}
const parameter = id => ({id, label: id === 'no2' ? 'NO₂ — kolumna troposferyczna' : id === 'so2' ? 'SO₂ — kolumna pionowa' : 'UVAI', unit: id === 'aer_ai' ? '1 (bezwymiarowy)' : 'mol/m²',
  description: 'Opis produktu', quality_filter: id === 'no2' ? 'qa_value > 0.75' : 'qa_value > 0.5', legend: {min: -1, max: 1, stops: [{value: -1, color: '#123456'}, {value: 0, color: '#abcdef'}, {value: 1, color: '#fedcba'}]}});
const observation = (id = 'DEMO-NO2') => ({id, observed_at: '2026-10-16T11:00:00Z', observation_start: '2026-10-16T11:00:00Z', observation_end: '2026-10-16T11:05:00Z', mode: 'OFFL', attribution: 'Copernicus Sentinel-5P'});
function searchResult(id = 'no2', item = observation()) {return {status: 'demo', day: '2026-10-16', parameter: parameter(id), items: [item]};}
function renderResult(id = 'no2', item = observation()) {return {status: 'demo', day: '2026-10-16', parameter: parameter(id), item, image: 'image', mask: 'mask', bounds: [[48, 12], [56, 26]], fetched_at: '2026-10-17T10:00:00Z',
  quality: {valid_percent: 65, no_coverage_percent: 10, rejected_percent: 15, nodata_percent: 10, zero_percent: 2, negative_percent: 8}};}
async function enable(h) {
  h.control('enabled').checked = true; h.control('enabled').change();
  h.requests.at(-1).resolve({status: 'demo', message: 'DEMO — dane syntetyczne.', min_day: '2018-04-30', max_day: '2026-10-17'}); await flush();
}
async function search(h, payload = searchResult()) {h.control('search').click(); h.requests.at(-1).resolve(payload); await flush();}
async function select(h, payload = renderResult()) {h.control('observation').value = payload.item.id; h.control('observation').change(); h.requests.at(-1).resolve(payload); await flush();}

test('off by default, independent UTC day, requests only after explicit activation and selection', async () => {
  const h = harness(); assert.equal(h.requests.length, 0); assert.equal(h.intervals.size, 0);
  assert.equal(h.control('day').value, '2026-10-16'); assert.equal(h.control('controls').hidden, true);
  h.control('search').click(); h.control('parameter').change(); h.ui.sync({visible: true});
  assert.equal(h.requests.length, 0);
  await enable(h); assert.match(h.requests[0].url, /^\/api\/sentinel5p\/status\?/);
  assert.equal(h.control('day').min, '2018-04-30'); assert.match(h.control('date-limits').textContent, /UTC/);
  await search(h); assert.equal(h.requests.length, 2); assert.equal(h.map.layers.size, 0);
  const query = new URLSearchParams(h.requests.at(-1).url.split('?')[1]);
  assert.equal(query.get('day'), '2026-10-16'); assert.equal(query.get('parameter'), 'no2'); assert.equal([...query.keys()].length, 2);
  await select(h); assert.equal(h.map.layers.size, 2); assert.equal(h.intervals.size, 1);
  assert.match(h.control('legend-title').textContent, /mol\/m²/); assert.equal(h.control('map-key').hidden, false);
  assert.match(allText(h.control('detail')), /DEMO.*syntetyczne/); assert.match(allText(h.control('detail')), /OFFL/);
  assert.match(allText(h.control('detail')), /ważne 65.0%.*brak pokrycia 10.0%.*odrzucone jakościowo 15.0%.*NoData 10.0%/);
  assert.match(allText(h.control('detail')), /Prawidłowe zera: 2.0%.*ujemne: 8.0%/);
  assert.match(allText(h.control('detail')), /qa_value > 0.75/);
  assert.match(h.control('age').textContent, /24.9 h.*2026-10-17 10:00:00 UTC/);
  h.ui.sync({visible: true}); assert.equal(h.requests.length, 3); assert.equal(h.map.layers.size, 2);
});

test('opacity, masks, extent and aging never fetch new products', async () => {
  const h = harness(); await enable(h); await search(h); await select(h);
  const [raster, mask] = [...h.map.layers]; assert.equal(raster.opacity, 0.65); assert.equal(mask.opacity, 0);
  h.control('quality').checked = true; h.control('quality').change(); assert.equal(mask.opacity, 0.65);
  h.control('opacity').value = '0'; h.control('opacity').input(); assert.equal(raster.opacity, 0); assert.equal(mask.opacity, 0);
  h.control('opacity').value = '80'; h.control('opacity').input(); assert.equal(raster.opacity, 0.8); assert.equal(mask.opacity, 0.8);
  h.control('extent').click(); assert.equal(JSON.stringify(h.map.bounds), '[[48,12],[56,26]]');
  h.advance(3600000); h.tick(); assert.match(h.control('age').textContent, /25.9 h/); assert.equal(h.requests.length, 3);
});

for (const action of ['disable', 'view', 'tab', 'day', 'parameter']) test(`late search cannot populate options after ${action}`, async () => {
  const h = harness(); await enable(h); h.control('search').click(); const late = h.requests.at(-1);
  if (action === 'disable') {h.control('enabled').checked = false; h.control('enabled').change();}
  if (action === 'view') h.ui.sync({visible: false});
  if (action === 'tab') {h.document.hidden = true; h.document.visibilitychange();}
  if (action === 'day') {h.control('day').value = '2026-10-15'; h.control('day').change();}
  if (action === 'parameter') {h.control('parameter').value = 'so2'; h.control('parameter').change();}
  const message = h.control('status').textContent; assert.equal(late.signal.aborted, true);
  late.resolve(searchResult()); await flush();
  assert.equal(h.control('observation').children.length, 1); assert.equal(h.control('observation').disabled, true);
  assert.equal(h.control('status').textContent, message); assert.equal(h.requests.length, 2); assert.equal(h.intervals.size, 0);
});

test('late status cannot overwrite newer search, and late first render cannot replace second selection', async () => {
  const h = harness(); h.control('enabled').checked = true; h.control('enabled').change(); const oldStatus = h.requests[0];
  const first = observation('first'), second = observation('second');
  await search(h, {...searchResult('no2', first), items: [first, second]});
  oldStatus.resolve({message: 'Stara odpowiedź'}); await flush(); assert.doesNotMatch(h.control('status').textContent, /Stara odpowiedź/); assert.equal(oldStatus.signal.aborted, true);
  h.control('observation').value = 'first'; h.control('observation').change(); const firstRender = h.requests.at(-1);
  await select(h, renderResult('no2', second)); const visible = [...h.map.layers][0];
  firstRender.resolve(renderResult('no2', first)); await flush();
  assert.equal(firstRender.signal.aborted, true); assert.equal([...h.map.layers][0], visible);
  assert.match(allText(h.control('detail')), /Produkt: second/); assert.doesNotMatch(allText(h.control('detail')), /Produkt: first/);
});

test('disable or parameter change during image decoding prevents publication of a stale raster', async () => {
  for (const action of ['disable', 'parameter']) {
    const h = harness(); await enable(h); await search(h); h.holdImages(); await select(h);
    assert.equal(h.images.length, 2); assert.equal(h.map.layers.size, 0);
    if (action === 'disable') {h.control('enabled').checked = false; h.control('enabled').change();}
    else {h.control('parameter').value = 'aer_ai'; h.control('parameter').change();}
    h.images.forEach(image => image.onload()); await flush();
    assert.equal(h.map.layers.size, 0); assert.equal(h.intervals.size, 0); assert.equal(h.control('map-key').hidden, true);
  }
});

test('hiding clears rasters, provenance and clock; returning requires explicit search', async () => {
  const h = harness(); await enable(h); await search(h); await select(h); const tick = [...h.intervals.values()][0];
  h.ui.sync({visible: false}); const message = h.control('status').textContent; h.advance(3600000); tick();
  assert.equal(h.map.layers.size, 0); assert.equal(h.intervals.size, 0); assert.equal(h.control('detail').children.length, 0);
  assert.equal(h.control('legend').hidden, true); assert.equal(h.control('map-key').hidden, true); assert.equal(h.control('status').textContent, message);
  h.ui.sync({visible: true}); assert.equal(h.requests.length, 3); assert.equal(h.map.layers.size, 0);
});

test('parameter changes remove the previous units and keep UVAI separate from surface measurements', async () => {
  const h = harness(); await enable(h); await search(h); await select(h);
  h.control('parameter').value = 'aer_ai'; h.control('parameter').change();
  assert.equal(h.map.layers.size, 0); assert.equal(h.control('legend').hidden, true);
  const item = observation('DEMO-UVAI'); await search(h, searchResult('aer_ai', item)); await select(h, renderResult('aer_ai', item));
  assert.match(h.control('legend-title').textContent, /UVAI.*bezwymiarowy/); assert.doesNotMatch(h.control('legend-title').textContent, /mol|µg|PM/);
  assert.match(h.requests.at(-1).url, /parameter=aer_ai/);
});

test('empty day and no valid samples are explicit without choosing another day', async () => {
  const h = harness(); await enable(h); await search(h, {...searchResult(), status: 'ready', items: []});
  assert.match(h.control('status').textContent, /Brak obserwacji dla 2026-10-16 UTC.*Nie zastąpiono/);
  assert.equal(h.map.layers.size, 0); assert.equal(h.requests.length, 2);
  await search(h); const result = renderResult(); result.status = 'quality_rejected'; result.quality.valid_percent = 0; await select(h, result);
  assert.match(h.control('status').textContent, /Brak ważnych danych.*Brak sygnału nie oznacza czystego powietrza/);
});

test('provider errors, Retry-After and unavailable configuration stay visible without retry loops', async () => {
  const h = harness(); await enable(h); h.control('search').click();
  h.requests.at(-1).resolve({detail: 'Limit konta CDSE.'}, 429, {'Retry-After': '120'}); await flush();
  assert.match(h.control('status').textContent, /Limit konta.*120 s/); assert.equal(h.intervals.size, 0); assert.equal(h.requests.length, 2);
  await search(h, {...searchResult(), status: 'unconfigured', items: [], message: 'Brak konfiguracji Sentinel-5P.'});
  assert.match(h.control('status').textContent, /Brak konfiguracji/); assert.equal(h.control('observation').disabled, true);
});

test('mismatched day, parameter and observation fail closed; metadata renders as text', async () => {
  for (const field of ['day', 'parameter', 'id', 'time']) {
    const h = harness(); await enable(h); await search(h); const result = renderResult();
    if (field === 'day') result.day = '2026-10-15';
    if (field === 'parameter') result.parameter = parameter('so2');
    if (field === 'id') result.item.id = 'other';
    if (field === 'time') result.item.observed_at = '2026-10-16T09:00:00Z';
    h.control('observation').value = 'DEMO-NO2'; h.control('observation').change(); h.requests.at(-1).resolve(result); await flush();
    assert.equal(h.map.layers.size, 0); assert.match(h.control('status').textContent, /Niezgodna/);
  }
  const h = harness(), item = observation('<img src=x onerror=alert(1)>'); await enable(h); await search(h, searchResult('no2', item)); await select(h, renderResult('no2', item));
  assert.match(allText(h.control('detail')), /<img src=x onerror=alert\(1\)>/);
  assert.ok(h.control('detail').children.every(node => node.tag === 'p'));
});

test('image failures clear output and stop the age clock', async () => {
  const h = harness(); await enable(h); await search(h); await select(h);
  const oldTick = [...h.intervals.values()][0]; [...h.map.layers][0].handlers.error(); const message = h.control('status').textContent;
  h.advance(3600000); oldTick(); assert.equal(h.control('status').textContent, message);
  assert.match(message, /Błąd wyświetlania/); assert.equal(h.map.layers.size, 0); assert.equal(h.intervals.size, 0);
});

test('nonuniform numeric color stops and source mask swatches match the raster contract', async () => {
  const h = harness(); await enable(h); await search(h);
  const result = renderResult(); result.parameter.legend = {min: -0.0001, max: 0.0003, stops: [
    {value: -0.0001, color: '#3768b0'}, {value: 0, color: '#d6e8ef'},
    {value: 0.0001, color: '#efca55'}, {value: 0.0003, color: '#aa2959'}]};
  result.quality.mask_legend = [{label: 'Pokrycie przybliżone', color: '#677586'}, {label: 'Odrzucone', color: '#a65cdb'}, {label: 'NoData', color: '#edbd4c'}];
  await select(h, result);
  assert.equal(h.control('map-colorbar').style.background, 'linear-gradient(to right, #3768b0 0%,#d6e8ef 25%,#efca55 50%,#aa2959 100%)');
  assert.match(h.control('map-scale').textContent, /≤ -0.0001 → ≥ 0.0003/);
  assert.deepEqual(h.control('mask-legend').children.map(entry => entry.children[0].style.backgroundColor), ['#677586', '#a65cdb', '#edbd4c']);
});

test('grid percentages, pixel selection and generation time never imply surface area or publication latency', async () => {
  const h = harness(); await enable(h); await search(h); const result = renderResult();
  result.item.processor_version = '020901'; result.item.product_generated_at = '2026-10-16T13:00:00Z'; result.item.product_generation_delay_hours = 1.92;
  result.item.time_basis = 'UTC; przedział produktu, nie dokładny czas każdego piksela';
  result.pixel_selection = 'Jeden produkt; NEAREST bez interpolacji'; result.quality.coverage_basis = 'Przybliżony footprint. Udziały siatki, nie powierzchni.';
  result.quality.valid_of_covered_percent = 72.2; result.quality.minimum = -0.005; result.quality.maximum = 0;
  await select(h, result); const details = allText(h.control('detail'));
  assert.match(details, /Udział pikseli siatki mapy/); assert.doesNotMatch(details, /Udział obszaru/);
  assert.match(details, /nie dokładny czas każdego piksela/); assert.match(details, /NEAREST bez interpolacji/);
  assert.match(details, /Przybliżony footprint/); assert.match(details, /020901/);
  assert.match(details, /Od końca obserwacji do generacji: 1.9 h.*Czas generacji nie jest czasem publikacji ani dostępności/);
  assert.match(details, /72.2%/); assert.match(details, /Zakres ważnych wartości: -0.005 — 0 mol\/m²/);
});

test('pending render is aborted when disabled and cannot restore the prior observation', async () => {
  const h = harness(); await enable(h); await search(h);
  h.control('observation').value = 'DEMO-NO2'; h.control('observation').change(); const late = h.requests.at(-1);
  h.control('enabled').checked = false; h.control('enabled').change(); assert.equal(late.signal.aborted, true);
  late.resolve(renderResult()); await flush(); assert.equal(h.map.layers.size, 0); assert.equal(h.control('detail').children.length, 0);
  assert.equal(h.control('map-key').hidden, true); assert.equal(h.intervals.size, 0); assert.match(h.control('status').textContent, /wyłączona/);
});

test('catalog exclusion and truncation notices accompany available choices', async () => {
  const h = harness(); await enable(h);
  await search(h, {...searchResult(), message: 'Wykluczono SO₂ V1: wymagane dodatkowe filtry.', unsupported_product_count: 2, truncated: true});
  assert.equal(h.control('observation').disabled, false); assert.equal(h.control('observation').children.length, 2);
  assert.match(h.control('status').textContent, /1 obserwacji.*Wykluczono SO₂ V1.*Lista ograniczona/);
});

test('a tiny valid fraction rounded to zero percent is not reported as missing data', async () => {
  const h = harness(); await enable(h); await search(h);
  const result = renderResult(); result.status = 'ready'; result.quality.valid_percent = 0;
  await select(h, result);
  assert.match(h.control('status').textContent, /Wyświetlono wybraną obserwację/);
  assert.doesNotMatch(h.control('status').textContent, /Brak ważnych danych/);
});
