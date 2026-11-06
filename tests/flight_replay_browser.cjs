// Real Cesium/Chromium, an isolated backend and two synthetic radar scans.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {PNG} = require('pngjs');
const {environment, camera, distance} = require('./helpers/vehicle3d_browser.cjs');

const start = Date.parse('2026-04-12T12:00:00Z') / 1000;
const points = Array.from({length: 13}, (_, i) => ({
  time: start + 30 * i, lat: 52.22 + i * 0.01, lon: 20.65 + i * 0.06, alt_m: 3000 + i * 100, heading: 75,
}));
const z = 6;
const x = Math.floor((points[0].lon + 180) / 360 * 2 ** z);
const y = Math.floor((1 - Math.asinh(Math.tan(points[0].lat * Math.PI / 180)) / Math.PI) / 2 * 2 ** z);
const frames = [start, start + 300].map(time => ({
  time, tiles: [{z, x, y, url: `/api/flight-replay/tiles/${'a'.repeat(20)}/${time}/${z}/${x}/${y}.png`}],
}));
const episode = {
  label: 'Syntetyczny przelot testowy', flight_source: 'Syntetyczny lot', radar_source: 'Syntetyczny radar',
  points, frames, demo: false,
};

function solidTile(red, green, blue) {
  const png = new PNG({width: 256, height: 256});
  for (let offset = 0; offset < png.data.length; offset += 4) {
    png.data[offset] = red;
    png.data[offset + 1] = green;
    png.data[offset + 2] = blue;
    png.data[offset + 3] = 255;
  }
  return PNG.sync.write(png);
}

async function installEpisode(page) {
  const tiles = new Map([
    [frames[0].tiles[0].url, solidTile(255, 0, 240)],
    [frames[1].tiles[0].url, solidTile(30, 255, 0)],
  ]);
  await page.route(/\/api\/flight-replay(?:\?|$)/, route => route.fulfill({json: episode}));
  await page.route('**/api/flight-replay/tiles/**', route => {
    const body = tiles.get(new URL(route.request().url()).pathname);
    return body ? route.fulfill({contentType: 'image/png', body}) : route.fulfill({status: 404});
  });
}

async function openReplay(page) {
  const button = page.locator('#flight-replay-open');
  const panel = page.locator('#layer-panel');
  if (!await panel.evaluate(element => element.open)) await panel.locator(':scope > summary').click();
  const group = page.locator('.layer-group').filter({has: button});
  if (!await group.evaluate(element => element.open)) await group.locator(':scope > summary').click();
  await button.click();
  await page.locator('#flight-replay-dialog[open]').waitFor();
}

async function ready(page) {
  await page.waitForFunction(() => ['error', 'ready'].includes(document.querySelector('#flight-replay-dialog').dataset.state));
  assert.equal(await page.locator('#flight-replay-dialog').getAttribute('data-state'), 'ready',
    await page.locator('#flight-replay-status').innerText());
}

async function checkAircraft(page, expected) {
  await page.waitForFunction(expected => {
    const view = window.__vehicleViewers.at(-1);
    const entity = view?.entities.getById('flight-replay-aircraft');
    const current = entity?.position?.getValue(view.clock.currentTime);
    return entity?.show && current && Cesium.Cartesian3.distance(
      current, Cesium.Cartesian3.fromDegrees(expected.lon, expected.lat, expected.alt_m),
    ) < 2;
  }, expected);
}

async function checkRadarPixels(page, color) {
  // A fetched PNG or updated time label alone cannot establish that imagery
  // reached the GPU. Distinct saturated scans also disambiguate it from land.
  const canvas = page.locator('#flight-replay-scene canvas');
  const deadline = Date.now() + 15000;
  let previous;
  do {
    const png = PNG.sync.read(await canvas.screenshot());
    const pixels = {magenta: 0, green: 0};
    for (let row = 8; row < png.height - 8; row += 4) {
      for (let col = 8; col < png.width - 8; col += 4) {
        const offset = 4 * (row * png.width + col);
        const r = png.data[offset], g = png.data[offset + 1], b = png.data[offset + 2];
        if (r > g + 45 && b > g + 35) pixels.magenta++;
        if (g > r + 45 && g > b + 35) pixels.green++;
      }
    }
    const other = color === 'magenta' ? pixels.green : pixels.magenta;
    if (pixels[color] > 50 && pixels[color] > 2 * other) return;
    previous = pixels;
    await page.waitForTimeout(100);
  } while (Date.now() < deadline);
  assert.fail(`Expected visible ${color} scan on the globe. Sample counts: ${JSON.stringify(previous)}`);
}

