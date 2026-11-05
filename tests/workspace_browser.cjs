'use strict';
const {revealControl, openFilters, closeFilters, openTools, closeTools, history24h} = require('./helpers/explorer_controls.cjs');
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');

async function setup({blockedStorage = false, instrumentMap = false} = {}) {
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
    if (instrumentMap) await page.addInitScript(() => {
      window.__mapRenders=[];window.__mapInRender=false;let factory;
      Object.defineProperty(window,'WiciWorkspaceMap',{configurable:true,get:()=>factory,set(value){factory=(...args)=>{
        const view=value(...args),render=view.render;
        view.render=(...args)=>{const start=performance.now();window.__mapInRender=true;
          try{return render(...args);}finally{window.__mapRenders.push(performance.now()-start);window.__mapInRender=false;}};
        return view;
      };}});
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

test('Analiza: coordinate-free station areas preserve live alarms and selected historical measurements in Leaflet', {timeout:60000}, async () => {
  const env=await setup(),{page}=env;
  try {
    const result=await page.evaluate(()=>{
      const now=Date.parse(state.health.now),iso=offset=>new Date(now+offset*60000).toISOString(), captured=[],original=L.geoJSON;
      L.geoJSON=(...args)=>{const layer=original(...args);captured.push(layer);return layer;};
      const view=WiciWorkspaceMap({map:state.map,geometries:state.geometries,select(){}});view.setActive(true);
      try {
        const measurement={value:500,metric:'water_level',unit:'cm',observed_at:iso(-10),thresholds:{warning_level_cm:300,alarm_level_cm:400}},hydro={ref:'hydro_station:imgw:without-coordinates',type:'hydro_station',label:'Wodowskaz',areas:[{admin_code:'14'}],measurement};
        const data={as_of:iso(0),map:{areas:[hydro]}},live={...WiciWorkspace.getState(),detailOpen:false,query:{time:{mode:'live'}}};
        const stroke=layer=>layer.getLayers()[0].getElement().getAttribute('stroke');
        view.render(data,live);const layer=captured[0],liveAlarm=stroke(layer);
        const selected={...live,detailOpen:true,selectedRef:hydro.ref,cursorAt:iso(-20),query:{time:{mode:'range',filter_range:{from:iso(-120),to:iso(1)}}}},sample={...measurement,value:350,observed_at:iso(-25)};
        view.render(data,selected,sample);const warningAtCursor=stroke(layer);
        view.render(data,selected,measurement);const futureSample=stroke(layer);
        const gios={ref:'air_quality_station:gios:1',type:'air_quality_station',label:'GIOŚ',areas:[{admin_code:'14'}],official_index:{value:5,observed_at:iso(-10)},measurement:{value:999}},gdata={as_of:iso(0),map:{areas:[gios]}},gstate={...selected,selectedRef:gios.ref};
        view.render(gdata,gstate,{value:999},{value:0,observed_at:iso(-25)},null,null,{nodes:[gios]});const graph=captured.at(-1),graphIndex=stroke(graph);
        view.render(gdata,gstate,{value:0},null,null,null,{nodes:[gios]});const missingIndex=stroke(graph);
        return {liveAlarm,warningAtCursor,futureSample,graphIndex,missingIndex};
      } finally {L.geoJSON=original;view.destroy();}
    });
    assert.deepEqual(result,{liveAlarm:'#bc4145',warningAtCursor:'#b78a28',futureSample:'#7e8990',graphIndex:'#459a77',missingIndex:'#7e8990'});
    assert.deepEqual(env.errors,[]);assert.deepEqual(env.upstream,[]);
  } finally {await env.close();}
});

test('Analiza: real cursor inputs do not regroup 999 communications sharing ten PRG counties', {timeout:60000}, async () => {
  const env=await setup({instrumentMap:true}),{page}=env;
  try {
    const counties=await page.evaluate(()=>[...state.geometries.keys()].filter(code=>code.length===4).slice(0,10));assert.equal(counties.length,10);
    await page.route('**/api/workspace/query',async route=>{
      const response=await route.fetch(),result=await response.json(),station=result.map?.points?.find(item=>item.ref==='hydro_station:imgw:demo-wisla');
      if(!station)return route.fulfill({json:result});
      const areas=Array.from({length:999},(_,i)=>({ref:`communication:${50000+i}`,type:'communication',label:`Syntetyczny komunikat ${i}`,metadata:{},areas:counties.map(admin_code=>({admin_code}))}));
      return route.fulfill({json:{...result,total:1000,next_cursor:null,items:[station,...areas.slice(0,99)],map:{mode:'objects',points:[station],areas,aggregates:[],total:1000,located_total:1000,unlocated_total:0}}});
    });
    await openFilters(page);
    await page.locator('[data-object-type="hydro_station"]').click();await settle(page);
    await page.evaluate(()=>WiciWorkspace.selectObject('hydro_station:imgw:demo-wisla'));
    await history24h(page);await settle(page);
    // Drain the source manager's already scheduled one-second catalogue refresh
    // before measuring repeated cursor inputs on an unchanged response.
    await page.waitForFunction(()=>WiciWorkspaceSources.pendingCount===0);
    await page.waitForTimeout(1100);await settle(page);
    await page.waitForFunction(()=>!document.getElementById('analysis-cursor').disabled);
    const result=await page.evaluate(async()=>{
      const source=WiciWorkspace.getData().map.areas;window.__membershipReads=0;window.__identifierReads=0;
      for(const item of source){const areas=item.areas,ref=item.ref;
        Object.defineProperty(item,'areas',{get(){if(window.__mapInRender)window.__membershipReads++;return areas;}});
        Object.defineProperty(item,'ref',{get(){if(window.__mapInRender)window.__identifierReads++;return ref;}});
      }
      window.__mapRenders=[];
      const cursor=document.getElementById('analysis-cursor');
      for(let i=0;i<40;i++){cursor.value=String(i*25);cursor.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));}
      const times=window.__mapRenders.slice().sort((a,b)=>a-b);
      return {sameSource:source===WiciWorkspace.getData().map.areas,membershipReads:window.__membershipReads,identifierReads:window.__identifierReads,renders:times.length,median_ms:times[Math.floor(times.length/2)],p95_ms:times[Math.min(times.length-1,Math.floor(times.length*.95))]};
    });
    assert.equal(result.sameSource,true);assert.ok(result.renders>=40);assert.equal(result.membershipReads,0);assert.equal(result.identifierReads,0);
    console.log('Shared-area cursor map render:',JSON.stringify(result));
    assert.deepEqual(env.errors,[]);assert.deepEqual(env.upstream,[]);
  } finally {await env.close();}
});

test('Analiza: cursor updates only the selected station row and preserves unrelated source coverage', {timeout:60000}, async () => {
  const env=await setup(), {page}=env;
  try {
    await openFilters(page);
    await page.locator('[data-object-type="hydro_station"]').click();
    await openFilters(page);
    await page.locator('[data-object-type="air_quality_station"]').click();await settle(page);
    const refs=await page.evaluate(()=>WiciWorkspace.getData().items.filter(item=>item.type.endsWith('_station')).map(item=>item.ref));
    assert.ok(refs.length>=2);
    assert.equal(await page.evaluate(()=>Object.hasOwn(WiciWorkspace.getData().map,'items')),false);
    const selected=refs.find(ref=>ref.startsWith('hydro_station:')), other=refs.find(ref=>ref!==selected);
    await page.evaluate(ref=>WiciWorkspace.selectObject(ref),selected);
    await history24h(page);await settle(page);
    await page.waitForFunction(()=>!document.getElementById('analysis-cursor').disabled);
    await page.evaluate(({selected,other})=>{
      const row=ref=>[...document.querySelectorAll('#analysis-table tr[data-ref]')].find(item=>item.dataset.ref===ref);
      window.__rowBefore=row(other);window.__rowChanges=0;window.__selectedChanges=0;window.__coverageChanges=0;
      new MutationObserver(records=>window.__rowChanges+=records.length).observe(__rowBefore,{subtree:true,childList:true,attributes:true,characterData:true});
      new MutationObserver(records=>window.__selectedChanges+=records.length).observe(row(selected),{subtree:true,childList:true,attributes:true,characterData:true});
      new MutationObserver(records=>window.__coverageChanges+=records.length).observe(document.querySelector('.analysis-source-coverage'),{subtree:true,childList:true,characterData:true});
      const cursor=document.getElementById('analysis-cursor');cursor.value='500';cursor.dispatchEvent(new Event('input',{bubbles:true}));
    },{selected,other});
    await page.waitForFunction(()=>WiciWorkspace.getState().cursorAt!==null);
    await page.evaluate(()=>new Promise(requestAnimationFrame));
    const result=await page.evaluate(other=>({sameRow:[...document.querySelectorAll('#analysis-table tr[data-ref]')].find(item=>item.dataset.ref===other)===__rowBefore,otherChanges:__rowChanges,selectedChanges:__selectedChanges,coverageChanges:__coverageChanges}),other);
    assert.equal(result.sameRow,true);assert.equal(result.otherChanges,0);assert.equal(result.coverageChanges,0);assert.ok(result.selectedChanges>0);
    assert.deepEqual(env.errors,[]);assert.deepEqual(env.upstream,[]);
  } finally {await env.close();}
});

test('Analiza: a filter click preserves a pending search and restoring a view cancels it', {timeout:60000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await openTools(page);
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
    await openFilters(page);
    await page.locator('[data-object-type="hydro_station"]').click(); await settle(page);
    await openFilters(page);
    await page.locator('[data-object-type="communication"]').click(); await settle(page);
    await page.waitForFunction(() => WiciWorkspace.getData().total === 2);
    await page.locator('[data-ref="hydro_station:imgw:demo-wisla"] .analysis-object-link').click();
    await page.locator('#analysis-card-title').filter({hasText:'DEMO: wodowskaz Wisła'}).waitFor();
    assert.match(await page.locator('.analysis-reading').innerText(), /274/);
    await history24h(page); await settle(page);
    await page.waitForFunction(() => !document.getElementById('analysis-cursor').disabled);
    await page.locator('#analysis-cursor').evaluate(input => {input.value = '500'; input.dispatchEvent(new Event('input', {bubbles:true}));});
    await page.waitForFunction(() => WiciWorkspace.getState().cursorAt !== null);
    assert.match(await page.locator('[data-ref="hydro_station:imgw:demo-wisla"]').innerText(), /Według kursora/);
    const before = await page.evaluate(() => ({time:WiciWorkspace.getState().query.time, cursor:WiciWorkspace.getState().cursorAt, map:state.map.getCenter()}));
    await openTools(page); await page.locator('#analysis-refresh').click(); await page.locator('#analysis-tools > summary').click(); await settle(page);
    assert.deepEqual(await page.evaluate(() => ({time:WiciWorkspace.getState().query.time, cursor:WiciWorkspace.getState().cursorAt, map:state.map.getCenter()})), before);
    await page.keyboard.press('Escape'); await page.locator('#analysis-card').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('analysis-object-link')), true);
    await openTools(page);
    await page.locator('.analysis-saved-views summary').click();
    await page.locator('#analysis-view-name').fill('Wisła — próba stanowiska');
    await page.getByRole('button', {name:'Zapisz nowe', exact:true}).click();
    await page.waitForFunction(() => document.getElementById('analysis-saved-view').options.length === 2);
    await page.locator('#analysis-search').fill('nieistniejąca-stacja');
    await page.waitForFunction(() => WiciWorkspace.getData().total === 0);
    await page.getByRole('button', {name:'Otwórz', exact:true}).click();
    await page.waitForFunction(() => WiciWorkspace.getData().total === 2);
    await openTools(page);
    await page.locator('.analysis-saved-views summary').click();
    await closeTools(page); await closeFilters(page);
    // Restoring a saved selection opens its inspector; close the mobile dialog
    // before using controls on the work surface underneath it.
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
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
    await openFilters(page);
    await page.locator('[data-object-type="air_quality_station"]').click();
    await openFilters(page);
    await page.locator('[data-object-type="communication"]').click();
    await page.waitForFunction(() => WiciWorkspace.getData().total === 1);
    await closeFilters(page);
    await page.evaluate(() => {
      const target = [];
      state.map.eachLayer(layer => {if ((layer instanceof L.CircleMarker || layer instanceof L.Marker) && layer.getTooltip()?.getContent()?.textContent.includes('DEMO: jakość powietrza')) target.push(layer);});
      if (target.length !== 1) throw new Error(`Expected one catalogue station, got ${target.length}`);
      target[0].fire('click');
    });
    await page.locator('#analysis-card-title').filter({hasText:'DEMO: jakość powietrza'}).waitFor();
    assert.equal(await page.locator('#analysis-sensor option').count(), 3);
    await page.locator('#analysis-sensor').selectOption('9000012');
    await page.waitForFunction(() => document.querySelector('.analysis-reading')?.textContent.includes('26'));
    await history24h(page); await settle(page);
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
