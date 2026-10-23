'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const Motion = require('../src/wici/static/js/workspace-motion.js');
const Store = require('../src/wici/static/js/workspace-store.js');
const range = {from: '2026-10-23T10:00:00Z', to: '2026-10-23T11:00:00Z'};
const point = (time, patch = {}) => ({position_at: `2026-10-23T${time}Z`, latitude: 52, longitude: 21, speed_kmh: 400, altitude_m: 3000, track_id: 'one', ...patch});

test('moving cursor uses only recorded points in the half-open range and never looks forward', () => {
  const series = {type: 'aircraft', gap_seconds: 120, points: [point('10:02:00'), point('09:59:59'), point('10:00:00'), point('11:00:00')]};
  assert.equal(Motion.frameAt(series, range.from, range).point.position_at, range.from);
  assert.equal(Motion.frameAt(series, '2026-10-23T10:01:30Z', range).point.position_at, range.from);
  assert.equal(Motion.frameAt(series, '2026-10-23T09:59:59Z', range).status, 'empty');
  assert.equal(Motion.frameAt(series, null, range).point, null);
  assert.equal(Motion.frameAt(series, null, range).lastPoint.position_at, '2026-10-23T10:02:00Z');
  assert.equal(Motion.frameAt({type: 'aircraft', points: []}, range.from, range).status, 'empty');
});

test('the last recorded position expires at its source-specific gap threshold', () => {
  const plane = {type: 'aircraft', gap_seconds: 120, points: [point('10:00:00')]};
  assert.equal(Motion.frameAt(plane, '2026-10-23T10:02:00Z', range).status, 'ready');
  const gap = Motion.frameAt(plane, '2026-10-23T10:02:01Z', range);
  assert.equal(gap.status, 'gap'); assert.equal(gap.point, null); assert.equal(gap.lastPoint, plane.points[0]);
  assert.equal(Motion.frameAt({...plane, type: 'ship', gap_seconds: 900}, '2026-10-23T10:14:59Z', range).status, 'ready');
  assert.equal(Motion.frameAt({...plane, type: 'ship', gap_seconds: 900}, '2026-10-23T10:15:01Z', range).status, 'gap');
});

test('paths never join sessions, invalid jumps, explicit discontinuities, date-line crossings or time gaps', () => {
  const points = [point('10:00:00'), point('10:00:30'), point('10:01:00', {break_before: true}), point('10:01:30', {track_id: 'two'}), point('10:05:00', {track_id: 'two'}), point('10:05:30', {track_id: 'two', longitude: -179})];
  assert.deepEqual(Motion.segments({type: 'aircraft', points}, range).map(segment => segment.length), [2, 1, 1, 1, 1]);
  assert.deepEqual(Motion.segments({type: 'aircraft', points}, range, '2026-10-23T10:00:30Z'), [points.slice(0, 2)]);
});

test('invalid positions cannot enter replay and normalized arrays are reused during scrubbing', () => {
  const series = {points: [point('10:00:00'), point('10:00:01', {latitude: null}), point('10:00:02', {longitude: 999}), point('bad')], type: 'aircraft'};
  const first = Motion.pointsInRange(series, range); assert.equal(first.length, 1);
  assert.equal(Motion.pointsInRange(series, {...range}), first);
  series.points = [point('10:00:30')];
  assert.notEqual(Motion.pointsInRange(series, range), first);
  assert.equal(Motion.frameAt(series, '2026-10-23T10:00:30Z', range).point.position_at, '2026-10-23T10:00:30Z');
});

test('five stable moving identities can be compared independently of the open card and persist in saved views', () => {
  let state = Store.initialState(); const refs = ['aircraft:icao:48abc0', 'aircraft:icao:48abc1', 'aircraft:icao:48abc2', 'ship:mmsi:261000001', 'ship:mmsi:261000002'];
  for (const ref of [...refs, 'ship:mmsi:261000003', 'hydro_station:imgw:1', 'aircraft:icao:~48abc0']) state = Store.reducer(state, {type: 'TOGGLE_COMPARE', ref});
  assert.deepEqual(state.comparedRefs, refs); assert.equal(state.queryRevision, 0);
  state = Store.reducer(state, {type: 'SELECT_OBJECT', ref: 'communication:1'}); assert.deepEqual(state.comparedRefs, refs);
  state = Store.reducer(state, {type: 'CLOSE_CARD'}); assert.deepEqual(state.comparedRefs, refs);
  const restored = Store.reducer(Store.initialState(), {type: 'APPLY_VIEW', config: {comparedRefs: [...refs, refs[0], 'ship:mmsi:261000003'], query: {watched_only: true}}});
  assert.deepEqual(restored.comparedRefs, refs); assert.equal(restored.query.watched_only, true);
  const removed = Store.reducer(restored, {type: 'TOGGLE_COMPARE', ref: refs[0]}); assert.deepEqual(removed.comparedRefs, refs.slice(1));
});

