'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const EARTH_M = 6371008.8, RAD = Math.PI / 180, FRAME = 1000 / 30;
function follower() {
  const window = {};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/aircraft-camera-motion.js', 'utf8'), {window});
  return window.WiciAircraftCameraMotion.createFollower();
}
const point = (values = {}) => ({latitude: 52, longitude: 20, altitude_m: 10000,
  track: 90, speed_kmh: 900, state: 'interpolated', ...values});
function distance(a, b) {
  const chord = Math.sin((b.latitude - a.latitude) * RAD / 2) ** 2
    + Math.cos(a.latitude * RAD) * Math.cos(b.latitude * RAD) * Math.sin((b.longitude - a.longitude) * RAD / 2) ** 2;
  return Math.hypot(2 * EARTH_M * Math.asin(Math.sqrt(Math.min(1, chord))), b.altitude_m - a.altitude_m);
}
const east = (origin, metres) => point({...origin, longitude: origin.longitude + metres / (EARTH_M * RAD * Math.cos(origin.latitude * RAD))});
const near = (actual, expected, tolerance = 1e-6) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);

test('ordinary target movement is transported without an additional prediction or lag', () => {
  const camera = follower(), start = point();
  camera.step(start, 0);
  for (let frame = 1; frame <= 90; frame++) {
    const target = east(start, 250 * frame / 30), display = camera.step(target, frame * FRAME);
    assert.ok(distance(display, target) < .001);
  }
});

for (const fps of [2, 3, 4, 5, 30]) test(`continuous ${fps} FPS follows a 60-second flight without accumulating lag`, () => {
  const camera = follower(), start = point();
  camera.step(start, 0);
  let maximumError = 0, display;
  for (let frame = 1; frame <= fps*60; frame++) {
    const time = frame*1000/fps, target = east(start, 250*time/1000);
    display = camera.step(target, time);
    maximumError = Math.max(maximumError, distance(display, target));
  }
  assert.ok(maximumError < .001, `${fps} FPS accumulated ${maximumError} m of error`);
  assert.ok(distance(display, start) > 14999, 'The display must cover the actual 15 km flight');
});

test('irregular continuous frames retain target movement through slow rendering and changing altitude', () => {
  const camera = follower(), start = point(), intervals = [16, 80, 333, 500, 200, 750, 33, 250, 1000];
  camera.step(start, 0);
  let time = 0, frame = 0;
  while (time < 60000) {
    time = Math.min(60000, time+intervals[frame++ % intervals.length]);
    const target = east(start, 250*time/1000);target.altitude_m += 20*time/1000;
    const display = camera.step(target, time);
    assert.ok(distance(display, target) < .001, `Irregular frame at ${time} ms fell behind`);
  }
});

test('slow rendering still transports observed movement when speed is unavailable', () => {
  const camera = follower(), start = point({speed_kmh: null});
  camera.step(start, 0);
  for (let frame = 1; frame <= 120; frame++) {
    const target = east(start, 125*frame), display = camera.step(target, frame*500);
    assert.ok(distance(display, target) < .001);
    assert.equal(display.speed_kmh, null);
  }
});

test('missing speed does not allow a source jump to bypass bounded correction at 2 FPS', () => {
  const camera = follower(), start = point({speed_kmh: null});camera.step(start, 0);
  const target = east(start, 805), display = camera.step(target, 500);
  assert.ok(distance(start, display) <= 15.001);
  assert.ok(distance(display, target) > 789);
  assert.equal(display.speed_kmh, null);
});

test('absorbs the reproduced 805 m late-fix correction and converges with bounded motion', () => {
  const camera = follower();
  const old = point({latitude: 51.999998588482036, longitude: 20.038259229724076, state: 'holding'});
  const corrected = point({latitude: 52.00000127011415, longitude: 20.05000000018913});
  let display = camera.step(old, 0), previous = display;
  assert.ok(distance(old, corrected) > 800);
  for (let frame = 1; frame <= 450; frame++) {
    display = camera.step(corrected, frame * FRAME);
    assert.ok(distance(previous, display) <= (30 + 250 * .25) / 30 + .001);
    previous = display;
  }
  assert.ok(distance(display, corrected) < .001);
});

test('continues ordinary movement while correcting a late fix, within the extra-speed budget', () => {
  const camera = follower(), start = point();
  let previous = camera.step(start, 0);
  for (let frame = 1; frame <= 90; frame++) {
    const target = east(start, 805 + 250 * frame / 30), display = camera.step(target, frame * FRAME);
    assert.ok(distance(previous, display) <= (250 + 30 + 250 * .25) / 30 + .01);
    assert.ok(distance(display, target) < distance(previous, target));
    previous = display;
  }
});

test('a moving 805 m source correction at 2 FPS is absorbed under the real-time correction budget', () => {
  const camera = follower(), start = point(), dt = .5, budget = (30+250*.25)*dt;
  let previous = camera.step(start, 0), previousError = Infinity;
  for (let frame = 1; frame <= 120; frame++) {
    const target = east(start, 805+250*frame*dt), display = camera.step(target, frame*dt*1000);
    assert.ok(distance(previous, display) <= (frame === 1 ? budget : 250*dt+budget)+.001);
    const error = distance(display, target);
    assert.ok(error <= previousError+.001, 'Source correction must converge, without building lag');
    if (frame === 1) assert.ok(error > 800, 'A late fix must not be transported as ordinary motion');
    if (frame >= 40) assert.ok(error < .001);
    previous = display;previousError = error;
  }
});

