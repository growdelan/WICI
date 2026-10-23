'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const Alerts = require('../src/wici/static/js/workspace-alerts.js'), Store = require('../src/wici/static/js/workspace-store.js');
const {create: createSources} = require('../src/wici/static/js/workspace-sources.js');
const range = {from: '2026-10-23T10:00:00Z', to: '2026-10-23T11:00:00Z'}, region = 'ua_region:neptun:oblast:львівська';
const episode = 'civil_alert:neptun:11111111-1111-4111-8111-111111111111';
const series = {ref: region, label: 'Львівська область', segments: [
  {from: range.from, to: '2026-10-23T10:15:00Z', state: 'red', episode_ref: episode},
  {from: '2026-10-23T10:15:00Z', to: '2026-10-23T10:30:00Z', state: 'unknown'},
  {from: '2026-10-23T10:30:00Z', to: range.to, state: 'none'},
]};
const flush = () => new Promise(resolve => setImmediate(resolve));
function node(tag = 'div', text) {
  const classes = new Set();
  return {tagName: tag.toUpperCase(), textContent: text, children: [], dataset: {}, value: '', hidden: false, isConnected: true,
    style: {setProperty(key, value) {this[key] = value;}}, classList: {add: value => classes.add(value), toggle(value, enabled) {enabled ? classes.add(value) : classes.delete(value);}, remove: value => classes.delete(value)},
    append(...children) {this.children.push(...children);}, replaceChildren(...children) {this.children = children;}, setAttribute(key, value) {this[key] = value;}, removeAttribute(key) {delete this[key];},
    addEventListener(event, handler) {this[event] = handler;}, focus() {}, get firstChild() {return this.children[0];}, get lastChild() {return this.children.at(-1);}};
}
const flatten = value => [value, ...(value.children || []).flatMap(flatten)];
function ui() {return {el: node, button(text, action) {return Object.assign(node('button', text), {click: action});}, field(label, control) {const el = node('label', label); el.append(control); return el;}, date: value => value || 'Brak czasu', typeNames: {}, statusNames: {}, safeLink: () => null};}

test('alarm cursor preserves half-open transitions, explicit gaps and empty periods', () => {
  assert.equal(Alerts.frameAt(series, range.from, range).state, 'red');
  assert.equal(Alerts.frameAt(series, '2026-10-23T10:14:59Z', range).segment.episode_ref, episode);
  assert.equal(Alerts.frameAt(series, '2026-10-23T10:15:00Z', range).state, 'unknown');
  assert.equal(Alerts.frameAt(series, '2026-10-23T10:30:00Z', range).state, 'none');
  assert.equal(Alerts.frameAt(series, null, range).state, 'none');
  assert.equal(Alerts.frameAt(series, range.to, range).state, 'unknown');
  assert.equal(Alerts.frameAt({segments: [series.segments[0]]}, '2026-10-23T10:20:00Z', range).state, 'unknown');
  assert.equal(Alerts.frameAt(null, range.from, range).state, 'unknown');
});

test('region comparison is independent of routes, capped at five and restored with a validated timezone', () => {
  let state = Store.reducer(Store.initialState(), {type: 'TOGGLE_COMPARE', ref: 'aircraft:icao:48abc0'});
  const refs = Array.from({length: 6}, (_, i) => `${region}${i}`);
  for (const ref of [...refs, episode, 'area:prg:14']) state = Store.reducer(state, {type: 'TOGGLE_REGION_COMPARE', ref});
  assert.deepEqual(state.comparedRegionRefs, refs.slice(0, 5)); assert.deepEqual(state.comparedRefs, ['aircraft:icao:48abc0']);
  const saved = Store.reducer(state, {type: 'APPLY_VIEW', config: {comparedRegionRefs: [region, region, episode], displayTimezone: 'Europe/Kyiv', query: {country: 'UA', region_ref: region}}});
  assert.deepEqual(saved.comparedRegionRefs, [region]); assert.equal(saved.displayTimezone, 'Europe/Kyiv'); assert.equal(saved.query.country, 'UA');
  assert.equal(Store.reducer(saved, {type: 'SET_TIMEZONE', timezone: 'bad'}), saved);
  assert.equal(Store.reducer(saved, {type: 'APPLY_VIEW', config: {displayTimezone: 'bad'}}).displayTimezone, 'Europe/Warsaw');
  assert.deepEqual(Store.reducer(saved, {type: 'CLEAR_REGION_COMPARE'}).comparedRegionRefs, []);
});

