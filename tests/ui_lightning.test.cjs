const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function harness(){
 const controls=new Map(),requests=[],layers=[],timers=new Map();let id=0;
 const element=()=>({checked:false,disabled:false,value:'',textContent:'',hidden:false,children:[],classList:{toggle(){}},addEventListener(k,f){this[k]=f;},append(...e){this.children.push(...e);},replaceChildren(){this.children=[];this.value='';}});
 const document={hidden:false,createElement:element,getElementById(id){if(!controls.has(id))controls.set(id,element());return controls.get(id);}};
 const map={layers:new Set(),createPane(){return {style:{}};},removeLayer(l){this.layers.delete(l);},closePopup(p){p.remove?.();}};
 const L={imageOverlay(url,options){const l={url,options,on(k,f){this[k]=f;return this;},addTo(m){m.layers.add(this);return this;},setOpacity(v){this.opacity=v;}};layers.push(l);return l;},popup(){return {setLatLng(){return this;},setContent(c){this.content=c;return this;},openOn(){return this;},on(k,f){this[k]=f;return this;}};}};
 const window={};vm.runInNewContext(fs.readFileSync('src/wici/static/js/lightning.js','utf8'),{window,document,L,Intl,Date,queueMicrotask,setTimeout(f){timers.set(++id,f);return id;},clearTimeout(i){timers.delete(i);}});
 const control=n=>document.getElementById('lightning-'+n);
 window.WiciLightning.init({map,api:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))});
 return {window,document,map,control,requests,layers,timers};
}
const data=()=>({enabled:true,frames:[0,1].map(i=>({timestamp:100+i,time:`2026-10-14T14:${i}0:00Z`,end:`2026-10-14T14:${i}5:00Z`,image_url:`/api/lightning/map?time=${100+i}`})),bounds:[[49,14],[55,24.2]],delay_minutes:30,stale:true,message:'Dane opóźnione',legend_url:'/api/lightning/legend',source_url:'https://view.eumetsat.int/'});
const flush=()=>new Promise(r=>setImmediate(r));
async function enabled(h){h.control('enabled').checked=true;h.control('enabled').change();h.requests[0].resolve(data());await flush();h.layers[0].load();await flush();}
test('off by default, loaded image and official legend with honest delay',async()=>{
 const h=harness();assert.equal(h.requests.length,0);await enabled(h);
 assert.equal(h.layers[0].opacity,1);assert.match(h.layers[0].url,/time=101/);
 assert.match(h.control('status').textContent,/30 min/);h.control('legend-image').load();assert.equal(h.control('legend').hidden,false);
});
test('period selection waits for readiness and failed image retains previous selection',async()=>{
 const h=harness();await enabled(h);h.control('time').value='100';h.control('time').change();
 assert.equal(h.map.layers.size,2);h.layers[1].error();await flush();assert.equal(h.map.layers.size,1);assert.equal(h.control('time').value,'101');
 assert.match(h.control('status').textContent,/Zachowano/);
});
test('refresh keeps manually selected period and displayed selector matches image',async()=>{
 const h=harness();await enabled(h);h.control('time').value='100';h.control('time').change();h.layers[1].load();await flush();
 [...h.timers.values()][0]();h.requests[1].resolve(data());await flush();assert.equal(h.control('time').value,'100');assert.equal(h.layers.length,2);
});
test('unchecked layer cancels late metadata, images and click responses',async()=>{
 const h=harness();await enabled(h);h.layers[0].click({latlng:{lat:52,lng:19}});assert.match(h.requests[1].url,/point\?time=101/);
 h.control('time').value='100';h.control('time').change();h.control('enabled').checked=false;h.control('enabled').change();
 h.layers[1].load();h.requests[1].resolve({visible_activity:true});await flush();assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);
 const b=harness();b.control('enabled').checked=true;b.control('enabled').change();b.window.WiciLightning.sync({visible:false});b.requests[0].resolve(data());await flush();assert.equal(b.layers.length,0);
});
test('demo does not create a layer',async()=>{
 const h=harness();h.control('enabled').checked=true;h.control('enabled').change();h.requests[0].resolve({enabled:false,frames:[],message:'EUMETSAT wyłączony w demonstracji'});await flush();assert.equal(h.layers.length,0);assert.match(h.control('status').textContent,/demonstracji/);
});
