'use strict';
window.WiciWorkspaceUI = (() => {
  const typeNames = {communication: 'Komunikat', hydro_station: 'Wodowskaz', air_quality_station: 'Stacja GIOŚ', area: 'Obszar'};
  const statusNames = {ready: 'Dostępne', partial: 'Dane częściowe', empty: 'Brak danych', disabled: 'Wyłączone',
    error: 'Błąd odczytu', not_loaded: 'Nie pobrano', fresh: 'Aktualne', stale: 'Nieaktualne', unknown_time: 'Czas nieznany', future: 'Czas przyszły'};
  const metricNames = {water_level: 'Stan wody', discharge: 'Przepływ', temperature: 'Temperatura'};
  function el(tag, text, cls) {const node = document.createElement(tag); if (text != null) node.textContent = String(text); if (cls) node.className = cls; return node;}
  function button(text, onClick, cls) {const node = el('button', text, cls); node.type = 'button'; if (onClick) node.addEventListener('click', onClick); return node;}
  function date(value) {if (!value) return 'Brak czasu'; if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value} · sama data`;
    const parsed = new Date(value); return Number.isFinite(parsed.getTime()) ? new Intl.DateTimeFormat('pl-PL', {timeZone: 'Europe/Warsaw', dateStyle: 'short', timeStyle: 'short'}).format(parsed) : 'Czas nieznany';}
  function measurement(item) {return item?.measurement || item?.latest || (Array.isArray(item?.measurements) ? item.measurements[0] : null);}
  function value(sample) {return sample?.value == null ? 'Brak pomiaru' : `${sample.value} ${sample.unit || ''}`.trim();}
  function field(label, control) {const node = el('label', label); node.append(control); return node;}
  function safeLink(url, text) {try {const parsed = new URL(url); if (!['https:', 'http:'].includes(parsed.protocol)) return null;
    const link = el('a', text || 'Materiał źródłowy'); link.href = parsed.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;} catch {return null;}}
  return {el, button, date, value, measurement, field, safeLink, typeNames, statusNames, metricNames};
})();
window.WiciWorkspaceTable = function (host, {select, sort, next, first}) {
  const U = window.WiciWorkspaceUI, heading = U.el('div', null, 'analysis-results-heading'), title = U.el('h2', 'Katalog obiektów');
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
  function render(data, state, selectedSample) {
    const items = data?.items || [], sortKey = JSON.stringify(state.query.sort);
    if (items !== previousItems || previousSort !== sortKey) {
      previousItems = items; previousSort = sortKey; body.replaceChildren(); rows = new Map();
      for (const item of items) {
        const row = U.el('tr'); row.dataset.ref = item.ref;
        const name = U.el('td'), control = U.button(item.label, event => select(item.ref, event.currentTarget)); control.className = 'analysis-object-link'; name.append(control);
        name.append(U.el('small', item.ref)); const type = U.el('td', U.typeNames[item.type] || item.type), time = U.el('td'), reading = U.el('td');
        row.append(name, type, time, reading); body.append(row); rows.set(item.ref, {row, time, reading, item});
      }
      if (!items.length) {const row = U.el('tr'), cell = U.el('td', 'Brak obiektów w tym zakresie. Zmień filtry lub pobierz dane stacji.'); cell.colSpan = 4; row.append(cell); body.append(row);}
    }
    for (const [field, th] of headers) th.setAttribute('aria-sort', state.query.sort.field === field ? state.query.sort.direction === 'asc' ? 'ascending' : 'descending' : 'none');
    for (const [ref, {row, time, reading, item}] of rows) {
      const selected = state.detailOpen && ref === state.selectedRef, cursor = selected && state.cursorAt && item.type.endsWith('_station'), sample = cursor ? selectedSample : selected && selectedSample ? selectedSample : U.measurement(item);
      row.classList.toggle('selected', selected); if (selected) row.setAttribute('aria-selected', 'true'); else row.removeAttribute('aria-selected');
      time.textContent = U.date(cursor ? sample?.observed_at : sample?.observed_at || item.updated_at || item.published_at || item.fetched_at);
      reading.replaceChildren(U.el('span', item.type.endsWith('_station') ? U.value(sample) : item.type === 'area' ? 'Kontekst bezczasowy' : U.statusNames[item.availability] || 'Materiał źródłowy'));
      const note = cursor ? 'Według kursora' : item.freshness ? U.statusNames[item.freshness] || item.freshness : item.type.endsWith('_station') && state.query.time.mode === 'range' ? 'Przegląd okresu' : '';
      if (note) reading.append(U.el('small', note));
    }
    const columns = ['label', 'type', 'updated_at', 'measurement'];
    for (const row of [header, ...Array.from(body.children)]) for (const [index, cell] of Array.from(row.children).entries()) if (row === header || rows.size) cell.hidden = !(state.columns || columns).includes(columns[index]);
    count.textContent = `${data?.total || 0} obiektów · ${items.length} na stronie${state.loading ? ' · odświeżanie…' : ''}`;
    nextButton.disabled = !data?.next_cursor || state.loading; firstButton.disabled = !data?._pageCursor || state.loading;
  }
  return {render, focusHeading: () => title.focus()};
};
