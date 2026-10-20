const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const elements=new Map(),listeners={},tiles=[],requests=[],styles=[];let additions=0;
 function element(){return {textContent:'',checked:false,children:[],classList:{remove(){},toggle(){}},append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;},addEventListener(type,fn){this[type]=fn;},setAttribute(){},removeAttribute(){}};}
 const tabs=['situation','sources'].map(view=>({...element(),dataset:{view}}));
 const document={hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element,querySelectorAll(selector){return selector==='.tab'?tabs:[];},querySelector:element,addEventListener(type,fn){listeners[type]=fn;}};
 document.getElementById('osm-enabled').checked=true;
 const map={layers:new Set(),removeLayer(l){this.layers.delete(l);},hasLayer(l){return this.layers.has(l);},invalidateSize(){}};
 const L={tileLayer(url,options){const layer={url,options,handlers:{},on(type,fn){this.handlers[type]=fn;return this;},addTo(m){additions++;m.layers.add(this);return this;},redraw(){throw Error('OSM must not redraw');}};tiles.push(layer);return layer;}};
 const ctx=vm.createContext({document,window:{L},L,URL,URLSearchParams,Intl,console,setInterval(){throw Error('No OSM timer');},clearInterval(){},setTimeout(fn){fn();},fetchJSON(url){requests.push(url);throw Error('OSM must not use API');}});
 const source=fs.readFileSync(path.join(__dirname,'../src/wici/static/js/app.js'),'utf8').replace('reload();setInterval(reload,60000);','');vm.runInContext(source,ctx);ctx.testMap=map;ctx.admin={setStyle(style){styles.push(style);}};vm.runInContext('state.administrativeLayer=admin;',ctx);
 return {ctx,document,map,tiles,requests,styles,tabs,listeners,get additions(){return additions;}};
}
const run=(h,expr='syncOsm()')=>vm.runInContext(expr,h.ctx);
const live=h=>run(h,"state.health.mode='live';state.map=testMap;syncOsm();");
test('default checked OSM waits for verified LIVE and map, then uses direct worldwide browser tiles',()=>{
 const h=harness();assert.match(fs.readFileSync(path.join(__dirname,'../src/wici/static/index.html'),'utf8'),/id="osm-enabled" checked disabled/);run(h);assert.equal(h.tiles.length,0);run(h,"state.health.mode='live';syncOsm()");assert.equal(h.tiles.length,0);live(h);
 const layer=h.tiles[0];assert.equal(layer.url,'https://tile.openstreetmap.org/{z}/{x}/{y}.png');assert.equal(layer.options.pane,'osmBase');assert.equal(layer.options.referrerPolicy,'strict-origin-when-cross-origin');assert.equal('crossOrigin' in layer.options,false);assert.equal(layer.options.keepBuffer,0);assert.equal(layer.options.noWrap,true);assert.equal(layer.options.updateWhenIdle,true);assert.equal(layer.options.updateWhenZooming,false);assert.equal(layer.options.maxNativeZoom,19);assert.equal(layer.options.maxZoom,19);assert.equal('bounds' in layer.options,false);assert.match(layer.options.attribution,/openstreetmap.org\/copyright/);
 assert.equal(h.styles.at(-1).fillOpacity,0);assert.equal(h.document.getElementById('traffic-enabled').checked,false);assert.equal(h.document.getElementById('gddkia-enabled').checked,false);h.document.getElementById('traffic-enabled').checked=true;run(h);assert.equal(h.map.hasLayer(layer),true);assert.equal(h.tiles.length,1);assert.equal(h.styles.at(-1).fillOpacity,0);assert.deepEqual(h.requests,[]);assert.match(h.document.getElementById('map-note').textContent,/OpenStreetMap.*PRG/);
});
test('repeated ready-map reload reuses layer without redraw or extra additions; toggle restores PRG fill',async()=>{
 const h=harness();live(h);run(h,'mapReady=true');await run(h,'initMap()');await run(h,'initMap()');assert.equal(h.tiles.length,1);assert.equal(h.additions,1);
 h.document.getElementById('osm-enabled').checked=false;run(h);assert.equal(h.map.layers.size,0);assert.equal(h.styles.at(-1).fillOpacity,1);
 h.document.getElementById('osm-enabled').checked=true;run(h);assert.equal(h.tiles.length,1);assert.equal(h.additions,2);assert.equal(h.styles.at(-1).fillOpacity,0);
});
test('sources and hidden browser remove OSM and return restores same layer; demo never creates URLs',()=>{
 const h=harness();run(h,"state.health.mode='demo';state.map=testMap;syncOsm()");assert.equal(h.tiles.length,0);assert.equal(h.document.getElementById('osm-enabled').disabled,true);live(h);
 h.tabs[1].click();assert.equal(h.map.layers.size,0);h.tabs[0].click();assert.equal(h.map.layers.size,1);h.document.hidden=true;h.listeners.visibilitychange();assert.equal(h.map.layers.size,0);h.document.hidden=false;h.listeners.visibilitychange();assert.equal(h.map.layers.size,1);assert.equal(h.tiles.length,1);
 run(h,"state.health.mode='demo';syncOsm()");assert.equal(h.map.layers.size,0);assert.equal(h.styles.at(-1).fillOpacity,1);assert.deepEqual(h.requests,[]);
});
test('tile failures preserve boundaries, do not retry, and late disabled events cannot change status',()=>{
 const h=harness();live(h);const layer=h.tiles[0];layer.handlers.loading();layer.handlers.tileerror();layer.handlers.load();assert.match(h.document.getElementById('osm-status').textContent,/Podkład OSM niedostępny; granice i znaczniki pozostają dostępne/);assert.equal(h.additions,1);assert.equal(h.map.layers.size,1);
 layer.handlers.loading();layer.handlers.load();assert.equal(h.document.getElementById('osm-status').textContent,'Podkład drogowy OpenStreetMap.');
 h.document.getElementById('osm-enabled').checked=false;run(h);const status=h.document.getElementById('osm-status').textContent;layer.handlers.tileerror();layer.handlers.load();assert.equal(h.document.getElementById('osm-status').textContent,status);assert.equal(h.map.layers.size,0);assert.equal(h.styles.at(-1).fillOpacity,1);
});
