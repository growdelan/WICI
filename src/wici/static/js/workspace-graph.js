'use strict';
/* Object graphs are bounded local explorations. Layout never changes source facts. */
(function (root) {
  const categoryNames = {source: 'Źródłowa', derived: 'Wyliczona', analyst: 'Analityczna'};
  const relationLabels = {communication_area: 'Obszar komunikatu', station_area: 'Położenie stacji', administrative_parent: 'Hierarchia PRG', region_parent: 'Hierarchia Ukrainy', alert_region: 'Region alarmu', reported_in_area: 'Raport pozycji w obszarze', custom_area_member: 'Położenie we własnym obszarze', analyst_related: 'Powiązanie analityczne'};
  const categoryColors = {source: '#217c83', derived: '#967126', analyst: '#8060b0'};
  const clone = value => structuredClone(value);
  function limitMessage(data) {return data?.edge_limit_reached ? `Pokazano ${data.edges?.length || 0} z ${data.edge_total} relacji. Osiągnięto limit ${data.limits?.max_edges || 500}; zawęź rodzaj lub podstawę relacji.` : '';}
  function visibleData(data, hidden = []) {
    const excluded = new Set(hidden), nodes = (data?.nodes || []).filter(node => !excluded.has(node.ref));
    const refs = new Set(nodes.map(node => node.ref));
    return {nodes, edges: (data?.edges || []).filter(edge => refs.has(edge.source_ref) && refs.has(edge.target_ref))};
  }
  function pathBetween(data, start, end, hidden = []) {
    const graph = visibleData(data, hidden), refs = new Set(graph.nodes.map(node => node.ref));
    if (!refs.has(start) || !refs.has(end)) return null;
    const queue = [start], previous = new Map([[start, null]]);
    for (let i = 0; i < queue.length && !previous.has(end); i++) for (const edge of graph.edges) {
      const next = edge.source_ref === queue[i] ? edge.target_ref : edge.target_ref === queue[i] ? edge.source_ref : null;
      if (next && !previous.has(next)) {previous.set(next, {ref: queue[i], edge: edge.id}); queue.push(next);}
    }
    if (!previous.has(end)) return null;
    const nodes = [end], edges = []; let current = end;
    while (previous.get(current)) {const step = previous.get(current); nodes.unshift(step.ref); edges.unshift(step.edge); current = step.ref;}
    return {nodes, edges};
  }
  const civilTypes = new Set([20,21,22,23,24,29,30,31,32,33,34,36,37,40,41,42,43,44,49,50,52,53,54,60,61,62,63,64,69,70,71,72,73,74,79,80,81,82,83,84,89]);
  function transportStyle(node, referenceAt = null) {
    const meta = node.metadata || {}, point = node.position || {};
    if (node.type === 'aircraft') return {glyph: '✈', color: meta.military === true ? '#b45309' : '#17465c', angle: Number.isFinite(point.heading) ? point.heading - 90 : -90};
    if (node.type === 'ship') {const key = root.WiciShips?.classification?.(meta).key || (meta.type_code === 35 ? 'military' : civilTypes.has(meta.type_code) ? 'civilian' : 'unclassified'), known = Number.isFinite(point.heading) && point.heading >= 0 && point.heading < 360; return {glyph: 'ship', color: {military: '#843ba7', civilian: '#126b78', unclassified: '#65717e'}[key], angle: known ? point.heading : 0, unknown: !known, old: Number.isFinite(referenceAt) && Number.isFinite(Date.parse(point.position_at)) && referenceAt - Date.parse(point.position_at) > 300000};}
    return {glyph: ({communication: '▤', hydro_station: '≈', air_quality_station: '◉', area: '◇', custom_area: '⬡', ua_region: '◇', civil_alert: '!'})[node.type] || '○', color: '#217c83', angle: 0};
  }
  function symbol(node, referenceAt = null) {
    const style = transportStyle(node, referenceAt), fill = style.old ? 'url(#old)' : style.color, content = style.glyph === 'ship'
      ? style.unknown ? `<circle cx="24" cy="24" r="11" fill="${fill}"/>` : `<path d="M24 5 35 19 33 39 15 39 13 19Z" fill="${fill}"/>`
      : `<text x="24" y="34" text-anchor="middle" font-size="34" font-family="Arial,sans-serif" fill="${style.color}">${style.glyph}</text>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><defs><pattern id="old" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="${style.color}"/><rect width="3" height="7" fill="#ffffff" fill-opacity=".65"/></pattern></defs><g transform="rotate(${style.angle},24,24)">${content}</g></svg>`);
  }
  function elements(data, positions, hidden) {
    const graph = visibleData(data, hidden), selector = data?.selector || {}, referenceAt = Date.parse(selector.cursor_at || (selector.time?.mode === 'range' ? selector.time.filter_range?.to : data?.as_of));
    return [...graph.nodes.map(node => ({data: {id: node.ref, label: node.label || node.ref, symbol: symbol(node, referenceAt), available: node.available === false ? 'false' : 'true'}, ...(positions[node.ref] ? {position: positions[node.ref]} : {})})),
      ...graph.edges.map(edge => ({data: {id: edge.id, source: edge.source_ref, target: edge.target_ref, label: edge.label || edge.type, category: edge.category, color: categoryColors[edge.category] || categoryColors.analyst, arrow: edge.directed === false ? 'none' : 'triangle'}}))];
  }
  function styles(dark = false) {
    return [
      {selector: 'node', style: {'width': 44, 'height': 44, 'background-color': dark ? '#eef7f5' : '#ffffff', 'background-image': 'data(symbol)', 'background-fit': 'contain', 'border-width': 2, 'border-color': dark ? '#73c2be' : '#2b777c', 'label': 'data(label)', 'font-size': 11, 'color': dark ? '#e3eff0' : '#193940', 'text-wrap': 'ellipsis', 'text-max-width': 145, 'text-valign': 'bottom', 'text-margin-y': 7}},
      {selector: 'node[available = "false"]', style: {'border-style': 'dashed', 'opacity': .65}},
      {selector: 'edge', style: {'width': 1.8, 'curve-style': 'bezier', 'line-color': 'data(color)', 'target-arrow-color': 'data(color)', 'target-arrow-shape': 'data(arrow)', 'label': 'data(label)', 'font-size': 9, 'color': dark ? '#c4d7d9' : '#3d565c', 'text-background-color': dark ? '#132731' : '#ffffff', 'text-background-opacity': .9, 'text-background-padding': 3, 'text-wrap': 'wrap', 'text-max-width': 120}},
      {selector: 'edge[category = "source"]', style: dark ? {'line-color': '#68c7c1', 'target-arrow-color': '#68c7c1'} : {}},
      {selector: 'edge[category = "derived"]', style: {'line-style': 'dashed', ...(dark ? {'line-color': '#d9ad56', 'target-arrow-color': '#d9ad56'} : {})}},
      {selector: 'edge[category = "analyst"]', style: {'line-style': 'dotted', 'width': 3, ...(dark ? {'line-color': '#bf9be8', 'target-arrow-color': '#bf9be8'} : {})}},
      {selector: ':selected', style: {'border-width': 4, 'border-color': '#d19231', 'line-color': '#d19231', 'target-arrow-color': '#d19231'}},
      {selector: 'node.graph-path', style: {'border-width': 4, 'border-color': '#d19231'}},
      {selector: 'edge.graph-path', style: {'line-color': '#d19231', 'target-arrow-color': '#d19231', 'width': 4}},
    ];
  }
  function formatGraphTime(value, timezone = 'UTC') {if (value == null) return 'Brak czasu'; const text = String(value); if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return `${text} · sama data`; if (!/(Z|[+-]\d{2}:\d{2})$/.test(text) || !Number.isFinite(Date.parse(text))) return text; return `${new Intl.DateTimeFormat('pl-PL', {timeZone: timezone, dateStyle: 'short', timeStyle: 'medium'}).format(new Date(text))} (${text})`;}
  function renderEdgeFacts(parent, edge, U, timezone = 'UTC') {
    const names = {basis: 'Podstawa', method: 'Metoda', method_version: 'Wersja metody', source_id: 'Źródło', source_url: 'Adres źródła', role: 'Rola obszaru', geometry_context: 'Geometria', justification: 'Uzasadnienie analityka', observed_at: 'Czas obserwacji', fetched_at: 'Czas pobrania', from: 'Od', to: 'Do (wyłącznie)', valid_from: 'Ważność od', valid_until: 'Ważność do', first_seen_at: 'Pierwsza lokalna obserwacja', last_seen_at: 'Ostatnia lokalna obserwacja', source_since: 'Początek według źródła', ended_after: 'Koniec później niż', ended_before: 'Koniec nie później niż', source_published_at: 'Publikacja źródłowa', source_published_date: 'Dzień publikacji źródłowej', created_at: 'Utworzono', updated_at: 'Zmieniono', kind: 'Znaczenie czasu', context: 'Kontekst czasu', document_version_id: 'Wersja dokumentu', note_id: 'Notatka teczki', material_id: 'Materiał teczki', revision: 'Rewizja', evidence: 'Materiał uzasadniający', evidence_missing: 'Niedostępne materiały', track_id: 'Sesja zapisu', latitude: 'Szerokość geograficzna', longitude: 'Długość geograficzna'};
    const words = {current_metadata: 'Bieżące metadane katalogu', source_version: 'Wybrana wersja źródłowa', observation: 'Konkretny raport obserwacji', interval: 'Przedział obserwacji z możliwą niepewnością końca', analyst_assertion: 'Powiązanie dodane przez analityka', current: 'Bieżący katalog', warning_area: 'Obszar ostrzeżenia', notification_area: 'Obszar powiadomienia', station_location: 'Lokalizacja stacji', point_in_prg: 'Przypisanie punktu do lokalnych granic PRG', source_administrative_code: 'Kod lub nazwa administracyjna ze źródła', reported_point_in_prg: 'Przypisanie zarejestrowanego raportu do granic PRG'};
    const dl = U.el('dl', null, 'analysis-graph-edge-facts');
    for (const [key, value] of Object.entries({...edge.provenance, ...edge.time})) {
      if (value == null || Array.isArray(value) && !value.length || ['id','dossier_id'].includes(key)) continue;
      const dd = U.el('dd');
      if (key.includes('url')) {const link = U.safeLink(value); dd.append(link || U.el('span', 'Nieprawidłowy adres źródła'));}
      else dd.textContent = /(_at|^valid_from$|^valid_until$|^source_since$|^ended_after$|^ended_before$|^source_published_date$|^from$|^to$)/.test(key) ? formatGraphTime(value,timezone) : typeof value === 'object' ? JSON.stringify(value) : ['kind','context','method','role','geometry_context'].includes(key) && Object.prototype.hasOwnProperty.call(words,value) ? words[value] : String(value);
      dl.append(U.el('dt', names[key] || key), dd);
    }
    parent.append(dl); return dl;
  }
  function createReadOnly(host, data, savedPositions = {}) {
    const U = root.WiciWorkspaceUI, graph = data || {}, positions = graph.positions || savedPositions, timezone = graph.selector?.display_timezone || 'Europe/Warsaw';
    const visible = visibleData(graph, graph.hidden_refs || []), types = graph.node_type ? new Set(visible.nodes.filter(node => node.type === graph.node_type).map(node => node.ref)) : null;
    const shown = {nodes: visible.nodes.filter(node => !types || types.has(node.ref)), edges: visible.edges.filter(edge => !types || types.has(edge.source_ref) && types.has(edge.target_ref)), selector: graph.selector, as_of: graph.as_of};
    host.append(U.el('p', `Zapisana kopia grafu · ${shown.nodes.length} widocznych obiektów · ${graph.partial ? 'fragment większego zbioru' : 'zapisany fragment eksploracji'}. Węzły i relacje pozostają w stanie z chwili zapisu; linie nie oznaczają związku przyczynowego. ${limitMessage(graph)}`, 'muted'));
    const canvas = U.el('div', null, 'analysis-graph-snapshot-canvas'); canvas.setAttribute('aria-label', 'Zapisany graf powiązań'); host.append(canvas);
    const inspection = U.el('section', null, 'analysis-graph-inspector'); inspection.setAttribute('aria-label', 'Szczegóły zapisanego węzła lub relacji'); host.append(inspection);
    const labels = new Map((graph.nodes || []).map(node => [node.ref, node.label || node.ref]));
    function nodeFacts(node) {
      inspection.replaceChildren(U.el('h3', node.label || node.ref));
      const facts = U.el('dl'), entries = [['Identyfikator',node.ref],['Typ',U.typeNames[node.type] || node.type],['Dostępność przy zapisie',node.available === false ? 'Niedostępny w katalogu' : 'Dostępny'],['Kontekst metadanych',node.metadata_context === 'selected_document_version' ? 'Wybrana wersja dokumentu' : 'Bieżący katalog przy zapisie']];
      const sample = node.measurement;
      if (sample) entries.push(['Zachowany odczyt',`${U.metricNames[sample.metric] || sample.metric || 'Pomiar'}${sample.sensor_id ? ` · stanowisko ${sample.sensor_id}` : ''}: ${U.value(sample)}`], ['Czas obserwacji',formatGraphTime(sample.observed_at,timezone)],['Pobrano',formatGraphTime(sample.fetched_at,timezone)]);
      if (node.official_index) entries.push(['Oficjalny indeks GIOŚ',node.official_index.name || 'Brak nazwy'],['Czas indeksu',formatGraphTime(node.official_index.observed_at,timezone)]);
      if (node.position) entries.push(['Czas raportu pozycji',formatGraphTime(node.position.position_at,timezone)],['Pozycja',`${node.position.latitude}, ${node.position.longitude}`],['Prędkość',Number.isFinite(node.position.speed_kmh) ? `${node.position.speed_kmh} km/h` : 'Brak danych']);
      if (node.state || node.alert_state) entries.push(['Stan alarmu',({red:'Alarm czerwony',yellow:'Alarm żółty',none:'Brak alarmu w zapisanej obserwacji',unknown:'Stan nieznany'})[node.state || node.alert_state] || node.state || node.alert_state]);
      for (const [label, value] of entries) facts.append(U.el('dt',label),U.el('dd',value)); inspection.append(facts);
      if (node.communication) inspection.append(U.el('p',node.communication.text || 'Brak zapisanej treści','analysis-note-text'));
      const link=U.safeLink(node.provenance?.source_url || node.communication?.original_url); if(link) inspection.append(link);
    }
    function edgeFacts(edge) {inspection.replaceChildren(U.el('h3',edge.label || edge.type),U.el('p',`${labels.get(edge.source_ref)} ${edge.directed === false ? '↔' : '→'} ${labels.get(edge.target_ref)} · ${categoryNames[edge.category] || edge.category}`)); renderEdgeFacts(inspection,edge,U,timezone);}
    let cy;
    if (root.cytoscape) {
      const el = elements(shown, positions, []), preset = shown.nodes.every(node => positions[node.ref]);
      cy = root.cytoscape({container: canvas, elements: el, style: styles(document.documentElement.dataset.theme === 'dark'), layout: {name: preset ? 'preset' : 'breadthfirst', animate: false}, userPanningEnabled: true, userZoomingEnabled: true, autoungrabify: true});
      cy.on('tap','node',event=>{const node=graph.nodes.find(node=>node.ref===event.target.id());if(node)nodeFacts(node);}); cy.on('tap','edge',event=>{const edge=graph.edges.find(edge=>edge.id===event.target.id());if(edge)edgeFacts(edge);});
      requestAnimationFrame(() => {if (canvas.isConnected) {cy.resize(); cy.fit(undefined, 35);}});
    } else canvas.append(U.el('p', 'Graf jest dostępny w czytelnej liście poniżej.'));
    const list = U.el('details'); list.open = true; list.append(U.el('summary', `Węzły i relacje · ${shown.nodes.length} / ${shown.edges.length}`));
    for (const node of shown.nodes) {const entry = U.el('details', null, 'analysis-graph-edge-copy'); entry.append(U.el('summary',`${node.label || node.ref} · ${U.typeNames[node.type] || node.type} · ${node.ref}`),U.button('Pokaż zachowane dane obiektu',()=>nodeFacts(node))); list.append(entry);}
    for (const edge of shown.edges) {const entry = U.el('details', null, 'analysis-graph-edge-copy'); entry.append(U.el('summary',`${labels.get(edge.source_ref) || edge.source_ref} ${edge.directed === false ? '↔' : '→'} ${labels.get(edge.target_ref) || edge.target_ref} · ${edge.label || edge.type} · ${categoryNames[edge.category] || edge.category}`)); renderEdgeFacts(entry,edge,U,timezone); list.append(entry);}
    host.append(list); if(shown.nodes.length)nodeFacts(shown.nodes[0]); return {destroy: () => cy?.destroy()};
  }
  root.WiciWorkspaceGraph = function (host, {request, getContext, select, changed, notify = () => {}}) {
    const U = root.WiciWorkspaceUI, heading = U.el('div', null, 'analysis-graph-heading'), title = U.el('h2', 'Graf powiązań'); title.tabIndex = -1; title.id = 'analysis-graph-title';
    const status = U.el('p', '', 'analysis-graph-status'); status.id = 'analysis-graph-status'; status.setAttribute('role', 'status');
    const refresh = U.button('Odśwież graf', () => refreshGraph(true)); refresh.id = 'analysis-graph-refresh';
    const fit = U.button('Dopasuj graf', () => {canvas.scrollIntoView?.({block: 'center', inline: 'nearest'}); cy?.resize(); cy?.fit(undefined, 35);}); fit.id = 'analysis-graph-fit'; heading.append(fit);
    const clear = U.button('Wyczyść graf', () => {reset(); render(); changed?.();}); clear.id = 'analysis-graph-clear'; heading.append(title, refresh, clear);
    const searchBox = U.el('div', null, 'analysis-graph-search'), search = U.el('input'); search.id = 'analysis-graph-search'; search.type = 'search'; search.maxLength = 200; search.placeholder = 'Dodaj obiekt z katalogu…'; search.setAttribute('aria-label', 'Szukaj obiektu do grafu');
    const results = U.el('div', null, 'analysis-graph-search-results'); results.id = 'analysis-graph-search-results'; searchBox.append(U.field('Dodaj obiekt', search), results);
    const tools = U.el('div', null, 'analysis-graph-tools'), categories = U.el('select'); categories.id = 'analysis-graph-category'; categories.setAttribute('aria-label', 'Pochodzenie relacji');
    for (const [value, text] of [['', 'Wszystkie podstawy'], ...Object.entries(categoryNames)]) {const option = U.el('option', text); option.value = value; categories.append(option);}
    const relationType = U.el('select'); relationType.id = 'analysis-graph-relation-type'; relationType.setAttribute('aria-label', 'Rodzaj relacji');
    const nodeType = U.el('select'); nodeType.id = 'analysis-graph-node-type'; nodeType.setAttribute('aria-label', 'Widoczne typy obiektów'); for (const [value, label] of [['', 'Wszystkie typy obiektów'], ...Object.entries(U.typeNames)]) {const option = U.el('option', label); option.value = value; nodeType.append(option);}
    const layout = U.el('select'); layout.id = 'analysis-graph-layout'; layout.setAttribute('aria-label', 'Układ grafu'); for (const [value, text] of [['breadthfirst', 'Hierarchiczny'], ['concentric', 'Wokół obiektu']]) {const option = U.el('option', text); option.value = value; layout.append(option);}
    const arrange = U.button('Ułóż ponownie', () => arrangeGraph(true)); arrange.id = 'analysis-graph-arrange'; const showHidden = U.button('Pokaż ukryte', () => {config.hidden_refs = []; render(); changed?.();}); showHidden.id = 'analysis-graph-show-hidden';
    tools.append(categories, relationType, nodeType, layout, arrange, showHidden);
    const legend = U.el('p', '━━ Źródłowa · ┄┄ Wyliczona · ··· Analityczna. Połączenie obiektów nie oznacza związku przyczynowego.', 'analysis-graph-legend');
    const canvas = U.el('div', null, 'analysis-graph-canvas'); canvas.id = 'analysis-graph-canvas'; canvas.setAttribute('aria-label', 'Interaktywny graf powiązań');
    const selection = U.el('div', null, 'analysis-graph-selection'), selectedName = U.el('strong', 'Wybierz węzeł'), expand = U.button('Rozwiń powiązania', () => expandSelected()); expand.id = 'analysis-graph-expand';
    const hide = U.button('Ukryj węzeł', () => {if (!selectedRef) return; config.hidden_refs = [...new Set([...config.hidden_refs, selectedRef])]; selectedRef = null; render(); changed?.();}); hide.id = 'analysis-graph-hide';
    selection.append(selectedName, expand, hide);
    const paths = U.el('div', null, 'analysis-graph-path'), pathFrom = U.el('select'), pathTo = U.el('select'); pathFrom.id = 'analysis-graph-path-from'; pathTo.id = 'analysis-graph-path-to'; pathFrom.setAttribute('aria-label', 'Początek ścieżki'); pathTo.setAttribute('aria-label', 'Koniec ścieżki');
    const findPath = U.button('Pokaż ścieżkę', () => {path = pathBetween(filteredData(), pathFrom.value, pathTo.value); renderCanvas(); pathStatus.textContent = path ? `Ścieżka powiązań w widocznym grafie · ${path.edges.length} relacji. Kierunki są pokazane na liniach.` : 'Brak ścieżki w aktualnie wczytanym, widocznym fragmencie grafu.';}); findPath.id = 'analysis-graph-find-path'; const pathStatus = U.el('p', '', 'muted'); pathStatus.id = 'analysis-graph-path-status'; paths.append(pathFrom, pathTo, findPath, pathStatus);
    const lists = U.el('details', null, 'analysis-graph-lists'); lists.open = true; lists.append(U.el('summary', 'Lista obiektów i relacji · obsługa klawiaturą')); const nodes = U.el('div', null, 'analysis-graph-nodes'), edges = U.el('div', null, 'analysis-graph-edges'); nodes.id = 'analysis-graph-nodes'; edges.id = 'analysis-graph-edges'; lists.append(nodes, edges);
    const inspector = U.el('section', null, 'analysis-graph-inspector'); inspector.id = 'analysis-graph-inspector'; inspector.setAttribute('aria-label', 'Szczegóły relacji');
    host.append(heading, status, searchBox, tools, legend, canvas, selection, paths, lists, inspector);
    let filteredSource = null, filteredCache = null, filteredKey = '', canvasWidth = 0;
    let data = null, config = blank(), selectedRef = null, busy = false, needsRefresh = false, error = null, active = false, run = 0, abort = null, searchRun = 0, searchTimer, timer, cy = null, path = null, styleKey = '', lastContext = '', lastListKey = '';
    const cursors = new Map();
    function blank() {return {node_type: null, graph: {seed_refs: [], node_refs: [], expanded_refs: [], relation_types: [], categories: [], time: {mode: 'live'}, cursor_at: null, version_ids: {}, dossier_id: null}, positions: {}, hidden_refs: [], layout: 'breadthfirst'};}
    function reset() {++run; abort?.abort(); clearTimeout(timer); timer = null; clearTimeout(searchTimer); ++searchRun; search.value = ''; results.replaceChildren(); config = blank(); selectedRef = null; busy = false; needsRefresh = false; error = null; data = null; cursors.clear(); cy?.destroy(); cy = null; lastListKey = ''; path = null; inspector.replaceChildren();}
    function contextual(selector) {const state = getContext().state; return {...selector, time: clone(state.query.time), cursor_at: state.cursorAt || null, display_timezone: state.displayTimezone || 'Europe/Warsaw'};}
    function filteredData() {const key = JSON.stringify([config.hidden_refs, nodeType.value]); if (data === filteredSource && key === filteredKey) return filteredCache; const graph = visibleData(data, config.hidden_refs), visible = new Set(graph.nodes.filter(node => !nodeType.value || node.type === nodeType.value).map(node => node.ref)); filteredSource = data; filteredKey = key; filteredCache = {...data, nodes: graph.nodes.filter(node => visible.has(node.ref)), edges: graph.edges.filter(edge => visible.has(edge.source_ref) && visible.has(edge.target_ref))}; return filteredCache;}
    function serializable() {if (cy) cy.nodes().forEach(node => {config.positions[node.id()] = {x: node.position('x'), y: node.position('y')};}); const value = {graph: clone(config.graph), positions: clone(config.positions), hidden_refs: [...config.hidden_refs], layout: config.layout, node_type: nodeType.value || null}; if (data) {value.graph = {...value.graph, ...clone(data.selector), expected_revision: data.revision, as_of: data.as_of};} return value;}
    function choose(ref, openCard = true) {selectedRef = ref; if (openCard) select(ref, config.graph.version_ids[ref] || null); renderSelection(); renderCanvas();}
    function renderSelection() {const node = data?.nodes?.find(node => node.ref === selectedRef), count = data?.neighbor_counts?.[selectedRef]; selectedName.textContent = node ? `${node.label} · ${count?.remaining ?? '?'} niewczytanych powiązań` : 'Wybierz węzeł'; expand.disabled = busy || !node || count?.remaining === 0; expand.textContent = cursors.has(selectedRef) ? 'Wczytaj kolejne powiązania' : 'Rozwiń powiązania'; hide.disabled = !node || busy;}
    function inspect(edge) {inspector.replaceChildren(U.el('h3', edge.label || edge.type)); const labels = new Map((data?.nodes || []).map(node => [node.ref, node.label || node.ref])); inspector.append(U.el('p', `${labels.get(edge.source_ref) || edge.source_ref} ${edge.directed === false ? '↔' : '→'} ${labels.get(edge.target_ref) || edge.target_ref}`), U.el('p', categoryNames[edge.category] || edge.category)); renderEdgeFacts(inspector,edge,U,getContext().state.displayTimezone || 'Europe/Warsaw'); inspector.tabIndex = -1; inspector.focus();}
    function renderLists() {const graph = filteredData(), key = JSON.stringify([graph.nodes.map(node => [node.ref, node.label, node.available]), graph.edges, nodeType.value, config.hidden_refs]); if (lastListKey === key) return; lastListKey = key; nodes.replaceChildren(); edges.replaceChildren();
      const oldFrom = pathFrom.value, oldTo = pathTo.value; pathFrom.replaceChildren(); pathTo.replaceChildren();
      for (const node of graph.nodes) {const row = U.el('div', null, 'analysis-graph-node'); row.dataset.graphRef = node.ref; const control = U.button(node.label || node.ref, () => choose(node.ref)); control.className = 'analysis-graph-select'; row.append(control, U.el('small', `${U.typeNames[node.type] || node.type} · ${node.ref}${node.available === false ? ' · obiekt niedostępny' : ''}${!getContext().state.query.types.includes(node.type) ? ' · poza filtrami katalogu' : ''}`)); nodes.append(row);
        for (const target of [pathFrom, pathTo]) {const option = U.el('option', node.label || node.ref); option.value = node.ref; target.append(option);}}
      pathFrom.value = graph.nodes.some(node => node.ref === oldFrom) ? oldFrom : graph.nodes[0]?.ref || ''; pathTo.value = graph.nodes.some(node => node.ref === oldTo) ? oldTo : graph.nodes.at(-1)?.ref || '';
      const labels = new Map(graph.nodes.map(node => [node.ref, node.label || node.ref])); for (const edge of graph.edges) {const control = U.button(`${labels.get(edge.source_ref)} — ${edge.label || edge.type} ${edge.directed === false ? '↔' : '→'} ${labels.get(edge.target_ref)}`, () => inspect(edge)); control.dataset.edgeId = edge.id; control.dataset.category = edge.category; edges.append(control);}
      if (!graph.nodes.length) nodes.append(U.el('p', config.graph.seed_refs.length ? 'Brak widocznych węzłów. Zmień filtr lub pokaż ukryte.' : 'Wybierz „Pokaż powiązania” w karcie lub dodaj obiekt przez wyszukiwarkę.', 'muted'));
    }
    function renderCanvas() {if (!root.cytoscape || !active || !host.isConnected) return;
      const currentStyles = styles(document.documentElement.dataset.theme === 'dark'), theme = JSON.stringify(currentStyles);
      if (!cy) {cy = root.cytoscape({container: canvas, elements: [], style: currentStyles, layout: {name: 'preset'}, wheelSensitivity: .25, boxSelectionEnabled: false}); cy.on('tap', 'node', event => choose(event.target.id())); cy.on('tap', 'edge', event => {const edge = data?.edges?.find(edge => edge.id === event.target.id()); if (edge) inspect(edge);}); cy.on('dragfree', 'node', event => {config.positions[event.target.id()] = {x: event.target.position('x'), y: event.target.position('y')}; changed?.();});}
      const existing = new Set(cy.nodes().map(node => node.id())), el = elements(filteredData(), config.positions, []), wanted = new Set(el.map(item => item.data.id));
      cy.batch(() => {cy.elements().filter(item => !wanted.has(item.id())).remove(); for (const item of el) {const old = cy.getElementById(item.data.id); if (old.length) old.data(item.data); else cy.add(item);} cy.elements().removeClass('graph-path'); cy.elements().unselect(); if (selectedRef) cy.getElementById(selectedRef).select(); for (const id of [...(path?.nodes || []), ...(path?.edges || [])]) cy.getElementById(id).addClass('graph-path');});
      if (theme !== styleKey) {cy.style(currentStyles); styleKey = theme;}
      const missing = cy.nodes().filter(node => !existing.has(node.id()) && !config.positions[node.id()]); if (missing.length) arrangeGraph(false); resizeGraph();
    }
    function resizeGraph() {if (!cy) return; const width = canvas.clientWidth; cy.resize(); if (width > 0 && (!canvasWidth || Math.abs(width - canvasWidth) > 20)) {host.scrollTop = 0; cy.fit(undefined, 35);} if (width > 0) canvasWidth = width;}
    function arrangeGraph(force) {if (!cy) return; const options = {name: layout.value || config.layout, animate: false, padding: 35, directed: true, circle: config.layout === 'concentric', fit: true};
      if (force || !Object.keys(config.positions).length) cy.layout(options).run(); else {const center = cy.getElementById(selectedRef || config.graph.seed_refs[0]), origin = center.length ? center.position() : {x: 100, y: 100}; const unknown = cy.nodes().filter(node => !config.positions[node.id()]); unknown.forEach((node, i) => node.position({x: origin.x + 150 * Math.cos(2 * Math.PI * i / Math.max(unknown.length, 1)), y: origin.y + 150 * Math.sin(2 * Math.PI * i / Math.max(unknown.length, 1))})); cy.fit(undefined, 35);}
      cy.nodes().forEach(node => {config.positions[node.id()] = {x: node.position('x'), y: node.position('y')};}); changed?.();
    }
    function render() {host.setAttribute('aria-busy', String(busy)); refresh.disabled = busy || !config.graph.seed_refs.length; fit.disabled = !data || busy; clear.disabled = busy || !config.graph.seed_refs.length; search.disabled = busy; categories.disabled = relationType.disabled = busy; showHidden.disabled = !config.hidden_refs.length || busy;
      status.dataset.error = String(Boolean(error)); status.textContent = error || (busy ? 'Wczytywanie spójnego grafu…' : needsRefresh ? 'Graf wymaga ponownego odczytu po przerwanym odświeżeniu.' : data ? `${filteredData().nodes.length} / ${data.nodes.length} węzłów · ${filteredData().edges.length} relacji · ${data.partial ? 'fragment większego zbioru' : 'widoczne powiązania'}. ${limitMessage(data) || 'Niewczytane relacje są dostępne po rozwinięciu węzła.'}` : 'Graf korzysta wyłącznie z lokalnego katalogu i historii.');
      categories.value = config.graph.categories?.[0] || ''; const selectedType = config.graph.relation_types?.[0] || ''; relationType.replaceChildren(); const all = U.el('option', 'Wszystkie rodzaje relacji'); all.value = ''; relationType.append(all); const types = new Map(Object.entries(relationLabels)); if (selectedType && !types.has(selectedType)) types.set(selectedType, selectedType); for (const [value, text] of types) {const option = U.el('option', text); option.value = value; relationType.append(option);} relationType.value = selectedType; layout.value = config.layout;
      renderSelection(); renderLists(); renderCanvas();
    }
    async function query(selector = config.graph, keepExpected = false) {if (!selector.seed_refs.length) return; abort?.abort(); abort = new AbortController(); const signal = abort.signal, generation = ++run; busy = true; needsRefresh = true; error = null; render(); changed?.();
      const body = clone(selector); if (!keepExpected) {delete body.expected_revision; delete body.as_of;}
      try {const result = await request('/workspace/graph/query', body, {signal}); if (generation !== run) return; data = result; config.graph = {...clone(result.selector || body), expected_revision: result.revision, as_of: result.as_of}; busy = false; needsRefresh = false; error = null; path = null; lastListKey = ''; render(); changed?.();}
      catch (err) {if (err.name === 'AbortError' || generation !== run) return; busy = false; error = err.status === 409 ? 'Graf zmienił się. Użyj „Odśwież graf”; układ i wybór obiektów pozostają zachowane.' : `Nie udało się odczytać grafu: ${err.message}`; render(); changed?.();}
    }
    async function refreshGraph(fresh = false) {
      if (!config.graph.seed_refs.length) return;
      // Remember invalidation even while hidden; retained data only preserves the layout.
      needsRefresh = true; cursors.clear();
      if (!active) {render(); changed?.(); return;}
      return query(contextual(config.graph), !fresh);
    }
    async function expandSelected() {if (busy || !selectedRef) return; const ref = selectedRef, generation = ++run; abort?.abort(); abort = new AbortController(); busy = true; error = null; render();
      try {const result = await request('/workspace/graph/neighbors', {graph: serializable().graph, ref, cursor: cursors.get(ref) || null, limit: 50}, {signal: abort.signal}); if (generation !== run) return;
        const refs = [...new Set([...config.graph.node_refs, ...result.items.map(item => item.node.ref)])]; if (refs.length > 200) {busy = false; error = 'Limit 200 węzłów. Ukrycie nie usuwa obiektu z grafu; rozpocznij mniejszą eksplorację.'; render(); return;}
        if (result.next_cursor) cursors.set(ref, result.next_cursor); else cursors.delete(ref); config.graph.node_refs = refs; config.graph.expanded_refs = [...new Set([...config.graph.expanded_refs, ref])]; busy = false; return query(config.graph, true);
      } catch (err) {if (err.name === 'AbortError' || generation !== run) return; busy = false; error = err.status === 409 ? 'Powiązania zmieniły się. Odśwież graf przed rozwinięciem.' : `Nie udało się rozwinąć powiązań: ${err.message}`; render();}
    }
    function scheduleContext() {const state = getContext().state, key = JSON.stringify([state.query.time, state.cursorAt, state.displayTimezone]); if (key === lastContext) return;
      if (!config.graph.seed_refs.length) return; lastContext = key;
      const changedTime = JSON.stringify([config.graph.time, config.graph.cursor_at]) !== JSON.stringify([state.query.time, state.cursorAt || null]);
      if (changedTime || (config.graph.display_timezone || 'Europe/Warsaw') !== (state.displayTimezone || 'Europe/Warsaw')) {abort?.abort(); ++run; busy = active; needsRefresh = true; render(); changed?.(); if (active && timer == null) timer = setTimeout(() => {timer = null; refreshGraph(true);}, 140);}}
    async function addSeed(ref) {if (config.graph.seed_refs.includes(ref)) {choose(ref); return;} if (config.graph.seed_refs.length >= 20) {notify('Graf może rozpoczynać się od najwyżej 20 obiektów.'); return;} config.graph.seed_refs.push(ref); config.graph.node_refs = [...new Set([...config.graph.node_refs, ref])]; selectedRef = ref; cursors.clear(); results.replaceChildren(); search.value = ''; await query(config.graph, false); if (!busy && !error && data?.nodes?.some(node => node.ref === ref)) choose(ref);}
    search.addEventListener('input', () => {clearTimeout(searchTimer); const q = search.value.trim(), generation = ++searchRun; results.replaceChildren(); if (!q) return; searchTimer = setTimeout(async () => {try {const found = await request('/workspace/query', {types: root.WiciWorkspaceStore.TYPES, q, page_size: 20, time: {mode: 'live'}}); if (generation !== searchRun) return; for (const node of found.items || []) {const button = U.button(`${node.label} · ${U.typeNames[node.type]}`, () => addSeed(node.ref)); button.dataset.graphSearchRef = node.ref; results.append(button);} if (!found.items?.length) results.append(U.el('p', 'Brak obiektów w lokalnym katalogu.'));} catch (err) {if (generation === searchRun) results.append(U.el('p', err.message));}}, 250);});
    categories.addEventListener('change', () => {config.graph.categories = categories.value ? [categories.value] : []; cursors.clear(); query(config.graph, false);}); relationType.addEventListener('change', () => {config.graph.relation_types = relationType.value ? [relationType.value] : []; cursors.clear(); query(config.graph, false);}); nodeType.addEventListener('change', () => {lastListKey = ''; path = null; render(); changed?.();}); layout.addEventListener('change', () => {config.layout = layout.value;});
    const observer = typeof MutationObserver !== 'undefined' ? new MutationObserver(() => renderCanvas()) : null; observer?.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    render();
    return {async open({seed_refs = [], dossier_id = null, config: restored = null} = {}) {reset(); config = restored ? {graph: {...blank().graph, ...clone(restored.graph || {})}, positions: clone(restored.positions || {}), hidden_refs: [...(restored.hidden_refs || [])], layout: ['breadthfirst', 'concentric'].includes(restored.layout) ? restored.layout : 'breadthfirst', node_type: restored.node_type || null} : blank(); config.graph.seed_refs = restored ? config.graph.seed_refs : [...new Set(seed_refs)]; config.graph.node_refs = restored ? config.graph.node_refs || config.graph.seed_refs : [...config.graph.seed_refs]; config.graph.dossier_id = dossier_id; if (config.graph.seed_refs.length > 20) {config.graph.seed_refs = []; notify('Wybierz najwyżej 20 obiektów początkowych.'); render(); return;}
        const state = getContext().state; if (!restored && state.selectedVersion && config.graph.seed_refs.includes(state.selectedRef)) config.graph.version_ids[state.selectedRef] = Number(state.selectedVersion); nodeType.value = config.node_type || ''; config.graph = contextual(config.graph); selectedRef = config.graph.seed_refs[0] || null; active = true; host.scrollTop = 0; await query(config.graph, false); title.focus(); host.scrollIntoView?.({block: 'start', inline: 'nearest'});},
      setActive(value) {const wasActive = active; active = Boolean(value); if (active && !wasActive) host.scrollTop = 0; if (!active) {needsRefresh ||= busy || timer != null; abort?.abort(); ++run; clearTimeout(timer); timer = null; busy = false;} else {if (config.graph.seed_refs.length && !busy && (needsRefresh || !data)) refreshGraph(true); else render(); requestAnimationFrame(() => {cy?.resize();});}},
      sync(state) {const visible = filteredData().nodes; if (state.selectedRef && visible.some(node => node.ref === state.selectedRef)) selectedRef = state.selectedRef; else if (!visible.some(node => node.ref === selectedRef)) selectedRef = null; scheduleContext(); renderSelection(); renderCanvas();},
      refresh: () => refreshGraph(true), getConfig: serializable, getCapture: () => busy || needsRefresh || error || !data ? null : serializable(), getData: () => busy || needsRefresh || error ? null : data, getVisibleData: () => busy || needsRefresh || error ? {nodes: [], edges: []} : filteredData(), isLoading: () => busy,
      hasTemporalNodes: () => config.graph.node_refs.some(ref => /^(aircraft:|ship:|ua_region:|civil_alert:|hydro_station:|air_quality_station:)/.test(ref)),
      getVersion: ref => config.graph.version_ids?.[ref] || null,
      setVersion(ref, version) {if (!config.graph.node_refs.includes(ref)) return; if (version) config.graph.version_ids[ref] = Number(version); else delete config.graph.version_ids[ref]; refreshGraph(true);},
      setDossier(id) {if (config.graph.dossier_id === (id || null)) return; config.graph.dossier_id = id || null; refreshGraph(true);},
      destroy() {reset(); observer?.disconnect();}, resize: resizeGraph};
  };
  root.WiciWorkspaceGraph.createReadOnly = createReadOnly;
  const exported = {visibleData, pathBetween, transportStyle, symbol, renderEdgeFacts, limitMessage, formatGraphTime, styles}; root.WiciGraphHelpers = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(typeof window !== 'undefined' ? window : globalThis);
