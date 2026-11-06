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

function solidTile(red, green, blue, alpha = 255) {
  const png = new PNG({width: 256, height: 256});
  for (let offset = 0; offset < png.data.length; offset += 4) {
    png.data[offset] = red;
    png.data[offset + 1] = green;
    png.data[offset + 2] = blue;
    png.data[offset + 3] = alpha;
  }
  return PNG.sync.write(png);
}

async function installEpisode(page, recording = episode, firstScan = solidTile(255, 0, 240)) {
  const tiles = new Map([
    [frames[0].tiles[0].url, firstScan],
    [frames[1].tiles[0].url, solidTile(30, 255, 0)],
  ]);
  await page.route(/\/api\/flight-replay(?:\?|$)/, route => route.fulfill({json: recording}));
  await page.route('**/api/flight-replay/tiles/**', route => {
    const body = tiles.get(new URL(route.request().url()).pathname);
    return body ? route.fulfill({contentType: 'image/png', body}) : route.fulfill({status: 404});
  });
}

// Okęcie, Poland. The first radar scan is clear, the second entirely green.
// The colour of the ground under a clear scan identifies the rendered layer.
const epwa = {lat: 52.1657, lon: 20.9671};
const approach = Array.from({length: 13}, (_, i) => ({
  time: start + 30 * i, lat: epwa.lat + .02 * (12 - i), lon: epwa.lon + .04 * (12 - i),
  alt_m: 110 + 100 * (12 - i), heading: 210,
}));

async function airportScene(page, enabled, available) {
  const requests = [];
  const jpeg = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#08d7ff'; ctx.fillRect(0, 0, 256, 256);
    return canvas.toDataURL('image/jpeg').split(',')[1];
  });
  const photo = Buffer.from(jpeg, 'base64'), base = solidTile(255, 105, 0);
  await page.route('**/static/geo/flight-satellite/**', route => route.fulfill({contentType:'image/png', body:base}));
  await page.route('**/api/flight-replay/orthophoto/**', route => {
    requests.push(new URL(route.request().url()).pathname);
    return available ? route.fulfill({contentType:'image/jpeg', body:photo}) :
      route.fulfill({status:503, headers:{'Retry-After':'60'}, json:{detail:'Źródło chwilowo niedostępne'}});
  });
  await installEpisode(page, {...episode, points:approach, demo:!enabled, orthophoto_enabled:enabled}, solidTile(0, 0, 0, 0));
  return requests;
}

async function viewAirport(page, height) {
  // Reposition the real overview camera to a reproducible extent on the runway.
  await page.evaluate(({lat, lon, height}) => {
    const view = window.__vehicleViewers.at(-1);
    view.camera.setView({destination:Cesium.Cartesian3.fromDegrees(lon,lat,height),
      orientation:{heading:0, pitch:-Math.PI / 2, roll:0}});
    view.scene.requestRender();
  }, {...epwa, height});
}

async function checkSurface(page, color) {
  const canvas = page.locator('#flight-replay-scene canvas');
  const deadline = Date.now() + 18000;
  let fraction;
  do {
    const png = PNG.sync.read(await canvas.screenshot());
    let sampled = 0, matching = 0;
    for (let row = Math.floor(png.height * .2); row < png.height * .8; row += 6) {
      for (let col = Math.floor(png.width * .2); col < png.width * .8; col += 6) {
        const offset = 4 * (row * png.width + col);
        const r = png.data[offset], g = png.data[offset + 1], b = png.data[offset + 2];
        const cyan = g > r + 70 && b > r + 70, orange = r > g + 50 && g > b + 25;
        matching += Number(color === 'cyan' ? cyan : orange);
        sampled++;
      }
    }
    fraction = matching / sampled;
    if (fraction > .7) return;
    await page.waitForTimeout(100);
  } while (Date.now() < deadline);
  assert.fail(`Expected ${color} ground over EPWA; observed ${Math.round(100 * fraction)}% of the central canvas`);
}

function checkAirportRequests(requests) {
  assert.ok(requests.length, 'The close camera must load orthoimagery');
  let onAirport = false;
  for (const path of requests) {
    const match = /^\/api\/flight-replay\/orthophoto\/(\d+)\/(\d+)\/(\d+)\.jpg$/.exec(path);
    assert.ok(match, path);
    const [level, x, y] = match.slice(1).map(Number), side = 2 ** level;
    assert.ok(level >= 11 && level <= 19 && x < side && y < side, path);
    const airportX = Math.floor((epwa.lon + 180) / 360 * side);
    const airportY = Math.floor((1 - Math.asinh(Math.tan(epwa.lat * Math.PI / 180)) / Math.PI) / 2 * side);
    if (x === airportX && y === airportY) onAirport = true;
  }
  assert.ok(onAirport, 'At least one requested XYZ tile must contain EPWA');
}

