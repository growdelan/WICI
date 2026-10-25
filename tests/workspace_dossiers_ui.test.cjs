const test = require('node:test');
const assert = require('node:assert/strict');
const {capturePayload, canCapture, renderMaterial} = require('../src/wici/static/js/workspace-dossiers.js');

function context() {
  return {ready: true, detailReady: true, inScope: true, comparisonReady: true, state: {
    query: {types: ['hydro_station'], cursor: 'page2', query_revision: 7, time: {mode: 'range', filter_range: {from: '2026-10-20T00:00:00Z', to: '2026-10-21T00:00:00Z'}}},
    selectedRef: 'hydro_station:imgw:1', selectedVersion: null, selectedSensor: null, selectedMetric: null,
    comparedRefs: ['aircraft:icao:48abc0'], comparedRegionRefs: ['ua_region:neptun:oblast:Kyiv'],
    asOf: '2026-10-21T11:00:00Z', dataRevision: 'rev123', cursorAt: '2026-10-20T12:00:00Z', displayTimezone: 'Europe/Kyiv',
  }};
}

test('capture submits source selectors and exact context without any client evidence or page cursor', () => {
  const c = context(), payload = capturePayload(c, 'timeline', '  Wisła  ');
  assert.equal(payload.ref, c.state.selectedRef);
  assert.equal(payload.metric, 'water_level');
  assert.equal(payload.cursor_at, c.state.cursorAt);
  assert.equal(payload.display_timezone, 'Europe/Kyiv');
  assert.equal(payload.data_revision, 'rev123');
  assert.equal(payload.as_of, c.state.asOf);
  assert.equal(payload.title, 'Wisła');
  assert.equal(payload.query.cursor, undefined);
  assert.equal(payload.query.query_revision, undefined);
  payload.query.types.push('ship');
  assert.deepEqual(c.state.query.types, ['hydro_station']);
  assert.equal('snapshot' in payload, false);
  assert.equal('data' in payload, false);
  const compared = capturePayload(c, 'comparison');
  assert.deepEqual(compared.moving_refs, c.state.comparedRefs);
  assert.deepEqual(compared.region_refs, c.state.comparedRegionRefs);
  assert.equal('sensor_id' in compared, false);
  assert.equal('ref' in compared, false);
});

test('capture controls reject stale selections, outside-scope cards and incomplete comparison while pins stay independent', () => {
  const c = context(); assert.equal(canCapture(c, 'object'), true); assert.equal(canCapture(c, 'timeline'), true);
  for (const patch of [{ready: false}, {detailReady: false}, {inScope: false}]) assert.equal(canCapture({...c, ...patch}, 'object'), false);
  assert.equal(canCapture({...c, comparisonReady: false}, 'comparison'), false);
  assert.equal(canCapture({...c, inScope: false}, 'comparison'), true);
  c.state.query.time.mode = 'live';
  assert.equal(canCapture(c, 'object'), true);
  assert.equal(canCapture(c, 'timeline'), false);
  assert.equal(canCapture(c, 'comparison'), false);
});

class Element {
  constructor(tag, text = '') {this.tag = tag; this.text = text == null ? '' : String(text); this.children = []; this.disabled = false;}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children = nodes;}
  get textContent() {return this.text + this.children.map(node => node.textContent || '').join(' ');}
  set textContent(text) {this.text = String(text); this.children = [];}
}
const U = {
  el(tag, text) {return new Element(tag, text);},
  button(text, callback) {const node = new Element('button', text); node.click = callback; return node;},
  value(row) {return row?.value == null ? 'Brak pomiaru' : `${row.value} ${row.unit || ''}`;},
  typeNames: {air_quality_station: 'Stacja GIOŚ'}, statusNames: {}, metricNames: {},
  safeLink(url, text) {try {const parsed = new URL(url); return ['http:', 'https:'].includes(parsed.protocol) ? new Element('a', text) : null;} catch {return null;}},
};
const flatten = node => [node, ...node.children.flatMap(flatten)];
const base = () => ({kind: 'object', title: 'Zapis', captured_at: '2026-10-21T12:00:00Z', sha256: 'abcdef', snapshot: {context: {display_timezone: 'UTC', query: {time: {mode: 'range', filter_range: {from: '2026-10-20T00:00:00Z', to: '2026-10-21T00:00:00Z'}}}}, objects: []}});

test('saved material renders source day precision, selected document version and filters executable URLs', () => {
  const material = base(); material.snapshot.objects = [{object: {ref: 'communication:1', type: 'communication', label: 'Komunikat'}, communication: {text: 'Nowa treść'}, selected_version: {title: 'Wersja dawna', text: '<script>stored source text</script>', source_date: '2026-10-20', source_url: 'https://example.test/source'}, injected_url: 'javascript:alert(1)'}];
  const host = new Element('div'); renderMaterial(host, material, U);
  const sections = host.children.filter(node => node.tag === 'section'), card = sections[1];
  assert.match(card.textContent, /2026-10-20 · sama data/);
  assert.match(card.textContent, /Wersja dawna/);
  assert.match(card.textContent, /<script>stored source text<\/script>/);
  assert.doesNotMatch(card.textContent, /Nowa treść/);
  const links = flatten(host).filter(node => node.tag === 'a');
  assert.deepEqual(links.map(node => node.textContent), ['https://example.test/source']);
  assert.equal(flatten(host).some(node => node.tag === 'script'), false);
});

