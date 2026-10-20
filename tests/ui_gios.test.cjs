'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function harness(region){
 const controls=new Map(),requests=[],markers=[],timeouts=new Map(),intervals=new Map();let id=0,now=Date.parse('2026-10-17T06:30:00Z');
 const element=tag=>({tag,checked:false,value:'',textContent:'',hidden:false,style:{},children:[],classList:{toggle(){}},addEventListener(k,f){this[k]=f;},append(...e){this.children.push(...e);},replaceChildren(...e){this.children=[...e];this.value='';}});
 const document={hidden:false,addEventListener(k,f){this[k]=f;},createElement:element,getElementById(id){if(!controls.has(id))controls.set(id,element('div'));return controls.get(id);}};
 const events={},map={bounds:[50,15,52,17],layers:new Set(),on(k,f){events[k]=f;},getBounds(){return {contains:([lat,lon])=>lat>=this.bounds[0]&&lon>=this.bounds[1]&&lat<=this.bounds[2]&&lon<=this.bounds[3]};},createPane(){return {style:{}};},removeLayer(l){this.layers.delete(l);l.markers.forEach(m=>m.open=false);},setView(){this.panned=true;}};
 const L={layerGroup(){return {markers:new Set(),removeLayer(m){this.markers.delete(m);m.open=false;},addTo(m){m.layers.add(this);return this;}};},circleMarker(coords,options){const m={coords,options,bindTooltip(){return this;},bindPopup(f){this.content=f;return this;},on(k,f){this[k]=f;return this;},addTo(g){g.markers.add(this);return this;},setLatLng(){return this;},setStyle(style){Object.assign(this.options,style);return this;},setTooltipContent(content){this.tooltip=content;return this;},isPopupOpen(){return !!this.open;},getPopup(){return {update:()=>this.rendered=this.content()};}};markers.push(m);return m;}};
 class Clock extends Date{static now(){return now;}}
 const window={WiciRegion:region};vm.runInNewContext(fs.readFileSync('src/wici/static/js/gios.js','utf8'),{window,document,L,Intl,AbortController,Date:Clock,setTimeout(f,delay){timeouts.set(++id,{f,delay,at:now+delay});return id;},clearTimeout(i){timeouts.delete(i);},setInterval(f){intervals.set(++id,f);return id;},clearInterval(i){intervals.delete(i);}});
 document.getElementById('gios-parameter').value='PM10';window.WiciGios.init({map,api:(url,body,options)=>new Promise((resolve,reject)=>requests.push({url,resolve,reject,signal:options.signal,at:now}))});
 return {ui:window.WiciGios,document,map,requests,markers,timeouts,intervals,control:n=>document.getElementById('gios-'+n),advance(ms){now+=ms;},refresh(){const [i,t]=[...timeouts].find(([,t])=>t.delay===300000);timeouts.delete(i);t.f();},move(bounds){events.movestart();map.bounds=bounds;events.moveend();},tick(){for(const f of intervals.values())f();},async run(ms){const end=now+ms;for(;;){const next=[...timeouts].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;const [i,t]=next;timeouts.delete(i);now=t.at;t.f();await new Promise(r=>setImmediate(r));}now=end;}};
}
const base={enabled:true,items:[],status:'ready',fetched_at:'2026-10-17T06:30:00Z',refresh_seconds:300};
const stations={...base,items:[{id:52,name:'Stacja <script>',address:'Adres',latitude:51,longitude:16},{id:53,name:'Bez lokalizacji',latitude:null,longitude:null}]};
const sensors={...base,items:[{id:295,parameter:'PM10',name:'PM10 manualny'},{id:14397,parameter:'PM10',name:'PM10 automatyczny'}]};
const series={...base,items:[{value:0,unit:'µg/m³',observed_at:'2026-10-17T06:00:00Z',source_time:'2026-10-17 08:00:00'},{value:null,source_time:'2026-10-17 09:00:00'}],latest:{value:0,unit:'µg/m³',observed_at:'2026-10-17T06:00:00Z',source_time:'2026-10-17 08:00:00'}};
const text=e=>[e.textContent,...e.children.map(text)].join(' ');
const flush=()=>new Promise(r=>setImmediate(r));
async function enable(h,payload=stations){h.control('enabled').checked=true;h.control('enabled').change();h.requests[0].resolve(payload);await flush();}
const indexData={...base,refresh_seconds:1800,items:[{name:'Dobry',value:1,observed_at:'2026-10-17T06:00:00Z',calculated:{observed_at:'2026-10-17T06:20:00Z'}}]};
async function select(h){h.control('station').value='52';h.control('station').change();await h.run(0);h.requests.find(r=>r.url.includes('kind=index')).resolve(indexData);h.requests.find(r=>r.url.includes('kind=sensors')).resolve(sensors);await flush();h.requests.at(-1).resolve(series);await flush();}

