'use strict';
/* Shared small controls for the three local monitoring panels. All remote text stays text. */
window.WiciMonitorUI = (() => {
  const U = window.WiciWorkspaceUI;
  function input(id, type = 'text', value = '') {const node = U.el('input'); node.id = id; node.type = type; node.value = value; return node;}
  function select(id, values) {const node = U.el('select'); node.id = id; for (const [value, label] of values) {const option = U.el('option', label); option.value = value; node.append(option);} return node;}
  function dialog(id, title) {
    const node = U.el('dialog', null, 'analysis-monitor-dialog'); node.id = id;
    const header = U.el('div', null, 'analysis-monitor-heading'), heading = U.el('h2', title), close = U.button('Zamknij', () => node.close()); heading.id = `${id}-title`; heading.tabIndex = -1;
    node.setAttribute('aria-labelledby', heading.id); header.append(heading, close);
    const status = U.el('p', null, 'analysis-monitor-status'); status.setAttribute('role', 'status');
    const body = U.el('div', null, 'analysis-monitor-body'); node.append(header, status, body); document.body.append(node);
    return {node, body, status, show() {if (!node.open) node.showModal(); heading.focus();}, tell(text, error = false) {status.textContent = text; status.dataset.error = String(error);}};
  }
  function facts(host, entries) {const dl = U.el('dl', null, 'analysis-material-facts'); for (const [label, value] of entries) {dl.append(U.el('dt', label), U.el('dd', value ?? 'Brak danych'));} host.append(dl);}
  function json(host, title, value) {const details = U.el('details'); details.append(U.el('summary', title), U.el('pre', JSON.stringify(value, null, 2))); host.append(details);}
  return {input, select, dialog, facts, json};
})();
window.WiciWorkspaceAreas = function (host, {request, map, selectObject, showMap, changed, createRule}) {
  const U = window.WiciWorkspaceUI, H = window.WiciMonitorUI, D = H.dialog('analysis-areas-dialog', 'Własne obszary zainteresowania');
  const launcher = U.button('Obszary', () => open()); launcher.id = 'analysis-areas-open'; host.append(launcher);
  const tools = U.el('div', null, 'analysis-monitor-actions'), choose = H.select('analysis-area-select', [['', 'Nowy obszar']]), archivedFilter = H.input('analysis-area-include-archived', 'checkbox');
  tools.append(choose, U.button('Nowy obszar', () => edit(null)), U.button('Wczytaj bieżący zapis', async () => {const id=selected?.id, run=++generation; drafts.delete(id||'_new'); const loaded=await load(); if(loaded&&run===generation&&D.node.open)edit(items.find(item=>item.id===id)||null,true);}), U.field('Także archiwalne', archivedFilter));
  const form = U.el('form', null, 'analysis-monitor-form'); form.id = 'analysis-area-form';
  const name = H.input('analysis-area-name'), description = U.el('textarea'), shape = H.select('analysis-area-shape', [['polygon', 'Wielokąt'], ['rectangle', 'Prostokąt'], ['circle', 'Koło']]), color = H.input('analysis-area-color', 'color', '#217c83'); description.id = 'analysis-area-description'; name.maxLength = 120; description.maxLength = 5000;
  const geometry = U.el('textarea'); geometry.id = 'analysis-area-geometry'; geometry.rows = 5; geometry.placeholder = '{"type":"Polygon","coordinates":[[[21,52],[22,52],[22,53],[21,52]]]}';
  const lon = H.input('analysis-area-longitude', 'number'), lat = H.input('analysis-area-latitude', 'number'), radius = H.input('analysis-area-radius', 'number'); lon.step = lat.step = 'any'; radius.min = '1'; radius.step = 'any';
  const circle = U.el('div', null, 'analysis-monitor-grid'); circle.append(U.field('Długość środka (°)', lon), U.field('Szerokość środka (°)', lat), U.field('Promień (m)', radius));
  const geometryLabel = U.field('Geometria GeoJSON — można także wkleić dokładne współrzędne', geometry);
  const draw = U.button('Narysuj obszar', beginDrawing); draw.id = 'analysis-area-draw';
  const save = U.button('Zapisz obszar', saveArea), duplicate = U.button('Powiel', duplicateArea), archive = U.button('Archiwizuj', archiveArea), membersButton = U.button('Obiekty w obszarze', loadMembers);
  save.id = 'analysis-area-save'; duplicate.id = 'analysis-area-duplicate'; archive.id = 'analysis-area-archive'; membersButton.id = 'analysis-area-members';
  const actions = U.el('div', null, 'analysis-monitor-actions');
  const pinButton=U.button('Otwórz kartę i przypnij do teczki', () => {if (selected) {D.node.close(); selectObject(selected.ref);}}), ruleButton=U.button('Utwórz regułę', () => {if (selected) {D.node.close(); createRule({area_id: selected.id});}}); pinButton.disabled=ruleButton.disabled=true;
  actions.append(save, duplicate, archive, membersButton, pinButton, ruleButton);
  form.append(U.field('Nazwa obszaru', name), U.field('Opis', description), U.field('Kształt', shape), U.field('Kolor', color), draw, geometryLabel, circle, actions);
  const fieldset = U.el('fieldset'); fieldset.append(...form.children); form.append(fieldset);
  const revision = U.el('p', null, 'muted'), members = U.el('section'); members.id = 'analysis-area-member-list';
  D.body.append(U.el('p', 'Granica należy do obszaru. Zmiana geometrii tworzy nową rewizję; wcześniejsze zdarzenia zachowują swoją podstawę.', 'muted'), tools, form, revision, members);
  let items = [], selected = null, generation = 0, listRun = 0, busy = false, drawing = null, drawingLayer = null, baseRevision = null;
  const drafts = new Map();
  function remember() {drafts.set(selected?.id || '_new', {revision: baseRevision, name: name.value, description: description.value, shape: shape.value, color: color.value, geometry: geometry.value, lon: lon.value, lat: lat.value, radius: radius.value});}
  function shapeFields() {circle.hidden = shape.value !== 'circle'; geometryLabel.hidden = shape.value === 'circle';}
  shape.addEventListener('change', shapeFields); form.addEventListener('submit', event => {event.preventDefault(); saveArea();});
  form.addEventListener('input', () => {++previewRun; remember();});
  choose.addEventListener('change', () => {remember(); edit(items.find(item => item.id === choose.value) || null);});
  archivedFilter.addEventListener('change', load);
  function edit(item, fresh = false) {
    ++generation; selected = item; choose.value = item?.id || ''; const draft = !fresh && drafts.get(item?.id || '_new'); baseRevision = draft?.revision ?? item?.revision ?? null;
    name.value = draft?.name ?? item?.name ?? ''; description.value = draft?.description ?? item?.description ?? ''; shape.value = draft?.shape ?? item?.shape ?? 'polygon'; color.value = draft?.color ?? item?.color ?? '#217c83';
    geometry.value = draft?.geometry ?? (item?.geometry ? JSON.stringify(item.geometry) : ''); lon.value = draft?.lon ?? item?.center?.[0] ?? ''; lat.value = draft?.lat ?? item?.center?.[1] ?? ''; radius.value = draft?.radius ?? item?.radius_m ?? '';
    duplicate.disabled = archive.disabled = membersButton.disabled = pinButton.disabled = ruleButton.disabled = !item; archive.textContent = item?.archived ? 'Przywróć z archiwum' : 'Archiwizuj';
    revision.textContent = item ? `Szkic oparty na rewizji ${baseRevision}${baseRevision !== item.revision ? ' · dostępna nowsza rewizja, wczytaj bieżący zapis' : ''}${item.archived ? ' · obszar archiwalny' : ''}` : 'Nowy obszar · limit 100 obszarów'; members.replaceChildren(); shapeFields(); D.tell('');
  }
  async function load() {const run = ++listRun; try {const result = await request(`/workspace/areas?include_archived=${archivedFilter.checked}`); if (run !== listRun) return; items = result.items || []; const value = choose.value; choose.replaceChildren(); for (const [id, text] of [['', 'Nowy obszar'], ...items.map(item => [item.id, `${item.name}${item.archived ? ' · archiwalny' : ''}`])]) {const option = U.el('option', text); option.value = id; choose.append(option);} choose.value = value; return true;} catch (error) {if (run === listRun) D.tell(error.message, true); return false;}}
  async function open(id) {D.show(); const run = ++generation, loaded = await load(); if (!loaded || run !== generation || !D.node.open) return; edit(items.find(item => item.id === id) || null);}
  function payload() {const raw = {name: name.value.trim(), description: description.value.trim(), shape: shape.value, color: color.value, archived: selected?.archived || false}; if (selected) raw.revision = baseRevision;
    if (raw.shape === 'circle') {raw.center = [Number(lon.value), Number(lat.value)]; raw.radius_m = Number(radius.value); if (!lon.value || !lat.value || !radius.value) throw Error('Podaj środek i promień koła albo narysuj je na mapie.');}
    else {try {raw.geometry = JSON.parse(geometry.value);} catch {throw Error('Narysuj obszar albo podaj prawidłową geometrię GeoJSON.');}} return raw;
  }
  async function mutate(action) {if (busy) return; const run = generation; busy = true; fieldset.disabled = true; save.disabled = true; D.node.setAttribute('aria-busy', 'true');
    try {const result = await action(); if(result?.archived)archivedFilter.checked=true; await load(); changed(); if (run === generation && D.node.open) {if (result?.id) {drafts.delete(selected?.id || '_new'); edit(result, true);} D.tell('Zapisano. Wcześniejsze zdarzenia zachowują poprzednią rewizję.');}}
    catch (error) {if (run === generation) D.tell(error.status === 409 ? 'Obszar zmienił się w innym oknie. Szkic zachowano. Otwórz obszar ponownie, aby pobrać nową rewizję.' : error.message, true);} finally {busy = false; fieldset.disabled = false; save.disabled = false; D.node.setAttribute('aria-busy', 'false');}}
  function saveArea() {let raw; try {raw = payload();} catch (error) {D.tell(error.message, true); return;} const id = selected?.id; mutate(() => request(`/workspace/areas${id ? '/'+id : ''}`, raw, {method: id ? 'PUT' : 'POST'}));}
  function duplicateArea() {if (selected) {const id = selected.id; mutate(() => request(`/workspace/areas/${id}/duplicate`, {}, {method: 'POST'}));}}
  function archiveArea() {if (!selected) return; let raw; try {raw = {...payload(), archived: !selected.archived};} catch (error) {D.tell(error.message, true); return;} const id = selected.id; mutate(() => request(`/workspace/areas/${id}`, raw, {method: 'PUT'}));}
  let previewRun = 0;
  async function loadMembers() {if (!selected) return; const id = selected.id, run = ++previewRun, context = generation; members.replaceChildren(U.el('p', 'Sprawdzanie rzeczywistych współrzędnych…'));
    try {const result = await request(`/workspace/areas/${id}/members`); if (run !== previewRun || context !== generation || !D.node.open) return; members.replaceChildren(U.el('h3', `Obiekty w obszarze (${result.total ?? result.items?.length ?? 0})`)); for (const item of result.items || []) members.append(U.button(item.label || item.ref, () => {D.node.close(); selectObject(item.ref);})); members.append(U.el('p', result.note || 'Dostępne lokalizacje katalogu; brak pozycji nie oznacza wyjścia z obszaru.', 'muted'));} catch (error) {if (run === previewRun && context === generation) D.tell(error.message, true);}}
  function stopDrawing(reopen = true) {if (!drawing) return; map.off('click', drawClick); document.removeEventListener('keydown', drawKeys); if (drawing.zoom) map.doubleClickZoom.enable(); drawing.controls.remove(); drawing = null; map.getContainer().classList.remove('analysis-drawing'); if (drawingLayer) map.removeLayer(drawingLayer); drawingLayer = null; if (reopen) D.show();}
  function finishDrawing() {if (!drawing || drawing.points.length < (shape.value === 'polygon' ? 3 : 2)) return;
    const points = drawing.points; if (shape.value === 'circle') {lon.value = points[0][1]; lat.value = points[0][0]; radius.value = Math.round(map.distance(points[0], points[1]));}
    else {let ring = points.map(point => [point[1], point[0]]); if (shape.value === 'rectangle') {const [a,b] = ring; ring = [[Math.min(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.max(a[1],b[1])],[Math.min(a[0],b[0]),Math.max(a[1],b[1])]];} ring.push([...ring[0]]); geometry.value = JSON.stringify({type:'Polygon',coordinates:[ring]});} remember(); stopDrawing(); D.tell('Kształt gotowy. Zapisz obszar, aby utrwalić rewizję.');}
  function drawKeys(event) {if (event.key === 'Escape') {event.preventDefault(); stopDrawing();} if (event.key === 'Enter' && drawing) {event.preventDefault(); finishDrawing();}}
  function drawClick(event) {if (!drawing) return; const {lat,lng} = event.latlng; if(drawing.points.length>=300){drawing.label.textContent='Osiągnięto limit 300 wierzchołków — zakończ kształt.';return;} const previous=drawing.points.at(-1);if(previous&&Math.abs(previous[0]-lat)<1e-9&&Math.abs(previous[1]-lng)<1e-9)return; drawing.points.push([lat,lng]); const points = drawing.points; if (drawingLayer) map.removeLayer(drawingLayer);
    drawingLayer = (shape.value === 'circle' && points.length > 1 ? L.circle(points[0], {radius:map.distance(points[0],points[1]),color:color.value}) : shape.value === 'rectangle' && points.length > 1 ? L.rectangle(points,{color:color.value}) : points.length > 2 ? L.polygon(points,{color:color.value}) : L.polyline(points,{color:color.value})).addTo(map);
    drawing.finish.disabled = points.length < (shape.value === 'polygon' ? 3 : 2); drawing.label.textContent = `${shape.value === 'polygon' ? 'Wielokąt: wskaż kolejne wierzchołki i zakończ' : 'Wskaż dwa punkty'} · ${points.length} punktów`; if (shape.value !== 'polygon' && points.length === 2) finishDrawing();}
  function beginDrawing() {if (!map || !window.L) {D.tell('Mapa jest niedostępna.', true); return;} remember(); showMap(); D.node.close();
    const controls = U.el('div', null, 'analysis-draw-controls'); controls.id = 'analysis-area-drawing'; const label = U.el('span', shape.value === 'polygon' ? 'Wskaż wierzchołki wielokąta na mapie' : shape.value === 'circle' ? 'Wskaż środek i punkt na obwodzie' : 'Wskaż przeciwległe rogi prostokąta'), finish = U.button('Zakończ kształt', finishDrawing); finish.disabled = true; controls.append(label,finish,U.button('Anuluj rysowanie',()=>stopDrawing())); document.body.append(controls);
    drawing = {points:[],controls,label,finish,zoom:map.doubleClickZoom.enabled()}; map.doubleClickZoom.disable(); map.getContainer().classList.add('analysis-drawing'); map.on('click', drawClick); document.addEventListener('keydown',drawKeys);}
  D.node.addEventListener('close', () => {++generation; ++previewRun;});
  return {open, load, close() {stopDrawing(false); if (D.node.open) D.node.close();}, getItems: () => items};
};
