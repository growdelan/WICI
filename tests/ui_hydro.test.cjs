const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function harness(){
 const controls=new Map(),requests=[],markers=[],timeouts=new Map(),intervals=new Map();let id=0,now=Date.parse('2026-10-17T06:00:00Z');
 const element=tag=>({tag,checked:false,disabled:false,value:'',textContent:'',hidden:false,children:[],classList:{toggle(){}},addEventListener(k,f){this[k]=f;},append(...e){this.children.push(...e);},replaceChildren(){this.children=[];this.value='';}});
 const document={hidden:false,createElement:element,getElementById(id){if(!controls.has(id))controls.set(id,element('div'));return controls.get(id);}};
 const map={layers:new Set(),panes:{},createPane(name){return this.panes[name]={style:{}};},removeLayer(l){this.layers.delete(l);l.markers?.forEach(m=>m.open=false);},setView(coords,zoom){this.coords=coords;this.zoom=zoom;}};
 const L={layerGroup(){return {markers:new Set(),removeLayer(m){this.markers.delete(m);m.open=false;},addTo(m){m.layers.add(this);return this;}};},circleMarker(coords,options){const marker={coords,options,bindTooltip(){return this;},bindPopup(content){this.content=content;return this;},addTo(group){group.markers.add(this);return this;},setLatLng(coords){this.coords=coords;return this;},setStyle(style){Object.assign(this.options,style);return this;},setTooltipContent(){return this;},isPopupOpen(){return !!this.open;},getPopup(){return {update:()=>{this.popupContent=this.content();}};}};markers.push(marker);return marker;}};
 class Clock extends Date {static now(){return now;}}
 const window={};vm.runInNewContext(fs.readFileSync('src/wici/static/js/hydro.js','utf8'),{window,document,L,Intl,Date:Clock,setTimeout(f){timeouts.set(++id,f);return id;},clearTimeout(i){timeouts.delete(i);},setInterval(f){intervals.set(++id,f);return id;},clearInterval(i){intervals.delete(i);}});
 window.WiciHydro.init({map,api:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))});
 const control=n=>document.getElementById('hydro-'+n);
 return {ui:window.WiciHydro,document,map,control,requests,markers,timeouts,intervals,advance(ms){now+=ms;},refresh(){const [i,f]=[...timeouts][0];timeouts.delete(i);f();}};
}
const measure=(value,time='2026-10-17T05:20:00Z')=>({value,observed_at:time,unit:'cm'});
const station={id:'151',name:'Stacja <img onerror=test>',river:'Wisła',province:'pomorskie',latitude:54,longitude:18,warning_level_cm:300,alarm_level_cm:340,measurements:{water_level:measure(340),discharge:measure(1,'2025-01-01T00:00:00Z'),temperature:measure(null,null)}};
const base={enabled:true,fetched_at:'2026-10-17T06:00:00Z',source_url:'https://danepubliczne.imgw.pl/api/data/hydro/',message:'',stale:false};
const stationData={...base,items:[station]};
const warning={id:'w1',event:'Susza hydrologiczna',number:'21',office:'Biuro IMGW',severity:null,severity_code:'-1',valid_from:'2026-04-17T06:00:00Z',valid_until:null,published_at:'2026-04-17T05:59:00Z',open_ended:true,description:'Pełna treść ostrzeżenia <script>',comment:'Uwagi',probability_percent:90,areas:[{province:'pomorskie',description:'Zlewnia Wdy',basin_codes:['Z_G_PM']} ]};
const warningData={...base,items:[warning]};
const flush=()=>new Promise(r=>setImmediate(r));
const text=e=>[e.textContent,...e.children.map(text)].join(' ');
async function enable(h,kind,data){h.control(kind).checked=true;h.control(kind).change();h.requests.at(-1).resolve(data);await flush();}

