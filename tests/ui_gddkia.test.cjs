const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const elements=new Map(),listeners={},timers=new Map(),markers=[],requests=[];let nextTimer=0;
 function element(tag){return {tag,textContent:'',checked:false,children:[],classList:{remove(){},toggle(){}},append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;},addEventListener(type,fn){this[type]=fn;},setAttribute(){},removeAttribute(){}};}
 const tabs=['situation','sources'].map(view=>({...element('button'),dataset:{view}}));
 const document={hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,element('div'));return elements.get(id);},createElement:element,querySelectorAll(selector){return selector==='.tab'?tabs:[];},querySelector:element,addEventListener(type,fn){listeners[type]=fn;}};
 const map={layers:new Set(),removeLayer(l){this.layers.delete(l);},hasLayer(l){return this.layers.has(l);},invalidateSize(){}};
 const L={layerGroup(){return {markers:[],addTo(m){m.layers.add(this);return this;}};},circleMarker(coords,options){const marker={coords,options,bindPopup(popup,options){this.popup=popup;this.popupOptions=options;return this;},bindTooltip(t){this.tooltip=t;return this;},addTo(g){g.markers.push(this);return this;}};markers.push(marker);return marker;}};
 const ctx=vm.createContext({document,window:{L},L,URL,URLSearchParams,Intl,console,setInterval(fn,ms){timers.set(++nextTimer,{fn,ms});return nextTimer;},clearInterval(id){timers.delete(id);},setTimeout(fn){fn();},fetchJSON(url){return new Promise((resolve,reject)=>requests.push({url,resolve,reject}));}});
 const source=fs.readFileSync(path.join(__dirname,'../src/wici/static/js/app.js'),'utf8').replace('reload();setInterval(reload,60000);','');vm.runInContext(source,ctx);ctx.testMap=map;vm.runInContext("state.map=testMap;state.health={mode:'live',now:'2026-10-14T10:00:00Z'};",ctx);
 return {ctx,document,map,markers,requests,timers,tabs,listeners};
}
const run=(h,expr='syncGddkia()')=>vm.runInContext(expr,h.ctx),enable=h=>{h.document.getElementById('gddkia-enabled').checked=true;};
const item={id:'1',road:'A1',section:'Odcinek',province:'Śląskie',latitude:50.2,longitude:19.1,cause:'Roboty',effects:['Zwężenie'],description:'Objazd',start_at:'2026-10-01T10:00:00Z',planned_end_at:'2026-10-02T10:00:00Z',planned_end_passed:true,upcoming:false,source_url:'https://www.archiwum.gddkia.gov.pl/dane/zima_html/utrdane.xml'};
function respond(h,index=0,extra={}){h.requests[index].resolve({response:{ok:true},data:{enabled:true,status:'success',message:'Odczyt poprawny',items:[item],source_generated_at:'2026-10-14T09:50:00Z',last_success_at:'2026-10-14T10:00:00Z',last_attempt_at:'2026-10-14T10:00:00Z',stale:false,total:3,unmapped_count:2,invalid_count:0,...extra}});}
const text=element=>[element.textContent,...element.children.map(text)].join(' ');
test('default off; independent bounded markers preserve past planned ends and safe popup text',async()=>{
 const h=harness();await run(h);assert.equal(h.requests.length,0);assert.equal(h.timers.size,0);assert.doesNotMatch(fs.readFileSync(path.join(__dirname,'../src/wici/static/index.html'),'utf8'),/id="gddkia-enabled" checked/);
 enable(h);const pending=run(h);assert.equal(h.requests[0].url,'/api/gddkia');respond(h,0,{items:[{...item,road:'<img src=x onerror=alert(1)>',effects:[],description:'<script>bad()</script>',planned_end_at:null,section:''}]});await pending;
 assert.equal(h.map.layers.size,1);assert.equal(h.markers[0].options.pane,'gddkiaIncidents');assert.equal(h.markers[0].options.bubblingMouseEvents,false);assert.match(text(h.markers[0].popup),/Planowany koniec minął; nadal w zestawieniu GDDKiA/);assert.match(text(h.markers[0].popup),/Nie podano/);assert.match(text(h.markers[0].popup),/<script>bad\(\)<\/script>/);assert.match(text(h.markers[0].popup),/środek odcinka/);assert.match(h.document.getElementById('gddkia-status').textContent,/bez współrzędnych: 2.*wygenerowano u źródła.*lokalny odczyt/);
 assert.equal(h.document.getElementById('traffic-enabled').checked,false);
});
test('five minute interval pauses on Sources and browser hidden and resumes checked layer',async()=>{
 const h=harness();enable(h);let pending=run(h);respond(h);await pending;assert.equal([...h.timers.values()][0].ms,300000);
 pending=[...h.timers.values()][0].fn();respond(h,1);await pending;assert.equal(h.map.layers.size,1);
 h.tabs[1].click();assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);assert.equal(h.requests.length,2);
 h.tabs[0].click();respond(h,2);await new Promise(resolve=>setImmediate(resolve));assert.equal(h.map.layers.size,1);
 h.document.hidden=true;h.listeners.visibilitychange();assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);
 h.document.hidden=false;h.listeners.visibilitychange();respond(h,3);await new Promise(resolve=>setImmediate(resolve));assert.equal(h.map.layers.size,1);
 h.document.getElementById('gddkia-enabled').checked=false;await run(h);assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);
});
test('late response after disable and demo cannot repopulate markers',async()=>{
 const h=harness();enable(h);const pending=run(h);h.document.getElementById('gddkia-enabled').checked=false;await run(h);respond(h);await pending;assert.equal(h.markers.length,0);
 enable(h);vm.runInContext("state.health.mode='demo'",h.ctx);await run(h);assert.equal(h.requests.length,1);assert.equal(h.timers.size,0);
});
test('backend stale data and network failure retain markers with explicit stale notices',async()=>{
 const h=harness();enable(h);let pending=run(h);respond(h,0,{stale:true,status:'error',message:'Ostatnie dobre dane'});await pending;assert.equal(h.map.layers.size,1);assert.match(h.document.getElementById('gddkia-status').textContent,/Nieaktualny odczyt/);assert.match(text(h.markers[0].popup),/Nieaktualny odczyt/);
 pending=run(h);respond(h,1);await pending;pending=run(h);h.requests[2].reject(new Error('offline'));await pending;assert.equal(h.map.layers.size,1);assert.match(h.document.getElementById('gddkia-status').textContent,/Nieaktualny odczyt.*zachowano ostatnie dane/);assert.match(text(h.markers.at(-1).popup),/Nieaktualny odczyt/);
});
test('same coordinates group distinct records without losing descriptions and dates',async()=>{
 const h=harness();enable(h);const pending=run(h);respond(h,0,{items:[item,{...item,id:'2',description:'Drugi opis',planned_end_at:'2026-11-01T10:00:00Z',planned_end_passed:false}]});await pending;
 assert.equal(h.markers.length,1);assert.equal(h.markers[0].popup.children.length,2);assert.equal(h.markers[0].popupOptions.maxHeight,340);assert.equal(h.markers[0].popupOptions.maxWidth,340);assert.match(text(h.markers[0].popup),/Objazd/);assert.match(text(h.markers[0].popup),/Drugi opis/);assert.match(h.document.getElementById('gddkia-status').textContent,/1 punktów · 2 zlokalizowanych/);
});
