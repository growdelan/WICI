'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(){
 const controls=new Map(),events={},requests=[],layers=new Set(),fits=[];let code='02';
 const element=()=>({value:'',children:[],style:{},textContent:'',checked:false,append(...els){this.children.push(...els);},replaceChildren(...els){this.children=els;this.value='';},setAttribute(){},addEventListener(k,fn){this[k]=fn;}});
 const document={hidden:false,getElementById(id){if(!controls.has(id))controls.set(id,element());return controls.get(id);},createElement:element,addEventListener(k,fn){events[k]=fn;}};
 const container=element(),map={getCenter:()=>({lat:51.11,lng:17.04}),getContainer:()=>container,createPane:()=>element(),fitBounds:b=>fits.push(b),removeLayer:l=>layers.delete(l),closePopup(){}};
 const layer=()=>({bindTooltip(){return this;},addTo(){layers.add(this);return this;},remove(){layers.delete(this);}});
 const window={WiciRegion:{contains:(lat,lon)=>!code||(code==='02'?lon<18:lon>20)}};
 vm.runInNewContext(fs.readFileSync('src/wici/static/js/sentinel2.js','utf8'),{window,document,L:{circleMarker:layer,rectangle:layer},URLSearchParams,AbortController,Option:function(text,value){return {text,value};},fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,signal:options?.signal,resolve:data=>resolve({ok:true,json:async()=>data}),reject})),Image:function(){throw Error('Late render must never decode images');}});
 window.WiciSentinel2.init({map});const control=name=>document.getElementById('s2-'+name);control('enabled').checked=true;control('size').value='4';control('center').click();
 return {control,requests,layers,fits,map,region(value){code=value;events['wici:regionchange']();}};
}
const result=()=>({items:[{id:'before',observed_at:'2026-10-01T10:00:00Z'},{id:'after',observed_at:'2026-10-15T10:00:00Z'}],grid:{bounds:[[51,17],[51.2,17.2]]}});
for(const failure of [false,true])test(`changing province cancels search and ignores late ${failure?'error':'success'}`,async()=>{
 const h=harness();h.control('search').click();const old=h.requests[0];h.region('14');assert.ok(old.signal.aborted);assert.equal(h.layers.size,0);assert.equal(h.control('point').textContent,'Nie wybrano punktu.');
 for(const r of h.requests)if(failure)r.reject(Error('old failure'));else r.resolve(result());await flush();assert.equal(h.fits.length,0);assert.equal(h.control('before').children.length,1);assert.match(h.control('status').textContent,/Zmieniono obszar/);
 h.region('02');assert.equal(h.layers.size,0);h.map.getCenter=()=>({lat:52.23,lng:21.01});h.region('14');h.control('center').click();h.control('search').click();assert.ok(!h.requests[2].signal.aborted);h.requests.slice(2).forEach(r=>r.resolve(result()));await flush();assert.equal(h.fits.length,1);assert.equal(h.control('before').children.length,3);
});
test('region change invalidates both pending comparison renders and clears selections and geometry',async()=>{
 const h=harness();h.control('search').click();h.requests.slice(0,2).forEach(r=>r.resolve(result()));await flush();h.control('before').value='before';h.control('after').value='after';h.control('compare').click();assert.equal(h.requests.length,4);
 h.region('14');assert.ok(h.requests.slice(2).every(r=>r.signal.aborted));assert.equal(h.layers.size,0);assert.equal(h.control('detail').children.length,0);assert.equal(h.control('before').children.length,1);
 h.requests.slice(2).forEach(r=>r.resolve({}));await flush();h.control('compare').click();assert.equal(h.requests.length,4);
});
test('expanding to Poland retains valid pending point and accepts its search',async()=>{
 const h=harness();h.control('search').click();h.region('');assert.ok(!h.requests[0].signal.aborted);h.requests.slice(0,2).forEach(r=>r.resolve(result()));await flush();assert.equal(h.fits.length,1);assert.equal(h.control('before').children.length,3);
});

