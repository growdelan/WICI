'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/wici/static/js/preferences.js'), 'utf8');
const storageKey = 'wici.ui.checkboxes.v1';
const defaults = {
  'communications-enabled': true,
  'include-active': false,
  'radar-enabled': false,
  'weather-wind': false,
  's2-full-only': true,
  'aircraft3d-osm': false,
};

function harness({stored = null, storageError} = {}) {
  const controls = Object.fromEntries(Object.entries(defaults).map(([id, checked]) =>
    [id, {id, type: 'checkbox', checked, disabled: false}]));
  const listeners = [], writes = [], dispatched = [];
  let writeAttempts = 0;
  const document = {
    querySelectorAll(selector) {
      assert.equal(selector, 'input[type="checkbox"][id]');
      return Object.values(controls);
    },
    addEventListener(type, callback, options) {
      listeners.push({type, callback, capture: options === true || options?.capture === true});
    },
    dispatchEvent() { assert.fail('Preferences must not emit document events'); },
  };
  const storage = {
    getItem(key) {
      assert.equal(key, storageKey);
      if (storageError === 'read') throw new Error('SecurityError');
      return stored;
    },
    setItem(key, value) {
      assert.equal(key, storageKey);
      writeAttempts++;
      if (storageError === 'write') throw new Error('QuotaExceededError');
      writes.push({key, value});
    },
  };
  const window = {get localStorage() {
    if (storageError === 'access') throw new Error('SecurityError');
    return storage;
  }};
  // Only the DOM and storage capabilities required by this module are exposed.
  // Unexpected requests, timers, reloads or synthetic events fail the harness.
  vm.runInNewContext(source, {window, document});
  function change(target, {bubbles = true} = {}) {
    const event = {type: 'change', target, bubbles};
    dispatched.push(event);
    for (const listener of listeners) {
      if (listener.type === event.type && (listener.capture || event.bubbles)) listener.callback(event);
    }
  }
  return {controls, listeners, writes, dispatched, change, api: window.WiciPreferences,
    get writeAttempts() { return writeAttempts; },
    get saved() { return writes.length ? JSON.parse(writes.at(-1).value) : null; }};
}

test('stored boolean choices restore synchronously only for known checkbox ids', () => {
  const h = harness({stored: JSON.stringify({
    'communications-enabled': false,
    'radar-enabled': true,
    'include-active': 'true',
    'weather-wind': 1,
    's2-full-only': null,
    'aircraft3d-osm': {},
    'removed-checkbox': true,
    toString: false,
  })});
  assert.equal(h.controls['communications-enabled'].checked, false);
  assert.equal(h.controls['radar-enabled'].checked, true);
  for (const id of ['include-active', 'weather-wind', 's2-full-only', 'aircraft3d-osm']) {
    assert.equal(h.controls[id].checked, defaults[id]);
    assert.equal(h.api.value(id, 'fallback'), 'fallback');
  }
  assert.equal(h.api.value('communications-enabled', true), false);
  assert.equal(h.api.value('radar-enabled', false), true);
  assert.equal(h.api.value('removed-checkbox', 'fallback'), 'fallback');
  assert.equal(h.api.value('toString', 'fallback'), 'fallback');
  assert.deepEqual(h.writes, []);
  assert.deepEqual(h.dispatched, []);
});

test('absent preferences preserve HTML defaults and caller-specific fallback values', () => {
  for (const stored of [null, '{}']) {
    const h = harness({stored});
    for (const [id, checked] of Object.entries(defaults)) {
      assert.equal(h.controls[id].checked, checked);
      assert.equal(h.api.value(id, true), true);
      assert.equal(h.api.value(id, false), false);
    }
    assert.deepEqual(h.writes, []);
  }
});

test('invalid JSON, primitives and arrays do not block startup or override defaults', () => {
  for (const stored of ['', '{', 'null', 'true', 'false', '0', '1', '"text"', '[]',
    '[{"communications-enabled":false,"radar-enabled":true}]']) {
    const h = harness({stored});
    for (const [id, checked] of Object.entries(defaults)) assert.equal(h.controls[id].checked, checked);
    assert.equal(h.api.value('communications-enabled', 'fallback'), 'fallback');
    assert.deepEqual(h.writes, []);
    h.controls['radar-enabled'].checked = true;
    h.change(h.controls['radar-enabled']);
    assert.deepEqual(h.saved, {'radar-enabled': true});
  }
});

