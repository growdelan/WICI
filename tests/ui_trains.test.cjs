const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(){
  let now=Date.parse('2026-10-15T12:00:00Z'),next=0;
  const requests=[],markers=[],groups=[],lines=[],timeouts=new Map(),intervals=new Map(),elements=new Map(),listeners={};
  function element(tag='div'){return {tag,children:[],textContent:'',style:{},checked:false,className:'',classList:{toggle(){}},append(...nodes){this.children.push(...nodes);},addEventListener(type,fn){this[type]=fn;},querySelectorAll(selector){return this.children.flatMap(n=>[...(selector==='.train-meta'&&n.className==='train-meta'?[n]:[]),...n.querySelectorAll(selector)]);}};}
  const document={hidden:false,createElement:element,getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},addEventListener(type,fn){listeners[type]=fn;}};
  const map={createPane(){return {style:{}};},attributionControl:{addAttribution(){}},removeLayer(layer){layer.removed=true;},fitBounds(bounds,options){this.bounds=bounds;this.fitOptions=options;}};
  const L={layerGroup(){const group={items:[],addTo(){groups.push(this);return this;},removeLayer(marker){this.items=this.items.filter(m=>m!==marker);}};return group;},circleMarker(coords,options){const marker={coords,options,handlers:{},bindPopup(content,options){this.content=content;this.popupOptions=options;return this;},bindTooltip(){return this;},on(type,fn){this.handlers[type]=fn;return this;},addTo(group){group.items.push(this);markers.push(this);return this;},setPopupContent(content){this.content=content;return this;},setLatLng(coords){this.coords=coords;return this;},getPopup(){return {getContent:()=>this.content};},open(){if(typeof this.content==='function')this.content=this.content();this.handlers.popupopen();}};return marker;},polyline(coords,options){const line={coords,options,addTo(group){group.items.push(this);lines.push(this);return this;},getBounds(){return this.coords;}};return line;}};
  L.marker=L.circleMarker;L.divIcon=options=>options;
  class FakeDate extends Date{static now(){return now;}}
  const window={};const ctx=vm.createContext({window,document,L,Date:FakeDate,AbortController,console,setTimeout(fn,ms){timeouts.set(++next,{fn,ms});return next;},clearTimeout(id){timeouts.delete(id);},setInterval(fn,ms){intervals.set(++next,{fn,ms});return next;},clearInterval(id){intervals.delete(id);},fetch(url,options){return new Promise((resolve,reject)=>requests.push({url,signal:options.signal,resolve:body=>resolve({ok:true,json:async()=>body}),reject}));}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/wici/static/js/trains.js'),'utf8'),ctx);
  window.WiciTrains.init({map,health:{mode:'live'}});
  const control=id=>document.getElementById(`trains-${id}`);
  return {ui:window.WiciTrains,map,document,control,requests,markers,groups,lines,timeouts,intervals,listeners,advance(ms){now+=ms;},refresh(){const entry=[...timeouts.entries()].find(([,v])=>v.ms===60000);assert.ok(entry);timeouts.delete(entry[0]);entry[1].fn();}};
}
const meta={source_updated_at:'2026-10-15T12:00:00Z',stale:false,stale_after_seconds:600};
const stations={...meta,items:[{id:'PL/A',name:'Stacja <test>',latitude:52,longitude:19},{id:'PL:B',name:'Druga',latitude:53,longitude:20}]};
const departure={trip_id:'IC/1',start_date:'2026-10-15',number:'123',headsign:'Warszawa',operator:'IC',scheduled_at:'2026-10-15T12:00:00Z',expected_at:'2026-10-15T12:10:00Z',delay_seconds:600,realtime:true};
const board={...meta,station:stations.items[0],departures:[departure]};
const trip={...meta,trip:{id:'IC/1',number:'123',headsign:'Warszawa',operator:'IC',realtime:true,stops:[{name:'Stacja <test>',scheduled_arrival:'2026-10-15T11:59:00Z',scheduled_departure:'2026-10-15T12:00:00Z',expected_arrival:'2026-10-15T12:09:00Z',expected_departure:'2026-10-15T12:10:00Z',delay_seconds:600}],geometry:{type:'LineString',coordinates:[[19,52],[20,53]]}}};
function text(node){return [node.textContent,...node.children.map(text)].join(' ');}
function buttons(node){return node.children.flatMap(n=>[...(n.tag==='button'?[n]:[]),...buttons(n)]);}
async function enable(h){h.ui.sync({visible:true});assert.equal(h.requests.length,0);h.control('enabled').checked=true;h.control('enabled').change();h.requests[0].resolve(stations);await flush();}

test('station board loads on click and course shows supplied route, times and stops',async()=>{
  const h=harness();await enable(h);assert.equal(h.markers.length,2);assert.equal(h.requests.length,1);assert.equal(h.markers[0].popupOptions.maxHeight,360);assert.equal(h.markers[0].popupOptions.maxWidth,320);
  h.markers[0].open();assert.equal(h.requests[1].url,'/api/trains/stations/PL%2FA');h.requests[1].resolve(board);await flush();
  assert.match(text(h.markers[0].content),/Stacja <test>/);assert.match(text(h.markers[0].content),/14:00 → 14:10/);assert.match(text(h.markers[0].content),/\+10 min/);
  const originalBoard=h.markers[0].content;let stopped=0;buttons(originalBoard)[0].click({stopPropagation(){assert.equal(h.markers[0].content,originalBoard);stopped++;}});assert.equal(stopped,1);assert.equal(h.requests[2].url,'/api/trains/trips/IC%2F1?start_date=2026-10-15');h.requests[2].resolve(trip);await flush();
  assert.equal(h.map.fitOptions.animate,false);assert.equal(JSON.stringify(h.lines[0].coords),'[[52,19],[53,20]]');assert.match(text(h.markers[0].content),/Przyjazd: 13:59 → 14:09/);assert.equal(h.markers.length,2);
  const originalTrip=h.markers[0].content;buttons(originalTrip)[0].click({stopPropagation(){assert.equal(h.markers[0].content,originalTrip);stopped++;}});assert.equal(stopped,2);assert.equal(h.groups.at(-1).removed,true);assert.match(text(h.markers[0].content),/Odjazdy/);
});

test('source becomes stale with passing time and retained board flags refresh failure',async()=>{
  const h=harness();await enable(h);h.markers[0].open();h.requests[1].resolve(board);await flush();
  h.advance(601000);[...h.intervals.values()][0].fn();assert.match(h.control('status').textContent,/DANE NIEAKTUALNE/);assert.match(text(h.markers[0].content),/DANE NIEAKTUALNE/);
  h.refresh();h.requests[2].reject(new Error('offline'));h.requests[3].reject(new Error('offline'));await flush();assert.equal(h.markers.length,2);assert.match(text(h.markers[0].content),/Nie udało się odświeżyć odjazdów/);assert.match(h.control('status').textContent,/Ponowna próba/);
});

test('selection races and hidden layer abort requests and prevent late route resurrection',async()=>{
  const h=harness();await enable(h);h.markers[0].open();const old=h.requests[1];h.markers[1].open();assert.equal(old.signal.aborted,true);
  old.resolve(board);h.requests[2].resolve({...board,station:stations.items[1]});await flush();assert.match(text(h.markers[1].content),/Druga/);
  buttons(h.markers[1].content)[0].click();const pending=h.requests[3];h.ui.sync({visible:false});assert.equal(pending.signal.aborted,true);assert.equal(h.intervals.size,0);
  pending.resolve(trip);await flush();assert.equal(h.lines.length,0);assert.equal(h.timeouts.size,0);assert.equal(h.groups.every(group=>group.removed),true);
  h.ui.sync({visible:true});const latest=h.requests.at(-1);h.document.hidden=true;h.listeners.visibilitychange();assert.equal(latest.signal.aborted,true);latest.resolve(stations);await flush();assert.equal(h.timeouts.size,0);
});

test('station list is bounded in popup, detour is disclosed, and health sync does not duplicate refresh',async()=>{
  const h=harness();await enable(h);h.ui.sync({visible:true,health:{mode:'live'}});assert.equal(h.requests.length,1);
  h.markers[0].open();h.requests[1].resolve({...board,departures:Array.from({length:100},()=>departure)});await flush();assert.equal(buttons(h.markers[0].content).length,30);assert.match(text(h.markers[0].content),/pierwszych 30/);
  buttons(h.markers[0].content)[0].click();h.requests[2].resolve({...trip,trip:{...trip.trip,detour:true,geometry:null}});await flush();assert.equal(h.lines.length,0);assert.match(text(h.markers[0].content),/Zmieniona trasa/);
  h.ui.sync({health:{mode:'demo'}});assert.equal(h.control('enabled').disabled,true);assert.equal(h.timeouts.size,0);
});

test('disabled backend stops polling with explicit configuration status',async()=>{
  const h=harness();h.ui.sync({visible:true});h.control('enabled').checked=true;h.control('enabled').change();
  h.requests[0].resolve({enabled:false,items:[],message:'Źródło wyłączone.'});await flush();
  assert.match(h.control('status').textContent,/wyłączona w konfiguracji/);assert.doesNotMatch(h.control('status').textContent,/DANE NIEAKTUALNE/);
  assert.equal(h.control('enabled').disabled,true);assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);
  h.ui.sync({health:{mode:'live'}});assert.equal(h.requests.length,1);
});

