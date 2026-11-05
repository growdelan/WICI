'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const Store = require('../src/wici/static/js/workspace-store.js');

function setup() {
  let focused;
  function node(tag) {
    const classes = new Set();
    return {tagName: tag.toUpperCase(), children: [], dataset: {}, attributes: {}, hidden: false, textContent: '',
      classList: {add(value) {classes.add(value);}, contains(value) {return classes.has(value);}},
      append(...children) {this.children.push(...children);}, replaceChildren(...children) {this.children = children;}, after(sibling) {this.sibling = sibling;},
      setAttribute(key, value) {this.attributes[key] = String(value);}, addEventListener(name, callback) {this[name] = callback;}, focus() {focused = this;},
      get firstChild() {return this.children[0];}};
  }
  const document = {createElement: node, createElementNS: (_, tag) => node(tag)}, window = {};
  const context = {window, document, Date, Intl, URL};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-table.js', 'utf8'), context);
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/object-card.js', 'utf8'), context);
  const calls = [], host = node('aside'), actions = Object.fromEntries(['close', 'show', 'graph', 'pin', 'capture', 'sensor', 'sample', 'moreHistory', 'fetchSource', 'rule'].map(name => [name, (...args) => calls.push([name, ...args])]));
  const card = window.WiciObjectCard(host, actions), flatten = value => [value, ...value.children.flatMap(flatten)];
  const find = predicate => flatten(host).find(predicate), byId = id => find(value => value.id === id);
  return {host, card, calls, find, byId, nodes: () => flatten(host), focused: () => focused};
}
const station = {ref: 'hydro_station:imgw:1', type: 'hydro_station', label: 'Trestno', source_id: 'imgw_hydro', freshness: 'fresh', metadata: {river: 'Odra'}};
const state = {...Store.initialState(), detailOpen: true, selectedRef: station.ref, selectedMetric: 'water_level', detailRevision: 1, queryRevision: 1};
const sample = (value, hour, extra = {}) => ({value, metric: 'water_level', unit: 'cm', quality: 'valid', observed_at: `2026-11-05T${hour}:00:00Z`, thresholds: {warning_level_cm: 400, alarm_level_cm: 500}, ...extra});
const detail = object => ({object, _detailRevision: 1, _queryRevision: 1});

test('inspector uses recorded thresholds and cannot classify absent, old or stale-generation samples as normal', () => {
  const h = setup(), value = sample(412, '09'), shown = detail({...station, measurement: value});
  h.card.render(shown, {items: [value]}, state, value);
  const badge = () => h.find(node => node.className === 'analysis-reading-status');
  assert.equal(badge().dataset.status, 'warning');
  assert.match(badge().textContent, /ostrzegawczy/);
  h.card.render(shown, null, {...state, detailRevision: 2}, value);
  assert.equal(badge().dataset.status, 'unknown');
  h.card.render(shown, null, state, sample(null, '09'));
  assert.equal(badge().dataset.status, 'unknown');
  h.card.render(shown, null, {...state, cursorAt: '2026-11-05T13:00:00Z'}, value);
  assert.equal(badge().dataset.status, 'stale');
  h.card.render(shown, null, state, sample(412, '09', {thresholds: {}}));
  assert.equal(badge().dataset.status, 'ready');
  h.card.render(shown, null, state, sample(280, '09'));
  assert.equal(badge().dataset.status, 'normal');
  h.card.render(shown, null, state, value, {loading: true});
  assert.equal(badge().dataset.status, 'unknown');
});

test('history is a keyboard accessible tab preserving sample selection and pagination actions', () => {
  const h = setup(), value = sample(412, '09');
  h.card.render(detail(station), {items: [value], next_cursor: 'more'}, state, value);
  assert.equal(h.byId('analysis-card-panel-history').hidden, true);
  h.byId('analysis-card-tab-details').keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(h.byId('analysis-card-panel-history').hidden, false);
  assert.equal(h.byId('analysis-card-panel-details').hidden, true);
  assert.equal(h.focused(), h.byId('analysis-card-tab-history'));
  assert.equal(h.byId('analysis-card-tab-history').attributes['aria-selected'], 'true');
  h.find(node => node.tagName === 'BUTTON' && node.textContent === 'Wczytaj kolejne zapisane próbki').click();
  assert.equal(h.calls.at(-1)[0], 'moreHistory');
  const table = h.find(node => node.className === 'analysis-sample-table');
  table.children[1].children[0].children[0].children[0].click();
  assert.deepEqual(h.calls.at(-1), ['sample', value]);
  h.byId('analysis-pin-object').click(); h.byId('analysis-show-relations').click();
  assert.equal(h.calls.at(-2)[0], 'pin'); assert.deepEqual(h.calls.at(-1), ['graph', station]);
  h.card.render(detail(station), null, {...state, detailOpen: false}, null);
  assert.equal(h.host.hidden, true); assert.equal(h.host.sibling.hidden, false);
});

test('chart retains null gaps and the latest correction instead of drawing a continuous invented series', () => {
  const h = setup();
  const items = [sample(390, '07'), sample(401, '08', {revision: 1}), sample(null, '08', {revision: 2}), sample(412, '09'), sample(414, '10')];
  h.card.render(detail(station), {items}, state, items.at(-1));
  const circles = h.nodes().filter(node => node.tagName === 'CIRCLE');
  assert.equal(circles.length, 3, 'corrected null is not a zero or the earlier reading');
  const segments = h.nodes().filter(node => node.tagName === 'LINE' && node.attributes.stroke === 'var(--teal)');
  assert.equal(segments.length, 1, 'only the 09:00 to 10:00 interval is connected');
  assert.ok(h.nodes().some(node => node.tagName === 'TEXT' && node.textContent === 'cm'));
  assert.ok(h.nodes().some(node => node.tagName === 'LINE' && node.attributes['stroke-dasharray'] === '6 5'));
});

test('secondary actions remain expanded during detail refresh and reset only for a different object', () => {
  const h = setup(), value = sample(412, '09');
  const disclosure = () => h.find(node => node.className === 'analysis-card-secondary-actions');
  h.card.render(detail(station), {items: [value]}, state, value);
  assert.equal(disclosure().open, false);
  disclosure().open = true;
  const refreshed = {...station, label: 'Trestno — aktualizacja'};
  h.card.render(detail(refreshed), {items: [value]}, state, value);
  assert.equal(disclosure().open, true, 'periodic refresh preserves the open actions');
  h.find(node => node.tagName === 'BUTTON' && node.textContent === 'Pokaż na mapie').click();
  assert.deepEqual(h.calls.at(-1), ['show', refreshed], 'rebuilt controls use the refreshed object');
  disclosure().open = false;
  h.card.render(detail(refreshed), {items: [value]}, state, value);
  assert.equal(disclosure().open, false, 'explicit closing persists through refresh');
  disclosure().open = true;
  const other = {...station, ref: 'hydro_station:imgw:2', label: 'Inny wodowskaz'};
  h.card.render(detail(other), {items: [value]}, {...state, selectedRef: other.ref}, value);
  assert.equal(disclosure().open, false, 'a different object starts with collapsed secondary actions');
});
