'use strict';
// Real local graph/dossier APIs and SQLite; every provider is synthetic and all external traffic is blocked.
const test = require('node:test'), assert = require('node:assert/strict');
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..'), evidence = path.join(root, 'tmp/graph-workspace-evidence');
fs.mkdirSync(evidence, {recursive:true});
const station = 'air_quality_station:gios:9000001', province = 'area:prg:14';

async function setup() {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const child = spawn(path.join(root, '.venv/bin/python'), ['tests/helpers/graph_workspace_server.py', String(port)],
    {cwd:root, stdio:['ignore', 'pipe', 'pipe']});
  let logs = '', browser;
  child.stdout.on('data', chunk => logs += chunk); child.stderr.on('data', chunk => logs += chunk);
  const url = `http://127.0.0.1:${port}`, errors = [], external = [], reads = [];
  try {
    for (let index=0; index<200; index++) {
      if (child.exitCode !== null) throw Error(logs);
      try {if ((await fetch(url+'/api/health')).ok) break;} catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({headless:true});
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    await context.route('**/*', async route => {
      const requestURL = new URL(route.request().url()); reads.push(requestURL.pathname);
      if (requestURL.origin !== url) {external.push(requestURL.href); return route.abort();}
      if (requestURL.pathname === '/api/health') {
        const response = await route.fetch(); return route.fulfill({json:{...await response.json(),mode:'live'}});
      }
      return route.continue();
    });
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.stack || error.message));
    await page.goto(url); await startAnalysis(page);
    const headers = {'Origin':url,'X-CSRF-Token':await page.evaluate(() => state.health.csrf_token)};
    const fixture = await (await context.request.get(url+'/_test/graph')).json();
    return {page,context,url,headers,fixture,errors,external,reads,
      async raw(method, pathname, data) {return context.request.fetch(url+'/api/workspace'+pathname,{method,headers,data});},
      async api(method, pathname, data) {
        const response = await this.raw(method,pathname,data);
        assert.ok(response.ok(),`${method} ${pathname}: ${response.status()} ${await response.text()}`);
        return response.status() === 204 ? null : response.json();
      },
      async change(kind) {const response = await context.request.post(url+'/_test/change/'+kind,{headers}); assert.ok(response.ok(),`fixture ${kind}: ${response.status()} ${await response.text()}`); return response.json();},
      async close() {
        await page.screenshot({path:path.join(evidence,'last-state.png'),fullPage:true}).catch(()=>{});
        await browser.close(); const done = once(child,'exit'); child.kill('SIGTERM'); await done;
        fs.writeFileSync(path.join(evidence,'server.log'),logs);
      }};
  } catch (error) {if (browser) await browser.close(); child.kill('SIGTERM'); throw error;}
}
async function settle(page) {
  await page.waitForFunction(() => WiciWorkspace?.getData() && !WiciWorkspace.getState().loading && !WiciWorkspace.getState().error);
}
async function startAnalysis(page) {
  await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled);
  if (!(await page.locator('#analysis-table').isVisible())) await page.locator('[data-view="analysis"]').click();
  await settle(page);
}
async function types(page, selected) {
  for (const desired of [true,false]) for (const button of await page.locator('[data-object-type]').all()) {
    const wanted = selected.includes(await button.getAttribute('data-object-type'));
    if (wanted === desired && (await button.getAttribute('aria-pressed') === 'true') !== wanted) await button.click();
  }
  await settle(page);
}
async function card(page, ref) {
  await page.locator(`#analysis-table [data-ref="${ref}"] .analysis-object-link`).click();
  await page.waitForFunction(ref => WiciWorkspace.getState().selectedRef === ref && document.getElementById('analysis-card-title').textContent !== 'Wczytywanie obiektu…',ref);
}
function selector(env, refs=[station], extra={}) {
  return {seed_refs:refs,node_refs:refs,expanded_refs:[],relation_types:[],categories:[],time:{mode:'live'},...extra};
}
function timed(env, at) {
  return {time:{mode:'range',filter_range:env.fixture.range},cursor_at:new Date(Date.parse(env.fixture.range.from)+at*1000).toISOString()};
}
async function query(env, value) {return env.api('POST','/graph/query',value);}
async function graphReady(page) {
  await page.waitForFunction(() => WiciWorkspace.getGraphData?.()?.nodes?.length > 0 && !document.querySelector('#analysis-graph-panel [aria-busy="true"]'));
}
async function openGraph(page, config) {
  await page.evaluate(config => WiciWorkspace.openGraph(config),config); await graphReady(page);
}
async function mutation(page, method, suffix, act) {
  const pending = page.waitForResponse(response => response.request().method() === method && new URL(response.url()).pathname.endsWith(suffix));
  await act(); const response = await pending; assert.ok(response.ok(),`${method} ${suffix}: ${response.status()} ${await response.text()}`);
  await page.waitForFunction(() => document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy') !== 'true');
  return response.json();
}
async function openDossier(page,id) {
  if (!(await page.locator('#analysis-dossiers').evaluate(element=>element.open))) await page.locator('#analysis-dossiers > summary').click();
  await page.locator('#analysis-dossier-select').selectOption(id); await page.locator('#analysis-dossier-open').click();
  await page.locator('#analysis-dossier-dialog').waitFor({state:'visible'});
  await page.waitForFunction(() => document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy') !== 'true');
}

// API-backed scenarios deliberately exercise server-built graph semantics with the same real app as the UI.
test('Graph API: every visible endpoint has provenance, independent graph revisions and bounded neighbor pages', {timeout:60000}, async () => {
  const env=await setup();
  try {
    const {notice}=env.fixture;
    const scope=selector(env,[station],{node_refs:[station,province,notice],expanded_refs:[station,province]});
    const graph=await query(env,scope);
    assert.deepEqual(new Set(graph.nodes.map(node=>node.ref)),new Set(scope.node_refs));
    const stationEdge=graph.edges.find(edge=>edge.source_ref===station && edge.target_ref===province);
    const noticeEdge=graph.edges.find(edge=>edge.source_ref===notice && edge.target_ref===province);
    assert.ok(stationEdge && noticeEdge,'station and communication meet via the actual administrative area');
    assert.equal(stationEdge.category,'source'); assert.equal(noticeEdge.category,'source');
    assert.ok(stationEdge.provenance && noticeEdge.provenance);
    assert.notEqual(stationEdge.id,noticeEdge.id); assert.ok(graph.partial);
    let cursor=null,total=null; const refs=[];
    do {
      const page=await env.api('POST','/graph/neighbors',{graph:{...graph.selector,expected_revision:graph.revision},ref:province,cursor,limit:50});
      assert.ok(page.items.length<=50); total=page.total; refs.push(...page.items.map(item=>item.node.ref)); cursor=page.next_cursor;
    } while(cursor);
    assert.ok(total>50,'high-degree area really needs multiple pages');
    assert.equal(refs.length,total); assert.equal(new Set(refs).size,total,'neighbor pages never duplicate endpoints');
    const baseline=await env.api('POST','/query',{types:['air_quality_station']});
    await env.change('notice');
    const unchanged=await env.api('POST','/query',{types:['air_quality_station']});
    assert.equal(unchanged.data_revision,baseline.data_revision,'catalog filtering does not cover connected communication');
    const stale=await env.raw('POST','/graph/query',{...graph.selector,expected_revision:graph.revision});
    assert.equal(stale.status(),409,'graph revision protects visible objects outside the catalogue type filter');
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph API: transport area membership follows a recorded cursor and disappears in a real observation gap', {timeout:60000}, async () => {
  const env=await setup();
  try {
    const ref=env.fixture.aircraft, base=selector(env,[ref],{node_refs:[ref,province]});
    const present=await query(env,{...base,...timed(env,300)});
    const edge=present.edges.find(item=>item.source_ref===ref && item.target_ref===province);
    assert.ok(edge,'archived aircraft report is inside mazowieckie'); assert.equal(edge.category,'derived');
    assert.ok(Object.values(edge.time).some(value=>typeof value==='string' && Number.isFinite(Date.parse(value))),'report relation retains its actual time');
    const hole=await query(env,{...base,...timed(env,1800)});
    assert.equal(hole.edges.some(item=>item.source_ref===ref && item.target_ref===province),false,'no position edge bridges a 20-minute archive gap');
    assert.equal(hole.nodes.find(node=>node.ref===ref).position,null);
    const live=await query(env,base); assert.ok(live.edges.some(item=>item.source_ref===ref));
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph API: Ukraine episode and hierarchy preserve independent relations and unknown-time coverage', {timeout:60000}, async () => {
  const env=await setup();
  try {
    const {alert,raion,oblast}=env.fixture;
    assert.ok(alert);
    const base=selector(env,[alert],{node_refs:[alert,raion,oblast],...timed(env,300)});
    const graph=await query(env,base);
    assert.ok(graph.edges.some(edge=>edge.source_ref===alert && edge.target_ref===raion));
    assert.ok(graph.edges.some(edge=>edge.source_ref===raion && edge.target_ref===oblast));
    assert.ok(graph.edges.every(edge=>edge.category==='source'));
    const hole=await query(env,{...base,...timed(env,1500)});
    assert.equal(hole.nodes.find(node=>node.ref===raion).state,'unknown','graph uses the same explicit source gap as timeline replay');
    assert.ok(hole.edges.some(edge=>edge.source_ref===raion && edge.target_ref===oblast),'hierarchy remains current metadata while alarm status is unknown');
    const dossier=await env.api('POST','/dossiers',{name:'Graf Ukrainy'});
    const material=await env.api('POST',`/dossiers/${dossier.id}/materials`,{kind:'graph',graph:{...graph.selector,expected_revision:graph.revision},positions:{[alert]:{x:40,y:50}},title:'Powiązania regionu'});
    assert.equal(material.kind,'graph');
    assert.ok(material.snapshot.graph.edges.some(edge=>edge.source_ref===alert));
    assert.equal(material.snapshot.graph.nodes.find(node=>node.ref===raion).state,'red');
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph API: analyst relations are justified, isolated, versioned and preserve a deletion audit', {timeout:60000}, async () => {
  const env=await setup();
  try {
    const first=await env.api('POST','/dossiers',{name:'Teczka powiązań'});
    const other=await env.api('POST','/dossiers',{name:'Osobna teczka'});
    const note=await env.api('POST',`/dossiers/${first.id}/notes`,{body:'Uzasadnienie źródłowe notatki'});
    const foreign=await env.api('POST',`/dossiers/${other.id}/notes`,{body:'Notatka innej sprawy'});
    const material=await env.api('POST',`/dossiers/${first.id}/materials`,{kind:'object',ref:station,query:{types:['air_quality_station']}});
    const body={source_ref:station,target_ref:env.fixture.notice,justification:'Powiązanie robocze analityka',note_id:note.id,material_id:material.id};
    const blank=await env.raw('POST',`/dossiers/${first.id}/relations`,{...body,justification:' '}); assert.equal(blank.status(),422);
    const cross=await env.raw('POST',`/dossiers/${first.id}/relations`,{...body,note_id:foreign.id}); assert.ok([404,422].includes(cross.status()));
    const relation=await env.api('POST',`/dossiers/${first.id}/relations`,body);
    const graph=await query(env,selector(env,[station],{node_refs:[station,env.fixture.notice],dossier_id:first.id}));
    const edge=graph.edges.find(edge=>edge.category==='analyst'); assert.ok(edge);
    assert.match(JSON.stringify(edge),/Powiązanie robocze analityka/);
    const isolated=await query(env,selector(env,[station],{node_refs:[station,env.fixture.notice],dossier_id:other.id}));
    assert.equal(isolated.edges.some(edge=>edge.category==='analyst'),false,'same object identities do not leak case assertions');
    const updated=await env.api('PUT',`/dossiers/${first.id}/relations/${relation.id}`,{...body,justification:'Poprawione uzasadnienie',revision:relation.revision});
    const stale=await env.raw('PUT',`/dossiers/${first.id}/relations/${relation.id}`,{...body,revision:relation.revision}); assert.equal(stale.status(),409);
    const history=await env.api('GET',`/dossiers/${first.id}/relations/${relation.id}/history`);
    assert.match(JSON.stringify(history),/Powiązanie robocze analityka/); assert.match(JSON.stringify(history),/Poprawione uzasadnienie/);
    await env.api('DELETE',`/dossiers/${first.id}/relations/${relation.id}?revision=${updated.revision}`);
    const after=await env.api('GET',`/dossiers/${first.id}/relations/${relation.id}/history`);
    assert.ok((after.items || after).length>=3,'create, edit and delete remain auditable');
    const deleted=await query(env,selector(env,[station],{node_refs:[station,env.fixture.notice],dossier_id:first.id}));
    assert.equal(deleted.edges.some(edge=>edge.category==='analyst'),false);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph UI: GIOS card expands actual area links and synchronizes graph, table and outside-scope card', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    await types(page,['air_quality_station']); await card(page,station);
    await page.getByRole('button',{name:'Pokaż powiązania',exact:true}).click(); await graphReady(page);
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    await page.locator(`[data-graph-ref="${station}"] .analysis-graph-select`).click();
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    await page.locator('#analysis-graph-expand').click();
    await page.waitForFunction(ref=>WiciWorkspace.getGraphData()?.nodes.some(node=>node.ref===ref),province);
    const graph=await page.evaluate(()=>WiciWorkspace.getGraphData());
    const edge=graph.edges.find(edge=>edge.source_ref===station && edge.target_ref===province); assert.ok(edge);
    await page.locator(`[data-edge-id="${edge.id}"]`).click();
    assert.match(await page.locator('#analysis-graph-inspector').innerText(),/Źródłowa|Podstawa|Źródło/);
    await page.locator(`[data-graph-ref="${province}"] .analysis-graph-select`).click();
    await page.waitForFunction(ref=>WiciWorkspace.getState().selectedRef===ref,province);
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getState().query.types),['air_quality_station']);
    assert.match(await page.locator('#analysis-outside-range').innerText(),/Poza bieżącym zakresem/);
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    await page.locator('#analysis-table-scope').selectOption('graph');
    await page.locator(`#analysis-table [data-ref="${province}"]`).waitFor();
    await page.locator('#analysis-view-both').click();
    assert.equal(await page.locator('#analysis-graph-canvas').isVisible(),true);
    assert.equal(await page.locator('#map').isVisible(),true);
    await page.locator('#analysis-graph-search').fill('TEST graf — komunikat 00');
    await page.locator(`[data-graph-search-ref="${env.fixture.notice}"]`).click();
    const connected=await (await page.waitForFunction(ref=>{const data=WiciWorkspace.getGraphData(); return data?.nodes.some(node=>node.ref===ref) ? data : false;},env.fixture.notice)).jsonValue();
    assert.ok(connected.edges.some(item=>item.source_ref===env.fixture.notice && item.target_ref===province));
    await page.locator('#analysis-graph-path-from').selectOption(station);
    await page.locator('#analysis-graph-path-to').selectOption(env.fixture.notice);
    await page.locator('#analysis-graph-find-path').click();
    assert.match(await page.locator('#analysis-graph-path-status').innerText(),/2 relacji/);
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    await page.locator('#analysis-graph-fit').click();
    await page.locator('#analysis-graph-canvas').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#analysis-card').isVisible(),false,'desktop graph evidence is unobscured by the detail card');
    await page.screenshot({path:path.join(evidence,'gios-source-path.png'),fullPage:true,animations:'disabled'});
    await page.screenshot({path:path.join(evidence,'graph-desktop-fit.png'),animations:'disabled'});
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph UI: analyst case relations, working layout and immutable copies coexist with old material kinds', {timeout:120000}, async () => {
  const env=await setup(),{page}=env;
  try {
    const dossier=await env.api('POST','/dossiers',{name:'Teczka grafu'});
    const note=await env.api('POST',`/dossiers/${dossier.id}/notes`,{body:'Źródło interpretacji użytkownika'});
    await env.api('POST',`/dossiers/${dossier.id}/pins`,{ref:station});
    await env.api('POST',`/dossiers/${dossier.id}/pins`,{ref:env.fixture.notice});
    const old=await env.api('POST',`/dossiers/${dossier.id}/materials`,{kind:'object',ref:station,query:{types:['air_quality_station']},title:'Zwykła karta v0.33'});
    await page.locator('[data-view="situation"]').click(); await page.locator('[data-view="analysis"]').click(); await settle(page);
    await openDossier(page,dossier.id);
    await page.locator('#analysis-relation-source').selectOption(station);
    await page.locator('#analysis-relation-target').selectOption(env.fixture.notice);
    const explanation='<img src=x onerror="window.graphXSS=true"> Powiązanie robocze do sprawdzenia.';
    await page.locator('#analysis-relation-justification').fill(explanation);
    await page.locator('#analysis-relation-note').selectOption(note.id);
    await page.locator('#analysis-relation-material').selectOption(old.id);
    const relation=await mutation(page,'POST',`/dossiers/${dossier.id}/relations`,()=>page.locator('#analysis-relation-save').click());
    assert.equal(await page.locator('#analysis-relations-list img').count(),0);
    assert.equal(await page.evaluate(()=>window.graphXSS),undefined);
    const body=await env.api('GET',`/dossiers/${dossier.id}/relations`); assert.match(JSON.stringify(body),/Powiązanie robocze/);
    const relationRow=page.locator(`[data-relation-id="${relation.id}"]`);
    await relationRow.getByRole('button',{name:'Edytuj',exact:true}).click();
    await page.locator('#analysis-relation-justification').fill('Mój niezapisany szkic uzasadnienia');
    await env.api('PUT',`/dossiers/${dossier.id}/relations/${relation.id}`,{source_ref:station,target_ref:env.fixture.notice,justification:explanation+' Zewnętrzna poprawka.',note_id:note.id,material_id:old.id,revision:relation.revision});
    const conflict=page.waitForResponse(response=>response.request().method()==='PUT' && new URL(response.url()).pathname.endsWith(`/relations/${relation.id}`));
    await page.locator('#analysis-relation-save').click(); assert.equal((await conflict).status(),409);
    await page.waitForFunction(()=>document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy')!=='true');
    assert.equal(await page.locator('#analysis-relation-justification').inputValue(),'Mój niezapisany szkic uzasadnienia');
    await page.locator('#analysis-relations-reload').click();
    await page.locator('#analysis-relation-cancel').click();
    await page.locator('#analysis-dossier-confirm').getByRole('button',{name:'Odrzuć szkic',exact:true}).click();
    await page.locator('#analysis-dossier-graph-open').click(); await graphReady(page);
    assert.equal(await page.locator('#analysis-dossier-dialog').isVisible(),false);
    const data=await page.evaluate(()=>WiciWorkspace.getGraphData()); assert.ok(data.edges.some(edge=>edge.category==='analyst'));
    await page.locator('#analysis-graph-layout').selectOption('concentric');
    await page.locator('#analysis-graph-arrange').click();
    const graphBox=await page.locator('#analysis-graph-panel').boundingBox(), timelineBox=await page.locator('.analysis-timeline').boundingBox();
    assert.ok(graphBox.y+graphBox.height<=timelineBox.y+1,'graph controls cannot overflow behind the timeline');
    const working=await page.evaluate(()=>WiciWorkspace.getGraphConfig());
    assert.equal(working.layout,'concentric');
    assert.ok(Object.keys(working.positions).length>=2);
    await openDossier(page,dossier.id);
    await mutation(page,'PUT',`/dossiers/${dossier.id}/graph`,()=>page.locator('#analysis-dossier-graph-save').click());
    const stored=await env.api('GET',`/dossiers/${dossier.id}/graph`);
    assert.deepEqual(new Set(stored.graph.node_refs),new Set(working.graph.node_refs));
    assert.ok(Object.keys(stored.positions).length>=2);
    assert.equal(stored.layout,'concentric');
    await page.locator('#analysis-dossier-close').click();
    await page.locator('#analysis-graph-clear').click();
    await openDossier(page,dossier.id);
    await page.locator('#analysis-dossier-graph-load').click(); await graphReady(page);
    const restored=await page.evaluate(()=>WiciWorkspace.getGraphConfig());
    assert.deepEqual(new Set(restored.graph.node_refs),new Set(stored.graph.node_refs));
    assert.equal(restored.layout,'concentric');
    for (const [ref,point] of Object.entries(stored.positions)) {
      assert.ok(Math.abs(restored.positions[ref].x-point.x)<.01 && Math.abs(restored.positions[ref].y-point.y)<.01,'restored layout retains user positions');
    }
    await page.locator('#analysis-graph-layout').selectOption('breadthfirst');
    await page.locator('#analysis-graph-arrange').click();
    await openDossier(page,dossier.id);
    await mutation(page,'PUT',`/dossiers/${dossier.id}/graph`,()=>page.locator('#analysis-dossier-graph-save').click());
    const savedAgain=await env.api('GET',`/dossiers/${dossier.id}/graph`);
    assert.equal(savedAgain.revision,stored.revision+1,'a restored config can be saved again without response-only metadata');
    const ownPositions=await page.evaluate(()=>WiciWorkspace.getGraphConfig().positions);
    const externalPositions=Object.fromEntries(Object.entries(savedAgain.positions).map(([ref,point])=>[ref,{x:point.x+40,y:point.y+70}]));
    await env.api('PUT',`/dossiers/${dossier.id}/graph`,{graph:savedAgain.graph,positions:externalPositions,hidden_refs:savedAgain.hidden_refs,layout:savedAgain.layout,node_type:savedAgain.node_type || null,revision:savedAgain.revision});
    const layoutConflict=page.waitForResponse(response=>response.request().method()==='PUT' && new URL(response.url()).pathname.endsWith(`/dossiers/${dossier.id}/graph`));
    await page.locator('#analysis-dossier-graph-save').click(); assert.equal((await layoutConflict).status(),409);
    await page.waitForFunction(()=>document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy')!=='true');
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getGraphConfig().positions),ownPositions,'conflict retains the working graph layout');
    await page.locator('#analysis-dossier-graph-load').click();
    await page.waitForFunction(expected=>WiciWorkspace.getGraphData() && JSON.stringify(WiciWorkspace.getGraphConfig().positions)===JSON.stringify(expected),externalPositions);
    await graphReady(page);
    const recovered=await page.evaluate(()=>WiciWorkspace.getGraphConfig());
    assert.deepEqual(recovered.positions,externalPositions,'explicit loading recovers the current competing layout');
    await openDossier(page,dossier.id);
    await page.locator('#analysis-material-title').fill('Zachowany graf sprawy');
    const saved=await mutation(page,'POST',`/dossiers/${dossier.id}/materials`,()=>page.locator('#analysis-dossier-graph-capture').click());
    assert.equal(saved.kind,'graph');
    await page.waitForFunction(()=>!document.getElementById('analysis-material-viewer').hidden);
    assert.match(await page.locator('#analysis-material-viewer').innerText(),/Powiązanie robocze|Analityczna/);
    await page.screenshot({path:path.join(evidence,'graph-copy-viewer.png'),animations:'disabled'});
    await env.change('prune');
    assert.deepEqual(await env.api('GET',`/dossiers/${dossier.id}/materials/${saved.id}`),saved,'retention never mutates a graph copy');
    await page.locator('#analysis-material-back').click();
    await page.locator(`[data-material-id="${old.id}"]`).getByRole('button',{name:'Otwórz zapis',exact:true}).click();
    await page.waitForFunction(()=>!document.getElementById('analysis-material-viewer').hidden);
    assert.match(await page.locator('#analysis-material-viewer').innerText(),/Stacja GIOŚ|jakość powietrza/);
    await page.locator('#analysis-material-back').click();
    const row=page.locator(`[data-relation-id="${relation.id}"]`);
    await row.locator('summary').filter({hasText:'Historia zmian'}).click();
    await page.waitForFunction(id=>document.querySelector(`[data-relation-id="${id}"]`).textContent.includes('Zachowana podstawa: notatka'),relation.id);
    assert.match(await page.locator('#analysis-relations-list').innerText(),/Powiązanie robocze/);
    assert.equal(await page.locator('#analysis-relations-list .notice').count(),0,'existing note and material are not falsely marked missing');
    const latest=(await env.api('GET',`/dossiers/${dossier.id}/relations`)).items.find(item=>item.id===relation.id);
    await env.api('DELETE',`/dossiers/${dossier.id}/relations/${relation.id}?revision=${latest.revision}`);
    await page.locator('#analysis-relations-reload').click();
    await row.waitFor({state:'hidden'});
    await page.locator('#analysis-relations-show-deleted').check();
    assert.equal(await page.locator('#analysis-relations-show-deleted').isChecked(),true);
    await row.waitFor({state:'visible'});
    assert.equal(await row.getByRole('button',{name:'Edytuj',exact:true}).count(),0,'deleted assertions remain audit-only');
    await row.locator('summary').filter({hasText:'Historia zmian'}).click();
    await page.waitForFunction(id=>document.querySelector(`[data-relation-id="${id}"]`).textContent.includes('Usunięto'),relation.id);
    await page.screenshot({path:path.join(evidence,'dossier-graph-copy.png'),fullPage:true});
    await page.locator('#analysis-relations-show-deleted').uncheck();
    await row.waitFor({state:'hidden'});
    assert.equal(await page.locator('#analysis-relations-show-deleted').isChecked(),false,'turning deleted history off hides deleted relations again');
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph UI: mobile keyboard exploration, type filters and hidden nodes preserve the visible-fragment path meaning', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    await openGraph(page,{seed_refs:[station],config:{graph:selector(env,[station],{node_refs:[station,province,env.fixture.notice]}),positions:{[station]:{x:100,y:100},[province]:{x:250,y:200}},hidden_refs:[]}});
    await page.setViewportSize({width:390,height:844});
    const select=page.locator(`[data-graph-ref="${station}"] .analysis-graph-select`);
    await select.focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(ref=>WiciWorkspace.getState().selectedRef===ref,station);
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    await page.locator('#analysis-graph-path-from').selectOption(station);
    await page.locator('#analysis-graph-path-to').selectOption(env.fixture.notice);
    await page.locator('#analysis-graph-find-path').click(); assert.match(await page.locator('#analysis-graph-path-status').innerText(),/2 relacji/);
    await page.locator(`[data-graph-ref="${province}"] .analysis-graph-select`).click();
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    await page.locator('#analysis-graph-hide').click();
    assert.equal(await page.locator(`[data-graph-ref="${province}"]`).count(),0);
    await page.locator('#analysis-graph-find-path').click(); assert.match(await page.locator('#analysis-graph-path-status').innerText(),/Brak ścieżki.*fragmencie/);
    for (const theme of ['light','dark']) {
      const current=await page.locator('html').getAttribute('data-theme');
      if ((current==='dark') !== (theme==='dark')) await page.locator('#theme-toggle').click();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'graph never creates horizontal page overflow');
      await page.locator('#analysis-graph-fit').click();
      await page.screenshot({path:path.join(evidence,`graph-mobile-${theme}.png`),animations:'disabled'});
    }
    await page.locator('#analysis-graph-show-hidden').click();
    await page.locator(`[data-graph-ref="${province}"]`).waitFor();
    await page.locator('[data-view="situation"]').click(); assert.equal(await page.locator('#analysis-graph-panel').isVisible(),false);
    await page.locator('[data-view="analysis"]').click(); await settle(page);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph UI: a delayed graph read cannot replace a newer exploration or resurrect a hidden panel', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    let release, observed;
    const blocked=new Promise(resolve=>release=resolve), seen=new Promise(resolve=>observed=resolve);
    let hold=true;
    await page.route('**/api/workspace/graph/query',async route=>{
      if (!hold) return route.continue();
      hold=false; const response=await route.fetch(); observed(); await blocked;
      await route.fulfill({response}).catch(()=>{});
    });
    const opening=page.evaluate(ref=>{WiciWorkspace.openGraph({seed_refs:[ref]});},station);
    await seen; await opening;
    await page.evaluate(ref=>WiciWorkspace.openGraph({seed_refs:[ref]}),env.fixture.notice);
    await page.waitForFunction(ref=>WiciWorkspace.getGraphData()?.nodes[0]?.ref===ref,env.fixture.notice);
    release();
    await page.waitForTimeout(150);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphData().nodes[0].ref),env.fixture.notice);
    let releaseHidden, observedHidden;
    const blockedHidden=new Promise(resolve=>releaseHidden=resolve), seenHidden=new Promise(resolve=>observedHidden=resolve);
    await page.route('**/api/workspace/graph/query',async route=>{
      const response=await route.fetch(); observedHidden(); await blockedHidden;
      await route.fulfill({response}).catch(()=>{});
    });
    await page.evaluate(ref=>{WiciWorkspace.openGraph({seed_refs:[ref]});},station);
    await seenHidden;
    await page.locator('#analysis-view-map').click(); releaseHidden();
    await page.waitForTimeout(150);
    assert.equal(await page.locator('#analysis-graph-panel').isVisible(),false);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph UI: Ukraine graph follows the shared cursor gap and saves the visible unknown-state copy', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    const {alert,raion,oblast}=env.fixture;
    await openGraph(page,{seed_refs:[alert],config:{graph:selector(env,[alert],{node_refs:[alert,raion,oblast],...timed(env,300)}),positions:{},hidden_refs:[]}});
    await page.waitForFunction(ref=>WiciWorkspace.getGraphData()?.nodes.find(node=>node.ref===ref)?.state==='red',raion);
    await page.locator(`[data-graph-ref="${raion}"] .analysis-graph-select`).click();
    await page.waitForFunction(ref=>WiciWorkspace.getState().selectedRef===ref,raion);
    await page.waitForFunction(()=>document.getElementById('analysis-card-title')?.textContent==='TEST Rejon grafu');
    assert.match(await page.locator('#analysis-card').innerText(),/Ukrain|NEPTUN|alarm/i);
    if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
    const cursor=new Date(Date.parse(env.fixture.range.from)+1500*1000).toISOString();
    const value=await page.evaluate(at=>WiciWorkspaceTimeline.localValue(at),cursor);
    await page.locator('#analysis-cursor-date').fill(value);
    await page.locator('#analysis-cursor-date').dispatchEvent('change');
    await page.waitForFunction(ref=>WiciWorkspace.getGraphData()?.nodes.find(node=>node.ref===ref)?.state==='unknown',raion);
    const dossier=await env.api('POST','/dossiers',{name:'Zachowany graf Ukrainy'});
    await page.locator('[data-view="situation"]').click(); await page.locator('[data-view="analysis"]').click(); await settle(page);
    await openDossier(page,dossier.id);
    await page.locator('#analysis-material-title').fill('Region i alarm podczas luki');
    const material=await mutation(page,'POST',`/dossiers/${dossier.id}/materials`,()=>page.locator('#analysis-dossier-graph-capture').click());
    assert.equal(material.snapshot.graph.nodes.find(node=>node.ref===raion).state,'unknown');
    assert.ok(material.snapshot.graph.edges.some(edge=>edge.source_ref===raion && edge.target_ref===oblast));
    await page.waitForFunction(()=>!document.getElementById('analysis-material-viewer').hidden);
    assert.match(await page.locator('#analysis-material-viewer').innerText(),/TEST Rejon grafu|TEST Obwód grafu/);
    assert.match(await page.locator('#analysis-material-viewer').innerText(),/Stan nieznany/);
    await page.screenshot({path:path.join(evidence,'ukraine-graph-copy.png'),animations:'disabled'});
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph UI: selecting a historical communication node retains the chosen version and its original area', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    const {ref,old_version}=env.fixture.versioned;
    const current=await query(env,selector(env,[ref],{node_refs:[ref,'area:prg:12']}));
    assert.ok(current.edges.some(edge=>edge.source_ref===ref && edge.target_ref==='area:prg:12'),'current source version really has a different administrative area');
    await openGraph(page,{seed_refs:[ref],config:{graph:selector(env,[ref],{node_refs:[ref,province],version_ids:{[ref]:old_version}}),positions:{},hidden_refs:[]}});
    await page.waitForFunction(({ref,province})=>WiciWorkspace.getGraphData()?.edges.some(edge=>edge.source_ref===ref && edge.target_ref===province),{ref,province});
    await page.locator(`[data-graph-ref="${ref}"] .analysis-graph-select`).click();
    await page.waitForFunction(({ref,old_version})=>WiciWorkspace.getState().selectedRef===ref && Number(WiciWorkspace.getState().selectedVersion)===old_version,{ref,old_version});
    const data=await (await page.waitForFunction(({ref,province})=>{const graph=WiciWorkspace.getGraphData(); return graph?.edges.some(edge=>edge.source_ref===ref && edge.target_ref===province) ? graph : false;},{ref,province})).jsonValue();
    assert.equal(data.edges.some(edge=>edge.source_ref===ref && edge.target_ref==='area:prg:12'),false);
    await page.waitForFunction(()=>document.getElementById('analysis-card').textContent.includes('Pierwsza treść i obszar'));
    assert.match(await page.locator('#analysis-card').innerText(),/Pierwsza treść i obszar/);
    await page.locator('#analysis-close-card').click(); await page.locator('#analysis-view-both').click();
    const areas=await page.evaluate(()=>{
      const result=[];
      state.map.eachLayer(layer=>{const content=layer.getTooltip?.()?.getContent?.(), text=typeof content==='string' ? content : content?.textContent || '';
        if (!text.includes('TEST graf — wersja')) return;
        for (const item of layer.getLayers?.() || [layer]) if(item.feature?.properties?.admin_code) result.push(item.feature.properties.admin_code);
      }); return result;
    });
    assert.ok(areas.includes('14'),'map renders the selected document version administrative geometry');
    assert.equal(areas.includes('12'),false,'current document geometry must not leak into selected historic version');
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph regression: showing a graph card on the map reveals and resizes the desktop map', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    await openGraph(page,{seed_refs:[station]});
    assert.equal(await page.locator('#map').isVisible(),false);
    await page.locator(`[data-graph-ref="${station}"] .analysis-graph-select`).click();
    await page.getByRole('button',{name:'Pokaż na mapie',exact:true}).click();
    assert.equal(await page.evaluate(()=>WiciWorkspace.getState().graphMode),'map');
    assert.equal(await page.evaluate(()=>WiciWorkspace.getState().layout.mobilePanel),'map');
    assert.equal(await page.locator('#map').isVisible(),true);
    const size=await page.evaluate(()=>({leaflet:state.map.getSize().x,actual:document.getElementById('map').clientWidth}));
    assert.ok(size.actual>0); assert.equal(size.leaflet,size.actual,'Leaflet has the revealed panel dimensions');
    assert.equal(await page.evaluate(()=>WiciWorkspace.getState().selectedRef),station);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph regression: obsolete saved-layout responses cannot close a reopened dossier or switch its graph', {timeout:90000}, async () => {
  const env=await setup(),{page}=env; let releasePending;
  try {
    const dossier=await env.api('POST','/dossiers',{name:'Ochrona nawigacji grafu'});
    await env.api('PUT',`/dossiers/${dossier.id}/graph`,{graph:selector(env,[env.fixture.notice],{dossier_id:dossier.id}),positions:{},hidden_refs:[],layout:'breadthfirst',revision:0});
    await page.locator('[data-view="situation"]').click(); await page.locator('[data-view="analysis"]').click(); await settle(page);
    await openGraph(page,{seed_refs:[station]});
    await openDossier(page,dossier.id);
    const endpoint=env.url+`/api/workspace/dossiers/${dossier.id}/graph`;
    for (const mode of ['closed','reopened','reopened-error']) {
      let arrived; const seen=new Promise(resolve=>arrived=resolve), blocked=new Promise(resolve=>releasePending=resolve);
      const handler=async route=>{const response=await route.fetch(); arrived(); await blocked;
        if (mode==='reopened-error') await route.fulfill({status:500,json:{detail:'Obsolete test error'}});
        else await route.fulfill({response});};
      await page.route(endpoint,handler);
      const delivered=page.waitForResponse(response=>response.url()===endpoint && response.request().method()==='GET');
      await page.locator('#analysis-dossier-graph-load').click(); await seen;
      await page.locator('#analysis-dossier-close').click();
      if (mode!=='closed') {
        // Keep the same selection: select/change would independently invalidate the request.
        await page.locator('#analysis-dossier-open').click();
        await page.locator('#analysis-dossier-dialog').waitFor({state:'visible'});
        await page.locator('#analysis-dossier-note-body').fill('Szkic po ponownym otwarciu');
        await page.locator('#analysis-dossier-note-body').focus();
      }
      releasePending(); releasePending=null; await (await delivered).finished();
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      assert.equal(await page.locator('#analysis-dossier-dialog').evaluate(node=>node.open),mode!=='closed');
      assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphData().nodes[0].ref),station,'obsolete layout cannot replace the current exploration');
      if (mode!=='closed') {
        assert.equal(await page.locator('#analysis-dossier-note-body').inputValue(),'Szkic po ponownym otwarciu');
        assert.equal(await page.evaluate(()=>document.activeElement.id),'analysis-dossier-note-body');
      }
      assert.doesNotMatch(await page.locator('#analysis-dossier-dialog').innerText().catch(()=>''),/Obsolete test error/);
      await page.unroute(endpoint,handler);
      if (mode==='closed') await page.locator('#analysis-dossier-open').click();
    }
    // A newly requested layout still loads normally after the obsolete requests finish.
    await page.locator('#analysis-dossier-graph-load').click();
    await page.waitForFunction(ref=>WiciWorkspace.getGraphData()?.nodes[0]?.ref===ref,env.fixture.notice);
    assert.equal(await page.locator('#analysis-dossier-dialog').evaluate(node=>node.open),false);
    assert.deepEqual(env.errors,[]);
  } finally {releasePending?.(); await env.close();}
});

