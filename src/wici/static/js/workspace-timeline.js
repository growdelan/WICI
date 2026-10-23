'use strict';
window.WiciWorkspaceTimeline = (() => {
  const U = window.WiciWorkspaceUI;
  function localValue(value) {
    if (!value) return ''; const date = new Date(value); if (!Number.isFinite(date.getTime())) return '';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Warsaw', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }
  // Round-trip candidate offsets: reject nonexistent local hours at the spring DST transition.
  function toUTC(value) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
    const raw = Date.parse(`${value}Z`);
    for (const offset of [120, 60]) {const candidate = new Date(raw - offset * 60000).toISOString(); if (localValue(candidate) === value) return candidate;}
    return null;
  }
  function create(host, {dispatch, getState, now}) {
    const heading = U.el('div', null, 'analysis-time-heading'), title = U.el('h2', 'Czas analizy'), mode = U.el('span', 'Bieżące');
    mode.id = 'analysis-time-mode'; heading.append(title, mode);
    const live = U.button('Bieżące', () => dispatch({type: 'RETURN_TO_LIVE'})), lastDay = U.button('Ostatnie 24 godziny', () => {
      const end = new Date(now()).getTime(); const range = {from: new Date(end - 86400000).toISOString(), to: new Date(end).toISOString()}; dispatch({type: 'SET_TIME_RANGE', range});
    }); heading.append(live, lastDay);
    const form = U.el('form', null, 'analysis-time-fields'), from = U.el('input'), to = U.el('input');
    from.type = to.type = 'datetime-local'; from.id = 'analysis-time-from'; to.id = 'analysis-time-to'; from.required = to.required = true; from.title = to.title = 'Czas Europe/Warsaw. Dla powtórzonej jesiennej godziny wybieramy wcześniejsze wystąpienie.';
    const apply = U.button('Ustaw przedział'); apply.type = 'submit';
    form.append(U.field('Od · Warszawa', from), U.field('Do · wyłącznie', to), apply);
    const message = U.el('p', '', 'analysis-message'); message.setAttribute('role', 'status');
    form.addEventListener('submit', event => {event.preventDefault(); const lower = toUTC(from.value), upper = toUTC(to.value);
      if (!lower || !upper || lower >= upper) {message.textContent = 'Podaj poprawny przedział. Nieistniejąca godzina zmiany czasu jest odrzucana.'; return;}
      const previous = getState().query.time.overview_range;
      const range = {from: lower, to: upper}, overview = previous && lower >= previous.from && upper <= previous.to ? previous : range;
      message.textContent = ''; dispatch({type: 'SET_TIME_RANGE', range, overview});
    });
    const histogram = U.el('div', null, 'analysis-histogram'); histogram.id = 'analysis-histogram'; histogram.setAttribute('aria-label', 'Zdarzenia w tle przedziału; wybierz koszyk, aby zawęzić zakres');
    const note = U.el('p', '', 'analysis-timeline-note');
    const cursorBox = U.el('div', null, 'analysis-cursor'), cursor = U.el('input'), cursorDate = U.el('input'), cursorOutput = U.el('output');
    cursor.type = 'range'; cursor.min = '0'; cursor.max = '1000'; cursor.step = '1'; cursor.id = 'analysis-cursor'; cursor.setAttribute('aria-label', 'Wspólny kursor czasu stacji i porównywanych tras');
    cursorDate.type = 'datetime-local'; cursorDate.id = 'analysis-cursor-date'; cursorDate.setAttribute('aria-label', 'Dokładny czas kursora · Warszawa');
    cursorOutput.htmlFor = cursor.id;
    let pendingFrame = null, pendingAt;
    cursor.addEventListener('input', () => {if (cursor.disabled) return; const range = getState().query.time.filter_range; if (!range) return;
      pendingAt = new Date(Date.parse(range.from) + (Date.parse(range.to) - Date.parse(range.from) - 1) * Number(cursor.value) / 1000).toISOString();
      if (pendingFrame === null) pendingFrame = requestAnimationFrame(() => {pendingFrame = null; dispatch({type: 'SET_CURSOR', at: pendingAt});});
    });
    cursorDate.addEventListener('change', () => {if (cursorDate.disabled) return; const at = toUTC(cursorDate.value); if (at) dispatch({type: 'SET_CURSOR', at});});
    let playTimer = null, lastTick = 0;
    const pause = () => {if (playTimer !== null) clearInterval(playTimer); playTimer = null; play.textContent = 'Odtwórz'; play.setAttribute('aria-pressed', 'false');};
    const speed = U.el('select'); speed.id = 'analysis-motion-speed'; speed.setAttribute('aria-label', 'Tempo odtwarzania historii');
    for (const [value, label] of [[60, '1 min / s'], [300, '5 min / s'], [1800, '30 min / s']]) {const option = U.el('option', label); option.value = value; speed.append(option);} speed.value = '300';
    const play = U.button('Odtwórz', () => {
      if (playTimer !== null) {pause(); return;}
      const state = getState(), selectedRange = state.query.time.filter_range; if (cursor.disabled || !selectedRange) return;
      if (!state.cursorAt || Date.parse(state.cursorAt) >= Date.parse(selectedRange.to) - 2) dispatch({type: 'SET_CURSOR', at: selectedRange.from});
      lastTick = Date.now(); play.textContent = 'Pauza'; play.setAttribute('aria-pressed', 'true');
      playTimer = setInterval(() => {const current = getState(), selected = current.query.time.filter_range, tick = Date.now();
        if (!selected || document.hidden || cursor.disabled) {pause(); return;}
        const next = Math.min(Date.parse(selected.to) - 1, Date.parse(current.cursorAt || selected.from) + (tick - lastTick) * Number(speed.value)); lastTick = tick;
        dispatch({type: 'SET_CURSOR', at: new Date(next).toISOString()}); if (next >= Date.parse(selected.to) - 1) pause();
      }, 100);
    }); play.id = 'analysis-motion-play'; play.setAttribute('aria-pressed', 'false');
    cursorBox.append(U.el('span', 'Wspólny kursor czasu'), play, speed, cursor, cursorDate, cursorOutput);
    host.append(heading, form, message, histogram, note, cursorBox);
    let lastSummary = null;
    return {pause, render(data, state, {historyIncomplete = false, detailLoading = false, motion = null} = {}) {
      const range = state.query.time.filter_range, summary = data?.timeline_summary;
      mode.textContent = state.query.time.mode === 'live' ? 'Bieżące' : 'Przegląd okresu'; live.setAttribute('aria-pressed', String(state.query.time.mode === 'live'));
      if (document.activeElement !== from) from.value = localValue(range?.from || summary?.filter_range?.from);
      if (document.activeElement !== to) to.value = localValue(range?.to || summary?.filter_range?.to);
      if (summary !== lastSummary) {
        lastSummary = summary; histogram.replaceChildren(); const buckets = summary?.buckets || [], max = Math.max(1, ...buckets.map(bucket => bucket.count));
        for (const bucket of buckets) {const bar = U.button('', () => dispatch({type: 'SET_TIME_RANGE', range: {from: bucket.from, to: bucket.to}, overview: summary.overview_range}), 'analysis-histogram-bar');
          bar.style.setProperty('--bar-height', `${Math.max(3, 100 * bucket.count / max)}%`); bar.setAttribute('aria-label', `${U.date(bucket.from)} – ${U.date(bucket.to)}: ${bucket.count} zdarzeń`);
          bar.title = bar.getAttribute('aria-label'); const inner = U.el('span'); inner.setAttribute('aria-hidden', 'true'); bar.append(inner);
          if (summary.filter_range && bucket.from < summary.filter_range.to && bucket.to > summary.filter_range.from) bar.classList.add('in-range'); histogram.append(bar);
        }
        if (!buckets.length) histogram.append(U.el('span', 'Brak zapisanych zdarzeń w tle przedziału. Obszary są bezczasowe.'));
      }
      note.textContent = `${summary?.event_total || 0} zdarzeń / pomiarów w tle${summary?.selected_event_total != null ? ` · ${summary.selected_event_total} w zaznaczeniu` : ''} · ${summary?.timeless_total || 0} obszarów bez czasu. Tło: ${U.date(summary?.overview_range?.from)} – ${U.date(summary?.overview_range?.to)}. Obiekty liczymy oddzielnie w tabeli.`;
      const stationCursor = state.selectedRef?.includes('_station:') && !historyIncomplete && !detailLoading;
      const movingCursor = state.comparedRefs?.length && motion?.data && !motion.loading && !motion.error;
      cursorBox.hidden = !range; cursor.disabled = !(stationCursor || movingCursor); cursorDate.disabled = cursor.disabled;
      play.disabled = speed.disabled = cursor.disabled; play.hidden = speed.hidden = !state.comparedRefs?.length;
      if (!range || cursor.disabled) pause();
      if (range) {const current = Date.parse(state.cursorAt || range.to) - (state.cursorAt ? 0 : 1), lower = Date.parse(range.from), upper = Date.parse(range.to);
        cursor.value = String(Math.max(0, Math.min(1000, 1000 * (current - lower) / (upper - lower))));
        if (document.activeElement !== cursorDate) cursorDate.value = localValue(new Date(current).toISOString());
        cursorOutput.textContent = historyIncomplete && !movingCursor ? 'Historia częściowa — wczytaj kolejne próbki w karcie, aby użyć kursora' : state.cursorAt ? `Według kursora: ${U.date(state.cursorAt)}` : movingCursor ? 'Przesuń kursor lub uruchom odtwarzanie zapisanych tras' : 'Przesuń kursor, aby sprawdzić zaznaczoną stację';
        cursor.setAttribute('aria-valuetext', U.date(new Date(current).toISOString()));
      }
    }};
  }
  return {create, localValue, toUTC};
})();