const basemap = '#flight-replay-basemap';
const atBasemap = (page, state) => page.locator(`${basemap}[data-state="${state}"]`).waitFor();

test('returning to EPWA reuses the visible orthophotos without fetching the same tiles again', {timeout:90000}, async () => {
  const env = await environment({name:'flight-replay-orthophoto-return', viewport:{width:960,height:720}}), {page} = env;
  try {
    const requests = await airportScene(page, true, true);
    await openReplay(page); await ready(page);
    await viewAirport(page, 1200); await checkSurface(page, 'cyan');
    // Let Cesium finish refining the close view before recording its working set.
    const settled = () => page.waitForFunction(() => window.__vehicleViewers.at(-1).scene.globe.tilesLoaded);
    await settled();
    checkAirportRequests(requests);
    const countLayers = () => page.evaluate(() => window.__vehicleViewers.at(-1).imageryLayers.length);
    const closeLayerCount = await countLayers();
    const loaded = new Set(requests), repeated = [];
    await page.route('**/api/flight-replay/orthophoto/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (!loaded.has(path)) return route.fallback();
      repeated.push(path);
      // A previously displayed area must also work if another download would fail.
      await route.fulfill({status:404});
    });

    const slider = page.locator('#flight-replay-time');
    await slider.press('End'); await checkRadarPixels(page, 'green');
    await slider.press('Home'); await checkSurface(page, 'cyan'); await settled();
    assert.deepEqual(repeated, [], 'Seeking the radar must preserve the ground under a stationary camera');
    await viewAirport(page, 14000); await atBasemap(page, 'local'); await settled();
    assert.equal(await countLayers(), closeLayerCount - 1, 'A wide camera must release the orthophoto layer');
    await checkSurface(page, 'orange');
    await viewAirport(page, 1200);
    await page.waitForFunction(() => ['orthophoto','partial','unavailable'].includes(
      document.querySelector('#flight-replay-basemap').dataset.state));
    await settled();
    assert.deepEqual(repeated, [], 'Returning to the same viewport must reuse previously fetched XYZ');
    await checkSurface(page, 'cyan');
    assert.equal(await countLayers(), closeLayerCount, 'Returning must attach only one orthophoto layer');
    await page.keyboard.press('Escape'); await checkReturned(page); await env.clean();
  } finally {await env.stop();}
});

test('LIVE approach to EPWA loads close orthophotos below both radar scans and releases them in overview', {timeout:90000}, async () => {
  const env = await environment({name:'flight-replay-orthophoto', viewport:{width:1100,height:760}}), {page} = env;
  try {
    const requests = await airportScene(page, true, true);
    await openReplay(page); await ready(page); await atBasemap(page, 'local');
    await viewAirport(page, 14000); await checkSurface(page, 'orange');
    assert.deepEqual(requests, [], 'A wide view must not request orthophotos');

    await viewAirport(page, 1200); await atBasemap(page, 'orthophoto'); await checkSurface(page, 'cyan');
    checkAirportRequests(requests);
    assert.equal(new URL(await page.locator(`${basemap} a`).getAttribute('href')).hostname, 'www.geoportal.gov.pl');
    const slider = page.locator('#flight-replay-time');
    await slider.press('End'); await checkAircraft(page, approach.at(-1)); await checkRadarPixels(page, 'green');
    await slider.press('Home'); await checkSurface(page, 'cyan');
    await page.context().setOffline(true);
    await atBasemap(page, 'offline'); await checkSurface(page, 'orange');
    await page.context().setOffline(false);
    await atBasemap(page, 'orthophoto'); await checkSurface(page, 'cyan');
    await viewAirport(page, 14000); await atBasemap(page, 'local'); await checkSurface(page, 'orange');

    // End on the low aircraft and switch between camera modes via the controls.
    await slider.press('End'); await page.locator('#flight-replay-follow').click();
    await atBasemap(page, 'orthophoto'); await checkRadarPixels(page, 'green');
    await page.locator('#flight-replay-overview').click(); await atBasemap(page, 'local');
    await page.keyboard.press('Escape'); await checkReturned(page); await env.clean();
  } finally {await env.stop();}
});

