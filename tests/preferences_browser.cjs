// Full application + bundled Leaflet regression on an isolated offline demo server.
// NODE_PATH=/path/to/node_modules node --test tests/preferences_browser.cjs
'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn, spawnSync} = require('node:child_process');
const {once} = require('node:events');
const net = require('node:net');
const path = require('node:path');
const {chromium} = require('playwright');
const {setTestTheme} = require('./browser_theme.cjs');
const root = path.resolve(__dirname, '..');
const storageKey = 'wici.ui.checkboxes.v1';

async function server() {
  const socket = net.createServer();
  socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const python = spawnSync('uv', ['run', 'python', '-c', 'import sys; print(sys.executable)'],
    {cwd: root, encoding: 'utf8'});
  assert.equal(python.status, 0, python.stderr);
  const process = spawn(python.stdout.trim(), ['-u', '-c', `
import tempfile
from pathlib import Path
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-preferences-regression-') as root:
    uvicorn.run(create_app(demo=True, root=Path(root), config=Config(port=${port})),
                host='127.0.0.1', port=${port}, log_level='error')
`], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  let logs = '';
  process.stdout.on('data', chunk => logs += chunk);
  process.stderr.on('data', chunk => logs += chunk);
  const url = `http://127.0.0.1:${port}`;
  try {
    for (let i = 0; i < 200; i++) {
      if (process.exitCode !== null) throw new Error(logs);
      try {
        if ((await fetch(url + '/api/health')).ok) return {url, async stop() {
          const exited = once(process, 'exit'); process.kill('SIGTERM'); await exited;
        }};
      } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error('Demo startup timeout: ' + logs);
  } catch (error) { process.kill('SIGTERM'); throw error; }
}

async function setup() {
  const app = await server();
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    await setTestTheme(page);
    const errors = [], external = [], reads = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== app.url) { external.push(url.href); return route.abort(); }
      if (url.pathname.startsWith('/api/')) reads.push(url.pathname + url.search);
      if (url.pathname === '/api/hydro' && url.searchParams.get('kind') === 'stations') {
        const observedAt = new Date().toISOString();
        return route.fulfill({json: {
          enabled: true, status: 'ready', fetched_at: observedAt, stale: false,
          source_url: 'https://danepubliczne.imgw.pl/api/data/hydro/',
          items: [{id: 'preferences-test', name: 'Syntetyczny wodowskaz preferencji',
            river: 'Wisła', province: 'mazowieckie', latitude: 52.2, longitude: 21.1,
            warning_level_cm: 300, alarm_level_cm: 400,
            measurements: {
              water_level: {value: 250, unit: 'cm', observed_at: observedAt},
              discharge: {value: 100, unit: 'm³/s', observed_at: observedAt},
              temperature: {value: 15, unit: '°C', observed_at: observedAt}
            }}]
        }});
      }
      return route.continue();
    });
    await page.goto(app.url);
    await ready(page);
    return {app, browser, page, errors, external, reads, async close() {
      await browser.close(); await app.stop();
    }};
  } catch (error) {
    if (browser) await browser.close();
    await app.stop(); throw error;
  }
}

async function ready(page) {
  await page.waitForFunction(() => typeof state !== 'undefined' && state.map
    && document.getElementById('communication-count').textContent !== 'Wczytywanie…'
    && !document.getElementById('refresh').disabled);
}
async function openControls(page, id) {
  await page.locator(`#${id}`).evaluate(control => {
    for (let node = control.parentElement; node; node = node.parentElement)
      if (node.tagName === 'DETAILS') node.open = true;
  });
}
async function setCheckbox(page, id, checked) {
  await openControls(page, id);
  await page.locator(`#${id}`).setChecked(checked);
}
async function publicationLayers(page) {
  return page.evaluate(() => ({
    areas: state.layers.filter(({layer}) => state.map.hasLayer(layer)).length,
    cards: state.cards.filter(layer => state.map.hasLayer(layer)).length,
    records: document.querySelectorAll('#communication-list [data-communication-id]').length,
    legendHidden: [...document.querySelectorAll('.communications-map-key')].every(el => el.hidden)
  }));
}
async function refreshView(page) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/communications');
  await page.locator('#refresh').click(); await response;
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
}
async function chooseDay(page, selector) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/communications');
  await page.locator(selector).click(); await response;
  await page.waitForFunction(() => document.getElementById('day-note').textContent
    .includes(document.getElementById('selected-day').value));
}
async function selectPublication(page) {
  const selected = await page.evaluate(() => state.communications.find(item =>
    locations(item).some(loc => geometryFor(loc)))?.id);
  assert.ok(selected, 'the demo includes a publication with geometry');
  const record = page.locator(`[data-communication-id="${selected}"]`);
  await record.evaluate(el => {
    for (let parent = el.parentElement; parent; parent = parent.parentElement)
      if (parent.tagName === 'DETAILS') parent.open = true;
  });
  await record.click();
  await page.locator('#detail-panel').waitFor();
  await page.waitForFunction(id => state.selected === id, selected);
  return selected;
}
async function saved(page) {
  return page.evaluate(key => JSON.parse(localStorage.getItem(key)), storageKey);
}

