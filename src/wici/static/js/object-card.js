'use strict';
window.WiciObjectCard = function (host, actions) {
  const U = window.WiciWorkspaceUI, heading = U.el('div', null, 'analysis-card-heading'), title = U.el('h2', 'Szczegóły obiektu');
  title.id = 'analysis-card-title'; title.tabIndex = -1; host.setAttribute('aria-labelledby', title.id);
  const close = U.button('Zamknij ×', actions.close); close.id = 'analysis-close-card'; heading.append(title, close);
  const outside = U.el('p', 'Poza bieżącym zakresem. Karta zachowuje wybrany obiekt.', 'notice'), body = U.el('div', null, 'analysis-card-body');
  outside.id = 'analysis-outside-range'; host.append(heading, outside, body);
  let lastKey = '', lastDetail = null, lastTimeline = null, reading, readingTime, readingNote, readingClocks, officialIndexNode, lastError = '';
  const section = (parent, name) => {const node = U.el('section', null, 'analysis-card-section'); node.append(U.el('h3', name)); parent.append(node); return node;};
  function dl(parent, entries) {const node = U.el('dl'); for (const [key, value] of entries) node.append(U.el('dt', key), U.el('dd', value ?? 'Nie podano')); parent.append(node);}
  function drawSeries(parent, samples, onSample) {
    if (!samples.length) {parent.append(U.el('p', 'Brak zapisanych pomiarów w przedziale. Historia powstaje z odczytów na żądanie; retencja wynosi 14 dni.', 'muted')); return;}
    const latest = new Map();
    for (const sample of samples) {const key = [sample.sensor_id, sample.metric, sample.observed_at].join('|'); if (!latest.has(key) || (sample.revision || 0) > (latest.get(key).revision || 0)) latest.set(key, sample);}
    const ordered = [...latest.values()].filter(item => Number.isFinite(Date.parse(item.observed_at))).sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
    const values = ordered.filter(item => Number.isFinite(item.value));
    if (values.length) {
      const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 400 130'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Zapisane pomiary; przerwy w danych nie są interpolowane'); svg.classList.add('analysis-series');
      const lower = Math.min(...ordered.map(item => Date.parse(item.observed_at))), upper = Math.max(...ordered.map(item => Date.parse(item.observed_at))), min = Math.min(...values.map(item => item.value)), max = Math.max(...values.map(item => item.value));
      const x = item => 20 + 360 * (Date.parse(item.observed_at) - lower) / Math.max(1, upper - lower), y = item => 110 - 90 * (item.value - min) / Math.max(1, max - min);
      let previous = null;
      for (const sample of ordered) {
        if (!Number.isFinite(sample.value)) {previous = null; continue;}
        if (previous && Date.parse(sample.observed_at) - Date.parse(previous.observed_at) <= 3 * 3600000 && sample.metric === previous.metric && sample.sensor_id === previous.sensor_id) {
          const line = document.createElementNS(ns, 'line'); for (const [attribute, value] of Object.entries({x1: x(previous), y1: y(previous), x2: x(sample), y2: y(sample)})) line.setAttribute(attribute, value); line.setAttribute('stroke', 'var(--teal)'); line.setAttribute('stroke-width', '1.5'); svg.append(line);
        }
        const dot = document.createElementNS(ns, 'circle'); dot.setAttribute('cx', x(sample)); dot.setAttribute('cy', y(sample)); dot.setAttribute('r', '2.5'); dot.setAttribute('fill', 'var(--teal)');
        const tooltip = document.createElementNS(ns, 'title'); tooltip.textContent = `${U.date(sample.observed_at)} · ${U.value(sample)}`; dot.append(tooltip); svg.append(dot); previous = sample;
      }
      parent.append(svg, U.el('small', `Minimum ${min} · maksimum ${max} ${values[0].unit || ''}. Najnowsze rewizje punktów źródłowych. Bez interpolacji luk ponad 3 godziny; korekty są w tabeli.`));
    }
    const table = U.el('table', null, 'analysis-sample-table'), head = U.el('tr');
    for (const label of ['Czas obserwacji', 'Wartość', 'Rewizja']) {const cell = U.el('th', label); cell.scope = 'col'; head.append(cell);} const thead = U.el('thead'); thead.append(head); table.append(thead); const tbody = U.el('tbody');
    for (const sample of [...samples].reverse().slice(0, 100)) {const row = U.el('tr'), dateCell = U.el('td'), value = U.el('td', U.value(sample));
      dateCell.append(sample.observed_at ? U.button(U.date(sample.observed_at), () => onSample(sample)) : U.el('span', 'Czas nieznany')); row.append(dateCell, value, U.el('td', sample.revision || 1)); tbody.append(row);}
    table.append(tbody); const scroll = U.el('div', null, 'analysis-samples-scroll'); scroll.append(table); parent.append(scroll);
    if (samples.length > 100) parent.append(U.el('small', `Tabela: 100 najnowszych z ${samples.length} odczytanych próbek. Wykres obejmuje wszystkie odczytane punkty.`));
  }
  function render(detail, timeline, state, sample, {inScope = true, loading = false, error = null, selectedIndex = null} = {}) {
    host.hidden = !state.detailOpen; if (!state.detailOpen) return;
    outside.hidden = inScope;
    const object = detail?.object || detail, key = [state.selectedRef, state.selectedVersion, state.selectedSensor, state.selectedMetric].join('|');
    if (!object || object.ref !== state.selectedRef) {
      title.textContent = loading ? 'Wczytywanie obiektu…' : 'Obiekt niedostępny'; body.replaceChildren(U.el('p', error || 'Pobieranie zapisanych danych…', 'muted')); lastKey = ''; return;
    }
    if (lastKey !== key || lastDetail !== detail || lastTimeline !== timeline || lastError !== error) {
      lastKey = key; lastDetail = detail; lastTimeline = timeline; lastError = error;
      title.textContent = object.label; body.replaceChildren(); reading = readingTime = readingNote = readingClocks = officialIndexNode = null;
      const meta = U.el('p', `${U.typeNames[object.type]} · ${object.source_id}`, 'analysis-card-type'); body.append(meta);
      body.append(U.button('Pokaż na mapie', () => actions.show(object)));
      if (error) body.append(U.el('p', `${error} Zachowano ostatni zapisany odczyt.`, 'notice'));
      const data = section(body, 'Dane');
      dl(data, [['Identyfikator', object.ref], ['Dostępność', U.statusNames[object.availability] || object.availability || 'Dostępne'], ['Aktualność', U.statusNames[object.freshness] || object.freshness || 'Według czasu źródła']]);
      if (!Number.isFinite(object.latitude) && !(object.areas || object.area_refs || []).length) data.append(U.el('p', 'Brak ustalonej geometrii. Obiekt jest dostępny w katalogu.', 'muted'));
      if (object.type === 'communication') {
        const communication = detail.communication || {}, versions = detail.versions || communication.history || [], selected = versions.find(version => String(version.id || version.version_id || version.version_number) === String(state.selectedVersion));
        if (selected) data.append(U.el('p', `Wersja źródłowa ${selected.version_number || selected.id}`, 'notice'));
        dl(data, [['Publikacja', U.date(object.date_precision === 'day' || object.time_precision === 'day' ? communication.source_published_date || object.metadata?.source_published_date || String(object.published_at || '').slice(0, 10) : object.published_at || communication.source_published_at || communication.source_published_date)], ['Ważność od', U.date(object.valid_from || communication.valid_from)], ['Ważność do', U.date(object.valid_until || communication.valid_until)], ['Udostępnianie RSO od', U.date(object.display_from || communication.display_from)], ['Udostępnianie RSO do', U.date(object.display_until || communication.display_until)]]);
        data.append(U.el('div', selected?.text || communication.text || object.metadata?.text || 'Brak treści w zapisanym materiale.', 'document-text'));
        const history = section(body, 'Historia wersji');
        for (const version of versions) history.append(U.button(`Wersja ${version.version_number || version.id} · ${U.date(version.created_at || version.source_updated_at)}`, () => actions.version(version.id || version.version_id || version.version_number)));
        if (!versions.length) history.append(U.el('p', 'Brak dodatkowych zapisanych wersji.', 'muted'));
        for (const event of timeline?.items || []) {if (event.kind === 'version') continue; history.append(U.el('p', `${({publication: 'Publikacja', update: 'Aktualizacja', validity: 'Okres ważności', display: 'Okres udostępniania'})[event.kind] || event.kind} · ${U.date(event.date_precision === 'day' ? event.source_date : event.at || event.observed_at)}`, 'muted'));}
      } else if (object.type === 'area') {
        dl(data, [['Kod PRG', object.native_id || object.source_object_id || object.ref.split(':').at(-1)], ['Charakter', 'Bezczasowy obszar referencyjny']]);
        const code = String(object.native_id || object.source_object_id || object.ref.split(':').at(-1));
        data.append(U.button('Komunikaty tego województwa', () => actions.region(code.slice(0, 2))));
      } else {
        if (object.type === 'hydro_station') {
          const metric = U.el('select'); metric.id = 'analysis-metric';
          for (const [id, label] of Object.entries(U.metricNames)) {const option = U.el('option', label); option.value = id; metric.append(option);} metric.value = state.selectedMetric || 'water_level';
          metric.addEventListener('change', () => actions.sensor(null, metric.value)); data.append(U.field('Parametr wodowskazu', metric));
          data.append(U.el('p', 'Stan wody ma lokalny poziom odniesienia wodowskazu. Nie porównuj go jak wysokości nad poziomem morza.', 'muted'));
        } else {
          const sensors = detail.sensors || object.metadata?.sensors || [], select = U.el('select'); select.id = 'analysis-sensor'; select.append(U.el('option', 'Wybierz stanowisko'));
          select.firstChild.value = '';
          for (const sensor of sensors) {const option = U.el('option', `${sensor.parameter || sensor.metric || sensor.name || 'Parametr'} · stanowisko ${sensor.id || sensor.sensor_id}`); option.value = sensor.id || sensor.sensor_id; option.dataset.metric = sensor.parameter || sensor.metric || ''; select.append(option);}
          select.value = state.selectedSensor || ''; select.addEventListener('change', () => actions.sensor(select.value, select.selectedOptions[0]?.dataset.metric)); data.append(U.field('Stanowisko pomiarowe GIOŚ', select));
          const index = detail.official_index || object.official_index || detail.index || object.metadata?.index;
          officialIndexNode = U.el('p', index ? `Oficjalny indeks ogólny: ${index.name || (index.value ?? 'brak')} · ${U.date(index.observed_at)}` : 'Brak zapisanego oficjalnego indeksu ogólnego.', 'muted'); data.append(officialIndexNode);
          data.append(U.el('p', 'Wybrana substancja nie zmienia koloru oficjalnego indeksu ogólnego stacji. Stanowiska nie są scalane.', 'muted'));
        }
        reading = U.el('strong', '', 'analysis-reading'); readingTime = U.el('p', '', 'muted'); readingNote = U.el('p', '', 'muted'); readingClocks = U.el('p', '', 'muted'); data.append(reading, readingTime, readingNote, readingClocks);
        data.append(U.button('Pobierz dostępne dane źródłowe', () => actions.fetchSource(object)));
        const allMeasurements = Array.isArray(detail.measurements) ? detail.measurements : [];
        if (allMeasurements.length > 1 && !state.cursorAt) {const current = section(data, 'Zapisane parametry');
          for (const row of allMeasurements) current.append(U.el('p', `${U.metricNames[row.metric] || row.metric || 'Pomiar'} · ${U.value(row)} · ${U.date(row.observed_at)}`, 'muted'));}
        const history = section(body, 'Historia pomiarów'), selectedSamples = (timeline?.items || []).filter(item => (!item.kind || item.kind === 'measurement') && (object.type !== 'air_quality_station' || Boolean(state.selectedSensor)) && (!state.selectedSensor || String(item.sensor_id) === String(state.selectedSensor)) && (!state.selectedMetric || item.metric === state.selectedMetric));
        if (object.type === 'air_quality_station' && !state.selectedSensor) history.append(U.el('p', 'Wybierz stanowisko pomiarowe, aby zobaczyć jego osobny szereg.', 'muted'));
        else drawSeries(history, selectedSamples, actions.sample);
        if (timeline?.next_cursor || timeline?.official_indices_next_cursor) history.append(U.el('p', 'Historia częściowa — wczytaj kolejne próbki, aby włączyć dokładny kursor czasu.', 'notice'));
        if (timeline?.next_cursor || timeline?.official_indices_next_cursor) history.append(U.button('Wczytaj kolejne zapisane próbki', actions.moreHistory));
        if (timeline?.coverage) history.append(U.el('p', typeof timeline.coverage === 'string' ? timeline.coverage : `Zakres historii: ${U.date(timeline.coverage.from)} – ${U.date(timeline.coverage.to)}. Odczyty na żądanie; możliwe luki.`, 'muted'));
      }
      const provenance = section(body, 'Pochodzenie'), source = detail.selected_measurement?.provenance || object.measurement?.provenance || object.provenance || object.metadata?.provenance || {};
      dl(provenance, [['Źródło', source.attribution || object.source_id], ['Odczyt źródła', U.date(detail.selected_measurement?.fetched_at || object.measurement?.fetched_at || object.fetched_at || source.fetched_at)], ['Stan zestawu', U.date(state.asOf)], ['Geometria', object.type.endsWith('_station') ? 'Ostatnie zapisane metadane; bez odtwarzania dawnych lokalizacji' : 'Lokalne granice PRG / GUGiK']]);
      const link = U.safeLink(source.url || source.source_url || detail.communication?.source_url || detail.communication?.original_url || object.metadata?.source_url); if (link) provenance.append(link);
      if (object.source_id?.includes('imgw')) provenance.append(U.el('p', 'Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy. Dane Instytutu zostały przetworzone.', 'muted'));
    }
    if (officialIndexNode) officialIndexNode.textContent = selectedIndex ? `Oficjalny indeks ogólny: ${selectedIndex.name || (selectedIndex.value ?? 'brak')} · ${U.date(selectedIndex.observed_at)}${state.cursorAt ? ' · Według kursora' : ''}` : 'Brak zapisanego oficjalnego indeksu dla tego czasu.';
    if (reading) {
      const chosen = detail._detailRevision !== state.detailRevision || detail._queryRevision !== state.queryRevision ? null : sample || (!state.cursorAt && (object.type !== 'air_quality_station' || state.selectedSensor) ? U.measurement(object) : null); reading.textContent = loading ? 'Odświeżanie…' : U.value(chosen);
      readingTime.textContent = `${state.cursorAt ? 'Według kursora' : state.query.time.mode === 'range' ? 'Przegląd okresu' : 'Ostatni zapisany pomiar'} · ${U.date(chosen?.observed_at)}`;
      if (state.cursorAt && chosen?.observed_at) {const age = Math.max(0, Math.round((Date.parse(state.cursorAt) - Date.parse(chosen.observed_at)) / 60000)); readingTime.textContent += ` · wiek przy kursorze: ${age} min${age > 180 ? ' · nieaktualny' : ''}`;}
      readingNote.textContent = state.cursorAt && !chosen ? 'Brak zapisanego pomiaru przed kursorem w tym przedziale.' : chosen?.thresholds && Object.values(chosen.thresholds).some(value => value != null) ? `Próg dostępny przy odczycie: ostrzegawczy ${chosen.thresholds.warning_level_cm ?? 'brak'} cm; alarmowy ${chosen.thresholds.alarm_level_cm ?? 'brak'} cm.` : 'Brak zapisanej podstawy historycznego porównania progów. Dane mogą zawierać luki.';
      if (readingClocks) readingClocks.textContent = chosen ? `Odczyt źródła: ${U.date(chosen.fetched_at)} · czas źródłowy: ${chosen.source_time || 'nie podano'} · rewizja ${chosen.revision || 1}` : '';
    }
  }
  return {render, focus: () => title.focus()};
};
