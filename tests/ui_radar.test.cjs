const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function harness(){
 const controls=new Map(),requests=[],layers=[],intervals=new Map(),timeouts=new Map();let id=0;
 const element=()=>({checked:false,disabled:false,value:0,textContent:'',hidden:false,classList:{toggle(){}},setAttribute(k,v){this[k]=v;},addEventListener(k,v){this[k]=v;}});
 const document={hidden:false,getElementById(id){if(!controls.has(id))controls.set(id,element());return controls.get(id);}};
 const map={layers:new Set(),handlers:{},panes:{},createPane(n){return this.panes[n]={style:{}};},getPane(n){return this.panes[n];},removeLayer(l){this.layers.delete(l);},getBounds(){return {intersects(){return true;}};},on(n,f){this.handlers[n]=f;}};
 const L={latLngBounds(x){return x;},tileLayer(url,options){const layer={url,options,handlers:{},on(n,f){this.handlers[n]=f;return this;},addTo(map){map.layers.add(this);return this;},setOpacity(v){this.opacity=v;},complete(ok=true){const attached=map.layers.has(this);this.handlers[ok?'tileload':'tileerror']();this.handlers.load();if(attached)assert.equal(map.layers.has(this),true,'Leaflet must finish load before layer removal');return Promise.resolve();}};layers.push(layer);return layer;}};
 const window={};const context=vm.createContext({window,document,L,Intl,Date,queueMicrotask,setTimeout(f,ms){timeouts.set(++id,{f,ms});return id;},clearTimeout(i){timeouts.delete(i);},setInterval(f,ms){intervals.set(++id,{f,ms});return id;},clearInterval(i){intervals.delete(i);}});
 vm.runInContext(fs.readFileSync('src/wici/static/js/radar.js','utf8'),context);
 const control=n=>document.getElementById('radar-'+n);control('opacity').value=65;
 const hour=control('hour');let rangeValue=0,rangeMax=0;
 Object.defineProperties(hour,{max:{get(){return rangeMax;},set(v){rangeMax=Number(v);rangeValue=Math.min(rangeValue,rangeMax);}},value:{get(){return rangeValue;},set(v){rangeValue=Math.max(0,Math.min(Number(v),rangeMax));}}});
 window.WiciRadar.init({map,api:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))});
 return {window,document,map,control,requests,layers,intervals,timeouts};
}
const frames=()=>({enabled:true,status:'success',stale:false,bounds:[[49,14],[55,24.2]],max_native_zoom:6,frames:[0,1,2].map(i=>({timestamp:100+i,time:`2026-10-14T14:${i}0:00Z`,tile_url:`/api/radar/tiles/${100+i}/{z}/{x}/{y}.png`}))});
const flush=()=>new Promise(r=>setImmediate(r));
async function enabled(h){h.control('enabled').checked=true;h.control('enabled').change();h.requests[0].resolve(frames());await flush();await h.layers[0].complete();}
test('radar off by default, local bounded tiles, start waits for loaded frame then plays',async()=>{
 const h=harness();assert.equal(h.requests.length,0);h.control('play').click();assert.equal(h.control('enabled').checked,true);
 h.requests[0].resolve(frames());await flush();assert.equal(h.intervals.size,0);
 await h.layers[0].complete();assert.equal(h.intervals.size,1);assert.equal(h.layers[0].options.maxNativeZoom,6);
 assert.match(h.layers[0].url,/^\/api\/radar\/tiles\/102/);assert.equal(h.layers[0].opacity,.65);
 [...h.intervals.values()][0].f();assert.equal(h.requests.length,1);assert.equal(h.map.layers.size,2);
 await h.layers[1].complete();assert.equal(h.map.layers.size,1);h.control('play').click();assert.equal(h.intervals.size,0);
});
test('failed next frame keeps previous complete image and stops animation',async()=>{
 const h=harness();await enabled(h);const previous=h.layers[0];h.control('play').click();
 [...h.intervals.values()][0].f();await h.layers[1].complete(false);
 assert.equal(h.map.layers.has(previous),true);assert.equal(h.map.layers.size,1);assert.equal(h.intervals.size,0);
 assert.match(h.control('status').textContent,/nie udało/);
});
test('hidden or unchecked map cancels pending playback and late images cannot reappear',async()=>{
 const h=harness();h.control('play').click();h.document.hidden=true;h.window.WiciRadar.sync({visible:false});
 h.requests[0].resolve(frames());await flush();assert.equal(h.layers.length,0);assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);
 h.document.hidden=false;h.window.WiciRadar.sync({visible:true});h.requests[1].resolve(frames());await flush();
 const pending=h.layers[0];h.control('enabled').checked=false;h.control('enabled').change();await pending.complete();assert.equal(h.map.layers.size,0);
});
test('demo disabled result and metadata outage report correctly without losing stored image',async()=>{
 const disabled=harness();disabled.control('play').click();disabled.requests[0].resolve({enabled:false,frames:[],message:'Radar wyłączony w demonstracji'});await flush();assert.equal(disabled.layers.length,0);assert.equal(disabled.intervals.size,0);assert.match(disabled.control('status').textContent,/demonstracji/);
 const h=harness();await enabled(h);[...h.timeouts.values()][0].f();h.requests[1].reject(new Error('offline'));await flush();assert.equal(h.map.layers.size,1);assert.match(h.control('status').textContent,/zachowano/);
});
test('opacity and slider use local layers only and do not refetch metadata',async()=>{
 const h=harness();await enabled(h);h.control('opacity').value=40;h.control('opacity').input();assert.equal(h.layers[0].opacity,.4);
 h.control('hour').value=0;h.control('hour').input();await h.layers[1].complete();assert.equal(h.requests.length,1);assert.match(h.control('time').textContent,/16:00/);
});
test('refresh follows latest while keeping a manually selected past frame',async()=>{
 const h=harness();await enabled(h);
 [...h.timeouts.values()][0].f();const updated=frames();updated.frames.push({timestamp:103,time:'2026-10-14T14:30:00Z',tile_url:'/api/radar/tiles/103/{z}/{x}/{y}.png'});
 h.requests[1].resolve(updated);await flush();await h.layers[1].complete();assert.equal(Number(h.control('hour').value),3);
 h.control('hour').value=0;h.control('hour').input();await h.layers[2].complete();
 [...h.timeouts.values()].at(-1).f();h.requests[2].resolve(updated);await flush();await h.layers[3].complete();assert.equal(Number(h.control('hour').value),0);
});
