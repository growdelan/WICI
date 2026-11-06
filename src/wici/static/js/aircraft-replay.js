'use strict';
window.WiciAircraftReplay = (() => {
  const $ = id => document.getElementById(`aircraft-replay-${id}`);
  const storageKey = 'wici.aircraftReplay.pending.v1';
  const pollDelay = 3000;
  const date = new Intl.DateTimeFormat('pl-PL', {timeZone:'UTC', dateStyle:'short', timeStyle:'short'});
  const validIcao = /^[0-9a-f]{6}$/;
  const validCallsign = /^[A-Z0-9][A-Z0-9 -]{0,7}$/;
  const pendingStates = new Set(['preparing', 'collecting']);
  let request, current = null, recent = [], storageAvailable = true;
  function selection(rawIcao, rawCallsign) {
    const icao = String(rawIcao || '').trim().toLowerCase();
    if (!validIcao.test(icao)) return null;
    const candidate = String(rawCallsign || '').trim().toUpperCase();
    return {icao, callsign:validCallsign.test(candidate) ? candidate : ''};
  }
  function same(a, b) {return a.icao === b.icao && a.callsign === b.callsign;}
  function name(item) {return [item.callsign, item.icao.toUpperCase()].filter(Boolean).join(' · ');}
  function episodePath(raw, icao) {
    if (typeof raw !== 'string') return null;
    const match = /^\/api\/flight-replay\/aircraft\/([a-f0-9]{6})\/episode\?revision=[a-f0-9]{20}$/.exec(raw);
    return match && match[1] === icao ? raw : null;
  }
  function readRecent() {
    if (!storageAvailable) return recent;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
      return Array.isArray(saved) ? saved.slice(0,12).map(item => selection(item?.icao, item?.callsign)).filter(Boolean) : [];
    } catch { return recent; }
  }
  function renderRecent() {
    const container = $('recent');
    container.replaceChildren();
    for (const item of recent) {
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = `Sprawdź stan: ${name(item)}`;
      button.addEventListener('click', () => open(item.icao, item.callsign, button, true));
      container.append(button);
    }
  }
  function remember(item, keep) {
    const saved = readRecent(), exists = saved.some(entry => same(entry, item));
    if (keep === exists) return;
    recent = saved.filter(entry => !same(entry, item));
    if (keep) recent.unshift({icao:item.icao, callsign:item.callsign});
    recent = recent.slice(0, 12);
    try {localStorage.setItem(storageKey, JSON.stringify(recent));} catch {storageAvailable = false;}
    renderRecent();
  }
  function stopPolling(run) {clearTimeout(run.timer); run.timer = null;}
  function close(restore = true) {
    const run = current;
    if (!run) return;
    current = null; stopPolling(run); run.controller?.abort();
    if ($('dialog').open) $('dialog').close();
    if (restore) focusTarget(run).focus({preventScroll:true});
  }
  function focusTarget(run) {
    if (run.trigger?.isConnected && run.trigger.getClientRects().length) return run.trigger;
    return $('submit').getClientRects().length ? $('submit') : document.getElementById('map');
  }
  function resetActions() {
    for (const id of ['collect','retry','saved']) $(id).hidden = true;
    $('counts').hidden = true;
  }
  function show(run, status, message) {
    run.status = status;
    $('dialog').dataset.state = status;
    $('background').hidden = !pendingStates.has(status);
    if ($('message').textContent !== message) $('message').textContent = message;
    resetActions();
  }
  function launch(run, url, keepPending = false) {
    const validated = episodePath(url, run.icao);
    if (!validated) throw Error('Zapis nie odpowiada wybranemu ICAO lub ma nieprawidłowy adres.');
    if (!keepPending) remember(run, false);
    const trigger = focusTarget(run);
    close(false);
    window.WiciFlightReplay.open(trigger, validated);
  }
  function schedule(run) {
    stopPolling(run);
    if (!document.hidden && current === run) run.timer = setTimeout(() => transact(run, 'status'), pollDelay);
  }
  function present(run, result) {
    if (!result || result.icao !== run.icao) throw Error('Odpowiedź nie dotyczy wybranego samolotu.');
    const status = result.status;
    if ((pendingStates.has(status) || status === 'ready') && run.callsign && result.callsign && result.callsign !== run.callsign) {
      throw Error('Odpowiedź dotyczy innego znaku wywoławczego.');
    }
    if (status === 'ready') {
      if (document.hidden) {
        run.readyUrl = episodePath(result.episode_url, run.icao);
        if (!run.readyUrl) throw Error('Nieprawidłowy adres odcinka.');
        show(run,'ready','Odcinek jest gotowy do odtworzenia.'); return;
      }
      launch(run, result.episode_url); return;
    }
    const hints = {
      preparing:'Przygotowywanie odcinka lotu z radarem…', collecting:'Trwa zbieranie pozycji i klatek radaru.',
      no_history:'Brak historii z radarem dla wybranego samolotu.', expired:'Zbieranie zakończyło się przed uzyskaniem wystarczających danych.',
      unavailable:'Źródło jest obecnie niedostępne.', error:'Nie udało się przygotować odcinka.'
    };
    if (!Object.hasOwn(hints,status)) throw Error('Nieznany stan przygotowania odcinka.');
    show(run, status, result.message || hints[status]);
    if (Number.isInteger(result.points) || Number.isInteger(result.frames)) {
      const counts = [];
      if (Number.isInteger(result.points)) counts.push(`Pozycje: ${result.points}`);
      if (Number.isInteger(result.frames)) counts.push(`Klatki radaru: ${result.frames}`);
      $('counts').textContent = counts.join(' · '); $('counts').hidden = false;
    }
    run.savedUrl = episodePath(result.saved_episode_url, run.icao);
    if (run.savedUrl && Number.isFinite(result.saved_end)) {
      const label = [result.saved_label, `${date.format(result.saved_end * 1000)} UTC`].filter(Boolean).join(' · ');
      $('saved').textContent = `Otwórz wcześniejszy zapis: ${label}`; $('saved').hidden = false;
    }
    if (pendingStates.has(status)) {
      remember(run, true); schedule(run); return;
    }
    remember(run, false);
    run.retryAction = 'prepare'; $('retry').hidden = false;
    $('collect').hidden = status !== 'no_history' && status !== 'expired';
  }
  async function transact(run, action) {
    if (current !== run || run.controller) return;
    stopPolling(run);
    const controller = run.controller = new AbortController();
    if (action !== 'status') {
      remember(run, true);
      show(run, action === 'collect' ? 'starting' : 'loading', action === 'collect' ? 'Rozpoczynanie zbierania…' : 'Sprawdzanie dostępnego odcinka lotu…');
    }
    const root = `/flight-replay/aircraft/${run.icao}`;
    const query = run.callsign ? `?${new URLSearchParams({callsign:run.callsign})}` : '';
    try {
      const args = {signal:controller.signal, timeoutMs:30000};
      const result = action === 'status' ? await request(`${root}/status${query}`, undefined, args) :
        await request(`${root}/${action}`, run.callsign ? {callsign:run.callsign} : {}, args);
      if (current === run && !controller.signal.aborted) present(run, result);
    } catch (error) {
      if (current !== run || controller.signal.aborted) return;
      show(run, 'error', error.message || 'Nie udało się odczytać stanu odcinka.');
      // A mutation may have reached the server even if the response was lost.
      run.retryAction = 'status'; $('retry').hidden = false;
    } finally {if (run.controller === controller) run.controller = null;}
  }
  function open(icao, callsign, trigger, resume = false) {
    const item = selection(icao, callsign);
    if (!item || !request || current) return;
    const run = current = {...item, trigger, timer:null, controller:null};
    $('title').textContent = `${name(item)} · ostatni odcinek`;
    const known = resume || readRecent().some(entry => same(entry, item));
    show(run, 'loading', known ? 'Odczytywanie stanu zapisu…' : 'Sprawdzanie dostępnego odcinka lotu…');
    $('dialog').showModal(); $('close').focus({preventScroll:true});
    return transact(run, known ? 'status' : 'prepare');
  }
  function init(api) {
    if (request) return;
    request = api; recent = readRecent(); renderRecent();
    $('form').addEventListener('submit', event => {event.preventDefault(); open($('icao').value, '', $('submit'));});
    $('close').addEventListener('click', () => close());
    $('dialog').addEventListener('click', event => event.stopPropagation());
    $('dialog').addEventListener('keydown', event => {
      if (event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); close();}
    });
    $('dialog').addEventListener('cancel', event => {event.preventDefault(); close();});
    $('dialog').addEventListener('close', () => {if (!$('dialog').open) close();});
    $('collect').addEventListener('click', () => {if (current && !($('collect').hidden)) transact(current,'collect');});
    $('retry').addEventListener('click', () => {if (current && !$('retry').hidden) transact(current, current.retryAction);});
    $('saved').addEventListener('click', () => {if (current?.savedUrl && !$('saved').hidden) launch(current, current.savedUrl, pendingStates.has(current.status));});
    document.addEventListener('visibilitychange', () => {
      if (current?.readyUrl && !document.hidden) {launch(current, current.readyUrl); return;}
      if (!current || !pendingStates.has(current.status)) return;
      if (document.hidden) stopPolling(current);
      else transact(current, 'status');
    });
    window.addEventListener('storage', event => {if (event.key === storageKey) {recent = readRecent(); renderRecent();}});
  }
  return {init, open};
})();
