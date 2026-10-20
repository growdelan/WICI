const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function harness({stacked = false} = {}) {
  const listeners = {}, frames = [], resized = [];
  const document = {activeElement: null, addEventListener(type, fn) { listeners[type] = fn; }};
  function element() {
    return {hidden: false, open: false, events: {}, scrolls: [],
      scrollIntoView(options) { this.scrolls.push({...options}); },
      addEventListener(type, fn) { this.events[type] = fn; },
      focus() { document.activeElement = this; },
      contains(target) { return target === this || target?.parent === this; },
      getAttribute(name) { return this[name]; }};
  }
  const elements = Object.fromEntries(['detail-panel', 'detail-title', 'layer-panel', 'map', 'situation', 'close-details', 'filters', 'filter-selection', 'theme-toggle'].map(id => [id, element()]));
  const filters = {category: {value: ''}, voivodeship: {value: ''}, include_active: {checked: false}};
  elements.filters.elements = {namedItem(name) { return filters[name]; }};
  elements['detail-panel'].hidden = true;
  elements['detail-title'].parent = elements['detail-panel'];
  elements['close-details'].parent = elements['detail-panel'];
  const summary = element(), tab = element(), record = element();
  record['data-communication-id'] = 'selected';
  elements['layer-panel'].querySelector = () => summary;
  document.getElementById = id => elements[id];
  document.querySelectorAll = selector => selector === '.tab' ? [tab] : [record];
  const window = {matchMedia(query) { assert.equal(query, '(max-width: 600px)'); return {matches: stacked}; }, addEventListener(type, fn) { listeners[`window:${type}`] = fn; },
    requestAnimationFrame(fn) { frames.push(fn); },
    ResizeObserver: class { constructor(callback) { this.callback = callback; resized.push(this); } observe(target) { this.target = target; } }};
  const context = vm.createContext({document, window, setTimeout});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/wici/static/js/atlas.js'), 'utf8'), context);
  let invalidations = 0;
  window.WiciAtlas.setMap({invalidateSize(options) { assert.equal(options.pan, false); invalidations++; }});
  const flush = () => { while (frames.length) frames.shift()(); };
  flush();
  return {filters, api: window.WiciAtlas, document, elements, listeners, summary, tab, record, resized, frames, flush, get invalidations() { return invalidations; }};
}

test('publication drawer opens without a modal trap and close restores the matching list card', () => {
  const h = harness();
  h.elements['layer-panel'].open = true;
  h.api.openDetails('selected');
  assert.equal(h.elements['detail-panel'].hidden, false);
  assert.equal(h.elements['layer-panel'].open, false);
  assert.equal(h.document.activeElement, h.elements['detail-title']);
  assert.equal(h.listeners.keydown({key: 'Tab'}), undefined);
  assert.equal(h.elements['detail-panel'].hidden, false);
  h.elements['close-details'].focus();
  h.elements['close-details'].events.click();
  assert.equal(h.elements['detail-panel'].hidden, true);
  assert.equal(h.document.activeElement, h.record);
});

test('Escape dismisses native layer settings first; outside click and view changes also close settings', () => {
  const h = harness(); let prevented = 0;
  h.api.openDetails('selected');
  h.elements['layer-panel'].open = true;
  h.listeners.keydown({key: 'Escape', preventDefault() { prevented++; }});
  assert.equal(h.elements['layer-panel'].open, false);
  assert.equal(h.elements['detail-panel'].hidden, false);
  assert.equal(h.document.activeElement, h.summary);
  assert.equal(prevented, 1);
  h.elements['layer-panel'].open = true;
  h.listeners.click({target: h.elements['layer-panel']});
  assert.equal(h.elements['layer-panel'].open, true);
  h.listeners.click({target: h.record});
  assert.equal(h.elements['layer-panel'].open, false);
  h.elements['layer-panel'].open = true;
  h.tab.events.click();
  assert.equal(h.elements['layer-panel'].open, false);
});

test('map resize observation coalesces layout changes and skips a hidden situation view', () => {
  const h = harness(), before = h.invalidations;
  assert.equal(h.resized[0].target, h.elements.map);
  h.resized[0].callback();
  h.listeners['window:resize']();
  h.api.openDetails('selected');
  assert.equal(h.frames.length, 1);
  h.flush();
  assert.equal(h.invalidations, before + 1);
  h.elements.situation.hidden = true;
  h.resized[0].callback(); h.flush();
  assert.equal(h.invalidations, before + 1);
  h.elements.situation.hidden = false;
  h.tab.events.click(); h.flush();
  assert.equal(h.invalidations, before + 2);
});