async function checkReturned(page) {
  assert.equal(await page.locator('#flight-replay-dialog').isVisible(), false);
  assert.equal(await page.locator('#flight-replay-scene canvas').count(), 0);
  assert.equal(await page.evaluate(() => window.__vehicleViewers.every(view => view.isDestroyed())), true);
  assert.equal(await page.locator('#flight-replay-open').evaluate(button => document.activeElement === button), true);
}

test('3D replay seeks a flight and visible radar in both directions and returns to Atlas', {timeout: 100000}, async () => {
  const env = await environment({name: 'flight-replay-desktop'});
  const {page} = env;
  try {
    await installEpisode(page);
    const mapState = () => page.evaluate(() => ({
      center: [state.map.getCenter().lat, state.map.getCenter().lng], zoom: state.map.getZoom(),
    }));
    const originalMap = await mapState();
    await openReplay(page);
    await ready(page);
    assert.equal(await page.evaluate(() => window.__vehicleViewers.at(-1).scene.context.webgl2), true);
    await checkAircraft(page, points[0]);
    await checkRadarPixels(page, 'magenta');

    const overview = await camera(page);
    await page.locator('#flight-replay-follow').click();
    assert.equal(await page.locator('#flight-replay-follow').getAttribute('aria-pressed'), 'true');
    const firstFollow = await camera(page);
    assert.ok(distance(overview, firstFollow) > 100, 'Follow must change the actual camera position');
    const slider = page.locator('#flight-replay-time');
    const firstRadarTime = await page.locator('#flight-replay-radar-time').innerText();
    await slider.press('End');
    await checkAircraft(page, points.at(-1));
    await checkRadarPixels(page, 'green');
    const lastRadarTime = await page.locator('#flight-replay-radar-time').innerText();
    assert.notEqual(lastRadarTime, firstRadarTime);
    assert.ok(distance(firstFollow, await camera(page)) > 1000, 'The follow camera must move with the aircraft');
    await slider.press('Home');
    await checkAircraft(page, points[0]);
    await checkRadarPixels(page, 'magenta');
    assert.equal(await page.locator('#flight-replay-radar-time').innerText(), firstRadarTime);

    await page.locator('#flight-replay-overview').click();
    assert.equal(await page.locator('#flight-replay-overview').getAttribute('aria-pressed'), 'true');
    await page.locator('#flight-replay-speed').selectOption('60');
    await page.locator('#flight-replay-play').click();
    await page.waitForFunction(start => Number(document.querySelector('#flight-replay-time').value) >= start + 3, start);
    await page.locator('#flight-replay-play').click();
    assert.equal(await page.locator('#flight-replay-dialog').getAttribute('data-playing'), 'false');
    await page.keyboard.press('Escape');
    await checkReturned(page);
    assert.deepEqual(await mapState(), originalMap);
    await env.clean();
  } finally {
    await env.stop();
  }
});

test('3D replay fits a mobile viewport and a missing episode leaves the map reachable', {timeout: 65000}, async () => {
  const env = await environment({viewport: {width: 390, height: 844}, name: 'flight-replay-mobile'});
  const {page} = env;
  try {
    // The isolated DEMO actually has no episode on disk. Verify that initial
    // failure, then reopen with a valid test recording to check real recovery.
    await openReplay(page);
    await page.locator('#flight-replay-dialog[data-state="error"]').waitFor();
    assert.ok((await page.locator('#flight-replay-status').innerText()).trim());
    await page.locator('#flight-replay-close').click();
    await checkReturned(page);
    await installEpisode(page);
    await openReplay(page);
    await ready(page);
    await checkAircraft(page, points[0]);
    const layout = await page.locator('#flight-replay-dialog').evaluate(element => {
      const box = element.getBoundingClientRect();
      return {left: box.left, right: box.right, width: innerWidth, contents: element.scrollWidth, inside: element.clientWidth};
    });
    assert.ok(layout.left >= -1 && layout.right <= layout.width + 1, JSON.stringify(layout));
    assert.ok(layout.contents <= layout.inside + 1, JSON.stringify(layout));
    for (const selector of ['#flight-replay-time', '#flight-replay-play', '#flight-replay-close']) {
      assert.equal(await page.locator(selector).isVisible(), true, selector);
    }
    await page.locator('#flight-replay-close').click();
    await checkReturned(page);
    await env.clean();
  } finally {
    await env.stop();
  }
});
