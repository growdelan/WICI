'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const Store = require('../src/wici/static/js/workspace-store.js');

test('query intent generations and detail generations are independent; closing invalidates pending cards', () => {
  const store = Store.createStore(); store.dispatch({type: 'SELECT_OBJECT', ref: 'communication:1'});
  const a = store.getState(); store.dispatch({type: 'SELECT_OBJECT', ref: 'communication:2'}); store.dispatch({type: 'SELECT_OBJECT', ref: 'communication:1'});
  assert.equal(store.getState().detailRevision, a.detailRevision + 2); assert.equal(store.getState().queryRevision, a.queryRevision);
  store.dispatch({type: 'CLOSE_CARD'}); assert.equal(store.getState().detailOpen, false); assert.equal(store.getState().selectedRef, 'communication:1');
  store.dispatch({type: 'SET_REGION', province: '14'}); assert.equal(store.getState().queryRevision, 1);
  store.dispatch({type: 'DATA_READY', revision: 0, dataRevision: 'stale', asOf: '2026-01-01T00:00:00Z'});
  assert.equal(store.getState().dataRevision, null);
});

test('historical cursor remains in half-open range and newest corrected null is not zero', () => {
  const store = Store.createStore(), range = {from: '2026-10-20T00:00:00Z', to: '2026-10-21T00:00:00Z'};
  store.dispatch({type: 'SET_TIME_RANGE', range}); store.dispatch({type: 'SET_CURSOR', at: range.to}); assert.equal(store.getState().cursorAt, null);
  store.dispatch({type: 'SET_CURSOR', at: range.from}); assert.equal(store.getState().cursorAt, '2026-10-20T00:00:00.000Z');
  const samples = [{sensor_id: '1', metric: 'PM10', observed_at: range.from, revision: 1, value: 30},
    {sensor_id: '1', metric: 'PM10', observed_at: range.from, revision: 2, value: null},
    {sensor_id: '2', metric: 'PM10', observed_at: range.from, revision: 3, value: 90}];
  assert.equal(Store.sampleAt(samples, range.from, range, '1', 'PM10').value, null);
  assert.equal(Store.sampleAt(samples, '2026-10-19T23:59:59Z', range, '1', 'PM10'), null);
  store.dispatch({type: 'REFRESH'}); assert.equal(store.getState().cursorAt, '2026-10-20T00:00:00.000Z');
});

test('saved view restores scope and layout without keeping stale selected sensor or version', () => {
  let state = Store.initialState(); state = {...state, selectedVersion: '1', selectedSensor: '44'};
  state = Store.reducer(state, {type: 'APPLY_VIEW', id: 'saved', config: {query: {province: '14'}, layout: {tablePercent: 60}, columns: ['label'], selectedRef: 'area:prg:14'}});
  assert.equal(state.query.province, '14'); assert.equal(state.selectedSensor, null); assert.equal(state.selectedVersion, null);
  assert.equal(state.layout.tablePercent, 60); assert.deepEqual(state.columns, ['label']); assert.equal(state.savedViewId, 'saved');
});

test('Warsaw local inputs account for 23h/25h days and reject nonexistent DST hour', () => {
  const window = {WiciWorkspaceUI: {}}; vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-timeline.js', 'utf8'), {window, Intl, Date});
  const time = window.WiciWorkspaceTimeline;
  assert.equal(Date.parse(time.toUTC('2026-03-30T00:00')) - Date.parse(time.toUTC('2026-03-29T00:00')), 23 * 3600000);
  assert.equal(Date.parse(time.toUTC('2026-10-26T00:00')) - Date.parse(time.toUTC('2026-10-25T00:00')), 25 * 3600000);
  assert.equal(time.toUTC('2026-03-29T02:30'), null);
  assert.equal(time.toUTC('2026-10-25T02:30'), '2026-10-25T00:30:00.000Z');
});

