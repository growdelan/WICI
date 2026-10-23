'use strict';
/* Alarm intervals are observations, never an inferred all-clear between reads. */
(function (root) {
  const stateNames = {red: 'Alarm aktywny', yellow: 'Ostrzeżenie / częściowy alarm', none: 'Brak alarmu według odczytu', unknown: 'Luka w obserwacji'};
  const colors = {red: '#b64046', yellow: '#c3982e', none: '#b3c6ca', unknown: '#73808b'};
  const objectState = object => object?.alert_state || object?.state || object?.metadata?.state || 'unknown';
  function frameAt(series, cursorAt, range) {
    const at = Date.parse(cursorAt || range?.to) - (cursorAt ? 0 : 1);
    if (!range || !Number.isFinite(at) || at < Date.parse(range.from) || at >= Date.parse(range.to)) return {state: 'unknown', segment: null};
    const segment = (series?.segments || []).find(item => Date.parse(item.from) <= at && Date.parse(item.to) > at);
    return {state: Object.hasOwn(stateNames, segment?.state) ? segment.state : 'unknown', segment: segment || null};
  }
  function duration(seconds) {
    if (!Number.isFinite(seconds)) return 'Brak danych';
    const minutes = Math.floor(Math.max(0, seconds) / 60);
    return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : minutes ? `${minutes} min` : `${Math.round(Math.max(0, seconds))} s`;
  }
  function view(host, {remove, clear, select, range, cursor, fit}) {
    const U = root.WiciWorkspaceUI, box = U.el('section', null, 'analysis-alerts'); box.id = 'analysis-alerts';
    const heading = U.el('div', null, 'analysis-motion-heading'); heading.append(U.el('h3', 'Ukraina · porównanie historii regionów'));
    const day = U.button('Porównaj ostatnie 24 h', range); day.id = 'analysis-alerts-day';
    const show = U.button('Pokaż regiony na mapie', fit); show.id = 'analysis-fit-regions';
    heading.append(day, show, U.button('Wyczyść regiony', clear));
    const chips = U.el('div', null, 'analysis-compare-chips'), note = U.el('p', '', 'analysis-timeline-note'); note.id = 'analysis-alerts-status'; note.setAttribute('role', 'status');
    const legend = U.el('div', null, 'analysis-alert-legend');
    for (const [state, label] of Object.entries(stateNames)) {const item = U.el('span', label); item.dataset.alertState = state; legend.append(item);}
    const lanes = U.el('div', null, 'analysis-alert-lanes'); lanes.id = 'analysis-alert-lanes';
    const scroll = U.el('div', null, 'analysis-comparison-scroll'), table = U.el('table'); table.id = 'analysis-region-comparison';
    const thead = U.el('thead'), tr = U.el('tr');
    for (const label of ['Region', 'Stan przy kursorze', 'Epizody', 'Zaobserwowany czas alarmu', 'Najdłuższy znany ciągły alarm', 'Pokrycie zapisu']) {const th = U.el('th', label); th.scope = 'col'; tr.append(th);} thead.append(tr);
    const body = U.el('tbody'); table.append(thead, body); scroll.append(table);
    const attribution = U.el('p', 'Źródło alarmów i granic: ', 'analysis-timeline-note'), sourceLink = U.safeLink('https://neptun.in.ua/', 'NEPTUN'); if (sourceLink) attribution.append(sourceLink); else attribution.append(U.el('span', 'NEPTUN'));
    box.append(heading, chips, note, legend, lanes, attribution, scroll, U.el('p', 'Historia od rozpoczęcia rejestracji · retencja 30 dni. Kreskowanie oznacza brak obserwacji. Czasy opisują zapisany zakres, a brak alarmu w odczycie nie potwierdza bezpieczeństwa. Statystyki regionów liczone osobno; nie sumuj obwodu z jego rejonami.', 'analysis-timeline-note')); host.append(box);
    let lastData, lastKey = ''; const rows = new Map(), laneCursors = [];
    return {render(state, context) {
      const refs = state.comparedRegionRefs || [], selectedRange = state.query.time.filter_range, replay = context?.data;
      box.hidden = !refs.length; if (box.hidden) return;
      day.hidden = Boolean(selectedRange); show.disabled = !refs.some(ref => (replay?.series || []).find(item => item.ref === ref)?.geometry || context?.regions?.find(item => item.ref === ref)?.geometry);
      const key = JSON.stringify([refs, selectedRange, state.displayTimezone, refs.map(ref => context?.labels?.get(ref))]);
      if (lastData !== replay || lastKey !== key) {
        lastData = replay; lastKey = key; chips.replaceChildren(); lanes.replaceChildren(); body.replaceChildren(); rows.clear(); laneCursors.length = 0;
        for (const ref of refs) {
          const series = replay?.series?.find(item => item.ref === ref), label = series?.label || context?.labels?.get(ref) || ref;
          const chip = U.el('span', null, 'analysis-compare-chip'); chip.append(U.button(label, () => select(ref)), U.button('×', () => remove(ref))); chip.lastChild?.setAttribute('aria-label', `Usuń ${label} z porównania`); chips.append(chip);
          const lane = U.el('div', null, 'analysis-alert-lane'), name = U.button(label, () => select(ref), 'analysis-alert-lane-label'), track = U.el('div', null, 'analysis-alert-track'); lane.dataset.ref = ref;
          if (selectedRange && series) {
            const from = Date.parse(selectedRange.from), to = Date.parse(selectedRange.to), span = Math.max(1, to - from);
            for (const segment of series.segments || []) {
              const lower = Math.max(from, Date.parse(segment.from)), upper = Math.min(to, Date.parse(segment.to)); if (!(upper > lower)) continue;
              const control = U.button('', () => {cursor(new Date(lower).toISOString()); if (segment.episode_ref) select(segment.episode_ref);}, 'analysis-alert-segment'); control.dataset.alertState = segment.state; control.dataset.episodeRef = segment.episode_ref || '';
              control.style.setProperty('left', `${100 * (lower - from) / span}%`); control.style.setProperty('width', `${100 * (upper - lower) / span}%`);
              control.title = `${label} · ${stateNames[segment.state] || stateNames.unknown} · ${U.date(segment.from)} – ${U.date(segment.to)}`; control.setAttribute('aria-label', control.title); track.append(control);
            }
            const indicator = U.el('span', null, 'analysis-alert-cursor'); indicator.setAttribute('aria-hidden', 'true'); track.append(indicator); laneCursors.push(indicator);
          }
          lane.append(name, track); lanes.append(lane);
          const row = U.el('tr'), nameCell = U.el('td'), current = U.el('td'), stats = series?.stats || {}, coverage = U.el('td'); row.dataset.ref = ref; nameCell.append(U.button(label, () => select(ref)));
          const ratio = stats.coverage_ratio; coverage.textContent = Number.isFinite(ratio) ? `${(ratio * 100).toFixed(1)}% · ${duration(stats.covered_seconds)}${ratio < 1 ? ' · niepełne' : ''}` : 'Brak zapisu';
          row.append(nameCell, current, U.el('td', stats.episode_count ?? '—'), U.el('td', duration(stats.alarm_seconds)), U.el('td', duration(stats.longest_alarm_seconds)), coverage); body.append(row); rows.set(ref, {row, current});
        }
      }
      note.textContent = !selectedRange ? `${refs.length} / 5 regionów. Wybierz przedział, aby odtworzyć lokalny zapis.` : context?.loading ? 'Wczytywanie zapisanej historii alarmów…' : context?.error ? `Nie udało się pobrać historii: ${context.error}` : `${refs.length} / 5 regionów · ${U.date(selectedRange.from)} – ${U.date(selectedRange.to)} · ${state.displayTimezone || 'Europe/Warsaw'}`;
      for (const ref of refs) {const entry = rows.get(ref), frame = context?.frames?.get(ref); if (entry) {entry.row.dataset.alertState = frame?.state || 'unknown'; entry.current.textContent = context?.loading ? 'Wczytywanie…' : !selectedRange ? 'Wybierz przedział' : stateNames[frame?.state] || stateNames.unknown;}}
      if (selectedRange) {const at = Date.parse(state.cursorAt || selectedRange.to) - (state.cursorAt ? 0 : 1), position = 100 * (at - Date.parse(selectedRange.from)) / Math.max(1, Date.parse(selectedRange.to) - Date.parse(selectedRange.from)); for (const line of laneCursors) line.style.setProperty('left', `${position}%`);}
    }};
  }
  const exported = {stateNames, colors, objectState, frameAt, duration, view}; root.WiciWorkspaceAlerts = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(typeof window !== 'undefined' ? window : globalThis);