test('on demand, station selection, missing pollutants, duplicate sensors and safe text',async()=>{
 const h=harness();assert.equal(h.requests.length,0);await enable(h);assert.equal(h.markers.length,1);assert.equal(h.requests.length,1);
 assert.equal(h.control('station').children.length,3);await select(h);
 assert.match(text(h.control('detail')),/Stacja <script>/);assert.match(text(h.control('detail')),/0 µg\/m³/);assert.match(text(h.control('detail')),/brak parametru na stacji/);
 assert.match(text(h.control('detail')),/Oficjalny polski indeks/);assert.match(text(h.control('history')),/Brak pomiaru \(null\)/);
 assert.equal(h.requests.length,4);assert.equal(h.control('sensor').children.length,3);
 h.control('sensor').value='14397';h.control('sensor').change();assert.equal(h.requests.at(-1).url,'/gios?kind=data&id=14397');h.requests.at(-1).resolve({...base,status:'manual',message:'Stanowisko manualne',items:[]});await flush();assert.match(text(h.control('detail')),/Stanowisko manualne/);
 h.control('parameter').value='CO';h.control('parameter').change();await flush();assert.equal(h.requests.length,5);assert.doesNotMatch(text(h.control('detail')),/Stężenie CO/);
});
test('late responses ignored after selection, hide, disable and timers stop',async()=>{
 const h=harness();await enable(h);h.control('station').value='52';h.control('station').change();const late=h.requests.slice(1);
 h.ui.sync({visible:false});assert.ok(late.every(r=>r.signal.aborted));assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);assert.equal(h.map.layers.size,0);
 late.forEach(r=>r.resolve(base));await flush();assert.equal(h.requests.length,2);assert.equal(h.timeouts.size,0);
 h.ui.sync({visible:true});h.control('enabled').checked=false;h.control('enabled').change();h.requests.at(-1).resolve(stations);await flush();assert.equal(h.timeouts.size,0);assert.equal(h.map.layers.size,0);
});
test('aging, failed refresh and open details/popup survive health sync',async()=>{
 const h=harness();await enable(h);await select(h);const m=h.markers[0];m.open=true;h.control('history').open=true;
 const tick=[...h.intervals.keys()][0];h.advance(4*3600000);h.ui.sync({visible:true});assert.equal([...h.intervals.keys()][0],tick);[...h.intervals.values()][0]();
 assert.match(text(m.rendered),/NIEAKTUALNY/);assert.equal(h.control('history').open,true);assert.equal(m.open,true);
 h.refresh();h.requests.at(-1).reject(new Error('offline'));await flush();
 // load continues selected detail refresh despite station transport failure.
 for(const r of h.requests.slice(-3))r.reject(new Error('offline'));await flush();
 assert.match(text(h.control('detail')),/ostatnie dane zachowane/);assert.equal(m.open,true);assert.equal(h.markers.length,1);
});
test('parameter change rejects late previous sensor response; missing index is explicit',async()=>{
 const h=harness();await enable(h);await select(h);h.control('sensor').value='14397';h.control('sensor').change();const late=h.requests.at(-1);
 h.control('parameter').value='CO';h.control('parameter').change();late.resolve(series);await flush();assert.doesNotMatch(text(h.control('detail')),/Stężenie CO/);
 h.control('station').value='53';h.control('station').change();h.requests.at(-1).resolve({...base,items:[]});await flush();
 assert.match(text(h.control('detail')),/Brak indeksu — jakość powietrza nieznana/);assert.match(text(h.control('detail')),/Brak poprawnych współrzędnych/);
});

