'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
function createTrack(options) {
  const window = {};
  for (const name of ['aircraft-motion', 'bus-motion']) vm.runInNewContext(fs.readFileSync(`src/wici/static/js/${name}.js`, 'utf8'), {window});
  return window.WiciBusMotion.createTrack(options);
}
const START = Date.parse('2026-10-19T10:00:00Z');
const item = (seconds, values = {}) => ({id: 'warszawa:1001', latitude: 52, longitude: 20, bearing: null,
  speed_kmh: null, position_at: new Date(START + seconds * 1000).toISOString(), ...values});
const near = (actual, expected, tolerance = 1e-6) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);
const north = metres => metres / 6371008.8 * 180 / Math.PI;

test('all four normalized city contracts accept source bearing and nullable speed without inventing telemetry', () => {
  for (const [id, bearing, speed] of [['szczecin:3', 90, 30], ['poznan:ztm:1050', 90, 36],
    ['krakow:103', null, null], ['warszawa:1001', null, null]]) {
    const track = createTrack(); assert.ok(track.push(item(0, {id, bearing, speed_kmh: speed, altitude_m: 999})));
    const sample = track.sample(START);
    assert.equal(sample.track, bearing); assert.equal(sample.speed_kmh, speed);
    assert.equal(sample.course_source, bearing === null ? null : 'reported');
    assert.equal(sample.altitude_m, 0); assert.equal(sample.altitude_source, 'surface');
    assert.equal(sample.state, 'warming');
  }
});
test('a lone stationary bus never acquires a course or motion and becomes stale after sixty seconds', () => {
  const track = createTrack(); assert.equal(track.sample(START), null); track.push(item(0));
  for (const seconds of [0, 12, 45, 60, 61, 3600]) {
    const sample = track.sample(START + seconds * 1000);
    assert.equal(sample.track, null); assert.equal(sample.course_source, null); assert.equal(sample.speed_kmh, null);
    assert.equal(sample.longitude, 20); assert.equal(sample.position_at, item(0).position_at);
    assert.equal(sample.state, seconds > 60 ? 'stale' : 'warming');
  }
});
test('missing bearing estimates direction from meaningful consecutive GPS displacement but never speed', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0)); track.push(item(10, {longitude: 20.001}));
  const sample = track.sample(START + 10000);
  near(sample.track, 90, .001); assert.equal(sample.course_source, 'estimated'); assert.equal(sample.speed_kmh, null);
  near(sample.longitude, 20.001);
});
test('reported bearing takes priority over GPS direction, including a reported zero and full circle', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {bearing: 0}));
  track.push(item(10, {longitude: 20.001, bearing: 360}));
  const sample = track.sample(START + 10000); assert.equal(sample.track, 0); assert.equal(sample.course_source, 'reported');
});
test('sub-ten-metre GPS jitter cannot create a direction for a bus with no known course', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0));
  for (let second = 1; second <= 10; second++) {
    track.push(item(second, {longitude: 20 + (second % 2) * .00001}));
    const sample = track.sample(START + second * 1000); assert.equal(sample.track, null); assert.equal(sample.course_source, null);
  }
});
test('stationary reports and GPS jitter retain the last reported or estimated direction', () => {
  for (const reported of [false, true]) {
    const track = createTrack({delayMs: 0}); track.push(item(0, {bearing: reported ? 270 : null}));
    track.push(item(10, {longitude: 20.001, bearing: reported ? 270 : null}));
    const known = track.sample(START + 10000);
    track.push(item(20, {longitude: 20.001})); track.push(item(30, {longitude: 20.00101}));
    const stopped = track.sample(START + 30000); near(stopped.track, known.track, 0); assert.equal(stopped.course_source, known.course_source);
  }
});
test('delayed unknown course stays unknown until the displayed timestamp reaches its first known bearing', () => {
  for (const bearing of [null, 180]) {
    const track = createTrack(); track.push(item(0)); track.push(item(10, {longitude: 20.001, bearing}));
    for (const seconds of [10, 12, 17, 21.999]) {
      const sample = track.sample(START + seconds * 1000); assert.equal(sample.track, null); assert.equal(sample.course_source, null);
    }
    const end = track.sample(START + 22000); assert.ok(Number.isFinite(end.track));
    assert.equal(end.course_source, bearing === null ? 'estimated' : 'reported');
  }
});
test('course provenance follows the displayed time, labeling mixed reported and estimated interpolation as estimated', () => {
  const track = createTrack(); track.push(item(0, {bearing: 90})); track.push(item(10, {longitude: 20.001}));
  assert.equal(track.sample(START + 12000).course_source, 'reported');
  assert.equal(track.sample(START + 17000).course_source, 'estimated');
  assert.equal(track.sample(START + 22000).course_source, 'estimated');
  track.push(item(20, {longitude: 20.002, bearing: 180}));
  assert.equal(track.sample(START + 27000).course_source, 'estimated');
  assert.equal(track.sample(START + 32000).course_source, 'reported');
});
test('heading and position interpolate on the shortest arcs across north and the dateline', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0, longitude: 179.9998, bearing: 359}));
  track.push(item(10, {latitude: 0, longitude: -179.9998, bearing: 1}));
  const sample = track.sample(START + 5000); near(Math.abs(sample.longitude), 180); near(sample.latitude, 0); near(sample.track, 0);
  assert.equal(sample.course_source, 'reported');
});
test('estimated bearing takes the short route at the dateline and stays finite near the pole', () => {
  const dateline = createTrack({delayMs: 0}); dateline.push(item(0, {latitude: 0, longitude: 179.9998}));
  dateline.push(item(10, {latitude: 0, longitude: -179.9998})); near(dateline.sample(START + 10000).track, 90);
  const pole = createTrack({delayMs: 0}); pole.push(item(0, {latitude: 89.9998, longitude: 0}));
  pole.push(item(10, {latitude: 89.9998, longitude: 180})); const sample = pole.sample(START + 10000);
  assert.ok(Number.isFinite(sample.track)); near(sample.track, 0); assert.equal(sample.course_source, 'estimated');
});
test('road vehicles hold the last GPS point without any dead reckoning even with source speed and bearing', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {bearing: 90, speed_kmh: 50}));
  track.push(item(10, {longitude: 20.001, bearing: 90, speed_kmh: 50}));
  const endpoint = track.sample(START + 10000).longitude;
  for (const seconds of [11, 15, 30, 70, 71, 3600]) {
    const sample = track.sample(START + seconds * 1000); near(sample.longitude, 20.001); assert.equal(sample.longitude, endpoint);
    assert.equal(sample.position_at, item(10).position_at); assert.equal(sample.state, seconds > 70 ? 'stale' : 'holding');
  }
});
test('delayed playback uses source observation time while freshness refers to the latest accepted report', () => {
  const track = createTrack(); track.push(item(0, {bearing: 90, speed_kmh: 20}));
  track.push(item(10, {longitude: 20.001, bearing: 90, speed_kmh: 40}));
  const sample = track.sample(START + 17000); near(sample.longitude, 20.0005); near(sample.speed_kmh, 30);
  assert.equal(sample.position_at, item(5).position_at); assert.equal(sample.ageMs, 7000); assert.equal(sample.state, 'interpolated');
});
test('duplicates and reversed source times cannot rewrite coordinates or create a false camera heading', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0)); track.push(item(10, {longitude: 20.001}));
  assert.equal(track.push(item(10, {longitude: 19, bearing: 270})), false);
  assert.equal(track.push(item(5, {longitude: 19, bearing: 270})), false);
  const sample = track.sample(START + 10000); near(sample.longitude, 20.001); near(sample.track, 90, .001);
  assert.equal(sample.course_source, 'estimated');
});
test('implausible source jumps reset the segment and cannot estimate a course across disconnected points', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {bearing: 90})); const first = track.sample(START);
  track.push(item(10, {longitude: 21})); const jumped = track.sample(START + 10000);
  assert.equal(jumped.segment, first.segment + 1); assert.equal(jumped.state, 'warming');
  assert.equal(jumped.track, null); assert.equal(jumped.course_source, null); near(jumped.longitude, 21);
  track.push(item(20, {longitude: 21.001})); assert.equal(track.sample(START + 20000).course_source, 'estimated');
});
test('bus-specific plausibility limits reset a 135 m one-second jump but retain a 125 m move', () => {
  for (const metres of [125, 135]) {
    const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0, bearing: 90}));
    const first = track.sample(START);
    track.push(item(1, {latitude: metres / 6371008.8 * 180 / Math.PI})); const next = track.sample(START + 1000);
    assert.equal(next.segment, first.segment + (metres > 130 ? 1 : 0));
    assert.equal(next.state, metres > 130 ? 'warming' : 'interpolated');
    assert.equal(next.course_source, metres > 130 ? null : 'estimated');
  }
});
test('an antipodal report begins a disconnected segment instead of interpolating an undefined great circle', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0, longitude: 0, bearing: 45}));
  track.push(item(10, {latitude: 0, longitude: 180})); const sample = track.sample(START + 5000);
  assert.equal(sample.state, 'warming'); assert.equal(sample.longitude, -180); assert.equal(sample.track, null);
});
test('source gaps reset direction while a reported bearing on the new segment remains available', () => {
  for (const bearing of [null, 270]) {
    const track = createTrack({delayMs: 0}); track.push(item(0, {bearing: 90}));
    track.push(item(60, {longitude: 20.001})); const continuous = track.sample(START + 60000);
    track.push(item(121, {longitude: 20.002, bearing})); const resumed = track.sample(START + 121000);
    assert.equal(resumed.segment, continuous.segment + 1); assert.equal(resumed.track, bearing);
    assert.equal(resumed.course_source, bearing === null ? null : 'reported'); assert.equal(resumed.state, 'warming');
  }
});
test('identity changes cannot carry an old vehicle course or buffer into another bus', () => {
  const track = createTrack({delayMs: 0}); track.push(item(10, {bearing: 90})); const first = track.sample(START + 10000);
  assert.ok(track.push(item(5, {id: 'poznan:ztm:1050'}))); const next = track.sample(START + 10000);
  assert.equal(next.track, null); assert.equal(next.course_source, null); assert.equal(next.state, 'warming'); assert.ok(next.segment > first.segment);
});
test('invalid required fields cannot change the track and invalid optional bearing/speed stay absent', () => {
  const track = createTrack();
  for (const values of [{latitude: NaN}, {latitude: 91}, {longitude: -181}, {longitude: '20'}, {position_at: 'invalid'}, {position_at: START}]) {
    assert.equal(track.push(item(0, values)), false);
  }
  assert.equal(track.sample(START), null); assert.ok(track.push(item(0, {bearing: 361, speed_kmh: -1})));
  const sample = track.sample(START); assert.equal(sample.track, null); assert.equal(sample.course_source, null); assert.equal(sample.speed_kmh, null);
  assert.equal(track.sample(NaN), null);
});
test('clear removes direction and the buffer keeps only thirty-two caller-independent recent samples', () => {
  const track = createTrack({delayMs: 0});
  for (let seconds = 0; seconds < 40; seconds++) {
    const source = item(seconds, {longitude: 20 + seconds * .0001, bearing: 90}); track.push(source); source.longitude = 24; source.bearing = 270;
  }
  const old = track.sample(START); near(old.longitude, 20.0008); near(old.track, 90); assert.equal(old.state, 'warming');
  const segment = old.segment; track.clear(); assert.equal(track.sample(START + 40000), null);
  track.push(item(40)); const fresh = track.sample(START + 40000); assert.ok(fresh.segment > segment); assert.equal(fresh.track, null);
});
test('custom delay/freshness boundaries are honored and invalid options use the safe bus defaults', () => {
  const custom = createTrack({delayMs: 1000, maxAgeMs: 10000}); custom.push(item(0, {bearing: 90})); custom.push(item(5, {longitude: 20.001, bearing: 90}));
  assert.equal(custom.sample(START + 3000).state, 'interpolated'); assert.equal(custom.sample(START + 15000).state, 'holding'); assert.equal(custom.sample(START + 15001).state, 'stale');
  const fallback = createTrack({delayMs: -1, maxAgeMs: Infinity}); fallback.push(item(0)); fallback.push(item(10, {longitude: 20.001}));
  assert.equal(fallback.sample(START + 11000).state, 'warming'); assert.equal(fallback.sample(START + 70000).state, 'holding'); assert.equal(fallback.sample(START + 70001).state, 'stale');
});
test('slow traffic acquires direction from net movement across several sub-ten-metre GPS reports', () => {
  const track = createTrack({delayMs: 0});
  for (let seconds = 0; seconds <= 120; seconds += 10) {
    track.push(item(seconds, {latitude: 52 + north(seconds / 2)}));
    const sample = track.sample(START + seconds * 1000);
    if (seconds < 20) { assert.equal(sample.track, null); assert.equal(sample.course_source, null); }
    if (seconds >= 30) { near(sample.track, 0); assert.equal(sample.course_source, 'estimated'); }
    assert.equal(sample.speed_kmh, null);
  }
});
test('slow turns replace the estimated heading once the new leg has meaningful net displacement', () => {
  const track = createTrack({delayMs: 0});
  for (const [seconds, metres] of [[0, 0], [10, 6], [20, 12]]) track.push(item(seconds, {latitude: north(metres), longitude: 0}));
  near(track.sample(START + 20000).track, 0);
  track.push(item(30, {latitude: north(12), longitude: north(6)}));
  near(track.sample(START + 30000).track, 0);
  track.push(item(40, {latitude: north(12), longitude: north(12)}));
  const turn = track.sample(START + 40000); near(turn.track, 90, .001); assert.equal(turn.course_source, 'estimated'); assert.equal(turn.speed_kmh, null);
});
test('back-and-forth jitter cannot accumulate traveled distance into a false course', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0}));
  // Four metres either side of the first report, repeated long enough to expire
  // the direction origin several times, still never gives ten metres net.
  for (let report = 1; report <= 40; report++) {
    track.push(item(report * 10, {latitude: north(report % 2 ? 4 : -4)}));
    const sample = track.sample(START + report * 10000); assert.equal(sample.track, null); assert.equal(sample.course_source, null);
  }
});
test('direction anchors expire after sixty seconds even when individual source gaps stay valid', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0}));
  const segment = track.sample(START).segment;
  track.push(item(40, {latitude: north(6)})); track.push(item(70, {latitude: north(12)}));
  const expired = track.sample(START + 70000); assert.equal(expired.track, null); assert.equal(expired.course_source, null); assert.equal(expired.segment, segment);
  track.push(item(80, {latitude: north(18)})); const recent = track.sample(START + 80000);
  near(recent.track, 0); assert.equal(recent.course_source, 'estimated'); assert.equal(recent.segment, segment);
});
test('duplicate and reversed reports cannot move a pending direction anchor', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0})); track.push(item(10, {latitude: north(6)}));
  assert.equal(track.push(item(10, {latitude: north(100), bearing: 180})), false);
  assert.equal(track.push(item(5, {latitude: north(200), bearing: 180})), false);
  track.push(item(20, {latitude: north(12)})); const sample = track.sample(START + 20000);
  near(sample.track, 0); assert.equal(sample.course_source, 'estimated'); assert.equal(sample.speed_kmh, null);
});
test('clear, source gaps and source jumps discard pending direction anchors', () => {
  for (const reset of ['clear', 'gap', 'jump']) {
    const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0})); track.push(item(10, {latitude: north(6)}));
    if (reset === 'clear') track.clear();
    const seconds = reset === 'gap' ? 80 : 20, origin = reset === 'jump' ? 1000 : 12;
    track.push(item(seconds, {latitude: north(origin)})); assert.equal(track.sample(START + seconds * 1000).track, null);
    track.push(item(seconds + 10, {latitude: north(origin + 6)})); assert.equal(track.sample(START + (seconds + 10) * 1000).track, null);
    track.push(item(seconds + 20, {latitude: north(origin + 12)}));
    const resumed = track.sample(START + (seconds + 20) * 1000); near(resumed.track, 0); assert.equal(resumed.course_source, 'estimated');
  }
});
test('vehicle changes discard pending direction anchors before estimating the next vehicle', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0})); track.push(item(10, {latitude: north(6)}));
  for (const [seconds, metres] of [[20, 12], [30, 18], [40, 24]]) {
    track.push(item(seconds, {id: 'poznan:ztm:1050', latitude: north(metres)}));
    const sample = track.sample(START + seconds * 1000);
    if (seconds < 40) assert.equal(sample.track, null);
    else { near(sample.track, 0); assert.equal(sample.course_source, 'estimated'); }
  }
});
test('a reported bearing refreshes the direction anchor before later cumulative estimation', () => {
  const track = createTrack({delayMs: 0}); track.push(item(0, {latitude: 0})); track.push(item(10, {latitude: north(6)}));
  track.push(item(20, {latitude: north(9), bearing: 270}));
  track.push(item(30, {latitude: north(15)})); const held = track.sample(START + 30000);
  near(held.track, 270); assert.equal(held.course_source, 'reported');
  track.push(item(40, {latitude: north(21)})); const derived = track.sample(START + 40000);
  near(derived.track, 0); assert.equal(derived.course_source, 'estimated'); assert.equal(derived.speed_kmh, null);
});
test('slow-motion estimates appear only when delayed playback reaches the accepted direction point', () => {
  const track = createTrack();
  for (const [seconds, metres] of [[0, 0], [10, 6], [20, 12]]) track.push(item(seconds, {latitude: north(metres)}));
  for (const seconds of [20, 22, 27, 31.999]) {
    const delayed = track.sample(START + seconds * 1000); assert.equal(delayed.track, null); assert.equal(delayed.course_source, null);
  }
  const arrived = track.sample(START + 32000); near(arrived.track, 0); assert.equal(arrived.course_source, 'estimated'); assert.equal(arrived.speed_kmh, null);
});
