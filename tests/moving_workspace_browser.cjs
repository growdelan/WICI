'use strict';
// Real workspace/tracking APIs and SQLite, synthetic transport feeds, no external network.
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'tmp/moving-workspace-evidence');
fs.mkdirSync(evidence, {recursive:true});
const aircraft = 'aircraft:icao:48abc0', ship = 'ship:mmsi:261000001';

async function setup() {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const child = spawn(path.join(root, '.venv/bin/python'), ['tests/helpers/moving_workspace_server.py', String(port)],
    {cwd:root, stdio:['ignore', 'pipe', 'pipe']});
  let logs = '', browser, page;
  child.stdout.on('data', chunk => logs += chunk); child.stderr.on('data', chunk => logs += chunk);
  const url = `http://127.0.0.1:${port}`, errors = [], external = [], reads = [];
  try {
    for (let i = 0; i < 200; i++) {
      if (child.exitCode !== null) throw new Error(logs);
      try {if ((await fetch(url+'/api/health')).ok) break;} catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({headless:true});
    const context = await browser.newContext({viewport:{width:1920, height:1080}});
    await context.route('**/*', async route => {
      const requestURL = new URL(route.request().url()); reads.push(requestURL.pathname);
      if (requestURL.origin !== url) {external.push(requestURL.href); return route.abort();}
      // DEMO supplies local station fixtures; transport is the real collector with test feeds.
      if (requestURL.pathname === '/api/health') {
        const response = await route.fetch();
        return route.fulfill({json:{...await response.json(), mode:'live'}});
      }
      return route.continue();
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.stack || error.message));
    await page.goto(url);
    await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
    await page.locator('[data-view="analysis"]').click();
    await settle(page);
    const headers = {'Origin':url, 'X-CSRF-Token':await page.evaluate(() => state.health.csrf_token)};
    return {page, context, url, errors, external, reads, headers,
      async close() {
        await page.screenshot({path:path.join(evidence,'last-state.png'), fullPage:true}).catch(()=>{});
        await browser.close(); const done = once(child,'exit'); child.kill('SIGTERM'); await done;
        fs.writeFileSync(path.join(evidence,'server.log'),logs);
      }};
  } catch (error) {if (browser) await browser.close(); child.kill('SIGTERM'); throw error;}
}

async function settle(page) {
  await page.waitForFunction(() => window.WiciWorkspace?.getData() && !WiciWorkspace.getState().loading && !WiciWorkspace.getState().error);
}
async function types(page, selected) {
  // Add the desired types first so normal setup never tries to leave zero selected.
  for (const desired of [true,false]) for (const button of await page.locator('[data-object-type]').all()) {
    const wanted = selected.includes(await button.getAttribute('data-object-type'));
    if (wanted === desired && (await button.getAttribute('aria-pressed') === 'true') !== wanted) await button.click();
  }
  await settle(page);
  assert.deepEqual(await page.evaluate(() => [...WiciWorkspace.getState().query.types].sort()),[...selected].sort());
}
async function darkCatalogueContrast(page) {
  return page.locator('#analysis-table .analysis-object-link, #analysis-table thead th button').evaluateAll(elements => {
    const rgba = text => {const values = text.match(/[\d.]+/g).map(Number); return [...values.slice(0,3),values[3] ?? 1];};
    const over = (front,back) => front.slice(0,3).map((value,index) => value*front[3] + back[index]*(1-front[3]));
    const background = element => element ? over(rgba(getComputedStyle(element).backgroundColor),background(element.parentElement)) : [255,255,255];
    const luminance = rgb => rgb.map(value => value/255).map(value => value <= .04045 ? value/12.92 : ((value+.055)/1.055)**2.4)
      .reduce((sum,value,index) => sum+value*[.2126,.7152,.0722][index],0);
    return elements.map(element => {
      const color = getComputedStyle(element).color, bg = background(element), fg = over(rgba(color),bg), a = luminance(fg), b = luminance(bg);
      return {label:element.textContent,foreground:color,background:bg,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
    });
  });
}
async function card(page, ref) {
  await page.locator(`#analysis-table [data-ref="${ref}"] .analysis-object-link`).click();
  await page.waitForFunction(ref => WiciWorkspace.getState().selectedRef === ref && document.getElementById('analysis-watch-object'), ref);
}
async function closeCard(page) {
  await page.keyboard.press('Escape'); await page.locator('#analysis-card').waitFor({state:'hidden'});
}
async function watchedOnly(page, enabled) {
  if (!(await page.locator('.analysis-query-options').evaluate(element => element.open))) {
    await page.locator('.analysis-query-options > summary').click();
  }
  await page.locator('#analysis-watched-only').setChecked(enabled);
}

test('Analiza transport: main-map icons, classification colors, labels and selection in light, dark and mobile', {timeout:90000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await types(page, ['aircraft','ship']);
    await page.waitForFunction(() => document.querySelectorAll('.analysis-transport-marker').length === 6);
    await page.evaluate(() => state.map.fitBounds(L.latLngBounds(WiciWorkspace.getData().map.points.map(item => [item.latitude,item.longitude])), {padding:[35,35],animate:false}));
    assert.equal(await page.locator('.analysis-transport-marker.aircraft-marker').count(),3);
    assert.equal(await page.locator('.analysis-transport-marker .aircraft-military').count(),1);
    for (const category of ['military','civilian','unclassified']) assert.equal(await page.locator(`.analysis-transport-marker .ship-${category}`).count(),1);
    await page.evaluate(() => {const item = WiciWorkspace.getData().items.find(item => item.ref === 'aircraft:icao:48abc1'); state.map.setView([item.latitude,item.longitude],9,{animate:false});});
    const plane = page.locator('.analysis-transport-marker .aircraft-military');
    await plane.hover(); await page.locator('.leaflet-tooltip').filter({hasText:'ANALIZA LOT 2'}).waitFor();
    await plane.click(); await page.waitForFunction(() => WiciWorkspace.getState().selectedRef === 'aircraft:icao:48abc1');
    await page.locator('#analysis-card-title').filter({hasText:'ANALIZA LOT 2'}).waitFor();
    assert.equal(await page.locator('.analysis-transport-selected .aircraft-military').count(),1);
    await closeCard(page);
    await page.locator('#analysis-transport-legend summary').click();
    assert.match(await page.locator('#analysis-transport-legend').innerText(),/Kolory ikon.*kolory tras/);
    const colors = await page.locator('.analysis-transport-marker .ship-symbol').evaluateAll(items => items.map(item => getComputedStyle(item).backgroundColor).sort());
    assert.deepEqual(colors,['rgb(101, 113, 126)','rgb(132, 59, 167)','rgb(18, 107, 120)'].sort());
    await page.screenshot({path:path.join(evidence,'transport-icons-light.png'),fullPage:true});
    await page.locator('#theme-toggle').click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    assert.deepEqual(await page.locator('.analysis-transport-marker .ship-symbol').evaluateAll(items => items.map(item => getComputedStyle(item).backgroundColor).sort()),colors);
    await page.screenshot({path:path.join(evidence,'transport-icons-dark.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'Mapa',exact:true}).click();
    await page.evaluate(() => {state.map.invalidateSize({pan:false}); const item = WiciWorkspace.getData().items.find(item => item.ref === 'aircraft:icao:48abc1'); state.map.setView([item.latitude,item.longitude],9,{animate:false});});
    await plane.hover(); await page.locator('.leaflet-tooltip').filter({hasText:'ANALIZA LOT 2'}).waitFor();
    const tooltip = await page.locator('.analysis-transport-tooltip').boundingBox(), mapBox = await page.locator('#map').boundingBox();
    assert.ok(tooltip.x >= mapBox.x && tooltip.x + tooltip.width <= mapBox.x + mapBox.width,'mobile tooltip stays inside the map');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.equal(await page.locator('.analysis-transport-marker').count(),6);
    await page.screenshot({path:path.join(evidence,'transport-icons-mobile.png'),fullPage:true});
    await page.locator('[data-view="situation"]').click();
    assert.equal(await page.locator('.analysis-transport-marker').count(),0);
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Analiza transport: catalogue identities, persistent watchlist, recording and Situation return', {timeout:120000}, async () => {
  const env = await setup(), {page, context, url, headers} = env;
  try {
    const originalMap = await page.evaluate(() => state.map._leaflet_id);
    await page.locator('[data-object-type="communication"]').click();
    assert.match(await page.locator('#analysis-message').innerText(),/Wybierz co najmniej jeden typ obiektu/);
    await types(page, ['aircraft','ship']);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 6);
    assert.equal(await page.locator('#analysis-table tbody tr').count(), 6);
    assert.doesNotMatch(await page.locator('#analysis-message').innerText(),/Wybierz co najmniej jeden typ obiektu/,'a successful query clears the obsolete zero-type warning');
    await page.locator('#analysis-search').fill('SP-TST0');
    await page.waitForFunction(() => WiciWorkspace.getData().total === 1);
    await card(page, aircraft);
    assert.match(await page.locator('#analysis-card').innerText(), /SP-TST0/);
    await page.locator('#theme-toggle').click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await page.waitForTimeout(200); // Allow the global 150 ms theme color transition to finish.
    const contrast = await darkCatalogueContrast(page);
    assert.equal(contrast.length,4,'one object link and three sortable headings are checked');
    for (const result of contrast) assert.ok(result.ratio >= 4.5,`${result.label}: dark text contrast ${result.ratio.toFixed(2)}:1 must reach 4.5:1`);
    console.log('Dark catalogue contrast:',contrast.map(result => `${result.label}: ${result.ratio.toFixed(2)}:1`).join(', '));
    await page.screenshot({path:path.join(evidence,'aircraft-card-dark.png'),fullPage:true,animations:'disabled'});
    await page.locator('#theme-toggle').click();
    await page.locator('#analysis-watch-object').click();
    await page.waitForFunction(() => document.getElementById('analysis-watch-object').getAttribute('aria-pressed') === 'true');
    const watched = await (await context.request.get(url+'/api/workspace/watchlist')).json();
    assert.ok(watched.items.some(item => item.ref === aircraft));
    await page.locator('#analysis-start-recording').click();
    await page.locator('[data-stop-track]').waitFor();
    let tracks = await (await context.request.get(url+'/api/tracks')).json();
    const active = tracks.items.find(item => item.kind === 'aircraft' && item.object_id === '48abc0' && item.active);
    assert.ok(active, 'start control creates a genuine durable tracking session');
    await page.locator(`[data-stop-track="${active.id}"]`).click();
    await page.waitForFunction(() => !document.querySelector('[data-stop-track]'));
    tracks = await (await context.request.get(url+'/api/tracks')).json();
    assert.equal(tracks.items.find(item => item.id === active.id).active, false);
    await closeCard(page);
    await page.locator('#analysis-search').fill('');
    await page.waitForFunction(() => WiciWorkspace.getData().total === 6);
    await watchedOnly(page,true);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 1);
    await page.reload();
    await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
    if (!(await page.locator('#analysis-table').isVisible())) await page.locator('[data-view="analysis"]').click();
    await settle(page); await types(page, ['aircraft','ship']);
    await watchedOnly(page,true);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 1);
    assert.equal(await page.locator(`#analysis-table [data-ref="${aircraft}"]`).count(),1);
    await card(page, aircraft);
    assert.equal(await page.locator('#analysis-watch-object').getAttribute('aria-pressed'),'true');
    await closeCard(page); await watchedOnly(page,false);
    await page.locator('[data-view="situation"]').click();
    await page.locator('#communication-list').waitFor({state:'visible'});
    const refreshedMap = await page.evaluate(() => state.map._leaflet_id);
    await page.locator('[data-view="analysis"]').click(); await settle(page);
    assert.equal(await page.evaluate(() => state.map._leaflet_id),refreshedMap,'tab switch reuses the map');
    assert.ok(originalMap, 'initial Situation map existed');
    await types(page,['hydro_station']);
    await page.waitForFunction(() => WiciWorkspace.getData().items.some(item => item.ref === 'hydro_station:imgw:demo-wisla'));
    await page.locator('[data-ref="hydro_station:imgw:demo-wisla"] .analysis-object-link').click();
    await page.locator('#analysis-card-title').filter({hasText:'DEMO: wodowskaz Wisła'}).waitFor();
    assert.match(await page.locator('.analysis-reading').innerText(), /274/);
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
    assert.ok(headers['X-CSRF-Token']);
  } finally {await env.close();}
});

test('Analiza transport: synchronized comparison leaves observation gaps and seeks locally', {timeout:120000}, async () => {
  const env = await setup(), {page, context, url} = env;
  try {
    await types(page,['aircraft','ship']);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 6);
    for (const ref of [aircraft,ship]) await page.locator(`#analysis-table [data-ref="${ref}"] .analysis-compare-toggle`).check();
    await page.locator('#analysis-motion').waitFor({state:'visible'});
    const history = await (await context.request.get(url+'/_test/history')).json();
    const start = Date.parse(history.range.from), end = Date.parse(history.range.to);
    const rangeInputs = await page.evaluate(range => ({
      from:WiciWorkspaceTimeline.localValue(range.from), to:WiciWorkspaceTimeline.localValue(range.to)
    }), {from:history.range.from,to:new Date(end+60000).toISOString()});
    await page.locator('#analysis-time-from').fill(rangeInputs.from);
    await page.locator('#analysis-time-to').fill(rangeInputs.to);
    await page.getByRole('button',{name:'Ustaw przedział',exact:true}).click();
    await settle(page);
    await page.waitForFunction(() => document.querySelectorAll('#analysis-comparison-table tbody tr').length === 2);
    await page.waitForFunction(() => !document.getElementById('analysis-cursor').disabled);
    const sourceReads = () => env.reads.filter(path => ['/api/aircraft','/api/ships'].includes(path)).length;
    const before = sourceReads();
    async function seek(at) {
      const value = await page.evaluate(at => WiciWorkspaceTimeline.localValue(new Date(at).toISOString()),at);
      await page.locator('#analysis-cursor-date').fill(value);
      await page.locator('#analysis-cursor-date').dispatchEvent('change');
      await page.waitForFunction(at => Date.parse(WiciWorkspace.getState().cursorAt) === at,at);
    }
    await seek(start+10*60000);
    for (const ref of [aircraft,ship]) assert.equal(await page.locator(`#analysis-comparison-table tr[data-ref="${ref}"]`).getAttribute('data-motion-status'),'ready');
    assert.equal(await page.locator('.analysis-replay-marker').count(),2,'map shows both observed objects at the shared cursor');
    assert.equal(await page.locator('.analysis-replay-marker .aircraft-symbol').count(),1);
    assert.equal(await page.locator('.analysis-replay-marker .ship-civilian').count(),1);
    assert.equal(await page.locator('.analysis-replay-marker .ship-old').count(),0,'historical positions use cursor age rather than current time');
    assert.equal(await page.locator('.analysis-replay-marker .aircraft-symbol').evaluate(item => item.style.transform),'rotate(-10deg)');
    assert.equal(await page.locator('.analysis-replay-marker .ship-symbol').evaluate(item => item.style.transform),'rotate(50deg)');
    assert.equal(await page.locator('.analysis-recorded-track').count(),3,'two aircraft segments preserve the gap beside one continuous ship route');
    await seek(start+30*60000);
    assert.equal(await page.locator(`#analysis-comparison-table tr[data-ref="${aircraft}"]`).getAttribute('data-motion-status'),'gap');
    assert.equal(await page.locator(`#analysis-comparison-table tr[data-ref="${ship}"]`).getAttribute('data-motion-status'),'ready');
    assert.match(await page.locator(`#analysis-comparison-table tr[data-ref="${aircraft}"]`).innerText(),/luka|przerwa|brak/i);
    assert.equal(await page.locator('.analysis-replay-marker').count(),1,'gap removes the unavailable aircraft position from the map');
    await seek(start+45*60000);
    assert.equal(await page.locator(`#analysis-comparison-table tr[data-ref="${aircraft}"]`).getAttribute('data-motion-status'),'ready');
    await page.locator('#analysis-motion-play').click();
    await page.locator(`#analysis-comparison-table tr[data-ref="${aircraft}"] button`).focus();
    const playingFrom = await page.evaluate(() => {
      window._movingTestFocused = document.activeElement;
      return WiciWorkspace.getState().cursorAt;
    });
    await page.waitForFunction(previous => WiciWorkspace.getState().cursorAt !== previous,playingFrom);
    assert.equal(await page.evaluate(() => document.activeElement === window._movingTestFocused),true,'playback preserves keyboard focus in the comparison table');
    await page.locator('#analysis-motion-play').click();
    await seek(start+45*60000);
    assert.equal(sourceReads(),before,'seeking archived tracks does not read live aircraft/AIS feeds');
    assert.ok(await page.locator('#analysis-speed-chart').count());
    assert.ok(await page.locator('#analysis-altitude-chart').count());
    await page.screenshot({path:path.join(evidence,'comparison-desktop.png'),fullPage:true});
    for (const width of [390,768,1920]) {
      await page.setViewportSize({width,height:1080});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1),`no document overflow at ${width}`);
      if (width === 390) await page.screenshot({path:path.join(evidence,'comparison-mobile.png'),fullPage:true});
    }
    const extraRefs = ['aircraft:icao:48abc1','aircraft:icao:48abc2','ship:mmsi:261000002'];
    for (const ref of extraRefs) await page.locator(`#analysis-table [data-ref="${ref}"] .analysis-compare-toggle`).check();
    await page.waitForFunction(() => WiciWorkspace.getState().comparedRefs.length === 5);
    const sixth = page.locator('#analysis-table [data-ref="ship:mmsi:261000003"] .analysis-compare-toggle');
    if (!(await sixth.isDisabled())) await sixth.click();
    assert.equal(await page.evaluate(() => WiciWorkspace.getState().comparedRefs.length),5,'comparison admits at most five objects');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Analiza transport: failed or absent source reports preserve identities without stale map positions', {timeout:90000}, async () => {
  const env = await setup(), {page, context, url, headers} = env;
  try {
    await types(page,['aircraft','ship']);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 6);
    assert.ok(await page.evaluate(() => WiciWorkspace.getData().items.every(item => item.freshness === 'fresh' && item.position)));
    await card(page, aircraft);
    await page.locator('#analysis-watch-object').click();
    await page.waitForFunction(() => document.getElementById('analysis-watch-object').getAttribute('aria-pressed') === 'true');
    await closeCard(page);
    const stale = await context.request.post(url+'/_test/feed/stale',{headers});
    assert.equal(stale.status(),200);
    await Promise.all(['/api/aircraft','/api/ships'].map(path => context.request.get(url+path)));
    await page.locator('#analysis-refresh').click();
    await page.waitForFunction(() => !WiciWorkspace.getState().loading && WiciWorkspace.getData().items.every(item => item.freshness === 'stale' && item.position === null));
    assert.equal(await page.locator('#analysis-table tbody tr').count(),6,'durable object identities remain discoverable');
    assert.equal(await page.evaluate(() => WiciWorkspace.getData().map.located_total),0,'stale positions are excluded from the current map');
    await watchedOnly(page,true);
    await page.waitForFunction(() => !WiciWorkspace.getState().loading && WiciWorkspace.getData().total === 1);
    assert.equal(await page.locator(`#analysis-table [data-ref="${aircraft}"]`).count(),1,'watchlist keeps an unavailable object');
    await context.request.post(url+'/_test/feed/fresh',{headers});
    await Promise.all(['/api/aircraft','/api/ships'].map(path => context.request.get(url+path)));
    await page.locator('#analysis-refresh').click();
    await page.waitForFunction(() => !WiciWorkspace.getState().loading && WiciWorkspace.getData().items[0]?.freshness === 'fresh');
    assert.equal(await page.evaluate(() => WiciWorkspace.getData().items[0].position.speed_kmh),620,'a new source snapshot reaches the catalogue');
    await context.request.post(url+'/_test/feed/empty',{headers});
    await Promise.all(['/api/aircraft','/api/ships'].map(path => context.request.get(url+path)));
    await page.locator('#analysis-refresh').click();
    await page.waitForFunction(() => !WiciWorkspace.getState().loading && WiciWorkspace.getData().items[0]?.position === null);
    assert.equal(await page.evaluate(() => WiciWorkspace.getData().total),1,'an absent report does not remove a watched identity');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Analiza transport: persistence failure remains visible across query warnings and clears on recovery', {timeout:90000}, async () => {
  const env = await setup(), {page} = env;
  let fail = true;
  try {
    await page.route('**/api/workspace/status', async route => {
      const response = await route.fetch(), body = await response.json();
      await route.fulfill({json:{...body,moving_persistence:{pending:0,errors:fail ? {aircraft:'Synthetic projection error'} : {},coalesced_snapshots:0}}});
    });
    await types(page,['aircraft','ship']);
    await page.locator('[data-view="situation"]').click();
    await page.locator('[data-view="analysis"]').click();
    await page.waitForFunction(() => document.getElementById('analysis-persistence-status').textContent.includes('Nie udało się zapisać'));
    assert.equal(await page.locator('#analysis-persistence-status').isVisible(),true);
    await page.getByRole('button',{name:'Ostatnie 24 godziny',exact:true}).click();
    await settle(page);
    await page.waitForFunction(() => document.getElementById('analysis-message').textContent.includes('Metadane'));
    assert.match(await page.locator('#analysis-persistence-status').innerText(),/Nie udało się zapisać/,'a catalogue query warning cannot overwrite a persistence failure');
    await page.screenshot({path:path.join(evidence,'projection-failure.png'),fullPage:true});
    fail = false;
    await page.locator('[data-view="situation"]').click();
    await page.locator('[data-view="analysis"]').click();
    await page.waitForFunction(() => document.getElementById('analysis-persistence-status').textContent === '');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});
