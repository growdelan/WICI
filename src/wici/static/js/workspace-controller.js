'use strict';
window.WiciWorkspace = (() => {
  const U = window.WiciWorkspaceUI, S = window.WiciWorkspaceStore, M = window.WiciWorkspaceMotion, A = window.WiciWorkspaceAlerts;
  let initialized = false, active = false, visible = true, options, store, sourceManager, mapView, tableView, timelineView, cardView, views, motionView, alertsView;
  let host, shell, toolbar, catalog, timelineHost, cardHost, search, province, message, status, split, sourceSelect, sourceCoverage, persistenceNotice, country, oblast, raion, provinceField, oblastField, raionField, recordingControl, recordingStatus, regionHint;
  const columnControls = new Map();
  let data = null, detail = null, timeline = null, detailError = null, detailLoading = false;
  let queryAbort, detailAbort, queryRun = 0, detailRun = 0, pageCursor = null, searchTimer, refreshTimer, sourceRefreshTimer;
  let persistence = null, movingPersistence = null, persistenceWarning = false;
  let trigger = null, wantsFocus = false, lastControlsQuery = null, lastLayout = null, sourceEnabled = true;
  let replayData = null, replayLoading = false, replayError = null, replayAbort, replayRun = 0, replayKey = '';
  let watchedItems = [], watchedRefs = null, watchlistHost, watchlistSummary, watchlistKey = '', watchlistRun = 0;
  let regions = [], regionOptionsKey = '', recording = null, recordingBusy = false, recordingRun = 0, regionsRun = 0, transportLegend;
  let alertReplay = null, alertLoading = false, alertError = null, alertAbort, alertRun = 0, alertKey = '';
  const movingBusy = new Set();
  const controls = new Map(), checkboxOptions = new Map(), localKey = 'wici.analysis.layout.v1';
  let messageKind = 'general';
  const health = () => typeof options.health === 'function' ? options.health() : options.health || {};
  const now = () => health().now || new Date().toISOString();
  const request = (...args) => options.api(...args);
  const dispatch = action => store.dispatch(action);
  function notify(text, kind = 'general') {messageKind = kind; message.textContent = text || '';}
  function motionContext() {
    const state = store.getState(), labels = new Map([...watchedItems, ...(data?.items || [])].map(item => [item.ref, item.label]));
    if (detail?.object) labels.set(detail.object.ref, detail.object.label);
    const frames = new Map();
    if (state.query.time.mode === 'range') for (const [index, ref] of state.comparedRefs.entries()) {
      const series = replayData?.series?.find(item => item.ref === ref), frame = replayLoading ? {status: 'loading', point: null} : replayError ? {status: 'error', point: null} : M?.frameAt(series, state.cursorAt, state.query.time.filter_range) || {status: 'empty', point: null};
      frames.set(ref, {...frame, label: series?.label || labels.get(ref) || ref, color: M?.colors[index]});
    }
    return {data: replayData, loading: replayLoading, error: replayError, frames, labels, watched: watchedRefs, busy: movingBusy};
  }
  function alertContext() {
    const state = store.getState(), labels = new Map([...regions, ...watchedItems, ...(data?.items || [])].map(item => [item.ref, item.label])), frames = new Map();
    if (detail?.object) labels.set(detail.object.ref, detail.object.label);
    if (state.query.time.mode === 'range') for (const ref of state.comparedRegionRefs || []) {
      const series = alertReplay?.series?.find(item => item.ref === ref), frame = !alertLoading && !alertError ? A?.frameAt(series, state.cursorAt, state.query.time.filter_range) : null;
      frames.set(ref, {...frame, state: frame?.state || 'unknown', label: series?.label || labels.get(ref) || ref});
    }
    return {refs: state.comparedRegionRefs || [], data: alertReplay, loading: alertLoading, error: alertError, frames, labels, regions, watched: watchedRefs, busy: movingBusy};
  }
  function syncMapScope() {
    const state = store.getState(), outside = active && (state.query.country === 'UA' || state.query.types.some(type => ['ua_region', 'civil_alert'].includes(type)) || state.comparedRegionRefs?.length);
    window.WiciRegion?.setAnalysisOutsidePoland?.(Boolean(outside));
  }
  function renderRegions() {
    if (!country) return;
    const state = store.getState(), query = state.query, selected = regions.find(item => item.ref === query.region_ref), isUA = query.country === 'UA' || query.types.some(type => ['ua_region', 'civil_alert'].includes(type));
    country.value = query.country || ''; provinceField.hidden = isUA; oblastField.hidden = raionField.hidden = regionHint.hidden = !isUA;
    const oblastKey = selected?.scope === 'oblast' ? selected.native_key : selected?.oblast;
    const selectedOblast = regions.find(item => item.scope === 'oblast' && (item.native_key === oblastKey || item.ref === selected?.parent_ref));
    const key = JSON.stringify([regions.map(item => [item.ref, item.label, item.scope, item.oblast]), query.region_ref]);
    if (key !== regionOptionsKey) {
      regionOptionsKey = key; oblast.replaceChildren(); raion.replaceChildren();
      const empty = U.el('option', 'Wszystkie obwody'); empty.value = ''; oblast.append(empty);
      for (const item of regions.filter(item => item.scope === 'oblast')) {const option = U.el('option', item.label); option.value = item.ref; oblast.append(option);}
      oblast.value = selectedOblast?.ref || (selected?.scope === 'oblast' ? selected.ref : '');
      const all = U.el('option', oblast.value ? 'Wszystkie rejony obwodu' : 'Wszystkie rejony'); all.value = ''; raion.append(all);
      for (const item of regions.filter(item => item.scope === 'raion' && (!oblast.value || item.oblast === selectedOblast?.native_key || item.parent_ref === oblast.value))) {const option = U.el('option', item.label); option.value = item.ref; raion.append(option);}
      raion.value = selected?.scope === 'raion' ? selected.ref : ''; raion.disabled = !regions.some(item => item.scope === 'raion');
    }
    recordingControl.checked = Boolean(recording?.enabled); recordingControl.disabled = recordingBusy || !recording || recording.available === false;
    const issue = recording?.last_error || recording?.error;
    recordingStatus.textContent = recordingBusy ? 'Zmiana rejestracji…' : !recording ? 'Odczyt stanu rejestracji…' : recording.available === false ? 'Rejestracja wymaga włączonego źródła Ukrainy w trybie LIVE.' : `${recording.enabled ? 'Rejestracja włączona. Działa po zamknięciu zakładki, dopóki działa WICI.' : 'Rejestracja wyłączona. Włącz ją, aby budować historię kolejnych odczytów.'} Ostatni udany odczyt: ${U.date(recording.last_success_at || recording.last_success)}${issue ? ` · problem: ${issue}` : ''}`;
  }
  async function loadRegions() {
    if (!A) return; const run = ++regionsRun;
    try {const result = await request('/workspace/ukraine/regions'); if (run !== regionsRun) return; regions = result.items || []; regionOptionsKey = ''; render();} catch (error) {notify(`Nie udało się odczytać regionów Ukrainy: ${error.message}`);}
  }
  async function loadRecording() {
    if (!A || recordingBusy) return; const run = ++recordingRun;
    try {const result = await request('/workspace/ukraine/recording'); if (run !== recordingRun) return; recording = result; render();} catch (error) {if (run !== recordingRun) return; recordingStatus.textContent = `Nie udało się odczytać stanu rejestracji: ${error.message}`;}
  }
  async function changeRecording(enabled) {
    if (recordingBusy) return; ++recordingRun; recordingBusy = true; render();
    try {recording = await request('/workspace/ukraine/recording', {enabled}, {method: 'PUT'}); notify(enabled ? 'Rejestracja historii alarmów włączona. Wcześniejsze okresy pozostają bez obserwacji.' : 'Rejestracja historii alarmów wyłączona. Zapisane okresy pozostają dostępne.'); dispatch({type: 'REFRESH'});}
    catch (error) {notify(`Nie udało się zmienić rejestracji: ${error.message}`);} finally {recordingBusy = false; render();}
  }
  async function loadAlertReplay(force = false) {
    const state = store.getState(), range = state.query.time.filter_range, refs = state.comparedRegionRefs || [], key = JSON.stringify([refs, range]);
    if (!force && key === alertKey) return;
    alertKey = key; alertAbort?.abort(); const run = ++alertRun; alertReplay = null; alertError = null; alertLoading = false;
    if (!active || !visible || document.hidden || !range || !refs.length || !A) {render(); return;}
    alertAbort = new AbortController(); alertLoading = true; render();
    try {const result = await request('/workspace/ukraine/replay', {refs, ...range}, {signal: alertAbort.signal}); if (run !== alertRun || !active) return; alertReplay = result; alertLoading = false; render();}
    catch (error) {if (error.name === 'AbortError' || run !== alertRun) return; alertLoading = false; alertError = error.message; render();}
  }
  function renderWatchlist() {
    if (!watchlistHost) return;
    const state = store.getState(), key = JSON.stringify([watchedItems.map(item => [item.ref, item.label]), state.comparedRefs, state.comparedRegionRefs, [...movingBusy]]);
    if (key === watchlistKey) return; watchlistKey = key;
    watchlistSummary.textContent = `Obserwowane (${watchedItems.length})`;
    watchlistHost.replaceChildren(U.el('p', 'Lista jest zapisywana w lokalnej bazie WICI. Obserwowanie nie uruchamia zapisu trasy ani historii alarmów.', 'muted'));
    for (const item of watchedItems) {const row = U.el('div', null, 'analysis-watchlist-row'); row.dataset.ref = item.ref;
      const refs = S.regionRef(item.ref) ? state.comparedRegionRefs : state.comparedRefs, compared = refs.includes(item.ref), compare = U.button(compared ? 'Usuń z porównania' : 'Porównaj', () => toggleCompare(item.ref)), remove = U.button('Przestań obserwować', () => toggleWatch(item));
      compare.disabled = !compared && refs.length >= 5; compare.setAttribute('aria-pressed', String(compared)); remove.disabled = movingBusy.has(item.ref);
      row.append(U.button(item.label || item.ref, () => selectObject(item.ref)), compare, remove); watchlistHost.append(row);
    }
    if (!watchedItems.length) watchlistHost.append(U.el('p', 'Dodaj region Ukrainy, samolot lub statek przyciskiem „Obserwuj” w katalogu albo w karcie.', 'muted'));
  }
  async function loadWatchlist() {
    const run = ++watchlistRun;
    try {const result = await request('/workspace/watchlist'); if (run !== watchlistRun) return; watchedItems = result.items || []; watchedRefs = new Set(watchedItems.map(item => item.ref)); watchlistKey = ''; render();}
    catch (error) {notify(`Nie udało się odczytać listy obserwowanych: ${error.message}`);}
  }
  async function toggleWatch(object) {
    if (movingBusy.has(object.ref)) return;
    const watched = watchedRefs ? watchedRefs.has(object.ref) : object.watched; movingBusy.add(object.ref); render();
    try {await request(`/workspace/watchlist/${encodeURIComponent(object.ref)}`, watched ? null : {}, {method: watched ? 'DELETE' : 'PUT'});
      watchedItems = watchedItems.filter(item => item.ref !== object.ref); if (!watched) watchedItems.push({...object, watched: true}); watchedRefs = new Set(watchedItems.map(item => item.ref));
      await loadWatchlist(); dispatch({type: 'REFRESH'}); notify(watched ? 'Usunięto z obserwowanych. Sesje zapisu trwają niezależnie.' : 'Dodano do obserwowanych. Rejestracja historii działa osobno.');}
    catch (error) {notify(`Nie udało się zmienić obserwowania: ${error.message}`);} finally {movingBusy.delete(object.ref); render();}
  }
  function toggleCompare(ref) {
    const state = store.getState();
    if (S.regionRef(ref)) {if (!state.comparedRegionRefs.includes(ref) && state.comparedRegionRefs.length >= 5) {notify('Możesz porównywać do pięciu regionów. Usuń jeden z porównania.'); return;} dispatch({type: 'TOGGLE_REGION_COMPARE', ref}); return;}
    if (!state.comparedRefs.includes(ref) && state.comparedRefs.length >= 5) {notify('Możesz porównywać do pięciu obiektów. Usuń jeden z porównania.'); return;}
    dispatch({type: 'TOGGLE_COMPARE', ref});
  }
  function compareDay() {const end = new Date(now()).getTime(); dispatch({type: 'SET_TIME_RANGE', range: {from: new Date(end - 86400000).toISOString(), to: new Date(end).toISOString()}});}
  async function loadReplay(force = false) {
    const state = store.getState(), range = state.query.time.filter_range, key = JSON.stringify([state.comparedRefs, range]);
    if (!force && key === replayKey) return;
    replayKey = key; replayAbort?.abort(); const run = ++replayRun; replayData = null; replayError = null; replayLoading = false;
    if (!active || !visible || document.hidden || !range || !state.comparedRefs.length || !M) {render(); return;}
    replayAbort = new AbortController(); replayLoading = true; render();
    try {const result = await request('/workspace/moving/replay', {refs: state.comparedRefs, ...range}, {signal: replayAbort.signal});
      if (run !== replayRun || !active) return; replayData = result; replayLoading = false; render();
    } catch (error) {if (error.name === 'AbortError' || run !== replayRun) return; replayLoading = false; replayError = error.message; render();}
  }
  async function record(object, sessionId = null) {
    if (movingBusy.has(object.ref)) return; movingBusy.add(object.ref); render();
    try {await request(sessionId == null ? '/tracks' : `/tracks/${encodeURIComponent(sessionId)}/stop`, sessionId == null ? {kind: object.type, object_id: object.ref.split(':').at(-1)} : {});
      notify(sessionId == null ? 'Uruchomiono zapis kolejnych obserwacji. Wcześniejsze pozycje nie są uzupełniane.' : 'Zatrzymano zapis. Zapisana sesja pozostaje dostępna do porównania.'); await loadQuery(); loadReplay(true);
    } catch (error) {notify(`Nie udało się zmienić zapisu trasy: ${error.message}`);} finally {movingBusy.delete(object.ref); render();}
  }
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
    const state = store.getState(), sample = currentSample(), motion = motionContext(), alerts = alertContext();
    U.setTimezone?.(state.displayTimezone); renderRegions(); syncMapScope();
    transportLegend.hidden = !state.query.types.some(type => ['aircraft', 'ship'].includes(type)) && !state.comparedRefs.length;
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
    tableView.render(data, state, sample, motion, alerts); timelineView.render(data, state, {historyIncomplete: Boolean(timeline?.next_cursor || timeline?.official_indices_next_cursor), detailLoading, motion, alerts}); mapView.render(data, state, sample, currentIndex(), motion, alerts); motionView?.render(state, motion); alertsView?.render(state, alerts); renderWatchlist();
    const mapItems = data?.map?.items || [...(data?.map?.points || []), ...(data?.map?.areas || [])];
    const inScope = detail?.in_scope ?? (!data || data.items.some(item => item.ref === state.selectedRef) || mapItems.some(item => item.ref === state.selectedRef));
    cardView.render(detail, timeline, state, sample, {inScope, loading: detailLoading, error: detailError, selectedIndex: currentIndex(), motion, alerts});
    sourceCoverage.replaceChildren();
    for (const source of data?.coverage?.sources || []) sourceCoverage.append(U.el('p', `${source.resource}: ${U.statusNames[source.status] || source.status} · ${source.item_count || 0} rekordów · odczyt ${U.date(source.fetched_at)}${source.complete === false || source.complete === 0 ? ' · zakres niepełny' : ''}`, 'muted'));
    if (persistence) sourceCoverage.append(U.el('p', `Zapis historii: ${persistence.pending || 0} w kolejce · ${Object.keys(persistence.errors || {}).length} błędów · ${persistence.rejected_submissions || 0} pominiętych odczytów`, 'muted'));
    if (movingPersistence) sourceCoverage.append(U.el('p', `Katalog samolotów i statków: ${movingPersistence.pending || 0} oczekujących zapisów · ${Object.keys(movingPersistence.errors || {}).length} błędów · ${movingPersistence.coalesced_snapshots || 0} odczytów zastąpionych nowszymi w kolejce. Zapis tras działa osobno.`, Object.keys(movingPersistence.errors || {}).length ? 'notice' : 'muted'));
    persistenceNotice.textContent = Object.keys(movingPersistence?.errors || {}).length ? 'Nie udało się zapisać odczytu samolotów lub statków w katalogu Analizy. Katalog może być nieaktualny. Ponów odczyt źródła w karcie; szczegóły są w „Pokrycie i aktualność źródeł”.' : movingPersistence?.pending ? 'Odczyt transportu oczekuje na zapis w katalogu Analizy. Po zakończeniu odśwież zestaw; źródło i katalog mogą chwilowo różnić się aktualnością.' : '';
    sourceCoverage.append(U.el('small', 'Historia pomiarów powstaje z odczytów na żądanie, przez 14 dni. Daty pierwszego i ostatniego pomiaru nie gwarantują ciągłego pokrycia.'));
    const regionStatus = state.query.time.mode === 'range' && state.query.types.some(type => ['ua_region', 'civil_alert'].includes(type)) ? ` · mapa alarmów przy kursorze: ${(alertReplay?.series || []).filter(item => item.geometry).length} z ${state.comparedRegionRefs.length} porównywanych regionów` : '';
    const replayStatus = state.query.time.mode === 'range' && state.query.types.some(type => ['aircraft', 'ship'].includes(type)) ? ` · mapa tras przy kursorze: ${[...motion.frames.values()].filter(frame => frame.point).length} z ${state.comparedRefs.length} porównywanych obiektów` : '';
    status.textContent = state.error ? `Odczyt nie powiódł się: ${state.error}. Ostatni zestaw pozostaje dostępny.` : state.loading ? 'Odświeżanie wspólnego zestawu…' : data ? `${data.total} obiektów · ${replayStatus ? 'katalog' : 'mapa'}: ${data.map?.located_total ?? 0} z geometrią, ${data.map?.unlocated_total ?? 0} bez geometrii${replayStatus}${regionStatus} · stan na ${U.date(data.as_of)}${data.map?.mode === 'aggregates' ? ' · agregaty: zawęź typ, region lub nazwę' : ''}` : 'Przygotowywanie katalogu…';
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
      const warning = (result.warnings || []).map(item => typeof item === 'string' ? item : item.message || item.code || JSON.stringify(item)).join(' · ');
      if (warning || messageKind === 'query') notify(warning, 'query');
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
  function setRegion(code) {if (!store || store.getState().query.country === 'UA' || store.getState().query.types.some(type => ['ua_region', 'civil_alert'].includes(type)) || store.getState().query.province === (code || null)) return; dispatch({type: 'SET_REGION', province: code});}
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
      if (['ua_region', 'civil_alert'].includes(object.type)) {await Promise.all([sourceManager.request('/ukraine/alerts'), sourceManager.request('/ukraine/geometry')]); await loadRegions();}
      if (object.type === 'hydro_station') await sourceManager.request('/hydro?kind=stations');
      if (object.type === 'aircraft' || object.type === 'ship') await sourceManager.request(object.type === 'aircraft' ? '/aircraft' : '/ships');
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
    return request('/workspace/status').then(result => {persistence = result.persistence || null; movingPersistence = result.moving_persistence || null;
      const incomplete = Boolean(persistence && (Number(persistence.rejected_submissions) > 0 || Object.keys(persistence.errors || {}).length)), movingFailed = Boolean(Object.keys(movingPersistence?.errors || {}).length);
      if (incomplete) notify('Zapis historii jest niepełny: kolejka odnotowała pominięte lub nieudane zapisy.');
      else if (persistenceWarning && !movingFailed && !movingPersistence?.pending) notify('Zapis katalogu i historii działa ponownie. Odśwież zestaw. Wcześniejsze luki historii nie są automatycznie uzupełniane.');
      persistenceWarning = incomplete || movingFailed; render();
    }).catch(() => {});
  }
  function sourceChanged(event) {
    if (!active || !visible || document.hidden) return;
    if (event.error) {if (event.error.name !== 'AbortError') notify(`Źródło chwilowo niedostępne: ${event.error.message}. Zapisane dane pozostają dostępne.`); return;}
    if (['/ukraine/alerts', '/ukraine/geometry'].includes(event.resource) && event.data) {loadRegions(); loadRecording();}
    if (event.data?.analysis_persistence) {movingPersistence = event.data.analysis_persistence;
      if (Object.keys(movingPersistence.errors || {}).length) persistenceWarning = true;
      render();
    }
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
    province = U.el('select'); province.id = 'analysis-province'; const all = U.el('option', 'Wszystkie obszary'); all.value = ''; province.append(all);
    const regions = [...(options.geometries || new Map())].filter(([key]) => /^\d{2}$/.test(key)).sort((a, b) => a[1].properties.name.localeCompare(b[1].properties.name, 'pl'));
    for (const [code, feature] of regions) {const option = U.el('option', feature.properties.name); option.value = code; province.append(option);}
    province.addEventListener('change', () => chooseRegion(province.value)); provinceField = U.field('Obszar danych', province);
    country = U.el('select'); country.id = 'analysis-country';
    for (const [id, name] of [['', 'Wszystkie kraje'], ['PL', 'Polska'], ['UA', 'Ukraina']]) {const option = U.el('option', name); option.value = id; country.append(option);}
    country.addEventListener('change', () => {sourceEnabled = true; const ua = country.value === 'UA'; dispatch({type: 'SET_QUERY', patch: {country: country.value || null, region_ref: null, province: country.value === 'PL' ? window.WiciRegion?.code?.() || null : null, ...(ua ? {types: ['ua_region', 'civil_alert'], source_ids: []} : country.value === 'PL' ? {types: ['communication'], source_ids: []} : {})}});});
    oblast = U.el('select'); oblast.id = 'analysis-ua-oblast'; raion = U.el('select'); raion.id = 'analysis-ua-raion';
    oblast.addEventListener('change', () => dispatch({type: 'SET_QUERY', patch: {country: 'UA', province: null, region_ref: oblast.value || null}}));
    raion.addEventListener('change', () => dispatch({type: 'SET_QUERY', patch: {country: 'UA', province: null, region_ref: raion.value || oblast.value || null}}));
    oblastField = U.field('Obwód Ukrainy', oblast); raionField = U.field('Rejon Ukrainy', raion); regionHint = U.el('small', 'Rejony bez przypisanego obwodu są dostępne przy wyborze „Wszystkie obwody”.', 'muted');
    fields.append(U.field('Szukaj w katalogu', search), U.field('Kraj', country), provinceField, oblastField, raionField, regionHint);
    const types = U.el('div', null, 'analysis-type-filters'); types.setAttribute('role', 'group'); types.setAttribute('aria-label', 'Typy obiektów');
    for (const type of S.TYPES) {const button = U.button(U.typeNames[type], () => {
      const current = store.getState().query.types, next = current.includes(type) ? current.filter(item => item !== type) : [...current, type];
      if (!next.length) {notify('Wybierz co najmniej jeden typ obiektu.', 'query'); return;} sourceEnabled = true; dispatch({type: 'SET_QUERY', patch: {types: next, ...(next.includes(type) && ['ua_region', 'civil_alert'].includes(type) ? {country: 'UA', province: null} : {})}});
    }); button.dataset.objectType = type; button.setAttribute('aria-pressed', 'false'); controls.set(type, button); types.append(button);}
    sourceSelect = U.el('select'); sourceSelect.id = 'analysis-source';
    for (const [id, name] of [['', 'Wszystkie źródła'], ['imgw_meteo', 'Ostrzeżenia IMGW'], ['rso', 'RSO'], ['rcb', 'RCB'], ['sg', 'Straż Graniczna'], ['imgw', 'Wodowskazy IMGW'], ['gios', 'GIOŚ'], ['prg', 'PRG'], ['aircraft', 'Samoloty · ADS-B'], ['ships', 'Statki · AIS'], ['ukraine_alerts', 'Ukraina · alarmy NEPTUN']]) {const option = U.el('option', name); option.value = id; sourceSelect.append(option);}
    sourceSelect.addEventListener('change', () => dispatch({type: 'SET_QUERY', patch: {source_ids: sourceSelect.value ? [sourceSelect.value] : []}})); fields.append(U.field('Źródło', sourceSelect));
    const advanced = U.el('details', null, 'analysis-query-options'); advanced.append(U.el('summary', 'Zakres i układ'));
    const advancedBody = U.el('div', null, 'analysis-option-fields');
    for (const [key, label] of [['include_periods', 'Także okresy ważności i udostępniania'], ['include_unlocated', 'Uwzględnij obiekty bez geometrii'], ['include_without_samples', 'Tylko stacje z pomiarami w przedziale'], ['watched_only', 'Tylko obserwowane regiony, samoloty i statki']]) {
      const checkbox = U.el('input'); checkbox.type = 'checkbox'; checkbox.id = key === 'watched_only' ? 'analysis-watched-only' : `analysis-${key}`;
      checkbox.addEventListener('change', () => dispatch({type: 'SET_QUERY', patch: {[key]: key === 'include_without_samples' ? !checkbox.checked : checkbox.checked}}));
      const labelNode = U.field(label, checkbox); labelNode.className = 'analysis-checkbox'; advancedBody.append(labelNode); checkboxOptions.set(key, checkbox);
    }
    for (const [column, label] of [['type', 'Kolumna: typ'], ['updated_at', 'Kolumna: czas'], ['measurement', 'Kolumna: wartość']]) {const control = U.el('input'); control.type = 'checkbox'; control.checked = true; control.addEventListener('change', () => {const columns = store.getState().columns.filter(item => item !== column); if (control.checked) columns.push(column); dispatch({type: 'SET_COLUMNS', columns});}); columnControls.set(column, control); const node = U.field(label, control); node.className = 'analysis-checkbox'; advancedBody.append(node);}
    split = U.el('input'); split.type = 'range'; split.min = '25'; split.max = '65'; split.step = '1'; split.id = 'analysis-table-size';
    split.addEventListener('input', () => dispatch({type: 'SET_LAYOUT', patch: {tablePercent: Number(split.value)}})); advancedBody.append(U.field('Szerokość tabeli względem mapy', split)); advanced.append(advancedBody);
    message = U.el('p', '', 'analysis-message'); message.id = 'analysis-message'; message.setAttribute('role', 'status');
    persistenceNotice = U.el('p', '', 'analysis-message'); persistenceNotice.id = 'analysis-persistence-status'; persistenceNotice.setAttribute('role', 'status');
    status = U.el('p', '', 'analysis-query-status'); status.id = 'analysis-status'; status.setAttribute('role', 'status');
    const coverage = U.el('details', null, 'analysis-source-coverage'); coverage.append(U.el('summary', 'Pokrycie i aktualność źródeł')); sourceCoverage = U.el('div'); coverage.append(sourceCoverage);
    transportLegend = U.el('details', null, 'analysis-transport-legend'); transportLegend.id = 'analysis-transport-legend';
    transportLegend.append(U.el('summary', 'Samoloty i statki · oznaczenia na mapie'));
    const legendItems = U.el('div', null, 'analysis-transport-legend-items');
    for (const [classes, glyph, label] of [
      ['aircraft-symbol', '✈', 'Samolot · brak oznaczenia wojskowego'],
      ['aircraft-symbol aircraft-military', '✈', 'Samolot · wojskowy według źródła'],
      ['ship-legend-swatch ship-military', '', 'Statek · wojskowy według AIS (kod 35)'],
      ['ship-legend-swatch ship-civilian', '', 'Statek · typ cywilny według AIS'],
      ['ship-legend-swatch ship-unclassified', '', 'Statek · typ nieustalony'],
      ['ship-legend-swatch ship-civilian ship-old', '', 'Paski · pozycja starsza niż 5 minut'],
    ]) {const entry = U.el('span'), symbol = U.el('i', glyph, classes); symbol.setAttribute('aria-hidden', 'true'); entry.append(symbol, U.el('span', label)); legendItems.append(entry);}
    transportLegend.append(legendItems, U.el('p', 'Kolory ikon oznaczają klasyfikację źródła; kolory tras identyfikują obiekty w porównaniu. Brak kodu AIS 35 nie potwierdza cywilnej przynależności. Przy odtwarzaniu klasyfikacja pochodzi z bieżącego katalogu, a wiek pozycji jest liczony względem kursora.', 'muted'));
    const recordingBox = U.el('details', null, 'analysis-ukraine-recording'); recordingBox.id = 'analysis-ukraine-recording'; recordingBox.append(U.el('summary', 'Ukraina · rejestracja historii alarmów'));
    recordingControl = U.el('input'); recordingControl.type = 'checkbox'; recordingControl.id = 'analysis-ukraine-record-enabled'; recordingControl.addEventListener('change', () => changeRecording(recordingControl.checked));
    recordingStatus = U.el('p', '', 'muted'); recordingStatus.id = 'analysis-ukraine-record-status'; recordingStatus.setAttribute('role', 'status');
    recordingBox.append(U.field('Rejestruj historię alarmów Ukrainy', recordingControl), recordingStatus, U.el('p', 'Odczyty co 15 s · retencja 30 dni. Obserwowanie regionu i zapisany widok nie zmieniają tej opcji. Błędy źródła oraz przerwy w działaniu WICI pozostawiają luki.', 'muted'));
    toolbar.append(top, fields, types, advanced, status, message, persistenceNotice, transportLegend, recordingBox, coverage);
    const watchlist = U.el('details', null, 'analysis-watchlist'); watchlist.id = 'analysis-watchlist'; watchlistSummary = U.el('summary', 'Obserwowane (0)'); watchlistHost = U.el('div'); watchlistHost.id = 'analysis-watchlist-items'; watchlist.append(watchlistSummary, watchlistHost); toolbar.append(watchlist);
    views = window.WiciWorkspaceViews(toolbar, {request, status: notify, getConfig() {
      const state = store.getState(), center = options.map?.getCenter?.();
      return {query: structuredClone(state.query), layout: {...state.layout}, columns: [...state.columns], selectedRef: state.selectedRef, comparedRefs: [...state.comparedRefs], comparedRegionRefs: [...state.comparedRegionRefs], displayTimezone: state.displayTimezone,
        camera: center ? {lat: center.lat, lng: center.lng, zoom: options.map.getZoom()} : null};
    }, apply(config, id) {
      sourceEnabled = false; sourceManager?.deactivate?.();
      if (config.relative_seconds && config.query?.time?.mode === 'range') {const end = new Date(now()).getTime(); const range = {from: new Date(end - config.relative_seconds * 1000).toISOString(), to: new Date(end).toISOString()}; config.query.time = {mode: 'range', overview_range: range, filter_range: range};}
      wantsFocus = false; dispatch({type: 'APPLY_VIEW', config, id}); if (config.query?.country !== 'UA') window.WiciRegion?.select?.(config.query?.province || '', {fit: false});
      if (config.camera && options.map) options.map.setView([config.camera.lat, config.camera.lng], config.camera.zoom, {animate: false});
    }, saved: id => dispatch({type: 'VIEW_SAVED', id})});
  }
  function init(settings) {
    if (initialized) return; options = settings; host = document.getElementById('analysis-workspace'); if (!host) return;
    shell = host.closest('.workspace'); store = S.createStore(); sourceManager = settings.sources || window.WiciWorkspaceSources;
    try {const saved = JSON.parse(localStorage.getItem(localKey)); if (saved && typeof saved === 'object') store.dispatch({type: 'SET_LAYOUT', patch: {tablePercent: Math.max(25, Math.min(65, Number(saved.tablePercent) || 42)), mobilePanel: saved.mobilePanel === 'map' ? 'map' : 'table'}});} catch { /* Default layout is sufficient. */ }
    toolbar = U.el('section', null, 'analysis-toolbar'); catalog = U.el('section', null, 'analysis-catalog'); timelineHost = U.el('section', null, 'analysis-timeline'); cardHost = U.el('aside', null, 'analysis-card');
    cardHost.id = 'analysis-card'; cardHost.hidden = true; host.append(toolbar, catalog, timelineHost, cardHost); createToolbar();
    tableView = window.WiciWorkspaceTable(catalog, {select: selectObject, compare: toggleCompare, watch: toggleWatch, sort(field) {const current = store.getState().query.sort; dispatch({type: 'SET_QUERY', patch: {sort: {field, direction: current.field === field && current.direction === 'asc' ? 'desc' : 'asc'}}});}, next: () => loadQuery(data?.next_cursor), first: () => loadQuery(null)});
    timelineView = window.WiciWorkspaceTimeline.create(timelineHost, {dispatch, getState: store.getState, now});
    motionView = M?.view(timelineHost, {remove: toggleCompare, clear: () => dispatch({type: 'CLEAR_COMPARE'}), select: selectObject, range: compareDay, fit: () => mapView.fitTracks?.(replayData)});
    alertsView = A?.view(timelineHost, {remove: toggleCompare, clear: () => dispatch({type: 'CLEAR_REGION_COMPARE'}), select: selectObject, range: compareDay, cursor: at => dispatch({type: 'SET_CURSOR', at}), fit: () => mapView.fitRegions?.(alertContext())});
    mapView = window.WiciWorkspaceMap({map: settings.map, geometries: settings.geometries, select: selectObject, narrow(aggregate) {chooseRegion(aggregate.province); dispatch({type: 'SET_QUERY', patch: {types: [aggregate.type]}}); mapView.show({areas: [{admin_code: aggregate.province}]});}});
    cardView = window.WiciObjectCard(cardHost, {close: closeCard, select: selectObject, watch: toggleWatch, compare: toggleCompare, record, replaySession(session, ref) {
      const lower = Date.parse(session.first_position_at || session.started_at), upper = Date.parse(session.last_position_at || session.stopped_at || now());
      if (!Number.isFinite(lower) || !Number.isFinite(upper)) return;
      if (!store.getState().comparedRefs.includes(ref)) toggleCompare(ref);
      if (!store.getState().comparedRefs.includes(ref)) return;
      dispatch({type: 'SET_TIME_RANGE', range: {from: new Date(Math.floor(lower / 60000) * 60000).toISOString(), to: new Date(Math.max(lower + 60000, Math.ceil((upper + 1) / 60000) * 60000)).toISOString()}});
    }, show(object) {dispatch({type: 'SET_LAYOUT', patch: {mobilePanel: 'map'}});
      if (M?.isMoving(object) && store.getState().query.time.mode === 'range') {const point = motionContext().frames.get(object.ref)?.point; if (!point) {notify('Brak zapisanej pozycji przy kursorze. Dodaj obiekt do porównania i wybierz czas raportu.'); return;} object = {...object, latitude: point.latitude, longitude: point.longitude};}
      if (!mapView.show(object)) notify('Ten obiekt nie ma geometrii do pokazania.');}, version: version => selectObject(store.getState().selectedRef, document.activeElement, version), region(code) {chooseRegion(code); dispatch({type: 'SET_QUERY', patch: {types: ['communication']}});}, sensor(sensor, metric) {dispatch({type: 'SELECT_SENSOR', sensor, metric}); if (store.getState().query.time.mode === 'live' && sensor) sourceManager?.loadSensor?.(sensor).catch(error => notify(error.message));}, fetchSource, sample: sampleSelected, moreHistory: () => loadDetail(true)});
    store.subscribe((state, previous, action) => {
      if (action.type === 'APPLY_VIEW') {clearTimeout(searchTimer); searchTimer = null;}
      if (state.queryRevision !== previous.queryRevision) {pageCursor = null; detailAbort?.abort(); ++detailRun; if (action.type !== 'REFRESH') syncSources(); loadQuery(); loadReplay(action.type === 'REFRESH'); loadAlertReplay(action.type === 'REFRESH');}
      else if (state.detailRevision !== previous.detailRevision) {syncSensor(); detailAbort?.abort(); ++detailRun; if (state.detailOpen) loadDetail();}
      if (state.comparedRefs !== previous.comparedRefs && state.queryRevision === previous.queryRevision) loadReplay();
      if (state.comparedRegionRefs !== previous.comparedRegionRefs && state.queryRevision === previous.queryRevision) loadAlertReplay();
      if (action.type === 'SET_TIME_RANGE' || action.type === 'RETURN_TO_LIVE' || action.type === 'APPLY_VIEW') timelineView.pause?.();
      render();
    });
    sourceManager?.subscribe?.(sourceChanged);
    window.addEventListener?.('resize', positionCard);
    document.addEventListener('keydown', event => {if (active && event.key === 'Escape' && store.getState().detailOpen) {event.preventDefault(); closeCard();}});
    document.addEventListener('visibilitychange', () => {syncSources(); if (document.hidden) timelineView.pause?.(); if (!document.hidden && active && visible) {loadQuery(pageCursor); loadReplay(true); loadAlertReplay(true);}});
    for (const disclosure of toolbar.querySelectorAll?.('details') || []) disclosure.addEventListener('toggle', positionCard);
    initialized = true; render(); host.hidden = true;
  }
  function setActive(value) {
    if (!initialized || active === Boolean(value)) return; active = Boolean(value); host.hidden = !active; shell.classList.toggle('analysis-active', active); mapView.setActive(active); syncSources();
    clearInterval(refreshTimer); refreshTimer = null;
    if (active) {setRegion(window.WiciRegion?.code ? window.WiciRegion.code() : store.getState().query.province); loadQuery(); views.load(); refreshSourceStatus(); loadWatchlist(); loadReplay(true); loadRegions(); loadRecording(); loadAlertReplay(true); refreshTimer = setInterval(() => {if (visible && !document.hidden) {if (store.getState().query.time.mode === 'live') loadQuery(pageCursor); loadRecording();}}, 60000);}
    else {queryAbort?.abort(); detailAbort?.abort(); replayAbort?.abort(); alertAbort?.abort(); ++alertRun; ++queryRun; ++detailRun; ++replayRun; timelineView.pause?.(); shell.classList.remove('analysis-card-open');}
    syncMapScope(); options.map?.invalidateSize?.(); options.onModeChange?.(active);
  }
  function setVisible(value) {if (visible === Boolean(value)) return; visible = Boolean(value); syncSources(); if (!visible) timelineView.pause?.(); if (visible && active) {loadQuery(pageCursor); loadReplay(true); loadAlertReplay(true);}}
  return {init, setActive, setVisible, setRegion, refresh: () => initialized && dispatch({type: 'REFRESH'}), selectObject,
    isActive: () => active, getState: () => store?.getState(), getData: () => data};
})();
