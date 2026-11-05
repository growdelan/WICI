'use strict';
// Real offline app/SQLite and Leaflet. Layout checks use actual element bounds,
// and UI interactions verify that the redesigned controls still reach the data.
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..'), evidence = path.join(root, 'tmp/explorer');
fs.mkdirSync(evidence, {recursive: true});

async function setup() {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const child = spawn(path.join(root, '.venv/bin/python'), ['-u', '-c', `
import tempfile
from pathlib import Path
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-explorer-browser-') as directory:
    uvicorn.run(create_app(demo=True, root=Path(directory), config=Config(port=${port})),
                host='127.0.0.1', port=${port}, log_level='error')
`], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  let logs = '', browser;
  child.stdout.on('data', chunk => logs += chunk); child.stderr.on('data', chunk => logs += chunk);
  const url = `http://127.0.0.1:${port}`, errors = [], external = [];
  try {
    for (let attempt = 0; attempt < 200; attempt++) {
      if (child.exitCode !== null) throw Error(logs);
      try {if ((await fetch(url+'/api/health')).ok) break;} catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1586, height: 992}});
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.stack || error.message));
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== url) {external.push(route.request().url()); return route.abort();}
      return route.continue();
    });
    await page.goto(url);
    await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
    await page.locator('[data-view="analysis"]').click(); await settle(page);
    return {page, errors, external, async close() {
      await browser.close(); const done = once(child, 'exit'); child.kill('SIGTERM'); await done;
    }};
  } catch (error) {if (browser) await browser.close(); child.kill('SIGTERM'); throw error;}
}

async function settle(page) {
  await page.waitForFunction(() => WiciWorkspace.getData() && !WiciWorkspace.getState().loading && !WiciWorkspace.getState().error);
}
async function openFilters(page) {
  const panel = page.locator('#analysis-filter-panel');
  if (!(await panel.evaluate(element => element.open))) await panel.locator(':scope > summary').click();
}
async function closeFilters(page) {
  const panel = page.locator('#analysis-filter-panel');
  if (await panel.evaluate(element => element.open)) await panel.locator(':scope > summary').click();
}
async function hydroOnly(page) {
  await openFilters(page);
  // Activate the desired type before removing the current types: an empty
  // selection is invalid and should never be needed for an ordinary workflow.
  const hydro = page.locator('[data-object-type="hydro_station"]');
  if ((await hydro.getAttribute('aria-pressed')) !== 'true') {await hydro.click(); await settle(page);}
  for (const button of await page.locator('[data-object-type]').all()) {
    if ((await button.getAttribute('data-object-type')) !== 'hydro_station' && (await button.getAttribute('aria-pressed')) === 'true') {
      await button.click(); await settle(page);
    }
  }
  await closeFilters(page);
}