test('unavailable EPWA orthophotos reveal the local ground and DEMO stays local after reopening', {timeout:90000}, async () => {
  const env = await environment({name:'flight-replay-orthophoto-fallback', viewport:{width:1100,height:760}}), {page} = env;
  try {
    const requests = await airportScene(page, true, false);
    await openReplay(page); await ready(page); await viewAirport(page, 1200);
    await atBasemap(page, 'unavailable'); await checkSurface(page, 'orange');
    assert.ok(requests.length);
    await page.locator('#flight-replay-time').press('End');
    await checkRadarPixels(page, 'green'); await page.locator('#flight-replay-close').click(); await checkReturned(page);

    env.feed.live = false;
    await page.evaluate(() => loadHealth());
    assert.equal(await page.evaluate(() => state.health.mode), 'demo');
    const demoRequests = await airportScene(page, false, true);
    await openReplay(page); await ready(page); await viewAirport(page, 1200); await atBasemap(page, 'local');
    await checkSurface(page, 'orange');
    assert.equal(new URL(await page.locator(`${basemap} a`).getAttribute('href')).hostname, 'esa-worldcover.org');
    assert.deepEqual(demoRequests, []);
    await page.keyboard.press('Escape'); await checkReturned(page); await env.clean();
  } finally {await env.stop();}
});

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
    const mapState = () => page.evaluate(() => {
      const {x, y} = state.map.project(state.map.getCenter());
      return {x, y, zoom:state.map.getZoom()};
    });
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
    const restored = await mapState();
    assert.equal(restored.zoom, originalMap.zoom);
    // Leaflet may round a restored centre to display pixels when resizing the map.
    assert.ok(Math.abs(restored.x - originalMap.x) <= .5 && Math.abs(restored.y - originalMap.y) <= .5,
      `The map moved after closing replay: ${JSON.stringify({originalMap, restored})}`);
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

const picker = '#aircraft-replay-dialog';
const revision = 'b'.repeat(20);
const replayUrl = icao => `/api/flight-replay/aircraft/${icao}/episode?revision=${revision}`;
async function manualEntry(page) {
  await page.locator('#layer-panel').evaluate(element => {element.open = true;});
  await page.locator('.layer-group').filter({has:page.locator('#aircraft-replay-icao')}).evaluate(group => {group.open = true;});
}
async function pickFromForm(page, icao) {
  await manualEntry(page);
  await page.locator('#aircraft-replay-icao').fill(icao);
  await page.locator('#aircraft-replay-submit').click();
}
async function installSelected(page, icao, label, requested) {
  const path = replayUrl(icao);
  const selected = {...episode, label, frames:frames.map(frame => ({...frame, tiles:frame.tiles.map(tile => ({...tile,
    url:`/api/flight-replay/tiles/${icao}/${revision}/${frame.time}/${tile.z}/${tile.x}/${tile.y}.png`}))}))};
  await page.route(url => url.pathname === `/api/flight-replay/aircraft/${icao}/episode`, async route => {
    requested.push(new URL(route.request().url()).pathname + new URL(route.request().url()).search);
    await route.fulfill({json:selected});
  });
  await page.route(`**/api/flight-replay/tiles/${icao}/**`, route => route.fulfill({contentType:'image/png', body:solidTile(24,86,195)}));
  return path;
}