test('Graph regression: the rendered ship badge retains the graph clock through type and hidden-node filters', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    await page.evaluate(()=>{window.cytoscape=new Proxy(window.cytoscape,{apply(target,receiver,args){const cy=Reflect.apply(target,receiver,args);window.testGraphRenderer=cy;return cy;}});});
    let age=420;
    // Change only report age in an actual API response, to exercise the renderer integration
    // independently of the backend freshness policy and the helper's direct unit tests.
    await page.route('**/api/workspace/graph/query',async route=>{
      const response=await route.fetch(), graph=await response.json();
      const clock=Date.parse(graph.selector.cursor_at || graph.as_of);
      for (const node of graph.nodes) if (node.type==='ship' && node.position) node.position.position_at=new Date(clock-age*1000).toISOString();
      await route.fulfill({response,json:graph});
    });
    const refs=[env.fixture.ship,province];
    const assertBadge=async expected=>{
      const result=await page.evaluate(ref=>{const data=WiciWorkspace.getGraphData(),node=data.nodes.find(node=>node.ref===ref),clock=Date.parse(data.selector.cursor_at || data.as_of);
        return {age:(clock-Date.parse(node.position.position_at))/1000,old:decodeURIComponent(window.testGraphRenderer.getElementById(ref).data('symbol')).includes('fill="url(#old)"')};},env.fixture.ship);
      assert.equal(result.age,age);assert.equal(result.old,expected,'actual Cytoscape node must reflect report age');
    };
    for (const range of [false,true]) {
      const scope=selector(env,refs,range ? timed(env,900) : {});
      await openGraph(page,{config:{graph:scope,positions:{},hidden_refs:[],layout:'breadthfirst'}});
      await assertBadge(true);
      await page.locator('#analysis-graph-node-type').selectOption('ship'); await assertBadge(true);
      await page.locator('#analysis-graph-node-type').selectOption('');
      await page.locator(`[data-graph-ref="${province}"] .analysis-graph-select`).click();
      if (await page.locator('#analysis-card').isVisible()) await page.locator('#analysis-close-card').click();
      await page.locator('#analysis-graph-hide').click(); await assertBadge(true);
      await page.locator('#analysis-graph-show-hidden').click(); await assertBadge(true);
    }
    age=120; await page.evaluate(()=>WiciWorkspace.refreshGraph()); await graphReady(page); await assertBadge(false);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph regression: returning to an interrupted refresh reloads the current cursor before allowing capture', {timeout:90000}, async () => {
  const env=await setup(),{page}=env; const releases=[];
  try {
    const ref=env.fixture.aircraft, scope=selector(env,[ref],{node_refs:[ref,province],...timed(env,300)});
    await openGraph(page,{config:{graph:scope,positions:{},hidden_refs:[]}});
    assert.ok((await page.evaluate(ref=>WiciWorkspace.getGraphData().nodes.find(node=>node.ref===ref),ref)).position);
    const gap=timed(env,1800).cursor_at;
    let firstSeen, resumedSeen, requests=0;
    const first=new Promise(resolve=>firstSeen=resolve), resumed=new Promise(resolve=>resumedSeen=resolve);
    const handler=async route=>{
      if (Date.parse(route.request().postDataJSON().cursor_at)!==Date.parse(gap)) return route.continue();
      const response=await route.fetch(), index=++requests;
      const hold=new Promise(resolve=>releases.push(resolve));
      if (index===1) firstSeen(); else resumedSeen();
      await hold; await route.fulfill({response}).catch(()=>{});
    };
    await page.route('**/api/workspace/graph/query',handler);
    const value=await page.evaluate(at=>WiciWorkspaceTimeline.localValue(at),gap);
    await page.locator('#analysis-cursor-date').fill(value); await page.locator('#analysis-cursor-date').dispatchEvent('change');
    await first;
    await page.locator('#analysis-view-map').click();
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null,'an interrupted result must not be capturable even while hidden');
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphData()),null);
    await page.locator('#analysis-view-graph').click();
    await resumed;
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null,'capture stays blocked until the resumed response arrives');
    assert.match(await page.locator('#analysis-graph-status').innerText(),/Wczytywanie/);
    releases.splice(0).forEach(release=>release());
    await page.waitForFunction(at=>Date.parse(WiciWorkspace.getGraphData()?.selector.cursor_at)===Date.parse(at),gap);
    const graph=await page.evaluate(()=>WiciWorkspace.getGraphData());
    assert.equal(graph.nodes.find(node=>node.ref===ref).position,null,'current gap replaces the former available position');
    assert.equal(graph.edges.some(edge=>edge.source_ref===ref && edge.type==='reported_in_area'),false);
    assert.equal(Date.parse(await page.evaluate(()=>WiciWorkspace.getGraphCapture().graph.cursor_at)),Date.parse(gap));
    assert.equal(requests,2);
    await page.unroute('**/api/workspace/graph/query',handler);
    // Also cancel the debounced refresh before any request has started.
    await page.evaluate(at=>{const input=document.getElementById('analysis-cursor-date');input.value=WiciWorkspaceTimeline.localValue(at);input.dispatchEvent(new Event('change',{bubbles:true}));document.getElementById('analysis-view-map').click();},scope.cursor_at);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null);
    await page.locator('#analysis-view-graph').click();
    await page.waitForFunction(at=>Date.parse(WiciWorkspace.getGraphData()?.selector.cursor_at)===Date.parse(at),scope.cursor_at);
    assert.ok(await page.evaluate(ref=>WiciWorkspace.getGraphData().nodes.find(node=>node.ref===ref).position,ref));
    assert.deepEqual(env.errors,[]);
  } finally {releases.splice(0).forEach(release=>release());await env.close();}
});

