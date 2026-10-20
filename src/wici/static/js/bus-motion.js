'use strict';
// Bus presentation reuses the geographic track, with no prediction beyond GPS.
window.WiciBusMotion = (() => {
  const EARTH_METRES = 6371008.8, MAX_SAMPLES = 32, MAX_SPEED_MPS = 55, JUMP_METRES = 75;
  const radians = value => value * Math.PI / 180;
  const degrees = value => value * 180 / Math.PI;
  const wrap = value => ((value + 180) % 360 + 360) % 360 - 180;
  const heading = value => ((value % 360) + 360) % 360;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const duration = (value, fallback) => finite(value) && value >= 0 ? value : fallback;
  function distance(a, b) {
    const lat1 = radians(a.latitude), lat2 = radians(b.latitude);
    const chord = Math.sin((lat2 - lat1) / 2) ** 2
      + Math.cos(lat1) * Math.cos(lat2) * Math.sin(radians(wrap(b.longitude - a.longitude)) / 2) ** 2;
    return 2 * EARTH_METRES * Math.asin(Math.sqrt(Math.min(1, Math.max(0, chord))));
  }
  function bearing(a, b) {
    const lat1 = radians(a.latitude), lat2 = radians(b.latitude), lon = radians(wrap(b.longitude - a.longitude));
    return heading(degrees(Math.atan2(Math.sin(lon) * Math.cos(lat2),
      Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(lon))));
  }
  function createTrack({delayMs = 12000, maxAgeMs = 60000} = {}) {
    delayMs = duration(delayMs, 12000); maxAgeMs = duration(maxAgeMs, 60000);
    const geographic = window.WiciAircraftMotion.createTrack({delayMs, maxAgeMs,
      maxExtrapolationMs: 0, maxSpeedMps: MAX_SPEED_MPS, jumpToleranceMetres: JUMP_METRES});
    let points = [], identity, directionAnchor;
    function clear() { geographic.clear(); points = []; identity = directionAnchor = undefined; }
    function push(item) {
      if (!item || !finite(item.latitude) || Math.abs(item.latitude) > 90
        || !finite(item.longitude) || Math.abs(item.longitude) > 180 || typeof item.position_at !== 'string') return false;
      const time = Date.parse(item.position_at);
      if (!Number.isFinite(time)) return false;
      const changedIdentity = identity !== undefined && item.id !== identity;
      const last = changedIdentity ? undefined : points.at(-1);
      if (last && time <= last.time) return false;
      const separation = last ? distance(last, item) : 0;
      const disconnected = last && (time - last.time > maxAgeMs
        || separation > MAX_SPEED_MPS * (time - last.time) / 1000 + JUMP_METRES);
      // Keep a recent origin across small reports: slow traffic can establish
      // direction after 10 m of net movement without accumulating GPS jitter.
      const anchor = last && !disconnected
        ? directionAnchor && time - directionAnchor.time <= maxAgeMs ? directionAnchor : last : null;
      const reported = finite(item.bearing) && item.bearing >= 0 && item.bearing <= 360;
      let course = reported ? heading(item.bearing) : null;
      let source = reported ? 'reported' : null, estimated = false;
      if (!reported && last && !disconnected) {
        if (distance(anchor, item) >= 10) { course = bearing(anchor, item); source = 'estimated'; estimated = true; }
        else { course = last.track; source = last.course_source; }
      }
      if (changedIdentity) clear();
      // Zero is the simplified map surface, never a measured GPS altitude.
      if (!geographic.push({...item, altitude_m: 0, track: course})) return false;
      if (disconnected) points = [];
      identity = item.id;
      const point = {time, latitude: item.latitude, longitude: item.longitude, track: course, course_source: source};
      points.push(point);
      if (reported || estimated || !anchor) directionAnchor = point;
      else directionAnchor = anchor;
      if (points.length > MAX_SAMPLES) points.shift();
      return true;
    }
    function sample(nowMs = Date.now()) {
      const result = geographic.sample(nowMs);
      if (!result) return null;
      const time = Date.parse(result.position_at);
      const upper = points.findIndex(point => point.time >= time);
      let source = upper < 0 ? points.at(-1)?.course_source : points[upper].course_source;
      if (upper > 0 && points[upper].time !== time && points[upper - 1].course_source !== source) source = 'estimated';
      return {...result, altitude_source: 'surface', course_source: result.track === null ? null : source};
    }
    return {push, sample, clear};
  }
  return {createTrack};
})();
