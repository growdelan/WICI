'use strict';
// Real Chromium + SQLite, isolated synthetic history. No user database or desktop.
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const A = 'ua_region:neptun:oblast:obwod-a', B = 'ua_region:neptun:oblast:obwod-b';

async function setup({empty = false} = {}) {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const process = spawn(path.join(root, '.venv/bin/python'), ['-u', 'tests/ukraine_workspace_fixture.py', String(port), ...(empty ? ['--empty'] : [])], {cwd:root, stdio:['ignore','pipe','pipe']});
  let logs = '', browser;
  process.stdout.on('data', data => logs += data); process.stderr.on('data', data => logs += data);
  const url = `http://127.0.0.1:${port}`;
  try {
    for (let index = 0; index < 240; index++) {
      if (process.exitCode !== null) throw new Error(logs);
      try {if ((await fetch(url+'/api/health')).ok) break;} catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:1600,height:1100}}), errors = [], external = [], reads = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const target = new URL(route.request().url());
      if (target.origin !== url) {external.push(target.href); return route.abort();}
      reads.push({path:target.pathname, method:route.request().method()});
      if (target.pathname === '/api/health') {
        const response = await route.fetch(), data = await response.json();
        return route.fulfill({json:{...data,mode:'live'}});
      }
      return route.continue();
    });
    await page.goto(url);
    await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
    await page.locator('[data-view="analysis"]').click();
    await page.locator('#analysis-country').selectOption('UA');
    await page.waitForFunction(() => WiciWorkspace.getState().query.country === 'UA' && !WiciWorkspace.getState().loading && WiciWorkspace.getData()?.total >= 3);
    return {page,url,errors,external,reads,async close(){await browser.close();const done=once(process,'exit');process.kill('SIGTERM');await done;}};
  } catch (error) {if(browser)await browser.close();process.kill('SIGTERM');throw error;}
}

async function settle(page) {
  await page.waitForFunction(() => !WiciWorkspace.getState().loading && !WiciWorkspace.getState().error);
}

