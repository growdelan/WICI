// Real Chromium/Leaflet, synthetic NEPTUN payloads, isolated offline DEMO server.
// NODE_PATH=/path/to/node_modules node --test tests/ukraine_browser.cjs
'use strict';
const {setTestTheme} = require('./browser_theme.cjs');
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');

async function server() {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const process = spawn(path.join(root, '.venv/bin/python'), ['-u', '-c', `
import tempfile
from pathlib import Path
import httpx, uvicorn
from wici.app import create_app
from wici.config import Config
def forbidden(request):
    raise AssertionError('External network forbidden: '+str(request.url))
with tempfile.TemporaryDirectory(prefix='wici-ukraine-browser-') as directory:
    client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    app=create_app(demo=True,root=Path(directory),config=Config(port=${port}),client=client)
    uvicorn.run(app,host='127.0.0.1',port=${port},log_level='error')
`], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  let logs = ''; process.stdout.on('data', b => logs += b); process.stderr.on('data', b => logs += b);
  const url = `http://127.0.0.1:${port}`;
  try {
    for (let i = 0; i < 200; i++) {
      if (process.exitCode !== null) throw new Error(logs);
      try { if ((await fetch(url + '/api/health')).ok) return {url, async stop() {
        const ended = once(process, 'exit'); process.kill('SIGTERM'); await ended;
      }}; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error('DEMO startup timed out: ' + logs);
  } catch (error) { process.kill('SIGTERM'); throw error; }
}
const polygon = (key, name, bounds, hole) => ({type:'Feature',properties:{key,region:name,rayon:name},geometry:{type:'Polygon',coordinates:[
  [[bounds[0],bounds[1]],[bounds[2],bounds[1]],[bounds[2],bounds[3]],[bounds[0],bounds[3]],[bounds[0],bounds[1]]],
  ...(hole ? [hole] : [])
]}});
const featureCollection = features => ({type:'FeatureCollection',features});
const syntheticGeometry = () => ({status:'ready',fetched_at:new Date().toISOString(),message:'',
  oblasts:featureCollection([polygon('test-oblast','Syntetyczny obwód testowy',[26,47,34,51],[[30,49],[31,49],[31,50],[30,50],[30,49]])]),
  raions:featureCollection([polygon('test-raion','Syntetyczny rejon testowy',[27,48,29,50])])});
function syntheticSnapshot() {
  const now = new Date().toISOString();
  const report = {type:'uav',title:'Syntetyczne doniesienie testowe',region:'Syntetyczny obwód testowy',district:'',locality:'Test',updated_at:now,status:'active',advisory:false,area_only:false,position_quality:'approx',uncertainty_km:4,confidence:'medium',source_count:2,count:1,description:'Wyłącznie test UI, nie rzeczywiste zgłoszenie.'};
  return {status:'ready',demo:false,refresh_seconds:15,retry_after_seconds:15,message:'DANE SYNTETYCZNE — test interfejsu',
    alerts:{status:'ready',fetched_at:now,updated_at:now,stale:false,error:null,items:[
      {scope:'raion',key:'test-raion',name:'Syntetyczny rejon testowy',oblast:'Test',level:'red',since:now,reasons:['Test alarmu']},
      {scope:'oblast',key:'test-oblast',name:'Syntetyczny obwód testowy',oblast:'',level:'yellow',since:now,reasons:[]},
      {scope:'raion',key:'unmapped',name:'Test bez geometrii',oblast:'Test',level:'red',since:now,reasons:[]}
    ]},
    threats:{status:'ready',fetched_at:now,server_time:now,stale:false,error:null,items:[
      {...report,id:'point',latitude:48.7,longitude:28},
      {...report,id:'advisory',type:'recon',latitude:50.4,longitude:32,advisory:true},
      {...report,id:'area',area_only:true,latitude:null,longitude:null},
      {...report,id:'outside',latitude:52,longitude:38},
      {...report,id:'hole',latitude:49.5,longitude:30.5}
    ]}};
}
async function open(page, url) {
  await page.goto(url);
  await page.locator('.province-card').first().waitFor();
  await page.waitForFunction(() => state.map && !state.map._animatingZoom);
  await page.locator('#layer-panel').evaluate(e => e.open = true);
  await page.locator('#ukraine-group').evaluate(e => e.open = true);
}

test('NEPTUN real DEMO stays offline and exposes its empty state', {timeout:30000}, async () => {
  const app = await server(); let browser;
  try {
    browser = await chromium.launch({headless:true}); const page = await browser.newPage();
    await setTestTheme(page);
    const external = [], reads = [], errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== app.url) { external.push(url.href); return route.abort(); }
      if (url.pathname.startsWith('/api/ukraine')) reads.push(url.pathname);
      return route.continue();
    });
    await open(page, app.url); assert.equal(await page.locator('#ukraine-enabled').isChecked(),false);
    await page.locator('#ukraine-enabled').check();
    await page.waitForFunction(() => document.querySelector('#ukraine-status').textContent.includes('demonstracji'));
    assert.equal(await page.locator('.ukraine-report-marker').count(),0);
    assert.deepEqual(reads,[]); assert.deepEqual(external,[]); assert.deepEqual(errors,[]);
    const response = await page.request.get(app.url+'/api/ukraine');
    assert.equal((await response.json()).status,'demo_no_data');
  } finally { if(browser)await browser.close(); await app.stop(); }
});

