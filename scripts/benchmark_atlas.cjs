// Full app + Leaflet on an isolated demo server. Provider requests are blocked.
'use strict';
const {setup} = require('../tests/helpers/atlas_refresh.cjs');
(async () => {
  const env = await setup(1000);
  try {
    const result = await env.page.evaluate(async () => {
      const list = document.getElementById('communication-list'), times = [], mutations = [];
      const observer = new MutationObserver(records => mutations.push(...records));
      observer.observe(list, {childList: true, subtree: true});
      const operations = {geoJSON: 0, markers: 0, removed: 0}, geoJSON = L.geoJSON, marker = L.marker, remove = state.map.removeLayer;
      L.geoJSON = (...args) => {operations.geoJSON++; return geoJSON(...args);};
      L.marker = (...args) => {operations.markers++; return marker(...args);};
      state.map.removeLayer = function (...args) {operations.removed++; return remove.apply(this, args);};
      const originalRead = api, snapshot = {items: structuredClone(state.communications), total: state.communications.length};
      // Separate parsing + presentation from loopback transport and backend cost.
      api = async () => structuredClone(snapshot);
      try {
        for (let run = 0; run < 15; run++) {
          await new Promise(requestAnimationFrame); const start = performance.now();
          await loadCommunications(); void list.offsetHeight; times.push(performance.now() - start);
        }
      } finally {api = originalRead; observer.disconnect(); L.geoJSON = geoJSON; L.marker = marker; state.map.removeLayer = remove;}
      times.sort((a, b) => a - b);
      return {communications: snapshot.items.length, identical_snapshots: times.length, ...operations,
        list_child_mutations: mutations.length, median_ms: +times[7].toFixed(2), p95_ms: +times.at(-1).toFixed(2)};
    });
    console.log(JSON.stringify({scope: 'Offline full Atlas refresh of identical synthetic communication snapshots; CPU/DOM, no provider/network/GPU timing.', browser: env.browserVersion, ...result, errors: env.errors}, null, 2));
    if (env.errors.length) process.exitCode = 1;
  } finally {await env.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
