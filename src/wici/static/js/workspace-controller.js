'use strict';
window.WiciWorkspace = (() => {
  const U = window.WiciWorkspaceUI, S = window.WiciWorkspaceStore;
  let initialized = false, active = false, visible = true, options, store, sourceManager, mapView, tableView, timelineView, cardView, views;
  let host, shell, toolbar, catalog, timelineHost, cardHost, search, province, message, status, split, sourceSelect, sourceCoverage;
  const columnControls = new Map();
  let data = null, detail = null, timeline = null, detailError = null, detailLoading = false;
  let queryAbort, detailAbort, queryRun = 0, detailRun = 0, pageCursor = null, searchTimer, refreshTimer, sourceRefreshTimer;
  let persistence = null, persistenceWarning = false;
  let trigger = null, wantsFocus = false, lastControlsQuery = null, lastLayout = null, sourceEnabled = true;
  const controls = new Map(), checkboxOptions = new Map(), localKey = 'wici.analysis.layout.v1';
  const health = () => typeof options.health === 'function' ? options.health() : options.health || {};
  const now = () => health().now || new Date().toISOString();
  const request = (...args) => options.api(...args);
  const dispatch = action => store.dispatch(action);
  function notify(text) {message.textContent = text || '';}
  function currentSample() {
    const state = store.getState(), object = detail?.object || detail;
    if (object?.ref !== state.selectedRef || detail?._detailRevision !== state.detailRevision || detail?._queryRevision !== state.queryRevision) return null;
    if (object.type === 'air_quality_station' && !state.selectedSensor) return null;
    if (!state.cursorAt) return detail.selected_measurement || object.measurement || null;
    if (timeline?.next_cursor || timeline?.official_indices_next_cursor) return null;
    const samples = (timeline?.ref === state.selectedRef ? timeline.items : detail?.measurements || []).filter(item => !item.kind || item.kind === 'measurement');
    if (object.type === 'air_quality_station' && !state.selectedSensor) return null;
    return S.sampleAt(samples, state.cursorAt, state.query.time.filter_range, state.selectedSensor,
      state.selectedMetric || (object?.type === 'hydro_station' ? 'water_level' : null));
  }
  function currentIndex() {
    const state = store.getState(), object = detail?.object;
    if (object?.ref !== state.selectedRef || object.type !== 'air_quality_station') return null;
    if (!state.cursorAt) return object.official_index || null;
    return S.sampleAt(timeline?.official_indices || (timeline?.items || []).filter(item => item.kind === 'official_index'), state.cursorAt, state.query.time.filter_range);
  }
  function positionCard() {
    const mapPanel = shell?.querySelector?.('.map-panel');
    if (mapPanel) {shell.style.setProperty('--analysis-card-top', `${mapPanel.offsetTop + 10}px`); shell.style.setProperty('--analysis-card-height', `${Math.max(260, mapPanel.offsetHeight - 20)}px`);}
  }
  function render() {
    if (!initialized) return;
    const state = store.getState(), sample = currentSample();
    shell.classList.toggle('analysis-card-open', active && state.detailOpen);
    shell.dataset.analysisPanel = state.layout.mobilePanel;
    shell.style.setProperty('--analysis-table-width', `${Math.max(25, Math.min(65, Number(state.layout.tablePercent) || 42))}%`);
    if (lastControlsQuery !== state.query) {
      lastControlsQuery = state.query;
      if (document.activeElement !== search && searchTimer == null) search.value = state.query.q;
      province.value = state.query.province || ''; sourceSelect.value = state.query.source_ids[0] || '';
      for (const [type, button] of controls) button.setAttribute('aria-pressed', String(state.query.types.includes(type)));
      for (const [name, checkbox] of checkboxOptions) checkbox.checked = name === 'include_without_samples' ? !state.query[name] : state.query[name];
    }
    if (lastLayout !== state.layout) {
      lastLayout = state.layout; split.value = state.layout.tablePercent;
      try {localStorage.setItem(localKey, JSON.stringify(state.layout));} catch { /* The workspace remains usable when browser storage is blocked. */ }
      options.map?.invalidateSize?.();
    }
    for (const [column, control] of columnControls) control.checked = state.columns.includes(column);
    tableView.render(data, state, sample); timelineView.render(data, state, {historyIncomplete: Boolean(timeline?.next_cursor || timeline?.official_indices_next_cursor), detailLoading}); mapView.render(data, state, sample, currentIndex());
    const mapItems = data?.map?.items || [...(data?.map?.points || []), ...(data?.map?.areas || [])];
    const inScope = detail?.in_scope ?? (!data || data.items.some(item => item.ref === state.selectedRef) || mapItems.some(item => item.ref === state.selectedRef));
    cardView.render(detail, timeline, state, sample, {inScope, loading: detailLoading, error: detailError, selectedIndex: currentIndex()});
    sourceCoverage.replaceChildren();
    for (const source of data?.coverage?.sources || []) sourceCoverage.append(U.el('p', `${source.resource}: ${U.statusNames[source.status] || source.status} · ${source.item_count || 0} rekordów · odczyt ${U.date(source.fetched_at)}${source.complete === false || source.complete === 0 ? ' · zakres niepełny' : ''}`, 'muted'));
    if (persistence) sourceCoverage.append(U.el('p', `Zapis historii: ${persistence.pending || 0} w kolejce · ${Object.keys(persistence.errors || {}).length} błędów · ${persistence.rejected_submissions || 0} pominiętych odczytów`, 'muted'));
    sourceCoverage.append(U.el('small', 'Historia pomiarów powstaje z odczytów na żądanie, przez 14 dni. Daty pierwszego i ostatniego pomiaru nie gwarantują ciągłego pokrycia.'));
    status.textContent = state.error ? `Odczyt nie powiódł się: ${state.error}. Ostatni zestaw pozostaje dostępny.` : state.loading ? 'Odświeżanie wspólnego zestawu…' : data ? `${data.total} obiektów · mapa: ${data.map?.located_total ?? 0} z geometrią, ${data.map?.unlocated_total ?? 0} bez geometrii · stan na ${U.date(data.as_of)}${data.map?.mode === 'aggregates' ? ' · agregaty: zawęź typ, region lub nazwę' : ''}` : 'Przygotowywanie katalogu…';
    positionCard();
  }
  function queryPayload(state, cursor) {return {...state.query, cursor, query_revision: state.queryRevision};}
  async function loadQuery(cursor = null, retries = 0) {
    if (!active || !visible || document.hidden) return;
    const state = store.getState(), revision = state.queryRevision, run = ++queryRun;
    queryAbort?.abort(); queryAbort = new AbortController(); dispatch({type: 'DATA_LOADING'});
    try {
      const result = await request('/workspace/query', queryPayload(state, cursor), {signal: queryAbort.signal});
      if (run !== queryRun || revision !== store.getState().queryRevision || !active) return;
      data = {...result, _pageCursor: cursor}; pageCursor = cursor;
      dispatch({type: 'DATA_READY', revision, dataRevision: result.data_revision, asOf: result.as_of});
      if (result.warnings?.length) notify(result.warnings.map(item => typeof item === 'string' ? item : item.message || item.code || JSON.stringify(item)).join(' · '));
      if (sourceEnabled && state.query.time.mode === 'live') sourceManager?.demandIndexes?.((result.items || []).filter(item => item.type === 'air_quality_station').map(item => item.native_id || item.source_object_id || item.ref.split(':').at(-1)));
      if (store.getState().detailOpen) loadDetail();
    } catch (error) {
      if (error.name === 'AbortError' || run !== queryRun) return;
      if (error.status === 409 && retries < 2) return loadQuery(null, retries + 1);
      dispatch({type: 'DATA_FAILED', revision, error: error.status === 409 ? 'Dane zmieniają się podczas odczytu. Użyj „Odśwież zestaw”.' : error.message});
    }
  }
  function contextParams(state) {
    const params = new URLSearchParams(); if (state.asOf) params.set('as_of', state.asOf); if (state.dataRevision != null) params.set('data_revision', state.dataRevision);
    const range = state.query.time.filter_range;
    if (range) {params.set('from', range.from); params.set('to', range.to);}
    if (state.selectedVersion) params.set('version_id', state.selectedVersion);
    if (state.selectedSensor) params.set('sensor_id', state.selectedSensor);
    if (state.selectedMetric) params.set('metric', state.selectedMetric);
    else if (state.selectedRef?.startsWith('hydro_station:')) params.set('metric', 'water_level');
    return params;
  }
  async function loadDetail(more = false) {
    const state = store.getState(); if (!active || !state.detailOpen || !state.selectedRef || !data) return;
    const generation = state.detailRevision, selectedRef = state.selectedRef, run = ++detailRun, params = contextParams(state);
    detailAbort?.abort(); detailAbort = new AbortController(); const signal = detailAbort.signal;
    if (more && timeline?.next_cursor) params.set('cursor', timeline.next_cursor);
    if (more && timeline?.official_indices_next_cursor) params.set('index_cursor', timeline.official_indices_next_cursor);
    detailLoading = true; detailError = null; render();
    const stillCurrent = () => active && run === detailRun && store.getState().detailOpen && store.getState().selectedRef === selectedRef && store.getState().detailRevision === generation;
    try {
      const path = `/workspace/objects/${encodeURIComponent(selectedRef)}`;
      const results = await Promise.all([request(`${path}?${params}`, null, {signal}), request(`${path}/timeline?${params}`, null, {signal})]);
      if (!stillCurrent()) return; detail = {...results[0], _detailRevision: generation, _queryRevision: state.queryRevision}; timeline = more && timeline ? {...results[1], items: timeline.next_cursor ? [...timeline.items, ...results[1].items] : timeline.items,
        official_indices: timeline.official_indices_next_cursor ? [...timeline.official_indices, ...results[1].official_indices] : timeline.official_indices,
        next_cursor: timeline.next_cursor ? results[1].next_cursor : null, official_indices_next_cursor: timeline.official_indices_next_cursor ? results[1].official_indices_next_cursor : null} : results[1]; detailLoading = false; render();
      if (wantsFocus) {wantsFocus = false; cardView.focus();}
    } catch (error) {
      if (error.name === 'AbortError' || !stillCurrent()) return; detailLoading = false;
      detailError = error.status === 409 ? 'Zestaw danych zmienił się. Odśwież zestaw, aby ponownie otworzyć spójne szczegóły.' : error.message; render();
    }
  }
  function selectObject(ref, origin, version = null) {
    trigger = origin || document.activeElement; wantsFocus = true;
    dispatch({type: 'SELECT_OBJECT', ref, version});
    if (sourceEnabled && store.getState().query.time.mode === 'live' && ref.startsWith('air_quality_station:')) sourceManager?.loadSensors?.(ref.split(':').at(-1)).catch(error => notify(error.message));
  }
  function closeCard() {
    wantsFocus = false; detailAbort?.abort(); ++detailRun; dispatch({type: 'CLOSE_CARD'});
    if (trigger?.isConnected && typeof trigger.focus === 'function') trigger.focus();
    else {const row = [...(shell.querySelectorAll?.('#analysis-table [data-ref]') || [])].find(item => item.dataset.ref === store.getState().selectedRef), control = row?.querySelector?.('.analysis-object-link'); if (control) control.focus(); else tableView.focusHeading();}
  }
  function setRegion(code) {if (!store || store.getState().query.province === (code || null)) return; dispatch({type: 'SET_REGION', province: code});}
  function chooseRegion(code) {window.WiciRegion?.select?.(code || '', {fit: false}); setRegion(code);}
  function sampleSelected(sample) {
    if (timeline?.next_cursor || timeline?.official_indices_next_cursor) {notify('Historia częściowa — wczytaj kolejne próbki przed ustawieniem kursora.'); return;}
    const time = sample.observed_at || sample.at; if (!time) return;
    const state = store.getState(); if (state.query.time.mode === 'live') {
      const end = new Date(now()).getTime(), from = new Date(Math.max(end - 14 * 86400000, Date.parse(time) - 3600000)).toISOString();
      dispatch({type: 'SET_TIME_RANGE', range: {from, to: new Date(Math.max(end, Date.parse(time) + 1)).toISOString()}});
    }
    dispatch({type: 'SET_CURSOR', at: time});
  }
  async function fetchSource(object) {
    if (!sourceManager) return;
    notify('Odczyt źródła… Wybrany przedział pozostaje bez zmian.');
    try {
      if (object.type === 'hydro_station') await sourceManager.request('/hydro?kind=stations');
      if (object.type === 'air_quality_station') {
        const stationId = object.native_id || object.source_object_id || object.ref.split(':').at(-1);
        const sensors = await sourceManager.loadSensors(stationId);
        const selected = store.getState().selectedSensor;
        if (selected) await sourceManager.loadSensor(selected);
        else if ((sensors.items || []).length) notify('Wybierz stanowisko pomiarowe, a następnie pobierz jego dostępne dane.');
        await sourceManager.request(`/gios?kind=index&id=${encodeURIComponent(stationId)}`);
      }
      dispatch({type: 'REFRESH'});
    } catch (error) {notify(`Nie udało się pobrać danych: ${error.message}`);}
  }
  function refreshSourceStatus() {
    return request('/workspace/status').then(result => {persistence = result.persistence || null; const incomplete = Boolean(persistence && (Number(persistence.rejected_submissions) > 0 || Object.keys(persistence.errors || {}).length));
      if (incomplete) notify('Zapis historii jest niepełny: kolejka odnotowała pominięte lub nieudane zapisy.');
      else if (persistenceWarning) notify('Zapis historii działa ponownie. Wcześniejsze luki nie są automatycznie uzupełniane.');
      persistenceWarning = incomplete; render();
    }).catch(() => {});
  }
  function sourceChanged(event) {
    if (!active || !visible || document.hidden) return;
    if (event.error) {if (event.error.name !== 'AbortError') notify(`Źródło chwilowo niedostępne: ${event.error.message}. Zapisane dane pozostają dostępne.`); return;}
    if (sourceRefreshTimer) return;
    sourceRefreshTimer = setTimeout(() => {sourceRefreshTimer = null; if (active) {dispatch({type: 'REFRESH'}); refreshSourceStatus();}}, 1000);
  }
  function syncSensor() {
    const state = store.getState();
    sourceManager?.demandSensor?.(active && sourceEnabled && state.detailOpen && state.query.time.mode === 'live' && state.selectedRef?.startsWith('air_quality_station:') ? state.selectedSensor : null);
  }
  function syncSources() {
    sourceManager?.setTypes?.(active && sourceEnabled ? store.getState().query.types : [], {live: store.getState().query.time.mode === 'live'});
    sourceManager?.setVisible?.(active && visible && !document.hidden); syncSensor();
  }
  function createToolbar() {
    const top = U.el('div', null, 'analysis-toolbar-heading'); top.append(U.el('strong', 'Stanowisko analityczne'), U.el('span', 'Katalog · mapa · czas', 'muted'));
    const refresh = U.button('Odśwież zestaw', () => dispatch({type: 'REFRESH'})); refresh.id = 'analysis-refresh'; top.append(refresh);
    const panels = U.el('div', null, 'analysis-mobile-switch');
    for (const [id, name] of [['table', 'Tabela'], ['map', 'Mapa']]) {const button = U.button(name, () => dispatch({type: 'SET_LAYOUT', patch: {mobilePanel: id}})); button.dataset.panel = id; panels.append(button);} top.append(panels);
    const fields = U.el('div', null, 'analysis-query-fields'); search = U.el('input'); search.type = 'search'; search.maxLength = 200; search.id = 'analysis-search'; search.placeholder = 'Nazwa, tytuł lub identyfikator…';
    search.addEventListener('input', () => {
      clearTimeout(searchTimer); const value = search.value;
      searchTimer = setTimeout(() => {searchTimer = null; dispatch({type: 'SET_QUERY', patch: {q: value}});}, 250);
    });
    province = U.el('select'); province.id = 'analysis-province'; const all = U.el('option', 'Cała Polska'); all.value = ''; province.append(all);
    const regions = [...(options.geometries || new Map())].filter(([key]) => /^\d{2}$/.test(key)).sort((a, b) => a[1].properties.name.localeCompare(b[1].properties.name, 'pl'));
    for (const [code, feature] of regions) {const option = U.el('option', feature.properties.name); option.value = code; province.append(option);}
    province.addEventListener('change', () => chooseRegion(province.value)); fields.append(U.field('Szukaj w katalogu', search), U.field('Obszar danych', province));
    const types = U.el('div', null, 'analysis-type-filters'); types.setAttribute('role', 'group'); types.setAttribute('aria-label', 'Typy obiektów');
    for (const type of S.TYPES) {const button = U.button(U.typeNames[type], () => {
      const current = store.getState().query.types, next = current.includes(type) ? current.filter(item => item !== type) : [...current, type];
      if (!next.length) {notify('Wybierz co najmniej jeden typ obiektu.'); return;} sourceEnabled = true; dispatch({type: 'SET_QUERY', patch: {types: next}});
    }); button.dataset.objectType = type; button.setAttribute('aria-pressed', 'false'); controls.set(type, button); types.append(button);}
    sourceSelect = U.el('select'); sourceSelect.id = 'analysis-source';
    for (const [id, name] of [['', 'Wszystkie źródła'], ['imgw_meteo', 'Ostrzeżenia IMGW'], ['rso', 'RSO'], ['rcb', 'RCB'], ['sg', 'Straż Graniczna'], ['imgw', 'Wodowskazy IMGW'], ['gios', 'GIOŚ'], ['prg', 'PRG']]) {const option = U.el('option', name); option.value = id; sourceSelect.append(option);}
    sourceSelect.addEventListener('change', () => dispatch({type: 'SET_QUERY', patch: {source_ids: sourceSelect.value ? [sourceSelect.value] : []}})); fields.append(U.field('Źródło', sourceSelect));
    const advanced = U.el('details', null, 'analysis-query-options'); advanced.append(U.el('summary', 'Zakres i układ'));
    const advancedBody = U.el('div', null, 'analysis-option-fields');
    for (const [key, label] of [['include_periods', 'Także okresy ważności i udostępniania'], ['include_unlocated', 'Uwzględnij obiekty bez geometrii'], ['include_without_samples', 'Tylko stacje z pomiarami w przedziale']]) {
      const checkbox = U.el('input'); checkbox.type = 'checkbox'; checkbox.id = `analysis-${key}`;
      checkbox.addEventListener('change', () => dispatch({type: 'SET_QUERY', patch: {[key]: key === 'include_without_samples' ? !checkbox.checked : checkbox.checked}}));
      const labelNode = U.field(label, checkbox); labelNode.className = 'analysis-checkbox'; advancedBody.append(labelNode); checkboxOptions.set(key, checkbox);
    }
    for (const [column, label] of [['type', 'Kolumna: typ'], ['updated_at', 'Kolumna: czas'], ['measurement', 'Kolumna: wartość']]) {const control = U.el('input'); control.type = 'checkbox'; control.checked = true; control.addEventListener('change', () => {const columns = store.getState().columns.filter(item => item !== column); if (control.checked) columns.push(column); dispatch({type: 'SET_COLUMNS', columns});}); columnControls.set(column, control); const node = U.field(label, control); node.className = 'analysis-checkbox'; advancedBody.append(node);}
    split = U.el('input'); split.type = 'range'; split.min = '25'; split.max = '65'; split.step = '1'; split.id = 'analysis-table-size';
    split.addEventListener('input', () => dispatch({type: 'SET_LAYOUT', patch: {tablePercent: Number(split.value)}})); advancedBody.append(U.field('Szerokość tabeli względem mapy', split)); advanced.append(advancedBody);
    message = U.el('p', '', 'analysis-message'); message.id = 'analysis-message'; message.setAttribute('role', 'status');
    status = U.el('p', '', 'analysis-query-status'); status.id = 'analysis-status'; status.setAttribute('role', 'status');
    const coverage = U.el('details', null, 'analysis-source-coverage'); coverage.append(U.el('summary', 'Pokrycie i aktualność źródeł')); sourceCoverage = U.el('div'); coverage.append(sourceCoverage);
    toolbar.append(top, fields, types, advanced, status, message, coverage);
    views = window.WiciWorkspaceViews(toolbar, {request, status: notify, getConfig() {
      const state = store.getState(), center = options.map?.getCenter?.();
      return {query: structuredClone(state.query), layout: {...state.layout}, columns: [...state.columns], selectedRef: state.selectedRef,
        camera: center ? {lat: center.lat, lng: center.lng, zoom: options.map.getZoom()} : null};
    }, apply(config, id) {
      sourceEnabled = false; sourceManager?.deactivate?.();
      if (config.relative_seconds && config.query?.time?.mode === 'range') {const end = new Date(now()).getTime(); const range = {from: new Date(end - config.relative_seconds * 1000).toISOString(), to: new Date(end).toISOString()}; config.query.time = {mode: 'range', overview_range: range, filter_range: range};}
      wantsFocus = false; dispatch({type: 'APPLY_VIEW', config, id}); window.WiciRegion?.select?.(config.query?.province || '', {fit: false});
      if (config.camera && options.map) options.map.setView([config.camera.lat, config.camera.lng], config.camera.zoom, {animate: false});
    }, saved: id => dispatch({type: 'VIEW_SAVED', id})});
  }
  function init(settings) {
    if (initialized) return; options = settings; host = document.getElementById('analysis-workspace'); if (!host) return;
    shell = host.closest('.workspace'); store = S.createStore(); sourceManager = settings.sources || window.WiciWorkspaceSources;
    try {const saved = JSON.parse(localStorage.getItem(localKey)); if (saved && typeof saved === 'object') store.dispatch({type: 'SET_LAYOUT', patch: {tablePercent: Math.max(25, Math.min(65, Number(saved.tablePercent) || 42)), mobilePanel: saved.mobilePanel === 'map' ? 'map' : 'table'}});} catch { /* Default layout is sufficient. */ }
    toolbar = U.el('section', null, 'analysis-toolbar'); catalog = U.el('section', null, 'analysis-catalog'); timelineHost = U.el('section', null, 'analysis-timeline'); cardHost = U.el('aside', null, 'analysis-card');
    cardHost.id = 'analysis-card'; cardHost.hidden = true; host.append(toolbar, catalog, timelineHost, cardHost); createToolbar();
    tableView = window.WiciWorkspaceTable(catalog, {select: selectObject, sort(field) {const current = store.getState().query.sort; dispatch({type: 'SET_QUERY', patch: {sort: {field, direction: current.field === field && current.direction === 'asc' ? 'desc' : 'asc'}}});}, next: () => loadQuery(data?.next_cursor), first: () => loadQuery(null)});
    timelineView = window.WiciWorkspaceTimeline.create(timelineHost, {dispatch, getState: store.getState, now});
    mapView = window.WiciWorkspaceMap({map: settings.map, geometries: settings.geometries, select: selectObject, narrow(aggregate) {chooseRegion(aggregate.province); dispatch({type: 'SET_QUERY', patch: {types: [aggregate.type]}}); mapView.show({areas: [{admin_code: aggregate.province}]});}});
    cardView = window.WiciObjectCard(cardHost, {close: closeCard, show(object) {dispatch({type: 'SET_LAYOUT', patch: {mobilePanel: 'map'}}); if (!mapView.show(object)) notify('Ten obiekt nie ma geometrii do pokazania.');}, version: version => selectObject(store.getState().selectedRef, document.activeElement, version), region(code) {chooseRegion(code); dispatch({type: 'SET_QUERY', patch: {types: ['communication']}});}, sensor(sensor, metric) {dispatch({type: 'SELECT_SENSOR', sensor, metric}); if (store.getState().query.time.mode === 'live' && sensor) sourceManager?.loadSensor?.(sensor).catch(error => notify(error.message));}, fetchSource, sample: sampleSelected, moreHistory: () => loadDetail(true)});
    store.subscribe((state, previous, action) => {
      if (action.type === 'APPLY_VIEW') {clearTimeout(searchTimer); searchTimer = null;}
      if (state.queryRevision !== previous.queryRevision) {pageCursor = null; detailAbort?.abort(); ++detailRun; if (action.type !== 'REFRESH') syncSources(); loadQuery();}
      else if (state.detailRevision !== previous.detailRevision) {syncSensor(); detailAbort?.abort(); ++detailRun; if (state.detailOpen) loadDetail();}
      render();
    });
    sourceManager?.subscribe?.(sourceChanged);
    window.addEventListener?.('resize', positionCard);
    document.addEventListener('keydown', event => {if (active && event.key === 'Escape' && store.getState().detailOpen) {event.preventDefault(); closeCard();}});
    document.addEventListener('visibilitychange', () => {syncSources(); if (!document.hidden && active && visible) loadQuery(pageCursor);});
    for (const disclosure of toolbar.querySelectorAll?.('details') || []) disclosure.addEventListener('toggle', positionCard);
    initialized = true; render(); host.hidden = true;
  }
  function setActive(value) {
    if (!initialized || active === Boolean(value)) return; active = Boolean(value); host.hidden = !active; shell.classList.toggle('analysis-active', active); mapView.setActive(active); syncSources();
    clearInterval(refreshTimer); refreshTimer = null;
    if (active) {setRegion(window.WiciRegion?.code ? window.WiciRegion.code() : store.getState().query.province); loadQuery(); views.load(); refreshSourceStatus(); refreshTimer = setInterval(() => {if (store.getState().query.time.mode === 'live' && visible && !document.hidden) loadQuery(pageCursor);}, 60000);}
    else {queryAbort?.abort(); detailAbort?.abort(); ++queryRun; ++detailRun; shell.classList.remove('analysis-card-open');}
    options.map?.invalidateSize?.(); options.onModeChange?.(active);
  }
  function setVisible(value) {if (visible === Boolean(value)) return; visible = Boolean(value); syncSources(); if (visible && active) loadQuery(pageCursor);}
  return {init, setActive, setVisible, setRegion, refresh: () => initialized && dispatch({type: 'REFRESH'}), selectObject,
    isActive: () => active, getState: () => store?.getState(), getData: () => data};
})();
