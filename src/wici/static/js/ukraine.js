'use strict';
window.WiciUkraine = (() => {
  const $ = id => document.getElementById(`ukraine-${id}`);
  const SOURCE = 'https://neptun.in.ua/';
  const ATTRIBUTION = '<a href="https://neptun.in.ua/" target="_blank" rel="noopener noreferrer">NEPTUN · alerty Ukrainy</a>';
  const MAX_SNAPSHOT_AGE = 90000, MAX_POSITION_AGE = 420000;
  const MAX_GEOMETRY_AGE = 24 * 60 * 60 * 1000;
  const BOUNDS = [[44.1, 14.0], [55.0, 40.3]];
  const TYPES = {uav:'Dron',recon:'Dron rozpoznawczy',missile:'Rakieta',ballistic:'Zagrożenie balistyczne',kab:'Bomba kierowana',mig31k:'MiG-31K',unknown:'Nieustalony typ'};
  let map, api, health = {}, visible = true, snapshot = null, geometry = null, base = null;
  let generation = 0, controller = null, fetching = false, poll = null, aging = null, failures = 0;
  let geometryError = '', attributed = false, active = false, focusPending = false;
  let geometryIndex = new Map(), countryPolygons = [];
  const alertLayers = new Map(), threatLayers = new Map(), reportCards = new Map();
  let emptyReports = null;
  const node = (tag, text, className) => { const e = document.createElement(tag); if(text != null)e.textContent = String(text); if(className)e.className = className; return e; };
  const shown = () => Boolean(map && visible && !document.hidden && $('enabled').checked);
  const live = () => shown() && health.mode === 'live';
  const date = value => { const t = Date.parse(value); return Number.isFinite(t) ? new Intl.DateTimeFormat('pl-PL',{timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'medium'}).format(new Date(t)) : 'Nie podano'; };
  const age = value => { const t = Date.parse(value); return Number.isFinite(t) ? Date.now() - t : Infinity; };
  const stale = feed => !feed || feed.stale || feed.status === 'error' || age(feed.fetched_at) > MAX_SNAPSHOT_AGE || age(feed.fetched_at) < -60000;
  function status(text, warning = false) { $('status').textContent = text; $('status').classList.toggle('notice', warning); }
  function legends(enabled) { for(const id of ['legend','map-legend','map-label'])$(id).hidden = !enabled; }
  function sourceLink() { const a = node('a','NEPTUN · źródło danych'); a.href = SOURCE; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
  function field(parent, label, value) { if(value != null && value !== '')parent.append(node('p',`${label}: ${value}`)); }
  function focus() { if(map)map.fitBounds(BOUNDS,{padding:[35,55],maxZoom:6}); }
  function attribute(enabled) {
    if(enabled === attributed)return;
    attributed = enabled;
    if(enabled)map.attributionControl?.addAttribution(ATTRIBUTION);
    else map.attributionControl?.removeAttribution(ATTRIBUTION);
  }
  function clearMap() {
    if(base)map.removeLayer(base); base = null;
    for(const entries of [alertLayers,threatLayers]) { for(const entry of entries.values())map.removeLayer(entry.layer); entries.clear(); }
  }
  function cancel() {
    generation++; controller?.abort(); controller = null; fetching = false;
    if(poll !== null)clearTimeout(poll); poll = null;
    if(aging !== null)clearInterval(aging); aging = null;
  }
  // GeoJSON uses longitude/latitude. An exterior ring includes its boundary;
  // holes exclude theirs. No bounding-box-only acceptance of a threat position.
  function inRing(point, ring) {
    let inside = false;
    for(let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[j], b = ring[i]; if(!a || !b)continue;
      const cross = (point[0]-a[0])*(b[1]-a[1]) - (point[1]-a[1])*(b[0]-a[0]);
      if(Math.abs(cross) < 1e-10 && point[0] >= Math.min(a[0],b[0]) && point[0] <= Math.max(a[0],b[0]) && point[1] >= Math.min(a[1],b[1]) && point[1] <= Math.max(a[1],b[1]))return true;
      if((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])inside = !inside;
    }
    return inside;
  }
  function polygonParts(feature) {
    const g = feature?.geometry;
    return g?.type === 'Polygon' ? [g.coordinates] : g?.type === 'MultiPolygon' ? g.coordinates : [];
  }
  function prepareGeometry(value) {
    geometry = value; geometryIndex = new Map(); countryPolygons = [];
    for(const [scope, collection] of [['oblast',value.oblasts],['raion',value.raions]]) {
      for(const feature of collection?.features || []) {
        const key = feature.properties?.key;
        // Duplicate keys must never silently select a different administrative area.
        if(typeof key === 'string' && key) {
          const id = `${scope}:${key}`;
          geometryIndex.set(id,geometryIndex.has(id) ? null : feature);
        }
        if(scope === 'oblast')for(const rings of polygonParts(feature)) {
          if(!rings?.[0]?.length)continue;
          const bbox = [Infinity,Infinity,-Infinity,-Infinity];
          for(const [x,y] of rings[0]) { bbox[0] = Math.min(bbox[0],x); bbox[1] = Math.min(bbox[1],y); bbox[2] = Math.max(bbox[2],x); bbox[3] = Math.max(bbox[3],y); }
          countryPolygons.push({rings,bbox});
        }
      }
    }
    if(base)map.removeLayer(base); base = null;
    for(const entry of alertLayers.values())map.removeLayer(entry.layer); alertLayers.clear();
  }
  function inUkraine(lat, lon) {
    return countryPolygons.some(({rings,bbox}) => lon >= bbox[0] && lat >= bbox[1] && lon <= bbox[2] && lat <= bbox[3]
      && inRing([lon,lat],rings[0]) && !rings.slice(1).some(ring => inRing([lon,lat],ring)));
  }
  function alertName(item) { return item.name || item.key || 'Obszar alarmu'; }
  function alertLevel(item, old) { return old ? 'Nieaktualny odczyt — stan alarmu niepotwierdzony' : ({red:'Aktywny alarm',yellow:'Ostrzeżenie / częściowy alarm',unknown:'Nieustalony poziom alarmu'}[item.level] || 'Nieustalony poziom alarmu'); }
  function alertPopup(item, old) {
    const body = node('div',null,'ukraine-popup');
    body.append(node('h3',alertName(item)),node('p',alertLevel(item,old),old?'notice':''));
    field(body,'Jednostka',item.scope === 'raion' ? 'Rejon' : 'Obwód');
    field(body,'Początek według źródła',date(item.since));
    field(body,'Powody według źródła',(item.reasons || []).join(' · ') || 'Nie podano');
    field(body,'Ostatni poprawny odczyt',date(snapshot?.alerts?.fetched_at));
    field(body,'Zmiana stanu u źródła',date(snapshot?.alerts?.updated_at));
    body.append(node('p','Alarm przekazany przez agregator NEPTUN. Brak alarmu na mapie nie potwierdza bezpieczeństwa.'),sourceLink());
    return body;
  }
  function noPointReason(item) {
    if(item.area_only)return 'Doniesienie obszarowe — bez dokładnego punktu.';
    if(item.status && item.status !== 'active')return 'Zgłoszenie nieaktywne — bez bieżącego punktu.';
    if(stale(snapshot?.threats))return 'Nieaktualny odczyt doniesień — punkt ukryty.';
    if(age(item.updated_at) > MAX_POSITION_AGE || age(item.updated_at) < -60000)return 'Brak aktualnego czasu pozycji lub doniesienie starsze niż 7 minut — punkt ukryty.';
    if(!Number.isFinite(item.latitude) || !Number.isFinite(item.longitude))return 'Brak współrzędnych — doniesienie dostępne na liście.';
    if(!countryPolygons.length)return 'Brak granic do weryfikacji lokalizacji — punkt ukryty.';
    if(!inUkraine(item.latitude,item.longitude))return 'Współrzędne poza geometrią Ukrainy — punkt ukryty.';
    return '';
  }
  function threatBody(item, reason) {
    const body = node('div',null,'ukraine-popup');
    body.append(node('h3',item.title || TYPES[item.type] || TYPES.unknown));
    body.append(node('p',item.advisory ? 'Informacja orientacyjna / ostrzegawcza.' : `Doniesienie: ${TYPES[item.type] || TYPES.unknown}. To nie potwierdzone uderzenie.`));
    field(body,'Obszar',[item.region,item.district,item.locality].filter(Boolean).join(' · ') || 'Nie podano');
    field(body,'Aktualizacja doniesienia',date(item.updated_at));
    field(body,'Ostatni poprawny odczyt',date(snapshot?.threats?.fetched_at));
    field(body,'Czas serwera źródła',date(snapshot?.threats?.server_time));
    if(reason)body.append(node('p',reason,'notice'));
    field(body,'Dokładność według źródła',item.position_quality || 'Nie podano');
    field(body,'Niepewność lokalizacji',Number.isFinite(item.uncertainty_km) ? `${item.uncertainty_km} km` : 'Nie podano');
    field(body,'Pewność według źródła',item.confidence);
    field(body,'Liczba źródeł',item.source_count);
    field(body,'Liczba obiektów według źródła',item.count);
    field(body,'Opis źródłowy',item.description);
    body.append(node('p','Lokalizacja doniesienia może być przybliżona. Mapa nie wyznacza toru lotu ani bieżącej pozycji obiektu.'),sourceLink());
    return body;
  }
  function updatePopup(entry, content, tooltip) {
    if(entry.layer.setPopupContent)entry.layer.setPopupContent(content);
    else entry.layer.bindPopup(content,{maxWidth:370,maxHeight:360});
    if(entry.layer.setTooltipContent)entry.layer.setTooltipContent(tooltip);
  }
  function render() {
    if(!live())return;
    if(geometry?.oblasts?.features?.length && !base) {
      base = L.geoJSON(geometry.oblasts,{pane:'ukraineBorders',style:{color:'#567d9d',weight:1.4,fillColor:'#d5e4ed',fillOpacity:.08},onEachFeature:(f,l)=>l.bindTooltip(node('span',f.properties.region || f.properties.name || f.properties.key || 'Ukraina'),{sticky:true})}).addTo(map);
    }
    const alerts = snapshot?.alerts?.items || [], oldAlerts = stale(snapshot?.alerts), wantedAlerts = new Set(), unmapped = [];
    for(const item of alerts) {
      const id = `${item.scope}:${item.key}`, feature = geometryIndex.get(id);
      if(!feature) { unmapped.push(item); continue; }
      wantedAlerts.add(id);
      const neutral = oldAlerts || !['red','yellow'].includes(item.level);
      const color = neutral ? '#71818b' : item.level === 'red' ? '#b43642' : '#bc8a15';
      const style = {color,weight:2,fillColor:color,fillOpacity:neutral?.13:.28,dashArray:neutral?'5 5':undefined};
      const content = alertPopup(item,oldAlerts), tooltip = node('span',`${alertName(item)} · ${alertLevel(item,oldAlerts)}`);
      let entry = alertLayers.get(id);
      if(!entry) {
        const layer = L.geoJSON(feature,{pane:item.scope === 'raion'?'ukraineRaionAlerts':'ukraineOblastAlerts',style}).bindPopup(content,{maxWidth:370,maxHeight:360}).bindTooltip(tooltip,{sticky:true}).addTo(map);
        entry = {layer}; alertLayers.set(id,entry);
      } else { entry.layer.setStyle(style); updatePopup(entry,content,tooltip); }
    }
    for(const [id,entry] of alertLayers)if(!wantedAlerts.has(id)) { map.removeLayer(entry.layer); alertLayers.delete(id); }
    const threats = snapshot?.threats?.items || [], wantedThreats = new Set();
    let hiddenPoints = 0;
    const list = $('list'), wantedReports = new Set();
    for(const item of threats) {
      const reason = noPointReason(item);
      const reportId = String(item.id); wantedReports.add(reportId);
      const title = `${item.advisory?'Informacja':TYPES[item.type] || TYPES.unknown} · ${item.locality || item.district || item.region || 'Lokalizacja niepodana'} · ${date(item.updated_at)}`;
      const signature = JSON.stringify([item,reason,snapshot?.threats?.fetched_at,snapshot?.threats?.server_time]);
      let card = reportCards.get(reportId);
      if(!card) {
        const article = node('details',null,'ukraine-report'), summary = node('summary',title), body = threatBody(item,reason);
        article.dataset.reportId = reportId; article.append(summary,body); list.append(article);
        card = {article,summary,body,signature}; reportCards.set(reportId,card);
      } else if(card.signature !== signature) {
        card.summary.textContent = title;
        // Keep the details and summary nodes stable so keyboard focus and open state survive polling.
        const focusedSource = card.body.contains(document.activeElement);
        const body = threatBody(item,reason); card.body.replaceWith(body); card.body = body; card.signature = signature;
        if(focusedSource)body.querySelector('a')?.focus({preventScroll:true});
      }
      if(reason) { hiddenPoints++; continue; }
      const id = String(item.id); wantedThreats.add(id);
      const neutral = item.advisory || !TYPES[item.type] || item.type === 'unknown';
      const style = {radius:7,color:neutral?'#576d7b':'#8a4b20',weight:2,fillColor:neutral?'#9baab3':'#e29a4b',fillOpacity:.9,dashArray:neutral?'3 3':undefined};
      const content = threatBody(item,''), tooltip = node('span',`${item.advisory?'Informacja': 'Doniesienie'} · ${TYPES[item.type] || TYPES.unknown} · ${date(item.updated_at)}`);
      let entry = threatLayers.get(id);
      if(!entry) {
        const layer = L.circleMarker([item.latitude,item.longitude],{...style,pane:'ukraineReports',className:'ukraine-report-marker',bubblingMouseEvents:false}).bindPopup(content,{maxWidth:370,maxHeight:360}).bindTooltip(tooltip).addTo(map);
        threatLayers.set(id,{layer});
      } else { entry.layer.setLatLng([item.latitude,item.longitude]); entry.layer.setStyle(style); updatePopup(entry,content,tooltip); }
    }
    for(const [id,entry] of threatLayers)if(!wantedThreats.has(id)) { map.removeLayer(entry.layer); threatLayers.delete(id); }
    for(const [id,card] of reportCards)if(!wantedReports.has(id)) { card.article.remove(); reportCards.delete(id); }
    if(!threats.length) {
      if(!emptyReports) { emptyReports = node('p'); list.append(emptyReports); }
      emptyReports.textContent = !snapshot ? 'Oczekiwanie na odczyt doniesień.' : stale(snapshot.threats) ? 'Brak aktualnego odczytu doniesień. Stan zagrożeń niepotwierdzony.' : 'Brak doniesień w ostatnim odczycie. Nie potwierdza to braku zagrożenia.';
    } else if(emptyReports) { emptyReports.remove(); emptyReports = null; }
    $('reports-count').textContent = `Doniesienia (${threats.length}; bez punktu: ${hiddenPoints})`;
    const missing = $('unmapped-alerts'); missing.replaceChildren();
    for(const item of unmapped)missing.append(node('p',`${alertName(item)} · ${alertLevel(item,oldAlerts)} · brak jednoznacznej geometrii (${item.scope || 'nieustalony zakres'}).`));
    $('unmapped').hidden = !unmapped.length;
    legends(true); $('reports-panel').hidden = false;
    report(unmapped.length,hiddenPoints);
  }
  function report(unmapped = 0, hiddenPoints = 0) {
    if(!snapshot) { status(geometryError || 'Wczytywanie danych NEPTUN…',Boolean(geometryError)); return; }
    if(['disabled','demo_no_data'].includes(snapshot.status)) { status(snapshot.message || 'Dane NEPTUN niedostępne.'); return; }
    const alerts = snapshot.alerts, threats = snapshot.threats;
    const oldAlerts = stale(alerts), oldThreats = stale(threats);
    const parts = [oldAlerts ? 'Alarmy: odczyt nieaktualny; szare obszary nie potwierdzają bieżącego stanu.' : `Obszary alarmów: ${alerts?.items?.length || 0}.`,
      `Odczyt alarmów: ${date(alerts?.fetched_at)}.`, oldThreats ? 'Doniesienia: odczyt nieaktualny, punkty ukryte.' : `Punkty doniesień: ${threatLayers.size}.`,
      `Odczyt doniesień: ${date(threats?.fetched_at)}.`];
    if(unmapped)parts.push(`Alarmy bez geometrii: ${unmapped}.`);
    if(hiddenPoints)parts.push(`Doniesienia bez punktu: ${hiddenPoints}; szczegóły na liście.`);
    for(const feed of [alerts,threats])if(feed?.invalid_count)parts.push(`Pominięte nieprawidłowe rekordy: ${feed.invalid_count}.`);
    if(threats?.stale_count)parts.push(`Pominięte stare doniesienia: ${threats.stale_count}.`);
    for(const feed of [alerts,threats])if(feed?.error)parts.push(feed.error);
    if(geometryError)parts.push(geometryError);
    if(snapshot.message)parts.push(snapshot.message);
    parts.push('Brak oznaczeń nie oznacza braku zagrożenia.');
    status(parts.join(' '),oldAlerts || oldThreats || Boolean(geometryError) || snapshot.status !== 'ready');
  }
  function schedule() {
    if(poll !== null)clearTimeout(poll); poll = null;
    if(!live())return;
    const requested = Number(snapshot?.retry_after_seconds) || Number(snapshot?.refresh_seconds) || 15;
    const seconds = Math.min(3600,Math.max(15,requested,failures ? Math.min(300,15 * (2 ** Math.min(failures,5))) : 0));
    poll = setTimeout(()=>{poll = null; load();},seconds*1000);
  }
  async function load() {
    if(!live() || fetching)return;
    fetching = true; const run = generation; controller = new AbortController();
    const options = {signal:controller.signal,timeoutMs:35000};
    try {
      // Use the backend fetch time so opening a tab cannot extend its 24-hour cache.
      const geometryAge = age(geometry?.fetched_at);
      const needsGeometry = !geometry?.oblasts?.features?.length || geometry.status !== 'ready'
        || geometryAge >= MAX_GEOMETRY_AGE || geometryAge < -60000;
      const jobs = [api('/ukraine',undefined,options)];
      if(needsGeometry)jobs.push(api('/ukraine/geometry',undefined,options));
      const results = await Promise.allSettled(jobs);
      if(run !== generation || !live())return;
      const result = results[0];
      if(result.status === 'fulfilled') { snapshot = result.value; failures = snapshot.status === 'error' ? failures+1 : 0; }
      else {
        failures++;
        snapshot = {...snapshot,status:'error',message:'Nie udało się odświeżyć NEPTUN. Stan zagrożeń pozostaje niepotwierdzony.',alerts:{...snapshot?.alerts,stale:true},threats:{...snapshot?.threats,stale:true}};
      }
      if(needsGeometry) {
        const result = results[1];
        if(result.status === 'fulfilled' && (result.value?.oblasts?.features?.length || result.value?.raions?.features?.length)) {
          prepareGeometry(result.value); geometryError = result.value.status === 'ready' ? '' : result.value.message || 'Niepełne granice Ukrainy; część alarmów może być dostępna tylko na liście.';
        } else geometryError = result.status === 'fulfilled' ? result.value.message || 'Granice Ukrainy niedostępne; alarmy i doniesienia pozostają na liście.' : 'Nie udało się odczytać granic Ukrainy; alarmy i doniesienia pozostają na liście.';
      }
      render();
    } finally {
      if(run === generation) { fetching = false; controller = null; schedule(); }
    }
  }
  function sync(options = {}) {
    if(!map)return;
    if(options.visible !== undefined)visible = options.visible;
    if(options.health)health = options.health;
    if(!shown()) {
      cancel(); clearMap(); attribute(false); active = false;
      legends(false); $('reports-panel').hidden = true; $('unmapped').hidden = true;
      status($('enabled').checked ? 'Pobieranie NEPTUN wstrzymane poza widoczną mapą.' : 'Warstwa Ukrainy wyłączona.');
      return;
    }
    if(focusPending) { focusPending = false; focus(); }
    attribute(true);
    if(!live()) {
      cancel(); clearMap(); active = false;
      legends(false); $('reports-panel').hidden = true; $('unmapped').hidden = true;
      status(health.mode === 'demo' ? 'NEPTUN wyłączony w demonstracji. Brak pobierania danych i rzeczywistych alarmów Ukrainy.' : 'NEPTUN oczekuje na sprawdzenie trybu aplikacji.');
      return;
    }
    if(!active) { active = true; render(); load(); }
    if(aging === null)aging = setInterval(()=>{if(live())render();},15000);
  }
  function init(options) {
    if(map || !options.map)return;
    map = options.map; api = options.api; health = options.health || {};
    for(const [name,z] of [['ukraineBorders',205],['ukraineOblastAlerts',365],['ukraineRaionAlerts',370],['ukraineReports',485]])map.createPane(name).style.zIndex = String(z);
    $('enabled').addEventListener('change',()=>{focusPending = $('enabled').checked; sync();});
    $('fit').addEventListener('click',focus);
    sync({visible:options.visible !== false});
  }
  return {init,sync};
})();