test('refresh removes obsolete sensor results before selecting a replacement',async()=>{
 const h=harness();await enable(h);await select(h);h.refresh();h.requests.at(-1).resolve(stations);await flush();
 h.requests.at(-2).resolve({...base,items:[{id:999,parameter:'PM10',name:'Nowe stanowisko'}]});
 h.requests.at(-1).resolve(series);await flush();
 assert.equal(h.control('sensor').value,'999');assert.equal(h.requests.at(-1).url,'/gios?kind=data&id=999');
 assert.doesNotMatch(text(h.control('detail')),/0 µg\/m³/);h.requests.at(-1).resolve({...base,items:[]});await flush();
});

test('disabled demo schedules no timers and document hiding cancels both timers',async()=>{
 const h=harness();h.control('enabled').checked=true;h.control('enabled').change();h.requests[0].resolve({...base,enabled:false,status:'disabled',message:'GIOŚ wyłączone w demonstracji.'});await flush();
 assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);h.ui.sync({visible:true});assert.equal(h.intervals.size,0);assert.equal(h.requests.length,1);
 const b=harness();await enable(b);b.document.hidden=true;b.document.visibilitychange();assert.equal(b.timeouts.size,0);assert.equal(b.intervals.size,0);assert.equal(b.map.layers.size,0);
});

test('authoritative station removal clears its selected series and closes popup',async()=>{
 const h=harness();await enable(h);await select(h);const m=h.markers[0];m.open=true;
 h.refresh();h.requests.at(-1).resolve({...base,items:[]});await flush();
 assert.equal(m.open,false);assert.equal(h.control('station').value,'');assert.doesNotMatch(text(h.control('history')),/0/);
});

for(const first of ['selection','refresh'])test(`overlapping ${first} success survives the other request failing`,async()=>{
 const h=harness();await enable(h);await select(h);
 const marker=h.markers[0];marker.open=true;h.control('history').open=true;
 h.control('sensor').value='14397';h.control('sensor').change();const selected=h.requests.at(-1);
 h.refresh();h.requests.at(-1).resolve(stations);await flush();const refreshed=h.requests.slice(-2);
 const fresh={...series,fetched_at:'2026-10-17T06:31:00Z',latest:{...series.latest,value:42},items:[{...series.latest,value:42}]};
 if(first==='selection'){
  selected.resolve(fresh);await flush();assert.match(text(h.control('detail')),/42 µg\/m³/);
  refreshed[1].reject(new Error('Connection lost'));
 }else{
  refreshed[1].resolve(fresh);refreshed[0].resolve(sensors);await flush();
  assert.match(text(h.control('detail')),/42 µg\/m³/);selected.reject(new Error('Connection lost'));
 }
 refreshed[0].resolve(sensors);await flush();
 assert.match(text(h.control('detail')),/42 µg\/m³/);
 assert.match(text(h.control('detail')),/ostatnie dane zachowane/);
 assert.match(text(h.control('detail')),/08:31/);
 assert.match(text(h.control('history')),/42/);
 assert.match(text(marker.rendered),/42 µg\/m³/);assert.equal(marker.open,true);
 assert.equal(h.control('history').open,true);
});

