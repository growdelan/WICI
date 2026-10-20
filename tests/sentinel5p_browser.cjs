// Real Leaflet/Chromium: synthetic Sentinel-5P + fixture GIOŚ, entirely offline.
// NODE_PATH=/path/to/node_modules node --test tests/sentinel5p_browser.cjs
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const {once}=require('node:events');
const net=require('node:net');
const path=require('node:path');
const {chromium}=require('playwright');
const {setTestTheme}=require('./browser_theme.cjs');
const root=path.resolve(__dirname,'..');
const theme=process.env.WICI_TEST_THEME||'light';
assert.ok(['light','dark'].includes(theme),'WICI_TEST_THEME must be light or dark');

async function server(){
 const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
 const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
 const python=spawnSync('uv',['run','python','-c','import sys; print(sys.executable)'],{cwd:root,encoding:'utf8'});
 assert.equal(python.status,0,python.stderr);
 const process=spawn(python.stdout.trim(),['-u','-c',`
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
import json
import httpx
from datetime import UTC, datetime
from wici.gios import GiosService
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-s5p-regression-') as root:
    app=create_app(demo=True, root=Path(root), config=Config(port=${port}))
    original=app.router.lifespan_context
    fixtures=Path('tests/fixtures/gios')
    def handler(request):
        name=('stations' if 'findAll' in request.url.path else 'sensors' if '/sensors/' in request.url.path
              else 'index' if '/getIndex/' in request.url.path else 'manual' if request.url.path.endswith('/9100') else 'data')
        return httpx.Response(400 if name=='manual' else 200, json=json.loads((fixtures/(name+'.json')).read_text()))
    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                app.state.gios=GiosService(client, lambda:datetime(2026,10,17,6,30,tzinfo=UTC))
                yield
    app.router.lifespan_context=lifespan
    uvicorn.run(app,
                host='127.0.0.1', port=${port}, log_level='error')
`],{cwd:root,stdio:['ignore','pipe','pipe']});
 let logs='';process.stdout.on('data',chunk=>logs+=chunk);process.stderr.on('data',chunk=>logs+=chunk);
 const url=`http://127.0.0.1:${port}`;
 try{
  for(let i=0;i<200;i++){
   if(process.exitCode!==null)throw new Error(logs);
   try{if((await fetch(url+'/api/health')).ok)return {url,async stop(){const exited=once(process,'exit');process.kill('SIGTERM');await exited;}};}catch{}
   await new Promise(resolve=>setTimeout(resolve,50));
  }
  throw new Error('Demo startup timeout: '+logs);
 }catch(error){process.kill('SIGTERM');throw error;}
}
for (const [name, viewport] of [['desktop', {width: 1440, height: 1000}], ['mobile', {width: 390, height: 844}]]) {
 test(`Sentinel-5P ${name}: regional rasters, GIOŚ, quality, dates, failures and cancellation`, {timeout: 60000}, async () => {
  const app = await server(); let browser;
  try {
   browser = await chromium.launch({headless: true});
   const page = await browser.newPage({viewport, hasTouch: name === 'mobile', isMobile: name === 'mobile'});
   await setTestTheme(page);
   const errors = [], external = [], reads = [];
   let searchMode = '', held = null, release, entered;
   page.on('pageerror', error => errors.push(error.message));
   await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== app.url) {external.push(url.href); return route.abort();}
    if (url.pathname.startsWith('/api/sentinel5p/')) reads.push(url.pathname);
    if (url.pathname === '/api/sentinel5p/search') {
     if (searchMode === 'empty') return route.fulfill({json: {status: 'ready', items: []}});
     if (searchMode === 'error') return route.fulfill({status: 429, headers: {'Retry-After': '8'}, json: {detail: 'Testowy limit CDSE'}});
    }
    if (url.pathname === '/api/sentinel5p/render' && held) {
     const response = await route.fetch(); entered(); await held; return route.fulfill({response});
    }
    return route.continue();
   });
   await page.goto(app.url);
   await page.locator('.province-card').first().waitFor();
   assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
   await page.waitForFunction(() => state.geometries.has('PL') && !state.map._animatingZoom);
   assert.deepEqual(reads, [], 'Inactive layer must not request even provider status');
   await page.locator('#layer-panel').evaluate(e => e.open = true);
   await page.locator('#s5p-group').evaluate(e => e.open = true);
   assert.equal(await page.locator('#s5p-enabled').isChecked(), false);
   await page.locator('#s5p-enabled').check();
   await page.waitForFunction(() => document.querySelector('#s5p-status').textContent.includes('DEMO'));
   await page.locator('#s5p-day').fill('2026-10-15');
   const selectObservation = async () => {
    await page.locator('#s5p-search').click();
    await page.waitForFunction(() => document.querySelector('#s5p-observation').options.length > 1);
    const id = await page.locator('#s5p-observation option').nth(1).getAttribute('value');
    await page.locator('#s5p-observation').selectOption(id);
    await page.locator('.leaflet-s5pData-pane img').waitFor({state: 'attached'});
    return id;
   };
   for (const parameter of ['no2', 'so2', 'aer_ai']) {
    await page.locator('#s5p-parameter').selectOption(parameter);
    const id = await selectObservation();
    assert.match(await page.locator('#s5p-detail').textContent(), /DEMO.*syntetyczne/);
    assert.ok((await page.locator('#s5p-detail').textContent()).includes(id));
    assert.match(await page.locator('#s5p-detail').textContent(), /2026-10-15/);
    assert.match(await page.locator('#s5p-detail').textContent(), /Wiek.*Czas pobrania/);
    assert.match(await page.locator('#s5p-legend-title').textContent(), parameter === 'aer_ai' ? /UVAI|aerozol/i : /mol/);
    assert.equal(await page.locator('.leaflet-s5pData-pane img').evaluate(e => getComputedStyle(e).imageRendering), 'pixelated');
   }
   await page.locator('#s5p-quality').check();
   await page.locator('#s5p-opacity').fill('40');
   assert.equal(await page.locator('.leaflet-s5pData-pane img').evaluate(e => e.style.opacity), '0.4');
   assert.equal(await page.locator('.leaflet-s5pQuality-pane img').evaluate(e => e.style.opacity), '0.4');
   await page.locator('#s5p-parameter').selectOption('no2');
   await selectObservation();
   // Separate units, station time and official station index remain usable beside the satellite raster.
   await page.locator('.layer-group').filter({has:page.locator('#gios-enabled')}).locator(':scope > summary').click();
   await page.locator('#gios-enabled').check();
   await page.locator('#gios-station option[value="9001"]').waitFor({state: 'attached'});
   await page.locator('#gios-station').selectOption('9001');
   await page.locator('#gios-sensor option[value="9101"]').waitFor({state: 'attached'});
   await page.locator('#gios-sensor').selectOption('9101');
   await page.waitForFunction(() => document.querySelector('#gios-detail').textContent.includes('12.5 µg/m³'));
   assert.equal(await page.locator('.leaflet-s5pData-pane img').count(), 1);
   assert.match(await page.locator('#s5p-legend-title').textContent(), /mol/);
   assert.match(await page.locator('#gios-detail').textContent(), /µg\/m³/);
   assert.equal(await page.locator('#s5p-day').inputValue(), '2026-10-15');
   await page.locator('#s5p-group').scrollIntoViewIfNeeded();
   await page.screenshot({path: `tmp/sentinel5p-${name}-controls${theme==='dark'?'-dark':''}.png`, fullPage: true});
   await page.locator('#layer-panel').evaluate(e => e.open = false);
   await page.evaluate(() => {state.map.stop(); state.map.fitBounds([[48,12],[56,26]], {animate:false});});
   await page.screenshot({path: `tmp/sentinel5p-${name}-map${theme==='dark'?'-dark':''}.png`, fullPage: true});
   assert.ok(await page.locator('#s5p-map-key').isVisible());
   assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
   // Publication navigation does not change the independent acquisition day or current raster.
   await page.locator('#previous-day').click();
   await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
   assert.equal(await page.locator('#s5p-day').inputValue(), '2026-10-15');
   assert.equal(await page.locator('.leaflet-s5pData-pane img').count(), 1);
   await page.locator('#layer-panel').evaluate(e => e.open = true);
   await page.locator('#s5p-day').fill('2026-10-14');
   await page.locator('#s5p-parameter').focus();
   assert.equal(await page.locator('.leaflet-s5pData-pane img').count(), 0);
   searchMode = 'empty'; await page.locator('#s5p-search').click();
   await page.waitForFunction(() => document.querySelector('#s5p-status').textContent.includes('Brak obserwacji'));
   assert.equal(await page.locator('#s5p-day').inputValue(), '2026-10-14');
   searchMode = 'error'; await page.locator('#s5p-search').click();
   await page.waitForFunction(() => document.querySelector('#s5p-status').textContent.includes('Retry-After'));
   assert.match(await page.locator('#s5p-status').textContent(), /8 s/);
   searchMode = ''; await page.locator('#s5p-search').click();
   await page.waitForFunction(() => document.querySelector('#s5p-observation').options.length > 1);
   held = new Promise(resolve => release = resolve);
   const pending = new Promise(resolve => entered = resolve);
   await page.locator('#s5p-observation').selectOption(await page.locator('#s5p-observation option').nth(1).getAttribute('value'));
   await pending; await page.locator('#s5p-enabled').uncheck(); release();
   await page.waitForTimeout(150);
   assert.equal(await page.locator('.leaflet-s5pData-pane img').count(), 0);
   assert.equal(await page.locator('#s5p-map-key').isHidden(), true);
   assert.equal(await page.locator('#gios-enabled').isChecked(), true);
   const count = reads.length; await page.waitForTimeout(150); assert.equal(reads.length, count);
   assert.deepEqual(errors, []); assert.deepEqual(external, []);
  } finally {if (browser) await browser.close(); await app.stop();}
 });
}
