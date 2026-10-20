const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function harness() {
  const elements = new Map();
  function element() {
    return {textContent:'',value:'',checked:false,className:'',children:[],
      classList:{toggle(){},remove(){}},append(...children){this.children.push(...children);},
      replaceChildren(...children){this.children=children;},addEventListener(){},setAttribute(){}};
  }
  const document = {getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},
    createElement:element,querySelectorAll(){return [];},querySelector:element,addEventListener(){}};
  document.getElementById('fires-enabled').checked=true;
  document.getElementById('fires-hours').value='24';
  document.getElementById('selected-day').value='2026-10-13';
  const map = {layers:new Set(),hasLayer(l){return this.layers.has(l);},removeLayer(l){this.layers.delete(l);}};
  const L = {layerGroup(){return {layers:[],clearLayers(){this.layers=[];},addTo(m){m.layers.add(this);return this;}};},
    circleMarker(coords){return {coords,bindPopup(p){this.popup=p;return this;},bindTooltip(){return this;},addTo(g){g.layers.push(this);return this;}};}};
  const requests=[];
  const ctx = vm.createContext({document,window:{L},L,URL,URLSearchParams,Intl,console,
    fetchJSON(url){return new Promise((resolve,reject)=>requests.push({url,resolve,reject}));}});
  let source=fs.readFileSync(path.join(__dirname,'../src/wici/static/js/app.js'),'utf8');
  source=source.replace('reload();setInterval(reload,60000);','');
  vm.runInContext(source,ctx);
  ctx.testMap=map;vm.runInContext('state.map = testMap;',ctx);
  return {ctx,document,map,requests};
}
const detection={id:'1',latitude:52,longitude:20,observed_at:'2026-10-13T09:00:00Z',age_minutes:60,satellite:'NOAA-20',instrument:'VIIRS',confidence:'n',frp:4};
function respond(request,items=[detection]){request.resolve({response:{ok:true},data:{items,total:items.length,hours:24,window_start:'2026-10-12T10:00:00Z',window_end:'2026-10-13T10:00:00Z'}});}

test('fire layer survives communications redraw without accumulating points and hides on toggle',async()=>{
  const h=harness();const pending=vm.runInContext('loadFires()',h.ctx);respond(h.requests[0]);await pending;
  const layer=vm.runInContext('state.fireLayer',h.ctx);
  assert.equal(layer.layers.length,1);
  vm.runInContext('renderMap();renderMap();',h.ctx);
  assert.equal(layer.layers.length,1);assert.equal(h.map.layers.size,1);
  h.document.getElementById('fires-enabled').checked=false;
  await vm.runInContext('loadFires()',h.ctx);
  assert.equal(h.map.layers.size,0);assert.equal(layer.layers.length,0);
});

test('new filters win over late older responses; fire query excludes communication filters',async()=>{
  const h=harness();const first=vm.runInContext('loadFires()',h.ctx);
  h.document.getElementById('fires-hours').value='48';h.document.getElementById('province').value='14';
  h.document.getElementById('selected-day').value='2026-10-12';
  const second=vm.runInContext('loadFires()',h.ctx);
  assert.equal(h.requests[1].url,'/api/fires?hours=48&date=2026-10-12&voivodeship=14');
  respond(h.requests[1],[{...detection,id:'new'}]);await second;
  respond(h.requests[0],[{...detection,id:'old'}]);await first;
  assert.equal(vm.runInContext('state.fires[0].id',h.ctx),'new');
});

test('disabling an in-flight request prevents points reappearing; errors remove old date points',async()=>{
  const h=harness();const first=vm.runInContext('loadFires()',h.ctx);
  h.document.getElementById('fires-enabled').checked=false;await vm.runInContext('loadFires()',h.ctx);
  respond(h.requests[0]);await first;assert.equal(h.map.layers.size,0);
  h.document.getElementById('fires-enabled').checked=true;const success=vm.runInContext('loadFires()',h.ctx);
  respond(h.requests[1]);await success;assert.equal(vm.runInContext('state.fireLayer.layers.length',h.ctx),1);
  const failed=vm.runInContext('loadFires()',h.ctx);h.requests[2].reject(new Error('Offline'));await failed;
  assert.equal(vm.runInContext('state.fireLayer.layers.length',h.ctx),0);
  assert.match(h.document.getElementById('fires-status').textContent,/Offline/);
});
