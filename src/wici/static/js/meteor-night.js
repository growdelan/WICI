'use strict';
window.WiciMeteorNight = (() => {
  const SAMPLE = '2026-11-04', NYSA = '20261104215730_pYgTq';
  const $ = name => document.getElementById('meteor-night-' + name);
  const places = {nysa:[50.474,17.334], warszawa:[52.230,21.012], krakow:[50.061,19.938],
    gdansk:[54.352,18.647], poznan:[52.407,16.925]};
  const clock = new Intl.DateTimeFormat('pl-PL', {timeZone:'UTC', hour:'2-digit', minute:'2-digit', second:'2-digit'});
  const amount = new Intl.NumberFormat('pl-PL', {maximumFractionDigits:2});
  const dayFormat = new Intl.DateTimeFormat('pl-PL', {timeZone:'Europe/Warsaw', day:'numeric', month:'long'});
  const fullDay = new Intl.DateTimeFormat('pl-PL', {timeZone:'Europe/Warsaw', year:'numeric', month:'numeric', day:'numeric', hour:'2-digit', hourCycle:'h23'});
  let context, active, picking;
  const at = (time, precise = false) => {
    const ms = Math.round(time * 1000);
    const decimals = precise ? ',' + String(ms % 1000).padStart(3, '0') : '';
    return clock.format(ms) + decimals;
  };
  const measurement = (value, unit) => Number.isFinite(value) ? amount.format(value) + ' ' + unit : 'Brak pomiaru';
  const finish = event => event.start + event.duration;
  const observer = () => {
    const city = places[$('observer').value];
    return city ? {lat:city[0],lon:city[1]} : active.custom;
  };
  function mostRecentNight() {
    const parts = Object.fromEntries(fullDay.formatToParts(new Date()).map(p => [p.type,p.value]));
    const midnight = Date.UTC(+parts.year, +parts.month - 1, +parts.day);
    return new Date(midnight - (+parts.hour >= 12 ? 1 : 2) * 86400000).toISOString().slice(0,10);
  }
  function pause(run) {
    cancelAnimationFrame(run.raf);
    run.playing = false;
    $('play').textContent = 'Odtwórz'; $('play').setAttribute('aria-pressed','false');
  }
  function destroyScene(run) {
    const scene = run.scene;
    run.scene = null;
    try { scene?.destroy(); } catch { /* The graphics context may already be gone. */ }
    $('scene').replaceChildren();
  }
  function endPick() {
    if (!picking) return;
    picking.abort(); picking = null;
    $('map-prompt').hidden = true;
    document.getElementById('map')?.classList.remove('mn-picking');
  }
  function close() {
    const run = active;
    if (!run) return;
    active = null;
    endPick(); pause(run); run.request?.abort(); destroyScene(run);
    if ($('dialog').open) $('dialog').close();
    const target = run.trigger?.isConnected && run.trigger.getClientRects().length ? run.trigger : document.getElementById('map');
    target?.focus({preventScroll:true});
  }
  function source(url) {
    try {
      const link = new URL(url);
      if (link.protocol === 'https:' && !link.username && !link.password) return link.href;
    } catch { /* Use the catalogue home when metadata has no source URL. */ }
    return 'https://globalmeteornetwork.org/';
  }
  function eventSummary(event) {
    $('event-title').textContent = event ? (event.id === NYSA ? 'Meteor nad Nysą' : 'Meteor · ' + at(event.start) + ' UTC') : 'Wybrany meteor';
    $('height').textContent = event ? amount.format(event.begin.alt_km) + ' → ' + amount.format(event.end.alt_km) + ' km' : '—';
    $('duration').textContent = event ? measurement(event.duration, 's') : '—';
    $('velocity').textContent = event ? measurement(event.speed_kms, 'km/s') : '—';
    $('magnitude').textContent = event ? measurement(event.magnitude, 'mag') : '—';
  }
  function modes(run) {
    for (const mode of ['night','trajectory','ground']) {
      $(mode).disabled = !run.event;
      $(mode).setAttribute('aria-pressed',String(mode === run.mode));
    }
    $('dialog').dataset.mode = run.mode;
    $('dialog').dataset.eventId = run.event?.id || '';
    $('legend').hidden = !run.event || run.mode !== 'night' || $('dialog').dataset.scene !== 'ready';
  }
  function displayTime(run) {
    $('time').value = String(Math.round((run.time - run.min) * run.ticksPerSecond));
    const label = at(run.time, run.mode !== 'night') + ' UTC';
    if ($('clock').textContent !== label) {
      $('clock').textContent = label;
      $('time').setAttribute('aria-valuetext',label);
    }
    run.scene?.draw(run.time);
  }
  function rateOptions(run) {
    const overview = run.mode === 'night';
    const rates = overview ? ['events','60','600','3600'] : ['0.1','0.25','0.5','1','2'];
    $('speed').replaceChildren(...rates.map(rate => new Option(rate === 'events' ? 'W rytmie zjawisk' : amount.format(+rate) + '×',rate)));
    $('speed').value = overview ? run.nightRate : run.flightRate;
    rateNote(run);
  }
  function rateNote(run) {
    $('play-note').textContent = run.mode === 'night' && run.nightRate === 'events'
      ? 'Przerwy w przyspieszeniu, przeloty w zwolnieniu.' : '';
  }
  function configureTimeline(run) {
    const overview = run.mode === 'night', event = run.event;
    run.min = overview ? run.data.start : event.start;
    run.max = overview ? run.data.end : finish(event);
    const slider = $('time');
    // Some range controls truncate large decimal UNIX timestamps, hiding
    // a meteor at the first frame or stopping it short of the endpoint.
    run.ticksPerSecond = overview ? 1 : 1000;
    run.lastTick = Math.max(1, Math.round((run.max - run.min) * run.ticksPerSecond));
    slider.min = '0'; slider.max = String(run.lastTick); slider.step = '1';
    slider.dataset.unit = overview ? 's' : 'ms';
    slider.dataset.start = String(run.min); slider.dataset.end = String(run.max);
    $('interval').textContent = overview ? dayFormat.format(run.min * 1000) + ' – ' + dayFormat.format(run.max * 1000) : measurement(event.duration, 's') + ' lotu';
    const marks = overview ? run.data.events.map(item => 1000 * (item.start - run.min) / (run.max - run.min)) : [0,1000];
    $('marks').setAttribute('d', marks.map(x => 'M' + x.toFixed(2) + ' 0v12').join(' '));
    for (const id of ['time','play','speed']) $(id).disabled = false;
    rateOptions(run);
  }
  function nearest(run, place) {
    const rad = Math.PI / 180;
    let shortest = Infinity;
    for (const event of run.data.events) {
      const target = event.begin;
      const a = Math.sin((target.lat - place.lat) * rad / 2) ** 2 +
        Math.cos(place.lat * rad) * Math.cos(target.lat * rad) * Math.sin((target.lon - place.lon) * rad / 2) ** 2;
      if (a < shortest) {shortest = a; run.nearest = event;}
    }
    const km = 2 * 6371.0088 * Math.asin(Math.sqrt(Math.min(1,shortest)));
    $('nearest').dataset.eventId = run.nearest.id;
    $('nearest').disabled = false;
    $('nearest').textContent = 'Najbliższy początek · ' + amount.format(Math.round(km * 10) / 10) + ' km';
  }
  function direction(run) {
    const place = observer();
    nearest(run,place);
    let result;
    if (run.scene) result = run.scene.setView(run.mode, run.event, place);
    const parts = [];
    if (run.mode === 'ground') {
      if (Number.isFinite(result?.azimuth_deg) && Number.isFinite(result.elevation_deg)) {
        parts.push('Azymut ' + amount.format(result.azimuth_deg) + '°, wysokość ' + amount.format(result.elevation_deg) + '° w połowie trasy.');
      }
      if (result?.visible === false) parts.push('Cała trajektoria poniżej horyzontu.');
      parts.push('Perspektywa geometryczna. Widok pomija zachmurzenie, zabudowę i lokalny teren.');
    }
    $('direction').textContent = parts.join(' ');
  }
  function select(run, mode, event = run.event) {
    if (!event || !run.data || active !== run) return;
    const changed = run.event !== event;
    pause(run);
    if (changed || run.mode !== mode) {
      if (mode !== 'night' && (changed || run.mode === 'night')) {
        run.time = event.start + event.duration / 2;
        run.preview = true;
      } else if (mode === 'night') {
        run.time = event.start;
        run.preview = false;
      }
    }
    run.mode = mode; run.event = event;
    modes(run); eventSummary(event); configureTimeline(run);
    if (run.selectedButton) run.selectedButton.removeAttribute('aria-current');
    run.selectedButton = run.buttons.get(event.id);
    run.selectedButton?.setAttribute('aria-current','true');
    direction(run); displayTime(run);
  }
  function chooseTrajectory(run, event) {
    select(run,'trajectory',event);
    if (window.matchMedia('(max-width: 740px)').matches) $('dialog').scrollTop = 0;
  }
  function clear(run) {
    pause(run); destroyScene(run);
    run.data = null; run.event = null; run.mode = 'night'; run.selectedButton = null; run.buttons = new Map();
    $('dialog').dataset.scene = 'idle';
    $('list').replaceChildren(); $('marks').removeAttribute('d'); $('featured').hidden = true;
    $('clock').textContent = '—'; $('interval').textContent = ''; $('direction').textContent = '';
    $('scene-note').textContent = ''; $('play-note').textContent = ''; $('speed').replaceChildren();
    $('time').value = '0'; $('time').removeAttribute('aria-valuetext');
    run.nearest = null; $('nearest').textContent = 'Najbliższy początek'; delete $('nearest').dataset.eventId;
    for (const id of ['time','play','speed','observer','pick','nearest']) $(id).disabled = true;
    modes(run); eventSummary(null); $('source').href = source('');
  }
  function listEvents(run) {
    const fragment = document.createDocumentFragment();
    for (const item of run.data.events) {
      const row = document.createElement('li'), button = document.createElement('button');
      button.type = 'button'; button.dataset.eventId = item.id;
      const label = document.createElement('strong'), duration = document.createElement('span');
      label.textContent = at(item.start, true) + ' UTC';
      duration.textContent = (item.id === NYSA ? 'Nysa · ' : '') + measurement(item.duration, 's');
      button.append(label, duration); row.append(button); fragment.append(row); run.buttons.set(item.id,button);
    }
    $('list').append(fragment);
  }
  async function renderScene(run, version) {
    const current = () => active === run && run.version === version && $('dialog').open;
    function failure(reason) {
      if (!current()) return;
      $('dialog').dataset.scene = 'unavailable';
      $('legend').hidden = true;
      $('scene-note').textContent = (typeof reason === 'string' ? reason : 'Widok 3D jest niedostępny.') + ' Możesz przeglądać godziny i parametry meteorów w katalogu.';
      queueMicrotask(() => {if (current() && run.scene) destroyScene(run);});
    }
    $('dialog').dataset.scene = 'loading'; $('scene-note').textContent = 'Wczytywanie sceny 3D…';
    try {
      const C = await window.WiciScene3D.loadEngine();
      if (!current()) return;
      run.scene = window.WiciMeteorScene.create($('scene'), C, {onPick:id => {
        const item = run.data?.events.find(e => e.id === id);
        if (item && current()) chooseTrajectory(run,item);
      }, onError:failure});
      if ($('dialog').dataset.scene === 'unavailable') {destroyScene(run); return;}
      run.scene.setNight(run.data); direction(run); displayTime(run);
      if ($('dialog').dataset.scene !== 'unavailable') {
        $('scene-note').textContent = ''; $('dialog').dataset.scene = 'ready';
        $('legend').hidden = run.mode !== 'night';
      }
    } catch {
      if (!current()) return;
      destroyScene(run); failure();
    }
  }
  async function load(run, date) {
    const version = ++run.version;
    run.request?.abort(); run.request = new AbortController(); clear(run);
    $('dialog').dataset.state = 'loading'; $('example').hidden = true;
    $('status').textContent = 'Wczytywanie obserwacji GMN…'; $('date').value = date;
    try {
      const data = await context.api('/meteors/night?date=' + encodeURIComponent(date), null, {signal:run.request.signal,timeoutMs:60000});
      if (active !== run || version !== run.version) return;
      if (data?.date !== date || !Array.isArray(data.events) || !Number.isFinite(data.start) || !(data.end > data.start)) throw Error('Nieprawidłowy zapis nocy.');
      const events = data.events.slice().sort((a,b) => a.start - b.start);
      run.data = {...data,events}; $('source').href = source(data.source_url);
      $('example').hidden = date === SAMPLE;
      if (!events.length) {
        $('dialog').dataset.state = 'empty';
        $('status').textContent = 'Brak opublikowanych trajektorii zaczynających się nad Polską. Katalog GMN może pojawić się z opóźnieniem.';
        return;
      }
      const featured = events.find(item => item.id === NYSA);
      $('featured').hidden = !featured;
      if (featured) $('featured').querySelector('span').textContent = at(featured.start) + ' UTC · ' + measurement(featured.duration, 's') + ' · Zobacz trajektorię';
      $('status').textContent = 'Trajektorie w katalogu: ' + events.length + (data.bundled ? ' · zapis lokalny' : '');
      $('dialog').dataset.state = 'ready';
      $('observer').disabled = false; $('pick').disabled = !context.getMap?.() || !document.getElementById('atlas3d-scene')?.hidden;
      listEvents(run);
      run.time = (featured || events[0]).start; select(run,'night',featured || events[0]);
      await renderScene(run,version);
    } catch (error) {
      if (active !== run || version !== run.version) return;
      clear(run); $('dialog').dataset.state = 'error';
      $('status').textContent = error.message || 'Nie udało się odczytać nocy z katalogu GMN.';
      $('example').hidden = date === SAMPLE;
    }
  }
  // In event-paced playback a long step stops exactly at the next observed onset.
  // Even subsecond meteors are therefore displayed for their full slowed duration.
  function nightStep(events, time, delta) {
    let next = Infinity;
    for (const event of events) {
      if (event.start > time) { next = event.start; break; }
      if (time < finish(event)) return time + delta * 0.2;
    }
    return Math.min(next, time + delta * 7200);
  }
  function play(run) {
    if (!run.event) return;
    if (run.playing) {pause(run); return;}
    if (run.preview || run.time >= run.max - 0.00001) run.time = run.min;
    run.preview = false; run.playing = true;
    $('play').textContent = 'Pauza'; $('play').setAttribute('aria-pressed','true');
    let last = performance.now();
    function frame(now) {
      if (!run.playing || active !== run) return;
      const delta = Math.min((now - last) / 1000, 0.15);
      last = now;
      const rate = $('speed').value;
      run.time = Math.min(run.max, rate === 'events' ? nightStep(run.data.events,run.time,delta) : run.time + delta * Number(rate));
      displayTime(run);
      if (run.time >= run.max) pause(run);
      else run.raf = requestAnimationFrame(frame);
    }
    displayTime(run);
    run.raf = requestAnimationFrame(frame);
  }
  function pickPoint(run) {
    const map = context.getMap?.();
    if (!map || !run.event || picking) return;
    pause(run);
    const container = map.getContainer(), layers = document.getElementById('layer-panel');
    const wasOpen = layers?.open;
    if (layers) layers.open = false;
    $('dialog').close();
    const pick = picking = new AbortController();
    container.classList.add('mn-picking');
    $('map-prompt').hidden = false;
    container.focus({preventScroll:true});
    container.scrollIntoView({block:'nearest'});
    const resume = point => {
      if (picking !== pick || active !== run) return;
      endPick();
      if (layers && wasOpen) layers.open = true;
      $('dialog').showModal();
      if (point && Number.isFinite(point.lat) && Number.isFinite(point.lng)) {
        run.custom = {lat:point.lat,lon:((point.lng + 180) % 360 + 360) % 360 - 180};
        let option = $('observer').querySelector('option[value="custom"]');
        if (!option) {option = new Option('', 'custom'); $('observer').add(option);}
        const coord = new Intl.NumberFormat('pl-PL',{maximumFractionDigits:3});
        option.textContent = 'Punkt (' + coord.format(run.custom.lat) + '°, ' + coord.format(run.custom.lon) + '°)';
        $('observer').value = 'custom';
        select(run,'ground');
      }
      $('pick').focus({preventScroll:true});
      if (!run.scene && $('dialog').dataset.scene === 'loading') renderScene(run,++run.version);
    };
    const capture = {capture:true,signal:pick.signal};
    let down = null;
    container.addEventListener('pointerdown', e => {down = [e.clientX,e.clientY];},capture);
    container.addEventListener('click', e => {
      if (e.target.closest?.('.leaflet-control') || e.button !== 0) return;
      e.stopImmediatePropagation(); e.preventDefault();
      if (down && Math.hypot(e.clientX-down[0], e.clientY-down[1]) > 8) return;
      resume(map.mouseEventToLatLng(e));
    },capture);
    $('pick-center').addEventListener('click', () => resume(map.getCenter()),{signal:pick.signal});
    $('pick-cancel').addEventListener('click', () => resume(null),{signal:pick.signal});
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {e.preventDefault(); e.stopImmediatePropagation(); resume(null);}
      else if (e.key === 'Enter' && e.target === container) {e.preventDefault(); resume(map.getCenter());}
    },capture);
    document.addEventListener('click', e => {
      if (e.target.closest?.('.tab')) close();
    },{signal:pick.signal});
  }
  function open(trigger) {
    if (active || !context) return;
    const run = active = {trigger,version:0,scene:null,request:null,nightRate:'events',flightRate:'0.25',
      mode:'night',custom:null,playing:false,raf:0,preview:false};
    $('observer').querySelector('option[value="custom"]')?.remove();
    $('observer').value = 'nysa';
    $('date').min = '2018-12-09'; $('date').max = mostRecentNight();
    $('date-hint').textContent = context.isDemo?.() ? 'Tryb demonstracyjny zawiera noc z 4 na 5 listopada 2026 r.' :
      'Noc obejmuje okres od południa do południa czasu polskiego.';
    $('dialog').showModal(); $('close').focus({preventScroll:true});
    return load(run,SAMPLE);
  }
  function init(options) {
    if (context) return;
    context = options;
    $('open').addEventListener('click', event => open(event.currentTarget));
    $('close').addEventListener('click', close);
    $('dialog').addEventListener('click', event => event.stopPropagation());
    $('dialog').addEventListener('keydown', event => {
      if (event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); close();}
    });
    $('dialog').addEventListener('cancel', event => {event.preventDefault(); close();});
    $('form').addEventListener('submit', event => {
      event.preventDefault();
      if (active && $('date').validity.valid) load(active,$('date').value);
    });
    $('example').addEventListener('click', () => {if (active) load(active,SAMPLE);});
    for (const mode of ['night','trajectory','ground']) $(mode).addEventListener('click', () => {if (active) select(active,mode);});
    $('featured').addEventListener('click', () => {
      const event = active?.data?.events.find(e => e.id === NYSA);
      if (event) chooseTrajectory(active,event);
    });
    $('list').addEventListener('click', e => {
      const id = e.target.closest('button')?.dataset.eventId;
      const event = active?.data?.events.find(item => item.id === id);
      if (event) chooseTrajectory(active,event);
    });
    $('observer').addEventListener('change', () => {if (active) select(active,'ground');});
    $('nearest').addEventListener('click', () => {
      if (!active?.nearest) return;
      select(active,'ground',active.nearest);
      if (window.matchMedia('(max-width: 740px)').matches) $('dialog').scrollTop = 0;
    });
    $('pick').addEventListener('click', () => {if (active) pickPoint(active);});
    $('play').addEventListener('click', () => {if (active) play(active);});
    $('speed').addEventListener('change', () => {
      if (!active) return;
      if (active.mode === 'night') active.nightRate = $('speed').value;
      else active.flightRate = $('speed').value;
      rateNote(active);
    });
    $('time').addEventListener('input', () => {
      if (!active?.event) return;
      const run = active, tick = Number($('time').value);
      pause(run); run.preview = false;
      if (tick === 0) run.time = run.min;
      else if (tick === run.lastTick) run.time = run.max;
      else run.time = run.min + tick / run.ticksPerSecond;
      displayTime(run);
    });
    document.addEventListener('visibilitychange', () => {if (document.hidden && active) pause(active);});
  }
  return {init,open,close};
})();
