'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync('src/wici/static/js/tracking.js','utf8'),sandbox);
const {normalizePoints,frameAt}=sandbox.window.WiciTracking;
const base=Date.parse('2026-10-20T12:00:00Z');
const point=(seconds,extra={})=>({position_at:new Date(base+seconds*1000).toISOString(),
  latitude:52+seconds*.0001,longitude:19+seconds*.0002,break_before:false,...extra});
const plain=value=>JSON.parse(JSON.stringify(value));

test('timeline uses source times and excludes invalid and duplicate observations',()=>{
  const points=normalizePoints([point(30),point(0),point(30),point(10),
    point(15,{latitude:NaN}),point(20,{longitude:181}),point(25,{position_at:'invalid'})]);
  assert.deepEqual(plain(points.map(p=>p.at)),[base,base+10000,base+30000]);
  assert.equal(frameAt(points,base-1).point,null);
  assert.equal(frameAt(points,base+29000).point.at,base+10000);
  assert.equal(frameAt(points,base+30000).point.at,base+30000);
});

test('seeking across a data gap holds the last observation and never draws a connecting segment',()=>{
  const points=normalizePoints([point(0,{break_before:true}),point(10),
    point(7200,{break_before:true}),point(7210)]);
  const during=frameAt(points,base+3600000);
  assert.equal(during.inGap,true);
  assert.equal(during.point.at,base+10000);
  assert.deepEqual(plain(during.segments),[[[52,19],[52.001,19.002]]]);
  const after=frameAt(points,base+7210000);
  assert.equal(after.inGap,false);
  assert.equal(after.segments.length,2);
  assert.equal(after.segments[0].length,2);
  assert.equal(after.segments[1].length,2);
});

test('new live observations preserve historical frame and no future route is shown',()=>{
  const initial=normalizePoints([point(0),point(10),point(20)]);
  const before=frameAt(initial,base+15000);
  const appended=normalizePoints([point(0),point(10),point(20),point(30)]);
  const after=frameAt(appended,base+15000);
  assert.deepEqual(plain(before),plain(after));
  assert.equal(after.segments[0].length,2);
});

test('empty and one-observation histories have deterministic frames',()=>{
  const empty=frameAt([],base);
  assert.equal(empty.point,null);
  assert.equal(empty.index,-1);
  assert.equal(empty.segments.length,0);
  const single=frameAt(normalizePoints([point(0)]),base+100000);
  assert.equal(single.index,0);
  assert.equal(single.inGap,false);
  assert.deepEqual(plain(single.segments),[[[52,19]]]);
});