test('saved publication history preserves day-only precision instead of displaying a synthetic midnight', () => {
  const material = base(); material.kind = 'timeline';
  material.snapshot.objects = [{object: {ref: 'communication:1', type: 'communication', label: 'Komunikat'}}];
  material.snapshot.timeline = {items: [{kind: 'version', at: '2026-10-19T22:00:00Z', source_date: '2026-10-20', date_precision: 'day', version_number: 1, title: 'Publikacja dzienna'}]};
  const host = new Element('div'); renderMaterial(host, material, U);
  const history = host.children.find(node => node.tag === 'section' && node.textContent.startsWith('Pełny zapis'));
  assert.match(history.textContent, /2026-10-20 · sama data/);
  assert.doesNotMatch(history.textContent, /22:00/);
});

test('all saved history pages remain readable, including null samples and corrections; GIOS index is distinct', () => {
  const material = base(); material.kind = 'timeline';
  material.snapshot.objects = [{object: {ref: 'air_quality_station:gios:1', type: 'air_quality_station', label: 'GIOŚ', official_index: {name: 'Bardzo dobry', observed_at: '2026-10-20T09:00:00Z'}}, measurements: [], selected_measurement: null}];
  material.snapshot.timeline = {items: Array.from({length: 56}, (_, index) => ({observed_at: '2026-10-20T12:00:00Z', metric: 'PM10', sensor_id: String(index), value: index === 55 ? null : index, unit: 'µg/m³', revision: index === 54 ? 2 : 1})), official_indices: []};
  const host = new Element('div'); renderMaterial(host, material, U);
  assert.match(host.textContent, /Oficjalny indeks ogólny GIOŚ/); assert.match(host.textContent, /Bardzo dobry/);
  const history = host.children.find(node => node.tag === 'section' && node.textContent.startsWith('Pełny zapis'));
  const body = flatten(history).find(node => node.tag === 'tbody'); assert.equal(body.children.length, 50);
  const next = flatten(history).find(node => node.tag === 'button' && node.textContent === 'Następne rekordy →'); next.click();
  assert.equal(body.children.length, 6); assert.match(body.textContent, /Brak pomiaru/); assert.match(body.textContent, /PM10 · 54/);
  assert.equal(next.disabled, true); assert.match(history.textContent, /Strona 2 z 2/);
});

test('historical transport snapshot distinguishes a missing cursor point from current catalog last-known position', () => {
  const material = base(); material.snapshot.context.cursor_at = '2026-10-20T12:00:00Z';
  material.snapshot.objects = [{object: {ref: 'aircraft:icao:48abc0', type: 'aircraft', label: 'LOT1', last_known_position: {position_at: '2026-10-21T12:00:00Z', latitude: 52, longitude: 21}}}];
  const host = new Element('div'); renderMaterial(host, material, U);
  assert.match(host.textContent, /Brak zapisanej pozycji przy wybranym kursorze/);
  assert.match(host.textContent, /nie odtwarza tej chwili/);
  assert.match(host.textContent, /nie potwierdza lokalizacji przy kursorze/);
});

test('saved GIOS card preserves the absence of a selected sensor despite a backend latest measurement', () => {
  const material = base(), sample = {sensor_id: '12', metric: 'PM10', value: 32, unit: 'µg/m³', observed_at: '2026-10-20T12:00:00Z'};
  material.snapshot.objects = [{object: {ref: 'air_quality_station:gios:1', type: 'air_quality_station', label: 'GIOŚ', measurement: sample, official_index: {name: 'Dobry', observed_at: sample.observed_at}}, selected_measurement: sample, measurements: [sample]}];
  const host = new Element('div'); renderMaterial(host, material, U);
  const fact = (view, label) => {
    for (const dl of flatten(view).filter(node => node.tag === 'dl')) {
      const index = dl.children.findIndex(node => node.tag === 'dt' && node.textContent === label);
      if (index >= 0) return dl.children[index + 1].textContent;
    }
    return null;
  };
  assert.equal(fact(host, 'Wybrany pomiar'), 'Nie wybrano stanowiska');
  assert.equal(fact(host, 'Czas obserwacji'), null);
  assert.equal(fact(host, 'Oficjalny indeks ogólny GIOŚ'), 'Dobry');
  const table = flatten(host).find(node => node.tag === 'tbody');
  assert.match(table.textContent, /PM10 · 12/);
  assert.match(table.textContent, /32 µg\/m³/);
  material.snapshot.context.sensor_id = '12';
  const selectedHost = new Element('div'); renderMaterial(selectedHost, material, U);
  assert.equal(fact(selectedHost, 'Wybrany pomiar'), '32 µg/m³');
  assert.match(fact(selectedHost, 'Czas obserwacji'), /2026-10-20T12:00:00Z/);
});
