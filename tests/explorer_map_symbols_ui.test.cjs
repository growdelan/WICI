'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const at = '2026-11-05T10:00:00Z';
function setup(markerStyle = 'symbol') {
  const added = [], selected = [], panes = new Map(), changes = {icons: 0, positions: 0, tooltip: 0, attributes: 0, fronts: 0};
  function node(tag, text, className) {return {tagName: tag, textContent: text, className, children: [], dataset: {}, attributes: {}, events: {},
    style: {setProperty(key, value) {this[key] = value;}}, append(...children) {this.children.push(...children);},
    setAttribute(key, value) {changes.attributes++; this.attributes[key] = String(value);}, addEventListener(name, handler) {this.events[name] = handler;}};}
  function layer(kind, coords, options = {}) {const element = node('div'); return {kind, coords, options, element, handlers: {},
    addTo(owner) {this.owner = owner; added.push(this); return this;}, bindTooltip(content) {this.tooltip = content; return this;},
    setTooltipContent(content) {changes.tooltip++; this.tooltip = content;}, bindPopup() {return this;}, on(name, handler) {this.handlers[name] = handler; return this;},
    setIcon(icon) {changes.icons++; this.options.icon = icon;}, getElement() {return element;}, setLatLng(next) {changes.positions++; this.coords = next;},
    setStyle(style) {this.options = {...this.options, ...style};}, setRadius() {}, setPopupContent() {},
    removeLayer(item) {item.removed = true;}, bringToFront() {changes.fronts++;}};}
  const L = {layerGroup: () => layer('group'), marker: (coords, options) => layer('marker', coords, options), circleMarker: (coords, options) => layer('circle', coords, options),
    divIcon: options => options, geoJSON: (feature, options) => Object.assign(layer('area', null, options), {feature})};
  const U = {el: node, icon: (type, className) => node('svg', null, className), button: (text, action) => ({textContent: text, action}),
    typeNames: {hydro_station: 'Wodowskaz', air_quality_station: 'Stacja GIOŚ'}, date: value => value, value: sample => sample?.value == null ? 'Brak pomiaru' : `${sample.value} cm`, measurement: item => item.measurement};
  const window = {L, WiciWorkspaceUI: U, WiciWorkspaceMotion: {isMoving: item => item.type === 'aircraft', number: value => String(value)},
    WiciAircraft: {icon: (value, options) => ({transport: true, value, options})}};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-map.js', 'utf8'), {window, L, Date});
  const map = window.WiciWorkspaceMap({markerStyle, select: ref => selected.push(ref), map: {removeLayer() {}, getPane: name => panes.get(name), createPane(name) {const pane = node('div'); panes.set(name, pane); return pane;}}});
  map.setActive(true);
  return {map, added, selected, changes, panes, data: items => ({as_of: at, map: {points: items}})};
}
const sample = (value, extra = {}) => ({value, metric: 'water_level', unit: 'cm', observed_at: '2026-11-05T09:50:00Z', thresholds: {warning_level_cm: 400, alarm_level_cm: 500}, ...extra});
const station = {ref: 'hydro_station:imgw:1', label: 'Trestno', type: 'hydro_station', latitude: 51.1, longitude: 17, measurement: sample(412)};
const state = (patch = {}) => ({detailOpen: false, query: {time: {mode: 'live'}}, comparedRefs: [], ...patch});
const symbol = marker => marker.options.icon.html;
const shownColor = marker => symbol(marker).style['--marker-color'];

test('symbol option keeps source colors, reuses markers and changes icons only for type, color or selection', () => {
  const h = setup(), data = h.data([station]);
  h.map.render(data, state()); const marker = h.added.find(item => item.kind === 'marker');
  assert.equal(shownColor(marker), '#b78a28'); assert.equal(symbol(marker).dataset.type, 'hydro_station');
  assert.equal(marker.options.keyboard, true); assert.equal(marker.options.bubblingMouseEvents, false);
  const before = {...h.changes};
  h.map.render(data, state()); assert.deepEqual(h.changes, before);
  const chosen = state({selectedRef: station.ref, detailOpen: true});
  h.map.render(data, chosen, sample(414));
  assert.equal(h.changes.icons, before.icons + 1); assert.match(symbol(marker).className, /is-selected/);
  const selectedIcons = h.changes.icons;
  h.map.render(data, chosen, sample(416)); assert.equal(h.changes.icons, selectedIcons, 'value-only update must keep the icon');
  h.map.render(data, chosen, sample(512)); assert.equal(shownColor(marker), '#bc4145');
  h.map.render(data, state({detailOpen: true, selectedRef: station.ref, cursorAt: '2026-11-05T13:10:00Z'}), sample(512));
  assert.equal(shownColor(marker), '#7e8990', 'an expired observation remains unknown');
  assert.equal(h.added.filter(item => item.kind === 'marker').length, 1);
});