for (const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
  test(`NEPTUN ${name}: areas, report semantics, unmapped records, lifecycle and failures`, {timeout:60000}, async () => {
    const app = await server(); let browser;
    try {
      browser = await chromium.launch({headless:true});
      const page = await browser.newPage({viewport,isMobile:name==='mobile',hasTouch:name==='mobile'});
    await setTestTheme(page);
      const errors = [], external = [], reads = []; let fail = false, live = false, hold = null, entered, release;
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.origin !== app.url) {external.push(url.href); return route.abort();}
        if(url.pathname==='/api/health' && live) {const response=await route.fetch(); const data=await response.json(); return route.fulfill({json:{...data,mode:'live'}});}
        if(url.pathname.startsWith('/api/ukraine'))reads.push(url.pathname);
        if(url.pathname==='/api/ukraine/geometry')return route.fulfill({json:syntheticGeometry()});
        if(url.pathname==='/api/ukraine') {
          if(hold) {entered(); await hold;}
          return fail ? route.fulfill({status:503,json:{detail:'Test awarii NEPTUN'}}) : route.fulfill({json:syntheticSnapshot()});
        }
        return route.continue();
      });
      await open(page,app.url); assert.deepEqual(reads,[]);
      live=true;
      await page.evaluate(() => {document.querySelector('#osm-enabled').checked=false; window.WiciUkraine.sync({health:{mode:'live'},visible:true});});
      await page.locator('#ukraine-enabled').check();
      await page.waitForFunction(() => document.querySelectorAll('.ukraine-report-marker').length===2);
      assert.equal(await page.locator('.leaflet-ukraineRaionAlerts-pane path').count(),1);
      assert.equal(await page.locator('.leaflet-ukraineOblastAlerts-pane path').count(),1);
      assert.match(await page.locator('#ukraine-status').textContent(),/Alarmy bez geometrii: 1/);
      assert.match(await page.locator('#ukraine-list').textContent(),/obszarowe|obszaru/);
      assert.match(await page.locator('#ukraine-list').textContent(),/poza geometrią/);
      assert.equal(await page.locator('.leaflet-control-attribution a[href="https://neptun.in.ua/"]').count(),1);
      assert.ok(await page.evaluate(() => state.map.getBounds().contains([49,31]) && state.map.getBounds().contains([52,19])));
      await page.locator('#ukraine-reports-panel').evaluate(e=>e.open=true);
      await page.locator('#ukraine-list details').first().evaluate(e=>e.open=true);
      await page.locator('#ukraine-list details summary').first().focus();
      assert.equal(await page.locator('#ukraine-list details summary').first().evaluate(e=>e===document.activeElement),true);
      // An ordinary refresh must keep the user's open details and map position.
      await page.evaluate(() => state.map.setView([49,29],7,{animate:false}));
      const center=await page.evaluate(()=>[state.map.getCenter().lat,state.map.getCenter().lng]);
      const previous=reads.length;
      await page.waitForFunction(() => document.querySelectorAll('.ukraine-report-marker').length===2);
      await page.waitForTimeout(15500);
      assert.ok(reads.length>previous);
      assert.equal(await page.locator('#ukraine-list details').first().evaluate(e=>e.open),true);
      assert.equal(await page.locator('#ukraine-list details summary').first().evaluate(e=>e===document.activeElement),true);
      assert.deepEqual(await page.evaluate(()=>[state.map.getCenter().lat,state.map.getCenter().lng]),center);
      fs.mkdirSync(path.join(root,'tmp'),{recursive:true});
      await page.locator('#ukraine-fit').click();
      await page.screenshot({path:path.join(root,`tmp/ukraine-${name}-controls.png`),fullPage:true});
      await page.locator('#layer-panel').evaluate(e=>e.open=false);
      assert.equal(await page.locator('#ukraine-map-label').isVisible(),true);
      await page.locator('.map-legend').evaluate(e=>e.open=true);
      assert.equal(await page.locator('#ukraine-map-legend').isVisible(),true);
      await page.locator('.map-legend').evaluate(e=>e.open=false);
      await page.screenshot({path:path.join(root,`tmp/ukraine-${name}-map.png`),fullPage:true});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      // Hiding the view removes layers and stops request scheduling.
      await page.evaluate(()=>window.WiciUkraine.sync({visible:false}));
      assert.equal(await page.locator('.ukraine-report-marker').count(),0);
      const hiddenReads=reads.length; await page.waitForTimeout(100); assert.equal(reads.length,hiddenReads);
      fail=true;
      await page.evaluate(()=>window.WiciUkraine.sync({visible:true}));
      await page.waitForFunction(()=>document.querySelector('#ukraine-status').textContent.includes('nieaktualny'));
      assert.equal(await page.locator('.ukraine-report-marker').count(),0);
      assert.equal(await page.locator('.leaflet-ukraineRaionAlerts-pane path').first().getAttribute('fill'),'#71818b');
      // A delayed response cannot restore disabled layers.
      await page.locator('#layer-panel').evaluate(e=>e.open=true);
      await page.locator('#ukraine-enabled').uncheck(); fail=false;
      hold=new Promise(resolve=>release=resolve); const pending=new Promise(resolve=>entered=resolve);
      await page.locator('#ukraine-enabled').check(); await pending;
      await page.locator('#ukraine-enabled').uncheck(); release(); hold=null;
      await page.waitForTimeout(150);
      assert.equal(await page.locator('.ukraine-report-marker').count(),0);
      assert.equal(await page.locator('.leaflet-ukraineBorders-pane path').count(),0);
      assert.equal(await page.locator('#ukraine-map-label').isHidden(),true);
      assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    } finally {if(browser)await browser.close(); await app.stop();}
  });
}
