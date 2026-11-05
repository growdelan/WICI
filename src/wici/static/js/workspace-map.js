'use strict';
window.WiciWorkspaceMap = function ({map, geometries, select, narrow, markerStyle = 'circle'}) {
  const U = window.WiciWorkspaceUI, M = window.WiciWorkspaceMotion, A = window.WiciWorkspaceAlerts;
  const groups = new Map(), points = new Map(), areas = new Map(), aggregates = new Map(), alertLayers = new Map(), replayMarkers = new Map(), graphPoints = new Map(), graphAreas = new Map();
  const featureCache = new WeakMap();
  const emptyAreas = [];
  let active = false, routeGroup = null, lastReplay = null, lastRouteKey = '', areaGroups = null, graphOrderDirty = false;
  const colors = {communication: '#c38235', hydro_station: '#16819c', air_quality_station: '#787e91', area: '#587a8a', aircraft: '#237a99', ship: '#93682f'};
  let graphPaneName = null;
  function graphPane() {
    if (markerStyle !== 'symbol' || !map?.createPane) return {};
    if (!graphPaneName) {
      graphPaneName = 'wici-analysis-graph';
      const pane = map.getPane?.(graphPaneName) || map.createPane(graphPaneName);
      // Graph evidence must stay above the base marker pane (600), including
      // polygons. SVG bringToFront alone cannot cross a Leaflet pane boundary.
      pane.style.zIndex = '625';
    }
    return {pane: graphPaneName};
  }
  function symbolIcon(item, color, selected) {
    const symbol = U.el('span', null, `analysis-point-symbol${selected ? ' is-selected' : ''}`);
    symbol.dataset.type = item.type; symbol.style.setProperty('--marker-color', color);
    symbol.setAttribute('aria-hidden', 'true'); symbol.append(U.icon(item.type, 'analysis-point-glyph'));
    return L.divIcon({className: 'analysis-symbol-marker', html: symbol, iconSize: [30, 30], iconAnchor: [15, 15], tooltipAnchor: [0, -18]});
  }
  function symbolAccessibility(entry, item, text, selected) {
    const element = entry.layer.getElement?.(); if (!element) return;
    if (entry.element !== element) {
      entry.element = element; entry.accessibility = null;
      element.setAttribute('role', 'button'); element.setAttribute('tabindex', '0');
      // Leaflet handles Enter for keyboard markers; provide the other button key.
      element.addEventListener('keydown', event => {if (event.key === ' ') {event.preventDefault(); select(item.ref);}});
    }
    const label = `${U.typeNames[item.type] || item.type}: ${text}`, key = `${label}|${selected}`;
    if (entry.accessibility === key) return;
    entry.accessibility = key; element.title = item.label;
    element.setAttribute('aria-label', label); element.setAttribute('aria-pressed', String(Boolean(selected)));
  }
  function group(name) {if (!groups.has(name)) groups.set(name, L.layerGroup().addTo(map)); return groups.get(name);}
  function prune(records, wanted) {for (const [key, entry] of records) if (!wanted.has(key)) {entry.group.removeLayer(entry.layer); records.delete(key);}}
  function clear() {
    for (const layer of groups.values()) map?.removeLayer(layer);
    if (routeGroup) map?.removeLayer(routeGroup);
    groups.clear(); for (const records of [points, areas, aggregates, alertLayers, replayMarkers, graphPoints, graphAreas]) records.clear();
    routeGroup = lastReplay = areaGroups = null; lastRouteKey = ''; graphOrderDirty = false;
  }
  function areaFeatures(item) {
    if (item.geometry?.type && item.geometry.type !== 'Point') {
      if (item.geometry.type === 'FeatureCollection') return item.geometry.features;
      if (item.geometry.type === 'Feature') return [item.geometry];
      const cached = featureCache.get(item); if (cached?.geometry === item.geometry) return cached.features;
      const features = [{type: 'Feature', properties: {ref: item.ref}, geometry: item.geometry}];
      featureCache.set(item, {geometry: item.geometry, features}); return features;
    }
    return (item.areas || item.area_refs || []).map(area => geometries?.get(String(typeof area === 'string' ? area.replace('area:prg:', '') : area.admin_code))).filter(Boolean);
  }
  function coordinates(item) {const lat = item.latitude ?? item.geometry?.coordinates?.[1], lon = item.longitude ?? item.geometry?.coordinates?.[0];
    return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;}
  function groupAreas(source, historical, overrides) {
    const overrideKey = overrides.size ? JSON.stringify([...overrides].sort()) : '';
    if (areaGroups?.source === source && areaGroups.historical === historical && areaGroups.overrideKey === overrideKey) return areaGroups;
    const grouped = new Map(), refs = new Set();
    // Map snapshots are immutable. Cursor/selection changes only affect styling;
    // membership changes on a new snapshot, mode or graph override set.
    for (const item of source) {
      const ref = item.ref;
      if (overrides.has(ref) || historical && ['ua_region', 'civil_alert'].includes(item.type)) continue;
      areaFeatures(item).forEach((feature, index) => {
        const key = String(['ua_region', 'civil_alert'].includes(item.type) ? item.region_ref || ref : feature.properties?.admin_code || feature.id || `${ref}:${index}`);
        if (!grouped.has(key)) grouped.set(key, {feature, items: [], byRef: new Map()}); const value = grouped.get(key);
        if (!value.byRef.has(ref)) {value.byRef.set(ref, item); if (item.type === 'ua_region') value.items.unshift(item); else value.items.push(item);}
        refs.add(ref);
      });
    }
    areaGroups = {source, historical, overrideKey, grouped, refs}; return areaGroups;
  }
  function transportValue(item, point) {return {...item.metadata, ...point, track: point?.heading};}
  function transportIcon(item, point, referenceAt, selected, className) {
    const value = transportValue(item, point);
    return item.type === 'aircraft' ? window.WiciAircraft.icon(value, {selected, className})
      : window.WiciShips.icon(value, {selected, className, referenceAt});
  }
  function transportKey(item, point, referenceAt, selected, className) {
    const value = transportValue(item, point), observed = Date.parse(value.position_at);
    return JSON.stringify([item.type, value.military, value.type_code, value.heading, value.course, value.track,
      !Number.isFinite(observed) || referenceAt - observed > 300000, selected, className]);
  }
  function transportText(item, point, note) {
    const classification = item.type === 'ship' ? window.WiciShips.classification(item.metadata || {}).label
      : item.metadata?.military === true ? 'Wojskowy według źródła' : item.metadata?.military === false ? 'Pozostałe według źródła' : 'Klasyfikacja nieustalona';
    return `${item.label} · ${classification} · ${M.number(point?.speed_kmh, 'km/h')} · ${note}`;
  }
  function popup(items) {const box = U.el('div', null, 'analysis-map-popup'); box.append(U.el('strong', items.length > 1 ? `${items.length} obiektów obszaru` : U.typeNames[items[0].type]));
    for (const item of items) box.append(U.button(item.label, () => select(item.ref))); return box;}
  function freshAt(observation, referenceAt) {
    const observed = Date.parse(observation?.observed_at), reference = Number(referenceAt);
    return Boolean(observation && Number.isFinite(observed) && Number.isFinite(reference) &&
      (!observation.quality || observation.quality === 'valid') &&
      !['error', 'unknown_time', 'future', 'no_data'].includes(observation.time_status || observation.status) &&
      reference >= observed && reference - observed <= 10800000);
  }
  function color(item, sample, referenceAt) {
    if (['ua_region', 'civil_alert'].includes(item.type)) return A?.colors[A.objectState(item)] || '#73808b';
    if (item.type === 'air_quality_station') {
      const index = Object.prototype.hasOwnProperty.call(item, 'official_index') ? item.official_index : item.metadata?.index || item.index;
      return freshAt(index, referenceAt) && Number.isInteger(index.value) && index.value >= 0 && index.value <= 5
        ? ['#459a77', '#80a24c', '#c1ac42', '#c98b3d', '#c95b48', '#9c4050'][index.value] : '#7e8990';
    }
    if (item.type === 'hydro_station') {
      if (!freshAt(sample, referenceAt) || !Number.isFinite(sample.value)) return '#7e8990';
      const threshold = sample.thresholds || sample.provenance?.thresholds || {}, warning = threshold.warning_level_cm, alarm = threshold.alarm_level_cm;
      if (sample.metric === 'water_level') {
        if (Number.isFinite(alarm) && sample.value >= alarm) return '#bc4145';
        if (Number.isFinite(warning) && sample.value >= warning) return '#b78a28';
        if (!Number.isFinite(alarm) && !Number.isFinite(warning)) return '#7e8990';
      }
    }
    return item.type === 'custom_area' ? item.metadata?.color || item.color || '#217c83' : colors[item.type] || '#587a8a';
  }
  function areaColor(item, chosen, selectedSample, selectedIndex, referenceAt, cursor) {
    const sample = chosen && item.type?.endsWith('_station') && (cursor || selectedSample) ? selectedSample : U.measurement(item);
    const shown = chosen && cursor ? {...item, official_index: selectedIndex} : item;
    return color(shown, sample, referenceAt);
  }
  function tooltip(entry, text) {
    if (entry.tooltip === text) return;
    entry.tooltip = text; entry.layer.setTooltipContent(U.el('span', text));
  }
  function style(entry, value) {
    const key = JSON.stringify(value); if (key === entry.style) return;
    entry.style = key; entry.layer.setStyle?.(value);
  }
  function point(records, name, item, coords, {referenceAt, selected, sample, index, cursor, className = '', note = '', graph = false}) {
    const moving = Boolean(M?.isMoving(item)), symbol = !moving && !graph && markerStyle === 'symbol' && typeof U.icon === 'function';
    const kind = moving ? item.type : symbol ? 'symbol' : 'circle', position = item.position;
    const shown = cursor && selected ? {...item, official_index: index} : item;
    const presentation = {weight: selected ? 4 : moving ? 2 : 1.5, fillOpacity: graph ? .85 : selected ? .7 : .8, color: color(shown, sample, referenceAt)};
    const iconKey = moving ? transportKey(item, position, referenceAt, selected, className) : symbol ? `${item.type}|${presentation.color}|${selected}` : null;
    const radius = selected ? 10 : graph ? 7 : 6;
    const text = moving ? transportText(item, position, note) : `${item.label} · ${U.value(sample)}${graph ? ` · ${U.date(sample?.observed_at)} · węzeł grafu` : ''}${cursor && selected || graph && cursor ? ' · Według kursora' : ''}`;
    let entry = records.get(item.ref);
    if (entry && entry.kind !== kind) {entry.group.removeLayer(entry.layer); records.delete(item.ref); entry = null;}
    if (!entry) {
      const layer = moving ? L.marker(coords, {icon: transportIcon(item, position, referenceAt, selected, className), title: item.label, bubblingMouseEvents: false})
        : symbol ? L.marker(coords, {icon: symbolIcon(item, presentation.color, selected), title: item.label, keyboard: true, bubblingMouseEvents: false})
          : L.circleMarker(coords, {...presentation, radius, ...(className ? {className} : {}), ...(graph ? graphPane() : {})});
      layer.bindTooltip(U.el('span', text), moving || graph ? {className: 'analysis-transport-tooltip'} : {});
      layer.on('click', () => select(item.ref)); const owner = group(name); layer.addTo(owner);
      if (!moving) graphOrderDirty = true;
      entry = {layer, group: owner, kind, coords, iconKey, style: JSON.stringify(presentation), radius, tooltip: text, title: item.label}; records.set(item.ref, entry);
    } else {
      if (entry.coords[0] !== coords[0] || entry.coords[1] !== coords[1]) {entry.layer.setLatLng(coords); entry.coords = coords;}
      if (entry.title !== item.label) {entry.title = item.label; entry.layer.options.title = item.label; const element = entry.layer.getElement?.(); if (element) element.title = item.label;}
      if (moving) {if (entry.iconKey !== iconKey) {entry.iconKey = iconKey; entry.layer.setIcon(transportIcon(item, position, referenceAt, selected, className));}}
      else if (symbol) {if (entry.iconKey !== iconKey) {entry.iconKey = iconKey; entry.layer.setIcon(symbolIcon(item, presentation.color, selected));}}
      else {style(entry, presentation); if (entry.radius !== radius) {entry.radius = radius; entry.layer.setRadius?.(radius);}}
      tooltip(entry, text);
    }
    if (symbol) symbolAccessibility(entry, item, text, selected);
  }
  function area(records, name, key, feature, items, presentation, text = null, click = null) {
    let entry = records.get(key);
    const popupKey = text === null ? entry?.items === items ? entry.popupKey : JSON.stringify(items.map(item => [item.ref, item.label, item.type])) : null;
    // PRG features keep their identity. Source/custom geometry can be replaced
    // with an equal JSON value on refresh without replacing its Leaflet layer.
    const geometryKey = entry?.feature === feature ? entry.geometryKey : JSON.stringify(feature);
    if (entry && entry.geometryKey !== geometryKey) {entry.group.removeLayer(entry.layer); records.delete(key); entry = null;}
    if (!entry) {
      const layer = L.geoJSON(feature, {style: presentation, ...(name === 'graph' ? graphPane() : {})}); const owner = group(name);
      entry = {layer, group: owner, geometryKey, feature, items, style: JSON.stringify(presentation)};
      if (text !== null) {layer.bindTooltip(U.el('span', text)); entry.tooltip = text;}
      else layer.bindPopup(popup(items));
      layer.on('click', () => {if (entry.click) entry.click(); else if (entry.items.length === 1) select(entry.items[0].ref);});
      layer.addTo(owner); records.set(key, entry); graphOrderDirty = true;
    } else {
      entry.feature = feature; style(entry, presentation);
      if (text !== null) tooltip(entry, text);
      else if (entry.popupKey !== popupKey) entry.layer.setPopupContent(popup(items));
    }
    entry.items = items; entry.click = click; entry.popupKey = popupKey;
    return entry;
  }
  function render(data, state, selectedSample, selectedIndex, motion, alerts, graph) {
    if (!active || !map || !window.L) return;
    const historical = state.query?.time?.mode === 'range', referenceAt = historical ? Date.parse(state.query.time.filter_range?.to) - 1 : Date.parse(data?.as_of || state.asOf);
    const cursorAt = state.cursorAt ? Date.parse(state.cursorAt) : referenceAt, selected = ref => state.detailOpen && state.selectedRef === ref;
    const graphNodes = graph?.nodes || [], overrides = new Set(graphNodes.filter(item => item.metadata_context === 'selected_document_version' || state.cursorAt && item.type?.endsWith('_station')).map(item => item.ref));
    const wanted = new Set(), baseRefs = new Set(), result = data?.map || {};
    for (const item of result.points || []) {
      const coords = coordinates(item); if (overrides.has(item.ref) || !coords || M?.isMoving(item) && historical) continue;
      const chosen = selected(item.ref), sample = chosen && item.type.endsWith('_station') && (state.cursorAt || selectedSample) ? selectedSample : U.measurement(item);
      point(points, 'base', item, coords, {referenceAt: chosen && state.cursorAt ? cursorAt : referenceAt, selected: chosen, sample, index: selectedIndex, cursor: state.cursorAt, className: M?.isMoving(item) ? 'analysis-transport-marker' : '', note: U.statusNames?.[item.freshness] || item.freshness || 'Czas źródłowy'});
      wanted.add(item.ref); baseRefs.add(item.ref);
    }
    prune(points, wanted); wanted.clear();
    const grouped = groupAreas(result.areas || emptyAreas, historical, overrides);
    for (const [key, value] of grouped.grouped) {
      const selectedItem = state.detailOpen ? value.byRef.get(state.selectedRef) : null, chosen = Boolean(selectedItem), item = selectedItem || value.items[0];
      area(areas, 'base', key, value.feature, value.items, {weight: chosen ? 4 : 1.5, fillOpacity: chosen ? .7 : .13,
        color: areaColor(item, chosen, selectedSample, selectedIndex, chosen && state.cursorAt ? cursorAt : referenceAt, state.cursorAt)}); wanted.add(key);
    }
    prune(areas, wanted); wanted.clear();
    for (const item of result.aggregates || []) {
      const feature = geometries?.get(String(item.province)); if (!feature) continue;
      const key = item.ref || `${item.type}:${item.province}`;
      area(aggregates, 'base', key, feature, [item], {color: colors[item.type], weight: 2, fillOpacity: .26}, `${item.count} · ${U.typeNames[item.type]} · zawęź zakres`, () => narrow(item)); wanted.add(key);
    }
    prune(aggregates, wanted); wanted.clear();
    const alarmReplay = historical && !alerts?.loading && !alerts?.error ? alerts?.data : null, alarmRefs = new Set();
    if (alarmReplay && A) for (const series of alarmReplay.series || []) {
      const status = alerts?.frames?.get(series.ref)?.state || 'unknown';
      areaFeatures(series).forEach((feature, index) => {
        const key = `${series.ref}:${index}`;
        area(alertLayers, 'alerts', key, feature, [series], {className: 'analysis-alert-region', color: A.colors[status] || A.colors.unknown, weight: selected(series.ref) ? 4 : 2, fillOpacity: status === 'none' ? .09 : .3, dashArray: status === 'unknown' ? '5 5' : null}, `${series.label} · ${A.stateNames[status] || A.stateNames.unknown} · Według wspólnego kursora`);
        wanted.add(key); alarmRefs.add(series.ref);
      });
    }
    prune(alertLayers, wanted); wanted.clear();
    const replay = historical && !motion?.loading && !motion?.error ? motion?.data : null;
    const routeKey = JSON.stringify([state.query?.time?.filter_range, state.comparedRefs]);
    if (lastReplay !== replay || lastRouteKey !== routeKey) {
      if (routeGroup) map.removeLayer(routeGroup); routeGroup = null; lastReplay = replay; lastRouteKey = routeKey;
      if (replay && M) {
        routeGroup = L.layerGroup().addTo(map); graphOrderDirty = true;
        for (const series of replay.series || []) {const color = M.colors[Math.max(0, (state.comparedRefs || []).indexOf(series.ref))];
          for (const segment of M.segments(series, state.query.time.filter_range)) if (segment.length > 1) L.polyline(segment.map(point => [point.latitude, point.longitude]), {color, weight: 2, opacity: .6, className: 'analysis-recorded-track'}).bindTooltip(U.el('span', `${series.label} · zapisane raporty w całym przedziale`)).addTo(routeGroup);
        }
      }
    }
    if (replay && M) for (const [ref, frame] of motion.frames) {
      if (!frame.point) continue; const series = replay.series.find(item => item.ref === ref); if (!series) continue;
      const item = {...series, label: frame.label || series.label, position: frame.point};
      point(replayMarkers, 'replay', item, [frame.point.latitude, frame.point.longitude], {referenceAt: cursorAt, selected: selected(ref), className: 'analysis-replay-marker', note: `${M.describe(frame, U)} · klasyfikacja z bieżącego katalogu`}); wanted.add(ref);
    }
    prune(replayMarkers, wanted); wanted.clear(); const wantedGraphAreas = new Set();
    for (const item of graphNodes) {
      if (baseRefs.has(item.ref) || grouped.refs.has(item.ref) || replayMarkers.has(item.ref) || alarmRefs.has(item.ref)) continue;
      const chosen = selected(item.ref), sample = chosen && item.type?.endsWith('_station') && (state.cursorAt || selectedSample) ? selectedSample : U.measurement(item), coords = coordinates(item);
      if (coords) {
        point(graphPoints, 'graph', item, coords, {referenceAt: state.cursorAt ? cursorAt : referenceAt, selected: chosen, sample, index: selectedIndex, cursor: state.cursorAt, className: 'analysis-graph-map-marker', note: 'węzeł grafu', graph: true}); wanted.add(item.ref);
      } else areaFeatures(item).forEach((feature, index) => {
        const key = `${item.ref}:${index}`;
        area(graphAreas, 'graph', key, feature, [item], {className: 'analysis-graph-map-area',
          color: areaColor(item, chosen, selectedSample, selectedIndex, state.cursorAt ? cursorAt : referenceAt, state.cursorAt), weight: chosen ? 4 : 2, fillOpacity: .12}, `${item.label} · węzeł grafu`); wantedGraphAreas.add(key);
      });
    }
    prune(graphPoints, wanted); prune(graphAreas, wantedGraphAreas);
    if (graphOrderDirty) {
      // LayerGroup does not own an SVG stacking context. Restore graph priority
      // after new paths, while leaving unchanged cursor frames untouched.
      for (const entry of graphAreas.values()) entry.layer.bringToFront();
      for (const entry of graphPoints.values()) if (entry.kind === 'circle') entry.layer.bringToFront();
      graphOrderDirty = false;
    }
  }
  function show(item) {if (!map || !item) return false; const coords = coordinates(item); if (coords) {map.setView(coords, Math.max(map.getZoom(), 10)); return true;}
    const features = areaFeatures(item); if (features.length) {const bounds = L.geoJSON({type: 'FeatureCollection', features}).getBounds(); if (bounds.isValid()) {map.fitBounds(bounds, {padding: [30, 40], maxZoom: 10}); return true;}} return false;
  }
  function fitTracks(replay) {const points = (replay?.series || []).flatMap(series => M?.pointsInRange(series, replay.range) || []); if (!points.length || !map || !window.L) return false; const bounds = L.latLngBounds(points.map(point => [point.latitude, point.longitude])); map.fitBounds(bounds, {padding: [30, 40], maxZoom: 12}); return true;}
  function fitRegions(context) {const refs = new Set(context?.refs || context?.frames?.keys?.() || []), items = (context?.data?.series || context?.regions || []).filter(item => refs.has(item.ref)), features = items.flatMap(areaFeatures); if (!features.length || !map || !window.L) return false; const bounds = L.geoJSON({type: 'FeatureCollection', features}).getBounds(); if (!bounds.isValid()) return false; map.fitBounds(bounds, {padding: [30, 40], maxZoom: 8}); return true;}
  return {render, show, fitTracks, fitRegions, setActive(value) {active = value; if (!value) clear();}, destroy: clear};
};
