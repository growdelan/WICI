const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function harness(){
 const elements=new Map(),listeners={},timers=new Map(),tiles=[],requests=[],popups=[];
 let timerId=0,now=1000;
 function element(){return {textContent:'',checked:false,children:[],classList:{remove(){},toggle(){}},append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;},addEventListener(type,fn){this[type]=fn;}};}
 const tabs=['situation','sources'].map(view=>({...element(),dataset:{view},setAttribute(){},removeAttribute(){}}));
 const document={hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element,querySelectorAll(selector){return selector==='.tab'?tabs:[];},querySelector:element,addEventListener(type,fn){listeners[type]=fn;}};
 const map={layers:new Set(),removeLayer(l){this.layers.delete(l);},hasLayer(l){return this.layers.has(l);},invalidateSize(){},closePopup(popup){popup.handlers.remove?.();}};
 const L={popup(){const popup={handlers:{},setLatLng(point){this.point=point;return this;},setContent(content){this.content=content;return this;},on(type,fn){this.handlers[type]=fn;return this;},openOn(){return this;}};popups.push(popup);return popup;},tileLayer(url,options){const layer={url,options,handlers:{},redraws:0,on(type,fn){this.handlers[type]=fn;return this;},addTo(m){m.layers.add(this);return this;},redraw(){this.redraws++;return this;}};tiles.push(layer);return layer;}};
 class Clock extends Date {static now(){return now;}}
 const ctx=vm.createContext({Date:Clock,document,window:{L},L,URL,URLSearchParams,Intl,console,setInterval(fn,ms){timers.set(++timerId,{fn,ms});return timerId;},clearInterval(id){timers.delete(id);},setTimeout(fn){fn();},fetchJSON(url){return new Promise((resolve,reject)=>requests.push({url,resolve,reject}));}});
 const source=fs.readFileSync(path.join(__dirname,'../src/wici/static/js/app.js'),'utf8').replace('reload();setInterval(reload,60000);','');vm.runInContext(source,ctx);ctx.testMap=map;vm.runInContext("state.map=testMap;state.health={mode:'live',now:'2026-10-13T10:00:00Z'};",ctx);
 return {ctx,document,map,tiles,requests,timers,tabs,listeners,popups,advance(ms){now+=ms;}};
}
const run=(h,expr='syncTraffic()')=>vm.runInContext(expr,h.ctx);
const enabled=h=>{h.document.getElementById('traffic-enabled').checked=true;};
function respond(h,index=0,extra={}){h.requests[index].resolve({response:{ok:true},data:{enabled:true,status:'ready',month:'2026-10',requests_used:3,monthly_limit:190000,tile_url:'/api/traffic/tiles/{z}/{x}/{y}.png',last_fetch_at:'2026-10-13T10:00:00Z',...extra}});}
test('traffic defaults off without metadata, and enabled layer uses bounded local tiles and quota',async()=>{
 const h=harness();await run(h);assert.equal(h.requests.length,0);assert.equal(h.timers.size,0);
 assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'../src/wici/static/index.html'),'utf8'),/id="traffic-enabled" checked/);
 enabled(h);const pending=run(h);assert.equal(h.requests[0].url,'/api/traffic');respond(h);await pending;
 const layer=h.tiles[0];assert.equal(layer.url,'/api/traffic/tiles/{z}/{x}/{y}.png');assert.deepEqual(JSON.parse(JSON.stringify(layer.options.bounds)),[[49,14],[55,24.2]]);
 assert.equal(layer.options.pane,'trafficFlow');assert.equal(layer.options.tileSize,256);assert.equal(layer.options.keepBuffer,0);assert.equal(layer.options.noWrap,true);assert.equal(layer.options.updateWhenIdle,true);assert.equal(layer.options.updateWhenZooming,false);assert.equal(layer.options.maxNativeZoom,18);
 layer.handlers.tileload();const loaded=layer.handlers.load();respond(h,1);await loaded;assert.equal(h.document.getElementById('traffic-legend').hidden,false);assert.match(h.document.getElementById('traffic-status').textContent,/3 \/ 190000.*lokalne pobranie/);
 h.document.getElementById('traffic-enabled').checked=false;await run(h);assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);
});
test('five minute refresh redraws and sources/hidden document pause until returning',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h);await pending;
 assert.equal([...h.timers.values()][0].ms,300000);pending=[...h.timers.values()][0].fn();respond(h,1);await pending;assert.equal(h.tiles[0].redraws,1);
 h.tabs[1].click();assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);assert.equal(h.requests.length,2);
 h.tabs[0].click();respond(h,2);await new Promise(resolve=>setImmediate(resolve));assert.equal(h.map.layers.size,1);
 h.document.hidden=true;await h.listeners.visibilitychange();assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);
 h.document.hidden=false;pending=h.listeners.visibilitychange();respond(h,3);await pending;assert.equal(h.map.layers.size,1);
});
test('late responses and disabled provider/demo never add traffic',async()=>{
 const h=harness();enabled(h);const pending=run(h);h.document.getElementById('traffic-enabled').checked=false;await run(h);respond(h);await pending;assert.equal(h.tiles.length,0);
 enabled(h);let blocked=run(h);respond(h,1,{enabled:false,message:'Brak klucza'});await blocked;assert.equal(h.tiles.length,0);assert.match(h.document.getElementById('traffic-status').textContent,/Brak klucza/);
 vm.runInContext("state.health.mode='demo'",h.ctx);await run(h);assert.equal(h.requests.length,2);assert.equal(h.timers.size,0);
});
test('tile error discards partial overlay and prevents immediate retry or stale events',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h);await pending;const old=h.tiles[0];old.handlers.tileerror();assert.equal(h.map.layers.size,0);assert.equal(h.document.getElementById('traffic-legend').hidden,true);
 await run(h);old.handlers.load();old.handlers.tileerror();assert.equal(h.requests.length,1);assert.match(h.document.getElementById('traffic-status').textContent,/niedostępny/);
 h.advance(300000);pending=[...h.timers.values()][0].fn();respond(h,1);await pending;assert.equal(h.map.layers.size,1);old.handlers.tileerror();assert.equal(h.map.layers.size,1);
});

