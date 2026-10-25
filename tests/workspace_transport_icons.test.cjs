'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const Motion = require('../src/wici/static/js/workspace-motion.js');
const at = '2020-01-01T12:00:00Z', range = {from: at, to: '2020-01-01T12:20:00Z'};
function setup() {
  const added = [], selected = [];
  const node = (tag, text) => ({tagName: tag, textContent: text, children: [], style: {}, append(...items) {this.children.push(...items);}});
  const layer = (kind, coords, options) => ({kind, coords, options, handlers: {}, addTo(group) {this.group = group; added.push(this); return this;},
    bindTooltip(content) {this.tooltip = content; return this;}, setTooltipContent(content) {this.tooltip = content; return this;},
    on(event, action) {this.handlers[event] = action; return this;}, setIcon(icon) {this.options.icon = icon; return this;},
    setStyle() {}, setRadius() {}, bindPopup() {return this;}});
  const L = {divIcon: options => options, layerGroup: () => layer('group'), marker: (coords, options) => layer('icon', coords, options),
    circleMarker: (coords, options) => layer('circle', coords, options), polyline: (coords, options) => layer('path', coords, options)};
  const window = {L, WiciWorkspaceMotion: Motion, WiciWorkspaceUI: {el: node, date: value => value, measurement: item => item.measurement, value: () => 'Pomiar', statusNames: {fresh: 'Aktualne'}}};
  const context = {window, L, document: {createElement: node, addEventListener() {}}, Date};
  for (const file of ['aircraft', 'ships', 'workspace-map']) vm.runInNewContext(fs.readFileSync(`src/wici/static/js/${file}.js`, 'utf8'), context);
  const map = window.WiciWorkspaceMap({map: {removeLayer() {}}, geometries: new Map(), select: ref => selected.push(ref)});
  map.setActive(true);
  return {map, added, selected, window};
}
function item(type, metadata = {}, heading = 90) {
  const ref = type === 'aircraft' ? 'aircraft:icao:abc123' : 'ship:mmsi:261000001';
  return {ref, type, label: type === 'aircraft' ? 'LOT123' : 'BALTIC', metadata, freshness: 'fresh', latitude: 52, longitude: 21,
    position: {position_at: at, latitude: 52, longitude: 21, heading, speed_kmh: 100}};
}
const state = (patch = {}) => ({detailOpen: false, comparedRefs: [], query: {time: {mode: 'live'}}, ...patch});

test('Analysis live markers share main-map aircraft and AIS symbols, colors, bearing and labels', () => {
  for (const [type, metadata, expected] of [
    ['aircraft', {military: true}, 'aircraft-military'], ['aircraft', {military: false}, 'aircraft-symbol'],
    ['ship', {type_code: 35}, 'ship-military'], ['ship', {type_code: 70}, 'ship-civilian'], ['ship', {}, 'ship-unclassified'],
  ]) {
    const h = setup(), value = item(type, metadata), data = {as_of: at, map: {points: [value]}};
    h.map.render(data, state());
    const marker = h.added.find(entry => entry.kind === 'icon'); assert.ok(marker); assert.equal(h.added.some(entry => entry.kind === 'circle'), false);
    const main = type === 'aircraft' ? h.window.WiciAircraft.icon({...metadata, track: 90})
      : h.window.WiciShips.icon({...metadata, heading: 90, position_at: at}, {referenceAt: Date.parse(at)});
    assert.equal(marker.options.icon.html.className, main.html.className);
    assert.equal(marker.options.icon.html.style.transform, main.html.style.transform);
    assert.ok(marker.options.icon.html.className.includes(expected)); assert.equal(marker.options.title, value.label);
    assert.ok(marker.tooltip.textContent.includes(value.label));
    if (type === 'ship') assert.ok(marker.tooltip.textContent.includes(h.window.WiciShips.classification(metadata).label));
    marker.handlers.click(); assert.deepEqual(h.selected, [value.ref]);
    h.map.render(data, state({detailOpen: true, selectedRef: value.ref}));
    assert.ok(marker.options.icon.className.includes('analysis-transport-selected'));
    assert.equal(marker.options.icon.html.className, main.html.className, 'selection preserves the classification color');
  }
});

