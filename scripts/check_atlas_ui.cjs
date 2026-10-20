// Optional real-browser smoke test. Requires Playwright and a running WICI DEMO instance.
// NODE_PATH=/path/to/node_modules WICI_UI_URL=http://127.0.0.1:8770 node scripts/check_atlas_ui.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const base = new URL(process.env.WICI_UI_URL || 'http://127.0.0.1:8765');
assert.equal(base.hostname, '127.0.0.1', 'Use a local DEMO instance.');
const output = path.resolve(process.env.WICI_SCREENSHOT_DIR || 'tmp/atlas-ui-evidence');
fs.mkdirSync(output, {recursive: true});
const layerIds = ['osm-enabled', 'fires-enabled', 'effis-enabled', 'traffic-enabled',
  'gddkia-enabled', 'radar-enabled', 'lightning-enabled', 'weather-wind', 'weather-rain',
  'aircraft-enabled', 'quality-enabled', 'buses-enabled', 'ships-enabled', 'ukraine-enabled'];

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'pl-PL'});
    const page = await context.newPage();
    const errors = [], external = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base.origin) {
        external.push(route.request().url());
        return route.abort();
      }
      return route.continue();
    });
    const health = await context.request.get(new URL('/api/health', base).href);
    assert.equal((await health.json()).mode, 'demo', 'Run this check against DEMO, never LIVE.');
    await page.goto(base.href);
    await page.locator('.province-card').first().waitFor();
    await page.locator('#source-list .source-card').first().waitFor({state: 'attached'});
    assert.equal(await page.locator('#demo-banner').isVisible(), true);
    assert.equal(await page.getByRole('button', {name: 'Odśwież widok', exact: true}).count(), 1);
    assert.equal(await page.locator('[name="communication_type"] option').count(), 4);
    assert.equal(await page.locator('[name="category"] option').count(), 7);
    assert.equal(await page.locator('#province option').count(), 17);
    assert.equal(await page.evaluate(() => {
      const ids = [...document.querySelectorAll('[id]')].map(element => element.id);
      return ids.length === new Set(ids).size;
    }), true, 'Every DOM id must be unique.');
    for (const id of layerIds) assert.equal(await page.locator(`#${id}`).count(), 1, id);
    await page.screenshot({path: path.join(output, 'atlas-desktop.png'), fullPage: true});

    // Date navigation, all hidden filters, source detail, original and saved versions.
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/communications?')),
      page.locator('#previous-day').click()
    ]);
    assert.equal(await page.locator('#include-active').isDisabled(), true);
    await page.locator('.filter-options > summary').click();
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/communications?')),
      page.locator('[name="category"]').selectOption('weather')
    ]);
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/communications?')),
      page.locator('#province').selectOption('14')
    ]);
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/api/communications?')),
      page.locator('[name="communication_type"]').selectOption('warning')
    ]);
    await page.locator('.record:visible').first().click();
    await page.locator('#detail-panel:not([hidden])').waitFor();
    assert.match(await page.locator('#details').innerText(), /Ważność od/);
    assert.equal(await page.locator('#details > a').first().getAttribute('target'), '_blank');
    await page.locator('#details .detail-section details > summary').first().click();
    assert.equal(await page.getByRole('link', {name: 'Oryginał tej wersji', exact: true}).first().isVisible(), true);
    await page.screenshot({path: path.join(output, 'atlas-details.png'), fullPage: true});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#detail-panel').isHidden(), true);
    assert.equal(await page.locator('.record[aria-pressed="true"]').evaluate(element => element === document.activeElement), true);

    // Opening layer controls preserves real controls and their independent settings.
    await page.locator('#layer-panel > summary').click();
    assert.equal(await page.locator('.layer-group > summary').count(), 13);
    // v0.24.3 keeps every group collapsed; opening the panel alone does not expose controls.
    await page.locator('.layer-group').filter({has: page.locator('#weather-wind')}).locator(':scope > summary').click();
    await page.locator('#weather-wind').check();
    await page.locator('.weather-arrow').first().waitFor({state: 'attached'});
    await page.locator('#weather-rain').check();
    await page.locator('#weather-mode').selectOption('forecast');
    await page.waitForFunction(() => !document.getElementById('weather-hour').disabled);
    await page.locator('#weather-play').click();
    await page.waitForFunction(() => document.getElementById('weather-play').getAttribute('aria-pressed') === 'true');
    await page.locator('#weather-play').click();
    await page.locator('.layer-group > summary').filter({hasText: /^Pożary$/}).click();
    await page.locator('#fires-hours').selectOption('48');
    assert.equal(await page.locator('#effis-enabled').isDisabled(), true);
    await page.locator('.layer-group > summary').filter({hasText: /^Drogi$/}).click();
    assert.equal(await page.locator('#osm-enabled').isDisabled(), true);
    await page.locator('.layer-group > summary').filter({hasText: /^Lotnictwo$/}).click();
    assert.equal(await page.locator('#aircraft-enabled').isVisible(), true);
    await page.locator('.layer-group > summary').filter({hasText: /^Bałtyk$/}).click();
    assert.equal(await page.locator('#ships-baltic').isVisible(), true);
    await page.screenshot({path: path.join(output, 'atlas-layers.png'), fullPage: true});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#layer-panel').getAttribute('open'), null);

    await page.locator('.tab[data-view="sources"]').click();
    assert.equal(await page.locator('#situation').isHidden(), true);
    assert.equal(await page.locator('#sources').isVisible(), true);
    const refreshes = page.locator('.source-card .form-actions button');
    for (let index = 0; index < await refreshes.count(); index++) {
      assert.equal(await refreshes.nth(index).isDisabled(), true, 'DEMO must not refresh real sources.');
    }
    await page.screenshot({path: path.join(output, 'atlas-sources.png'), fullPage: true});
    await page.locator('.tab[data-view="situation"]').click();
    await page.getByRole('button', {name: 'Odśwież widok', exact: true}).click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);

    // Real narrow and short screens: no overflow, reachable filters and visible detail selection.
    for (const viewport of [{width: 1366, height: 768}, {width: 768, height: 1024},
      {width: 390, height: 844}, {width: 320, height: 750}]) {
      await page.setViewportSize(viewport);
      await page.reload();
      await page.locator('.province-card').first().waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${viewport.width}`);
      await page.locator('.filter-options > summary').click();
      assert.ok(await page.locator('.records').evaluate(element => element.clientHeight) >= 120, 'Expanded filters must leave a usable list.');
      await page.locator('.filter-options > summary').click();
      if (viewport.width <= 600) {
        assert.equal(await page.getByRole('button', {name: 'Odśwież widok', exact: true}).count(), 1);
        await page.locator('.record:visible').first().click();
        await page.locator('#detail-panel:not([hidden])').waitFor();
        const detail = await page.locator('#detail-panel').boundingBox();
        assert.ok(detail.y >= 0 && detail.y < viewport.height - 100, 'Opening a record must reveal the phone drawer.');
        await page.locator('#close-details').click();
        const record = await page.locator('.record[aria-pressed="true"]').boundingBox();
        assert.ok(record.y >= 0 && record.y < viewport.height, 'Closing details must return to the selected record.');
      }
      await page.screenshot({path: path.join(output, `atlas-${viewport.width}.png`), fullPage: true});
    }
    assert.deepEqual(errors, [], 'Browser runtime errors');
    assert.deepEqual(external, [], 'DEMO must stay offline');
    console.log('Atlas browser smoke passed: filters, dates, detail/history, all layer controls, weather playback, sources, 4 viewport sizes and offline DEMO.');
    console.log(`Screenshots: ${output}`);
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