test('symbol accessibility uses safe DOM text, keyboard selection and current titles after refresh', () => {
  const h = setup(), label = '<img src=x onerror=alert(1)>', malicious = {...station, label};
  h.map.render(h.data([malicious]), state()); const marker = h.added.find(item => item.kind === 'marker');
  assert.equal(typeof marker.options.icon.html, 'object', 'the icon receives a DOM node, not interpolated source HTML');
  assert.equal(marker.element.title, label); assert.equal(marker.element.attributes.role, 'button');
  assert.equal(marker.element.attributes.tabindex, '0'); assert.match(marker.element.attributes['aria-label'], /<img src=x/);
  let prevented = false; marker.element.events.keydown({key: ' ', preventDefault() {prevented = true;}});
  assert.equal(prevented, true); assert.deepEqual(h.selected, [station.ref]);
  marker.handlers.click(); assert.deepEqual(h.selected, [station.ref, station.ref]);
  const before = h.changes.icons;
  h.map.render(h.data([{...station, label: 'Nowa nazwa'}]), state({detailOpen: true, selectedRef: station.ref}));
  assert.equal(marker.element.title, 'Nowa nazwa'); assert.equal(marker.element.attributes['aria-pressed'], 'true');
  assert.equal(h.changes.icons, before + 1, 'selection is the only icon change');
  h.map.render(h.data([{...station, label: 'Jeszcze inna nazwa'}]), state({detailOpen: true, selectedRef: station.ref}));
  assert.equal(h.changes.icons, before + 1, 'a source label change does not rebuild the icon');
});

test('GIOS symbols use the official index at the cursor, independently of concentration', () => {
  const h = setup(), gios = {...station, type: 'air_quality_station', ref: 'air_quality_station:gios:1', official_index: {value: 5, observed_at: station.measurement.observed_at}};
  const data = h.data([gios]); h.map.render(data, state()); const marker = h.added.find(item => item.kind === 'marker');
  assert.equal(shownColor(marker), '#9c4050');
  const selected = state({detailOpen: true, selectedRef: gios.ref, cursorAt: at});
  h.map.render(data, selected, sample(999), {value: 0, observed_at: station.measurement.observed_at});
  assert.equal(shownColor(marker), '#459a77');
  h.map.render(data, selected, sample(0), null); assert.equal(shownColor(marker), '#7e8990');
});

test('graph points and areas keep a pane above base symbols without reordering unchanged frames; transport stays unchanged', () => {
  const h = setup(), aircraft = {...station, ref: 'aircraft:icao:abc123', type: 'aircraft', position: {position_at: at, heading: 80, latitude: 51, longitude: 17}};
  const graphStation = {...station, ref: 'hydro_station:imgw:graph'};
  const graphArea = {type: 'custom_area', ref: 'custom_area:graph', label: 'Obszar', geometry: {type: 'Polygon', coordinates: [[[17,51], [18,51], [18,52], [17,51]]]}};
  const data = h.data([station, aircraft]), graph = {nodes: [graphStation, graphArea]};
  h.map.render(data, state(), null, null, null, null, graph);
  const graphPoint = h.added.find(item => item.kind === 'circle'), area = h.added.find(item => item.kind === 'area');
  assert.equal(graphPoint.options.pane, 'wici-analysis-graph'); assert.equal(area.options.pane, 'wici-analysis-graph');
  assert.ok(Number(h.panes.get('wici-analysis-graph').style.zIndex) > 600);
  assert.ok(h.added.some(item => item.kind === 'marker' && item.options.icon.transport));
  const before = {...h.changes}; h.map.render(data, state(), null, null, null, null, graph); assert.deepEqual(h.changes, before);
  const legacy = setup('circle'); legacy.map.render(legacy.data([station]), state());
  assert.equal(legacy.added.filter(item => item.kind === 'marker').length, 0); assert.equal(legacy.panes.size, 0);
});
