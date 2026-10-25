'use strict';
// Real dossiers APIs/SQLite on an isolated temporary server. No live database or external network.
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'tmp/dossiers-workspace-evidence');
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
    const context = await browser.newContext({viewport:{width:1440, height:1000}});
    await context.route('**/*', async route => {
      const requestURL = new URL(route.request().url()); reads.push(requestURL.pathname);
      if (requestURL.origin !== url) {external.push(requestURL.href); return route.abort();}
      // Station fixtures stay synthetic; transport uses the actual local collector with test feeds.
      if (requestURL.pathname === '/api/health') {
        const response = await route.fetch();
        return route.fulfill({json:{...await response.json(), mode:'live'}});
      }
      return route.continue();
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.stack || error.message));
    await page.goto(url);
    await startAnalysis(page);
    const headers = {'Origin':url, 'X-CSRF-Token':await page.evaluate(() => state.health.csrf_token)};
    return {page, context, url, errors, external, reads, headers,
      async api(method, pathname, data) {
        const response = await context.request.fetch(url+'/api/workspace'+pathname, {method, headers, data});
        assert.ok(response.ok(), `${method} ${pathname}: ${response.status()} ${await response.text()}`);
        return response.status() === 204 ? null : response.json();
      },
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
async function startAnalysis(page) {
  await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
  if (!(await page.locator('#analysis-table').isVisible())) await page.locator('[data-view="analysis"]').click();
  await settle(page);
}
async function types(page, selected) {
  // Add desired types first: the UI deliberately never permits an empty type set.
  for (const desired of [true,false]) for (const button of await page.locator('[data-object-type]').all()) {
    const wanted = selected.includes(await button.getAttribute('data-object-type'));
    if (wanted === desired && (await button.getAttribute('aria-pressed') === 'true') !== wanted) await button.click();
  }
  await settle(page);
  assert.deepEqual(await page.evaluate(() => [...WiciWorkspace.getState().query.types].sort()),[...selected].sort());
}
async function card(page, ref) {
  const label = await page.evaluate(ref => WiciWorkspace.getData().items.find(item => item.ref === ref)?.label, ref);
  await page.locator(`#analysis-table [data-ref="${ref}"] .analysis-object-link`).click();
  await page.waitForFunction(({ref,label}) => WiciWorkspace.getState().selectedRef === ref && document.getElementById('analysis-card-title').textContent === label, {ref,label});
}
async function closeCard(page) {
  await page.keyboard.press('Escape'); await page.locator('#analysis-card').waitFor({state:'hidden'});
}
async function historyRange(env) {
  const history = await (await env.context.request.get(env.url+'/_test/history')).json();
  const range = {from:history.range.from,to:new Date(Date.parse(history.range.to)+60000).toISOString()};
  const fields = await env.page.evaluate(range => ({from:WiciWorkspaceTimeline.localValue(range.from),to:WiciWorkspaceTimeline.localValue(range.to)}), range);
  await env.page.locator('#analysis-time-from').fill(fields.from);
  await env.page.locator('#analysis-time-to').fill(fields.to);
  await env.page.getByRole('button',{name:'Ustaw przedział',exact:true}).click();
  await settle(env.page);
  return range;
}

async function openDossiers(page) {
  if (!(await page.locator('#analysis-dossiers').evaluate(element => element.open))) await page.locator('#analysis-dossiers > summary').click();
}
async function mutation(page, method, suffix, act) {
  const response = page.waitForResponse(response => response.request().method() === method && new URL(response.url()).pathname.endsWith(suffix));
  await act();
  const result = await response;
  assert.ok(result.ok(), `${method} ${suffix}: ${result.status()} ${await result.text()}`);
  await page.waitForFunction(() => document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy') !== 'true');
  return result.status() === 204 ? null : result.json();
}
async function createDossier(page, name, description = '') {
  await openDossiers(page);
  await page.locator('#analysis-dossier-new').click();
  await page.locator('#analysis-dossier-dialog').waitFor({state:'visible'});
  await page.locator('#analysis-dossier-name').fill(name);
  await page.locator('#analysis-dossier-description').fill(description);
  return mutation(page, 'POST', '/workspace/dossiers', () => page.locator('#analysis-dossier-save').click());
}
async function openDossier(page, id) {
  await openDossiers(page);
  await page.locator('#analysis-dossier-select').selectOption(id);
  await page.locator('#analysis-dossier-open').click();
  await page.locator('#analysis-dossier-dialog').waitFor({state:'visible'});
  await page.locator('#analysis-dossier-delete').waitFor({state:'visible'});
}
async function closeDossier(page) {
  await page.locator('#analysis-dossier-close').click();
  await page.locator('#analysis-dossier-dialog').waitFor({state:'hidden'});
}
async function confirmDelete(page) {
  await page.locator('#analysis-dossier-confirm').getByRole('button',{name:'Usuń trwale',exact:true}).click();
}
async function seek(page, at) {
  const value = await page.evaluate(at => WiciWorkspaceTimeline.localValue(at), at);
  await page.locator('#analysis-cursor-date').fill(value);
  await page.locator('#analysis-cursor-date').dispatchEvent('change');
  await page.waitForFunction(at => Date.parse(WiciWorkspace.getState().cursorAt) === Date.parse(at), at);
}

test('Teczki: create, notes and pins survive reload; dossiers isolate content and delete deliberately', {timeout:120000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await types(page,['aircraft']);
    await card(page,aircraft); await closeCard(page);
    const dossier = await createDossier(page,'Analiza lotu','Obserwacje na podstawie lokalnych danych.');
    await mutation(page,'POST',`/dossiers/${dossier.id}/pins`,() => page.locator('#analysis-dossier-pin-selected').click());
    await page.locator(`#analysis-dossier-pins [data-ref="${aircraft}"]`).waitFor();
    const literal = '<img src=x onerror="window.dossierXSS=true"> To jest notatka analityka.';
    await page.locator('#analysis-dossier-note-body').fill(literal);
    const note = await mutation(page,'POST',`/dossiers/${dossier.id}/notes`,() => page.locator('#analysis-dossier-note-save').click());
    const noteRow = page.locator(`#analysis-dossier-notes [data-note-id="${note.id}"]`);
    await noteRow.waitFor();
    assert.ok((await noteRow.innerText()).includes(literal),'user text is preserved verbatim');
    assert.equal(await noteRow.locator('img').count(),0,'note HTML is never executed');
    assert.equal(await page.evaluate(() => window.dossierXSS),undefined);
    await noteRow.getByRole('button',{name:'Edytuj',exact:true}).click();
    await page.locator('#analysis-dossier-note-body').fill(literal+' Dopisek po weryfikacji.');
    await mutation(page,'PUT',`/notes/${note.id}`,() => page.locator('#analysis-dossier-note-save').click());
    await page.locator('#analysis-dossier-name').fill('Lot — ustalenia');
    await mutation(page,'PUT',`/dossiers/${dossier.id}`,() => page.locator('#analysis-dossier-save').click());
    await page.locator('#analysis-material-title').fill('Karta lotu przed porównaniem');
    const material = await mutation(page,'POST',`/dossiers/${dossier.id}/materials`,() => page.locator('#analysis-capture-object').click());
    assert.equal(material.snapshot.objects[0].object.ref,aircraft);
    await closeDossier(page);
    await page.reload(); await startAnalysis(page); await openDossier(page,dossier.id);
    assert.equal(await page.locator('#analysis-dossier-name').inputValue(),'Lot — ustalenia');
    assert.equal(await page.locator('#analysis-dossier-description').inputValue(),'Obserwacje na podstawie lokalnych danych.');
    assert.ok((await noteRow.innerText()).includes('Dopisek po weryfikacji.'));
    assert.equal(await page.locator(`#analysis-dossier-pins [data-ref="${aircraft}"]`).count(),1);
    assert.equal(await page.locator(`#analysis-dossier-materials [data-material-id="${material.id}"]`).count(),1);
    await closeDossier(page);
    const other = await createDossier(page,'Druga sprawa');
    assert.equal(await page.locator('#analysis-dossier-notes [data-note-id]').count(),0);
    assert.equal(await page.locator('#analysis-dossier-pins [data-ref]').count(),0);
    assert.equal(await page.locator('#analysis-dossier-materials [data-material-id]').count(),0);
    await closeDossier(page); await openDossier(page,dossier.id);
    await closeDossier(page); await page.locator('#theme-toggle').click();
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await page.setViewportSize({width:390,height:844}); await openDossier(page,dossier.id);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),'mobile page does not overflow horizontally');
    assert.ok(await page.locator('#analysis-dossier-dialog').evaluate(element => element.scrollWidth <= element.clientWidth+1),'dossier dialog fits mobile width');
    const dialogBox = await page.locator('#analysis-dossier-dialog').boundingBox();
    assert.ok(dialogBox.y >= 0 && dialogBox.y + dialogBox.height <= 845,'mobile dialog fits the visible viewport vertically');
    assert.ok(dialogBox.x >= 0 && dialogBox.x + dialogBox.width <= 391,'mobile dialog fits the visible viewport horizontally');
    await page.screenshot({path:path.join(evidence,'dossier-mobile-dark.png')});
    await mutation(page,'DELETE',`/pins/${encodeURIComponent(aircraft)}`,() => page.locator(`#analysis-dossier-pins [data-ref="${aircraft}"]`).getByRole('button',{name:'Odepnij',exact:true}).click());
    assert.equal((await env.api('GET',`/dossiers/${dossier.id}`)).pins.length,0);
    await noteRow.getByRole('button',{name:'Usuń',exact:true}).click();
    await mutation(page,'DELETE',`/notes/${note.id}`,() => confirmDelete(page));
    assert.equal((await env.api('GET',`/dossiers/${dossier.id}`)).notes.length,0);
    await page.locator(`#analysis-dossier-materials [data-material-id="${material.id}"]`).getByRole('button',{name:'Usuń materiał',exact:true}).click();
    await page.locator('#analysis-dossier-confirm').getByRole('button',{name:'Anuluj',exact:true}).click();
    assert.equal((await env.api('GET',`/dossiers/${dossier.id}`)).materials.length,1,'cancelled removal preserves evidence');
    await page.locator(`#analysis-dossier-materials [data-material-id="${material.id}"]`).getByRole('button',{name:'Usuń materiał',exact:true}).click();
    await mutation(page,'DELETE',`/materials/${material.id}`,() => confirmDelete(page));
    await page.locator('#analysis-dossier-delete').click();
    await mutation(page,'DELETE',`/dossiers/${dossier.id}`,() => confirmDelete(page));
    if (await page.locator('#analysis-dossier-dialog').isVisible()) await closeDossier(page);
    const remaining = await env.api('GET','/dossiers');
    assert.deepEqual(remaining.items.map(item=>item.id),[other.id]);
    await page.locator('[data-view="situation"]').click();
    await page.locator('#communication-list').waitFor({state:'visible'});
    await page.locator('[data-view="analysis"]').click(); await settle(page);
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Teczki: captured comparison retains source reports, interval and cursor after live updates', {timeout:120000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await types(page,['aircraft','ship']);
    for (const ref of [aircraft,ship]) await page.locator(`#analysis-table [data-ref="${ref}"] .analysis-compare-toggle`).check();
    const range = await historyRange(env), cursor = new Date(Date.parse(range.from)+10*60000).toISOString();
    await page.waitForFunction(() => document.querySelectorAll('#analysis-comparison-table tbody tr').length === 2);
    await seek(page,cursor);
    const dossier = await createDossier(page,'Przekrój czasu');
    await page.locator('#analysis-material-title').fill('Samolot i statek — zapis porównania');
    const material = await mutation(page,'POST',`/dossiers/${dossier.id}/materials`,() => page.locator('#analysis-capture-comparison').click());
    assert.equal(material.kind,'comparison');
    assert.equal(Date.parse(material.snapshot.context.cursor_at),Date.parse(cursor));
    assert.equal(Date.parse(material.snapshot.context.query.time.filter_range.from),Date.parse(range.from));
    assert.deepEqual(material.snapshot.moving.series.map(item=>item.ref).sort(),[aircraft,ship].sort());
    assert.match(material.sha256,/^[a-f0-9]{64}$/);
    assert.ok(JSON.stringify(material.snapshot).includes('adsb.fi'));
    assert.ok(JSON.stringify(material.snapshot).includes('aisstream.io'));
    await page.locator('#analysis-material-viewer').waitFor({state:'visible'});
    const text = await page.locator('#analysis-material-viewer').innerText();
    assert.match(text,/ANALIZA LOT 1/); assert.match(text,/ANALIZA STATEK 1/);
    await page.screenshot({path:path.join(evidence,'saved-comparison.png'),fullPage:true});
    await closeDossier(page);
    await page.getByRole('button',{name:'Bieżące',exact:true}).click(); await settle(page);
    const before = await env.api('GET',`/dossiers/${dossier.id}/materials/${material.id}`);
    const changed = await env.context.request.post(env.url+'/_test/feed/fresh',{headers:env.headers}); assert.ok(changed.ok());
    await env.context.request.get(env.url+'/api/aircraft'); await env.context.request.get(env.url+'/api/ships');
    await page.evaluate(() => WiciWorkspace.refresh()); await settle(page);
    assert.deepEqual(await env.api('GET',`/dossiers/${dossier.id}/materials/${material.id}`),before,'new source reports do not mutate saved evidence');
    await openDossier(page,dossier.id);
    await page.locator(`#analysis-dossier-materials [data-material-id="${material.id}"]`).getByRole('button',{name:'Otwórz zapis',exact:true}).click();
    await page.locator('#analysis-material-viewer').waitFor({state:'visible'});
    assert.equal(await page.locator('#analysis-material-viewer').innerText(),text,'saved viewer is independent of the current live workspace');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Teczki: history snapshot preserves station measurements; concurrent note edit keeps local draft', {timeout:120000}, async () => {
  const env = await setup(), {page} = env;
  try {
    await types(page,['hydro_station']); await historyRange(env);
    await card(page,'hydro_station:imgw:demo-wisla');
    assert.match(await page.locator('.analysis-reading').innerText(),/274/);
    await closeCard(page);
    const dossier = await createDossier(page,'Wodowskaz');
    const material = await mutation(page,'POST',`/dossiers/${dossier.id}/materials`,() => page.locator('#analysis-capture-timeline').click());
    assert.equal(material.kind,'timeline');
    assert.equal(material.snapshot.objects[0].object.ref,'hydro_station:imgw:demo-wisla');
    assert.ok(material.snapshot.timeline.items.some(item=>item.value === 274),'server captures the selected interval measurements');
    await page.locator('#analysis-material-viewer').waitFor({state:'visible'});
    assert.match(await page.locator('#analysis-material-viewer').innerText(),/274/);
    await page.locator('#analysis-material-back').click();
    await page.locator('#analysis-dossier-note-body').fill('Wersja początkowa');
    const note = await mutation(page,'POST',`/dossiers/${dossier.id}/notes`,() => page.locator('#analysis-dossier-note-save').click());
    await page.locator(`#analysis-dossier-notes [data-note-id="${note.id}"]`).getByRole('button',{name:'Edytuj',exact:true}).click();
    await page.locator('#analysis-dossier-note-body').fill('Mój niezapisany szkic');
    await env.api('PUT',`/dossiers/${dossier.id}/notes/${note.id}`,{body:'Zmiana z drugiego okna',revision:note.revision});
    const conflict = page.waitForResponse(response=>response.request().method()==='PUT'&&new URL(response.url()).pathname.endsWith(`/notes/${note.id}`));
    await page.locator('#analysis-dossier-note-save').click();
    assert.equal((await conflict).status(),409);
    await page.waitForFunction(() => document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy') !== 'true');
    assert.equal(await page.locator('#analysis-dossier-note-body').inputValue(),'Mój niezapisany szkic','conflict must not discard the pending draft');
    assert.match(await page.locator('#analysis-dossier-status').innerText(),/zmien|konflikt|aktual/i);
    const saved = await env.api('GET',`/dossiers/${dossier.id}`);
    assert.equal(saved.notes.find(item=>item.id===note.id).body,'Zmiana z drugiego okna','stale editor must not overwrite the competing edit');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Teczki: metadata drafts tolerate own note writes and recover explicitly from another window', {timeout:90000}, async () => {
  const env = await setup(), {page} = env;
  try {
    const dossier = await createDossier(page,'Pierwsza nazwa','Cel początkowy');
    await page.locator('#analysis-dossier-name').fill('Lokalna poprawka nazwy');
    await page.locator('#analysis-dossier-note-body').fill('Własny zapis notatki podczas edycji opisu');
    await mutation(page,'POST',`/dossiers/${dossier.id}/notes`,() => page.locator('#analysis-dossier-note-save').click());
    assert.equal(await page.locator('#analysis-dossier-name').inputValue(),'Lokalna poprawka nazwy');
    await mutation(page,'PUT',`/dossiers/${dossier.id}`,() => page.locator('#analysis-dossier-save').click());
    const current = await env.api('GET',`/dossiers/${dossier.id}`);
    assert.equal(current.name,'Lokalna poprawka nazwy','own child mutation must not create a false metadata conflict');
    await page.locator('#analysis-dossier-name').fill('Niezapisana nazwa z tego okna');
    await page.locator('#analysis-dossier-description').fill('Niezapisany opis z tego okna');
    await env.api('PUT',`/dossiers/${dossier.id}`,{name:'Nazwa z drugiego okna',description:'Opis z drugiego okna',revision:current.revision});
    const conflict = page.waitForResponse(response=>response.request().method()==='PUT'&&new URL(response.url()).pathname.endsWith(`/dossiers/${dossier.id}`));
    await page.locator('#analysis-dossier-save').click(); assert.equal((await conflict).status(),409);
    await page.waitForFunction(() => document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy') !== 'true');
    for (let attempt = 0; attempt < 2; attempt++) {
      const loaded = page.waitForResponse(response=>response.request().method()==='GET'&&new URL(response.url()).pathname.endsWith(`/dossiers/${dossier.id}`));
      await page.locator('#analysis-dossier-reload').click(); await loaded;
      await page.waitForFunction(() => document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy') !== 'true');
      assert.equal(await page.locator('#analysis-dossier-name').inputValue(),'Niezapisana nazwa z tego okna');
      assert.equal(await page.locator('#analysis-dossier-description').inputValue(),'Niezapisany opis z tego okna');
      assert.match(await page.locator('#analysis-dossier-description-conflict').innerText(),/Nazwa z drugiego okna/);
    }
    assert.equal((await env.api('GET',`/dossiers/${dossier.id}`)).name,'Nazwa z drugiego okna','loading a conflict must not overwrite the stored version');
    await page.locator('#analysis-dossier-description-discard').click();
    await page.locator('#analysis-dossier-confirm').getByRole('button',{name:'Odrzuć szkic',exact:true}).click();
    assert.equal(await page.locator('#analysis-dossier-name').inputValue(),'Nazwa z drugiego okna');
    assert.equal(await page.locator('#analysis-dossier-description').inputValue(),'Opis z drugiego okna');
    await page.locator('#analysis-dossier-name').fill('Uzgodniona nazwa');
    await mutation(page,'PUT',`/dossiers/${dossier.id}`,() => page.locator('#analysis-dossier-save').click());
    assert.equal((await env.api('GET',`/dossiers/${dossier.id}`)).name,'Uzgodniona nazwa');
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {await env.close();}
});

test('Teczki: delayed material reads cannot replace a closed or newly reopened editor', {timeout:90000}, async () => {
  const env = await setup(), {page} = env;
  let releasePending;
  try {
    await types(page,['aircraft']); await card(page,aircraft); await closeCard(page);
    const dossier = await createDossier(page,'Praca w toku');
    const material = await mutation(page,'POST',`/dossiers/${dossier.id}/materials`,() => page.locator('#analysis-capture-object').click());
    await page.locator('#analysis-material-viewer').waitFor({state:'visible'});
    await page.locator('#analysis-material-back').click();
    const materialURL = `${env.url}/api/workspace/dossiers/${dossier.id}/materials/${material.id}`;
    const materialButton = page.locator(`#analysis-dossier-materials [data-material-id="${material.id}"]`).getByRole('button',{name:'Otwórz zapis',exact:true});
    for (const mode of ['closed','reopened','deleted']) {
      let received;
      const arrived = new Promise(resolve => {received = resolve;});
      const hold = new Promise(resolve => {releasePending = resolve;});
      await page.route(materialURL, async route => {
        if (route.request().method() !== 'GET') return route.fallback();
        const response = await route.fetch(); received(); await hold; await route.fulfill({response});
      });
      const delivered = page.waitForResponse(response => response.url() === materialURL && response.request().method() === 'GET');
      await materialButton.click(); await arrived;
      if (mode === 'deleted') {
        await page.locator(`#analysis-dossier-materials [data-material-id="${material.id}"]`).getByRole('button',{name:'Usuń materiał',exact:true}).click();
        await mutation(page,'DELETE',`/materials/${material.id}`,() => confirmDelete(page));
        assert.equal((await env.api('GET',`/dossiers/${dossier.id}`)).materials.length,0);
      } else await closeDossier(page);
      if (mode === 'reopened') {
        // Reopen the same selection without firing a select/change event: changing
        // dossiers already invalidates reads and would conceal this regression.
        await page.locator('#analysis-dossier-open').click();
        await page.locator('#analysis-dossier-manager').waitFor({state:'visible'});
        await page.locator('#analysis-dossier-note-body').fill('Szkic pisany po ponownym otwarciu');
        await page.locator('#analysis-dossier-note-body').focus();
      }
      releasePending(); releasePending = null;
      const response = await delivered; assert.ok(response.ok()); await response.finished();
      // Let the fetch/body promises and resulting DOM work complete before asserting
      // that the obsolete response did not switch panels or move keyboard focus.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      assert.equal(await page.locator('#analysis-material-viewer').evaluate(element=>element.hidden),true,'obsolete saved-material response must not reveal its viewer');
      assert.equal(await page.locator('#analysis-dossier-manager').evaluate(element=>element.hidden),false,'manager state must survive the obsolete response');
      assert.equal(await page.locator('#analysis-dossier-dialog').evaluate(element=>element.open),mode !== 'closed');
      if (mode === 'reopened') {
        assert.equal(await page.locator('#analysis-dossier-note-body').inputValue(),'Szkic pisany po ponownym otwarciu');
        assert.equal(await page.evaluate(()=>document.activeElement.id),'analysis-dossier-note-body','late material response must not steal focus from the note');
      } else if (mode === 'closed') {
        await page.locator('#analysis-dossier-open').click();
        await page.locator('#analysis-dossier-manager').waitFor({state:'visible'});
      }
      await page.unroute(materialURL);
    }
    assert.deepEqual(env.errors,[]); assert.deepEqual(env.external,[]);
  } finally {releasePending?.(); await env.close();}
});
