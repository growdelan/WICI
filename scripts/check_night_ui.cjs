// Real Chromium regression. Starts an isolated, network-forbidden DEMO unless WICI_UI_URL is set.
// NODE_PATH=/path/to/node_modules node scripts/check_night_ui.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), net = require('node:net');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.WICI_SCREENSHOT_DIR || path.join(root, 'tmp/wici-night-evidence'));
const themeKey = 'wici.ui.theme.v1';
const viewports = [320, 390, 768, 1024, 1366, 1440, 1920];
fs.mkdirSync(output, {recursive: true});

async function server() {
  if (process.env.WICI_UI_URL) return {url: process.env.WICI_UI_URL, stop: async () => {}};
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const child = spawn(path.join(root, '.venv/bin/python'), ['-u', '-c', `
import tempfile
from pathlib import Path
import httpx, uvicorn
from wici.app import create_app
from wici.config import Config
def forbidden(request):
    raise AssertionError('External network forbidden: '+str(request.url))
with tempfile.TemporaryDirectory(prefix='wici-night-browser-') as directory:
    client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    app=create_app(demo=True,root=Path(directory),config=Config(port=${port}),client=client)
    uvicorn.run(app,host='127.0.0.1',port=${port},log_level='error')
`], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  let logs = ''; child.stdout.on('data', b => logs += b); child.stderr.on('data', b => logs += b);
  const url = `http://127.0.0.1:${port}`;
  try {
    for (let i = 0; i < 200; i++) {
      if (child.exitCode !== null) throw new Error(logs);
      try { if ((await fetch(url + '/api/health')).ok) return {url, async stop() {
        const ended = once(child, 'exit'); child.kill('SIGTERM'); await ended;
      }}; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error('DEMO startup timed out: ' + logs);
  } catch (error) { child.kill('SIGTERM'); throw error; }
}

// Uses computed RGBA values and composites transparent surfaces through all ancestors.
// Gradients/images and source-colour symbols are recorded separately for visual review;
// inactive controls are exempt under WCAG. Text on severity badges is still measured.
async function contrastInventory(page, screen) {
  return page.evaluate(screenName => {
    const rgba = value => {
      const parts = value.match(/[\d.]+/g)?.map(Number);
      return parts?.length >= 3 ? [...parts.slice(0, 3), parts[3] ?? 1] : [0, 0, 0, 0];
    };
    const over = (front, back) => {
      const alpha = front[3] + back[3] * (1 - front[3]);
      return [...front.slice(0, 3).map((v, i) => alpha ? (v * front[3] + back[i] * back[3] * (1 - front[3])) / alpha : 0), alpha];
    };
    const luminance = color => color.slice(0, 3).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
      .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
    const samples = [], review = [], seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode, text = node.textContent.trim(), element = node.parentElement;
      if (!text || !element || element.closest('script,style,svg,option,[hidden]')) continue;
      const style = getComputedStyle(element), rect = document.createRange(); rect.selectNodeContents(node);
      const boxes = [...rect.getClientRects()].filter(b => b.width && b.height && b.bottom > 0 && b.top < innerHeight && b.right > 0 && b.left < innerWidth);
      if (!boxes.length || style.visibility !== 'visible' || element.closest(':disabled,[aria-disabled="true"]')) continue;
      const box = boxes[0], x = Math.max(0, Math.min(innerWidth - 1, box.x + box.width / 2)), y = Math.max(0, Math.min(innerHeight - 1, box.y + box.height / 2));
      const top = document.elementFromPoint(x, y);
      if (top && !element.contains(top) && !top.contains(element)) continue; // Covered by a drawer or floating controls.
      const ancestors = []; let current = element, opacity = 1, image = false;
      while (current) {
        const computed = getComputedStyle(current); ancestors.push(computed);
        opacity *= Number(computed.opacity); image ||= computed.backgroundImage !== 'none'; current = current.parentElement;
      }
      if (!opacity) continue;
      let background = [255, 255, 255, 1];
      for (const computed of ancestors.reverse()) background = over(rgba(computed.backgroundColor), background);
      const foreground = rgba(style.color); foreground[3] *= opacity;
      const painted = over(foreground, background), a = luminance(painted), b = luminance(background);
      const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      const size = parseFloat(style.fontSize), large = size >= 24 || size >= 18.66 && Number(style.fontWeight) >= 700;
      const selector = element.id ? '#' + element.id : element.tagName.toLowerCase() + (element.className && typeof element.className === 'string' ? '.' + element.className.trim().split(/\s+/).join('.') : '');
      const sample = {screen: screenName, selector, text: text.slice(0, 120), foreground: style.color, background: background.map(v => Math.round(v * 100) / 100), fontSize: size, ratio: Math.round(ratio * 100) / 100, required: large ? 3 : 4.5};
      const key = [selector, sample.foreground, sample.background, sample.required].join('|');
      if (seen.has(key)) continue; seen.add(key);
      if (image) review.push({...sample, reason: 'Background image/gradient requires visual inspection.'}); else samples.push(sample);
    }
    return {samples, failures: samples.filter(sample => sample.ratio + .02 < sample.required), review};
  }, screen);
}

(async () => {
  const app = await server(), base = new URL(app.url);
  assert.equal(base.hostname, '127.0.0.1', 'Only a loopback DEMO is allowed.');
  let browser;
  const allErrors = [], allExternal = [], inventories = [], evidence = [];
  try {
    browser = await chromium.launch({headless: true});
    assert.equal((await (await fetch(new URL('/api/health', base))).json()).mode, 'demo', 'Never run against LIVE.');
    async function context(options = {}) {
      const value = await browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'pl-PL', colorScheme: 'dark', ...options});
      await value.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== base.origin) {allExternal.push(url.href); return route.abort();}
        return route.continue();
      });
      value.on('page', page => page.on('pageerror', error => allErrors.push(error.message)));
      return value;
    }
    async function ready(page) {
      await page.locator('.province-card').first().waitFor();
      await page.locator('#source-list .source-card').first().waitFor({state: 'attached'});
      await page.waitForFunction(() => state.map && !state.map._animatingZoom && !document.getElementById('refresh').disabled);
    }
    async function shot(page, name) {
      const filename = name + '.png';
      await page.screenshot({path: path.join(output, filename), fullPage: true}); evidence.push(filename);
    }
    async function theme(page, wanted, key) {
      if (await page.locator('html').getAttribute('data-theme') !== wanted) {
        await page.locator('#theme-toggle').focus();
        await page.keyboard.press(key || 'Enter');
        await page.waitForTimeout(180); // Sample the final painted theme, after UI surface transitions.
      }
      assert.equal(await page.locator('html').getAttribute('data-theme'), wanted);
      assert.equal(await page.locator('#theme-toggle').getAttribute('aria-pressed'), String(wanted === 'dark'));
      assert.ok(await page.locator('#theme-toggle').getAttribute('aria-label'), 'Theme button has an accessible name.');
      assert.equal(await page.locator('html').evaluate(element => getComputedStyle(element).colorScheme.includes(element.dataset.theme)), true);
    }
    const main = await context(), page = await main.newPage();
    const requests = [];
    page.on('request', request => {if (new URL(request.url()).pathname.startsWith('/api/')) requests.push(request.url());});
    await page.goto(base.href); await ready(page);
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light', 'First run stays Atlas despite OS dark mode.');
    assert.equal(await page.locator('.layer-group[open]').count(), 0);
    const layerCount = await page.locator('.layer-group').count(); assert.equal(layerCount, 13);
    await shot(page, 'light-desktop');
    inventories.push(await contrastInventory(page, 'light-desktop'));
    await theme(page, 'dark', 'Enter');
    assert.equal(await page.evaluate(key => localStorage.getItem(key), themeKey), 'dark');
    await page.reload(); await ready(page);
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark', 'Reload retains the saved night preference.');
    // At stylesheet delivery the bootstrap must already have applied the saved preference.
    let earlyTheme;
    await page.route('**/static/css/app.css', async route => {
      // Chromium's speculative loader may request CSS before the parser reaches
      // the blocking bootstrap. Hold stylesheet delivery, not its request time.
      await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark', null, {timeout: 3000});
      earlyTheme = await page.evaluate(() => document.documentElement.dataset.theme);
      await route.continue();
    });
    await page.reload(); await ready(page);
    assert.equal(earlyTheme, 'dark', 'Saved dark theme is applied before the first app stylesheet is delivered.');
    await page.unroute('**/static/css/app.css');
    await shot(page, 'dark-desktop'); inventories.push(await contrastInventory(page, 'dark-desktop'));

    // Keyboard focus must be visible, and reduced motion must suppress decorative transitions.
    await page.locator('#theme-toggle').focus();
    assert.equal(await page.locator('#theme-toggle').evaluate(element => element.matches(':focus-visible') && (getComputedStyle(element).outlineStyle !== 'none' || getComputedStyle(element).boxShadow !== 'none')), true);
    await page.emulateMedia({reducedMotion: 'reduce'});
    assert.equal(await page.locator('#theme-toggle').evaluate(element => getComputedStyle(element).transitionDuration.split(',').every(v => parseFloat(v) <= .01)), true);

    await page.locator('.filter-options > summary').click();
    await Promise.all([page.waitForResponse(r => r.url().includes('/api/communications?')), page.locator('[name="category"]').selectOption('weather')]);
    await Promise.all([page.waitForResponse(r => r.url().includes('/api/communications?')), page.locator('#province').selectOption('14')]);
    await Promise.all([page.waitForResponse(r => r.url().includes('/api/communications?')), page.locator('[name="communication_type"]').selectOption('warning')]);
    await page.locator('.record:visible').first().click();
    await page.locator('#detail-panel:not([hidden])').waitFor();
    await page.locator('#details .detail-section details > summary').first().click();
    assert.equal(await page.getByRole('link', {name: 'Oryginał tej wersji', exact: true}).first().isVisible(), true);
    await page.locator('#layer-panel > summary').click();
    const activeCount = async () => Number((await page.locator('#layer-selection').textContent()).match(/\d+/)[0]);
    const initialActiveCount = await activeCount();
    const checkboxes = await page.locator('#layer-panel input[type=checkbox]').evaluateAll(elements => elements.map(e => [e.id, e.checked]));
    const beforeOpen = requests.length;
    for (const summary of await page.locator('.layer-group > summary').all()) await summary.click();
    assert.deepEqual(await page.locator('#layer-panel input[type=checkbox]').evaluateAll(elements => elements.map(e => [e.id, e.checked])), checkboxes, 'Opening groups does not activate data.');
    assert.equal(requests.length, beforeOpen, 'Opening groups makes no API requests.');
    await page.locator('#weather-wind').check();
    await page.locator('.weather-arrow').first().waitFor({state: 'attached'});
    await page.locator('#weather-rain').check();
    assert.equal(await activeCount(), initialActiveCount + 2, 'Wind and point precipitation are two user layers.');
    const beforeHelper = await activeCount();
    await page.locator('#weather-animation').check();
    assert.equal(await activeCount(), beforeHelper, 'Wind animation is a helper, not another active layer.');
    await page.locator('#weather-animation').uncheck();
    assert.equal(await page.locator('#osm-enabled').isDisabled(), true, 'DEMO never enables the network basemap.');
    assert.equal(await page.locator('#effis-enabled').isDisabled(), true, 'Unconfigured source remains explicitly unavailable.');
    await page.locator('#weather-mode').selectOption('forecast');
    await page.waitForFunction(() => !document.getElementById('weather-hour').disabled);
    await page.locator('#weather-hour').focus(); await page.keyboard.press('ArrowRight');
    await page.locator('#radar-opacity').focus(); await page.keyboard.press('ArrowLeft');
    // Real existing publication popup, not a replacement mock.
    await page.evaluate(() => {state.map.setView([52, 19], 6, {animate: false}); state.cards[0].openPopup();});
    await page.locator('.leaflet-popup').waitFor();
    await page.waitForTimeout(150); // Finish layout invalidation before taking the invariant snapshot.
    await page.evaluate(() => {window.__nightMap = state.map; window.__nightLayers = {...state.map._layers}; window.__nightPopup = state.map._popup;});
    const snapshot = () => page.evaluate(() => ({
      controls: [...document.querySelectorAll('input,select')].map(e => [e.id || e.name, e.value, e.checked, e.disabled]),
      selected: state.selected, day: state.day, view: state.view,
      center: [state.map.getCenter().lat, state.map.getCenter().lng], zoom: state.map.getZoom(),
      details: document.getElementById('details').innerHTML,
      history: [...document.querySelectorAll('#details details')].map(e => e.open),
      groups: [...document.querySelectorAll('#layer-panel, .layer-group')].map(e => e.open)
    }));
    const saved = await snapshot(), noSwitchRequests = requests.length;
    for (const selected of ['light', 'dark']) {
      await theme(page, selected, 'Space');
      assert.deepEqual(await snapshot(), saved, 'Theme preserves controls, filters, date, history, details, map center and zoom.');
      assert.equal(await page.evaluate(() => state.map === window.__nightMap && state.map._popup === window.__nightPopup && Object.keys(state.map._layers).length === Object.keys(window.__nightLayers).length && Object.entries(window.__nightLayers).every(([id, layer]) => state.map._layers[id] === layer)), true, 'Map, data layers and open popup retain object identity.');
    }
    assert.equal(requests.length, noSwitchRequests, 'Switching theme must never request /api.');
    assert.match(await page.locator('#layer-selection').textContent(), /\d+ aktywn/);
    await shot(page, 'dark-layers-details-popup'); inventories.push(await contrastInventory(page, 'dark-layers-details-popup'));
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#layer-panel').getAttribute('open'), null);
    await page.locator('#details .detail-section details > summary').first().focus();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#detail-panel').isHidden(), true);
    assert.equal(await page.locator('.record[aria-pressed="true"]').evaluate(e => e === document.activeElement), true);
    await page.evaluate(() => state.map.closePopup());
    await page.locator('.map-legend > summary').click();
    await shot(page, 'dark-map-legend'); inventories.push(await contrastInventory(page, 'dark-map-legend'));
    await page.locator('.map-legend > summary').click();
    for (const selected of ['light', 'dark']) {
      await theme(page, selected);
      await page.locator('.tab[data-view="sources"]').click();
      assert.equal(await page.locator('#theme-toggle').isVisible(), true);
      assert.equal(await page.locator('#sources').isVisible(), true);
      await shot(page, selected + '-sources'); inventories.push(await contrastInventory(page, selected + '-sources'));
      await page.locator('.tab[data-view="situation"]').click();
      assert.equal(await page.locator('html').getAttribute('data-theme'), selected);
    }

    // All seven required widths plus a 600 px short window, in both themes.
    // Reload each case to verify the default collapsed state and avoid previous scroll position.
    for (const selected of ['light', 'dark']) for (const width of viewports) {
      await theme(page, selected);
      await page.setViewportSize({width, height: 600}); await page.reload(); await ready(page);
      await page.evaluate(() => window.scrollTo(0, 0));
      assert.equal(await page.locator('.layer-group[open]').count(), 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${selected} document overflow at ${width}×600`);
      const toggle = await page.locator('#theme-toggle').boundingBox();
      assert.ok(toggle.x >= 0 && toggle.x + toggle.width <= width && toggle.y >= 0 && toggle.y + toggle.height <= 600, `Theme control completely reachable at ${selected} ${width}: ${JSON.stringify(toggle)}`);
      await page.locator('#layer-panel > summary').click();
      await page.locator('.layer-group').evaluateAll(groups => groups.forEach(group => group.open = true));
      const panel = page.locator('.layer-panel-body');
      assert.equal(await panel.evaluate(e => e.scrollHeight > e.clientHeight && ['auto', 'scroll'].includes(getComputedStyle(e).overflowY)), true, 'All expanded groups require bounded internal scrolling.');
      await page.locator('.layer-group').last().locator(':scope > summary').scrollIntoViewIfNeeded();
      assert.equal(await page.locator('.layer-group').last().locator(':scope > summary').evaluate(e => {
        const group = e.getBoundingClientRect(), body = document.querySelector('.layer-panel-body').getBoundingClientRect();
        return group.top >= body.top - 2 && group.bottom <= body.bottom + 2;
      }), true, 'Last layer group is reachable by scrolling inside the panel.');
      assert.equal(await page.locator('#layer-panel').evaluate(e => {
        const panel = e.getBoundingClientRect(), body = e.querySelector('.layer-panel-body').getBoundingClientRect(), map = document.querySelector('.map-panel').getBoundingClientRect();
        return body.bottom <= panel.bottom + 2 && panel.bottom <= map.bottom + 2;
      }), true, 'Expanded controls cannot spill outside the map/panel.');
      await page.keyboard.press('Escape');
      await page.locator('.record:visible').first().click(); await page.locator('#detail-panel:not([hidden])').waitFor();
      await page.locator('#close-details').scrollIntoViewIfNeeded();
      const close = await page.locator('#close-details').boundingBox();
      assert.ok(close.x >= 0 && close.x + close.width <= width && close.y >= 0 && close.y + close.height <= 600, `Close details reachable at ${width}`);
      await page.locator('#close-details').click();
      assert.equal(await page.locator('.record[aria-pressed="true"]').evaluate(e => e === document.activeElement), true);
      await shot(page, `${selected}-${width}-short`);
      await page.locator('.map-legend > summary').click();
      if (width <= 1100) assert.equal(await page.locator('.map-legend').evaluate(e => {
        const legend = e.getBoundingClientRect(), attribution = document.querySelector('.leaflet-control-attribution').getBoundingClientRect();
        return legend.bottom <= attribution.top + 2;
      }), true, `Open legend leaves attribution readable at ${selected} ${width}`);
      if (width === 390 || width === 768) {
        await shot(page, `${selected}-${width}-legend`);
        inventories.push(await contrastInventory(page, `${selected}-${width}-legend`));
      }
      await page.locator('.map-legend > summary').click();
    }

    // Reload persists both values. Corrupt and unavailable storage fail gracefully.
    await theme(page, 'light'); await page.reload(); await ready(page); await theme(page, 'light');
    for (const stored of ['invalid', null, 'blocked', 'quota']) {
      const isolated = await context();
      await isolated.addInitScript(({key, value}) => {
        if (location.origin === 'null') return; // New pages begin at an opaque about:blank origin.
        if (value === 'blocked') Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('Blocked by test', 'SecurityError');}});
        else if (value === 'quota') Storage.prototype.setItem = () => {throw new DOMException('Quota blocked by test', 'QuotaExceededError');};
        else if (value !== null) localStorage.setItem(key, value);
      }, {key: themeKey, value: stored});
      const check = await isolated.newPage(); await check.goto(base.href); await ready(check);
      assert.equal(await check.locator('html').getAttribute('data-theme'), 'light', `Safe default with ${stored} storage`);
      await theme(check, 'dark'); await theme(check, 'light');
      await isolated.close();
    }

    // A local synthetic road tile exercises the actual Leaflet osmBase pane. It does
    // not claim that real OSM city/road names have been visually validated offline.
    await page.setViewportSize({width: 1440, height: 1000}); await page.reload(); await ready(page);
    // Pixel comparison needs the complete synthetic raster inside the saved spatial scope.
    await page.locator('#province').selectOption('');
    const tile = '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9e9df"/><path d="M0 120L256 155M95 0L130 256" stroke="#fff" stroke-width="12"/><path d="M0 120L256 155" stroke="#e8c369" stroke-width="5"/><text x="20" y="90" fill="#333" font-size="17">SYNTHETIC TILE</text><text x="145" y="180" fill="#666" font-size="13">road 12</text></svg>';
    await page.route('**/__night_tile/**', route => route.fulfill({contentType: 'image/svg+xml', body: tile}));
    await page.evaluate(() => {
      window.__nightTiles = L.tileLayer('/__night_tile/{z}/{x}/{y}.svg', {pane: 'osmBase', noWrap: true}).addTo(state.map);
      state.administrativeLayer.setStyle({fillOpacity: 0});
      // Opaque PNG avoids SVG path-edge antialiasing against the changing base.
      const canvas = document.createElement('canvas'); canvas.width = 240; canvas.height = 48;
      const context = canvas.getContext('2d');
      ['#ffcc00', '#ed7b21', '#c43131', '#168bc4'].forEach((color, index) => {context.fillStyle = color; context.fillRect(index * 60, 0, 60, 48);});
      window.__nightRaster = L.imageOverlay(canvas.toDataURL('image/png'), [[51.8, 17.8], [52.2, 20.2]], {pane: 'overlayPane', interactive: true}).addTo(state.map);
    });
    await page.locator('.leaflet-osmBase-pane .leaflet-tile-loaded').first().waitFor();
    // Publication cards and DEMO labels sit above rasters and change their own
    // chrome by design. Hide occluding panes only while sampling source pixels.
    await page.evaluate(() => {
      window.__nightOccluders = [...document.querySelectorAll('.leaflet-pane')].filter(e => !e.matches('.leaflet-map-pane,.leaflet-osmBase-pane,.leaflet-overlay-pane')).map(e => [e, e.style.visibility]);
      for (const [e] of window.__nightOccluders) e.style.visibility = 'hidden';
    });
    await theme(page, 'light');
    const raster = page.locator('.leaflet-overlay-pane > img').last(), lightRaster = await raster.screenshot();
    fs.writeFileSync(path.join(output, 'source-raster-light.png'), lightRaster);
    await theme(page, 'dark');
    const darkRaster = await raster.screenshot(); fs.writeFileSync(path.join(output, 'source-raster-dark.png'), darkRaster);
    assert.ok(darkRaster.equals(lightRaster), 'Source raster pixels remain identical in both themes.');
    await page.evaluate(() => {for (const [e, value] of window.__nightOccluders) e.style.visibility = value;});
    assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('#map, #map *')].filter(e => getComputedStyle(e).filter !== 'none' && !e.closest('.leaflet-osmBase-pane')).map(e => e.className.baseVal || e.className || e.id)), [], 'Only osmBase tiles may receive a filter.');
    await shot(page, 'dark-synthetic-tile-overlay');
    await page.evaluate(() => {state.map.removeLayer(window.__nightTiles); state.map.removeLayer(window.__nightRaster); state.administrativeLayer.setStyle({fillOpacity: 1});});
    assert.ok(await page.locator('.leaflet-administrativeBase-pane path').count() > 0, 'Local PRG boundaries survive without tiles.');
    await shot(page, 'dark-no-tiles-prg');

    // Exercise failures as actual browser responses, with the same UI in both themes.
    for (const selected of ['light', 'dark']) {
      const faults = await context();
      await faults.addInitScript(({key, value}) => {if (location.origin !== 'null') localStorage.setItem(key, value);}, {key: themeKey, value: selected});
      for (const scenario of ['missing-geometry', 'empty-and-source-states', 'api-error', 'offline']) {
        const check = await faults.newPage();
        if (scenario === 'missing-geometry') await check.route('**/static/geo/*.geojson', route => route.fulfill({status: 503, json: {detail: 'Syntetyczny brak PRG'}}));
        if (scenario === 'empty-and-source-states') {
          await check.route('**/api/communications?**', route => route.fulfill({json: {items: [], total: 0}}));
          await check.route('**/api/sources', route => route.fulfill({json: {items: [
            {id: 'test-error', name: 'TEST błąd źródła', status: 'error', last_result: 'error', error: 'Syntetyczny błąd źródła', stale: true},
            {id: 'test-stale', name: 'TEST dane nieaktualne', status: 'ok', last_result: 'ok', stale: true, coverage: 'Częściowe pokrycie testowe'},
            {id: 'test-empty', name: 'TEST źródło puste', status: 'ok', last_result: 'ok', stale: false, coverage: 'Brak zapisanych obserwacji testowych'},
            {id: 'test-key', name: 'TEST brak klucza', access_state: 'disabled_by_user', access_note: 'Brak skonfigurowanego klucza testowego', stale: true}
          ]}}));
        }
        if (scenario === 'api-error') await check.route('**/api/communications?**', route => route.fulfill({status: 503, json: {detail: 'Syntetyczna awaria odczytu komunikatów'}}));
        await check.goto(base.href);
        await check.waitForFunction(() => !document.getElementById('refresh').disabled && state.health.mode === 'demo');
        assert.equal(await check.locator('html').getAttribute('data-theme'), selected);
        if (scenario === 'missing-geometry') {
          assert.match(await check.locator('#map-note').textContent(), /Brak geometrii referencyjnej/);
          assert.ok(await check.locator('.record').count() > 0, 'Geometry failure preserves accessible publication list.');
        } else if (scenario === 'empty-and-source-states') {
          assert.match(await check.locator('.records').textContent(), /Brak zapisanych komunikatów/);
          await check.locator('.tab[data-view="sources"]').click();
          assert.match(await check.locator('#source-list').textContent(), /Syntetyczny błąd źródła/);
          assert.match(await check.locator('#source-list').textContent(), /Nieaktualne/);
          assert.match(await check.locator('#source-list').textContent(), /Brak zapisanych obserwacji testowych/);
          assert.match(await check.locator('#source-list').textContent(), /Brak skonfigurowanego klucza/);
        } else if (scenario === 'api-error') {
          assert.match(await check.locator('#global-status').textContent(), /Syntetyczna awaria/);
          assert.doesNotMatch(await check.locator('.records').textContent(), /Brak zapisanych komunikatów/, 'Read failure must not imply no events.');
        } else {
          const records = await check.locator('.record').count(); assert.ok(records > 0);
          await faults.setOffline(true);
          await check.locator('#refresh').click();
          await check.waitForFunction(() => document.getElementById('global-status').textContent.includes('lokalnego serwera'));
          assert.equal(await check.locator('.record').count(), records, 'Previously loaded publications survive network loss.');
          await faults.setOffline(false);
        }
        await shot(check, `${selected}-${scenario}`);
        inventories.push(await contrastInventory(check, `${selected}-${scenario}`));
        await check.close();
      }
      await faults.close();
    }

    // A late detail response after changing publication day must not reopen the drawer.
    for (const selected of ['light', 'dark']) {
      await theme(page, selected);
      await page.reload(); await ready(page);
      let release, entered;
      const held = new Promise(resolve => release = resolve), requested = new Promise(resolve => entered = resolve);
      const handler = async route => {const response = await route.fetch(); entered(); await held; await route.fulfill({response});};
      await page.route('**/api/communications/*', handler);
      await page.locator('.record:visible').first().click(); await requested;
      await Promise.all([page.waitForResponse(r => r.url().includes('/api/communications?')), page.locator('#previous-day').click()]);
      const oldDay = await page.locator('#selected-day').inputValue();
      const responseFinished = page.waitForResponse(r => /\/api\/communications\/[^/?]+$/.test(new URL(r.url()).pathname));
      release(); await responseFinished; await page.waitForTimeout(50);
      assert.equal(await page.locator('#detail-panel').isHidden(), true, 'Late response cannot reopen details after changing day.');
      assert.equal(await page.locator('#selected-day').inputValue(), oldDay);
      assert.equal(await page.locator('#include-active').isDisabled(), true);
      await page.unroute('**/api/communications/*', handler);
    }

    const report = {viewports: viewports.map(width => `${width}×600`), themes: ['light', 'dark'], screenshots: evidence,
      externalRequests: allExternal, browserErrors: allErrors, contrast: inventories,
      limitations: ['Synthetic local tiles verify filter isolation and unchanged raster pixels; real OSM label readability requires separate visual review with cached/available OSM tiles.', 'Contrast inventory measures visible text with composited solid backgrounds. Image/gradient backgrounds are listed for visual review; source scales and nontext controls require semantic/visual assessment.']};
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    assert.deepEqual(allExternal, [], 'DEMO stays entirely offline.');
    assert.deepEqual(allErrors, [], 'No browser runtime errors.');
    const failures = inventories.flatMap(inventory => inventory.failures);
    assert.equal(failures.length, 0, `Computed text contrast below WCAG AA; see report.json. ${JSON.stringify(failures.slice(0, 12))}`);
    console.log('WICI Noc Chromium passed: persistence/storage, early bootstrap, keyboard, state and map identity, zero switch API requests, offline DEMO, 7 widths × 2 themes at 600 px, source raster isolation and computed text contrast.');
    console.log(`Evidence: ${output}`);
  } catch (error) {
    fs.writeFileSync(path.join(output, 'partial-report.json'), JSON.stringify({error: error.message, screenshots: evidence, contrast: inventories, externalRequests: allExternal, browserErrors: allErrors}, null, 2));
    throw error;
  } finally {if (browser) await browser.close(); await app.stop();}
})().catch(error => {console.error(error); process.exitCode = 1;});
