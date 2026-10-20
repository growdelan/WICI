const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/wici/static/js/theme.js'), 'utf8');

function harness({stored, blockedRead = false, blockedWrite = false, ready = false} = {}) {
  const root = {}, listeners = {}, emitted = [], writes = [], attributes = {};
  const button = {title: '', setAttribute(name, value) { attributes[name] = value; }, addEventListener(type, fn) { this[type] = fn; }};
  const document = {readyState: ready ? 'complete' : 'loading', documentElement: {setAttribute(name, value) { root[name] = value; }},
    getElementById(id) { assert.equal(id, 'theme-toggle'); return button; },
    addEventListener(type, fn) { listeners[type] = fn; }, dispatchEvent(event) { emitted.push(event); }};
  const window = {get localStorage() {
    if (blockedRead) throw new Error('SecurityError');
    return {getItem(key) { assert.equal(key, 'wici.ui.theme.v1'); return stored; }, setItem(key, value) {
      if (blockedWrite) throw new Error('QuotaExceededError'); writes.push({key, value});
    }};
  }};
  // Any accidental data request, timer, page reload or unrelated DOM access fails this harness.
  vm.runInNewContext(source, {window, document, CustomEvent: class {constructor(type, options) { this.type = type; this.detail = options.detail; }}});
  return {root, listeners, emitted, writes, attributes, button, bind() { listeners.DOMContentLoaded?.(); }};
}

test('bootstrap applies only a valid stored theme synchronously before DOM ready', () => {
  for (const [stored, expected] of [[undefined, 'light'], [null, 'light'], ['', 'light'], ['invalid', 'light'], ['DARK', 'light'], ['light', 'light'], ['dark', 'dark']]) {
    const h = harness({stored});
    assert.equal(h.root['data-theme'], expected);
    assert.equal(h.button.click, undefined);
    assert.deepEqual(h.emitted, []);
    assert.deepEqual(h.writes, []);
    h.bind();
    assert.equal(h.attributes['aria-pressed'], String(expected === 'dark'));
  }
});

test('storage access and writes can fail while keyboard-native button remains usable', () => {
  for (const options of [{blockedRead: true}, {blockedWrite: true}]) {
    const h = harness(options); h.bind();
    assert.equal(h.root['data-theme'], 'light');
    h.button.click();
    assert.equal(h.root['data-theme'], 'dark');
    assert.equal(h.attributes['aria-pressed'], 'true');
    h.button.click();
    assert.equal(h.root['data-theme'], 'light');
    assert.equal(h.attributes['aria-pressed'], 'false');
  }
});

test('each toggle persists only theme and emits one presentation event without data side effects', () => {
  const h = harness({stored: 'dark', ready: true});
  assert.match(h.button.title, /Atlasu/);
  h.button.click();
  assert.equal(h.root['data-theme'], 'light');
  assert.match(h.button.title, /Włącz WICI Noc/);
  assert.deepEqual(h.writes, [{key: 'wici.ui.theme.v1', value: 'light'}]);
  assert.equal(h.emitted.length, 1);
  assert.equal(h.emitted[0].type, 'wici:themechange');
  assert.equal(h.emitted[0].detail.theme, 'light');
  assert.deepEqual(Object.keys(h.emitted[0].detail), ['theme']);
});

test('theme bootstrap is local, synchronous and precedes every stylesheet', () => {
  const html = fs.readFileSync(path.join(__dirname, '../src/wici/static/index.html'), 'utf8');
  const script = html.indexOf('<script src="/static/js/theme.js"></script>');
  assert.ok(script >= 0 && script < html.indexOf('rel="stylesheet"'));
  assert.match(html, /<button type="button" id="theme-toggle"[^>]*aria-pressed="false"/);
});