test('Graph regression: a first-layout conflict permits explicit loading without silently overwriting either layout', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    const dossier=await env.api('POST','/dossiers',{name:'Równoległy pierwszy układ'});
    await page.locator('[data-view="situation"]').click();await page.locator('[data-view="analysis"]').click();await settle(page);
    await openGraph(page,{seed_refs:[station],dossier_id:dossier.id});
    const missing=page.waitForResponse(response=>response.request().method()==='GET' && new URL(response.url()).pathname.endsWith(`/dossiers/${dossier.id}/graph`));
    await openDossier(page,dossier.id);assert.equal((await missing).status(),404);
    await page.waitForFunction(()=>!document.getElementById('analysis-dossier-graph-save').disabled);
    const own=await page.evaluate(()=>WiciWorkspace.getGraphConfig());
    const externalPositions={[env.fixture.notice]:{x:135,y:246}};
    const external=await env.api('PUT',`/dossiers/${dossier.id}/graph`,{graph:selector(env,[env.fixture.notice],{dossier_id:dossier.id}),positions:externalPositions,hidden_refs:[],layout:'concentric',revision:0});
    const conflict=page.waitForResponse(response=>response.request().method()==='PUT' && new URL(response.url()).pathname.endsWith(`/dossiers/${dossier.id}/graph`));
    await page.locator('#analysis-dossier-graph-save').click();assert.equal((await conflict).status(),409);
    await page.waitForFunction(()=>document.getElementById('analysis-dossier-dialog').getAttribute('aria-busy')!=='true');
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getGraphConfig().positions),own.positions);
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getGraphConfig().graph.node_refs),own.graph.node_refs);
    assert.deepEqual((await env.api('GET',`/dossiers/${dossier.id}/graph`)).positions,externalPositions);
    assert.equal(await page.locator('#analysis-dossier-graph-load').isEnabled(),true,'a cached 404 cannot prevent explicit recovery');
    await page.locator('#analysis-dossier-graph-load').click();
    await page.waitForFunction(ref=>WiciWorkspace.getGraphData()?.nodes[0]?.ref===ref,env.fixture.notice);
    await page.locator('#analysis-dossier-dialog').waitFor({state:'hidden'});
    const loaded=await page.evaluate(()=>WiciWorkspace.getGraphConfig());
    assert.deepEqual(loaded.graph.node_refs,[env.fixture.notice]);assert.deepEqual(loaded.positions,externalPositions);
    await openDossier(page,dossier.id);
    await mutation(page,'PUT',`/dossiers/${dossier.id}/graph`,()=>page.locator('#analysis-dossier-graph-save').click());
    assert.equal((await env.api('GET',`/dossiers/${dossier.id}/graph`)).revision,external.revision+1,'explicit recovery establishes the correct next write revision');
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph regression: deleting a relation while the graph is hidden invalidates capture and refreshes on return', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;let releasePending;
  try {
    const dossier=await env.api('POST','/dossiers',{name:'Zmiana powiązań przy ukrytym grafie'});
    await env.api('POST',`/dossiers/${dossier.id}/pins`,{ref:station});
    await env.api('POST',`/dossiers/${dossier.id}/pins`,{ref:env.fixture.notice});
    const relation=await env.api('POST',`/dossiers/${dossier.id}/relations`,{source_ref:station,target_ref:env.fixture.notice,justification:'Powiązanie przed usunięciem'});
    await page.locator('[data-view="situation"]').click();await page.locator('[data-view="analysis"]').click();await settle(page);
    await openDossier(page,dossier.id);await page.locator('#analysis-dossier-close').click();
    await openGraph(page,{seed_refs:[station,env.fixture.notice],dossier_id:dossier.id});
    const previous=await page.evaluate(()=>WiciWorkspace.getGraphData());
    const edge=previous.edges.find(item=>item.category==='analyst');assert.ok(edge);
    const ownPositions=await page.evaluate(()=>WiciWorkspace.getGraphConfig().positions);
    assert.ok(await page.evaluate(()=>WiciWorkspace.getGraphCapture()));
    await page.locator('#analysis-view-map').click();
    let graphRequests=0;page.on('request',request=>{if(new URL(request.url()).pathname==='/api/workspace/graph/query') graphRequests++;});
    const before=graphRequests;
    await openDossier(page,dossier.id);
    await page.locator(`[data-relation-id="${relation.id}"]`).getByRole('button',{name:'Usuń powiązanie',exact:true}).click();
    await mutation(page,'DELETE',`/relations/${relation.id}`,()=>page.locator('#analysis-dossier-confirm').getByRole('button',{name:'Usuń trwale',exact:true}).click());
    assert.equal(graphRequests,before,'a hidden graph defers its network read');
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null,'deleted relationships cannot be captured from the retained result');
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphData()),null,'the retained result is no longer current');
    assert.equal(await page.locator('#analysis-dossier-graph-capture').isDisabled(),true);
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getGraphConfig().positions),ownPositions,'invalidation preserves working node positions');
    await page.locator('#analysis-dossier-close').click();
    let arrived;const seen=new Promise(resolve=>arrived=resolve),hold=new Promise(resolve=>releasePending=resolve);
    await page.route('**/api/workspace/graph/query',async route=>{const response=await route.fetch();arrived();await hold;await route.fulfill({response});});
    await page.locator('#analysis-view-graph').click();await seen;
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null,'capture remains blocked until the new result is available');
    releasePending();releasePending=null;await graphReady(page);
    const current=await page.evaluate(()=>WiciWorkspace.getGraphData());
    assert.equal(current.edges.some(item=>item.id===edge.id),false,'the deleted edge disappears after returning');
    assert.equal(current.edges.some(item=>item.category==='analyst'),false);
    assert.equal(await page.locator(`[data-edge-id="${edge.id}"]`).count(),0);
    assert.notEqual(current.revision,previous.revision);
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getGraphConfig().positions),ownPositions);
    assert.ok(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),'a fresh graph can be captured again');
    assert.equal(graphRequests,before+1);
    assert.deepEqual(env.errors,[]);
  } finally {releasePending?.();await env.close();}
});