function harness() {
  const requests = [], cardRenders = [], sourceCalls = []; let viewActions, timelineActions; const timers = new Map(); let timerId = 0;
  function node(tag = 'div') {
    const classes = new Set();
    return {tagName: tag.toUpperCase(), children: [], dataset: {}, value: '', hidden: false, isConnected: true,
      style: {setProperty() {}}, classList: {add: value => classes.add(value), toggle(value, enabled) {enabled ? classes.add(value) : classes.delete(value);}, remove: value => classes.delete(value)},
      append(...children) {this.children.push(...children);}, replaceChildren(...children) {this.children = children;},
      setAttribute(key, value) {this[key] = value;}, removeAttribute(key) {delete this[key];},
      addEventListener(event, handler) {this[event] = handler;}, focus() {document.activeElement = this;}, get firstChild() {return this.children[0];}};
  }
  const shell = node(), host = node(); host.closest = () => shell;
  const document = {hidden: false, activeElement: null, events: {}, createElement: node, getElementById: id => id === 'analysis-workspace' ? host : null, addEventListener(name, handler) {this.events[name] = handler;}};
  const U = {el(tag, text, cls) {const item = node(tag); item.textContent = text; item.className = cls; return item;},
    button(text, click, cls) {const item = this.el('button', text, cls); item.click = click; return item;},
    field(label, control) {const item = this.el('label', label); item.append(control); return item;}, date: value => value || 'brak', typeNames: {}, statusNames: {}};
  const sources = {setVisible(value) {sourceCalls.push(['visible', value]);}, setTypes(types) {sourceCalls.push(['types', [...types]]);}, subscribe() {}, demandIndexes() {}, deactivate() {}, loadSensors() {return Promise.resolve({items: []});}};
  const window = {WiciWorkspaceUI: U, WiciWorkspaceStore: Store, WiciWorkspaceSources: sources,
    WiciWorkspaceViews: (host, actions) => {viewActions = actions; return {load() {}};}, WiciWorkspaceTable: () => ({render() {}, focusHeading() {}}),
    WiciWorkspaceTimeline: {create: (host, actions) => {timelineActions = actions; return {render() {}};}}, WiciWorkspaceMap: () => ({render() {}, setActive() {}, show() {}}),
    WiciObjectCard: () => ({render(detail, timeline, state, sample) {cardRenders.push({detail, timeline, state, sample});}, focus() {}})};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-controller.js', 'utf8'), {
    window, document, URLSearchParams, Date, Intl, structuredClone, AbortController,
    localStorage: {getItem() {throw Error('disabled');}, setItem() {throw Error('disabled');}},
    setTimeout(fn) {timers.set(++timerId, fn); return timerId;}, clearTimeout(id) {timers.delete(id);}, setInterval() {return ++timerId;}, clearInterval() {},
  });
  window.WiciWorkspace.init({map: {invalidateSize() {}}, health: {now: '2026-10-22T12:00:00Z'}, geometries: new Map(), api: (path, body, options) => new Promise((resolve, reject) => requests.push({path, body, options, resolve, reject}))});
  const queryResponse = {items: [], total: 0, next_cursor: null, map: {items: []}, timeline_summary: {buckets: []}, coverage: {sources: []}, data_revision: 'data1', as_of: '2026-10-22T12:00:00Z'};
  return {ui: window.WiciWorkspace, document, requests, cardRenders, queryResponse, sourceCalls, viewActions, timelineActions};
}
const flush = () => new Promise(resolve => setImmediate(resolve));
async function ready(h) {h.ui.setActive(true); h.requests.find(request => request.path === '/workspace/query').resolve(h.queryResponse); h.requests.find(request => request.path === '/workspace/status').resolve({}); await flush();}
function resolveDetail(requests, ref, label) {
  for (const request of requests) if (request.path.includes('/timeline?')) request.resolve({ref, items: []}); else request.resolve({object: {ref, type: 'communication', label}});
}

