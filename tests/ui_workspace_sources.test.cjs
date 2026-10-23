'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {create, MAX_INDEX_QUEUE} = require('../src/wici/static/js/workspace-sources.js');
const tick = () => new Promise(resolve => setImmediate(resolve));

test('Atlas and Analysis share concurrent reads and TTL without changing fetched_at', async () => {
  let count = 0, time = 0, release;
  const source = create({now:() => time, hidden:() => false, read:() => {
    count++; return new Promise(resolve => { release = resolve; });
  }});
  const first = source.request('/hydro?kind=stations'), second = source.request('/hydro?kind=stations');
  await tick(); assert.equal(count, 1);
  release({status:'ready', fetched_at:'2026-01-01T12:00:00Z', items:[]});
  assert.deepEqual(await first, await second);
  time = 299999;
  assert.equal((await source.request('/hydro?kind=stations')).fetched_at, '2026-01-01T12:00:00Z');
  assert.equal(count, 1);
});

test('cancelling a card does not cancel the same source request used by the table', async () => {
  let release;
  const source = create({hidden:() => false, read:() => new Promise(resolve => { release = resolve; })});
  const controller = new AbortController();
  const card = source.request('/hydro?kind=stations', undefined, {signal:controller.signal});
  const table = source.request('/hydro?kind=stations');
  await tick(); controller.abort();
  await assert.rejects(card, {name:'AbortError'});
  release({status:'ready', items:[{id:1}]});
  assert.equal((await table).items[0].id, 1);
});

test('hidden browser and historical mode schedule no new periodic source reads', async () => {
  let count = 0, hidden = true;
  const scheduled = [];
  const source = create({hidden:() => hidden, delay:(fn, ms) => { scheduled.push({fn, ms}); return scheduled.length; },
    cancel:() => {}, read:async () => { count++; return {status:'ready', items:[]}; }});
  source.setTypes(['hydro_station'], {live:false}); source.setVisible(true);
  assert.equal(count, 0);
  hidden = false; source.setVisible(true); await tick();
  assert.equal(count, 1); assert.equal(scheduled.length, 0);
  source.setVisible(false); await tick(); assert.equal(count, 1);
});

test('GIOS starts no more than two requests concurrently and spaces starts by 600ms', async () => {
  let time = 0, active = 0, peak = 0;
  const started = [], scheduled = [], releases = [];
  const source = create({now:() => time, hidden:() => false,
    delay:(fn, ms) => { scheduled.push({fn, ms}); return scheduled.length; }, cancel:() => {},
    read:() => { active++; peak = Math.max(peak, active); started.push(time);
      return new Promise(resolve => releases.push(() => { active--; resolve({status:'ready', items:[]}); })); }});
  const reads = [1,2,3].map(id => source.request(`/gios?kind=index&id=${id}`));
  await tick(); assert.deepEqual(started, [0]); assert.equal(scheduled[0].ms, 600);
  time = 600; scheduled.shift().fn(); await tick(); assert.deepEqual(started, [0,600]);
  releases.shift()(); await tick(); time = 1200; scheduled.shift().fn(); await tick();
  assert.deepEqual(started, [0,600,1200]); assert.equal(peak, 2);
  releases.splice(0).forEach(release => release()); await Promise.all(reads);
});

function clocked(extra = {}) {
  let time = 0, isHidden = false, nextTimer = 0;
  const timers = new Map(), calls = [];
  const source = create({now:() => time, hidden:() => isHidden,
    delay:(fn, ms) => {const id = ++nextTimer; timers.set(id, {fn, at:time + ms}); return id;},
    cancel:id => timers.delete(id), read:async path => {
      calls.push({path, at:time});
      return {status:'ready', enabled:true, items:[], fetched_at:new Date(time).toISOString()};
    }, ...extra});
  return {source, calls, timers, hide(value = true) {isHidden = value; source.setVisible(!value);},
    async advance(ms) {
      const end = time + ms;
      for (let turns = 0; turns < 5000; turns++) {
        const first = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
        if (!first || first[1].at > end) break;
        time = first[1].at; timers.delete(first[0]); first[1].fn(); await tick();
      }
      time = end; await tick();
    }};
}

test('withdrawn index demand is pruned before admission instead of delaying a new region for a minute', async () => {
  const clock = clocked(), {source, calls} = clock;
  source.setTypes(['air_quality_station']); source.setVisible(true);
  source.demandIndexes(Array.from({length:100}, (_, i) => i + 1));
  source.demandIndexes([999]); await tick(); await clock.advance(600);
  const target = calls.find(call => call.path.includes('id=999&'));
  assert.ok(target); assert.equal(target.at, 600);
  assert.equal(calls.filter(call => call.path.includes('kind=index')).length, 1);
  source.deactivate(); await tick();
});