test('historical ship styling uses cursor time and recorded bearing rather than wall time or live coordinates', () => {
  const h = setup(), live = item('ship', {type_code: 35}, 200);
  const recorded = {...live.position, heading: 50, latitude: 55, longitude: 18};
  const series = {...live, points: [recorded], gap_seconds: 900}, replay = {range, series: [series]};
  function render(cursor) {
    const frame = Motion.frameAt(series, cursor, range);
    h.map.render({map: {points: [live]}}, state({cursorAt: cursor, comparedRefs: [live.ref], query: {time: {mode: 'range', filter_range: range}}}), null, null,
      {data: replay, frames: new Map([[live.ref, {...frame, label: live.label}]])});
    return h.added.filter(entry => entry.kind === 'icon').at(-1);
  }
  const fresh = render(at);
  assert.deepEqual(Array.from(fresh.coords), [55, 18]); assert.equal(fresh.options.icon.html.style.transform, 'rotate(50deg)');
  assert.equal(fresh.options.icon.html.className, 'ship-symbol ship-military', 'old archive timestamps are fresh at their own cursor');
  const old = render('2020-01-01T12:05:01Z');
  assert.equal(old.options.icon.html.className, 'ship-symbol ship-military ship-old');
  assert.ok(old.tooltip.textContent.includes('klasyfikacja z bieżącego katalogu'));
  assert.ok(old.options.icon.className.includes('analysis-replay-marker'));
});

test('historical aircraft uses shared military color and recorded heading; ships retain unknown direction', () => {
  for (const type of ['aircraft', 'ship']) {
    const h = setup(), value = item(type, type === 'aircraft' ? {military: true} : {}, type === 'aircraft' ? 180 : null);
    const series = {...value, points: [value.position]}, replay = {range, series: [series]};
    h.map.render({map: {points: []}}, state({cursorAt: at, query: {time: {mode: 'range', filter_range: range}}}), null, null,
      {data: replay, frames: new Map([[value.ref, {...Motion.frameAt(series, at, range), label: value.label, color: '#ff00ff'}]])});
    const marker = h.added.find(entry => entry.kind === 'icon');
    if (type === 'aircraft') {assert.equal(marker.options.icon.html.className, 'aircraft-symbol aircraft-military'); assert.equal(marker.options.icon.html.style.transform, 'rotate(90deg)');}
    else assert.equal(marker.options.icon.html.className, 'ship-symbol ship-unclassified ship-direction-unknown');
  }
});

test('non-transport station markers retain their existing measurement rendering', () => {
  const h = setup(), value = {ref: 'hydro_station:imgw:1', type: 'hydro_station', label: 'Wisła', latitude: 52, longitude: 21};
  h.map.render({as_of: at, map: {points: [value]}}, state());
  assert.equal(h.added.filter(entry => entry.kind === 'circle').length, 1);
  assert.equal(h.added.some(entry => entry.kind === 'icon'), false);
});

test('graph stations at a shared cursor override every catalogue marker while preserving the selected sensor context', () => {
  const h = setup(), observed = '2020-01-01T10:00:00Z', cursorAt = '2020-01-01T10:15:00Z';
  h.window.WiciWorkspaceUI.value = sample => sample?.value == null ? 'Brak pomiaru' : `${sample.value} µg/m³`;
  const nodes = ['1','2'].map(id => ({ref:`air_quality_station:gios:${id}`,type:'air_quality_station',label:`GIOŚ ${id}`,latitude:52+Number(id)/100,longitude:21,
    measurement:{value:10,observed_at:observed}, official_index:{value:0,observed_at:observed}}));
  const catalog = nodes.map(node => ({...node,measurement:{value:90,observed_at:'2020-01-01T11:00:00Z'},official_index:{value:5,observed_at:'2020-01-01T11:00:00Z'}}));
  h.map.render({map:{points:catalog}}, state({detailOpen:true,selectedRef:nodes[0].ref,cursorAt,query:{time:{mode:'range',filter_range:{from:observed,to:at}}}}),
    {value:12,observed_at:observed}, {value:1,observed_at:observed}, null, null, {nodes});
  const markers=h.added.filter(layer=>layer.kind==='circle');
  assert.equal(markers.length,2,'catalogue period markers are replaced by graph cursor markers');
  const first=markers.find(layer=>layer.tooltip.textContent.includes('GIOŚ 1')),second=markers.find(layer=>layer.tooltip.textContent.includes('GIOŚ 2'));
  assert.match(first.tooltip.textContent,/12 µg\/m³/);assert.equal(first.options.color,'#80a24c','selected card index remains independent');
  assert.match(second.tooltip.textContent,/10 µg\/m³/);assert.doesNotMatch(second.tooltip.textContent,/90 µg/);assert.equal(second.options.color,'#459a77');
});
