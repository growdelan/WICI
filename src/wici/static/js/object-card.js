'use strict';
window.WiciObjectCard = function (host, actions) {
  const U = window.WiciWorkspaceUI, M = window.WiciWorkspaceMotion, A = window.WiciWorkspaceAlerts, heading = U.el('div', null, 'analysis-card-heading'), title = U.el('h2', 'Szczegóły obiektu');
  title.id = 'analysis-card-title'; title.tabIndex = -1; host.setAttribute('aria-labelledby', title.id);
  const close = U.button('Zamknij ×', actions.close); close.id = 'analysis-close-card'; heading.append(title, close);
  const outside = U.el('p', 'Poza bieżącym zakresem. Karta zachowuje wybrany obiekt.', 'notice'), body = U.el('div', null, 'analysis-card-body');
  outside.id = 'analysis-outside-range'; host.append(heading, outside, body);
  let lastKey = '', lastDetail = null, lastTimeline = null, reading, readingTime, readingNote, readingClocks, officialIndexNode, lastError = '', movingNodes = null, alertNodes = null;
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
  function render(detail, timeline, state, sample, {inScope = true, loading = false, error = null, selectedIndex = null, motion = null, alerts = null} = {}) {
    host.hidden = !state.detailOpen; if (!state.detailOpen) return;
    outside.hidden = inScope;
    const object = detail?.object || detail, key = [state.selectedRef, state.selectedVersion, state.selectedSensor, state.selectedMetric].join('|');
    if (!object || object.ref !== state.selectedRef) {
      title.textContent = loading ? 'Wczytywanie obiektu…' : 'Obiekt niedostępny'; body.replaceChildren(U.el('p', error || 'Pobieranie zapisanych danych…', 'muted')); lastKey = ''; return;
    }
    if (lastKey !== `${key}|${state.displayTimezone || ''}` || lastDetail !== detail || lastTimeline !== timeline || lastError !== error) {
      lastKey = `${key}|${state.displayTimezone || ''}`; lastDetail = detail; lastTimeline = timeline; lastError = error;
      title.textContent = object.label; body.replaceChildren(); reading = readingTime = readingNote = readingClocks = officialIndexNode = movingNodes = alertNodes = null;
      const meta = U.el('p', `${U.typeNames[object.type]} · ${object.source_id}`, 'analysis-card-type'); body.append(meta);
      body.append(U.button('Pokaż na mapie', () => actions.show(object)));
      if (actions.pin && actions.capture) {
        const dossierActions = U.el('div', null, 'analysis-dossier-card-actions');
        const pin = U.button('Przypnij do teczki', actions.pin), capture = U.button('Zapisz kartę w teczce', actions.capture);
        pin.id = 'analysis-pin-object'; capture.id = 'analysis-save-object'; dossierActions.append(pin, capture); body.append(dossierActions);
      }
      if (error) body.append(U.el('p', `${error} Zachowano ostatni zapisany odczyt.`, 'notice'));
      const data = section(body, 'Dane');
      dl(data, [['Identyfikator', object.ref], ['Dostępność', U.statusNames[object.availability] || object.availability || 'Dostępne'], ['Aktualność', U.statusNames[object.freshness] || object.freshness || 'Według czasu źródła']]);
      if (!object.geometry && !Number.isFinite(object.latitude) && !(object.areas || object.area_refs || []).length) data.append(U.el('p', 'Brak ustalonej geometrii. Obiekt jest dostępny w katalogu.', 'muted'));
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
      } else if (object.type === 'ua_region' || object.type === 'civil_alert') {
        const history = detail.ukraine || {}, metadata = object.metadata || {}, isRegion = object.type === 'ua_region', regionRef = isRegion ? object.ref : object.region_ref || metadata.region_ref || history.region_ref;
        const controls = U.el('div', null, 'analysis-moving-actions'); let watch = null, compare = null;
        if (isRegion) {watch = U.button('Obserwuj ☆', () => actions.watch(object)); watch.id = 'analysis-watch-object'; compare = U.button('Dodaj do porównania', () => actions.compare(object.ref)); compare.id = 'analysis-compare-object'; controls.append(watch, compare);}
        else if (regionRef) {controls.append(U.button('Otwórz region', () => actions.select(regionRef)), U.button('Porównaj historię regionu', () => actions.compare(regionRef)));}
        controls.append(U.button('Pobierz bieżący odczyt alarmów', () => actions.fetchSource(object))); data.append(controls);
        const current = U.el('strong', '', 'analysis-reading'), quality = U.el('p', '', 'muted'); data.append(current, quality);
        dl(data, isRegion ? [['Zakres', metadata.scope === 'raion' ? 'Rejon' : 'Obwód'], ['Nazwa źródłowa', metadata.native_key || object.native_id], ['Obwód', metadata.oblast || object.label]] : [['Region', regionRef], ['Początek według źródła', U.date(metadata.source_since)], ['Pierwsza obserwacja WICI', U.date(metadata.first_seen_at)], ['Ostatnia obserwacja z alarmem', U.date(metadata.last_seen_at)], ['Zakończenie po', U.date(metadata.ended_after)], ['Zakończenie nie później niż', U.date(metadata.ended_before)]]);
        if (!isRegion) data.append(U.el('p', metadata.ended_before ? 'Koniec alarmu zaobserwowano między ostatnim poprawnym odczytem z alarmem a pierwszym odczytem bez niego. Dokładna chwila zakończenia pozostaje nieznana.' : 'Nie zarejestrowano potwierdzonego zakończenia tego epizodu. Brak nowych odczytów nie oznacza końca alarmu.', 'muted'));
        const stats = history.stats;
        if (stats) {const sectionStats = section(body, 'Statystyki zapisanego przedziału'); dl(sectionStats, [['Epizody', stats.episode_count], ['Zaobserwowany czas alarmu', A.duration(stats.alarm_seconds)], ['Najdłuższy znany ciągły alarm', A.duration(stats.longest_alarm_seconds)], ['Pokrycie rejestracji', Number.isFinite(stats.coverage_ratio) ? `${(stats.coverage_ratio * 100).toFixed(1)}%${stats.coverage_ratio < 1 ? ' · niepełne' : ''}` : 'Brak danych'], ['Luki', A.duration(stats.unknown_seconds)]]);}
        const episodes = section(body, 'Zarejestrowane epizody');
        for (const episode of history.episodes || []) {const entry = U.el('div', null, 'analysis-track-session');
          entry.append(U.button(`${A.stateNames[episode.level] || 'Alarm'} · ${U.date(episode.source_since || episode.first_seen_at)}`, () => actions.select(episode.ref || episode.episode_ref)));
          entry.append(U.el('p', `Obserwacje: ${U.date(episode.first_seen_at)} – ${U.date(episode.last_seen_at)}${episode.ended_before ? ` · zakończenie w przedziale ${U.date(episode.ended_after)} – ${U.date(episode.ended_before)}` : ' · zakończenie niepotwierdzone'}`, 'muted')); episodes.append(entry);
        }
        if (!history.episodes?.length) episodes.append(U.el('p', 'Brak zarejestrowanych epizodów w tym zakresie. Sprawdź pokrycie przed interpretacją wyniku.', 'muted'));
        const revisions = section(body, 'Zmiany i obserwacje źródła'), entries = history.revisions || timeline?.items || [];
        for (const entry of entries.slice(-100).reverse()) revisions.append(U.el('p', `${U.date(entry.observed_at || entry.at)} · ${A.stateNames[entry.state] || entry.state || 'Zmiana'} · początek źródłowy: ${U.date(entry.source_since)}`, 'muted'));
        if (!entries.length) revisions.append(U.el('p', 'Brak zapisanych zmian.', 'muted'));
        if (entries.length > 100) revisions.append(U.el('p', 'Pokazano 100 najnowszych zmian. Zawęź przedział, aby przejrzeć pozostałe.', 'notice'));
        revisions.append(U.el('p', 'Awaria źródła i przerwa w działaniu WICI tworzą lukę. Czas źródłowy jest oddzielony od czasu obserwacji. Obserwowanie regionu nie włącza rejestracji.', 'muted'));
        alertNodes = {watch, compare, current, quality, isRegion};
      } else if (M?.isMoving(object)) {
        const metadata = object.metadata || {}, sessions = detail.track_sessions || [];
        const watch = U.button('Obserwuj ☆', () => actions.watch(object)); watch.id = 'analysis-watch-object';
        const compare = U.button('Dodaj do porównania', () => actions.compare(object.ref)); compare.id = 'analysis-compare-object';
        const start = U.button('Rozpocznij zapis trasy', () => actions.record(object)); start.id = 'analysis-start-recording';
        const actionsRow = U.el('div', null, 'analysis-moving-actions'); actionsRow.append(watch, compare, start); data.append(actionsRow);
        dl(data, object.type === 'aircraft' ? [['ICAO', object.native_id || object.ref.split(':').at(-1)], ['Rejestracja', metadata.registration], ['Znak wywoławczy', metadata.callsign], ['Typ samolotu', metadata.type_code], ['Klasyfikacja źródła', metadata.military == null ? 'Nie podano' : metadata.military ? 'Wojskowy według źródła' : 'Pozostałe według źródła']] : [['MMSI', object.native_id || object.ref.split(':').at(-1)], ['IMO', metadata.imo], ['Typ jednostki AIS', metadata.type_code], ['Deklarowany cel', metadata.destination]]);
        data.append(U.el('p', 'Identyfikatory i metadane pochodzą z ostatniego odczytu źródła. Historia pozycji nie odtwarza dawnych metadanych ani nie potwierdza tożsamości operatora.', 'muted'));
        const position = section(body, 'Pozycja i ruch'), values = U.el('div'), quality = U.el('p', '', 'muted'); position.append(values, quality);
        position.append(U.button('Pobierz bieżący odczyt źródła', () => actions.fetchSource(object)));
        if (object.last_known_position && !object.position) position.append(U.el('p', `Ostatni znany raport: ${U.date(object.last_known_position.position_at)}. Brak świeżej pozycji; nie pokazujemy go jako pozycji bieżącej.`, 'notice'));
        const history = section(body, 'Sesje zapisu'), stops = [];
        history.append(U.el('p', 'Obserwowanie zapisuje obiekt na liście. Zapis trasy działa osobno i zbiera kolejne raporty od chwili uruchomienia. Retencja: 7 dni.', 'muted'));
        for (const session of sessions) {const entry = U.el('div', null, 'analysis-track-session'); entry.dataset.trackId = session.id;
          entry.append(U.el('strong', `${session.active ? '● Zapis trwa' : 'Zapis zakończony'} · ${U.date(session.started_at)}`), U.el('p', `${session.point_count || 0} raportów · ${U.date(session.first_position_at)} – ${U.date(session.last_position_at)}`, 'muted'));
          const replay = U.button('Odtwórz tę sesję', () => actions.replaySession(session, object.ref)); replay.disabled = !session.point_count; entry.append(replay);
          if (session.active) {const stop = U.button('Zatrzymaj zapis', () => actions.record(object, session.id)); stop.dataset.stopTrack = session.id; stops.push(stop); entry.append(stop);}
          history.append(entry);
        }
        if (!sessions.length) history.append(U.el('p', 'Nie ma zapisanych sesji tego obiektu. Rozpocznij zapis, aby zbudować historię.', 'muted'));
        movingNodes = {watch, compare, start, values, quality, active: sessions.some(session => session.active), stops};
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
      dl(provenance, [['Źródło', source.attribution || object.metadata?.source_name || object.source_id], ['Odczyt źródła', U.date(detail.selected_measurement?.fetched_at || object.measurement?.fetched_at || object.fetched_at || source.fetched_at)], ['Stan zestawu', U.date(state.asOf)], ['Geometria', ['ua_region', 'civil_alert'].includes(object.type) ? 'Bieżące granice NEPTUN. Dawne wersje granic nie są odtwarzane.' : M?.isMoving(object) ? 'Raporty pozycji ADS-B / AIS. Zakres czasu pochodzi z lokalnego zapisu sesji.' : object.type.endsWith('_station') ? 'Ostatnie zapisane metadane; bez odtwarzania dawnych lokalizacji' : 'Lokalne granice PRG / GUGiK']]);
      const link = U.safeLink(source.url || source.source_url || detail.communication?.source_url || detail.communication?.original_url || object.metadata?.source_url); if (link) provenance.append(link);
      if (object.source_id?.includes('imgw')) provenance.append(U.el('p', 'Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy. Dane Instytutu zostały przetworzone.', 'muted'));
    }
    if (alertNodes) {
      const compared = state.comparedRegionRefs?.includes(object.ref), watched = alerts?.watched ? alerts.watched.has(object.ref) : object.watched;
      if (alertNodes.watch) {alertNodes.watch.textContent = watched ? 'Obserwowany ★' : 'Obserwuj ☆'; alertNodes.watch.setAttribute('aria-pressed', String(Boolean(watched))); alertNodes.watch.disabled = Boolean(alerts?.busy?.has(object.ref));}
      if (alertNodes.compare) {alertNodes.compare.textContent = compared ? 'Usuń z porównania' : 'Dodaj do porównania'; alertNodes.compare.setAttribute('aria-pressed', String(Boolean(compared))); alertNodes.compare.disabled = !compared && (state.comparedRegionRefs?.length || 0) >= 5;}
      const historical = state.query.time.mode === 'range', frame = alerts?.frames?.get(alertNodes.isRegion ? object.ref : object.region_ref || object.metadata?.region_ref), current = detail._detailRevision === state.detailRevision && detail._queryRevision === state.queryRevision;
      const status = historical ? !frame || frame.state === 'unknown' ? 'unknown' : alertNodes.isRegion || frame.segment?.episode_ref === object.ref ? frame.state : 'none' : current ? A.objectState(object) : 'unknown';
      alertNodes.current.textContent = !current && !historical ? 'Odświeżanie stanu regionu…' : A.stateNames[status] || A.stateNames.unknown;
      alertNodes.current.dataset.alertState = status;
      alertNodes.quality.textContent = historical ? frame ? `Według wspólnego kursora · ${U.date(state.cursorAt || new Date(Date.parse(state.query.time.filter_range?.to) - 1).toISOString())}` : 'Dodaj region do porównania, aby zsynchronizować stan z kursorem.' : `Stan według źródła · ${U.date(object.fetched_at)} · ${U.statusNames[object.source_status] || object.source_status || 'Brak odczytu'}`;
    }
    if (movingNodes) {
      const watched = motion?.watched ? motion.watched.has(object.ref) : object.watched, compared = state.comparedRefs.includes(object.ref), busy = motion?.busy?.has(object.ref);
      movingNodes.watch.textContent = watched ? 'Obserwowany ★' : 'Obserwuj ☆'; movingNodes.watch.setAttribute('aria-pressed', String(Boolean(watched))); movingNodes.watch.disabled = Boolean(busy);
      movingNodes.compare.textContent = compared ? 'Usuń z porównania' : 'Dodaj do porównania'; movingNodes.compare.setAttribute('aria-pressed', String(compared)); movingNodes.compare.disabled = !compared && state.comparedRefs.length >= 5;
      movingNodes.start.textContent = movingNodes.active ? 'Zapis trwa' : 'Rozpocznij zapis trasy';
      movingNodes.start.disabled = Boolean(busy || movingNodes.active); for (const stop of movingNodes.stops) stop.disabled = Boolean(busy);
      const historical = state.query.time.mode === 'range', frame = motion?.frames?.get(object.ref), current = detail._detailRevision === state.detailRevision && detail._queryRevision === state.queryRevision;
      const position = historical ? frame?.point : current ? object.position : null;
      movingNodes.values.replaceChildren();
      if (!historical && !current) movingNodes.values.append(U.el('p', loading || !error ? 'Odświeżanie pozycji dla aktualnego zestawu…' : 'Pozycja wymaga ponownego odczytu spójnego zestawu. Użyj „Odśwież zestaw”.', 'muted'));
      else dl(movingNodes.values, [['Czas raportu', U.date(position?.position_at || position?.at)], ['Szerokość', Number.isFinite(position?.latitude) ? position.latitude.toFixed(5) : 'Brak pozycji'], ['Długość', Number.isFinite(position?.longitude) ? position.longitude.toFixed(5) : 'Brak pozycji'], ['Prędkość', M.number(position?.speed_kmh, 'km/h')], ...(object.type === 'aircraft' ? [['Wysokość', M.number(position?.altitude_m, 'm')]] : []), ['Kurs', M.number(position?.heading, '°')]]);
      movingNodes.quality.textContent = historical ? `Według wspólnego kursora · ${M.describe(frame, U)}` : !current ? 'Szczegóły pochodzą z poprzedniego zestawu; trwa uzgadnianie z katalogiem.' : `${U.statusNames[object.freshness] || object.freshness || 'Czas nieznany'} · status źródła: ${U.statusNames[object.source_status] || object.source_status || 'nie podano'}`;
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
