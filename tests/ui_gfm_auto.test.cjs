'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness({transport=false}={}){
 const controls=new Map(),requests=[],timers=new Map(),events={};let id=0,zoom=6;
 const element=()=>({value:'.65',textContent:'',append(){},addEventListener(name,fn){this[name]=fn;}});
 const document={hidden:false,createElement:element,getElementById(name){if(!controls.has(name))controls.set(name,element());return controls.get(name);}};
 const group={layers:[],clearLayers(){this.layers=[];},eachLayer(fn){this.layers.forEach(fn);},addTo(){return this;}};
 const layer=()=>({addTo(g){g.layers.push(this);return this;},bindPopup(){return this;},bindTooltip(){return this;},setStyle(s){this.style=s;}});
 const L={canvas:()=>({}),layerGroup:()=>group,geoJSON(data){return {...layer(),data};},circleMarker:()=>layer()};
 const map={createPane:()=>({style:{}}),on(name,fn){events[name]=fn;},getZoom:()=>zoom,
  getBounds:()=>({getWest:()=>14,getSouth:()=>49,getEast:()=>24.3,getNorth:()=>55})};
 const window={},runtime={window,document,L,URLSearchParams,Date,AbortController,TypeError,
  fetch:(url,options)=>new Promise((resolve,reject)=>{
   requests.push({url,signal:options.signal,resolve:data=>resolve({json:async()=>data}),reject});
   options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
  }),
  setTimeout(fn,ms){timers.set(++id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);}};
 vm.createContext(runtime);
 vm.runInContext(fs.readFileSync('src/wici/static/js/gfm-auto.js','utf8'),runtime);
 let api=(url,body,options)=>new Promise((resolve,reject)=>requests.push({url,signal:options.signal,resolve,reject}));
 if(transport){
  vm.runInContext(fs.readFileSync('src/wici/static/js/requests.js','utf8'),runtime);
  const fetchJSON=vm.runInContext('fetchJSON',runtime);
  api=async(url,body,options)=>(await fetchJSON(url,options)).data;
 }
 window.WiciGFMAuto.init({map,api});
 return {window,map,ui:window.WiciGFMAuto,document,requests,timers,group,events,control:name=>document.getElementById('gfm-'+name),
  zoom(value){zoom=value;events.zoomend();},tick(){const [id,t]=timers.entries().next().value;timers.delete(id);t.fn();},
  fire(ms){const entry=[...timers].find(([,t])=>t.ms===ms);assert.ok(entry,`Missing ${ms} ms timer`);timers.delete(entry[0]);entry[1].fn();}};
}
const feature={geometry:{coordinates:[16.65,50.44]},properties:{pixels:1,product:{observed_at:'2026-10-17T05:00:00Z'}}};
const result=(revision=1)=>({enabled:true,revision,clusters:[feature],features:[],products:2,processed:1,pixels:1,poll_after_seconds:3,checked_at:new Date().toISOString()});
test('active layer automatically polls Poland, replaces new revisions and clears superseded floods',async()=>{
 const h=harness();assert.equal(h.requests.length,0);h.ui.sync({active:true});assert.equal(h.requests[0].url,'/gfm/monitor');
 h.requests[0].resolve(result());await flush();assert.equal(h.group.layers.length,1);assert.equal(h.timers.size,1);
 assert.match(h.control('status').textContent,/1\/2/);h.tick();h.requests[1].resolve({...result(2),clusters:[],pixels:0,processed:2});await flush();
 assert.equal(h.group.layers.length,0);assert.match(h.control('status').textContent,/nie oznacza pełnego pokrycia/);
});
test('zoom and movement debounce detail requests without the manual half degree restriction',async()=>{
 const h=harness();h.ui.sync({active:true});h.requests[0].resolve(result());await flush();
 h.zoom(12);h.events.moveend();assert.equal(h.timers.size,1);h.tick();assert.match(h.requests[1].url,/bbox=14%2C49%2C24.3%2C55/);
 h.requests[1].resolve({...result(),features:[feature]});await flush();assert.equal(h.group.layers.length,1);assert.ok(h.group.layers[0].data);
});
test('disabled or hidden layers stop timers and ignore late results',async()=>{
 for(const hidden of [false,true]){
  const h=harness();h.ui.sync({active:true});h.document.hidden=hidden;h.ui.sync({active:hidden});
  h.requests[0].resolve(result());await flush();assert.equal(h.group.layers.length,0);assert.equal(h.timers.size,0);
  h.document.hidden=false;h.ui.sync({active:true});assert.equal(h.requests.length,2);
 }
});
test('failure preserves detections, opacity works, and offline demo stops polling',async()=>{
 const h=harness();h.ui.sync({active:true});h.requests[0].resolve(result());await flush();
 h.control('opacity').value='.3';h.control('opacity').input();assert.equal(h.group.layers[0].style.opacity,.3);
 h.tick();h.requests[1].reject(new Error('offline'));await flush();assert.equal(h.group.layers.length,1);assert.match(h.control('status').textContent,/zachowano/);
 h.tick();h.requests[2].resolve({enabled:false,message:'Demo offline'});await flush();assert.equal(h.group.layers.length,0);assert.equal(h.timers.size,0);
});