test('time inputs convert Kyiv and UTC without changing the represented instant; DST gaps remain invalid', () => {
  const window = {WiciWorkspaceUI: {}}; vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-timeline.js', 'utf8'), {window, Date, Intl});
  const {localValue, toUTC} = window.WiciWorkspaceTimeline;
  assert.equal(localValue(range.from, 'Europe/Kyiv'), '2026-10-23T13:00'); assert.equal(localValue(range.from, 'UTC'), '2026-10-23T10:00');
  assert.equal(toUTC('2026-10-23T13:00', 'Europe/Kyiv'), '2026-10-23T10:00:00.000Z');
  assert.equal(toUTC('2026-03-29T03:30', 'Europe/Kyiv'), null);
  assert.equal(toUTC('2026-10-25T03:30', 'Europe/Kyiv'), '2026-10-25T00:30:00.000Z');
  assert.equal(toUTC('2026-03-29T03:30', 'UTC'), '2026-03-29T03:30:00.000Z');
});

test('cold Ukrainian scope loads geometry once per day and alarms each fifteen seconds; history withdraws both', async () => {
  let time = 100000; const reads = [], timers = new Map(); let id = 0;
  const sources = createSources({now: () => time, hidden: () => false, delay: (fn, ms) => {timers.set(++id, {fn, ms}); return id;}, cancel: id => timers.delete(id), read: async path => {reads.push(path); return {status: 'ready', alerts: {fetched_at: range.from}};}});
  sources.setTypes(['ua_region', 'civil_alert']); sources.setVisible(true); await flush();
  assert.deepEqual(reads, ['/ukraine/alerts', '/ukraine/geometry']); assert.deepEqual([...timers.values()].map(timer => timer.ms).sort((a,b) => a-b), [15000, 86400000]);
  await sources.request('/ukraine/alerts'); await sources.request('/ukraine/geometry'); assert.equal(reads.length, 2);
  sources.setTypes(['ua_region'], {live: false}); assert.equal(timers.size, 0); time += 16000; await flush(); assert.equal(reads.length, 2);
  sources.setTypes(['ua_region'], {live: true}); await flush(); assert.equal(reads.length, 3); assert.equal(reads.filter(path => path === '/ukraine/geometry').length, 1);
  sources.setVisible(false); assert.equal(timers.size, 0);
});

test('alarm lanes expose gaps, coverage and exact episode navigation at the segment start', () => {
  const U = ui(), window = {WiciWorkspaceUI: U}; vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-alerts.js', 'utf8'), {window, Date, Object, Number, Map, JSON});
  const host = node(), selected = [], cursors = [];
  const view = window.WiciWorkspaceAlerts.view(host, {remove() {}, clear() {}, select: ref => selected.push(ref), range() {}, cursor: at => cursors.push(at), fit() {}});
  const state = {...Store.initialState(), comparedRegionRefs: [region], cursorAt: range.from, query: {...Store.initialState().query, time: {mode: 'range', filter_range: range}}};
  const payload = {...series, stats: {episode_count: 1, alarm_seconds: 900, longest_alarm_seconds: 900, covered_seconds: 2700, coverage_ratio: .75}};
  view.render(state, {data: {series: [payload]}, frames: new Map([[region, Alerts.frameAt(series, range.from, range)]])});
  const items = flatten(host), segment = items.find(item => item.dataset.episodeRef === episode);
  segment.click(); assert.deepEqual(selected, [episode]); assert.deepEqual(cursors, ['2026-10-23T10:00:00.000Z']);
  assert.ok(items.some(item => item.dataset.alertState === 'unknown' && item.style.width === '25%'));
  assert.ok(items.some(item => String(item.textContent).includes('75.0%') && String(item.textContent).includes('niepełne')));
  assert.ok(items.some(item => String(item.textContent).includes('15 min')));
});

test('historical regional map changes to a dashed unknown interval without borrowing current live alarm', () => {
  const added = [], U = ui(); U.measurement = () => null;
  const layer = (kind, geometry) => ({kind, geometry, addTo(group) {this.group = group; added.push(this); return this;}, bindTooltip() {return this;}, bindPopup() {return this;}, on() {return this;}, setStyle(value) {this.style = value;}, setTooltipContent() {}});
  const L = {layerGroup: () => layer('group'), geoJSON: geometry => layer('area', geometry)};
  const window = {WiciWorkspaceUI: U, WiciWorkspaceAlerts: Alerts, L}; vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-map.js', 'utf8'), {window, L, Date, Number, Set, Map});
  const map = window.WiciWorkspaceMap({map: {removeLayer() {}}, geometries: new Map(), select() {}}); map.setActive(true);
  const geometry = {type: 'Polygon', coordinates: [[[23,49],[24,49],[24,50],[23,49]]]}, replay = {series: [{...series, geometry}]};
  const state = {...Store.initialState(), comparedRegionRefs: [region], query: {...Store.initialState().query, time: {mode: 'range', filter_range: range}}};
  const data = {map: {areas: [{ref: region, type: 'ua_region', state: 'yellow', geometry}]}};
  map.render(data, state, null, null, null, {data: replay, frames: new Map([[region, Alerts.frameAt(series, range.from, range)]])});
  const area = added.filter(item => item.kind === 'area'); assert.equal(area.length, 1); assert.equal(area[0].style.color, Alerts.colors.red);
  map.render(data, state, null, null, null, {data: replay, frames: new Map([[region, Alerts.frameAt(series, '2026-10-23T10:20:00Z', range)]])});
  assert.equal(added.filter(item => item.kind === 'area').length, 1); assert.equal(area[0].style.color, Alerts.colors.unknown); assert.equal(area[0].style.dashArray, '5 5');
});