test('subminute delay is not rounded into false zero-minute punctuality',async()=>{
  const h=harness();await enable(h);h.markers[0].open();h.requests[1].resolve({...board,departures:[{...departure,delay_seconds:20},{...departure,delay_seconds:-20}]});await flush();
  assert.match(text(h.markers[0].content),/\+20 s/);assert.match(text(h.markers[0].content),/-20 s/);assert.doesNotMatch(text(h.markers[0].content),/[+-]0 min/);
});

const positionItem={id:'IC/1|2026-10-15',trip_id:'IC/1',start_date:'2026-10-15',number:'123',headsign:'Warszawa',operator:'IC',latitude:52.2,longitude:19.2,estimated:true,estimated_at:'2026-10-15T12:00:00Z',source_updated_at:'2026-10-15T12:00:00Z',from_station:'Stacja <test>',to_station:'Druga',valid_until:'2026-10-15T12:00:30Z'};
const positions={...meta,estimated_at:positionItem.estimated_at,valid_until:positionItem.valid_until,items:[positionItem]};
async function enablePositions(h,payload=positions){h.control('positions-enabled').checked=true;h.control('positions-enabled').change();const request=h.requests.at(-1);assert.equal(request.url,'/api/trains/positions');request.resolve(payload);await flush();return h.markers.at(-1);}
function refreshPositions(h){const entry=[...h.timeouts.entries()].find(([,v])=>v.ms===15000);assert.ok(entry);h.timeouts.delete(entry[0]);entry[1].fn();}

