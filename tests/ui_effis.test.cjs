const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function harness(){
 const elements=new Map();
 function element(){return {textContent:'',value:'',checked:false,children:[],classList:{remove(){},toggle(){}},append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;},addEventListener(){},setAttribute(){}};}
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element,querySelectorAll(){return [];},querySelector:element,addEventListener(){}};
 document.getElementById('effis-enabled').checked=true;
 document.getElementById('effis-day').value='0';
 document.getElementById('effis-day').options=[0,1,2].map(value=>({value:String(value)}));
 document.getElementById('selected-day').value='2020-01-01';
 const map={layers:new Set(),removeLayer(l){this.layers.delete(l);},hasLayer(l){return this.layers.has(l);}};
 const images=[],requests=[];
 const L={imageOverlay(url,bounds,options){const image={url,bounds,options,handlers:{},on(event,fn){this.handlers[event]=fn;return this;},addTo(m){m.layers.add(this);return this;}};images.push(image);return image;}};
 const ctx=vm.createContext({document,window:{L},L,URL,URLSearchParams,Intl,console,fetchJSON(url){return new Promise((resolve,reject)=>requests.push({url,resolve,reject}));}});
 const source=fs.readFileSync(path.join(__dirname,'../src/wici/static/js/app.js'),'utf8').replace('reload();setInterval(reload,60000);','');
 vm.runInContext(source,ctx);ctx.testMap=map;vm.runInContext("state.map=testMap;state.health={now:'2026-10-13T10:00:00Z',mode:'live'};",ctx);
 return {ctx,document,map,images,requests};
}
function respond(request,day='2026-10-13',extra={}){request.resolve({response:{ok:true},data:{available:true,forecast_date:day,fetched_at:'2026-10-13T10:00:00Z',model:'ECMWF',image_url:`/api/effis/map?day=${day}`,legend_url:'/api/effis/legend',...extra}});}
function loaded(h,index=h.images.length-1){h.images[index].handlers.load();h.document.getElementById('effis-legend-image').children[0].onload();}
test('forecast day uses Warsaw server day independently of publication filters and moves at midnight',async()=>{
 const h=harness();vm.runInContext('updateEffisDays()',h.ctx);
 assert.match(h.document.getElementById('effis-day').options[0].textContent,/2026-10-13/);
 h.document.getElementById('effis-day').value='2';
 const pending=vm.runInContext('loadEffis()',h.ctx);assert.equal(h.requests[0].url,'/api/effis?day=2026-10-15');respond(h.requests[0],'2026-10-15');await pending;
 const health=vm.runInContext('loadHealth()',h.ctx);
 h.requests[1].resolve({response:{ok:true},data:{now:'2026-10-13T22:05:00Z',mode:'live'}});await health;
 assert.match(h.document.getElementById('effis-day').options[0].textContent,/2026-10-14/);
 assert.equal(vm.runInContext('effisForecastDay()',h.ctx),'2026-10-16');
});
test('map reports ready only after map and legend load; toggle removes overlay',async()=>{
 const h=harness();const pending=vm.runInContext('loadEffis()',h.ctx);respond(h.requests[0]);await pending;
 assert.equal(h.images[0].options.pane,'effisForecast');assert.equal(h.map.layers.size,1);
 assert.match(h.document.getElementById('effis-status').textContent,/Wczytywanie/);
 h.images[0].handlers.load();assert.equal(h.document.getElementById('effis-legend').hidden,true);
 h.document.getElementById('effis-legend-image').children[0].onload();
 assert.match(h.document.getElementById('effis-status').textContent,/Prognoza na 2026-10-13.*pobrano.*ECMWF/);
 assert.equal(h.document.getElementById('effis-legend').hidden,false);
 h.document.getElementById('effis-enabled').checked=false;await vm.runInContext('loadEffis()',h.ctx);
 assert.equal(h.map.layers.size,0);assert.equal(h.document.getElementById('effis-legend').hidden,true);
});
test('date change discards late metadata and stale image events; failure clears previous forecast',async()=>{
 const h=harness();const first=vm.runInContext('loadEffis()',h.ctx);
 h.document.getElementById('effis-day').value='1';const second=vm.runInContext('loadEffis()',h.ctx);
 respond(h.requests[1],'2026-10-14');await second;respond(h.requests[0]);await first;
 assert.equal(h.images.length,1);loaded(h);
 const old=h.images[0];h.document.getElementById('effis-day').value='2';const third=vm.runInContext('loadEffis()',h.ctx);
 respond(h.requests[2],'2026-10-15');await third;
 old.handlers.error();assert.equal(h.map.layers.size,1);assert.match(h.document.getElementById('effis-status').textContent,/Wczytywanie.*2026-10-15/);
 h.images[1].handlers.error();assert.equal(h.map.layers.size,0);assert.match(h.document.getElementById('effis-status').textContent,/2026-10-15 niedostępna/);
});
test('disabled in-flight response and demo cannot show real forecasts; no fallback to wrong date',async()=>{
 const h=harness();const first=vm.runInContext('loadEffis()',h.ctx);h.document.getElementById('effis-enabled').checked=false;await vm.runInContext('loadEffis()',h.ctx);respond(h.requests[0]);await first;assert.equal(h.images.length,0);
 h.document.getElementById('effis-enabled').checked=true;const second=vm.runInContext('loadEffis()',h.ctx);respond(h.requests[1],'2026-10-12');await second;assert.equal(h.map.layers.size,0);assert.match(h.document.getElementById('effis-status').textContent,/inny dzień/);
 vm.runInContext("state.health.mode='demo'",h.ctx);await vm.runInContext('loadEffis()',h.ctx);assert.equal(h.requests.length,2);assert.match(h.document.getElementById('effis-status').textContent,/demonstracji/);
});