test('warming, holding and stale never travel from speed alone and settle to their endpoint', () => {
  for (const state of ['warming', 'holding', 'stale']) {
    const camera = follower(), start = point({state});
    let display = camera.step(start, 0);
    for (let frame = 1; frame <= 90; frame++) display = camera.step(start, frame * FRAME);
    assert.ok(distance(display, start) < 1e-6);
    const endpoint = east(start, 40);
    const first = camera.step(endpoint, 91 * FRAME);
    assert.ok(distance(first, display) > 0 && distance(first, display) < 4);
    for (let frame = 92; frame <= 240; frame++) display = camera.step(endpoint, frame * FRAME);
    assert.ok(distance(display, endpoint) < .001);
    const resting = camera.step(endpoint, 241 * FRAME);
    assert.ok(distance(resting, endpoint) < .001);
  }
});

test('freeze preserves the exact render and resumes without catching up in one frame', () => {
  const camera = follower(), start = point();
  const displayed = camera.step(start, 0), away = east(start, 2000);
  for (const time of [FRAME, 5000, 15000]) assert.deepEqual(camera.step(away, time, {freeze: true}), displayed);
  const resumed = camera.step(away, 15000 + FRAME);
  assert.ok(distance(resumed, displayed) > 0 && distance(resumed, displayed) < 4);
  assert.ok(distance(resumed, away) > 1900);
});

test('a long frame gap absorbs displacement and caps the elapsed correction time', () => {
  const camera = follower(), start = point(), displayed = camera.step(start, 0);
  const resumed = camera.step(east(start, 2000), 60000);
  assert.ok(distance(displayed, resumed) <= 9.251);
});

test('low-FPS freeze and a sixty-second interruption do not consume missed wall time on resume', () => {
  for (const freeze of [false, true]) {
    const camera = follower(), start = point(), displayed = camera.step(start, 0);
    const away = east(start, 15000);
    if (freeze) assert.deepEqual(camera.step(away, 60000, {freeze: true}), displayed);
    const resumed = camera.step(away, freeze ? 60500 : 60000);
    assert.ok(distance(displayed, resumed) <= 9.251);
    assert.ok(distance(resumed, away) > 14900);
  }
});

test('headings cross 359 to zero along the short arc, with bounded turn rates', () => {
  const camera = follower();
  let display = camera.step(point({track: 359}), 0), previous = 359;
  for (let frame = 1; frame <= 60; frame++) {
    display = camera.step(point({track: 1}), frame * FRAME);
    const step = ((display.track - previous + 540) % 360) - 180;
    assert.ok(step >= 0 && step <= 45 / 30 + 1e-8);
    previous = display.track;
  }
  near(display.track, 1, 1e-5);
  const turn = camera.step(point({track: 181}), 61 * FRAME);
  assert.ok(Math.abs(((turn.track - display.track + 540) % 360) - 180) <= 45 / 30 + 1e-8);
});

test('heading correction respects elapsed wall time at 2 FPS and remains capped after a pause', () => {
  const camera = follower();camera.step(point({track: 90}), 0);
  const first = camera.step(point({track: 180}), 500);near(first.track,112.5);
  const second = camera.step(point({track: 180}), 1000);near(second.track,135);
  const afterPause = camera.step(point({track: 270}), 61000);
  assert.ok(Math.abs(((afterPause.track-second.track+540)%360)-180) <= 4.5+1e-8);
});

test('vertical jumps settle under the same three-dimensional correction limit', () => {
  const camera = follower(), start = point();
  camera.step(start, 0);
  const display = camera.step(point({altitude_m: 12000}), FRAME);
  near(display.latitude, start.latitude);
  near(display.longitude, start.longitude);
  assert.ok(display.altitude_m > 10000 && display.altitude_m < 10004);
});

test('reset drops presentation history and caller mutation cannot rewrite stored points', () => {
  const camera = follower(), source = point(), displayed = camera.step(source, 0);
  source.longitude = 24; displayed.latitude = 10;
  const held = camera.step(point({longitude: 25}), FRAME, {freeze: true});
  near(held.latitude, 52); near(held.longitude, 20);
  camera.clear();
  assert.equal(camera.step(null, 100), null);
  const fresh = camera.step(point({longitude: 24}), 200);
  near(fresh.longitude, 24);
});

test('invalid targets and nonmonotonic clocks keep the previous render stable', () => {
  const camera = follower(), start = point(), displayed = camera.step(start, 0);
  for (const invalid of [null, point({latitude: 91}), point({longitude: NaN}), point({altitude_m: null})]) {
    assert.deepEqual(camera.step(invalid, FRAME), displayed);
  }
  assert.deepEqual(camera.step(east(start, 1000), NaN), displayed);
  assert.deepEqual(camera.step(east(start, 1000), -1000), displayed);
  const resumed = camera.step(east(start, 1000), 2 * FRAME);
  assert.ok(distance(displayed, resumed) < 4);
});

test('spherical transport stays continuous across the dateline and near a pole', () => {
  for (const start of [point({latitude: 0, longitude: 179.9999}), point({latitude: 89.99, longitude: 20})]) {
    const camera = follower(); camera.step(start, 0);
    const target = east(start, 5);
    target.longitude = ((target.longitude + 540) % 360) - 180;
    const display = camera.step(target, FRAME);
    assert.ok(distance(display, target) < .001);
    assert.ok(Number.isFinite(display.longitude) && Number.isFinite(display.latitude));
  }
});