function mapHarness({opacity = 0} = {}) {
  const app = fs.readFileSync(path.join(__dirname, '../src/wici/static/js/app.js'), 'utf8');
  const presentation = app.slice(app.indexOf('function mapPresentationStyles()'), app.indexOf('async function initMap()'));
  const callbacks = {}, changes = [], admin = {options: {fillOpacity: opacity, color: 'old'}, setStyle(style) { changes.push('administrative'); Object.assign(this.options, style); }};
  const borders = [0, 1].map(index => ({options: {fill: false}, setStyle(style) { changes.push(index); Object.assign(this.options, style); }}));
  const state = {administrativeLayer: admin, countryBorderLayers: borders,
    selected: 'selected-record', layers: [{style: {color: '#bf3232'}, layer: {popup: 'still open'}}],
    map: {center: [51, 19], zoom: 8}, communications: [{id: 'selected-record'}]};
  const before = JSON.stringify({selected: state.selected, layers: state.layers, map: state.map, communications: state.communications});
  const tokens = {'--map-prg-line': '#587582', '--map-prg-fill': '#0f2028', '--map-border-halo': '#0b141b', '--map-border-line': '#90bac6'};
  const document = {documentElement: {}, addEventListener(type, fn) { callbacks[type] = fn; }};
  vm.runInNewContext(presentation, {state, document, window: {getComputedStyle() { return {getPropertyValue(key) { return tokens[key]; }}; }}});
  return {state, admin, borders, callbacks, before, changes};
}

test('theme event restyles existing PRG only, preserving OSM fill visibility and selected popup/map/data', () => {
  for (const opacity of [0, 1]) {
    const h = mapHarness({opacity}), originalAdmin = h.admin, originalBorders = [...h.borders];
    h.callbacks['wici:themechange']();
    assert.equal(h.admin.options.color, '#587582');
    assert.equal(h.admin.options.fillColor, '#0f2028');
    assert.equal(h.admin.options.fillOpacity, opacity);
    assert.equal(h.borders[0].options.color, '#0b141b');
    assert.equal(h.borders[1].options.color, '#90bac6');
    assert.equal(h.state.administrativeLayer, originalAdmin);
    assert.deepEqual(h.state.countryBorderLayers, originalBorders);
    assert.equal(JSON.stringify({selected: h.state.selected, layers: h.state.layers, map: h.state.map, communications: h.state.communications}), h.before);
    assert.deepEqual(h.changes, ['administrative', 0, 1]);
  }
});

test('PRG loading resolves in the current theme after a toggle during the geometry request', async () => {
  const app = fs.readFileSync(path.join(__dirname, '../src/wici/static/js/app.js'), 'utf8');
  const initialization = app.slice(app.indexOf('let mapReady=false;'), app.indexOf('function geometryFor(loc)'));
  const requests = [], callbacks = {}, layers = [];
  let currentTheme = 'light', styleReads = 0;
  const state = {map: {fitBounds() {}}, administrativeLayer: null, countryBorderLayers: [], geometries: new Map()};
  const document = {documentElement: {}, addEventListener(type, fn) { callbacks[type] = fn; }};
  const L = {geoJSON(geometry, options = {}) {
    const layer = {options: {...options.style}, addTo(map) { assert.equal(map, state.map); layers.push(this); return this; },
      getBounds() { return {isValid() { return true; }}; }};
    return layer;
  }};
  const context = vm.createContext({state, document, L, window: {L, getComputedStyle() {
    styleReads++;
    return {getPropertyValue(name) { return name === '--map-prg-fill' ? (currentTheme === 'dark' ? '#0f2028' : '#f7fafb') : ''; }};
  }}, fetchJSON(url) { return new Promise(resolve => requests.push({url, resolve})); },
    $() { return {append() {}}; }, el() { return {}; }, syncWeather() {}, syncOsm() {}, renderMap() {}, syncIoda() {}});
  vm.runInContext(initialization, context);
  const pending = context.initMap();
  assert.equal(requests.length, 3);
  assert.equal(styleReads, 0);
  currentTheme = 'dark';
  callbacks['wici:themechange']();
  assert.equal(styleReads, 0, 'no layers exist to restyle before the requests complete');
  for (const request of requests) request.resolve({response: {ok: true}, data: {type: 'FeatureCollection', features: []}});
  await pending;
  assert.equal(state.administrativeLayer.options.fillColor, '#0f2028');
  assert.equal(state.countryBorderLayers.length, 2);
  assert.equal(layers.length, 3);
  assert.equal(styleReads, 1);
  assert.equal(requests.length, 3, 'theme switch must not start an additional geometry request');
});