test('aircraft popup prepares the selected callsign and reopens its collecting job into the correct 3D episode', {timeout:60000}, async () => {
  const env = await environment({name:'selected-aircraft-replay'}), {page} = env;
  try {
    const icao = '48abcd', callsign = 'TEST3D', calls = [], requested = [];
    const address = await installSelected(page, icao, 'TEST3D · wybrana trasa', requested);
    let statusReads = 0;
    await page.route(/\/api\/flight-replay\/aircraft\/48abcd\/(prepare|collect|status)(\?|$)/, async route => {
      const req = route.request(), url = new URL(req.url()), action = url.pathname.split('/').at(-1);
      calls.push({action, method:req.method(), token:req.headers()['x-csrf-token'], body:req.postDataJSON(), query:url.searchParams.get('callsign')});
      const response = action === 'prepare' ? {status:'no_history', message:'Brak śladu historycznego.'} :
        action === 'collect' || ++statusReads === 1 ? {status:'collecting', message:'Trwa zbieranie.', points:2, frames:1} :
        {status:'ready', episode_url:address};
      await route.fulfill({json:{icao,callsign,...response}});
    });
    await page.locator('.aircraft-marker').first().click();
    await page.getByRole('button',{name:'Odtwórz ostatni odcinek w 3D',exact:true}).click();
    const collect = page.getByRole('button', {name:'Zbieraj od teraz', exact:true});
    await collect.waitFor();
    assert.equal(await page.locator(picker).getAttribute('data-state'), 'no_history');
    assert.deepEqual(calls.map(call => call.action), ['prepare']);
    await collect.evaluate(button => {button.click(); button.click();});
    await page.locator(`${picker}[data-state="collecting"]`).waitFor();
    assert.match(await page.locator('#aircraft-replay-counts').innerText(), /Pozycje: 2/);
    await page.locator('#aircraft-replay-close').click();
    await manualEntry(page);
    await page.getByRole('button',{name:'Sprawdź stan: TEST3D · 48ABCD',exact:true}).click();
    await page.locator('#flight-replay-dialog[open]').waitFor(); await ready(page);
    assert.deepEqual(requested, [address]);
    assert.equal(await page.locator('#flight-replay-title').innerText(), 'TEST3D · wybrana trasa');
    assert.deepEqual(calls.map(call => call.action), ['prepare','collect','status','status']);
    const csrf = await page.evaluate(() => state.health.csrf_token);
    assert.ok(csrf);
    for (const call of calls.slice(0,2)) {
      assert.equal(call.method,'POST'); assert.deepEqual(call.body,{callsign}); assert.equal(call.token,csrf);
    }
    for (const call of calls.slice(2)) {assert.equal(call.method,'GET'); assert.equal(call.query,callsign);}
    assert.equal(await page.locator('#aircraft-replay-recent button').count(),0);
    await page.locator('#flight-replay-close').click();
    assert.equal(await page.locator('#aircraft-replay-submit').evaluate(button => button === document.activeElement), true);
    await env.clean();
  } finally {await env.stop();}
});

test('manual ICAO rejects malformed input, isolates a late previous request and requires an explicit older-recording choice', {timeout:60000}, async () => {
  const env = await environment({name:'manual-aircraft-replay'}), {page} = env;
  let release;
  try {
    const current = '48abce', address = replayUrl(current), requested = [], calls = [];
    await installSelected(page, current, 'Starszy odcinek 48ABCE', requested);
    let started;
    const firstStarted = new Promise(resolve => {started = resolve;});
    const held = new Promise(resolve => {release = resolve;});
    await page.route(/\/api\/flight-replay\/aircraft\/[0-9a-f]+\/prepare$/, async route => {
      const icao = new URL(route.request().url()).pathname.split('/').at(-2);
      calls.push({icao, body:route.request().postDataJSON()});
      if (icao === '123abc') {
        started(); await held;
        await route.fulfill({json:{icao,status:'ready',episode_url:replayUrl(icao)}}).catch(() => {}); return;
      }
      await route.fulfill({json:{icao,status:'unavailable',message:'Źródło chwilowo niedostępne.',saved_label:'Archiwum',saved_end:start,
        saved_episode_url:address}});
    });
    await pickFromForm(page, 'ABCDEF7');
    assert.equal(await page.locator('#aircraft-replay-icao').evaluate(input => input.validity.valid), false);
    assert.equal(await page.locator(picker).isVisible(),false);
    await pickFromForm(page,'123ABC'); await firstStarted;
    await page.locator('#aircraft-replay-close').click();
    await pickFromForm(page, current.toUpperCase());
    await page.locator(`${picker}[data-state="unavailable"]`).waitFor(); release();
    assert.deepEqual(calls, [{icao:'123abc',body:{}},{icao:current,body:{}}]);
    assert.equal(await page.locator('#aircraft-replay-collect').isVisible(),false);
    assert.equal(await page.locator('#flight-replay-dialog').isVisible(),false);
    const saved = page.locator('#aircraft-replay-saved');
    assert.match(await saved.innerText(), /Archiwum.*UTC/);
    await saved.click(); await ready(page);
    assert.deepEqual(requested,[address]);
    assert.equal(await page.locator('#flight-replay-title').innerText(), 'Starszy odcinek 48ABCE');
    await page.locator('#flight-replay-close').click();
    await env.clean();
  } finally {release?.(); await env.stop();}
});