test('Graph regression: changing dossiers during the first graph load rejects all obsolete case responses', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;let releasePending;
  try {
    const cases=[];
    for (const name of ['Pierwsza teczka podczas ładowania','Docelowa teczka podczas ładowania']) {
      const dossier=await env.api('POST','/dossiers',{name});
      const relation=await env.api('POST',`/dossiers/${dossier.id}/relations`,{source_ref:station,target_ref:env.fixture.notice,justification:name});
      cases.push({...dossier,relation});
    }
    await page.locator('[data-view="situation"]').click();await page.locator('[data-view="analysis"]').click();await settle(page);
    let firstSeen;const seen=new Promise(resolve=>firstSeen=resolve),hold=new Promise(resolve=>releasePending=resolve),requested=[];
    await page.route('**/api/workspace/graph/query',async route=>{
      requested.push(route.request().postDataJSON().dossier_id || null);
      const response=await route.fetch();firstSeen();await hold;await route.fulfill({response}).catch(()=>{});
    });
    // Do not await openGraph: its first response is deliberately held before any data exists.
    await page.evaluate(refs=>{WiciWorkspace.openGraph({seed_refs:refs});},[station,env.fixture.notice]);await seen;
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphData()),null);
    await openDossier(page,cases[0].id);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphConfig().graph.dossier_id),cases[0].id);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null);
    await page.locator('#analysis-dossier-close').click();
    await openDossier(page,cases[1].id);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphConfig().graph.dossier_id),cases[1].id);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphCapture()),null);
    releasePending();releasePending=null;await graphReady(page);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const graph=await page.evaluate(()=>WiciWorkspace.getGraphData());
    assert.equal(graph.selector.dossier_id,cases[1].id,'a previous response cannot restore null or another dossier');
    assert.deepEqual(requested,[null,cases[0].id,cases[1].id],'each switch replaces the pending request even without a previous result');
    const relations=graph.edges.filter(edge=>edge.category==='analyst');
    assert.equal(relations.length,1);
    assert.equal(relations[0].provenance.id,cases[1].relation.id);
    assert.equal(relations[0].provenance.justification,cases[1].name);
    const capture=await page.evaluate(()=>WiciWorkspace.getGraphCapture());
    assert.equal(capture.graph.dossier_id,cases[1].id);
    assert.equal(await page.locator('#analysis-dossier-graph-capture').isEnabled(),true);
    assert.equal(await page.locator('#analysis-dossier-dialog').evaluate(node=>node.open),true);
    assert.deepEqual(env.errors,[]);
  } finally {releasePending?.();await env.close();}
});