function controller() {
  const requests = [], sourceCalls = [], clip = [], renderedAlerts = []; let viewActions, timelineActions, tableActions, cardActions;
  const U = ui(), shell = node(), host = node(); host.closest = () => shell;
  const document = {hidden: false, activeElement: null, createElement: node, getElementById: id => id === 'analysis-workspace' ? host : null, addEventListener() {}};
  const source = {setVisible() {}, setTypes(types, options) {sourceCalls.push({types, options});}, subscribe() {}, deactivate() {}, demandIndexes() {}};
  const window = {WiciWorkspaceUI: U, WiciWorkspaceStore: Store, WiciWorkspaceAlerts: {...Alerts, view: () => ({render(state, context) {renderedAlerts.push(context);}})}, WiciWorkspaceSources: source,
    WiciRegion: {code: () => '14', setAnalysisOutsidePoland: value => clip.push(value)},
    WiciWorkspaceViews: (host, actions) => {viewActions = actions; return {load() {}};}, WiciWorkspaceTable: (host, actions) => {tableActions = actions; return {render() {}};},
    WiciWorkspaceTimeline: {create: (host, actions) => {timelineActions = actions; return {render() {}};}}, WiciWorkspaceMap: () => ({render() {}, setActive() {}}),
    WiciObjectCard: (host, actions) => {cardActions = actions; return {render() {}, focus() {}};}};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-controller.js', 'utf8'), {window, document, URLSearchParams, Date, Intl, structuredClone, AbortController,
    localStorage: {getItem() {return null;}, setItem() {}}, setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}});
  window.WiciWorkspace.init({map: {invalidateSize() {}}, health: {now: range.to}, geometries: new Map(), api: (path, body, options) => new Promise((resolve, reject) => requests.push({path, body, options, resolve, reject}))});
  const query = {items: [], total: 0, next_cursor: null, map: {items: []}, coverage: {sources: []}, data_revision: 'one', as_of: range.to};
  return {ui: window.WiciWorkspace, host, requests, sourceCalls, clip, renderedAlerts, query, viewActions, timelineActions, tableActions, cardActions};
}

test('restoring Ukrainian views never starts recording or sources; unassigned raions remain selectable', async () => {
  const h = controller(); h.ui.setActive(true);
  h.requests.find(item => item.path === '/workspace/ukraine/regions').resolve({items: [{ref: region, label: 'Львівська область', scope: 'oblast', native_key: 'львівська'}, {ref: 'ua_region:neptun:raion:непризначений', label: 'Без обводу', scope: 'raion', parent_ref: null}]});
  h.requests.find(item => item.path === '/workspace/ukraine/recording').resolve({enabled: false, last_success_at: null}); await flush();
  h.viewActions.apply({query: {types: ['ua_region'], country: 'UA', province: null, region_ref: null, time: {mode: 'range', filter_range: range, overview_range: range}}, comparedRegionRefs: [region], displayTimezone: 'Europe/Kyiv'}, 'saved');
  assert.equal(h.ui.getState().displayTimezone, 'Europe/Kyiv'); assert.equal(h.ui.getState().query.province, null);
  assert.equal(h.requests.filter(item => item.path === '/workspace/ukraine/replay').length, 1);
  assert.equal(h.requests.filter(item => item.options?.method === 'PUT').length, 0);
  assert.equal(h.sourceCalls.at(-1).types.length, 0); assert.equal(h.clip.at(-1), true);
  const raion = flatten(h.host).find(item => item.id === 'analysis-ua-raion'); assert.equal(raion.disabled, false); assert.equal(raion.children.length, 2);
  h.ui.setActive(false); assert.equal(h.clip.at(-1), false);
  h.ui.setActive(true); assert.equal(h.ui.getState().query.province, null);
  const config = h.viewActions.getConfig(); assert.equal(config.displayTimezone, 'Europe/Kyiv'); assert.deepEqual(Array.from(config.comparedRegionRefs), [region]); assert.equal(Object.hasOwn(config, 'recording'), false);
});

