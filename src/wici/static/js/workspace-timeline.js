'use strict';
window.WiciWorkspaceTimeline = (() => {
  const U = window.WiciWorkspaceUI;
  function localValue(value, timezone = 'Europe/Warsaw') {
    if (!value) return ''; const date = new Date(value); if (!Number.isFinite(date.getTime())) return '';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('sv-SE', {timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }
  // Round-trip candidate offsets: reject nonexistent local hours at the spring DST transition.
  function toUTC(value, timezone = 'Europe/Warsaw') {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
    const raw = Date.parse(`${value}Z`);
    for (const offset of timezone === 'UTC' ? [0] : timezone === 'Europe/Kyiv' ? [180, 120] : [120, 60]) {const candidate = new Date(raw - offset * 60000).toISOString(); if (localValue(candidate, timezone) === value) return candidate;}
    return null;
  }
  function stationSamples(timeline, state) {
    if (timeline?.ref !== state.selectedRef) return [];
    const isAir = state.selectedRef?.startsWith('air_quality_station:');
    if (isAir && !state.selectedSensor) return [];
    const metric = state.selectedMetric || (state.selectedRef?.startsWith('hydro_station:') ? 'water_level' : null), latest = new Map();
    for (const item of timeline.items || []) {
      if (item.kind && item.kind !== 'measurement' || !Number.isFinite(Date.parse(item.observed_at)) || item.quality && item.quality !== 'valid') continue;
      if (metric && item.metric !== metric || state.selectedSensor && String(item.sensor_id) !== String(state.selectedSensor)) continue;
      const at = Date.parse(item.observed_at), range = state.query.time.filter_range;
      if (range && (at < Date.parse(range.from) || at >= Date.parse(range.to))) continue;
      const key = [item.sensor_id, item.metric, item.observed_at].join('|');
      if (!latest.has(key) || (item.revision || 0) >= (latest.get(key).revision || 0)) latest.set(key, item);
    }
    return [...latest.values()].sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
  }
  function drawStation(host, samples, range, timezone) {
    host.replaceChildren(); const values = samples.filter(sample => Number.isFinite(sample.value));
    if (!values.length) {host.append(U.el('p', 'Brak zapisanych pomiarów w tym zakresie.', 'analysis-chart-empty')); return null;}
    const times = samples.map(sample => Date.parse(sample.observed_at));
    let lower = range ? Date.parse(range.from) : Math.min(...times), upper = range ? Date.parse(range.to) : Math.max(...times);
    if (lower === upper) {lower -= 1800000; upper += 1800000;}
    const min = Math.min(...values.map(sample => sample.value)), max = Math.max(...values.map(sample => sample.value)), pad = Math.max(1, (max-min) * .15);
    const floor = min-pad, ceiling = max+pad, x = at => 50 + 690 * (Date.parse(at)-lower) / (upper-lower), y = value => 94 - 74 * (value-floor) / (ceiling-floor);
    const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 760 126'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Historia pomiarów wybranej stacji. Braki wartości i luki ponad trzy godziny nie są łączone.');
    const add = (tag, attrs, text) => {const node = document.createElementNS(ns, tag); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value); if (text != null) node.textContent = text; svg.append(node); return node;};
    for (let index=0; index<=3; index++) {
      const value = floor + (ceiling-floor)*index/3, yy = y(value);
      add('line', {x1: 50, x2: 740, y1: yy, y2: yy, stroke: 'var(--line)'});
      add('text', {x: 42, y: yy+4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 11}, `${Math.round(value*10)/10}`);
    }
    add('text', {x: 50, y: 12, fill: 'var(--muted)', 'font-size': 11}, values[0].unit || '');
    const dateLabels = upper-lower > 86400000;
    for (let index=0; index<=4; index++) {
      const at = lower+(upper-lower)*index/4, xx = 50+690*index/4;
      add('line', {x1: xx, x2: xx, y1: 20, y2: 94, stroke: 'var(--line)'});
      const text = new Intl.DateTimeFormat('pl-PL', {timeZone: timezone, ...(dateLabels ? {day: '2-digit', month: '2-digit'} : {}), hour: '2-digit', minute: '2-digit'}).format(new Date(at));
      add('text', {x: xx, y: 116, 'text-anchor': index === 0 ? 'start' : index === 4 ? 'end' : 'middle', fill: 'var(--muted)', 'font-size': 11}, text);
    }
    // Each bar is one recorded reading, placed at its actual time. Empty
    // intervals stay empty; the line below still preserves observation gaps.
    const intervals = times.slice(1).map((at, index) => at - times[index]).filter(delta => delta > 0).sort((a, b) => a - b);
    const interval = intervals[Math.floor(intervals.length / 2)] || 3600000;
    const barWidth = Math.max(2, Math.min(24, 690 * interval / (upper-lower) * .75));
    for (const sample of values) {
      const xx = x(sample.observed_at), yy = y(sample.value);
      add('rect', {x: Math.max(50, xx - barWidth / 2), y: yy, width: Math.min(barWidth, 740 - Math.max(50, xx - barWidth / 2)), height: 94 - yy, fill: 'var(--teal)', opacity: .3, class: 'analysis-station-bar'});
    }
    let previous = null;
    for (const sample of samples) {
      if (!Number.isFinite(sample.value)) {previous = null; continue;}
      if (previous && sample.metric === previous.metric && sample.sensor_id === previous.sensor_id && Date.parse(sample.observed_at)-Date.parse(previous.observed_at) <= 10800000) add('line', {x1: x(previous.observed_at), x2: x(sample.observed_at), y1: y(previous.value), y2: y(sample.value), stroke: 'var(--teal)', 'stroke-width': 2.5, class: 'analysis-station-segment'});
      const dot = add('circle', {cx: x(sample.observed_at), cy: y(sample.value), r: 2.5, fill: 'var(--teal)', class: 'analysis-station-sample'}), tooltip = document.createElementNS(ns, 'title');
      tooltip.textContent = `${U.date(sample.observed_at)} · ${U.value(sample)}`; dot.append(tooltip); previous = sample;
    }
    const cursorLine = add('line', {x1: 0, x2: 0, y1: 18, y2: 97, stroke: 'var(--teal)', 'stroke-width': 1.5, 'stroke-dasharray': '3 3', visibility: 'hidden'});
    const cursorDot = add('circle', {cx: 0, cy: 0, r: 4.5, fill: 'var(--teal)', stroke: 'var(--paper)', 'stroke-width': 2, visibility: 'hidden'});
    host.append(svg); return {cursorLine, cursorDot, lower, upper, x, y};
  }
  function create(host, {dispatch, getState, now}) {
    const main = U.el('div', null, 'analysis-time-main'), heading = U.el('div', null, 'analysis-time-context'), title = U.el('h2', 'Zdarzenia w zakresie'), objectName = U.el('p', '', 'analysis-time-object'), mode = U.el('span', 'Bieżące');
    mode.id = 'analysis-time-mode'; heading.append(title, objectName, mode);
    const chart = U.el('div', null, 'analysis-time-chart'), stationChart = U.el('div', null, 'analysis-station-history'), timeActions = U.el('div', null, 'analysis-time-actions'); chart.append(stationChart);
    const live = U.button('Bieżące', () => dispatch({type: 'RETURN_TO_LIVE'})), lastDay = U.button('Ostatnie 24 godziny', () => {
      const end = new Date(now()).getTime(); const range = {from: new Date(end - 86400000).toISOString(), to: new Date(end).toISOString()}; dispatch({type: 'SET_TIME_RANGE', range});
    }); heading.append(lastDay); timeActions.append(live); main.append(heading, chart, timeActions);
    const form = U.el('form', null, 'analysis-time-fields'), from = U.el('input'), to = U.el('input');
    from.type = to.type = 'datetime-local'; from.id = 'analysis-time-from'; to.id = 'analysis-time-to'; from.required = to.required = true; from.title = to.title = 'Czas Europe/Warsaw. Dla powtórzonej jesiennej godziny wybieramy wcześniejsze wystąpienie.';
    const zone = U.el('select'); zone.id = 'analysis-timezone'; zone.setAttribute('aria-label', 'Strefa czasu analizy');
    for (const [value, label] of [['Europe/Warsaw', 'Warszawa'], ['Europe/Kyiv', 'Kijów'], ['UTC', 'UTC']]) {const option = U.el('option', label); option.value = value; zone.append(option);}
    zone.addEventListener('change', () => dispatch({type: 'SET_TIMEZONE', timezone: zone.value}));
    const apply = U.button('Ustaw przedział'); apply.type = 'submit';
    form.append(U.field('Od · wybrana strefa', from), U.field('Do · wyłącznie', to), U.field('Strefa czasu', zone), apply);
    const message = U.el('p', '', 'analysis-message'); message.setAttribute('role', 'status');
    form.addEventListener('submit', event => {event.preventDefault(); const lower = toUTC(from.value, getState().displayTimezone), upper = toUTC(to.value, getState().displayTimezone);
      if (!lower || !upper || lower >= upper) {message.textContent = 'Podaj poprawny przedział. Nieistniejąca godzina zmiany czasu jest odrzucana.'; return;}
      const previous = getState().query.time.overview_range;
      const range = {from: lower, to: upper}, overview = previous && lower >= previous.from && upper <= previous.to ? previous : range;
      message.textContent = ''; dispatch({type: 'SET_TIME_RANGE', range, overview});
    });
    const histogram = U.el('div', null, 'analysis-histogram'); histogram.id = 'analysis-histogram'; histogram.setAttribute('aria-label', 'Zdarzenia w tle przedziału; wybierz koszyk, aby zawęzić zakres');
    const note = U.el('p', '', 'analysis-timeline-note'), histogramBlock = U.el('div', null, 'analysis-histogram-block'); histogramBlock.append(histogram, note); chart.append(histogramBlock);
    const catalogHistory = U.el('details', null, 'analysis-catalog-history'); catalogHistory.append(U.el('summary', 'Zdarzenia całego katalogu'));
    const timeOptions = U.el('details', null, 'analysis-time-options'); timeOptions.append(U.el('summary', 'Przedział i strefa czasu'), form, message);
    const cursorOptions = U.el('details', null, 'analysis-cursor-options'); cursorOptions.append(U.el('summary', 'Kursor i odtwarzanie'));
    const cursorBox = U.el('div', null, 'analysis-cursor'), cursor = U.el('input'), cursorDate = U.el('input'), cursorOutput = U.el('output');
    cursor.type = 'range'; cursor.min = '0'; cursor.max = '1000'; cursor.step = '1'; cursor.id = 'analysis-cursor'; cursor.setAttribute('aria-label', 'Wspólny kursor czasu stacji, tras i regionów Ukrainy');
    cursorDate.type = 'datetime-local'; cursorDate.id = 'analysis-cursor-date'; cursorDate.setAttribute('aria-label', 'Dokładny czas kursora · Warszawa');
    cursorOutput.htmlFor = cursor.id;
    let pendingFrame = null, pendingAt;
    cursor.addEventListener('input', () => {if (cursor.disabled) return; const range = getState().query.time.filter_range; if (!range) return;
      pendingAt = new Date(Date.parse(range.from) + (Date.parse(range.to) - Date.parse(range.from) - 1) * Number(cursor.value) / 1000).toISOString();
      if (pendingFrame === null) pendingFrame = requestAnimationFrame(() => {pendingFrame = null; dispatch({type: 'SET_CURSOR', at: pendingAt});});
    });
    cursorDate.addEventListener('change', () => {if (cursorDate.disabled) return; const at = toUTC(cursorDate.value, getState().displayTimezone); if (at) dispatch({type: 'SET_CURSOR', at});});
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
    cursorOptions.append(cursorBox); host.append(main, timeOptions, catalogHistory, cursorOptions);
    let lastSummary = null, lastTimezone = null, lastStationMode = null, lastChartInputs = null, stationPlot = null, hadRange = false;
    return {pause, render(data, state, {detail = null, timeline = null, selectedSample = null, historyIncomplete = false, detailLoading = false, motion = null, alerts = null, graph = null} = {}) {
      const range = state.query.time.filter_range, summary = data?.timeline_summary, timezone = state.displayTimezone || 'Europe/Warsaw';
      const object = detail?.object || detail, isStation = Boolean(state.detailOpen && state.selectedRef?.includes('_station:'));
      const ready = isStation && object?.ref === state.selectedRef && timeline?.ref === state.selectedRef && !detailLoading && (detail._detailRevision == null || detail._detailRevision === state.detailRevision) && (detail._queryRevision == null || detail._queryRevision === state.queryRevision);
      const label = object?.ref === state.selectedRef ? object.label : 'Wybrana stacja';
      title.textContent = isStation ? 'Historia wybranego obiektu' : 'Zdarzenia w zakresie';
      const metric = state.selectedMetric || (object?.type === 'hydro_station' ? 'water_level' : null), source = U.sourceNames?.[object?.source_id] || object?.source_id || '';
      objectName.textContent = isStation ? [label, source, U.metricNames?.[metric] || metric].filter(Boolean).join(' · ') : 'Publikacje, pomiary i zapisane obserwacje';
      if (lastStationMode !== isStation) {lastStationMode = isStation; (isStation ? catalogHistory : chart).append(histogramBlock);}
      stationChart.hidden = !isStation; catalogHistory.hidden = !isStation;
      const chartInputs = [isStation, ready, timeline, state.selectedRef, state.selectedMetric, state.selectedSensor, range?.from, range?.to, timezone, historyIncomplete];
      if (!lastChartInputs || chartInputs.some((value, index) => value !== lastChartInputs[index])) {
        lastChartInputs = chartInputs; stationPlot = null;
        if (isStation) {
          if (!ready) stationChart.replaceChildren(U.el('p', detailLoading ? 'Wczytywanie historii stacji…' : 'Historia wybranej stacji jest niedostępna.', 'analysis-chart-empty'));
          else if (object.type === 'air_quality_station' && !state.selectedSensor) stationChart.replaceChildren(U.el('p', 'Wybierz stanowisko pomiarowe w szczegółach, aby zobaczyć jego historię.', 'analysis-chart-empty'));
          else {
            stationPlot = drawStation(stationChart, stationSamples(timeline, state), range, timezone);
            if (historyIncomplete) stationChart.append(U.el('small', 'Historia częściowa — kolejne próbki są dostępne w karcie obiektu.', 'analysis-chart-note'));
          }
        }
      }
      if (stationPlot) {
        const at = Date.parse(state.cursorAt), visible = Number.isFinite(at) && at >= stationPlot.lower && at < stationPlot.upper;
        stationPlot.cursorLine.setAttribute('visibility', visible ? 'visible' : 'hidden');
        if (visible) {const xx = stationPlot.x(state.cursorAt); stationPlot.cursorLine.setAttribute('x1', xx); stationPlot.cursorLine.setAttribute('x2', xx);}
        const showSample = visible && selectedSample && Number.isFinite(selectedSample.value);
        stationPlot.cursorDot.setAttribute('visibility', showSample ? 'visible' : 'hidden');
        if (showSample) {stationPlot.cursorDot.setAttribute('cx', stationPlot.x(selectedSample.observed_at)); stationPlot.cursorDot.setAttribute('cy', stationPlot.y(selectedSample.value));}
      }
      zone.value = timezone; from.title = to.title = `Czas ${timezone}. Dla powtórzonej jesiennej godziny wybieramy wcześniejsze wystąpienie.`; cursorDate.setAttribute('aria-label', `Dokładny czas kursora · ${timezone}`);
      mode.textContent = state.query.time.mode === 'live' ? 'Bieżące' : 'Przegląd okresu'; live.setAttribute('aria-pressed', String(state.query.time.mode === 'live'));
      if (document.activeElement !== from) from.value = localValue(range?.from || summary?.filter_range?.from, timezone);
      if (document.activeElement !== to) to.value = localValue(range?.to || summary?.filter_range?.to, timezone);
      if (summary !== lastSummary || timezone !== lastTimezone) {
        lastSummary = summary; lastTimezone = timezone; histogram.replaceChildren(); const buckets = summary?.buckets || [], max = Math.max(1, ...buckets.map(bucket => bucket.count));
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
      const regionCursor = state.comparedRegionRefs?.length && alerts?.data && !alerts.loading && !alerts.error;
      const graphCursor = Boolean(range && graph?.temporal);
      cursorOptions.hidden = !range; if (range && !hadRange) cursorOptions.open = true; hadRange = Boolean(range); cursorBox.hidden = !range; cursor.disabled = !(stationCursor || movingCursor || regionCursor || graphCursor); cursorDate.disabled = cursor.disabled;
      play.disabled = speed.disabled = cursor.disabled; play.hidden = speed.hidden = !(state.comparedRefs?.length || state.comparedRegionRefs?.length || graphCursor);
      if (!range || cursor.disabled) pause();
      if (range) {const current = Date.parse(state.cursorAt || range.to) - (state.cursorAt ? 0 : 1), lower = Date.parse(range.from), upper = Date.parse(range.to);
        cursor.value = String(Math.max(0, Math.min(1000, 1000 * (current - lower) / (upper - lower))));
        if (document.activeElement !== cursorDate) cursorDate.value = localValue(new Date(current).toISOString(), timezone);
        cursorOutput.textContent = historyIncomplete && !movingCursor && !regionCursor && !graphCursor ? 'Historia częściowa — wczytaj kolejne próbki w karcie, aby użyć kursora' : state.cursorAt ? `Według kursora: ${U.date(state.cursorAt)}` : movingCursor || regionCursor || graphCursor ? 'Przesuń kursor lub uruchom odtwarzanie zapisanej historii' : 'Przesuń kursor, aby sprawdzić zaznaczoną stację';
        cursor.setAttribute('aria-valuetext', U.date(new Date(current).toISOString()));
      }
    }};
  }
  return {create, localValue, toUTC, stationSamples};
})();