test('Graph regression: historical transport without comparison can be shown on the map but gaps cannot', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    for (const {ref,context} of [{ref:env.fixture.aircraft,context:timed(env,300)},{ref:env.fixture.ship,context:timed(env,300)},
      {ref:env.fixture.ship,context:{time:{mode:'range',filter_range:env.fixture.range},cursor_at:null}}]) {
      await openGraph(page,{config:{graph:selector(env,[ref],context),positions:{},hidden_refs:[]}});
      const point=await page.evaluate(ref=>WiciWorkspace.getGraphData().nodes.find(node=>node.ref===ref).position,ref);
      assert.ok(point);
      assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getState().comparedRefs),[]);
      await page.locator(`[data-graph-ref="${ref}"] .analysis-graph-select`).click();
      await page.waitForFunction(()=>document.getElementById('analysis-card-title').textContent!=='Wczytywanie obiektu…');
      await page.evaluate(()=>state.map.setView([49,15],6,{animate:false}));
      await page.getByRole('button',{name:'Pokaż na mapie',exact:true}).click();
      await page.waitForFunction(point=>state.map.project(state.map.getCenter()).distanceTo(state.map.project([point.latitude,point.longitude]))<1.5,point);
      assert.equal(await page.locator('#map').isVisible(),true);
      assert.ok(await page.evaluate(()=>state.map.getZoom()>=10));
      assert.doesNotMatch(await page.locator('#analysis-message').innerText(),/Brak zapisanej pozycji/);
      assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getState().comparedRefs),[],'showing a graph point does not implicitly add a comparison');
      await page.locator('#analysis-close-card').click();
    }
    const ref=env.fixture.aircraft;
    await openGraph(page,{config:{graph:selector(env,[ref],timed(env,300)),positions:{},hidden_refs:[]}});
    await page.locator(`[data-graph-ref="${ref}"] .analysis-graph-select`).click();
    await page.waitForFunction(()=>document.getElementById('analysis-card-title').textContent!=='Wczytywanie obiektu…');
    await page.getByRole('button',{name:'Pokaż na mapie',exact:true}).click();
    const readsBefore=env.reads.filter(path=>path==='/api/workspace/graph/query').length;
    const gap=timed(env,1800).cursor_at;
    const input=await page.evaluate(at=>WiciWorkspaceTimeline.localValue(at),gap);
    await page.locator('#analysis-cursor-date').fill(input);await page.locator('#analysis-cursor-date').dispatchEvent('change');
    await page.waitForFunction(at=>Date.parse(WiciWorkspace.getState().cursorAt)===Date.parse(at),gap);
    assert.equal(await page.evaluate(()=>WiciWorkspace.getGraphData()),null,'changing time on the map must invalidate the former graph point');
    assert.equal(await page.locator('.analysis-graph-map-marker').count(),0,'the former cursor marker disappears immediately');
    assert.equal(env.reads.filter(path=>path==='/api/workspace/graph/query').length,readsBefore,'a hidden graph is not fetched in the background');
    await page.evaluate(()=>state.map.setView([49,15],6,{animate:false}));
    await page.getByRole('button',{name:'Pokaż na mapie',exact:true}).click();
    assert.match(await page.locator('#analysis-message').innerText(),/Brak zapisanej pozycji przy kursorze/);
    assert.ok(await page.evaluate(()=>state.map.project(state.map.getCenter()).distanceTo(state.map.project([49,15]))<1.5),'an outdated graph point must not move the map');
    await page.locator('#analysis-close-card').click();await page.locator('#analysis-view-graph').click();await graphReady(page);
    assert.equal(Date.parse(await page.evaluate(()=>WiciWorkspace.getGraphData().selector.cursor_at)),Date.parse(gap));
    assert.equal(await page.evaluate(ref=>WiciWorkspace.getGraphData().nodes.find(node=>node.ref===ref).position,ref),null);
    await page.locator(`[data-graph-ref="${ref}"] .analysis-graph-select`).click();
    await page.waitForFunction(()=>document.getElementById('analysis-card-title').textContent!=='Wczytywanie obiektu…');
    await page.evaluate(()=>state.map.setView([49,15],6,{animate:false}));
    await page.getByRole('button',{name:'Pokaż na mapie',exact:true}).click();
    assert.match(await page.locator('#analysis-message').innerText(),/Brak zapisanej pozycji przy kursorze/);
    const center=await page.evaluate(()=>({pixels:state.map.project(state.map.getCenter()).distanceTo(state.map.project([49,15])),zoom:state.map.getZoom()}));
    assert.ok(center.pixels<1.5);
    assert.equal(center.zoom,6,'a gap must not fall back to a live or previous position');
    assert.equal(await page.locator('.analysis-graph-map-marker').count(),0);
    assert.deepEqual(await page.evaluate(()=>WiciWorkspace.getState().comparedRefs),[]);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});