function ranges(h){
 for(const [side,year] of [['before','2020'],['after','2026']]){
  h.control(side+'-start').value=year+'-06-01';h.control(side+'-end').value=year+'-06-30';
 }
}
const yearResult=year=>({items:[{id:'scene-'+year,observed_at:year+'-06-15T10:00:00Z',catalog_coverage_percent:100}],grid:result().grid});
test('separate 2020 and 2026 searches populate only their respective lists and render exact choices',async()=>{
 const h=harness();ranges(h);h.control('search').click();
 assert.equal(h.requests.length,2);
 for(const [index,year] of ['2020','2026'].entries()){
  const params=new URL(h.requests[index].url,'http://local').searchParams;
  assert.equal(params.get('start'),year+'-06-01');assert.equal(params.get('end'),year+'-06-30');
 }
 // Arrival order must not exchange the two sides.
 h.requests[1].resolve(yearResult('2026'));h.requests[0].resolve(yearResult('2020'));await flush();
 assert.deepEqual(h.control('before').children.map(i=>i.value),['','scene-2020']);
 assert.deepEqual(h.control('after').children.map(i=>i.value),['','scene-2026']);
 h.control('before').value='scene-2020';h.control('after').value='scene-2026';h.control('compare').click();
 assert.equal(h.requests.length,4);
 assert.equal(new URL(h.requests[2].url,'http://local').searchParams.get('identifier'),'scene-2020');
 assert.equal(new URL(h.requests[3].url,'http://local').searchParams.get('identifier'),'scene-2026');
 h.control('before-start').change();assert.ok(h.requests.slice(2).every(r=>r.signal.aborted));
 assert.equal(h.control('before').children.length,1);
 assert.equal(h.control('after').value,'scene-2026');assert.equal(h.control('after').children.length,2);
 h.requests.slice(2).forEach(r=>r.resolve({}));await flush();assert.equal(h.control('detail').children.length,0);
});
for(const side of ['before','after'])test(`${side} range changes cancel both pending searches and reject late results`,async()=>{
 const h=harness();ranges(h);h.control('search').click();const old=[...h.requests];
 h.control(side+'-end').value='2020-07-01';h.control(side+'-end').change();
 assert.ok(old.every(r=>r.signal.aborted));
 // Same point, new date range: even an old failure cannot replace the new status.
 h.control('search').click();h.requests[2].resolve(yearResult('2020'));h.requests[3].resolve(yearResult('2026'));await flush();
 old[0].resolve(result());old[1].reject(Error('stale error'));await flush();
 assert.deepEqual(h.control('before').children.map(i=>i.value),['','scene-2020']);
 assert.deepEqual(h.control('after').children.map(i=>i.value),['','scene-2026']);
 assert.doesNotMatch(h.control('status').textContent,/stale error/);assert.equal(h.fits.length,1);
});
test('one failed or empty range does not erase successful observations from the other range',async()=>{
 const h=harness();ranges(h);h.control('search').click();h.requests[0].reject(Error('Testowa awaria 2020'));
 h.requests[1].resolve(yearResult('2026'));await flush();
 assert.equal(h.control('before').children.length,1);assert.equal(h.control('after').children.length,2);
 assert.match(h.control('before-status').textContent,/awaria 2020/);
 assert.match(h.control('after-status').textContent,/1 obserwacji/);
 h.control('after').value='scene-2026';h.control('compare').click();assert.equal(h.requests.length,2);
 h.control('search').click();h.requests[2].resolve(yearResult('2020'));h.requests[3].resolve({items:[]});await flush();
 assert.equal(h.control('before').children.length,2);assert.equal(h.control('after').children.length,1);
 assert.match(h.control('after-status').textContent,/Brak obserwacji/);
});
test('an observation from the opposite range cannot be selected by assigning its ID',async()=>{
 const h=harness();ranges(h);h.control('search').click();h.requests[0].resolve(yearResult('2020'));h.requests[1].resolve(yearResult('2026'));await flush();
 h.control('before').value='scene-2026';h.control('after').value='scene-2020';h.control('compare').click();assert.equal(h.requests.length,2);
 assert.match(h.control('status').textContent,/Wybierz dwie różne/);
});