test('official six colors, zero, grey missing/stale/unknown time and legend agree',async()=>{
 const colors=JSON.parse(fs.readFileSync('tests/fixtures/gios/legend.json','utf8')).categories.slice(0,6).map(c=>c.color);
 for(const [value,color] of colors.entries()){
  const h=harness();await enable(h);await h.run(0);assert.equal(h.requests.at(-1).url,'/gios?kind=index&id=52');
  h.requests.at(-1).resolve({...indexData,items:[{...indexData.items[0],value}]});await flush();
  assert.equal(h.markers[0].options.fillColor,color);assert.equal(h.control('legend-items').children[value].children[0].style.backgroundColor,color);
  assert.equal(h.control('legend').hidden,false);assert.equal(h.control('legend-items').children.length,7);
 }
 for(const result of [{...indexData,items:[]},{...indexData,stale:true},{...indexData,status:'error'},
   {...indexData,items:[{...indexData.items[0],value:null}]},
   {...indexData,items:[{...indexData.items[0],observed_at:null}]},
   {...indexData,items:[{...indexData.items[0],observed_at:'2026-10-17T02:00:00Z'}]},
   {...indexData,items:[{...indexData.items[0],observed_at:'2026-10-17T07:00:00Z'}]}]){
  const h=harness();await enable(h);await h.run(0);h.requests.at(-1).resolve(result);await flush();assert.equal(h.markers[0].options.fillColor,'#bfbfbf');
 }
});
test('only viewport stations fetch indices; panning reuses cache then refreshes expired entry',async()=>{
 const h=harness(),other={id:54,name:'Inny widok',latitude:53,longitude:18};await enable(h,{...stations,items:[...stations.items,other]});
 await h.run(0);h.requests.at(-1).resolve(indexData);await flush();assert.equal(h.requests.length,2);
 h.move([52.5,17.5,53.5,18.5]);await h.run(599);assert.equal(h.requests.length,2);await h.run(1);
 assert.equal(h.requests.at(-1).url,'/gios?kind=index&id=54');h.requests.at(-1).resolve(indexData);await flush();
 h.move([50,15,52,17]);await h.run(1000);assert.equal(h.requests.length,3);
 h.advance(1800000);h.tick();await h.run(0);assert.equal(h.requests.at(-1).url,'/gios?kind=index&id=52');
 assert.ok(h.requests.every(r=>!r.url.includes('kind=sensors')&&!r.url.includes('kind=data')));
});
test('index queue permits at most two concurrent reads and spaces starts by 600 ms',async()=>{
 const h=harness(),items=Array.from({length:130},(_,i)=>({id:i+1,name:`Stacja ${i}`,latitude:51,longitude:16}));
 await enable(h,{...stations,items});await h.run(0);assert.equal(h.requests.length,2);await h.run(600);assert.equal(h.requests.length,3);
 await h.run(5000);assert.equal(h.requests.length,3,'two pending reads hold the queue');
 h.requests[1].resolve(indexData);h.requests[2].resolve(indexData);await flush();
 for(let i=0;i<100;i++){
  await h.run(600);
  for(const r of h.requests.slice(3))r.resolve(indexData);
  await flush();
 }
 const reads=h.requests.filter(r=>r.url.includes('kind=index'));
 for(let i=1;i<reads.length;i++)assert.ok(reads[i].at-reads[i-1].at>=600);
 for(const read of reads)assert.ok(reads.filter(r=>r.at>=read.at&&r.at<read.at+60000).length<=100);
});
test('leaving viewport or hiding cancels index reads and discards late color updates',async()=>{
 const h=harness();await enable(h);await h.run(0);const first=h.requests.at(-1);
 h.move([40,10,41,11]);assert.equal(first.signal.aborted,true);first.resolve(indexData);await flush();
 assert.equal(h.markers[0].options.fillColor,'#bfbfbf');h.move([50,15,52,17]);await h.run(600);
 const second=h.requests.at(-1);assert.notEqual(first,second);h.ui.sync({visible:false});assert.equal(second.signal.aborted,true);
 second.resolve(indexData);await flush();assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);assert.equal(h.map.layers.size,0);
});
test('global Retry-After pauses the remaining viewport queue',async()=>{
 const h=harness();await enable(h,{...stations,items:[stations.items[0],{...stations.items[0],id:54}]});
 await h.run(0);h.requests.at(-1).resolve({...base,status:'error',service_retry_after_seconds:1200});await flush();
 await h.run(1199999);assert.equal(h.requests.filter(r=>r.url.includes('kind=index')).length,1);
 await h.run(1);assert.equal(h.requests.filter(r=>r.url.includes('kind=index')).length,2);
  // A local transport failure must not renew a relative Retry-After from the retained response.
  h.requests.at(-1).reject(new Error('Local API unavailable'));await flush();await h.run(600);
  assert.equal(h.requests.filter(r=>r.url.includes('kind=index')).length,3);
});
test('cached index becomes grey when its own source time exceeds three hours',async()=>{
 const h=harness();await enable(h);await h.run(0);h.requests.at(-1).resolve({...indexData,items:[{...indexData.items[0],value:0,observed_at:'2026-10-17T03:31:00Z'}]});await flush();
 const marker=h.markers[0];marker.open=true;assert.equal(marker.options.fillColor,'#57b108');h.advance(120000);h.tick();
 assert.equal(marker.options.fillColor,'#bfbfbf');assert.match(text(marker.rendered),/NIEAKTUALNY/);assert.equal(marker.open,true);assert.equal(h.requests.length,2);
});
test('unmapped station selection never requests an index',async()=>{
 const h=harness();await enable(h,{...stations,items:[stations.items[1]]});h.control('station').value='53';h.control('station').change();await h.run(0);
 assert.equal(h.requests.at(-1).url,'/gios?kind=sensors&id=53');h.requests.at(-1).resolve({...base,items:[]});await flush();
 assert.ok(!h.requests.some(r=>r.url.includes('kind=index')));assert.match(text(h.control('detail')),/wyłącznie dla stacji widocznych/);
});

