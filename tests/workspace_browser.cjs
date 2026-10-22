'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');

async function setup({blockedStorage = false} = {}) {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const process = spawn(path.join(root, '.venv/bin/python'), ['-u', '-c', `
import tempfile
from pathlib import Path
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-analysis-browser-') as directory:
    uvicorn.run(create_app(demo=True,root=Path(directory),config=Config(port=${port})),
                host='127.0.0.1',port=${port},log_level='error')
`], {cwd:root, stdio:['ignore', 'pipe', 'pipe']});
  let logs = ''; process.stdout.on('data', chunk => logs += chunk); process.stderr.on('data', chunk => logs += chunk);
  const url = `http://127.0.0.1:${port}`;
  let browser;
  try {
    for (let i = 0; i < 200; i++) {
      if (process.exitCode !== null) throw new Error(logs);
      try { if ((await fetch(url+'/api/health')).ok) break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:1366, height:1000}}), errors = [], upstream = [], reads = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      reads.push(new URL(route.request().url()).pathname);
      if (new URL(route.request().url()).origin !== url) {upstream.push(route.request().url()); return route.abort();}
      return route.continue();
    });
    if (blockedStorage) await page.addInitScript(() => {
      Storage.prototype.getItem = Storage.prototype.setItem = function () {throw new DOMException('Blocked', 'SecurityError');};
    });
    await page.goto(url);
    await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
    await page.locator('[data-view="analysis"]').click();
    await page.waitForFunction(() => window.WiciWorkspace?.getData()?.total > 0 && !window.WiciWorkspace.getState().loading);
    return {page, errors, upstream, reads, url, async close() {await browser.close(); const done = once(process, 'exit'); process.kill('SIGTERM'); await done;}};
  } catch (error) {if (browser) await browser.close(); process.kill('SIGTERM'); throw error;}
}

async function settle(page) {
  await page.waitForFunction(() => !window.WiciWorkspace.getState().loading && !window.WiciWorkspace.getState().error);
}

test('Analiza: a filter click preserves a pending search and restoring a view cancels it', {timeout:60000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await page.locator('.analysis-saved-views summary').click();
    await page.locator('#analysis-view-name').fill('Wszystkie komunikaty');
    await page.getByRole('button', {name:'Zapisz nowe', exact:true}).click();
    await page.waitForFunction(() => document.getElementById('analysis-saved-view').options.length === 2);
    // Dispatch both real input/click events in one turn, within the debounce window.
    await page.locator('#analysis-search').focus();
    await page.evaluate(() => {
      const search = document.getElementById('analysis-search');
      search.value = 'Wisła'; search.dispatchEvent(new Event('input', {bubbles:true}));
      const filter = document.querySelector('[data-object-type="hydro_station"]');
      filter.focus(); filter.click();
    });
    await page.waitForFunction(() => WiciWorkspace.getState().query.q === 'Wisła' && !WiciWorkspace.getState().loading);
    assert.equal(await page.locator('#analysis-search').inputValue(), 'Wisła');
    assert.equal(await page.locator('#analysis-table tbody tr').count(), 1);
    await page.evaluate(() => {
      const search = document.getElementById('analysis-search');
      search.value = 'Nieistniejący'; search.dispatchEvent(new Event('input', {bubbles:true}));
      const open = [...document.querySelectorAll('.analysis-saved-views button')].find(button => button.textContent === 'Otwórz');
      open.focus(); open.click();
    });
    await page.waitForTimeout(400);
    await settle(page);
    assert.equal(await page.locator('#analysis-search').inputValue(), '');
    assert.equal(await page.evaluate(() => WiciWorkspace.getState().query.q), '');
    assert.deepEqual(env.errors, []);
  } finally {await env.close();}
});