test('Ukraine Analysis: synchronized comparison, gaps, timezone and saved view without provider reads', {timeout:90000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await page.locator(`[data-ref="${A}"] .analysis-compare-toggle`).check();
    await page.locator(`[data-ref="${B}"] .analysis-compare-toggle`).check();
    await page.locator(`[data-ref="${A}"] .analysis-watch-toggle`).click();
    await page.waitForFunction(() => document.getElementById('analysis-watchlist-items').textContent.includes('TEST Obwód A'));
    assert.equal((await (await page.request.get(env.url+'/api/workspace/ukraine/recording')).json()).enabled,false);
    await page.locator('#analysis-timezone').selectOption('UTC');
    const now = new Date((await (await page.request.get(env.url+'/api/health')).json()).now);
    now.setUTCSeconds(0,0); const from = new Date(now.getTime()-3600000);
    await page.locator('#analysis-time-from').fill(from.toISOString().slice(0,16));
    await page.locator('#analysis-time-to').fill(now.toISOString().slice(0,16));
    await page.getByRole('button',{name:'Ustaw przedział',exact:true}).click();
    await page.waitForFunction(() => document.querySelectorAll('.analysis-alert-segment').length > 5 && !document.getElementById('analysis-cursor').disabled);
    await settle(page);
    assert.equal(await page.locator('#analysis-region-comparison tbody tr').count(),2);
    assert.ok(await page.locator('.analysis-alert-segment[data-alert-state="unknown"]').count());
    assert.match(await page.locator('#analysis-region-comparison').innerText(),/niepełne/);
    const row = page.locator(`#analysis-table [data-ref="${A}"]`);
    const segment = page.locator(`.analysis-alert-lane[data-ref="${A}"] [data-alert-state="red"]`).first();
    await segment.click();
    await page.waitForFunction(() => WiciWorkspace.getState().cursorAt && document.getElementById('analysis-card-title').textContent.includes('Alarm'));
    assert.equal(await row.getAttribute('data-alert-state'),'red');
    assert.equal(await page.locator(`#analysis-region-comparison [data-ref="${A}"]`).getAttribute('data-alert-state'),'red');
    await page.keyboard.press('Escape');
    await page.locator(`.analysis-alert-lane[data-ref="${A}"] [data-alert-state="unknown"]`).first().click();
    await page.waitForFunction(ref => document.querySelector(`#analysis-table [data-ref="${ref}"]`).dataset.alertState === 'unknown',A);
    await page.locator('#analysis-fit-regions').click();
    assert.ok(await page.evaluate(() => state.map.getBounds().contains([49.5,26.5]) && state.map.getBounds().contains([49.5,30.5])));
    const cursor = await page.evaluate(() => WiciWorkspace.getState().cursorAt);
    await page.locator('#analysis-timezone').selectOption('Europe/Kyiv');
    assert.equal(await page.evaluate(() => WiciWorkspace.getState().cursorAt),cursor);
    await page.locator('.analysis-saved-views summary').click();
    await page.locator('#analysis-view-name').fill('TEST porównanie Ukrainy');
    await page.getByRole('button',{name:'Zapisz nowe',exact:true}).click();
    await page.waitForFunction(() => document.getElementById('analysis-saved-view').options.length === 2);
    const saved = (await (await page.request.get(env.url+'/api/workspace/views')).json()).items[0];
    assert.deepEqual(saved.config.comparedRegionRefs,[A,B]);
    assert.equal(saved.config.displayTimezone,'Europe/Kyiv');
    await page.locator('#analysis-timezone').selectOption('UTC');
    await page.getByRole('button',{name:'Wyczyść regiony',exact:true}).click();
    const providerReads = () => env.reads.filter(read => read.path.startsWith('/api/ukraine')).length;
    const before = providerReads();
    await page.getByRole('button',{name:'Otwórz',exact:true}).click();
    await page.waitForFunction(() => WiciWorkspace.getState().comparedRegionRefs.length === 2 && !WiciWorkspace.getState().loading);
    assert.equal(await page.locator('#analysis-timezone').inputValue(),'Europe/Kyiv');
    await page.waitForTimeout(1200);
    assert.equal(providerReads(),before);
    assert.equal((await (await page.request.get(env.url+'/api/workspace/ukraine/recording')).json()).enabled,false);
    fs.mkdirSync(path.join(root,'tmp/v0320'),{recursive:true});
    await page.screenshot({path:path.join(root,'tmp/v0320/ukraine-comparison.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({path:path.join(root,'tmp/v0320/ukraine-mobile.png'),fullPage:true});
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Ukraine Analysis: region hierarchy and recording toggle remain independent from observation', {timeout:60000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await page.locator('#analysis-ua-oblast').selectOption(A); await settle(page);
    assert.ok((await page.locator('#analysis-ua-raion option').allTextContents()).includes('TEST Rejon A'));
    await page.locator('#analysis-ua-raion').selectOption('ua_region:neptun:raion:rejon-a'); await settle(page);
    assert.equal(await page.evaluate(() => WiciWorkspace.getState().query.region_ref),'ua_region:neptun:raion:rejon-a');
    await page.locator('#analysis-ukraine-recording summary').click();
    await page.locator('#analysis-ukraine-record-enabled').click();
    await page.waitForFunction(() => document.getElementById('analysis-ukraine-record-status').textContent.includes('Rejestracja włączona'));
    assert.equal((await (await page.request.get(env.url+'/api/workspace/ukraine/recording')).json()).enabled,true);
    await page.locator('#analysis-ukraine-record-enabled').click();
    await page.waitForFunction(() => !document.getElementById('analysis-ukraine-record-enabled').disabled);
    assert.equal((await (await page.request.get(env.url+'/api/workspace/ukraine/recording')).json()).enabled,false);
    await page.locator('[data-view="situation"]').click();
    await page.locator('[data-view="analysis"]').click();
    await settle(page);
    assert.equal(await page.locator('#analysis-country').inputValue(),'UA');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Ukraine Analysis: first opening loads boundaries and inactive regions with recording off', {timeout:60000}, async () => {
  const env = await setup({empty:true}), {page} = env;
  try {
    await page.waitForFunction(() => WiciWorkspace.getData()?.map?.located_total === 3);
    assert.ok(env.reads.some(read => read.path === '/api/ukraine/alerts'));
    assert.ok(env.reads.some(read => read.path === '/api/ukraine/geometry'));
    assert.equal(env.reads.some(read => read.path === '/api/ukraine'),false);
    await page.waitForFunction(() => document.getElementById('analysis-ua-oblast').options.length === 3);
    assert.equal((await (await page.request.get(env.url+'/api/workspace/ukraine/recording')).json()).enabled,false);
    assert.equal(await page.locator('#analysis-table [data-ref^="civil_alert:"]').count(),0);
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});