test('region change cancels outside index queue, filters stations and restores national cached list',async()=>{
 let code='02';const progress=[];const h=harness({contains:(lat,lon)=>!code||(Number.isFinite(lon)&&(code==='02'?lon<18:lon>20)),progress:(id,value)=>progress.push(value)});
 h.map.bounds=[49,14,55,24];await enable(h,{...stations,items:[...stations.items,{id:54,name:'Warszawa',latitude:52.23,longitude:21.01}]});
 assert.equal(h.control('station').children.length,2);await h.run(0);const old=h.requests.find(r=>r.url.includes('kind=index'));assert.match(old.url,/id=52/);
 code='14';h.document['wici:regionchange']();assert.ok(old.signal.aborted);assert.equal(h.control('station').children.length,2);assert.equal(h.control('station').children[1].value,'54');
 old.resolve(indexData);await flush();await h.run(2000);const latest=h.requests.filter(r=>r.url.includes('kind=index')).at(-1);assert.match(latest.url,/id=54/);latest.resolve(indexData);await flush();assert.equal(progress.at(-1).done,1);assert.equal(progress.at(-1).total,1);
 code='';h.document['wici:regionchange']();assert.equal(h.control('station').children.length,4);assert.equal(h.requests.filter(r=>r.url==='/gios').length,1);
});

test('expanding region resumes an interrupted selected station detail without refetching national list',async()=>{
 const h=harness({contains:()=>true,progress(){}});await enable(h);h.control('station').value='52';h.control('station').change();const old=h.requests.find(r=>r.url.includes('kind=sensors'));
 h.document['wici:regionchange']();assert.ok(old.signal.aborted);assert.equal(h.requests.filter(r=>r.url==='/gios').length,1);
 const latest=h.requests.filter(r=>r.url.includes('kind=sensors')).at(-1);assert.notEqual(latest,old);old.resolve({...base,items:[]});latest.resolve(sensors);await flush();h.requests.at(-1).resolve(series);await flush();assert.match(text(h.control('detail')),/0 µg\/m³/);
});