test('Analiza: shared selection, cursor, persistence, responsive themes and Atlas return', {timeout:120000}, async () => {
  const env = await setup(), {page} = env;
  try {
    assert.equal(await page.locator('#analysis-table tbody tr').count(), 2);
    const originalMap = await page.evaluate(() => state.map._leaflet_id);
    await page.locator('[data-object-type="hydro_station"]').click(); await settle(page);
    await page.locator('[data-object-type="communication"]').click(); await settle(page);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 2);
    await page.locator('[data-ref="hydro_station:imgw:demo-wisla"] .analysis-object-link').click();
    await page.locator('#analysis-card-title').filter({hasText:'DEMO: wodowskaz Wisła'}).waitFor();
    assert.match(await page.locator('.analysis-reading').innerText(), /274/);
    await page.getByRole('button', {name:'Ostatnie 24 godziny', exact:true}).click(); await settle(page);
    await page.waitForFunction(() => !document.getElementById('analysis-cursor').disabled);
    await page.locator('#analysis-cursor').evaluate(input => {input.value = '500'; input.dispatchEvent(new Event('input', {bubbles:true}));});
    await page.waitForFunction(() => WiciWorkspace.getState().cursorAt !== null);
    assert.match(await page.locator('[data-ref="hydro_station:imgw:demo-wisla"]').innerText(), /Według kursora/);
    const before = await page.evaluate(() => ({time:WiciWorkspace.getState().query.time, cursor:WiciWorkspace.getState().cursorAt, map:state.map.getCenter()}));
    await page.locator('#analysis-refresh').click(); await settle(page);
    assert.deepEqual(await page.evaluate(() => ({time:WiciWorkspace.getState().query.time, cursor:WiciWorkspace.getState().cursorAt, map:state.map.getCenter()})), before);
    await page.keyboard.press('Escape'); await page.locator('#analysis-card').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('analysis-object-link')), true);
    await page.locator('.analysis-saved-views summary').click();
    await page.locator('#analysis-view-name').fill('Wisła — próba stanowiska');
    await page.getByRole('button', {name:'Zapisz nowe', exact:true}).click();
    await page.waitForFunction(() => document.getElementById('analysis-saved-view').options.length === 2);
    await page.locator('#analysis-search').fill('nieistniejąca-stacja');
    await page.waitForFunction(() => WiciWorkspace.getData().total === 0);
    await page.getByRole('button', {name:'Otwórz', exact:true}).click();
    await page.waitForFunction(() => WiciWorkspace.getData().total === 2);
    await page.locator('.analysis-saved-views summary').click();
    for (const width of [320, 390, 768, 1366, 1920]) {
      await page.setViewportSize({width, height:1000});
      if (width < 700) {
        await page.locator('.analysis-mobile-switch [data-panel="map"]').click();
        await page.locator('#map').waitFor({state:'visible'});
        await page.locator('.analysis-mobile-switch [data-panel="table"]').click();
        await page.locator('#analysis-table').waitFor({state:'visible'});
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `no horizontal document overflow at ${width}`);
      if (width === 1366) await page.screenshot({path:'/tmp/wici-analysis-light.png', fullPage:true, animations:'disabled'});
    }
    await page.locator('#theme-toggle').click(); await page.screenshot({path:'/tmp/wici-analysis-dark.png', fullPage:true, animations:'disabled'});
    await page.locator('[data-view="situation"]').click();
    await page.locator('#communication-list').waitFor({state:'visible'});
    assert.equal(await page.evaluate(() => state.map._leaflet_id), originalMap);
    await page.locator('[data-view="analysis"]').click(); await settle(page);
    assert.equal(await page.locator('#analysis-search').inputValue(), '');
    assert.deepEqual(env.errors, []); assert.deepEqual(env.upstream, []);
  } catch (error) {
    await page.screenshot({path:'/tmp/wici-analysis-failure.png', fullPage:true, animations:'disabled'});
    console.log({errors:env.errors, state:await page.evaluate(() => WiciWorkspace.getState())});
    console.log(await page.evaluate(() => [...document.querySelectorAll('.analysis-timeline,.map-panel,#map,.workspace')].map(el=>({class:el.className, rect:el.getBoundingClientRect().toJSON()}))));
    throw error;
  } finally {await env.close();}
});

test('Analiza: real map selection, GIOS sensor identity, local cursor and blocked storage', {timeout:90000}, async () => {
  const env = await setup({blockedStorage:true}), {page} = env;
  try {
    await page.locator('[data-object-type="air_quality_station"]').click();
    await page.locator('[data-object-type="communication"]').click();
    await page.waitForFunction(() => WiciWorkspace.getData().total === 1);
    await page.evaluate(() => {
      const target = [];
      state.map.eachLayer(layer => {if (layer instanceof L.CircleMarker && layer.getTooltip()?.getContent()?.textContent.includes('DEMO: jakość powietrza')) target.push(layer);});
      if (target.length !== 1) throw new Error(`Expected one catalogue station, got ${target.length}`);
      target[0].fire('click');
    });
    await page.locator('#analysis-card-title').filter({hasText:'DEMO: jakość powietrza'}).waitFor();
    assert.equal(await page.locator('#analysis-sensor option').count(), 3);
    await page.locator('#analysis-sensor').selectOption('9000012');
    await page.waitForFunction(() => document.querySelector('.analysis-reading')?.textContent.includes('26'));
    await page.getByRole('button', {name:'Ostatnie 24 godziny', exact:true}).click(); await settle(page);
    await page.waitForFunction(() => !document.getElementById('analysis-cursor').disabled);
    const sourceReads = () => env.reads.filter(path => ['/api/hydro','/api/gios'].includes(path)).length;
    const before = sourceReads();
    const timings = await page.evaluate(async () => {
      const input = document.getElementById('analysis-cursor'), times = [];
      for (let i = 0; i < 20; i++) {
        const start = performance.now(); input.value = String(i*50);
        input.dispatchEvent(new Event('input', {bubbles:true}));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        times.push(performance.now()-start);
      }
      return times;
    });
    assert.equal(sourceReads(), before, 'moving the cursor never fetches upstream sources');
    assert.equal(await page.locator('#analysis-sensor').inputValue(), '9000012');
    assert.match(await page.locator('[data-ref="air_quality_station:gios:9000001"]').innerText(), /Według kursora/);
    console.log('Local cursor p95 ms:', timings.sort((a,b) => a-b)[18].toFixed(2));
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#analysis-card').isVisible(), false);
    assert.deepEqual(env.errors, []); assert.deepEqual(env.upstream, []);
  } finally {await env.close();}
});
