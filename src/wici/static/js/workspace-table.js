'use strict';
window.WiciWorkspaceUI = (() => {
  const typeNames = {communication: 'Komunikat', hydro_station: 'Wodowskaz', air_quality_station: 'Stacja GIOŚ', area: 'Obszar', aircraft: 'Samolot', ship: 'Statek', ua_region: 'Region Ukrainy', civil_alert: 'Alarm Ukrainy', custom_area: 'Własny obszar'};
  const statusNames = {ready: 'Dostępne', partial: 'Dane częściowe', empty: 'Brak danych', disabled: 'Wyłączone',
    error: 'Błąd odczytu', not_loaded: 'Nie pobrano', fresh: 'Aktualne', stale: 'Nieaktualne', unknown_time: 'Czas nieznany', future: 'Czas przyszły', recorded: 'Zapis historyczny', no_data: 'Brak danych'};
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
  return {el, button, date, value, measurement, field, safeLink, setTimezone, typeNames, statusNames, metricNames};
})();
window.WiciWorkspaceTable = function (host, {select, sort, next, first, compare, watch}) {
  const U = window.WiciWorkspaceUI, M = window.WiciWorkspaceMotion, A = window.WiciWorkspaceAlerts, heading = U.el('div', null, 'analysis-results-heading'), title = U.el('h2', 'Katalog obiektów');
  title.id = 'analysis-results-title'; title.tabIndex = -1;
  const count = U.el('span', 'Wczytywanie…'); count.id = 'analysis-count'; count.setAttribute('aria-live', 'polite');
  heading.append(title, count);
  const scroll = U.el('div', null, 'analysis-table-scroll'), table = U.el('table'), caption = U.el('caption', 'Obiekty wspólnego zakresu mapy i osi czasu', 'sr-only');
  table.id = 'analysis-table'; const thead = U.el('thead'), header = U.el('tr'), headers = new Map();
  for (const [field, label] of [['label', 'Obiekt'], ['type', 'Typ'], ['updated_at', 'Odczyt / aktualizacja']]) {
    const th = U.el('th'); th.scope = 'col'; const control = U.button(label, () => sort(field)); th.append(control); header.append(th); headers.set(field, th);
  }
  const measurementHeading = U.el('th', 'Wartość / stan'); measurementHeading.scope = 'col'; header.append(measurementHeading); thead.append(header);
  const body = U.el('tbody'); table.append(caption, thead, body); scroll.append(table);
  const pagination = U.el('div', null, 'analysis-pagination'), firstButton = U.button('Pierwsza strona', first), nextButton = U.button('Następna strona →', next);
  nextButton.id = 'analysis-next-page'; pagination.append(firstButton, nextButton); host.append(heading, scroll, pagination);
  let previousItems = null, previousSort = '', rows = new Map();
  function render(data, state, selectedSample, motion, alerts) {
    host.dataset.tableScope = data?._graphScope ? 'graph' : 'catalog'; title.textContent = data?._graphScope ? 'Węzły grafu' : 'Katalog obiektów'; caption.textContent = data?._graphScope ? 'Obiekty widocznego grafu; mogą wychodzić poza filtry katalogu' : 'Obiekty wspólnego zakresu mapy i osi czasu';
    const items = data?.items || [], sortKey = JSON.stringify(state.query.sort);
    if (items !== previousItems || previousSort !== sortKey) {
      previousItems = items; previousSort = sortKey; body.replaceChildren(); rows = new Map();
      for (const item of items) {
        const row = U.el('tr'); row.dataset.ref = item.ref;
        const name = U.el('td'), control = U.button(item.label, event => select(item.ref, event.currentTarget)); control.className = 'analysis-object-link'; name.append(control);
        name.append(U.el('small', item.ref)); const type = U.el('td', U.typeNames[item.type] || item.type), time = U.el('td'), reading = U.el('td');
        let compareControl, watchControl;
        if (M?.isMoving(item) || item.type === 'ua_region') {const actions = U.el('div', null, 'analysis-row-actions'); compareControl = U.el('input'); compareControl.type = 'checkbox'; compareControl.className = 'analysis-compare-toggle'; compareControl.setAttribute('aria-label', `Porównaj ${item.label}`); compareControl.addEventListener('change', () => compare?.(item.ref));
          const label = U.field('Porównaj', compareControl); label.className = 'analysis-checkbox'; watchControl = U.button('Obserwuj', () => watch?.(item), 'analysis-watch-toggle'); actions.append(label, watchControl); name.append(actions);}
        row.append(name, type, time, reading); body.append(row); rows.set(item.ref, {row, time, reading, item, compareControl, watchControl});
      }
      if (!items.length) {const row = U.el('tr'), cell = U.el('td', 'Brak obiektów w tym zakresie. Zmień filtry lub pobierz dane wybranego źródła.'); cell.colSpan = 4; row.append(cell); body.append(row);}
    }
    for (const [field, th] of headers) th.setAttribute('aria-sort', state.query.sort.field === field ? state.query.sort.direction === 'asc' ? 'ascending' : 'descending' : 'none');
    for (const [ref, {row, time, reading, item, compareControl, watchControl}] of rows) {
      const graphScope = Boolean(data?._graphScope);
      const selected = state.detailOpen && ref === state.selectedRef, cursor = selected && state.cursorAt && item.type.endsWith('_station'), sample = cursor ? selectedSample : selected && selectedSample ? selectedSample : U.measurement(item);
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
        continue;
      }
      time.textContent = U.date(cursor ? sample?.observed_at : sample?.observed_at || item.updated_at || item.published_at || item.fetched_at);
      reading.replaceChildren(U.el('span', item.type.endsWith('_station') ? U.value(sample) : ['area', 'custom_area'].includes(item.type) ? 'Kontekst bezczasowy' : U.statusNames[item.availability] || 'Materiał źródłowy'));
      const note = cursor ? 'Według kursora' : item.freshness ? U.statusNames[item.freshness] || item.freshness : item.type.endsWith('_station') && state.query.time.mode === 'range' ? 'Przegląd okresu' : '';
      if (note) reading.append(U.el('small', note));
    }
    const columns = ['label', 'type', 'updated_at', 'measurement'];
    for (const row of [header, ...Array.from(body.children)]) for (const [index, cell] of Array.from(row.children).entries()) if (row === header || rows.size) cell.hidden = !(state.columns || columns).includes(columns[index]);
    count.textContent = data?._graphScope ? `${items.length} obiektów widocznego grafu` : `${data?.total || 0} obiektów · ${items.length} na stronie${state.loading ? ' · odświeżanie…' : ''}`;
    nextButton.disabled = !data?.next_cursor || state.loading; firstButton.disabled = !data?._pageCursor || state.loading;
  }
  return {render, focusHeading: () => title.focus()};
};