test('publication overlay can stay off through refresh, day changes, selection and IODA', {timeout: 45000}, async () => {
  const h = await setup(), {page} = h;
  try {
    const initial = await publicationLayers(page);
    assert.ok(initial.areas > 0 && initial.cards > 0 && initial.records > 0);
    assert.equal(initial.legendHidden, false);
    assert.equal(await page.locator('#communications-enabled').isChecked(), true);
    await page.evaluate(() => state.cards[0].openPopup());
    assert.equal(await page.locator('.leaflet-popup').count(), 1);
    await setCheckbox(page, 'communications-enabled', false);
    assert.deepEqual(await publicationLayers(page),
      {areas: 0, cards: 0, records: initial.records, legendHidden: true});
    await page.locator('.leaflet-popup').waitFor({state: 'detached'});
    assert.equal(await page.locator('.leaflet-popup').count(), 0);
    await page.screenshot({path: path.join(root, 'tmp/preferences-overlay-off-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 320, height: 900});
    await page.locator('#communications-enabled').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(root, 'tmp/preferences-overlay-off-mobile.png'), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.setViewportSize({width: 1440, height: 1000});
    await refreshView(page);
    assert.deepEqual(await publicationLayers(page),
      {areas: 0, cards: 0, records: initial.records, legendHidden: true});
    await chooseDay(page, '#previous-day');
    assert.equal((await publicationLayers(page)).areas, 0);
    assert.equal((await publicationLayers(page)).cards, 0);
    await chooseDay(page, '#today');
    assert.deepEqual(await publicationLayers(page),
      {areas: 0, cards: 0, records: initial.records, legendHidden: true});
    await page.evaluate(() => {
      window.preferenceFitCalls = 0;
      const original = state.map.fitBounds;
      state.map.fitBounds = function (...args) {
        window.preferenceFitCalls++; return original.apply(this, args);
      };
    });
    await selectPublication(page);
    assert.equal(await page.evaluate(() => window.preferenceFitCalls), 0);
    assert.equal(await page.locator('#communications-enabled').isChecked(), false);
    assert.equal((await publicationLayers(page)).areas, 0);
    await page.locator('#close-details').click();
    await setCheckbox(page, 'communications-enabled', true);
    assert.deepEqual(await publicationLayers(page), initial);

    await setCheckbox(page, 'ioda-enabled', true);
    await page.locator('#ioda-list > details').first().waitFor();
    assert.equal((await publicationLayers(page)).areas, 0);
    await setCheckbox(page, 'ioda-communications', true);
    assert.deepEqual(await publicationLayers(page), initial);
    await setCheckbox(page, 'communications-enabled', false);
    assert.equal((await publicationLayers(page)).areas, 0);
    assert.equal(await page.locator('#ioda-communications').isChecked(), true);
    await selectPublication(page);
    assert.equal(await page.locator('#communications-enabled').isChecked(), false);
    assert.equal((await publicationLayers(page)).areas, 0);
    await page.locator('#close-details').click();
    await setCheckbox(page, 'ioda-enabled', false);
    assert.equal((await publicationLayers(page)).areas, 0);
    await setCheckbox(page, 'communications-enabled', true);
    assert.deepEqual(await publicationLayers(page), initial);
    assert.deepEqual(h.errors, []); assert.deepEqual(h.external, []);
  } finally { await h.close(); }
});

test('checkbox preferences restore before startup and activate the saved data layers', {timeout: 45000}, async () => {
  const h = await setup(), {page} = h;
  try {
    await setCheckbox(page, 'communications-enabled', false);
    await setCheckbox(page, 'include-active', false);
    await setCheckbox(page, 'hydro-stations', true);
    await setCheckbox(page, 'weather-animation', true);
    await setCheckbox(page, 's2-enabled', true);
    await setCheckbox(page, 's2-full-only', false);
    await setCheckbox(page, 's2-quality', true);
    await page.waitForFunction(() => state.map.getPane('hydroStations')?.querySelector('path'));
    const choices = await page.locator('input[type=checkbox][id]').evaluateAll(controls =>
      Object.fromEntries(controls.map(control => [control.id, control.checked])));
    const stored = await saved(page);
    for (const id of ['communications-enabled', 'include-active', 'hydro-stations',
      'weather-animation', 's2-enabled', 's2-full-only', 's2-quality'])
      assert.equal(stored[id], choices[id], id);
    const stationReads = h.reads.filter(url => url.startsWith('/api/hydro?') && url.includes('kind=stations')).length;
    await page.reload(); await ready(page);
    await page.waitForFunction(() => state.map.getPane('hydroStations')?.querySelector('path'));
    const restored = await page.locator('input[type=checkbox][id]').evaluateAll(controls =>
      Object.fromEntries(controls.map(control => [control.id, control.checked])));
    assert.deepEqual(restored, choices);
    assert.ok(h.reads.filter(url => url.startsWith('/api/hydro?') && url.includes('kind=stations')).length > stationReads);
    assert.equal((await publicationLayers(page)).areas, 0);
    assert.equal((await publicationLayers(page)).cards, 0);
    assert.equal((await publicationLayers(page)).legendHidden, true);
    assert.ok(h.reads.filter(url => url.startsWith('/api/communications?')).at(-1).includes('date='));
    assert.ok(!h.reads.filter(url => url.startsWith('/api/communications?')).at(-1).includes('include_active'));

    // Programmatic checkbox changes caused by ordinary UI buttons must persist too.
    await openControls(page, 'weather-play'); await page.locator('#weather-play').click();
    assert.equal(await page.locator('#weather-wind').isChecked(), true);
    assert.equal((await saved(page))['weather-wind'], true);
    await openControls(page, 'radar-play'); await page.locator('#radar-play').click();
    assert.equal(await page.locator('#radar-enabled').isChecked(), true);
    assert.equal((await saved(page))['radar-enabled'], true);
    await page.reload(); await ready(page);
    assert.equal(await page.locator('#weather-wind').isChecked(), true);
    assert.equal(await page.locator('#radar-enabled').isChecked(), true);
    assert.deepEqual(h.errors, []); assert.deepEqual(h.external, []);
  } finally { await h.close(); }
});

test('today-only publication preference survives archive navigation without storing its disabled state', {timeout: 45000}, async () => {
  const h = await setup(), {page} = h;
  try {
    // In demo the default is on. Exercise both explicit choices.
    for (const value of [false, true]) {
      await setCheckbox(page, 'include-active', value);
      assert.equal((await saved(page))['include-active'], value);
      await chooseDay(page, '#previous-day');
      assert.equal(await page.locator('#include-active').isDisabled(), true);
      assert.equal(await page.locator('#include-active').isChecked(), false);
      assert.equal((await saved(page))['include-active'], value);
      await refreshView(page);
      assert.equal((await saved(page))['include-active'], value);
      await chooseDay(page, '#today');
      assert.equal(await page.locator('#include-active').isDisabled(), false);
      assert.equal(await page.locator('#include-active').isChecked(), value);
      await page.reload(); await ready(page);
      assert.equal(await page.locator('#include-active').isChecked(), value);
    }
    assert.deepEqual(h.errors, []); assert.deepEqual(h.external, []);
  } finally { await h.close(); }
});