test('historical map suppresses live moving coordinates and removes markers when cursor enters a gap', () => {
  const added = [], removed = [], U = {el: (tag, text) => ({textContent: text}), measurement: item => item.measurement, value: () => 'x', date: value => value, statusNames: {}};
  const layer = (kind, coords, style) => ({kind, coords, style, addTo(group) {this.group = group; added.push(this); return this;}, bindTooltip() {return this;}, on() {return this;}, setStyle() {}, setRadius() {}, setTooltipContent() {}});
  const L = {layerGroup: () => layer('group'), marker: (coords, style) => layer('marker', coords, style), circleMarker: (coords, style) => layer('marker', coords, style), polyline: (coords, style) => layer('path', coords, style)};
  const window = {WiciWorkspaceUI: U, WiciWorkspaceMotion: Motion, WiciAircraft: {icon: () => ({})}, L};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-map.js', 'utf8'), {window, L, Date});
  const map = window.WiciWorkspaceMap({map: {removeLayer(value) {removed.push(value);}}, geometries: new Map(), select() {}, narrow() {}}); map.setActive(true);
  const ref = 'aircraft:icao:48abc0', live = {ref, type: 'aircraft', latitude: 50, longitude: 20, position: {latitude: 50, longitude: 20}}, data = {map: {points: [live]}};
  const replay = {range, series: [{ref, type: 'aircraft', points: [point('10:00:00'), point('10:01:00')]}]}, state = {detailOpen: false, comparedRefs: [ref], query: {time: {mode: 'range', filter_range: range}}, cursorAt: range.from};
  const frame = Motion.frameAt(replay.series[0], state.cursorAt, range);
  map.render(data, state, null, null, {data: replay, frames: new Map([[ref, {...frame, color: '#16819c'}]])});
  const markers = added.filter(item => item.kind === 'marker'); assert.equal(markers.length, 1); assert.deepEqual(Array.from(markers[0].coords), [52, 21]);
  const group = markers[0].group;
  map.render(data, {...state, cursorAt: '2026-10-23T10:30:00Z'}, null, null, {data: replay, frames: new Map([[ref, Motion.frameAt(replay.series[0], '2026-10-23T10:30:00Z', range)]])});
  assert.equal(added.filter(item => item.kind === 'marker').length, 1); assert.ok(removed.includes(group));
});

test('live moving card renders positions without comparison, distinguishes pending refresh and labels active recording', () => {
  function node(tag, text) {return {tagName: tag, textContent: text, children: [], dataset: {}, append(...items) {this.children.push(...items);}, replaceChildren(...items) {this.children = items;}, setAttribute(name, value) {this[name] = value;}, focus() {}};}
  const U = {el: node, button: (text, action) => Object.assign(node('button', text), {click: action}), typeNames: {aircraft: 'Samolot'}, statusNames: {fresh: 'Aktualne', ready: 'Dostępne'}, date: value => value || 'Brak czasu', safeLink: () => null};
  const window = {WiciWorkspaceUI: U, WiciWorkspaceMotion: Motion};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/object-card.js', 'utf8'), {window, Date, Number});
  const host = node('aside'), card = window.WiciObjectCard(host, {}), ref = 'aircraft:icao:502d47';
  const state = {...Store.initialState(), selectedRef: ref, detailOpen: true, detailRevision: 1, queryRevision: 2};
  const detail = {object: {ref, type: 'aircraft', label: 'BTI695', source_id: 'aircraft', latitude: 54, longitude: 22, freshness: 'fresh', source_status: 'ready', position: point('10:00:00', {speed_kmh: 785.2})}, track_sessions: [{id: 1, active: true, point_count: 1}], _detailRevision: 1, _queryRevision: 2};
  const flatten = value => [value, ...value.children.flatMap(flatten)], texts = () => flatten(host).map(value => value.textContent || '').join('|');
  card.render(detail, null, state, null);
  assert.match(texts(), /785\.2 km\/h/); assert.match(texts(), /52\.00000/); assert.deepEqual(state.comparedRefs, []);
  const start = flatten(host).find(value => value.id === 'analysis-start-recording'); assert.equal(start.textContent, 'Zapis trwa'); assert.equal(start.disabled, true);
  card.render(detail, null, {...state, queryRevision: 3}, null, {loading: true});
  assert.match(texts(), /Odświeżanie pozycji dla aktualnego zestawu/); assert.doesNotMatch(texts(), /Brak pozycji|Brak danych/);
  card.render({...detail, _queryRevision: 3, track_sessions: [{id: 1, active: false, point_count: 1}]}, null, {...state, queryRevision: 3}, null);
  assert.match(texts(), /785\.2 km\/h/); const restart = flatten(host).find(value => value.id === 'analysis-start-recording'); assert.equal(restart.textContent, 'Rozpocznij zapis trasy'); assert.equal(restart.disabled, false);
  card.render(detail, null, {...state, query: {...state.query, time: {mode: 'range', filter_range: range}}}, null, {motion: {frames: new Map()}});
  assert.match(texts(), /Brak pozycji/); assert.doesNotMatch(texts(), /785\.2 km\/h/);
});
