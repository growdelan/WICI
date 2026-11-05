'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
function setup() {
  function element(tag) {
    const classes = new Set();
    return {tagName: tag, children: [], dataset: {}, attributes: {}, hidden: false, textContent: '', replacements: 0, style: {setProperty() {}},
      classList: {add(name) {classes.add(name);}, toggle(name, value) {value ? classes.add(name) : classes.delete(name);}},
      append(...children) {for (const child of children) {if (child.parent) child.parent.children = child.parent.children.filter(node => node !== child); child.parent = this; this.children.push(child);}},
      replaceChildren(...children) {this.replacements++; this.children = []; this.append(...children);},
      setAttribute(name, value) {this.attributes[name] = value;}, getAttribute(name) {return this.attributes[name];},
      addEventListener(name, handler) {this[name] = handler;}};
  }
  const document = {createElement: element, createElementNS: (_, tag) => element(tag), activeElement: null, hidden: false}, window = {}, actions = [], host = element('section');
  const scope = {window, document, URL, Date, Intl, clearInterval() {}, setInterval() {return 1;}, requestAnimationFrame(fn) {fn(); return 1;}};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-table.js', 'utf8'), scope);
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-timeline.js', 'utf8'), scope);
  const state = {query: {time: {mode: 'live'}}, displayTimezone: 'Europe/Warsaw', selectedRef: 'hydro_station:imgw:1', detailOpen: true, detailRevision: 1, queryRevision: 1};
  const timeline = window.WiciWorkspaceTimeline.create(host, {dispatch: action => actions.push(action), getState: () => state, now: () => '2026-11-05T12:00:00Z'});
  const flatten = node => [node, ...node.children.flatMap(flatten)];
  return {host, timeline, state, actions, api: window.WiciWorkspaceTimeline, find: predicate => flatten(host).find(predicate), all: predicate => flatten(host).filter(predicate)};
}
const sample = (at, value, extra = {}) => ({kind: 'measurement', metric: 'water_level', observed_at: `2026-11-05T${at}:00Z`, value, unit: 'cm', revision: 1, ...extra});
const detail = {object: {ref: 'hydro_station:imgw:1', type: 'hydro_station', label: 'Trestno', source_id: 'imgw'}, _detailRevision: 1, _queryRevision: 1};
const data = {timeline_summary: {buckets: [{from: '2026-11-05T00:00:00Z', to: '2026-11-05T01:00:00Z', count: 3}], overview_range: {from: '2026-11-05T00:00:00Z', to: '2026-11-06T00:00:00Z'}}};

test('station history filters sensor/metric and keeps corrected null instead of joining it', () => {
  const h = setup(), state = {...h.state, selectedRef: 'air_quality_station:gios:1', selectedSensor: '2', selectedMetric: 'PM10'};
  const timeline = {ref: state.selectedRef, items: [sample('00:00', 10, {sensor_id: '2', metric: 'PM10'}), sample('00:00', null, {sensor_id: '2', metric: 'PM10', revision: 2}), sample('01:00', 99, {sensor_id: '3', metric: 'PM10'}), sample('02:00', 9, {sensor_id: '2', metric: 'PM2.5'}), sample('03:00', 20, {sensor_id: '2', metric: 'PM10'})]};
  const items = h.api.stationSamples(timeline, state);
  assert.equal(items.length, 2); assert.equal(items[0].value, null); assert.equal(items[1].value, 20);
  assert.equal(h.api.stationSamples(timeline, {...state, selectedSensor: null}).length, 0);
  assert.equal(h.api.stationSamples(timeline, {...state, selectedRef: 'hydro_station:imgw:1'}).length, 0);
});

test('station SVG keeps gaps, separates catalogue histogram and preserves geometry during cursor changes', () => {
  const h = setup(), timeline = {ref: h.state.selectedRef, items: [sample('00:00', 390), sample('01:00', 400), sample('02:00', null), sample('03:00', 420), sample('08:00', 430)]};
  h.timeline.render(data, h.state, {detail, timeline});
  assert.equal(h.find(node => node.tagName === 'h2').textContent, 'Historia wybranego obiektu');
  const chart = h.find(node => node.className === 'analysis-station-history'), svg = chart.children[0];
  assert.equal(h.all(node => node.attributes.class === 'analysis-station-segment').length, 1);
  assert.equal(h.all(node => node.attributes.class === 'analysis-station-sample').length, 4);
  assert.equal(h.all(node => node.attributes.class === 'analysis-station-bar').length, 4, 'bars only represent numeric observations; missing samples remain gaps');
  const histogram = h.find(node => node.id === 'analysis-histogram');
  assert.equal(histogram.parent.parent.className, 'analysis-catalog-history');
  h.state.query.time = {mode: 'range', filter_range: {from: '2026-11-05T00:00:00Z', to: '2026-11-05T12:00:00Z'}};
  h.timeline.render(data, h.state, {detail, timeline});
  const rangedSvg = chart.children[0], replacements = chart.replacements;
  h.timeline.render(data, {...h.state, cursorAt: '2026-11-05T01:00:00Z'}, {detail, timeline, selectedSample: timeline.items[1]});
  assert.equal(chart.children[0], rangedSvg); assert.equal(chart.replacements, replacements);
  assert.notEqual(svg, rangedSvg);
  assert.equal(h.find(node => node.className === 'analysis-cursor-options').open, true);
});

test('stale selected object cannot display previous station history and closing restores catalogue histogram', () => {
  const h = setup(), timeline = {ref: h.state.selectedRef, items: [sample('00:00', 390)]};
  h.timeline.render(data, h.state, {detail, timeline});
  h.timeline.render(data, {...h.state, selectedRef: 'hydro_station:imgw:2'}, {detail, timeline, detailLoading: true});
  assert.equal(h.all(node => node.tagName === 'svg').length, 0);
  assert.equal(h.find(node => node.className === 'analysis-chart-empty').textContent, 'Wczytywanie historii stacji…');
  h.timeline.render(data, {...h.state, detailOpen: false}, {detail, timeline});
  assert.equal(h.find(node => node.tagName === 'h2').textContent, 'Zdarzenia w zakresie');
  assert.equal(h.find(node => node.id === 'analysis-histogram').parent.parent.className, 'analysis-time-chart');
  assert.equal(h.find(node => node.className === 'analysis-catalog-history').hidden, true);
});
