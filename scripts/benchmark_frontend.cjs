// Offline CPU/DOM benchmark. Real Leaflet and application modules, synthetic data.
// NODE_PATH=/path/to/node_modules node scripts/benchmark_frontend.cjs
// No server, provider traffic, local database, or persistent browser profile.
'use strict';
const {chromium} = require('playwright');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');

(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.WICI_CHROMIUM_EXECUTABLE ? {executablePath: process.env.WICI_CHROMIUM_EXECUTABLE} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}}), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => route.abort());
    await page.setContent('<div id="map" style="width:1400px;height:850px"></div><input id="aircraft-enabled" type="checkbox" checked><div id="aircraft-status"></div><input id="ships-enabled" type="checkbox" checked><div id="ships-status"></div><div id="ships-map-legend"></div><button id="ships-baltic"></button>');
    await page.addStyleTag({path: path.join(root, 'src/wici/static/vendor/leaflet/leaflet.css')});
    for (const file of ['vendor/leaflet/leaflet.js', 'js/workspace-store.js', 'js/workspace-table.js']) {
      await page.addScriptTag({path: path.join(root, 'src/wici/static', file)});
    }
    const calculations = await page.evaluate(() => {
      const measure = (fn, runs = 9) => {
        fn(); const times = [];
        for (let run = 0; run < runs; run++) {const start = performance.now(); fn(); times.push(performance.now() - start);}
        times.sort((a, b) => a - b);
        return {median_ms: +times[Math.floor(times.length / 2)].toFixed(3), p95_ms: +times.at(-1).toFixed(3)};
      };
      const start = Date.parse('2026-10-01T00:00:00Z'), count = 5000;
      const samples = Array.from({length: count}, (_, index) => ({observed_at: new Date(start + index * 60000).toISOString(), value: index % 19 ? index : null, metric: 'water_level', revision: index % 3}));
      const range = {from: samples[0].observed_at, to: new Date(start + count * 60000).toISOString()};
      let formatted, selected;
      const formatting = measure(() => {for (let i = 0; i < 1000; i++) {formatted = WiciWorkspaceUI.date(samples[i].observed_at); WiciWorkspaceUI.shortTime(samples[i].observed_at);}});
      const cursor = measure(() => {for (let i = 0; i < 120; i++) selected = WiciWorkspaceStore.sampleAt(samples, new Date(start + (i * 41) * 60000).toISOString(), range, null, 'water_level');}, 5);
      if (selected.value !== 4879 || !formatted) throw Error('Invalid benchmark output');
      return {formatting: {calls_per_run: 2000, ...formatting}, station_cursor: {samples: count, lookups_per_run: 120, ...cursor}};
    });
    await page.evaluate(() => {
      window.benchmarkMap = L.map('map', {zoomAnimation: false, fadeAnimation: false}).setView([52.5, 19], 6);
      window.benchmarkTimers = new Map(); window.benchmarkIntervals = new Map();
      window.benchmarkSnapshot = null; let timer = 0;
      window.benchmarkTurn = () => new Promise(resolve => window.setImmediateForBenchmark(resolve, 0));
      window.setImmediateForBenchmark = window.setTimeout.bind(window);
      window.setTimeout = (fn, ms) => {benchmarkTimers.set(++timer, {fn, ms}); return timer;};
      window.clearTimeout = id => benchmarkTimers.delete(id);
      window.setInterval = (fn, ms) => {benchmarkIntervals.set(++timer, {fn, ms}); return timer;};
      window.clearInterval = id => benchmarkIntervals.delete(id);
      window.fetch = async () => ({ok: true, json: async () => structuredClone(benchmarkSnapshot)});
    });
    for (const file of ['aircraft.js', 'ships.js']) await page.addScriptTag({path: path.join(root, 'src/wici/static/js', file)});
    const transport = await page.evaluate(async () => {
      const results = {};
      for (const kind of ['aircraft', 'ships']) {
        const module = kind === 'aircraft' ? WiciAircraft : WiciShips, now = new Date().toISOString();
        const items = Array.from({length: 1000}, (_, index) => ({hex: index.toString(16).padStart(6, '0'), mmsi: String(261000000 + index), id: `TEST${index}`, name: `Statek ${index}`, type_code: 70,
          latitude: 52.2 + (index % 40) * .002, longitude: 19 + Math.floor(index / 40) * .003, track: 90, heading: 90, speed_kmh: 250, altitude_m: 5000, position_at: now}));
        benchmarkSnapshot = {items, status: 'ready', stale: false};
        module.init({map: benchmarkMap, health: {mode: 'live'}}); module.sync({visible: true}); await benchmarkTurn();
        const operations = {icons: 0, positions: 0}, times = [], icon = L.Marker.prototype.setIcon, position = L.Marker.prototype.setLatLng;
        L.Marker.prototype.setIcon = function (...args) {operations.icons++; return icon.apply(this, args);};
        L.Marker.prototype.setLatLng = function (...args) {operations.positions++; return position.apply(this, args);};
        for (let run = 0; run < 15; run++) {
          const next = [...benchmarkTimers.entries()].find(([, entry]) => entry.ms === 10000);
          if (!next) throw Error(`Missing ${kind} poll`);
          benchmarkTimers.delete(next[0]); const begin = performance.now(); next[1].fn(); await benchmarkTurn();
          void benchmarkMap.getContainer().offsetHeight; times.push(performance.now() - begin);
        }
        L.Marker.prototype.setIcon = icon; L.Marker.prototype.setLatLng = position;
        times.sort((a, b) => a - b);
        results[kind] = {objects: items.length, identical_snapshots: times.length, ...operations,
          median_ms: +times[Math.floor(times.length / 2)].toFixed(3), p95_ms: +times.at(-1).toFixed(3)};
        module.sync({visible: false});
      }
      return results;
    });
    await page.addScriptTag({path: path.join(root, 'src/wici/static/js/region.js')});
    const spatial = await page.evaluate(({provinces, country}) => {
      WiciRegion.init({map: benchmarkMap, provinces, country, select: document.createElement('select')});
      WiciRegion.select('14', {fit: false});
      const points = Array.from({length: 10000}, (_, index) => [49 + Math.floor(index / 100) * .06, 14 + (index % 100) * .105]);
      const measure = (fn, runs = 7) => {const times = []; let value; for (let run = 0; run < runs; run++) {const begin = performance.now(); value = fn(); times.push(performance.now() - begin);} times.sort((a, b) => a - b); return {median_ms: +times[Math.floor(times.length / 2)].toFixed(3), p95_ms: +times.at(-1).toFixed(3), result: value};};
      const membership = measure(() => {let count = 0; for (const [lat, lon] of points) if (WiciRegion.contains(lat, lon)) count++; return count;});
      const bounds = measure(() => {let west; for (let index = 0; index < 100; index++) west = WiciRegion.bounds().getWest(); return west;});
      return {region: '14', points: points.length, membership, bounds_100_calls: bounds};
    }, {provinces: JSON.parse(fs.readFileSync(path.join(root, 'src/wici/static/geo/provinces.geojson'), 'utf8')),
      country: JSON.parse(fs.readFileSync(path.join(root, 'src/wici/static/geo/poland-border.geojson'), 'utf8'))});
    console.log(JSON.stringify({scope: 'Synthetic offline CPU and Leaflet DOM refresh; not GPU FPS or network latency.', browser: browser.version(), ...calculations, transport, spatial, errors}, null, 2));
    if (errors.length) process.exitCode = 1;
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