test('Graph regression: loading and resaving a working graph preserves its wider overview and narrow time filter', {timeout:90000}, async () => {
  const env=await setup(),{page}=env;
  try {
    const dossier=await env.api('POST','/dossiers',{name:'Różne zakresy czasu grafu'});
    const start=Date.parse(env.fixture.range.from),overview=env.fixture.range;
    const filter={from:new Date(start+10*60000).toISOString(),to:new Date(start+20*60000).toISOString()},cursor=new Date(start+15*60000).toISOString();
    const graph=selector(env,[station],{dossier_id:dossier.id,time:{mode:'range',overview_range:overview,filter_range:filter},cursor_at:cursor,display_timezone:'Europe/Kyiv'});
    const saved=await env.api('PUT',`/dossiers/${dossier.id}/graph`,{graph,positions:{[station]:{x:180,y:90}},hidden_refs:[],layout:'concentric',revision:0});
    await page.locator('[data-view="situation"]').click();await page.locator('[data-view="analysis"]').click();await settle(page);
    await openDossier(page,dossier.id);await page.locator('#analysis-dossier-graph-load').click();
    await page.waitForFunction(id=>WiciWorkspace.getGraphData()?.selector.dossier_id===id,dossier.id);
    await page.locator('#analysis-dossier-dialog').waitFor({state:'hidden'});
    const epochs=value=>({from:Date.parse(value.from || value.start),to:Date.parse(value.to || value.end)});
    const state=await page.evaluate(()=>WiciWorkspace.getState());
    assert.deepEqual(epochs(state.query.time.overview_range),epochs(overview),'shared histogram keeps the whole hour');
    assert.deepEqual(epochs(state.query.time.filter_range),epochs(filter),'catalogue retains the selected ten minutes');
    assert.equal(Date.parse(state.cursorAt),Date.parse(cursor));assert.equal(state.displayTimezone,'Europe/Kyiv');
    const current=await page.evaluate(()=>WiciWorkspace.getGraphData());
    assert.deepEqual(epochs(current.selector.time.overview_range),epochs(overview),'graph query receives the same overview');
    assert.deepEqual(epochs(current.selector.time.filter_range),epochs(filter));
    await openDossier(page,dossier.id);
    await mutation(page,'PUT',`/dossiers/${dossier.id}/graph`,()=>page.locator('#analysis-dossier-graph-save').click());
    const resaved=await env.api('GET',`/dossiers/${dossier.id}/graph`);
    assert.equal(resaved.revision,saved.revision+1);
    assert.deepEqual(epochs(resaved.graph.time.overview_range),epochs(overview),'resaving must not narrow the persisted overview');
    assert.deepEqual(epochs(resaved.graph.time.filter_range),epochs(filter));
    assert.equal(Date.parse(resaved.graph.cursor_at),Date.parse(cursor));
    assert.deepEqual(resaved.positions,saved.positions);
    assert.deepEqual(env.errors,[]);
  } finally {await env.close();}
});