test('recording is changed only through its explicit PUT control and cursor changes perform no reads', async () => {
  const h = controller(); h.ui.setActive(true);
  h.requests.find(item => item.path === '/workspace/ukraine/recording').resolve({enabled: false}); await flush();
  const control = flatten(h.host).find(item => item.id === 'analysis-ukraine-record-enabled'); control.checked = true; control.change();
  const mutation = h.requests.find(item => item.options?.method === 'PUT'); assert.equal(mutation.path, '/workspace/ukraine/recording'); assert.equal(mutation.body.enabled, true);
  mutation.resolve({enabled: true}); await flush();
  h.timelineActions.dispatch({type: 'SET_TIME_RANGE', range}); const count = h.requests.length;
  h.timelineActions.dispatch({type: 'SET_CURSOR', at: range.from}); h.timelineActions.dispatch({type: 'SET_CURSOR', at: '2026-10-23T10:15:00Z'});
  assert.equal(h.requests.length, count); assert.equal(control.checked, true);
});

test('a stale region replay cannot overwrite the next comparison response', async () => {
  const h = controller(); h.ui.setActive(true); h.timelineActions.dispatch({type: 'SET_TIME_RANGE', range});
  h.tableActions.compare(region); const first = h.requests.filter(item => item.path === '/workspace/ukraine/replay').at(-1);
  h.tableActions.compare('ua_region:neptun:oblast:київська'); const second = h.requests.filter(item => item.path === '/workspace/ukraine/replay').at(-1);
  assert.equal(first.options.signal.aborted, true); second.resolve({series: [series]}); await flush(); first.resolve({series: []}); await flush();
  assert.deepEqual(Array.from(h.ui.getState().comparedRegionRefs), [region, 'ua_region:neptun:oblast:київська']);
  assert.equal(h.renderedAlerts.at(-1).data.series.length, 1); assert.equal(h.renderedAlerts.at(-1).data.series[0].ref, region);
});

test('region and episode cards follow the shared frame including unknown gaps, never the live state', () => {
  const U = ui(), window = {WiciWorkspaceUI: U, WiciWorkspaceAlerts: Alerts};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/object-card.js', 'utf8'), {window, Date, Number});
  const host = node(), card = window.WiciObjectCard(host, {select() {}, compare() {}});
  const state = {...Store.initialState(), selectedRef: region, detailOpen: true, queryRevision: 1, detailRevision: 1, comparedRegionRefs: [region], query: {...Store.initialState().query, time: {mode: 'range', filter_range: range}}};
  const detail = {object: {ref: region, label: 'Львівська область', type: 'ua_region', state: 'yellow', metadata: {}}, ukraine: {episodes: [], revisions: []}, _detailRevision: 1, _queryRevision: 1};
  const render = (shown, at) => {card.render(shown, null, {...state, selectedRef: shown.object.ref, cursorAt: at}, null, {alerts: {frames: new Map([[region, Alerts.frameAt(series, at, range)]])}}); return flatten(host).find(item => item.className === 'analysis-reading' || item.tagName === 'STRONG' && Object.hasOwn(item.dataset, 'alertState'));};
  assert.equal(render(detail, range.from).dataset.alertState, 'red'); assert.equal(render(detail, '2026-10-23T10:20:00Z').dataset.alertState, 'unknown');
  const alert = {...detail, object: {...detail.object, type: 'civil_alert', ref: episode, region_ref: region, metadata: {region_ref: region, source_since: range.from}}};
  assert.equal(render(alert, range.from).dataset.alertState, 'red'); assert.equal(render(alert, '2026-10-23T10:35:00Z').dataset.alertState, 'none');
});

test('recording status from a slow GET cannot undo a newer explicit choice', async () => {
  const h = controller(); h.ui.setActive(true);
  const firstRead = h.requests.find(item => item.path === '/workspace/ukraine/recording'); firstRead.resolve({enabled: false}); await flush();
  h.ui.setActive(false); h.ui.setActive(true); const staleRead = h.requests.filter(item => item.path === '/workspace/ukraine/recording').at(-1);
  const control = flatten(h.host).find(item => item.id === 'analysis-ukraine-record-enabled'); control.checked = true; control.change();
  const write = h.requests.find(item => item.options?.method === 'PUT'); write.resolve({enabled: true}); await flush(); staleRead.resolve({enabled: false}); await flush();
  assert.equal(control.checked, true);
});


test('all countries clears the hidden Polish province left by Situation when leaving Ukrainian scope', () => {
  const h = controller(); h.ui.setActive(true);
  const country = flatten(h.host).find(item => item.id === 'analysis-country');
  country.value = 'UA'; country.change(); assert.equal(h.ui.getState().query.country, 'UA'); assert.equal(h.ui.getState().query.province, null);
  country.value = ''; country.change(); assert.equal(h.ui.getState().query.country, null); assert.equal(h.ui.getState().query.province, null);
  country.value = 'PL'; country.change(); assert.equal(h.ui.getState().query.province, '14');
});