test('position marker identifies estimate and opens trip route without selecting a station',async()=>{
  const h=harness();await enable(h);const marker=await enablePositions(h);assert.equal(marker.options.pane,'trainEstimatedPositions');assert.equal(marker.options.icon.html.children[1].textContent,'≈');
  marker.open();assert.match(text(marker.content),/POZYCJA SZACOWANA · nie GPS/);assert.match(text(marker.content),/Stacja <test> → Druga/);assert.match(text(marker.content),/Oszacowanie na 14:00/);assert.match(text(marker.content),/aktualizacja źródła 0 s temu/);
  let stopped=false;buttons(marker.content)[0].click({stopPropagation(){stopped=true;}});assert.equal(stopped,true);assert.equal(h.requests.at(-1).url,'/api/trains/trips/IC%2F1?start_date=2026-10-15');h.requests.at(-1).resolve(trip);await flush();
  assert.equal(h.lines.length,1);assert.match(text(marker.content),/POZYCJA SZACOWANA · nie GPS/);assert.match(text(marker.content),/Przyjazd/);buttons(marker.content)[0].click();assert.match(text(marker.content),/Oszacowanie na/);
  h.advance(12000);[...h.intervals.values()][0].fn();assert.match(text(marker.content),/źródła 12 s temu/);assert.match(h.control('positions-status').textContent,/źródła 12 s temu/);
});

