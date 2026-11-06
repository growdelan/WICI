'use strict';
// A replay clock is bounded by observed positions. Long gaps have no interpolated aircraft.
(function (root) {
  const MAX_POSITION_GAP = 120, MAX_RADAR_AGE = 15 * 60;
  function atOrBefore(items, time) {
    let low = 0, high = items.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (items[mid].time <= time) low = mid + 1;
      else high = mid;
    }
    return low - 1;
  }
  const radians = degrees => degrees * Math.PI / 180;
  const turn = (from, to) => ((to - from + 540) % 360) - 180;
  const compass = degrees => (degrees % 360 + 360) % 360;
  function course(a, b) {
    if (!a || !b || (a.lon === b.lon && a.lat === b.lat)) return null;
    const dy = radians(b.lon - a.lon), p = radians(a.lat), q = radians(b.lat);
    return compass(Math.atan2(Math.sin(dy) * Math.cos(q),
      Math.cos(p) * Math.sin(q) - Math.sin(p) * Math.cos(q) * Math.cos(dy)) * 180 / Math.PI);
  }
  function sample(points, time) {
    const index = atOrBefore(points, time), a = points[index], b = points[index + 1];
    if (!a || (!b && time !== a.time)) return null;
    const connected = b && b.time - a.time <= MAX_POSITION_GAP;
    if (a.time !== time && !connected) return null;
    const previous = points[index - 1];
    const derived = connected ? course(a, b) : previous && a.time - previous.time <= MAX_POSITION_GAP ? course(previous, a) : null;
    const heading = Number.isFinite(a.heading) ? a.heading : derived;
    if (time === a.time) return {...a, heading, index, measured: true};
    const weight = (time - a.time) / (b.time - a.time);
    return {index, time, lat: a.lat + (b.lat - a.lat) * weight,
      lon: compass(a.lon + turn(a.lon, b.lon) * weight + 180) - 180,
      alt_m: a.alt_m + (b.alt_m - a.alt_m) * weight,
      heading: Number.isFinite(heading) && Number.isFinite(b.heading) ? compass(heading + turn(heading, b.heading) * weight) : heading,
      measured: false};
  }
  function radarAt(frames, time) {
    const frame = frames[atOrBefore(frames, time)];
    return {frame, usable: Boolean(frame && time - frame.time <= MAX_RADAR_AGE)};
  }
  function legs(points) {
    const result = [];
    for (const point of points) {
      const leg = result.at(-1);
      if (!leg || point.time - leg.at(-1).time > MAX_POSITION_GAP) result.push([point]);
      else leg.push(point);
    }
    return result;
  }
  const api = {MAX_POSITION_GAP, sample, radarAt, legs};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.WiciFlightReplayData = api;
})(typeof window !== 'undefined' ? window : globalThis);
