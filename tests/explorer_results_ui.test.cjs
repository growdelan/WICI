'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');

function setup() {
  function element(tag) {
    const classes = new Set();
    return {tagName: tag, children: [], dataset: {}, attributes: {}, hidden: false, textContent: '', replacements: 0,
      classList: {toggle(name, value) {value ? classes.add(name) : classes.delete(name);}},
      append(...children) {this.children.push(...children);},
      replaceChildren(...children) {this.replacements++; this.children = children;},
      setAttribute(name, value) {this.attributes[name] = value;}, removeAttribute(name) {delete this.attributes[name];},
      addEventListener(name, handler) {this[name] = handler;}, focus() {this.focused = true;}};
  }
  const document = {createElement: element}, window = {}, selections = [], host = element('section');
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-table.js', 'utf8'), {window, document, URL, Date, Intl});
  const table = window.WiciWorkspaceTable(host, {select: (...args) => selections.push(args)});
  const flatten = node => [node, ...node.children.flatMap(flatten)];
  const find = predicate => flatten(host).find(predicate);
  const state = {query: {sort: {field: 'label', direction: 'asc'}, time: {mode: 'live'}}, columns: ['label', 'type', 'updated_at', 'measurement'], detailOpen: false, displayTimezone: 'Europe/Warsaw'};
  return {host, table, selections, state, find};
}
const station = {ref: 'hydro_station:imgw:1', type: 'hydro_station', source_id: 'imgw', label: 'Trestno', freshness: 'fresh', measurement: {value: 412, unit: 'cm', metric: 'water_level', observed_at: '2026-11-05T08:40:00Z', thresholds: {warning_level_cm: 400, alarm_level_cm: 450}}};

test('explorer starts as a list and table switch preserves selection target and existing DOM', () => {
  const h = setup(), data = {items: [station], total: 18};
  h.table.render(data, h.state);
  const row = h.find(node => node.dataset.ref === station.ref), body = h.find(node => node.tagName === 'tbody');
  assert.equal(h.host.dataset.resultsView, 'list');
  assert.deepEqual(row.children.map(node => node.hidden), [false, true, true, true]);
  assert.equal(h.find(node => node.id === 'analysis-count').textContent, '· 18');
  const link = h.find(node => node.className === 'analysis-object-link');
  link.click({currentTarget: link}); assert.equal(h.selections[0][0], station.ref);
  const replacements = body.replacements;
  h.find(node => node.dataset.resultsView === 'table').click();
  assert.equal(h.host.dataset.resultsView, 'table');
  assert.deepEqual(row.children.map(node => node.hidden), [false, false, false, false]);
  assert.equal(body.replacements, replacements);
  assert.equal(h.find(node => node.dataset.ref === station.ref), row);
  h.find(node => node.tagName === 'button' && node.dataset.resultsView === 'list').click();
  assert.equal(h.find(node => node.className === 'analysis-object-link'), link);
});

test('station badges distinguish fresh threshold, old measurements and historical samples', () => {
  const h = setup(), status = () => h.find(node => node.className === 'analysis-result-status');
  h.table.render({items: [station], total: 1}, h.state);
  assert.equal(status().textContent, 'Próg ostrzegawczy'); assert.equal(status().dataset.tone, 'warning');
  assert.match(h.find(node => node.className === 'analysis-result-meta').textContent, /Wodowskaz · IMGW · 09:40/);
  h.table.render({items: [{...station, freshness: 'stale'}], total: 1}, h.state);
  assert.equal(status().textContent, 'Nieaktualne'); assert.equal(status().dataset.tone, 'muted');
  h.table.render({items: [station], total: 1}, {...h.state, query: {...h.state.query, time: {mode: 'range'}}});
  assert.equal(status().textContent, 'Zapis');
  h.table.render({items: [{...station, measurement: {...station.measurement, value: null}}], total: 1}, h.state);
  assert.equal(status().textContent, 'Brak pomiaru');
});

test('selected cursor updates only the chosen row and list mode always keeps its name visible', () => {
  const h = setup(), second = {...station, ref: 'hydro_station:imgw:2', label: 'Oława'}, data = {items: [station, second], total: 2};
  h.table.render(data, h.state);
  const body = h.find(node => node.tagName === 'tbody'), secondRow = h.find(node => node.dataset.ref === second.ref), secondReading = secondRow.children[3], replacements = secondReading.replacements;
  const state = {...h.state, columns: ['measurement'], selectedRef: station.ref, detailOpen: true, cursorAt: '2026-11-05T08:00:00Z'};
  h.table.render(data, state, {...station.measurement, value: 390, observed_at: state.cursorAt});
  assert.equal(body.replacements, 1); assert.equal(secondReading.replacements, replacements);
  assert.equal(h.find(node => node.dataset.ref === station.ref).children[0].hidden, false);
  assert.equal(h.find(node => node.className === 'analysis-result-status').textContent, 'Według kursora');
  h.find(node => node.dataset.resultsView === 'table').click();
  assert.equal(h.find(node => node.dataset.ref === station.ref).children[0].hidden, true);
});


test('date-only publications never acquire an invented hour in the list', () => {
  const h = setup();
  h.table.render({items: [{ref: 'communication:1', type: 'communication', source_id: 'rso', label: 'Komunikat', date_precision: 'day', published_at: '2026-11-05T00:00:00Z'}], total: 1}, h.state);
  const meta = h.find(node => node.className === 'analysis-result-meta').textContent;
  assert.match(meta, /2026-11-05 · sama data/); assert.doesNotMatch(meta, /01:00|02:00/);
});
