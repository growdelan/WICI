'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function createTrack(options){
  const window={};vm.runInNewContext(fs.readFileSync('src/wici/static/js/aircraft-motion.js','utf8'),{window});
  return window.WiciAircraftMotion.createTrack(options);
}
const START=Date.parse('2026-10-19T10:00:00Z');
const item=(seconds,values={})=>({latitude:52,longitude:20,altitude_m:10000,track:90,speed_kmh:900,position_at:new Date(START+seconds*1000).toISOString(),...values});
const near=(actual,expected,tolerance=1e-6)=>assert.ok(Math.abs(actual-expected)<=tolerance,`${actual} differs from ${expected}`);
test('empty track and clear have no position; a lone report warms without inventing motion',()=>{
  const track=createTrack();assert.equal(track.sample(START),null);assert.ok(track.push(item(0)));
  for(const seconds of [0,15,29]){const sample=track.sample(START+seconds*1000);assert.equal(sample.state,'warming');near(sample.longitude,20);assert.equal(sample.ageMs,seconds*1000);}
  assert.equal(track.sample(START+31000).state,'stale');track.clear();assert.equal(track.sample(START+32000),null);
});
test('uses observation times and delayed playback, with source age independent of display time',()=>{
  const track=createTrack();track.push(item(0,{longitude:20}));track.push(item(10,{longitude:20.02,altitude_m:11000,speed_kmh:800}));
  // Reports can arrive late: no local fetch timestamp is used to place either sample.
  const sample=track.sample(START+17000);assert.equal(sample.state,'interpolated');near(sample.longitude,20.01);near(sample.altitude_m,10500);near(sample.speed_kmh,850);
  assert.equal(sample.position_at,new Date(START+5000).toISOString());assert.equal(sample.ageMs,7000);
  assert.equal(track.sample(START+11000).state,'warming');
});
test('rejects duplicates and reversed source times without rewriting the accepted track',()=>{
  const track=createTrack({delayMs:0});track.push(item(0));track.push(item(10,{longitude:20.02}));
  assert.equal(track.push(item(10,{longitude:24})),false);assert.equal(track.push(item(5,{longitude:15})),false);
  const sample=track.sample(START+10000);assert.equal(sample.state,'interpolated');near(sample.longitude,20.02);
});
test('interpolates across the dateline and heading zero along the shortest arcs',()=>{
  const track=createTrack({delayMs:0});track.push(item(0,{latitude:0,longitude:179.99,track:359}));track.push(item(10,{latitude:0,longitude:-179.99,track:1}));
  const sample=track.sample(START+5000);assert.equal(sample.state,'interpolated');near(Math.abs(sample.longitude),180);near(sample.latitude,0);near(sample.track,0);
});
test('uses a great circle near a pole instead of interpolating longitude through the wrong hemisphere',()=>{
  const track=createTrack({delayMs:0});track.push(item(0,{latitude:89.99,longitude:0}));track.push(item(10,{latitude:89.99,longitude:180}));
  const sample=track.sample(START+5000);assert.ok(sample.latitude>89.99999);assert.ok(Number.isFinite(sample.longitude));
});
test('caps geodesic prediction and then holds exactly the same endpoint, including after becoming stale',()=>{
  const track=createTrack({delayMs:0});track.push(item(0,{latitude:0,longitude:179.97}));track.push(item(10,{latitude:0,longitude:179.99}));
  const predicted=track.sample(START+13000);assert.equal(predicted.state,'predicted');assert.ok(predicted.longitude>179.99);near(predicted.latitude,0);
  const limit=track.sample(START+15000),held=track.sample(START+16000),later=track.sample(START+39000),stale=track.sample(START+41000);
  assert.equal(limit.state,'predicted');assert.equal(held.state,'holding');assert.equal(later.state,'holding');assert.equal(stale.state,'stale');
  for(const sample of [held,later,stale]){near(sample.longitude,limit.longitude,0);near(sample.latitude,limit.latitude,0);assert.equal(sample.position_at,limit.position_at);}
  near(limit.longitude,-179.9987585,1e-6);assert.equal(stale.ageMs,31000);
});
test('resets after an implausible jump instead of interpolating across Poland',()=>{
  const track=createTrack({delayMs:0});track.push(item(0,{longitude:15}));track.push(item(10,{longitude:15.02}));
  assert.ok(track.push(item(20,{longitude:23})));const sample=track.sample(START+22000);assert.equal(sample.state,'warming');near(sample.longitude,23);
  track.push(item(30,{longitude:23.02}));assert.equal(track.sample(START+25000).state,'interpolated');
});
test('a source gap beyond freshness starts a new track, while ordinary jet movement remains continuous',()=>{
  const track=createTrack({delayMs:0});track.push(item(0));track.push(item(10,{longitude:20.07}));assert.equal(track.sample(START+5000).state,'interpolated');
  track.push(item(41,{longitude:20.1}));assert.equal(track.sample(START+42000).state,'warming');
});
test('missing height remains null and missing speed or heading cannot create predicted motion',()=>{
  for(const missing of [{altitude_m:null,track:null,speed_kmh:null},{altitude_m:undefined,track:90,speed_kmh:null},{altitude_m:null,track:null,speed_kmh:900}]){
    const track=createTrack({delayMs:0});track.push(item(0,missing));track.push(item(10,{...missing,longitude:20.02}));
    const middle=track.sample(START+5000);assert.equal(middle.altitude_m,null);assert.equal(middle.track,missing.track);assert.equal(middle.speed_kmh,missing.speed_kmh);
    const later=track.sample(START+13000);assert.equal(later.state,'holding');near(later.longitude,20.02);assert.equal(later.altitude_m,null);
  }
});
test('does not invent optional fields between a report lacking them and a complete report',()=>{
  const track=createTrack({delayMs:0});track.push(item(0,{altitude_m:null,track:null,speed_kmh:null}));track.push(item(10));
  const middle=track.sample(START+5000);for(const key of ['altitude_m','track','speed_kmh'])assert.equal(middle[key],null);
  const end=track.sample(START+10000);assert.equal(end.altitude_m,10000);assert.equal(end.track,90);assert.equal(end.speed_kmh,900);
});
test('rejects invalid required coordinates and timestamps and sanitizes invalid optional numbers',()=>{
  const track=createTrack();for(const values of [{latitude:NaN},{latitude:91},{longitude:-181},{longitude:'20'},{position_at:'invalid'},{position_at:START}])assert.equal(track.push(item(0,values)),false);
  assert.equal(track.sample(START),null);assert.ok(track.push(item(0,{altitude_m:Infinity,track:-1,speed_kmh:-1})));
  const sample=track.sample(START);for(const key of ['altitude_m','track','speed_kmh'])assert.equal(sample[key],null);assert.equal(track.sample(NaN),null);
});
test('configured delay, prediction cap and freshness are honored at their boundaries',()=>{
  const track=createTrack({delayMs:1000,maxExtrapolationMs:2000,maxAgeMs:10000});track.push(item(0));track.push(item(5,{longitude:20.01}));
  assert.equal(track.sample(START+3000).state,'interpolated');assert.equal(track.sample(START+7000).state,'predicted');
  const limit=track.sample(START+8000),held=track.sample(START+9000);assert.equal(limit.state,'predicted');assert.equal(held.state,'holding');near(held.longitude,limit.longitude,0);
  assert.equal(track.sample(START+15000).state,'holding');assert.equal(track.sample(START+15001).state,'stale');
});
test('prediction can be disabled without moving or changing the source timestamp',()=>{
  const track=createTrack({delayMs:0,maxExtrapolationMs:0});track.push(item(0));track.push(item(10,{longitude:20.02}));
  const sample=track.sample(START+15000);assert.equal(sample.state,'holding');near(sample.longitude,20.02);assert.equal(sample.position_at,item(10).position_at);
});
test('stale never extends prediction even if the configured prediction window outlives freshness',()=>{
  const track=createTrack({delayMs:0,maxExtrapolationMs:20000,maxAgeMs:10000});track.push(item(0));track.push(item(5,{longitude:20.01}));
  const end=track.sample(START+15000),stale=track.sample(START+15001),later=track.sample(START+20000);
  assert.equal(stale.state,'stale');for(const sample of [stale,later]){near(sample.longitude,end.longitude,0);assert.equal(sample.position_at,end.position_at);}
});
test('retains a bounded recent buffer without retaining caller-owned mutable objects',()=>{
  const track=createTrack({delayMs:0});for(let seconds=0;seconds<40;seconds++){const source=item(seconds,{longitude:20+seconds*.001});track.push(source);source.longitude=23;}
  const old=track.sample(START+1000);assert.equal(old.state,'warming');near(old.longitude,20.008);const latest=track.sample(START+39000);near(latest.longitude,20.039);
});
test('segment identifies disconnected tracks after jumps, source gaps and explicit clear',()=>{
  const track=createTrack({delayMs:0});track.push(item(0));
  const initial=track.sample(START).segment;assert.ok(Number.isInteger(initial));
  track.push(item(10,{longitude:20.02}));assert.equal(track.sample(START+10000).segment,initial);
  assert.equal(track.push(item(5)),false);assert.equal(track.push(item(10)),false);
  assert.equal(track.push(item(11,{latitude:NaN})),false);assert.equal(track.sample(START+10000).segment,initial);
  track.push(item(20,{longitude:23}));const jumped=track.sample(START+20000);
  assert.equal(jumped.state,'warming');assert.equal(jumped.segment,initial+1);
  track.push(item(51,{longitude:23.02}));const resumed=track.sample(START+51000);
  assert.equal(resumed.state,'warming');assert.equal(resumed.segment,jumped.segment+1);
  track.clear();assert.equal(track.sample(START+52000),null);track.push(item(52,{longitude:15}));
  assert.equal(track.sample(START+52000).segment,resumed.segment+1);
});
