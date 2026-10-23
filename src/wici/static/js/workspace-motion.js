'use strict';
/* Recorded positions only: no interpolation, no current position fallback in replay. */
(function (root) {
  const colors = ['#16819c', '#b26429', '#8b67ae', '#388961', '#b34c77'];
  const isMoving = object => ['aircraft', 'ship'].includes(object?.type);
  const pointTime = point => Date.parse(point?.position_at || point?.at);
  const coordinates = point => Number.isFinite(point?.latitude) && Math.abs(point.latitude) <= 90 && Number.isFinite(point?.longitude) && Math.abs(point.longitude) <= 180;
  const pointCache = new WeakMap();
  function pointsInRange(series, range) {
    if (!series) return [];
    const key = `${range?.from || ''}|${range?.to || ''}`, cached = pointCache.get(series);
    if (cached?.key === key && cached.source === series.points) return cached.points;
    const lower = range ? Date.parse(range.from) : -Infinity, upper = range ? Date.parse(range.to) : Infinity;
    const points = (series.points || []).filter(point => coordinates(point) && Number.isFinite(pointTime(point)) && pointTime(point) >= lower && pointTime(point) < upper)
      .slice().sort((a, b) => pointTime(a) - pointTime(b));
    pointCache.set(series, {key, source: series.points, points}); return points;
  }
  function frameAt(series, cursorAt, range) {
    const limit = Date.parse(cursorAt || range?.to) - (cursorAt ? 0 : 1), points = pointsInRange(series, range);
    let lower = 0, upper = points.length;
    while (lower < upper) {const middle = Math.floor((lower + upper) / 2); if (pointTime(points[middle]) <= limit) lower = middle + 1; else upper = middle;}
    const point = lower > 0 && Number.isFinite(limit) ? points[lower - 1] : null;
    if (!point) return {point: null, status: 'empty', age_seconds: null};
    const age = Math.max(0, (limit - pointTime(point)) / 1000), threshold = series?.gap_seconds || (series?.type === 'ship' ? 900 : 120);
    if (age > threshold) return {point: null, lastPoint: point, status: 'gap', age_seconds: age};
    return {point, status: 'ready', age_seconds: age};
  }
  function segments(series, range, cursorAt = null) {
    const limit = cursorAt ? Date.parse(cursorAt) : Infinity, gap = (series?.gap_seconds || (series?.type === 'ship' ? 900 : 120)) * 1000;
    const result = []; let current = [], previous = null;
    for (const point of pointsInRange(series, range)) {
      if (pointTime(point) > limit) break;
      if (previous && (point.break_before || point.track_id !== previous.track_id || pointTime(point) - pointTime(previous) > gap || Math.abs(point.longitude - previous.longitude) > 180)) {if (current.length) result.push(current); current = [];}
      current.push(point); previous = point;
    }
    if (current.length) result.push(current); return result;
  }
  function describe(frame, U) {
    if (!frame) return 'Dodaj do porównania';
    if (frame.status === 'loading') return 'Wczytywanie zapisanych pozycji…';
    if (frame.status === 'error') return 'Odczyt historii nie powiódł się';
    if (frame.status === 'gap') return `Luka · ostatni raport ${U.date(frame.lastPoint?.position_at || frame.lastPoint?.at)}`;
    if (!frame.point) return 'Brak zapisanej pozycji przed kursorem';
    return `Raport sprzed ${Math.round(frame.age_seconds)} s · ${U.date(frame.point.position_at || frame.point.at)}`;
  }
  const number = (value, unit) => Number.isFinite(value) ? `${Math.round(value * 10) / 10} ${unit}` : 'Brak danych';
  function view(host, {remove, clear, select, range, fit}) {
    const U = root.WiciWorkspaceUI, box = U.el('section', null, 'analysis-motion'); box.id = 'analysis-motion';
    const heading = U.el('div', null, 'analysis-motion-heading'); heading.append(U.el('h3', 'Porównanie zapisanych tras'));
    const day = U.button('Porównaj ostatnie 24 h', range); day.id = 'analysis-compare-day';
    const show = U.button('Pokaż trasy na mapie', fit); show.id = 'analysis-fit-tracks';
    heading.append(day, show, U.button('Wyczyść porównanie', clear));
    const chips = U.el('div', null, 'analysis-compare-chips'), note = U.el('p', '', 'analysis-timeline-note'); note.id = 'analysis-motion-status'; note.setAttribute('role', 'status');
    const scroll = U.el('div', null, 'analysis-comparison-scroll'), table = U.el('table'); table.id = 'analysis-comparison-table';
    const thead = U.el('thead'), tr = U.el('tr'); for (const label of ['Obiekt', 'Prędkość · km/h', 'Wysokość · m', 'Raport przy kursorze']) {const th = U.el('th', label); th.scope = 'col'; tr.append(th);} thead.append(tr);
    const body = U.el('tbody'); table.append(thead, body); scroll.append(table);
    const chartHost = U.el('div', null, 'analysis-motion-charts');
    box.append(heading, chips, note, scroll, chartHost, U.el('p', 'Zapis obejmuje wyłącznie uruchomione sesje. Retencja: 7 dni. Kursor pokazuje ostatni rzeczywisty raport, maksymalnie 120 s dla samolotu i 900 s dla statku. Luki i granice sesji przerywają linie; pozycje nie są interpolowane.', 'analysis-timeline-note')); host.append(box);
    let lastReplay, lastRefs = '', lastRange = '', chartCursors = []; const rows = new Map();
    function chart(series, selectedRange, metric, label, id) {
      const ns = 'http://www.w3.org/2000/svg', figure = U.el('figure'), caption = U.el('figcaption', label), svg = document.createElementNS(ns, 'svg');
      svg.id = id; svg.setAttribute('viewBox', '0 0 600 170'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${label}. Wspólna skala dla porównywanych obiektów; tylko zapisane raporty.`);
      const from = Date.parse(selectedRange.from), to = Date.parse(selectedRange.to), values = series.flatMap(item => pointsInRange(item, selectedRange).map(point => point[metric])).filter(Number.isFinite);
      const min = values.reduce((result, value) => Math.min(result, value), 0), max = values.reduce((result, value) => Math.max(result, value), 1), x = point => 55 + 530 * (pointTime(point) - from) / Math.max(1, to - from), y = value => 138 - 118 * (value - min) / Math.max(1, max - min);
      const element = (tag, attrs, text) => {const node = document.createElementNS(ns, tag); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value); if (text != null) node.textContent = text; return node;};
      for (const value of [min, (max + min) / 2, max]) {svg.append(element('line', {x1: 55, y1: y(value), x2: 585, y2: y(value), stroke: 'var(--line)'}), element('text', {x: 48, y: y(value) + 4, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 11}, Math.round(value)));}
      for (const item of series) {
        const commands = [], stride = Math.max(1, Math.ceil(pointsInRange(item, selectedRange).length / 150)); let index = 0;
        for (const segment of segments(item, selectedRange)) {let previous = null;
          for (const point of segment) {
            if (!Number.isFinite(point[metric])) {previous = null; continue;}
            const coordinate = `${x(point).toFixed(2)},${y(point[metric]).toFixed(2)}`;
            commands.push(previous ? `L${coordinate}` : `M${coordinate}L${coordinate}`); previous = point;
            // Exact data forms the path and cursor. Limit only hover glyphs, keeping SVG responsive.
            if (index++ % stride === 0) {const dot = element('circle', {cx: x(point), cy: y(point[metric]), r: 2, fill: item.color}); dot.append(element('title', {}, `${item.label} · ${U.date(point.position_at || point.at)} · ${point[metric]}`)); svg.append(dot);}
          }
        }
        svg.append(element('path', {d: commands.join(''), stroke: item.color, 'stroke-width': 1.5, 'stroke-linecap': 'round', fill: 'none'}));
      }
      svg.append(element('text', {x: 55, y: 162, fill: 'var(--muted)', 'font-size': 10}, U.date(selectedRange.from)), element('text', {x: 585, y: 162, 'text-anchor': 'end', fill: 'var(--muted)', 'font-size': 10}, U.date(selectedRange.to)));
      const cursorLine = element('line', {x1: 585, x2: 585, y1: 16, y2: 140, stroke: 'var(--ink)', 'stroke-width': 1, 'stroke-dasharray': '4 3'}); svg.append(cursorLine); chartCursors.push(cursorLine);
      figure.append(caption, svg); if (!values.length) figure.append(U.el('small', 'Brak zapisanych wartości w tym przedziale.')); chartHost.append(figure);
    }
    return {render(state, context) {
      const refs = state.comparedRefs || [], selectedRange = state.query.time.filter_range, replay = context?.data, frames = context?.frames || new Map();
      box.hidden = refs.length === 0;
      if (box.hidden) return;
      day.hidden = Boolean(selectedRange); show.disabled = !selectedRange || !replay?.series?.some(item => item.points?.length);
      const rangeKey = JSON.stringify([selectedRange, state.displayTimezone]);
      const series = refs.map((ref, index) => ({...replay?.series?.find(item => item.ref === ref), ref, label: replay?.series?.find(item => item.ref === ref)?.label || context?.labels?.get(ref) || ref, color: colors[index]}));
      const key = JSON.stringify(series.map(item => [item.ref, item.label]));
      if (key !== lastRefs || replay !== lastReplay || rangeKey !== lastRange) {
        lastRefs = key; lastReplay = replay; lastRange = rangeKey; chips.replaceChildren(); chartHost.replaceChildren(); body.replaceChildren(); rows.clear(); chartCursors = [];
        for (const item of series) {const chip = U.el('span', null, 'analysis-compare-chip'); chip.style.setProperty('--track-color', item.color); chip.append(U.button(item.label, () => select(item.ref)), U.button('×', () => remove(item.ref))); chip.lastChild?.setAttribute('aria-label', `Usuń ${item.label} z porównania`); chips.append(chip);}
        for (const item of series) {const row = U.el('tr'), name = U.el('td'), speedValue = U.el('td'), altitude = U.el('td'), report = U.el('td'); row.dataset.ref = item.ref; name.append(U.button(item.label, () => select(item.ref))); name.style.setProperty('--track-color', item.color); row.append(name, speedValue, altitude, report); body.append(row); rows.set(item.ref, {row, speedValue, altitude, report});}
        if (selectedRange && replay) {chart(series, selectedRange, 'speed_kmh', 'Prędkość · km/h', 'analysis-speed-chart'); if (series.some(item => item.type === 'aircraft')) chart(series.filter(item => item.type === 'aircraft'), selectedRange, 'altitude_m', 'Wysokość · m', 'analysis-altitude-chart');}
      }
      note.textContent = !selectedRange ? `${refs.length} / 5 obiektów. Ustaw przedział, aby odtworzyć zapisane trasy.` : context?.loading ? 'Wczytywanie zapisanych tras…' : context?.error ? `Nie udało się pobrać tras: ${context.error}` : `${refs.length} / 5 obiektów · ${(replay?.series || []).reduce((sum, item) => sum + (item.returned_points ?? item.points?.length ?? 0), 0)} zapisanych raportów${replay?.series?.some(item => item.downsampled) ? ' · historia ograniczona: zawęź przedział, aby uzyskać pełną dokładność' : ''}.`;
      for (const item of series) {const frame = frames.get(item.ref), entry = rows.get(item.ref); if (!entry) continue; entry.row.dataset.motionStatus = frame?.status || 'empty'; entry.speedValue.textContent = number(frame?.point?.speed_kmh, ''); entry.altitude.textContent = item.type === 'ship' ? '—' : number(frame?.point?.altitude_m, ''); entry.report.textContent = selectedRange ? describe(frame, U) : 'Wybierz przedział historii';}
      if (selectedRange) {const position = 55 + 530 * (Date.parse(state.cursorAt || selectedRange.to) - Date.parse(selectedRange.from)) / Math.max(1, Date.parse(selectedRange.to) - Date.parse(selectedRange.from)); for (const line of chartCursors) {line.setAttribute('x1', position); line.setAttribute('x2', position);}}
    }};
  }
  const exported = {colors, isMoving, pointTime, pointsInRange, frameAt, segments, describe, number, view};
  root.WiciWorkspaceMotion = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(typeof window !== 'undefined' ? window : globalThis);