test('theme toggle and its icon preserve open layer settings and the current drawer revision', () => {
  const h = harness();
  h.api.openDetails('selected');
  h.elements['layer-panel'].open = true;
  const revision = h.api.revision;
  h.listeners.click({target: h.elements['theme-toggle']});
  h.listeners.click({target: {parent: h.elements['theme-toggle']}});
  assert.equal(h.elements['layer-panel'].open, true);
  assert.equal(h.elements['detail-panel'].hidden, false);
  assert.equal(h.api.revision, revision);
});

test('day reset hides details without moving keyboard focus', () => {
  const h = harness();
  h.api.openDetails('selected');
  const dateInput = {name: 'date'}; h.document.activeElement = dateInput;
  h.api.resetDetails();
  assert.equal(h.elements['detail-panel'].hidden, true);
  assert.equal(h.document.activeElement, dateInput);
});

test('late publication responses cannot replace the newest selection or reopen a day-reset drawer', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../src/wici/static/js/app.js'), 'utf8');
  const selectionFunction = source.slice(source.indexOf('async function selectCommunication(id)'), source.indexOf('\n\nfunction syncWeather()'));
  const requests = [], rendered = [], opened = [], highlighted = [];
  const state = {selected: null};
  const context = vm.createContext({state, encodeURIComponent, renderCommunications() {},
    api(path) { return new Promise(resolve => requests.push({path, resolve})); },
    renderCommunication(item) { rendered.push(item.id); }, highlightMap(id) { highlighted.push(id); },
    error(err) { throw err; }, window: {WiciAtlas: {openDetails(id) { opened.push(id); }}}});
  vm.runInContext(selectionFunction, context);
  const first = context.selectCommunication('first');
  const second = context.selectCommunication('second');
  requests[1].resolve({id: 'second'}); await second;
  requests[0].resolve({id: 'first'}); await first;
  assert.deepEqual(rendered, ['second']);
  assert.deepEqual(opened, ['second']);
  assert.deepEqual(highlighted, ['second']);
  const pending = context.selectCommunication('old-day');
  state.selected = null;
  requests[2].resolve({id: 'old-day'}); await pending;
  assert.deepEqual(opened, ['second']);
  context.window.WiciAtlas.revision = 0;
  const closedDuringRequest = context.selectCommunication('closed-before-load');
  context.window.WiciAtlas.revision++;
  requests[3].resolve({id: 'closed-before-load'}); await closedDuringRequest;
  assert.deepEqual(opened, ['second'], 'manual dismissal must survive a pending response');
  assert.equal(rendered.at(-1), 'closed-before-load', 'latest detail data stays available without reopening');
});


test('collapsed filter summary exposes hidden filter count and tracks programmatic day changes', () => {
  const h = harness();
  assert.equal(h.elements['filter-selection'].textContent, 'Bez dodatkowych filtrów');
  h.filters.category.value = 'weather';
  h.elements.filters.events.change();
  assert.equal(h.elements['filter-selection'].textContent, '1 aktywny filtr');
  h.filters.voivodeship.value = '14';
  h.filters.include_active.checked = true;
  h.api.updateFilterSummary();
  assert.equal(h.elements['filter-selection'].textContent, '3 aktywne filtry');
  h.filters.include_active.checked = false;
  h.api.updateFilterSummary();
  assert.equal(h.elements['filter-selection'].textContent, '2 aktywne filtry');
});


test('stacked mobile layout reveals the opened drawer and returns the selected list card into view', () => {
  const h = harness({stacked: true});
  h.api.openDetails('selected');
  assert.deepEqual(h.elements['detail-panel'].scrolls, [{block: 'nearest', behavior: 'auto'}]);
  assert.equal(h.document.activeElement, h.elements['detail-title']);
  h.elements['close-details'].focus();
  h.api.closeDetails();
  assert.equal(h.document.activeElement, h.record);
  assert.deepEqual(h.record.scrolls, [{block: 'nearest', behavior: 'auto'}]);
  h.api.openDetails('selected');
  h.api.resetDetails();
  assert.equal(h.record.scrolls.length, 1, 'day reset must not scroll back to a stale record');
});

test('desktop drawer selection and close keep document scroll unchanged', () => {
  const h = harness();
  h.api.openDetails('selected');
  h.elements['close-details'].focus();
  h.api.closeDetails();
  assert.deepEqual(h.elements['detail-panel'].scrolls, []);
  assert.deepEqual(h.record.scrolls, []);
});


test('drawer revision changes on visible dismissal so pending selection cannot override a manual close', () => {
  const h = harness();
  assert.equal(h.api.revision, 0);
  h.api.closeDetails();
  assert.equal(h.api.revision, 0, 'closing an already hidden drawer is a no-op');
  h.api.openDetails('selected');
  const pendingSelectionRevision = h.api.revision;
  h.api.closeDetails();
  assert.notEqual(h.api.revision, pendingSelectionRevision);
  assert.equal(h.api.revision, 1);
  h.api.openDetails('selected');
  assert.equal(h.api.revision, 1);
});
