'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const square=(x,y,size=2)=>[[x,y],[x+size,y],[x+size,y+size],[x,y+size],[x,y]];
const provinces={features:[{properties:{admin_code:'02',name:'dolnośląskie'},geometry:{type:'Polygon',coordinates:[square(15,50),square(15.5,50.5,.2)]}},{properties:{admin_code:'14',name:'mazowieckie'},geometry:{type:'MultiPolygon',coordinates:[[square(20,52)],[square(23,53,.2)]]}}]};
function harness(saved='',blocked=false){
 const elements=new Map(),events={},frames=[],requests=[],storage=new Map([['wici.region.v1',saved]]);
 const element=()=>({children:[],style:{},dataset:{},textContent:'',checked:false,hidden:false,value:'',append(...els){this.children.push(...els);},setAttribute(){},addEventListener(k,fn){this[k]=fn;}});
 const document={hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element,addEventListener(k,fn){(events[k]??=[]).push(fn);},dispatchEvent(e){events[e.type]?.forEach(fn=>fn(e));}};
 const panes={mapPane:element(),tilePane:element(),popupPane:element(),osmBase:element(),data:element()};
 const map={events:{},fits:[],createPane(name){return panes[name]=element();},getPanes:()=>panes,latLngToLayerPoint:([lat,lon])=>({x:lon*10,y:lat*10}),on(names,fn){for(const n of names.split(' '))this.events[n]=fn;},fitBounds(b){this.fits.push(b);},closePopup(){this.closed=true;}};
 const L={geoJSON(f){const points=f?.geometry?.coordinates.flat(Infinity)||[14,49,24,55],xs=points.filter((_,i)=>i%2===0),ys=points.filter((_,i)=>i%2===1);return {getBounds:()=>({getWest:()=>Math.min(...xs),getSouth:()=>Math.min(...ys),getEast:()=>Math.max(...xs),getNorth:()=>Math.max(...ys),isValid:()=>true}),addTo(){return this;},remove(){}};}};
 const window={};vm.runInNewContext(fs.readFileSync('src/wici/static/js/region.js','utf8'),{window,document,L,Event,localStorage:{getItem(k){if(blocked)throw Error();return storage.get(k);},setItem(k,v){if(blocked)throw Error();storage.set(k,v);}},requestAnimationFrame(fn){frames.push(fn);return frames.length;},fetch:(url)=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))});
 window.WiciRegion.init({map,provinces,select:document.getElementById('province'),country:{}});
 return {ui:window.WiciRegion,document,map,panes,storage,frames,requests,control:id=>document.getElementById(id)};
}
const box=(w,s,e,n)=>({getWest:()=>w,getSouth:()=>s,getEast:()=>e,getNorth:()=>n});
test('saved scope, holes, boundary, multipolygon, country and blocked storage',()=>{
 const h=harness('02');assert.equal(h.ui.code(),'02');assert.ok(h.ui.contains(51,16));assert.ok(h.ui.contains(50,15));assert.ok(!h.ui.contains(50.6,15.6));assert.ok(!h.ui.contains(null,null));
 assert.ok(h.ui.matchesProvince('woj. dolnośląskie'));assert.ok(h.ui.matchesProvince('województwo dolnośląskie'));
 h.ui.select('14');assert.ok(h.ui.contains(53.1,23.1));assert.ok(!h.ui.contains(51,16));assert.equal(h.storage.get('wici.region.v1'),'14');assert.ok(h.map.closed);
 h.ui.select('');assert.ok(h.ui.contains(null,null));assert.equal(h.ui.bounds(),null);assert.equal(h.panes.data.style.clipPath,'');
 assert.equal(harness('corrupt').ui.code(),'');assert.equal(harness('02',true).ui.code(),'');
});
test('pane clipping preserves base map and popups and batches newly added layers',()=>{
 const h=harness('02');assert.match(h.panes.data.style.clipPath,/path\(evenodd/);assert.equal(h.panes.osmBase.style.clipPath,undefined);assert.equal(h.panes.popupPane.style.clipPath,undefined);
 h.panes.newData={style:{}};for(let i=0;i<100;i++)h.map.events.layeradd();assert.equal(h.frames.length,1);h.frames.shift()();assert.match(h.panes.newData.style.clipPath,/path/);
});
test('viewport intersection remains small, skips outside and touching views, country keeps viewport',()=>{
 const h=harness('02');assert.deepEqual([...h.ui.viewBox(box(16,51,16.2,51.2))],[16,51,16.2,51.2]);assert.deepEqual([...h.ui.viewBox(box(14,49,16,51))],[15,50,16,51]);
 assert.equal(h.ui.viewBox(box(18,50,19,51)),null);assert.equal(h.ui.viewBox(box(17,50,18,51)),null);
 h.ui.select('');assert.deepEqual([...h.ui.viewBox(box(14,49,24,55))],[14,49,24,55]);
});
function progressHarness(){const h=harness('02');h.ui.initProgress({'gios-enabled':'GIOŚ','hydro-stations':'Hydro','buses-enabled':'Autobusy'});for(const id of ['gios-enabled','hydro-stations','buses-enabled'])h.control(id).checked=true;return h;}
const row=(h,id)=>h.control('layer-progress').children.find(el=>el.dataset.layer===id);
test('independent layer progress, counters, failures and checkbox state',()=>{
 const h=progressHarness(),end=h.ui.begin('/api/buses');h.ui.progress('gios-enabled',{done:1,total:4,pending:true});h.ui.begin('/hydro?kind=stations')('ready');end('error');
 assert.equal(row(h,'gios-enabled').dataset.state,'Wczytywanie');assert.equal(row(h,'hydro-stations').dataset.state,'Odczyt zakończony');assert.equal(row(h,'buses-enabled').dataset.state,'Błąd odczytu');assert.equal(row(h,'gios-enabled').children[2].value,1);
 h.ui.progress('gios-enabled',{done:4,total:4,pending:false});assert.match(h.control('layer-progress-summary').textContent,/0 wczytywanych/);
 h.control('gios-enabled').checked=false;h.control('gios-enabled').change();assert.ok(row(h,'gios-enabled').hidden);
});
for(const stale of ['error','partial','ready'])test(`scope generation rejects late ${stale} even after A→B→A`,()=>{
 const h=progressHarness(),old=h.ui.begin('/gios');h.ui.select('14');h.ui.select('02');h.ui.begin('/gios')(stale==='ready'?'error':'ready');old(stale);old('error');assert.equal(row(h,'gios-enabled').dataset.state,stale==='ready'?'Błąd odczytu':'Odczyt zakończony');
});
test('native fetch progress waits for JSON and releases network, HTTP and JSON failures',async()=>{
 const h=progressHarness();let pending=h.ui.fetch('/api/gios');h.requests[0].resolve({ok:true,json:async()=>({status:'ready'})});const response=await pending;assert.equal(row(h,'gios-enabled').dataset.state,'Wczytywanie');await response.json();assert.equal(row(h,'gios-enabled').dataset.state,'Odczyt zakończony');
 pending=h.ui.fetch('/api/gios');h.requests[1].reject(Error('offline'));await assert.rejects(pending);assert.equal(row(h,'gios-enabled').dataset.state,'Błąd odczytu');
 pending=h.ui.fetch('/api/gios');h.requests[2].resolve({ok:false,json:async()=>({})});await pending;assert.equal(row(h,'gios-enabled').dataset.state,'Błąd odczytu');
 pending=h.ui.fetch('/api/gios');h.requests[3].resolve({ok:true,json:async()=>{throw Error('json');}});await assert.rejects((await pending).json());assert.equal(row(h,'gios-enabled').dataset.state,'Błąd odczytu');
});
