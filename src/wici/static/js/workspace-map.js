'use strict';
window.WiciWorkspaceMap = function ({map, geometries, select, narrow}) {
  const U = window.WiciWorkspaceUI; let group = null, currentData = null, active = false; const layers = new Map();
  const colors = {communication: '#c38235', hydro_station: '#16819c', air_quality_station: '#787e91', area: '#587a8a'};
  function clear() {if (group && map) map.removeLayer(group); group = null; layers.clear();}
  function areaFeatures(item) {return (item.areas || item.area_refs || []).map(area => geometries?.get(String(typeof area === 'string' ? area.replace('area:prg:', '') : area.admin_code))).filter(Boolean);}
  function coordinates(item) {const lat = item.latitude ?? item.geometry?.coordinates?.[1], lon = item.longitude ?? item.geometry?.coordinates?.[0];
    return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;}
  function register(ref, layer, item) {if (!layers.has(ref)) layers.set(ref, []); layers.get(ref).push({layer, item});}
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
    // The station's measurement freshness says nothing about its official index.
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
    return colors[item.type] || '#587a8a';
  }
  function render(data, state, selectedSample, selectedIndex) {
    if (!active || !map || !window.L) return;
    const referenceAt = state.query?.time?.mode === 'range' ? Date.parse(state.query.time.filter_range?.to) - 1 : Date.parse(data?.as_of || state.asOf);
    if (data !== currentData) {
      currentData = data; clear(); group = L.layerGroup().addTo(map);
      const result = data?.map || {}, items = result.items || [], points = result.points || items.filter(item => coordinates(item)), areas = result.areas || items.filter(item => !coordinates(item) && item.ref);
      for (const item of points) {const coords = coordinates(item); if (!coords) continue;
        const marker = L.circleMarker(coords, {radius: 6, color: color(item, U.measurement(item), referenceAt), weight: 2, fillOpacity: .8});
        marker.bindTooltip(U.el('span', `${item.label} · ${U.value(U.measurement(item))}`)); marker.on('click', () => select(item.ref)); marker.addTo(group); register(item.ref, marker, item);
      }
      const grouped = new Map();
      for (const item of areas) for (const feature of areaFeatures(item)) {const key = String(feature.properties?.admin_code || feature.id);
        if (!grouped.has(key)) grouped.set(key, {feature, items: []}); const collection = grouped.get(key).items; if (!collection.some(existing => existing.ref === item.ref)) collection.push(item);
      }
      for (const {feature, items: areaItems} of grouped.values()) {const layer = L.geoJSON(feature, {style: {color: '#587a8a', weight: 1.5, fillOpacity: .13}}).bindPopup(popup(areaItems)).addTo(group);
        if (areaItems.length === 1) layer.on('click', () => select(areaItems[0].ref)); for (const item of areaItems) register(item.ref, layer, item);
      }
      for (const aggregate of result.aggregates || (result.mode === 'aggregates' ? items.filter(item => item.count) : [])) {
        const feature = geometries?.get(String(aggregate.province)); if (!feature) continue;
        const layer = L.geoJSON(feature, {style: {color: colors[aggregate.type], weight: 2, fillOpacity: .26}});
        layer.bindTooltip(U.el('span', `${aggregate.count} · ${U.typeNames[aggregate.type]} · zawęź zakres`)); layer.on('click', () => narrow(aggregate)); layer.addTo(group);
      }
    }
    const visited = new Set();
    for (const [ref, entries] of layers) for (const {layer, item} of entries) {
      if (visited.has(layer)) continue; visited.add(layer);
      const selected = state.detailOpen && entries.some(() => ref === state.selectedRef) || [...(layers.get(state.selectedRef) || [])].some(entry => entry.layer === layer) && state.detailOpen;
      const sample = selected && item.type.endsWith('_station') && (state.cursorAt || selectedSample) ? selectedSample : U.measurement(item);
      const shown = selected && state.cursorAt ? {...item, official_index: selectedIndex} : item;
      const colorAt = selected && state.cursorAt ? Date.parse(state.cursorAt) : referenceAt;
      const style = {weight: selected ? 4 : 1.5, fillOpacity: selected ? .7 : coordinates(item) ? .8 : .13, color: color(shown, sample, colorAt)};
      layer.setStyle?.(style); if (coordinates(item)) {layer.setRadius?.(selected ? 10 : 6); layer.setTooltipContent?.(U.el('span', `${item.label} · ${U.value(sample)}${selected && state.cursorAt ? ' · Według kursora' : ''}`));}
    }
  }
  function show(item) {if (!map || !item) return false; const coords = coordinates(item); if (coords) {map.setView(coords, Math.max(map.getZoom(), 10)); return true;}
    const features = areaFeatures(item); if (features.length) {const bounds = L.geoJSON({type: 'FeatureCollection', features}).getBounds(); if (bounds.isValid()) {map.fitBounds(bounds, {padding: [30, 40], maxZoom: 10}); return true;}} return false;
  }
  return {render, show, setActive(value) {active = value; if (!value) {clear(); currentData = null;}}, destroy: clear};
};