test('on demand independent feeds, threshold markers and full measurement popup',async()=>{
 const h=harness();assert.equal(h.requests.length,0);await enable(h,'stations',stationData);
 assert.equal(h.requests[0].url,'/hydro?kind=stations');assert.equal(h.markers.length,1);assert.equal(h.markers[0].options.color,'#c32b35');
 const popup=h.markers[0].content();assert.match(text(popup),/Stacja <img onerror=test>/);assert.match(text(popup),/NIEAKTUALNY POMIAR/);assert.match(text(popup),/Brak danych/);
 h.control('station').value='151';h.control('station').change();assert.equal(h.map.zoom,10);assert.match(text(h.control('station-detail')),/340 cm/);
 await enable(h,'warnings',warningData);assert.equal(h.requests.length,2);assert.match(text(h.control('warning-list')),/Bez określonego końca/);assert.match(text(h.control('warning-list')),/Pełna treść ostrzeżenia <script>/);assert.match(text(h.control('warning-list')),/bez stopnia/);
 h.control('warning-list').children[1].open=true;[...h.intervals.values()][0]();assert.equal(h.control('warning-list').children[1].open,true);
 h.control('filter').value='nieistniejący obszar';h.control('filter').input();assert.match(text(h.control('warning-list')),/0 ostrzeżeń/);
 h.control('filter').value='Wdy';h.control('filter').input();assert.match(text(h.control('warning-list')),/Z_G_PM/);
});
test('clock aging and failed refresh keep old station with gray marker and honest status',async()=>{
 const h=harness();await enable(h,'stations',stationData);h.advance(4*3600000);[...h.intervals.values()][0]();
 assert.equal(h.markers.at(-1).options.color,'#6b7780');assert.match(h.control('stations-status').textContent,/NIEAKTUALNY ODCZYT/);
 h.refresh();h.requests.at(-1).reject(new Error('offline'));await flush();assert.equal(h.map.layers.size,1);assert.match(text(h.markers.at(-1).content()),/aktualność niepotwierdzona/);
});
test('hide and disable remove layers and timers and reject late responses',async()=>{
 const h=harness();await enable(h,'stations',stationData);h.control('warnings').checked=true;h.control('warnings').change();const late=h.requests.at(-1);
 h.ui.sync({visible:false});assert.equal(h.map.layers.size,0);assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);
 late.resolve(warningData);await flush();assert.equal(h.control('warning-list').children.length,0);assert.equal(h.timeouts.size,0);
 h.ui.sync({visible:true});assert.equal(h.requests.length,4);h.control('stations').checked=false;h.control('stations').change();h.requests[2].resolve(stationData);h.requests[3].resolve(warningData);await flush();assert.equal(h.map.layers.size,0);
});
test('disabled/demo stops refresh, empty lists stay explicit',async()=>{
 const h=harness();await enable(h,'warnings',{...base,enabled:false,items:[],message:'Hydrologia wyłączona w demonstracji.'});assert.equal(h.timeouts.size,0);assert.match(h.control('warnings-status').textContent,/demonstracji/);h.ui.sync({visible:true});assert.equal(h.requests.length,1);
 const b=harness();await enable(b,'stations',{...base,items:[],message:'Źródło zwróciło pusty wykaz stacji.'});assert.match(b.control('stations-status').textContent,/pusty wykaz/);
});

test('health synchronizations preserve the running freshness timer and marker identity',async()=>{
 const h=harness();await enable(h,'stations',stationData);
 const timer=[...h.intervals.keys()][0],marker=h.markers[0];
 for(let i=0;i<4;i++){h.advance(60000);h.ui.sync({visible:true});}
 assert.equal(h.intervals.size,1);assert.equal([...h.intervals.keys()][0],timer);
 assert.equal(h.markers.length,1);assert.equal(h.markers[0],marker);
 assert.equal(marker.options.pane,'hydroStations');assert.equal(h.map.panes.hydroStations.style.zIndex,'475');
});
test('refresh updates an open popup in place; stale errors retain it and removal closes it',async()=>{
 const h=harness();await enable(h,'stations',stationData);const marker=h.markers[0];marker.open=true;
 h.advance(4*3600000);[...h.intervals.values()][0]();
 assert.equal(marker.open,true);assert.match(text(marker.popupContent),/NIEAKTUALNY POMIAR/);
 h.refresh();h.requests.at(-1).resolve({...base,items:[{...station,measurements:{...station.measurements,water_level:measure(410)}}]});await flush();
 assert.equal(h.markers.length,1);assert.equal(marker.open,true);assert.match(text(marker.popupContent),/410 cm/);
 h.refresh();h.requests.at(-1).reject(new Error('offline'));await flush();
 assert.equal(marker.open,true);assert.match(text(marker.popupContent),/aktualność niepotwierdzona/);
 h.refresh();h.requests.at(-1).resolve({...base,items:[]});await flush();assert.equal(marker.open,false);
});
test('turning the station layer off closes its popup and removes freshness timers',async()=>{
 const h=harness();await enable(h,'stations',stationData);const marker=h.markers[0];marker.open=true;
 h.control('stations').checked=false;h.control('stations').change();
 assert.equal(marker.open,false);assert.equal(h.map.layers.size,0);assert.equal(h.intervals.size,0);assert.equal(h.timeouts.size,0);
});