test('denied storage access, reads and writes leave checkbox choices usable in memory', () => {
  for (const storageError of ['access', 'read', 'write']) {
    const h = harness({storageError});
    const control = h.controls['radar-enabled'];
    assert.equal(control.checked, false);
    control.checked = true;
    h.change(control);
    assert.equal(control.checked, true);
    assert.equal(h.api.value(control.id, false), true);
    control.checked = false;
    h.api.remember(control);
    assert.equal(control.checked, false);
    assert.equal(h.api.value(control.id, true), false);
    if (storageError === 'write') {
      assert.equal(h.writeAttempts, 2);
      assert.deepEqual(h.writes, []);
    }
    if (storageError === 'read') assert.deepEqual(h.saved, {'radar-enabled': false});
    if (storageError === 'access') assert.deepEqual(h.writes, []);
  }
});

test('saving one checkbox does not snapshot temporary states or unrelated defaults', () => {
  const h = harness({stored: JSON.stringify({'include-active': true, 'communications-enabled': false})});
  // Archive navigation temporarily clears and disables this control without
  // changing the user's saved preference for today's publications.
  h.controls['include-active'].checked = false;
  h.controls['include-active'].disabled = true;
  h.controls['radar-enabled'].checked = true;
  h.change(h.controls['radar-enabled']);
  assert.deepEqual(h.saved, {'include-active': true, 'communications-enabled': false, 'radar-enabled': true});
  assert.equal(Object.hasOwn(h.saved, 's2-full-only'), false);
  assert.equal(Object.hasOwn(h.saved, 'aircraft3d-osm'), false);
  const reloaded = harness({stored: h.writes.at(-1).value});
  assert.equal(reloaded.controls['include-active'].checked, true);
  assert.equal(reloaded.controls['communications-enabled'].checked, false);
  assert.equal(reloaded.controls['radar-enabled'].checked, true);
  assert.equal(reloaded.controls['s2-full-only'].checked, true);
});

test('capture observes non-bubbling checkbox changes and ignores unrelated targets', () => {
  const h = harness();
  assert.ok(h.listeners.some(listener => listener.type === 'change' && listener.capture));
  const control = h.controls['communications-enabled'];
  control.checked = false;
  h.change(control, {bubbles: false});
  assert.deepEqual(h.saved, {'communications-enabled': false});
  h.change({id: 'province', type: 'select-one', value: '14'});
  h.change({id: 'new-checkbox', type: 'checkbox', checked: true});
  h.change({id: control.id, type: 'checkbox', checked: true});
  h.change(null);
  assert.equal(h.writes.length, 1);
  assert.equal(h.api.value(control.id, true), false);
});

test('remember saves programmatic changes without emitting events or touching other controls', () => {
  const h = harness(), control = h.controls['weather-wind'];
  control.checked = true;
  h.api.remember(control);
  assert.deepEqual(h.saved, {'weather-wind': true});
  assert.equal(h.api.value(control.id, false), true);
  assert.deepEqual(h.dispatched, []);
  for (const [id, checked] of Object.entries(defaults)) {
    if (id !== control.id) assert.equal(h.controls[id].checked, checked);
  }
  h.api.remember(undefined);
  h.api.remember({id: control.id, checked: false});
  assert.equal(h.writes.length, 1);
});

test('preferences defer script precedes all deferred initialization modules', () => {
  const html = fs.readFileSync(path.join(__dirname, '../src/wici/static/index.html'), 'utf8');
  const scripts = [...html.matchAll(/<script\b([^>]*)\bsrc="([^"]+)"[^>]*><\/script>/g)]
    .map(match => ({attributes: match[1], src: match[2]}));
  const deferred = scripts.filter(script => /\bdefer\b/.test(script.attributes));
  assert.equal(deferred[0]?.src, '/static/js/preferences.js');
  assert.equal(scripts.filter(script => script.src === '/static/js/preferences.js').length, 1);
  assert.equal(/\basync\b/.test(deferred[0].attributes), false);
  for (const module of ['layers', 'atlas', 'app', 'weather', 'radar', 'buses', 'aircraft3d']) {
    assert.ok(deferred.some(script => script.src === `/static/js/${module}.js`), `${module} remains deferred`);
  }
});