for(const stage of ['inflight','retry_wait'])test(`disabling cancels real fetchJSON transport at ${stage} and prevents retries`,async()=>{
 const h=harness({transport:true});h.ui.sync({active:true});
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].signal.aborted,false);
 if(stage==='retry_wait'){h.requests[0].reject(new TypeError('connection lost'));await flush();}
 h.ui.sync({active:false});
 assert.equal(h.requests[0].signal.aborted,true);
 if(stage==='retry_wait')h.fire(150);
 await flush();assert.equal(h.requests.length,1);assert.equal(h.timers.size,0);assert.equal(h.group.layers.length,0);
 // A fresh activation must use a fresh signal, not resume the cancelled retry.
 h.ui.sync({active:true});assert.equal(h.requests.length,2);assert.equal(h.requests[1].signal.aborted,false);
 h.requests[1].resolve(result());await flush();assert.equal(h.group.layers.length,1);
 h.ui.sync({active:false});assert.equal(h.timers.size,0);
});

test('real fetchJSON still retries network errors while the layer is active',async()=>{
 const h=harness({transport:true});h.ui.sync({active:true});
 h.requests[0].reject(new TypeError('connection lost'));await flush();h.fire(150);await flush();
 assert.equal(h.requests.length,2);h.requests[1].resolve(result());await flush();
 assert.equal(h.group.layers.length,1);h.ui.sync({active:false});assert.equal(h.timers.size,0);
});

test('cleanup from a cancelled request cannot detach the next request controller',async()=>{
 const h=harness({transport:true});h.ui.sync({active:true});h.ui.sync({active:false});h.ui.sync({active:true});
 await flush();assert.equal(h.requests.length,2);h.ui.sync({active:false});await flush();
 assert.ok(h.requests.every(r=>r.signal.aborted));assert.equal(h.timers.size,0);
});

test('same revision and bbox redraws clusters and polygons when zoom crosses detail threshold',async()=>{
 const h=harness();h.window.WiciRegion={code:()=> '02',viewBox:()=>[16.6,50.4,16.7,50.5]};h.ui.sync({active:true});h.requests[0].resolve({...result(),features:[feature]});await flush();assert.ok(!h.group.layers[0].data);
 h.zoom(12);h.tick();h.requests[1].resolve({...result(),features:[feature]});await flush();assert.ok(h.group.layers[0].data);
 h.zoom(6);h.tick();h.requests[2].resolve({...result(),features:[feature]});await flush();assert.ok(!h.group.layers[0].data);
});
test('regional monitor queries intersection and pauses outside until viewport returns',async()=>{
 const h=harness();let inside=false;h.window.WiciRegion={code:()=> '02',viewBox:()=>inside?[16.6,50.4,16.7,50.5]:null};h.ui.sync({active:true});assert.equal(h.requests.length,0);assert.equal(h.timers.size,0);
 inside=true;h.events.moveend();h.tick();assert.equal(new URLSearchParams(h.requests[0].url.split('?')[1]).get('bbox'),'16.6,50.4,16.7,50.5');h.requests[0].resolve(result());await flush();assert.equal(h.group.layers.length,1);
 inside=false;h.events.moveend();h.tick();assert.equal(h.requests.length,1);assert.equal(h.group.layers.length,0);assert.equal(h.timers.size,0);
});
