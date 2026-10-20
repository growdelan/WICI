// Real browser, offline DEMO with no remote resources. Run against port 8773 or WICI_UI_URL.
const assert = require('node:assert/strict');
require('node:fs').mkdirSync('tmp/quality-ui',{recursive:true});
const {chromium} = require('playwright');
const base=process.env.WICI_UI_URL||'http://127.0.0.1:8773';
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[], external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>{if(!r.request().url().startsWith(base+'/')){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.goto(base);
  await page.locator('.province-card').first().waitFor();
  assert.equal(await page.locator('#quality-enabled').isChecked(),false);
  await page.locator('#layer-panel > summary').click();
  const aviation=page.locator('details.layer-group').filter({has:page.locator('#aircraft-enabled')});
  if((await aviation.getAttribute('open'))===null)await aviation.locator(':scope > summary').click();
  await page.locator('#quality-enabled').check();
  await page.waitForFunction(()=>document.querySelector('#quality-status').textContent.includes('DEMO'));
  assert.match(await page.locator('#quality-status').innerText(),/syntetyczne/);
  assert.ok(await page.locator('#quality-window option').count()>10);
  await page.waitForFunction(()=>document.querySelector('#quality-summary').textContent.includes('anomalie 1'));
  // History map is drawn by real Leaflet, and its popup carries the sample and field availability.
  const qualityPath=page.locator('path.leaflet-interactive[fill="#c53535"]');
  await qualityPath.first().click();
  await page.locator('.leaflet-popup-content').waitFor();
  assert.match(await page.locator('.leaflet-popup-content').innerText(),/różne samoloty: 6/);
  assert.match(await page.locator('.leaflet-popup-content').innerText(),/Dostępność pól/);
  assert.match(await page.locator('.leaflet-popup-content').innerText(),/Źródło: DEMO \(syntetyczne\)/);
  assert.match(await page.locator('.leaflet-popup-content').innerText(),/Porównanie wyłącznie w obrębie tego samego okresu źródła/);
  await page.locator('.leaflet-popup-close-button').click();
  await page.locator('.leaflet-popup').waitFor({state:'detached'});
  if((await page.locator('#layer-panel').getAttribute('open'))===null)await page.locator('#layer-panel > summary').click();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/position-quality?')&&r.url().includes('hours=48')),page.locator('#quality-hours').selectOption('48')]);
  await page.locator('#quality-enabled').uncheck();
  assert.equal(await page.locator('path.leaflet-interactive[fill="#c53535"]').count(),0);
  await page.locator('#quality-enabled').check();
  await page.waitForFunction(()=>document.querySelector('#quality-summary').textContent.includes('anomalie 1'));
  await page.locator('#quality-method').evaluate(e=>e.parentElement.open=true);
  await page.locator('#layer-panel').evaluate(e=>e.open=false);
  await page.screenshot({path:'tmp/quality-ui/desktop.png',fullPage:true});
  await page.locator('.filter-options > summary').click();
  await page.locator('#province').selectOption('32');
  await page.waitForFunction(()=>document.querySelector('#quality-summary').textContent.includes('Brak zapisanych'));
  await page.locator('#province').selectOption('14');
  await page.waitForFunction(()=>document.querySelector('#quality-summary').textContent.includes('anomalie 1'));
  await page.locator('#previous-day').click();
  await page.waitForFunction(()=>document.querySelector('#quality-summary').textContent.includes('Brak zapisanych'));
  await page.locator('#today').click();
  await page.waitForFunction(()=>document.querySelector('#quality-summary').textContent.includes('anomalie 1'));
  await page.setViewportSize({width:390,height:844});
  await page.locator('#layer-panel > summary').click();
  await page.locator('#quality-latest').scrollIntoViewIfNeeded();
  await page.screenshot({path:'tmp/quality-ui/mobile.png',fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  // Source problems retain historical classifications but visibly mark the map as unavailable now.
  const original=await (await page.request.get(base+'/api/position-quality?hours=24')).json();
  let sourceState='error';
  await page.route('**/api/position-quality?**',r=>r.fulfill({json:{...original,status:sourceState,status_label:sourceState==='error'?'Błąd źródła':'Dane nieaktualne'}}));
  await page.locator('#quality-hours').selectOption('24');
  await page.waitForFunction(()=>document.querySelector('#quality-status').textContent.includes('Błąd źródła'));
  assert.equal(await page.locator('path.leaflet-interactive[stroke="#9a6639"]').count(),1);
  sourceState='stale';await page.locator('#quality-hours').selectOption('48');
  await page.waitForFunction(()=>document.querySelector('#quality-status').textContent.includes('Dane nieaktualne'));
  assert.equal(await page.locator('path.leaflet-interactive[stroke-dasharray="5 5"]').count(),1);
  // Advance a real browser clock: automatic polling must follow new complete windows,
  // preserve a manual choice, and retain fetch errors until a successful response.
  const live=await browser.newPage({viewport:{width:1440,height:1000}});
  live.on('pageerror',e=>errors.push(e.message));
  await live.clock.install();
  let phase=0,failRead=false;
  const latest=Math.max(...original.items.filter(i=>i.window_end<=original.window_end).map(i=>i.window_start));
  await live.route('**/*',r=>{if(!r.request().url().startsWith(base+'/')){external.push(r.request().url());return r.abort();}return r.continue();});
  await live.route('**/api/position-quality?**',r=>{
    if(failRead)return r.abort('failed');
    const delta=phase*300;
    return r.fulfill({json:{...original,window_start:original.window_start+delta,window_end:original.window_end+delta,
      items:original.items.map(i=>({...i,window_start:i.window_start+delta,window_end:i.window_end+delta,last_observed:i.last_observed+delta}))}});
  });
  await live.goto(base);await live.locator('.province-card').first().waitFor();
  await live.locator('#layer-panel > summary').click();
  await live.locator('details.layer-group').filter({has:live.locator('#aircraft-enabled')}).locator(':scope > summary').click();
  await live.locator('#quality-enabled').check();
  const selected=async expected=>live.waitForFunction(t=>document.querySelector('#quality-window').value===String(t),expected);
  await selected(latest);
  phase=1;await live.clock.fastForward(60000);await selected(latest+300);
  await live.locator('#quality-window').selectOption(String(latest));
  phase=2;await live.clock.fastForward(60000);
  await live.waitForFunction(t=>[...document.querySelector('#quality-window').options].some(o=>o.value===String(t)),latest+600);
  assert.equal(await live.locator('#quality-window').inputValue(),String(latest));
  assert.match(await live.locator('#quality-follow').innerText(),/Ręcznie/);
  await live.locator('#quality-latest').click();await selected(latest+600);
  failRead=true;await live.clock.fastForward(60000);
  await live.waitForFunction(()=>document.querySelector('#quality-status').textContent.includes('Błąd odczytu'));
  await live.locator('#quality-window').selectOption(String(latest));
  assert.match(await live.locator('#quality-status').innerText(),/Błąd odczytu/);
  assert.equal(await live.locator('path.leaflet-interactive[stroke="#9a6639"]').count(),1);
  await live.locator('#quality-latest').click();
  assert.match(await live.locator('#quality-status').innerText(),/Błąd odczytu/);
  failRead=false;phase=3;await live.clock.fastForward(60000);await selected(latest+900);
  assert.equal((await live.locator('#quality-status').innerText()).includes('Błąd'),false);
  assert.match(await live.locator('#quality-follow').innerText(),/Śledzenie/);
  await live.close();
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('Position quality browser: map, popup, offline, filters, history, desktop/mobile passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