test('position expiry removes markers and route during failed or pending refresh',async()=>{
  const h=harness();await enable(h);const marker=await enablePositions(h);marker.open();buttons(marker.content)[0].click();h.requests.at(-1).resolve(trip);await flush();const routeGroup=h.groups.at(-1);
  refreshPositions(h);const pending=h.requests.at(-1);h.advance(31000);[...h.intervals.values()][0].fn();assert.equal(routeGroup.removed,true);assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);
  pending.resolve(positions);await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);assert.match(h.control('positions-status').textContent,/wstrzymane/);
});

test('stale source, bad estimates, and any refresh failure suppress positions immediately',async()=>{
  const h=harness();await enable(h);await enablePositions(h);h.markers[0].open();h.requests.at(-1).reject(new Error('offline'));await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);assert.match(h.control('positions-status').textContent,/błąd odczytu odjazdów/);
  refreshPositions(h);h.requests.at(-1).resolve(positions);await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 1/);
  refreshPositions(h);h.requests.at(-1).reject(new Error('offline'));await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);
  refreshPositions(h);h.requests.at(-1).resolve({...positions,stale:true});await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);
  refreshPositions(h);h.requests.at(-1).resolve({...positions,items:[{...positionItem,estimated:false},{...positionItem,id:'old',source_updated_at:'2026-10-15T11:00:00Z'},{...positionItem,id:'expired',valid_until:'2026-10-15T12:00:00Z'}]});await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);
});

test('positions require main layer and cancel late responses across child toggles and hiding',async()=>{
  const h=harness();h.control('positions-enabled').checked=true;h.control('positions-enabled').change();assert.equal(h.requests.length,0);h.control('positions-enabled').checked=false;
  await enable(h);h.control('positions-enabled').checked=true;h.control('positions-enabled').change();const old=h.requests.at(-1);
  h.control('positions-enabled').checked=false;h.control('positions-enabled').change();assert.equal(old.signal.aborted,true);h.control('positions-enabled').checked=true;h.control('positions-enabled').change();const latest=h.requests.at(-1);
  old.resolve(positions);await flush();assert.equal(h.markers.length,2);latest.resolve(positions);await flush();assert.equal([...h.timeouts.values()].filter(v=>v.ms===15000).length,1);
  refreshPositions(h);const hidden=h.requests.at(-1);h.ui.sync({visible:false});assert.equal(hidden.signal.aborted,true);hidden.resolve(positions);await flush();assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);assert.equal(h.groups.every(group=>group.removed),true);
});

test('known source failure invalidates older in-flight positions and permits a fresh retry',async()=>{
  const h=harness();await enable(h);await enablePositions(h);refreshPositions(h);const older=h.requests.at(-1);
  h.markers[0].open();h.requests.at(-1).resolve({...board,stale:true});await flush();assert.equal(older.signal.aborted,true);assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);
  older.resolve(positions);await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);assert.equal([...h.timeouts.values()].filter(v=>v.ms===15000).length,1);
  refreshPositions(h);h.requests.at(-1).resolve(positions);await flush();assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 1/);
});

test('new cancelled, diverted or missing-route trip details remove selected estimate immediately',async()=>{
  for(const change of [{cancelled:true},{detour:true},{geometry:null}]){
    const h=harness();await enable(h);const marker=await enablePositions(h);marker.open();buttons(marker.content)[0].click();h.requests.at(-1).resolve({...trip,trip:{...trip.trip,...change}});await flush();
    assert.match(h.control('positions-status').textContent,/Pozycje szacowane: 0/);assert.equal(h.lines.length,0);
  }
});

