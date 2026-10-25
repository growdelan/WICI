'use strict';
/* Serializable intent state. Network responses and Leaflet handles belong to controllers. */
(function (root) {
  const TYPES = ['communication', 'hydro_station', 'air_quality_station', 'area', 'aircraft', 'ship', 'ua_region', 'civil_alert', 'custom_area'];
  const movingRef = ref => typeof ref === 'string' && /^(aircraft:icao:[a-f0-9]{6}|ship:mmsi:[1-9]\d{8})$/.test(ref);
  const regionRef = ref => typeof ref === 'string' && /^ua_region:neptun:(oblast|raion):[^\r\n]+$/.test(ref);
  const timezones = ['Europe/Warsaw', 'Europe/Kyiv', 'UTC'];
  const comparedRegions = refs => [...new Set((Array.isArray(refs) ? refs : []).filter(regionRef))].slice(0, 5);
  const compared = refs => [...new Set((Array.isArray(refs) ? refs : []).filter(movingRef))].slice(0, 5);
  function initialState() {
    return {query: {types: ['communication'], source_ids: [], q: '', province: null, country: null, region_ref: null,
      time: {mode: 'live', overview_range: null, filter_range: null}, include_periods: true,
      include_unlocated: true, include_without_samples: true, watched_only: false, sort: {field: 'label', direction: 'asc'}, page_size: 100},
    selectedRef: null, selectedVersion: null, selectedSensor: null, selectedMetric: null, graphMode: 'map', tableScope: 'catalog',
    cursorAt: null, comparedRefs: [], comparedRegionRefs: [], displayTimezone: 'Europe/Warsaw', detailOpen: false, layout: {tablePercent: 42, mobilePanel: 'table'},
    columns: ['label', 'type', 'updated_at', 'measurement'], savedViewId: null, queryRevision: 0, detailRevision: 0, dataRevision: null, asOf: null, loading: false, error: null};
  }
  function changed(state, query) {
    return {...state, query, queryRevision: state.queryRevision + 1, cursorAt: null, error: null};
  }
  function reducer(state, action) {
    switch (action.type) {
      case 'SET_QUERY': return changed(state, {...state.query, ...action.patch});
      case 'SET_REGION': return changed(state, {...state.query, province: action.province || null});
      case 'SET_TIME_RANGE': return changed(state, {...state.query, time: {mode: 'range',
        overview_range: action.overview || action.range, filter_range: action.range}});
      case 'RETURN_TO_LIVE': return changed(state, {...state.query, time: {mode: 'live', overview_range: null, filter_range: null}});
      case 'REFRESH': return {...state, queryRevision: state.queryRevision + 1, error: null};
      case 'SELECT_OBJECT': return {...state, selectedRef: action.ref, selectedVersion: action.version || null,
        selectedSensor: action.ref === state.selectedRef ? state.selectedSensor : null,
        selectedMetric: action.ref === state.selectedRef ? state.selectedMetric : null,
        detailOpen: true, detailRevision: state.detailRevision + 1};
      case 'SELECT_SENSOR': return {...state, selectedSensor: action.sensor || null, selectedMetric: action.metric || null,
        detailRevision: state.detailRevision + 1};
      case 'CLOSE_CARD': return {...state, detailOpen: false, detailRevision: state.detailRevision + 1};
      case 'SET_CURSOR': {
        const range = state.query.time.filter_range, value = Date.parse(action.at);
        if (!range || !Number.isFinite(value) || value < Date.parse(range.from) || value >= Date.parse(range.to)) return state;
        return {...state, cursorAt: new Date(value).toISOString()};
      }
      case 'SET_COLUMNS': return {...state, columns: action.columns.includes('label') ? action.columns : ['label', ...action.columns]};
      case 'SET_GRAPH_MODE': return ['map', 'graph', 'both'].includes(action.mode) ? {...state, graphMode: action.mode} : state;
      case 'SET_TABLE_SCOPE': return ['catalog', 'graph'].includes(action.scope) ? {...state, tableScope: action.scope} : state;
      case 'SET_LAYOUT': return {...state, layout: {...state.layout, ...action.patch}};
      case 'TOGGLE_COMPARE': {
        if (!movingRef(action.ref)) return state;
        if (state.comparedRefs.includes(action.ref)) return {...state, comparedRefs: state.comparedRefs.filter(ref => ref !== action.ref)};
        return state.comparedRefs.length >= 5 ? state : {...state, comparedRefs: [...state.comparedRefs, action.ref]};
      }
      case 'TOGGLE_REGION_COMPARE': {
        if (!regionRef(action.ref)) return state;
        const refs = state.comparedRegionRefs || [];
        if (refs.includes(action.ref)) return {...state, comparedRegionRefs: refs.filter(ref => ref !== action.ref)};
        return refs.length >= 5 ? state : {...state, comparedRegionRefs: [...refs, action.ref]};
      }
      case 'CLEAR_REGION_COMPARE': return {...state, comparedRegionRefs: []};
      case 'SET_TIMEZONE': return timezones.includes(action.timezone) ? {...state, displayTimezone: action.timezone} : state;
      case 'CLEAR_COMPARE': return {...state, comparedRefs: []};
      case 'APPLY_VIEW': {
        const config = action.config || {}, query = {...initialState().query, ...config.query};
        if (query.time?.mode === 'range') {const normalize = range => range ? {from: range.from || range.start, to: range.to || range.end} : null; query.time = {...query.time, overview_range: normalize(query.time.overview_range), filter_range: normalize(query.time.filter_range)};}
        const next = changed(state, query);
        return {...next, graphMode: config.layout?.mobilePanel === 'graph' ? 'graph' : 'map', tableScope: 'catalog', layout: {...state.layout, ...config.layout}, savedViewId: action.id || null,
          columns: config.columns || state.columns, selectedRef: config.selectedRef || null, detailOpen: Boolean(config.selectedRef), selectedVersion: null,
          selectedSensor: null, selectedMetric: null, comparedRefs: compared(config.comparedRefs), comparedRegionRefs: comparedRegions(config.comparedRegionRefs), displayTimezone: timezones.includes(config.displayTimezone) ? config.displayTimezone : 'Europe/Warsaw', detailRevision: state.detailRevision + 1};
      }
      case 'VIEW_SAVED': return {...state, savedViewId: action.id};
      case 'DATA_LOADING': return {...state, loading: true, error: null};
      case 'DATA_READY': return action.revision !== state.queryRevision ? state : {...state, loading: false,
        dataRevision: action.dataRevision, asOf: action.asOf, error: null};
      case 'DATA_FAILED': return action.revision !== state.queryRevision ? state : {...state, loading: false, error: action.error};
      default: return state;
    }
  }
  function createStore(seed) {
    let state = {...initialState(), ...seed}; const listeners = new Set();
    return {getState: () => state, dispatch(action) {const previous = state; state = reducer(state, action);
      if (state !== previous) for (const listener of listeners) listener(state, previous, action); return state;},
    subscribe(listener) {listeners.add(listener); return () => listeners.delete(listener);}};
  }
  function sampleAt(samples, cursorAt, range, sensor, metric) {
    const limit = cursorAt ? Date.parse(cursorAt) : Infinity, lower = range ? Date.parse(range.from) : -Infinity,
      upper = range ? Date.parse(range.to) : Infinity;
    return (samples || []).filter(sample => {
      const time = Date.parse(sample.observed_at || sample.at);
      return Number.isFinite(time) && time >= lower && time < upper && time <= limit &&
        (!sensor || String(sample.sensor_id) === String(sensor)) && (!metric || sample.metric === metric) &&
        !['future', 'unknown_time'].includes(sample.quality || sample.time_status);
    }).sort((a, b) => Date.parse(b.observed_at || b.at) - Date.parse(a.observed_at || a.at) || (b.revision || 0) - (a.revision || 0))[0] || null;
  }
  const exported = {TYPES, initialState, reducer, createStore, sampleAt, movingRef, regionRef, timezones};
  root.WiciWorkspaceStore = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(typeof window !== 'undefined' ? window : globalThis);
