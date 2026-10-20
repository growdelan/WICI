const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function harness() {
  const controls = new Map(), observers = [];
  const document = {getElementById(id) {
    if (!controls.has(id)) controls.set(id, {checked: false, disabled: false, textContent: '', events: {}, addEventListener(type, fn) { this.events[type] = fn; }});
    return controls.get(id);
  }};
  const window = {MutationObserver: class {constructor(callback) { this.callback = callback; observers.push(this); } observe(control, options) { this.targets ??= []; this.targets.push({control, options}); }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/wici/static/js/layers.js'), 'utf8'), {window, document});
  return {window, document, controls, observers, get count() { return document.getElementById('layer-selection').textContent; }};
}

test('compact count includes primary checked available layers while excluding base and module helpers', () => {
  const h = harness();
  assert.equal(h.count, '· 0 aktywnych');
  for (const id of ['communications-enabled', 'radar-enabled', 'hydro-stations', 'weather-wind']) h.document.getElementById(id).checked = true;
  const disabled = h.document.getElementById('aircraft-enabled'); disabled.checked = true; disabled.disabled = true;
  for (const id of ['osm-enabled', 'weather-animation', 's2-quality', 's5p-quality', 'ioda-communications', 'trains-positions-enabled']) h.document.getElementById(id).checked = true;
  h.window.WiciLayers.update();
  assert.equal(h.count, '· 4 aktywnych');
  assert.equal(h.document.getElementById('osm-enabled').events.change, undefined);
  assert.equal(disabled.checked, true, 'counting must not modify selections');
  h.document.getElementById('radar-enabled').checked = false;
  h.document.getElementById('radar-enabled').events.change();
  assert.equal(h.count, '· 3 aktywnych');
  h.document.getElementById('communications-enabled').checked = false;
  h.document.getElementById('communications-enabled').events.change();
  assert.equal(h.count, '· 2 aktywnych');
});

test('availability changes update count without synthetic checkbox events or changing group state', () => {
  const h = harness(), control = h.document.getElementById('trains-enabled');
  control.checked = true;
  h.window.WiciLayers.update();
  assert.equal(h.count, '· 1 aktywnych');
  control.disabled = true;
  h.observers[0].callback();
  assert.equal(h.count, '· 0 aktywnych');
  control.disabled = false;
  h.observers[0].callback();
  assert.equal(h.count, '· 1 aktywnych');
  assert.equal(control.checked, true);
  assert.ok(h.observers[0].targets.some(target => target.control === control && target.options.attributeFilter.includes('disabled')));
});