function activePositionIds(h){
  return h.groups.filter(group=>!group.removed).flatMap(group=>group.items)
    .filter(marker=>marker.options?.pane==='trainEstimatedPositions').map(marker=>marker.trainPosition.id).sort();
}

test('station boards remove only the cancelled or diverted course and service date',async()=>{
  for(const change of [{cancelled:true,trip_cancelled:true},{detour:true}]){
    const h=harness();await enable(h);
    const other={...positionItem,id:'IC/2|2026-10-15',trip_id:'IC/2'};
    const otherDay={...positionItem,id:'IC/1|2026-10-14',start_date:'2026-10-14'};
    await enablePositions(h,{...positions,items:[positionItem,other,otherDay]});
    h.markers[0].open();h.requests.at(-1).resolve({...board,departures:[{...departure,...change}]});await flush();
    assert.deepEqual(activePositionIds(h),[otherDay.id,other.id].sort());
    assert.match(text(h.markers[0].content),/Odjazdy/);
  }
});

test('a skipped station departure does not reject the entire train position',async()=>{
  const h=harness();await enable(h);await enablePositions(h);
  h.markers[0].open();h.requests.at(-1).resolve({...board,departures:[{...departure,cancelled:true,trip_cancelled:false}]});await flush();
  assert.deepEqual(activePositionIds(h),[positionItem.id]);
  assert.match(text(h.markers[0].content),/ODWOŁANY/);
});

test('trip details opened from a station reject the matching estimate without closing station details',async()=>{
  for(const change of [{cancelled:true},{detour:true},{geometry:null}]){
    const h=harness();await enable(h);await enablePositions(h);
    h.markers[0].open();h.requests.at(-1).resolve(board);await flush();
    buttons(h.markers[0].content)[0].click();h.requests.at(-1).resolve({...trip,trip:{...trip.trip,...change}});await flush();
    assert.deepEqual(activePositionIds(h),[]);
    assert.match(text(h.markers[0].content),/Odjazdy ze stacji/);
    if(change.cancelled)assert.match(text(h.markers[0].content),/ODWOŁANY/);
  }
});

test('course rejection invalidates a pending positions response from either popup entry point',async()=>{
  for(const fromStation of [false,true])for(const change of [{cancelled:true},{detour:true},{geometry:null}]){
    const h=harness();await enable(h);const marker=await enablePositions(h);
    if(fromStation){h.markers[0].open();h.requests.at(-1).resolve(board);await flush();}else marker.open();
    refreshPositions(h);const older=h.requests.at(-1);
    buttons(fromStation?h.markers[0].content:marker.content)[0].click();
    h.requests.at(-1).resolve({...trip,trip:{...trip.trip,...change}});await flush();
    assert.equal(older.signal.aborted,true);
    assert.deepEqual(activePositionIds(h),[]);
    older.resolve(positions);await flush();
    assert.deepEqual(activePositionIds(h),[]);
    assert.equal([...h.timeouts.values()].filter(v=>v.ms===15000).length,1);
  }
});

test('a rejected estimate stays blocked for old source data and can recover with newer source data',async()=>{
  const h=harness();await enable(h);const marker=await enablePositions(h);
  marker.open();buttons(marker.content)[0].click();h.requests.at(-1).resolve({...trip,trip:{...trip.trip,cancelled:true}});await flush();
  refreshPositions(h);h.requests.at(-1).resolve(positions);await flush();assert.deepEqual(activePositionIds(h),[]);
  refreshPositions(h);h.requests.at(-1).resolve({...positions,source_updated_at:'2026-10-15T11:59:59Z',items:[{...positionItem,source_updated_at:'2026-10-15T11:59:59Z'}]});await flush();assert.deepEqual(activePositionIds(h),[]);
  h.advance(1000);
  refreshPositions(h);h.requests.at(-1).resolve({...positions,source_updated_at:'2026-10-15T12:00:01Z',items:[{...positionItem,source_updated_at:'2026-10-15T12:00:01Z'}]});await flush();assert.deepEqual(activePositionIds(h),[positionItem.id]);
});
