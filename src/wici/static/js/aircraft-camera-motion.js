'use strict';
// Presentation only: never writes observations back into the aircraft track.
window.WiciAircraftCameraMotion = (() => {
  const EARTH_M = 6371008.8, MAX_CONTINUOUS_SECONDS = 1, RESUME_STEP_SECONDS = .1;
  const MAX_AIRCRAFT_MPS = 600;
  const SETTLE_SECONDS = .1, HEADING_RATE_DPS = 45;
  const radians = value => value * Math.PI / 180;
  const degrees = value => value * 180 / Math.PI;
  const wrap = value => ((value + 180) % 360 + 360) % 360 - 180;
  const heading = value => ((value % 360) + 360) % 360;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const moving = point => point.state === 'interpolated' || point.state === 'predicted';
  const valid = point => point && finite(point.latitude) && Math.abs(point.latitude) <= 90
    && finite(point.longitude) && Math.abs(point.longitude) <= 180 && finite(point.altitude_m);
  const speed = point => finite(point.speed_kmh) ? Math.min(MAX_AIRCRAFT_MPS, Math.max(0, point.speed_kmh / 3.6)) : 0;

  function angle(a, b) {
    const lat1 = radians(a.latitude), lat2 = radians(b.latitude);
    const chord = Math.sin((lat2 - lat1) / 2) ** 2
      + Math.cos(lat1) * Math.cos(lat2) * Math.sin(radians(wrap(b.longitude - a.longitude)) / 2) ** 2;
    return 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, chord))));
  }
  const separation = (a, b) => Math.hypot(angle(a, b) * EARTH_M, b.altitude_m - a.altitude_m);
  function approach(a, b, fraction) {
    if (fraction >= 1) return {latitude: b.latitude, longitude: b.longitude, altitude_m: b.altitude_m};
    const lat = radians(a.latitude), lon = radians(a.longitude), endLat = radians(b.latitude);
    const dLon = radians(wrap(b.longitude - a.longitude));
    const bearing = Math.atan2(Math.sin(dLon) * Math.cos(endLat),
      Math.cos(lat) * Math.sin(endLat) - Math.sin(lat) * Math.cos(endLat) * Math.cos(dLon));
    const distance = angle(a, b) * fraction;
    const nextLat = Math.asin(Math.max(-1, Math.min(1,
      Math.sin(lat) * Math.cos(distance) + Math.cos(lat) * Math.sin(distance) * Math.cos(bearing))));
    const nextLon = lon + Math.atan2(Math.sin(bearing) * Math.sin(distance) * Math.cos(lat),
      Math.cos(distance) - Math.sin(lat) * Math.sin(nextLat));
    return {latitude: degrees(nextLat), longitude: wrap(degrees(nextLon)),
      altitude_m: a.altitude_m + (b.altitude_m - a.altitude_m) * fraction};
  }
  const vector = point => {
    const lat = radians(point.latitude), lon = radians(point.longitude);
    return [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
  };
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  // Apply only the observed target displacement to the presentation position.
  // A rotation on the sphere keeps the same contract near poles and the dateline.
  function transport(position, from, to) {
    const first = vector(from), second = vector(to), axis = cross(first, second);
    const sine = Math.hypot(...axis), cosine = Math.min(1, Math.max(-1, first.reduce((sum, v, i) => sum + v * second[i], 0)));
    if (sine < 1e-12) return {...position, altitude_m: position.altitude_m + to.altitude_m - from.altitude_m};
    const normal = axis.map(value => value / sine), point = vector(position), tangent = cross(normal, point);
    const projection = normal.reduce((sum, value, index) => sum + value * point[index], 0);
    const rotated = point.map((value, index) => value * cosine + tangent[index] * sine + normal[index] * projection * (1 - cosine));
    return {latitude: degrees(Math.atan2(rotated[2], Math.hypot(rotated[0], rotated[1]))),
      longitude: wrap(degrees(Math.atan2(rotated[1], rotated[0]))),
      altitude_m: position.altitude_m + to.altitude_m - from.altitude_m};
  }

  function createFollower() {
    let previous, displayed, lastTime, reanchor = false;
    const copy = () => displayed ? {...displayed} : null;
    function clear() { previous = displayed = lastTime = undefined; reanchor = false; }
    function step(target, nowMs, {freeze = false} = {}) {
      if (!finite(nowMs)) return copy();
      if (freeze && displayed) {
        lastTime = nowMs; reanchor = true;
        return copy();
      }
      if (!valid(target)) {
        if (displayed) { lastTime = nowMs; reanchor = true; }
        return copy();
      }
      if (!displayed) {
        previous = {...target}; displayed = {...target}; lastTime = nowMs;
        reanchor = freeze;
        return copy();
      }
      if (nowMs <= lastTime) return copy();
      const elapsed = (nowMs - lastTime) / 1000;
      lastTime = nowMs;
      const pace = Math.max(speed(target), speed(previous));
      const resumed = reanchor || elapsed > MAX_CONTINUOUS_SECONDS;
      // Low FPS is elapsed flight time, not an interruption. Only a real pause
      // or explicit freeze drops missed time from the correction/turn budget.
      const dt = resumed ? Math.min(RESUME_STEP_SECONDS, elapsed) : elapsed;
      // Missing speed cannot prevent transport of physically plausible observed
      // displacement. This bound is internal; it never supplies telemetry.
      const continuitySpeed = finite(target.speed_kmh) || finite(previous.speed_kmh) ? pace * 3 : MAX_AIRCRAFT_MPS;
      const discontinuity = resumed
        || separation(previous, target) > Math.max(25, continuitySpeed * elapsed + 15);
      let position = {latitude: displayed.latitude, longitude: displayed.longitude, altitude_m: displayed.altitude_m};
      if (!discontinuity && moving(target)) position = transport(position, previous, target);
      const remaining = separation(position, target);
      if (remaining > 0) {
        // Small offsets settle ~95% within 300 ms. Large corrections are capped
        // at 30 m/s + 25% of speed, in addition to ordinary target displacement.
        const correction = Math.min(remaining * (1 - Math.exp(-dt / SETTLE_SECONDS)), (30 + pace * .25) * dt);
        position = approach(position, target, correction / remaining);
      }
      const targetHeading = finite(target.track) ? heading(target.track) : displayed.track;
      let course = finite(displayed.track) ? displayed.track : targetHeading;
      if (finite(targetHeading) && finite(course)) {
        const difference = wrap(targetHeading - course);
        const change = Math.max(-HEADING_RATE_DPS * dt,
          Math.min(HEADING_RATE_DPS * dt, difference * (1 - Math.exp(-dt / SETTLE_SECONDS))));
        course = heading(course + change);
      }
      displayed = {...target, ...position, track: course};
      previous = {...target}; reanchor = false;
      return copy();
    }
    return {step, clear};
  }
  return {createFollower};
})();
