'use strict';
window.WiciImagery = (() => {
  const node = (tag, text, className) => { const item = document.createElement(tag); if (text != null) item.textContent = text; if (className) item.className = className; return item; };
  const timestamp = value => {
    if (!value) return 'Nie podano';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Nie podano';
    return new Intl.DateTimeFormat('pl-PL', {timeZone:'Europe/Warsaw', dateStyle:'medium', ...(/^\d{4}-\d{2}-\d{2}$/.test(value) ? {} : {timeStyle:'short'})}).format(date);
  };
  const previewPath = value => typeof value === 'string' && /^\/api\/imagery\/preview\/[a-zA-Z0-9_-]+$/.test(value) ? value : null;
  const sourceUrl = value => { if (previewPath(value)) return value; try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } };
  let map, api, group, visible = true, generation = 0, active = false, loading = false, data = null, point = null, lastError = '';
  const controls = {};
  const shown = () => visible && !document.hidden && controls.enabled.checked;
  function status(message, warning = false) { controls.status.textContent = message; controls.status.classList.toggle('notice', warning); }
  function card(item, popup = false) {
    const article = node('article', null, 'imagery-card');
    article.append(node('h4', item.title || 'Zobrazowanie bez tytułu'), node('p', `${item.source || 'Źródło nieznane'} · Produkt kartograficzny · nie fotografia`, 'imagery-meta'));
    const details = node('dl');
    details.append(node('dt', 'Wykonanie zobrazowania'), node('dd', item.acquired_at ? timestamp(item.acquired_at) : 'Data nieudostępniona przez źródło'));
    if (item.acquisition_end) details.append(node('dt', 'Koniec pozyskiwania'), node('dd', timestamp(item.acquisition_end)));
    if (item.product_at) details.append(node('dt', 'Publikacja produktu'), node('dd', timestamp(item.product_at)));
    article.append(details);
    if (item.attribution) article.append(node('p', item.attribution, 'imagery-meta'));
    if (item.license) article.append(node('p', `Licencja: ${item.license}`, 'imagery-meta'));
    const path = previewPath(item.preview_url);
    const url = sourceUrl(item.source_url);
    const previewTarget = url || path;
    const previewLabel = url ? 'Otwórz materiał źródłowy' : 'Otwórz miniaturę';
    if (path) {
      const link = node('a', `${previewLabel} ↗`); link.href = previewTarget; link.target = '_blank'; link.rel = 'noopener noreferrer';
      if (!popup) {
        const image = node('img'); image.src = path; image.alt = `${previewLabel}: ${item.title || 'zobrazowanie'} (${item.source || 'źródło nieznane'})`; image.loading = 'lazy'; image.decoding = 'async'; image.referrerPolicy = 'no-referrer';
        image.addEventListener('error', () => { image.hidden = true; article.append(node('p', 'Podgląd jest chwilowo niedostępny. Otwórz materiał źródłowy.')); });
        link.append(image);
      }
      article.append(link);
    } else if (!popup) article.append(node('p', 'Źródło nie udostępnia podglądu tego materiału.'));
    if (url && (!path || url !== previewTarget)) { const link = node('a', 'Otwórz materiał źródłowy ↗'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; article.append(link); }
    return article;
  }
  function validBounds(bounds) {
    return Array.isArray(bounds) && bounds.length === 2 && bounds.every(pair => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite)) && bounds[0][0] >= -90 && bounds[1][0] <= 90 && bounds[0][1] >= -180 && bounds[1][1] <= 180 && bounds[0][0] < bounds[1][0] && bounds[0][1] < bounds[1][1];
  }
  function render() {
    group.clearLayers(); controls.gallery.replaceChildren(); controls.providers.replaceChildren();
    controls.center.disabled = !shown(); controls.location.textContent = point ? `Wybrane miejsce: ${point.lat.toFixed(5)}° N, ${point.lng.toFixed(5)}° E` : 'Nie wybrano miejsca.';
    controls.results.hidden = !shown() || !data;
    if (!shown()) { status(controls.enabled.checked ? 'Zobrazowania wstrzymane, gdy mapa jest ukryta.' : 'Warstwa zobrazowań wyłączona.'); return; }
    if (point) {
      const summary = loading ? 'Zobrazowania: wyszukiwanie…' : lastError ? 'Zobrazowania: błąd odczytu' : data ? `Zobrazowania: ${data.items?.length || 0} materiałów` : 'Wybrane miejsce';
      const box = node('div'); box.append(node('p', summary));
      const button = node('button', 'Pokaż materiały i stan źródeł'); button.type = 'button';
      button.addEventListener('click', event => { event?.stopPropagation(); document.getElementById('layer-panel').open = true; document.getElementById('imagery-group').open = true; controls.status.scrollIntoView({block:'nearest'}); controls.center.focus({preventScroll:true}); map.closePopup(); });
      box.append(button);
      L.circleMarker([point.lat, point.lng], {radius:7, color:'#754a12', weight:3, fillColor:'#ffdb8b', fillOpacity:1, bubblingMouseEvents:false, className:'imagery-selected-point'}).bindTooltip(`${summary} · kliknij punkt`, {permanent:true, direction:'top'}).bindPopup(box).addTo(group);
    }
    if (loading) { status('Wyszukiwanie materiałów dla wskazanego miejsca…'); return; }
    if (lastError) { status(`Nie udało się pobrać zobrazowań: ${lastError}. Wybierz miejsce ponownie, aby spróbować.`, true); return; }
    if (!data) { status('Kliknij miejsce na mapie lub wybierz środek mapy, aby wyszukać materiały.'); return; }
    const items = Array.isArray(data.items) ? data.items : [];
    for (const provider of data.providers || []) controls.providers.append(node('li', `${provider.source || 'Źródło'}: ${provider.message || ({ready:'Odczyt poprawny',success:'Odczyt poprawny',empty:'Brak materiałów',error:'Błąd odczytu',disabled:'Źródło wyłączone'}[provider.status] || provider.status || 'Brak informacji')}`));
    for (const item of items) {
      controls.gallery.append(card(item));
      if (validBounds(item.bounds)) L.rectangle(item.bounds, {color:'#7541a1', weight:2, fill:false, bubblingMouseEvents:false, className:'imagery-footprint'}).bindPopup(() => card(item, true)).addTo(group);
    }
    status(`${items.length ? `Znaleziono materiałów: ${items.length}.` : 'Brak materiałów dla wskazanego miejsca.'}${data.message ? ` ${data.message}` : ''}${data.fetched_at ? ` Odczyt: ${timestamp(data.fetched_at)}.` : ''}`, data.enabled === false || ['error','partial','disabled','disabled_in_demo'].includes(data.status));
  }
  async function select(latlng) {
    if (!shown() || !latlng || !Number.isFinite(latlng.lat) || Math.abs(latlng.lat) > 90 || !Number.isFinite(latlng.lng)) return;
    const candidate = {lat:latlng.lat, lng:latlng.lng >= -180 && latlng.lng <= 180 ? latlng.lng : ((latlng.lng + 180) % 360 + 360) % 360 - 180};
    if(window.WiciRegion&&!window.WiciRegion.contains(candidate.lat,candidate.lng)){controls.status.textContent='Wskaż miejsce w wybranym województwie.';return;}
    point=candidate;
    const request = ++generation; data = null; lastError = ''; loading = true; render();
    try {
      const result = await api(`/imagery?lat=${encodeURIComponent(point.lat)}&lon=${encodeURIComponent(point.lng)}`);
      if (request !== generation || !shown()) return;
      data = result;
    } catch (error) { if (request === generation && shown()) lastError = error.message || 'Błąd odczytu'; }
    finally { if (request === generation) { loading = false; render(); } }
  }
  function sync(options = {}) {
    if (!map) return;
    if (options.visible !== undefined) visible = options.visible;
    const next = shown();
    if (next === active) return;
    active = next;
    if (!next) { generation++; loading = false; }
    render();
  }
  function init(options) {
    if (map) return;
    map = options.map; api = options.api; visible = options.visible !== false;
    for (const name of ['enabled','center','status','location','results','providers','gallery']) controls[name] = document.getElementById(`imagery-${name}`);
    group = L.layerGroup().addTo(map);
    controls.enabled.addEventListener('change', () => { generation++; loading = false; data = null; point = null; lastError = ''; active = shown(); render(); });
    controls.center.addEventListener('click', () => select(map.getCenter()));
    map.getContainer().addEventListener('click', event => {
      if (!shown() || event.button > 0) return;
      if (event.target?.closest?.('.leaflet-marker-icon,.leaflet-popup,.leaflet-control,.imagery-footprint,.imagery-selected-point')) return;
      if (map.dragging?.moved() || map.boxZoom?.moved()) return;
      // Capture before Leaflet popup handlers consume area clicks. Picking a place is exclusive.
      event.stopPropagation();
      map.closePopup();
      select(map.mouseEventToLatLng(event));
    }, true);
    document.addEventListener('wici:regionchange',()=>{
      if(!point||!window.WiciRegion||window.WiciRegion.contains(point.lat,point.lng))return;
      generation++;loading=false;data=null;point=null;lastError='';render();
    });
    document.addEventListener('visibilitychange', () => sync());
    active = shown(); render();
  }
  return {init, sync};
})();