test('empty viewport and quota limit show no traffic legend or freshness claim',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h);await pending;h.tiles[0].handlers.load();assert.equal(h.document.getElementById('traffic-legend').hidden,true);assert.match(h.document.getElementById('traffic-status').textContent,/Brak kafelków/);
 pending=run(h);respond(h,1,{status:'limit',message:'Limit miesięczny wyczerpany'});await pending;assert.equal(h.map.layers.size,0);assert.match(h.document.getElementById('traffic-status').textContent,/Limit miesięczny/);
});

test('completed tile batch updates quota and local fetch time once without tile reload',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h,0,{requests_used:1,last_fetch_at:null});await pending;const layer=h.tiles[0];
 layer.handlers.loading();layer.handlers.tileload();layer.handlers.tileload();assert.equal(h.requests.length,1);pending=layer.handlers.load();assert.equal(h.requests.length,2);
 respond(h,1,{requests_used:9,last_fetch_at:'2026-10-13T12:34:00Z'});await pending;assert.match(h.document.getElementById('traffic-status').textContent,/9 \/ 190000.*lokalne pobranie:.*14:34/);assert.equal(layer.redraws,0);assert.equal(h.tiles.length,1);
 await layer.handlers.load();assert.equal(h.requests.length,2);
 layer.handlers.loading();layer.handlers.tileload();pending=layer.handlers.load();respond(h,2,{status:'limit',message:'Limit miesięczny wyczerpany'});await pending;assert.equal(h.map.layers.size,0);assert.match(h.document.getElementById('traffic-status').textContent,/Limit miesięczny/);
});
test('late metadata after tile load cannot change status after disable',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h);await pending;const layer=h.tiles[0];layer.handlers.tileload();pending=layer.handlers.load();
 h.document.getElementById('traffic-enabled').checked=false;await run(h);const status=h.document.getElementById('traffic-status').textContent;respond(h,1,{requests_used:99});await pending;assert.equal(h.document.getElementById('traffic-status').textContent,status);assert.equal(h.map.layers.size,0);
});

function roadRespond(h,index,extra={}){h.requests[index].resolve({response:{ok:true},data:{found:true,name:'Autostrada A1',symbols:['A1','E75'],source:'TomTom',...extra}});}
const popupText=popup=>JSON.stringify(popup.content,(key,value)=>key==='handlers'?undefined:value);
test('clicking road opens name and source symbols safely and only when traffic active',async()=>{
 const h=harness();await run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');assert.equal(h.requests.length,0);
 enabled(h);let pending=run(h);respond(h);await pending;
 pending=run(h,'lookupTrafficRoad({latlng:{lat:52.0729,lng:19.6146}})');assert.equal(h.requests[1].url,'/api/traffic/road?lat=52.072900&lon=19.614600');
 roadRespond(h,1);await pending;assert.match(popupText(h.popups[0]),/Autostrada A1/);assert.match(popupText(h.popups[0]),/E75/);assert.match(popupText(h.popups[0]),/250 m/);
});
test('road popup ignores late response after new click, close and traffic disable',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h);await pending;
 const first=run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');const second=run(h,'lookupTrafficRoad({latlng:{lat:53,lng:20}})');
 roadRespond(h,2,{name:'Droga S8',symbols:['S8']});await second;roadRespond(h,1);await first;assert.match(popupText(h.popups[1]),/Droga S8/);assert.doesNotMatch(popupText(h.popups[0]),/Autostrada A1/);
 pending=run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');h.document.getElementById('traffic-enabled').checked=false;await run(h);roadRespond(h,3);await pending;assert.doesNotMatch(popupText(h.popups[2]),/Autostrada A1/);
 enabled(h);pending=run(h);respond(h,4);await pending;pending=run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');h.popups[3].handlers.remove();roadRespond(h,5);await pending;assert.doesNotMatch(popupText(h.popups[3]),/Autostrada A1/);
});
test('road popup states missing symbols, empty result and lookup error explicitly',async()=>{
 const h=harness();enabled(h);let pending=run(h);respond(h);await pending;
 pending=run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');roadRespond(h,1,{name:'Ulica Zielona',symbols:[]});await pending;assert.match(popupText(h.popups[0]),/nie podało numeru/);
 pending=run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');roadRespond(h,2,{found:false});await pending;assert.match(popupText(h.popups[1]),/Nie znaleziono drogi/);
 pending=run(h,'lookupTrafficRoad({latlng:{lat:52,lng:19}})');h.requests[3].resolve({response:{ok:false},data:{detail:'Limit miesięczny'}});await pending;assert.match(popupText(h.popups[2]),/Limit miesięczny/);
});
