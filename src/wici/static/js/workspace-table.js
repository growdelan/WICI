'use strict';
window.WiciWorkspaceUI = (() => {
  const typeNames = {communication: 'Komunikat', hydro_station: 'Wodowskaz', air_quality_station: 'Stacja GIOŚ', area: 'Obszar', aircraft: 'Samolot', ship: 'Statek', ua_region: 'Region Ukrainy', civil_alert: 'Alarm Ukrainy', custom_area: 'Własny obszar'};
  const statusNames = {ready: 'Dostępne', partial: 'Dane częściowe', empty: 'Brak danych', disabled: 'Wyłączone',
    error: 'Błąd odczytu', not_loaded: 'Nie pobrano', fresh: 'Aktualne', stale: 'Nieaktualne', unknown_time: 'Czas nieznany', future: 'Czas przyszły', recorded: 'Zapis historyczny', no_data: 'Brak danych'};
  const sourceNames = {imgw: 'IMGW', imgw_meteo: 'IMGW', gios: 'GIOŚ', rso: 'RSO', rcb: 'RCB', sg: 'Straż Graniczna', prg: 'PRG', aircraft: 'adsb.fi', ships: 'AISStream', ukraine_alerts: 'NEPTUN', local: 'Lokalnie'};
  const iconPaths = {hydro_station: 'M2 7c3-5 7 5 10 0s7 5 10 0M2 12c3-5 7 5 10 0s7 5 10 0M2 17c3-5 7 5 10 0s7 5 10 0', air_quality_station: 'M3 8h12a3 3 0 1 0-3-3M2 12h17a3 3 0 1 1-3 3M4 16h5', communication: 'M3 9v6h4l12 4V5L7 9H3Zm4 6 2 6h3l-2-5M19 8l3 2v4l-3 2', area: 'm4 4 16 2-2 14-15-3 1-13Z', custom_area: 'm4 4 16 2-2 14-15-3 1-13Z', aircraft: 'm12 2 2 7 8 5v3l-8-3v5l3 2v1l-5-1-5 1v-1l3-2v-5l-8 3v-3l8-5 2-7Z', ship: 'M7 12V5h10v7M10 5V2h4v3M3 13l9-3 9 3-4 7H7l-4-7ZM2 22c3-3 5 3 8 0s5 3 8 0h4', ua_region: 'm4 4 16 2-2 14-15-3 1-13Z', civil_alert: 'm12 3 10 18H2L12 3Zm0 6v5m0 3v1', list: 'M8 6h13M8 12h13M8 18h13M3 6h1M3 12h1M3 18h1', table: 'M3 3h18v18H3V3Zm0 6h18M3 15h18M9 3v18M15 3v18'};
  function icon(type, cls = 'analysis-result-icon') {const node = el('span', null, cls); node.setAttribute('aria-hidden', 'true'); node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${iconPaths[type] || iconPaths.area}"></path></svg>`; return node;}
  function shortTime(value) {if (/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return `${value} · sama data`; const parsed = new Date(value); return value && Number.isFinite(parsed.getTime()) ? new Intl.DateTimeFormat('pl-PL', {timeZone: displayTimezone, hour: '2-digit', minute: '2-digit'}).format(parsed) : 'Brak czasu';}
  const metricNames = {water_level: 'Stan wody', discharge: 'Przepływ', temperature: 'Temperatura'};
  function el(tag, text, cls) {const node = document.createElement(tag); if (text != null) node.textContent = String(text); if (cls) node.className = cls; return node;}
  function button(text, onClick, cls) {const node = el('button', text, cls); node.type = 'button'; if (onClick) node.addEventListener('click', onClick); return node;}
  let displayTimezone = 'Europe/Warsaw';
  function setTimezone(value) {displayTimezone = ['Europe/Warsaw', 'Europe/Kyiv', 'UTC'].includes(value) ? value : 'Europe/Warsaw';}
  function date(value) {if (!value) return 'Brak czasu'; if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value} · sama data`;
    const parsed = new Date(value); return Number.isFinite(parsed.getTime()) ? new Intl.DateTimeFormat('pl-PL', {timeZone: displayTimezone, dateStyle: 'short', timeStyle: 'short'}).format(parsed) : 'Czas nieznany';}
  function measurement(item) {return item?.measurement || item?.latest || (Array.isArray(item?.measurements) ? item.measurements[0] : null);}
  function value(sample) {return sample?.value == null ? 'Brak pomiaru' : `${sample.value} ${sample.unit || ''}`.trim();}
  function field(label, control) {const node = el('label', label); node.append(control); return node;}
  function safeLink(url, text) {try {const parsed = new URL(url); if (!['https:', 'http:'].includes(parsed.protocol)) return null;
    const link = el('a', text || 'Materiał źródłowy'); link.href = parsed.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;} catch {return null;}}
  return {el, button, date, shortTime, icon, value, measurement, field, safeLink, setTimezone, typeNames, sourceNames, statusNames, metricNames};
})();
window.WiciWorkspaceTable = function (host, {select, sort, next, first, compare, watch}) {
  const U = window.WiciWorkspaceUI, M = window.WiciWorkspaceMotion, A = window.WiciWorkspaceAlerts, heading = U.el('div', null, 'analysis-results-heading'), title = U.el('h2', 'Wyniki');
  title.id = 'analysis-results-title'; title.tabIndex = -1;
  const count = U.el('span', 'Wczytywanie…'); count.id = 'analysis-count'; count.setAttribute('aria-live', 'polite');
  const titleGroup = U.el('div', null, 'analysis-results-title-group'); titleGroup.append(title, count);
  const viewSwitch = U.el('div', null, 'analysis-results-switch'); viewSwitch.setAttribute('role', 'group'); viewSwitch.setAttribute('aria-label', 'Prezentacja wyników');
  const viewButtons = new Map(); let resultsView = 'list', lastState = null;
  function setResultsView(view) {
    resultsView = view; host.dataset.resultsView = view;
    for (const [name, control] of viewButtons) control.setAttribute('aria-pressed', String(name === view));
    previousColumns = null; if (lastState) updateColumns(lastState);
  }
  for (const [view, label] of [['list', 'Lista'], ['table', 'Tabela']]) {
    const control = U.button(null, () => setResultsView(view)); control.dataset.resultsView = view;
    control.setAttribute('aria-controls', 'analysis-table'); control.setAttribute('aria-pressed', String(view === resultsView));
    control.append(U.icon(view, 'analysis-view-icon'), U.el('span', label)); viewSwitch.append(control); viewButtons.set(view, control);
  }
  host.dataset.resultsView = resultsView; heading.append(titleGroup, viewSwitch);
  const scroll = U.el('div', null, 'analysis-table-scroll'), table = U.el('table'), caption = U.el('caption', 'Obiekty wspólnego zakresu mapy i osi czasu', 'sr-only');
  table.id = 'analysis-table'; const thead = U.el('thead'), header = U.el('tr'), headers = new Map();
  for (const [field, label] of [['label', 'Obiekt'], ['type', 'Typ'], ['updated_at', 'Odczyt / aktualizacja']]) {
    const th = U.el('th'); th.scope = 'col'; const control = U.button(label, () => sort(field)); th.append(control); header.append(th); headers.set(field, th);
  }
  const measurementHeading = U.el('th', 'Wartość / stan'); measurementHeading.scope = 'col'; header.append(measurementHeading); thead.append(header);
  const body = U.el('tbody'); table.append(caption, thead, body); scroll.append(table);
  const pagination = U.el('div', null, 'analysis-pagination'), firstButton = U.button('Pierwsza strona', first), nextButton = U.button('Następna strona →', next);
  nextButton.id = 'analysis-next-page'; pagination.append(firstButton, nextButton); host.append(heading, scroll, pagination);
  let previousItems = null, previousSort = '', previousColumns = null, rows = new Map();
  function updateColumns(state) {
    if (previousColumns === state.columns) return;
    previousColumns = state.columns; const columns = ['label', 'type', 'updated_at', 'measurement'];
    for (const row of [header, ...Array.from(body.children)]) for (const [index, cell] of Array.from(row.children).entries()) if (row === header || rows.size) cell.hidden = resultsView === 'list' ? index !== 0 : !(state.columns || columns).includes(columns[index]);
  }
  function badge(item, sample, historical, cursor) {
    if (item.type === 'hydro_station') {
      if (!sample || sample.value == null) return ['Brak pomiaru', 'muted'];
      if (cursor) return ['Według kursora', 'neutral'];
      if (historical) return ['Zapis', 'neutral'];
      if (item.freshness !== 'fresh') return [U.statusNames[item.freshness] || 'Czas nieznany', 'muted'];
      if (sample.metric === 'water_level') {
        const thresholds = sample.thresholds || sample.provenance?.thresholds || {};
        if (Number.isFinite(thresholds.alarm_level_cm) && sample.value >= thresholds.alarm_level_cm) return ['Próg alarmowy', 'danger'];
        if (Number.isFinite(thresholds.warning_level_cm) && sample.value >= thresholds.warning_level_cm) return ['Próg ostrzegawczy', 'warning'];
        if (Number.isFinite(thresholds.warning_level_cm)) return ['Poniżej progu', 'good'];
      }
      return [U.value(sample), 'neutral'];
    }
    if (item.type === 'air_quality_station') return [cursor ? 'Według kursora' : historical ? 'Zapis' : U.statusNames[item.freshness] || 'Brak danych', item.freshness === 'fresh' ? 'neutral' : 'muted'];
    if (item.type === 'communication') {
      const statuses = {active: ['Aktywny', 'warning'], expired: ['Wygasł', 'muted'], cancelled: ['Odwołany', 'muted'], upcoming: ['Zapowiedziany', 'neutral']};
      return statuses[item.warning_status] || ['Publikacja', 'neutral'];
    }
    return [['area', 'custom_area'].includes(item.type) ? 'Obszar' : U.statusNames[item.availability] || 'Dostępne', 'neutral'];
  }
  function presentList(entry, at, status) {
    const item = entry.item, source = U.sourceNames[item.source_id] || item.source_id;
    const dayOnly = item.type === 'communication' && (item.date_precision === 'day' || item.time_precision === 'day');
    const when = dayOnly ? item.metadata?.source_published_date || String(item.published_at || at || '').slice(0, 10) : at;
    entry.meta.textContent = [U.typeNames[item.type] || item.type, source, when ? lastState?.query.time.mode === 'range' ? U.date(when) : U.shortTime(when) : null].filter(Boolean).join(' · ');
    entry.meta.title = when ? U.date(when) : '';
    entry.status.textContent = status[0]; entry.status.dataset.tone = status[1];
  }
  function render(data, state, selectedSample, motion, alerts) {
    lastState = state; host.dataset.tableScope = data?._graphScope ? 'graph' : 'catalog'; title.textContent = data?._graphScope ? 'Węzły grafu' : 'Wyniki'; caption.textContent = data?._graphScope ? 'Obiekty widocznego grafu; mogą wychodzić poza filtry katalogu' : 'Obiekty wspólnego zakresu mapy i osi czasu';
    const items = data?.items || [], sortKey = JSON.stringify(state.query.sort);
    if (items !== previousItems || previousSort !== sortKey) {
      previousItems = items; previousSort = sortKey; previousColumns = null; body.replaceChildren(); rows = new Map();
      for (const item of items) {
        const row = U.el('tr'); row.dataset.ref = item.ref;
        const name = U.el('td', null, 'analysis-result-name'), control = U.button(item.label, event => select(item.ref, event.currentTarget)); control.className = 'analysis-object-link';
        row.addEventListener('click', event => {if (resultsView === 'list' && !event.target.closest?.('button, input, label, a')) select(item.ref, control);});
        const main = U.el('div', null, 'analysis-result-main'), copy = U.el('div', null, 'analysis-result-copy'), meta = U.el('small', null, 'analysis-result-meta'), status = U.el('span', null, 'analysis-result-status');
        copy.append(control, meta); main.append(U.icon(item.type), copy, status); name.append(main);
        name.append(U.el('small', item.ref, 'analysis-result-ref')); const type = U.el('td', U.typeNames[item.type] || item.type, 'analysis-result-type'), time = U.el('td', null, 'analysis-result-time'), reading = U.el('td', null, 'analysis-result-reading');
        let compareControl, watchControl;
        if (M?.isMoving(item) || item.type === 'ua_region') {const actions = U.el('div', null, 'analysis-row-actions'); compareControl = U.el('input'); compareControl.type = 'checkbox'; compareControl.className = 'analysis-compare-toggle'; compareControl.setAttribute('aria-label', `Porównaj ${item.label}`); compareControl.addEventListener('change', () => compare?.(item.ref));
          const label = U.field('Porównaj', compareControl); label.className = 'analysis-checkbox'; watchControl = U.button('Obserwuj', () => watch?.(item), 'analysis-watch-toggle'); actions.append(label, watchControl); name.append(actions);}
        row.append(name, type, time, reading); body.append(row); rows.set(item.ref, {row, time, reading, item, meta, status, compareControl, watchControl});
      }
      if (!items.length) {const row = U.el('tr'), cell = U.el('td', 'Brak obiektów w tym zakresie. Zmień filtry lub pobierz dane wybranego źródła.'); cell.colSpan = 4; cell.className = 'analysis-results-empty'; row.append(cell); body.append(row);}
    }
    for (const [field, th] of headers) th.setAttribute('aria-sort', state.query.sort.field === field ? state.query.sort.direction === 'asc' ? 'ascending' : 'descending' : 'none');
    for (const [ref, entry] of rows) {
      const {row, time, reading, item, compareControl, watchControl} = entry;
      const graphScope = Boolean(data?._graphScope);
      const selected = state.detailOpen && ref === state.selectedRef, cursor = selected && state.cursorAt && item.type.endsWith('_station'), sample = cursor ? selectedSample : selected && selectedSample ? selectedSample : U.measurement(item);
      const historical = state.query.time.mode === 'range', moving = M?.isMoving(item), alarm = item.type === 'ua_region' || item.type === 'civil_alert';
      const frame = moving ? motion?.frames?.get(ref) : alarm ? alerts?.frames?.get(item.type === 'ua_region' ? ref : item.region_ref || item.metadata?.region_ref) : null;
      const inputs = [item, selected, Boolean(cursor), sample, graphScope, historical, state.displayTimezone,
        moving || alarm ? state.comparedRefs : null, alarm ? state.comparedRegionRefs : null,
        moving ? motion?.watched?.has(ref) : alarm ? alerts?.watched?.has(ref) : null,
        moving ? motion?.busy?.has(ref) : alarm ? alerts?.busy?.has(ref) : null,
        frame?.point, frame?.lastPoint, frame?.status, frame?.age_seconds, frame?.state, frame?.segment,
        alarm && historical ? state.cursorAt || state.query.time.filter_range?.to : null];
      if (entry.inputs && inputs.every((value, index) => value === entry.inputs[index])) continue;
      entry.inputs = inputs;
      row.classList.toggle('selected', selected); if (selected) row.setAttribute('aria-selected', 'true'); else row.removeAttribute('aria-selected');
      if (item.type === 'ua_region' || item.type === 'civil_alert') {
        const region = item.type === 'ua_region', compared = state.comparedRegionRefs?.includes(ref), watched = alerts?.watched ? alerts.watched.has(ref) : item.watched;
        if (compareControl) {compareControl.checked = compared; compareControl.disabled = !compared && (state.comparedRegionRefs?.length || 0) >= 5;}
        if (watchControl) {watchControl.textContent = watched ? 'Obserwowany ★' : 'Obserwuj ☆'; watchControl.setAttribute('aria-pressed', String(Boolean(watched))); watchControl.disabled = Boolean(alerts?.busy?.has(ref));}
        const historical = state.query.time.mode === 'range', frame = historical ? alerts?.frames?.get(region ? ref : item.region_ref || item.metadata?.region_ref) : null;
        const status = historical && !graphScope ? !frame || frame.state === 'unknown' ? 'unknown' : region || frame.segment?.episode_ref === ref ? frame.state : 'none' : A?.objectState(item) || 'unknown';
        row.dataset.alertState = status; time.textContent = U.date(historical ? state.cursorAt || new Date(Date.parse(state.query.time.filter_range?.to) - 1).toISOString() : item.updated_at || item.fetched_at);
        reading.replaceChildren(U.el('span', A?.stateNames[status] || status));
        reading.append(U.el('small', historical && !graphScope ? frame ? 'Według wspólnego kursora' : 'Dodaj region do porównania, aby odtworzyć stan' : 'Stan według źródła NEPTUN'));
        presentList(entry, historical ? state.cursorAt : item.updated_at || item.fetched_at, [A?.stateNames[status] || status, status === 'red' ? 'danger' : status === 'yellow' ? 'warning' : status === 'unknown' ? 'muted' : 'neutral']);
        continue;
      }
      if (M?.isMoving(item)) {
        const compared = state.comparedRefs?.includes(ref), watched = motion?.watched ? motion.watched.has(ref) : item.watched;
        if (compareControl) {compareControl.checked = compared; compareControl.disabled = !compared && (state.comparedRefs?.length || 0) >= 5;}
        if (watchControl) {watchControl.textContent = watched ? 'Obserwowany ★' : 'Obserwuj ☆'; watchControl.setAttribute('aria-pressed', String(Boolean(watched))); watchControl.disabled = Boolean(motion?.busy?.has(ref));}
        const historical = state.query.time.mode === 'range', frame = motion?.frames?.get(ref), position = historical && !graphScope ? frame?.point : item.position;
        row.dataset.motionStatus = historical && !graphScope ? frame?.status || 'not_compared' : item.freshness || 'unknown_time';
        time.textContent = U.date(position?.position_at || position?.at);
        reading.replaceChildren(U.el('span', M.number(position?.speed_kmh, 'km/h')));
        if (item.type === 'aircraft') reading.append(U.el('small', `Wysokość ${M.number(position?.altitude_m, 'm')}`));
        reading.append(U.el('small', historical && !graphScope ? M.describe(frame, U) : U.statusNames[item.freshness] || item.freshness || 'Czas nieznany'));
        presentList(entry, position?.position_at || position?.at, [historical && !graphScope ? frame?.status === 'ready' ? 'Zapis' : 'Brak pozycji' : U.statusNames[item.freshness] || 'Czas nieznany', historical || item.freshness !== 'fresh' ? 'muted' : 'neutral']);
        continue;
      }
      time.textContent = U.date(cursor ? sample?.observed_at : sample?.observed_at || item.updated_at || item.published_at || item.fetched_at);
      reading.replaceChildren(U.el('span', item.type.endsWith('_station') ? U.value(sample) : ['area', 'custom_area'].includes(item.type) ? 'Kontekst bezczasowy' : U.statusNames[item.availability] || 'Materiał źródłowy'));
      const note = cursor ? 'Według kursora' : item.freshness ? U.statusNames[item.freshness] || item.freshness : item.type.endsWith('_station') && state.query.time.mode === 'range' ? 'Przegląd okresu' : '';
      if (note) reading.append(U.el('small', note));
      presentList(entry, cursor ? sample?.observed_at : sample?.observed_at || item.updated_at || item.published_at || item.fetched_at, badge(item, sample, historical, cursor));
    }
    updateColumns(state);
    const total = data?._graphScope ? items.length : data?.total || 0;
    count.textContent = `· ${total}`; count.title = `${total} obiektów · ${items.length} na stronie${state.loading ? ' · odświeżanie…' : ''}`;
    count.setAttribute('aria-label', count.title); host.setAttribute('aria-busy', String(Boolean(state.loading)));
    nextButton.disabled = !data?.next_cursor || state.loading; firstButton.disabled = !data?._pageCursor || state.loading;
  }
  return {render, focusHeading: () => title.focus()};
};