test('Eksplorator: list, map and inspector remain separate; controls retain selection, history and saved views', {timeout: 90000}, async () => {
  const env = await setup(), {page} = env;
  try {
    const originalMap = await page.evaluate(() => state.map._leaflet_id);
    assert.equal(await page.locator('#analysis-filter-panel').evaluate(element => element.open), false);
    assert.equal(await page.locator('.analysis-inspector-empty').isVisible(), true);
    await hydroOnly(page);
    await page.locator('button[data-results-view="table"]').click();
    assert.equal(await page.locator('button[data-results-view="table"]').getAttribute('aria-pressed'), 'true');
    await page.locator('button[data-results-view="list"]').click();
    assert.equal(await page.locator('button[data-results-view="list"]').getAttribute('aria-pressed'), 'true');
    await page.locator('#analysis-table [data-ref="hydro_station:imgw:demo-wisla"] .analysis-object-link').click();
    await page.locator('#analysis-card-title').filter({hasText: 'DEMO: wodowskaz Wisła'}).waitFor();
    assert.match(await page.locator('.analysis-reading').innerText(), /274/);
    const boxes = await page.evaluate(() => {
      const rect = selector => {const box = document.querySelector(selector).getBoundingClientRect(); return {x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height};};
      return {catalog: rect('.analysis-catalog'), map: rect('#situation > .map-panel'), inspector: rect('#analysis-card'), timeline: rect('.analysis-timeline')};
    });
    assert.ok(boxes.catalog.right <= boxes.map.x + 1, 'the results panel does not cover the map');
    assert.ok(boxes.map.right <= boxes.inspector.x + 1, 'the inspector does not cover the map');
    assert.ok(boxes.map.width >= 400, 'the map remains a useful central work surface at desktop width');
    assert.ok(boxes.inspector.width >= 280, 'the inspector remains readable');
    assert.ok(await page.evaluate(() => {const chart = document.querySelector('#analysis-card .analysis-series').getBoundingClientRect(), panel = document.querySelector('#analysis-card-panel-details').getBoundingClientRect(); return chart.bottom <= panel.bottom + 1;}), 'the full station chart is visible without being covered by actions');
    assert.ok(boxes.timeline.y >= Math.max(boxes.catalog.bottom, boxes.map.bottom, boxes.inspector.bottom) - 1, 'the timeline sits below the three panels');
    await page.locator('#analysis-time-preset').selectOption('24h'); await settle(page);
    await page.waitForFunction(() => !document.getElementById('analysis-cursor').disabled);
    await page.locator('#analysis-cursor').evaluate(input => {input.value = '500'; input.dispatchEvent(new Event('input', {bubbles: true}));});
    await page.waitForFunction(() => WiciWorkspace.getState().cursorAt !== null);
    assert.match(await page.locator('#analysis-table [data-ref="hydro_station:imgw:demo-wisla"]').innerText(), /Według kursora/);
    await page.screenshot({path: path.join(evidence, 'explorer-desktop.png'), fullPage: true, animations: 'disabled'});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#analysis-card').isVisible(), false);
    assert.equal(await page.locator('.analysis-inspector-empty').isVisible(), true);
    await page.locator('#analysis-save-view').click();
    await page.locator('#analysis-view-name').fill('Eksplorator — wodowskazy');
    await page.getByRole('button', {name: 'Zapisz nowe', exact: true}).click();
    await page.waitForFunction(() => document.getElementById('analysis-saved-view').options.length === 2);
    await page.keyboard.press('Escape');
    await page.locator('[data-view="situation"]').click();
    await page.locator('#communication-list').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => state.map._leaflet_id), originalMap, 'Atlas and Analysis keep the existing Leaflet instance');
    await page.locator('[data-view="analysis"]').click(); await settle(page);
    assert.equal(await page.locator('button[data-results-view="list"]').getAttribute('aria-pressed'), 'true');
    assert.deepEqual(env.errors, []); assert.deepEqual(env.external, []);
  } catch (error) {
    await page.screenshot({path: path.join(evidence, 'explorer-failure.png'), fullPage: true, animations: 'disabled'});
    console.log('Explorer errors:', env.errors); throw error;
  } finally {await env.close();}
});

test('Eksplorator: responsive panels, search and mobile inspector do not overflow the viewport', {timeout: 90000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await hydroOnly(page);
    await page.locator('#analysis-search').fill('Wisła');
    await page.waitForFunction(() => WiciWorkspace.getState().query.q === 'Wisła' && WiciWorkspace.getData().total === 1 && !WiciWorkspace.getState().loading);
    for (const width of [1920, 1366, 1024, 768, 390, 320]) {
      await page.setViewportSize({width, height: 900});
      if (width < 700) {
        await page.locator('.analysis-mobile-switch [data-panel="map"]').click();
        await page.locator('#map').waitFor({state: 'visible'});
        await page.locator('.analysis-mobile-switch [data-panel="table"]').click();
        await page.locator('#analysis-table').waitFor({state: 'visible'});
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `no horizontal page overflow at ${width}px`);
      await openFilters(page);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `filters fit at ${width}px`);
      await closeFilters(page);
      if (width === 390) {
        await page.locator('#analysis-table .analysis-object-link').click();
        await page.locator('#analysis-card-title').filter({hasText: 'DEMO: wodowskaz Wisła'}).waitFor();
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'mobile inspector fits');
        assert.equal(await page.locator('#analysis-card').getAttribute('aria-modal'), 'true');
        await page.locator('#analysis-close-card').focus(); await page.keyboard.press('Shift+Tab');
        assert.ok(await page.evaluate(() => document.getElementById('analysis-card').contains(document.activeElement)), 'keyboard focus stays inside the mobile inspector');
        assert.equal(await page.evaluate(() => getComputedStyle(document.body).overflow), 'hidden', 'background does not scroll under mobile details');
        await page.screenshot({path: path.join(evidence, 'explorer-mobile.png'), fullPage: true, animations: 'disabled'});
        await page.keyboard.press('Escape');
      }
    }
    assert.deepEqual(env.errors, []); assert.deepEqual(env.external, []);
  } catch (error) {
    await page.screenshot({path: path.join(evidence, 'explorer-responsive-failure.png'), fullPage: true, animations: 'disabled'});
    console.log('Explorer responsive errors:', env.errors); throw error;
  } finally {await env.close();}
});