test('controller keeps one activation and ignores A→B→A late detail results and close responses', async () => {
  const h = harness(); await ready(h); const count = h.requests.length; h.ui.setActive(true); assert.equal(h.requests.length, count);
  h.ui.selectObject('communication:1'); const first = h.requests.slice(-2);
  h.ui.selectObject('communication:2'); const second = h.requests.slice(-2);
  h.ui.selectObject('communication:1'); const third = h.requests.slice(-2);
  assert.equal(first[0].options.signal.aborted, true); assert.equal(second[0].options.signal.aborted, true);
  resolveDetail(third, 'communication:1', 'new A'); await flush();
  resolveDetail(first, 'communication:1', 'old A'); resolveDetail(second, 'communication:2', 'late B'); await flush();
  assert.equal(h.cardRenders.at(-1).detail.object.label, 'new A');
  h.ui.selectObject('communication:2'); const closing = h.requests.slice(-2);
  h.document.events.keydown({key: 'Escape', preventDefault() {}}); resolveDetail(closing, 'communication:2', 'closed B'); await flush();
  assert.equal(h.ui.getState().detailOpen, false); assert.equal(h.cardRenders.at(-1).detail.object.label, 'new A');
});

test('controller rejects stale query batches after region change and bounds 409 retries', async () => {
  const h = harness(); h.ui.setActive(true); const old = h.requests.find(request => request.path === '/workspace/query');
  h.ui.setRegion('14'); const current = h.requests.filter(request => request.path === '/workspace/query').at(-1);
  current.resolve({...h.queryResponse, total: 9}); await flush(); old.resolve({...h.queryResponse, total: 99}); await flush(); assert.equal(h.ui.getData().total, 9);
  h.ui.refresh();
  for (let retry = 0; retry < 3; retry++) {const request = h.requests.filter(request => request.path === '/workspace/query').at(-1); request.reject(Object.assign(Error('changed'), {status: 409})); await flush();}
  assert.match(h.ui.getState().error, /Odśwież zestaw/); assert.equal(h.ui.getData().total, 9);
});


test('restoring a saved view clears old source demands before visibility is resumed', async () => {
  const h = harness(); await ready(h); h.sourceCalls.length = 0;
  h.viewActions.apply({query: {...Store.initialState().query, types: ['hydro_station']}, layout: {tablePercent: 50}}, 'saved');
  assert.deepEqual(h.sourceCalls.slice(0, 2), [['types', []], ['visible', true]]);
  assert.equal(h.ui.getState().savedViewId, 'saved');
  h.ui.setActive(true); assert.equal(h.sourceCalls.length, 2);
});


test('view range accepts earlier stored start/end names and exposes canonical from/to', () => {
  const state = Store.reducer(Store.initialState(), {type: 'APPLY_VIEW', config: {query: {time: {mode: 'range', overview_range: {start: '2026-10-20T00:00:00Z', end: '2026-10-21T00:00:00Z'}, filter_range: {start: '2026-10-20T02:00:00Z', end: '2026-10-20T03:00:00Z'}}}}});
  assert.deepEqual(state.query.time.filter_range, {from: '2026-10-20T02:00:00Z', to: '2026-10-20T03:00:00Z'});
  assert.equal(state.query.time.overview_range.from, '2026-10-20T00:00:00Z');
});


test('cursor selects a local correction without queries or source demand changes', async () => {
  const h = harness(); await ready(h); const ref = 'hydro_station:imgw:1';
  h.ui.selectObject(ref);
  const row = {ref, type: 'hydro_station', label: 'Wodowskaz', measurement: {value: 99, metric: 'water_level', observed_at: '2026-10-22T11:00:00Z'}};
  for (const request of h.requests.slice(-2)) request.resolve(request.path.includes('/timeline?') ? {ref, items: []} : {object: row});
  await flush();
  h.timelineActions.dispatch({type: 'SET_TIME_RANGE', range: {from: '2026-10-22T00:00:00Z', to: '2026-10-22T12:00:00Z'}});
  h.requests.at(-1).resolve({...h.queryResponse, items: [row], total: 1}); await flush();
  const samples = [{ref, metric: 'water_level', observed_at: '2026-10-22T03:00:00Z', revision: 1, value: 20}, {ref, metric: 'water_level', observed_at: '2026-10-22T03:00:00Z', revision: 2, value: null}, {ref, metric: 'water_level', observed_at: '2026-10-22T10:00:00Z', revision: 1, value: 80}];
  for (const request of h.requests.slice(-2)) request.resolve(request.path.includes('/timeline?') ? {ref, items: samples} : {object: row});
  await flush(); const reads = h.requests.length, demands = h.sourceCalls.length;
  h.timelineActions.dispatch({type: 'SET_CURSOR', at: '2026-10-22T04:00:00Z'});
  assert.equal(h.cardRenders.at(-1).sample.value, null);
  h.timelineActions.dispatch({type: 'SET_CURSOR', at: '2026-10-22T10:30:00Z'});
  assert.equal(h.cardRenders.at(-1).sample.value, 80);
  assert.equal(h.requests.length, reads); assert.equal(h.sourceCalls.length, demands);
});

