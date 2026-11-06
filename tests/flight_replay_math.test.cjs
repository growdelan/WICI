'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {sample, legs, radarAt} = require('../src/wici/static/js/flight-replay-data.js');

const points = [
  {time:100, lat:52, lon:18, alt_m:3000, heading:355},
  {time:220, lat:53, lon:20, alt_m:4000, heading:5},
  {time:341, lat:54, lon:21, alt_m:4400}
];

test('interpolates the altitude and the shortest course turn inside a recorded leg', () => {
  const middle = sample(points, 160);
  assert.deepEqual([middle.lat, middle.lon, middle.alt_m, middle.heading], [52.5,19,3500,0]);
  assert.equal(middle.measured, false);
});

test('retains exact observations while splitting the path and hiding the aircraft inside a gap', () => {
  assert.equal(sample(points, 220).measured, true);
  assert.equal(sample(points, 220.1), null);
  assert.equal(sample(points, 340.9), null);
  assert.equal(sample(points, 341).alt_m, 4400);
  assert.equal(sample(points, 341).heading, null);
  assert.equal(sample(points, 342), null);
  assert.deepEqual(legs(points).map(leg => leg.length), [2,1]);
});

test('never borrows a future or expired radar scan, including on a backwards seek', () => {
  const frames = [{time:100}, {time:1300}];
  const times = [99, 100, 1000, 1000.01, 1300, 1299, 100];
  assert.deepEqual(times.map(time => {
    const {frame, usable} = radarAt(frames, time);
    return usable ? frame.time : undefined;
  }), [undefined,100,100,undefined,1300,undefined,100]);
  assert.deepEqual(radarAt(frames, 1000.01), {frame: frames[0], usable: false});
});