test('index queue is bounded and hidden documents cancel queued demand without starting more reads', async () => {
  const clock = clocked(), {source, calls} = clock;
  source.setTypes(['air_quality_station']); source.setVisible(true);
  source.demandIndexes(Array.from({length:1000}, (_, i) => i + 1)); await tick();
  assert.ok(source.queuedCount <= MAX_INDEX_QUEUE);
  assert.ok(source.pendingCount <= MAX_INDEX_QUEUE + 2);
  clock.hide(); await tick();
  const before = calls.length;
  await clock.advance(3600000);
  assert.equal(calls.length, before); assert.equal(source.queuedCount, 0); assert.equal(source.pendingCount, 0);
});

test('station metadata and selected sensor data bypass index admission even with a frozen clock', async () => {
  const clock = clocked(), {source, calls} = clock;
  source.setTypes(['air_quality_station']); source.setVisible(true); source.demandIndexes([1, 2, 3]);
  const first = source.loadSensors(91), shared = source.loadSensors(91), data = source.loadSensor(912);
  await Promise.all([first, shared, data]);
  assert.equal(calls.filter(call => call.path.includes('kind=sensors')).length, 1);
  assert.equal(calls.filter(call => call.path.includes('kind=data')).length, 1);
  assert.ok(calls.every(call => call.at === 0));
  source.deactivate(); await tick();
});

test('selected sensor refreshes at its TTL and stops on deselection, historical mode and hidden document', async () => {
  const clock = clocked(), {source, calls} = clock;
  source.setTypes(['air_quality_station']); source.setVisible(true); source.demandSensor(912); await tick();
  const sensorCalls = () => calls.filter(call => call.path.includes('id=912&kind=data'));
  assert.equal(sensorCalls().length, 1);
  // Routine sync keeps the same timer and does not postpone its deadline.
  await clock.advance(60000); source.setVisible(true); source.setTypes(['air_quality_station']);
  await clock.advance(1740000); assert.equal(sensorCalls().length, 2);
  source.demandSensor(null); await clock.advance(1800000); assert.equal(sensorCalls().length, 2);
  source.demandSensor(912); await tick(); assert.equal(sensorCalls().length, 3);
  source.setTypes(['air_quality_station'], {live:false}); await clock.advance(1800000);
  assert.equal(sensorCalls().length, 3);
  source.setTypes(['air_quality_station'], {live:true}); await tick(); assert.equal(sensorCalls().length, 4);
  clock.hide(); await clock.advance(1800000); assert.equal(sensorCalls().length, 4);
});

test('an external consumer keeps a queued shared index alive after workspace demand is withdrawn', async () => {
  const clock = clocked(), {source, calls} = clock;
  source.setTypes(['air_quality_station']); source.setVisible(true); source.demandIndexes([1, 2]);
  const external = source.request('/gios?kind=index&id=2');
  source.demandIndexes([]); await tick(); await clock.advance(600);
  assert.equal((await external).status, 'ready');
  assert.ok(calls.some(call => call.path.includes('id=2&kind=index')));
  source.deactivate(); await tick();
});

test('transport shares reads at ten seconds and historical/hidden views withdraw all demand', async () => {
  const clock = clocked(), {source, calls} = clock;
  source.setTypes(['aircraft', 'ship'], {live:false}); source.setVisible(true); await tick();
  assert.equal(calls.length, 0);
  source.setTypes(['aircraft', 'ship']); await tick();
  assert.deepEqual(calls.map(call => call.path).sort(), ['/aircraft', '/ships']);
  await Promise.all([source.request('/aircraft'), source.request('/ships')]);
  assert.equal(calls.length, 2);
  await clock.advance(9999); assert.equal(calls.length, 2);
  await clock.advance(1); assert.equal(calls.length, 4);
  source.setTypes(['aircraft', 'ship'], {live:false});
  await clock.advance(60000); assert.equal(calls.length, 4);
  source.setTypes(['aircraft', 'ship']); await tick(); assert.equal(calls.length, 6);
  clock.hide(); await clock.advance(60000); assert.equal(calls.length, 6);
});

test('quiet AIS uses polling TTL without rejuvenating the source timestamp', async () => {
  const stamp = '2020-01-01T00:00:00Z';
  let reads = 0;
  const clock = clocked({read:async () => {reads++; return {status:'ready', fetched_at:stamp, items:[]};}});
  clock.source.setTypes(['ship']); clock.source.setVisible(true); await tick();
  await clock.advance(9999); assert.equal(reads, 1);
  await clock.advance(1); assert.equal(reads, 2);
  assert.equal((await clock.source.request('/ships')).fetched_at, stamp);
  clock.source.deactivate();
});