function mapHarness() {
  const markers = [], U = {el: (tag, text) => ({textContent: text}), value: sample => String(sample?.value), measurement: item => item.measurement};
  const L = {layerGroup: () => ({addTo() {return this;}}), circleMarker(coords, style) {
    const marker = {style, bindTooltip() {return this;}, on() {}, addTo() {return this;}, setStyle(style) {this.style = style;}, setRadius() {}, setTooltipContent() {}};
    markers.push(marker); return marker;
  }};
  const window = {WiciWorkspaceUI: U, L};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-map.js', 'utf8'), {window, L, Date});
  const map = window.WiciWorkspaceMap({map: {removeLayer() {}}, geometries: new Map(), select() {}, narrow() {}}); map.setActive(true);
  const clock = '2026-10-22T12:00:00Z';
  function render(item, options = {}) {
    const state = {detailOpen: false, query: {time: {mode: 'live'}}, ...options.state};
    map.render({as_of: clock, map: {points: [{ref: 'station:1', latitude: 52, longitude: 21, ...item}], areas: []}}, state, options.sample, options.index);
    return markers.at(-1).style.color;
  }
  return {render};
}

test('GIOS map color follows the official index clock independently of concentration freshness', () => {
  const h = mapHarness(), current = '2026-10-22T11:30:00Z', old = '2026-10-21T00:00:00Z';
  const base = {type: 'air_quality_station', official_index: {value: 1, quality: 'valid', observed_at: current}};
  assert.equal(h.render({...base, freshness: 'stale', measurement: {value: 999, observed_at: old}}), '#80a24c');
  assert.equal(h.render({...base, freshness: 'fresh', measurement: {value: 1, observed_at: current}, official_index: {...base.official_index, observed_at: old}}), '#7e8990');
  for (const index of [null, {value: null, observed_at: current}, {value: 1, observed_at: null}, {value: 1, quality: 'unknown_time', observed_at: current}, {value: 1, observed_at: '2026-10-22T13:00:00Z'}]) assert.equal(h.render({...base, official_index: index}), '#7e8990');
});

test('historical map colors use period end or selected cursor without borrowing a different sensor or index', () => {
  const h = mapHarness(), oldIndex = {value: 3, quality: 'valid', observed_at: '2026-10-20T10:00:00Z'}, range = {mode: 'range', filter_range: {from: '2026-10-20T00:00:00Z', to: '2026-10-20T12:00:00Z'}};
  const station = {type: 'air_quality_station', freshness: 'stale', official_index: oldIndex};
  assert.equal(h.render(station, {state: {query: {time: range}}}), '#c98b3d');
  const selection = {detailOpen: true, selectedRef: 'station:1', cursorAt: '2026-10-20T10:30:00Z', query: {time: range}};
  assert.equal(h.render(station, {state: selection, index: {...oldIndex, value: 0}, sample: {value: 9999}}), '#459a77');
  assert.equal(h.render(station, {state: selection, index: null, sample: {value: 1}}), '#7e8990');
  const water = {type: 'hydro_station', freshness: 'stale', measurement: {value: 340, metric: 'water_level', observed_at: oldIndex.observed_at, thresholds: {warning_level_cm: 300, alarm_level_cm: 400}}};
  assert.equal(h.render(water, {state: {query: {time: range}}}), '#b78a28');
  assert.equal(h.render(water), '#7e8990');
  assert.equal(h.render({...water, measurement: {...water.measurement, thresholds: {}}}, {state: {query: {time: range}}}), '#7e8990');
});
