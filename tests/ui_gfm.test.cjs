'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const initial=Date.parse('2026-10-17T10:00:00Z');
function harness(){
  let now=initial,sequence=0;
  const controls=new Map(),requests=[],intervals=new Map(),listeners={};
  const element=()=>({value:'',checked:false,hidden:false,children:[],textContent:'',
    addEventListener(name,fn){this[name]=fn;},append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=nodes;this.value='';}});
  const document={hidden:false,createElement:element,getElementById(id){if(!controls.has(id))controls.set(id,element());return controls.get(id);},addEventListener(name,fn){listeners[name]=fn;}};
  const map={layers:new Set(),fitBounds(bounds){this.fitted=bounds;},createPane:()=>({style:{}}),removeLayer(layer){this.layers.delete(layer);},
    getBounds:()=>({getWest:()=>16.55,getSouth:()=>50.35,getEast:()=>16.75,getNorth:()=>50.55})};
  class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
  const L={imageOverlay(){return {handlers:{},on(name,fn){this.handlers[name]=fn;},addTo(map){map.layers.add(this);},setOpacity(){}};}};
  const window={};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/gfm.js','utf8'),{window,document,L,URLSearchParams,Date:Clock,
    setInterval(fn,ms){assert.equal(ms,60000);intervals.set(++sequence,fn);return sequence;},clearInterval(id){intervals.delete(id);}});
  const api=(url,...options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
  window.WiciGFM.init({map,api});
  return {window,map,ui:window.WiciGFM,document,map,requests,intervals,listeners,
    control:name=>document.getElementById('gfm-'+name),advance(ms){now+=ms;},tick(){for(const fn of [...intervals.values()])fn();}};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const counts={assessed_clear:100,flood:1,reference_water:0,excluded:0,no_observation:0};
const data=()=>({status:'flood',image:'',bounds:[[50.35,16.55],[50.55,16.75]],counts:{...counts},
  source_counts:{...counts},quality:{},product:{id:'test',observed_at:new Date(initial).toISOString(),stale:false}});
async function select(h,result=data()){
  h.control('enabled').checked=true;h.control('enabled').change();
  h.control('search').click();h.requests.at(-1).resolve({items:[result.product]});await flush();
  h.control('observation').value=result.product.id;h.control('observation').change();
  h.requests.at(-1).resolve(result);await flush();
}

test('age and stale status advance without reselecting or fetching the observation',async()=>{
  const h=harness();assert.equal(h.intervals.size,0);await select(h);
  const overlay=[...h.map.layers][0],timer=[...h.intervals.keys()][0];
  assert.match(h.control('status').textContent,/Wiek: 0 h/);
  h.advance(2*3600000);h.tick();assert.match(h.control('status').textContent,/Wiek: 2 h/);
  h.advance(22*3600000);h.tick();assert.doesNotMatch(h.control('status').textContent,/NIEAKTUALNA/);
  h.advance(60000);h.tick();assert.match(h.control('status').textContent,/NIEAKTUALNA/);
  h.advance(3*3600000);h.ui.sync({visible:true});assert.match(h.control('status').textContent,/Wiek: 27 h/);
  assert.match(h.control('status').textContent,/NIEAKTUALNA/);
  assert.equal(h.requests.length,2);assert.equal([...h.map.layers][0],overlay);
  assert.equal(h.intervals.size,1);assert.equal([...h.intervals.keys()][0],timer);
});

test('cached stale flags do not override freshness derived from the observation time',async()=>{
  for(const [ageHours,cachedStale,expectedStale] of [[26,false,true],[0,true,false]]){
    const h=harness(),result=data();result.product.observed_at=new Date(initial-ageHours*3600000).toISOString();result.product.stale=cachedStale;
    await select(h,result);assert.equal(h.control('status').textContent.includes('NIEAKTUALNA'),expectedStale);
    assert.match(h.control('status').textContent,new RegExp(`Wiek: ${ageHours} h`));
  }
});

test('clearing or hiding removes the clock and old callbacks cannot restore an observation status',async()=>{
  for(const action of ['disable','view','tab','date','selection']){
    const h=harness();await select(h);const late=[...h.intervals.values()][0];
    if(action==='disable'){h.control('enabled').checked=false;h.control('enabled').change();}
    if(action==='view')h.ui.sync({visible:false});
    if(action==='tab'){h.document.hidden=true;h.listeners.visibilitychange();}
    if(action==='date')h.control('start').change();
    if(action==='selection'){h.control('observation').value='';h.control('observation').change();}
    const status=h.control('status').textContent;
    h.advance(26*3600000);late();assert.equal(h.control('status').textContent,status);
    assert.equal(h.intervals.size,0);assert.equal(h.map.layers.size,0);assert.equal(h.requests.length,2);
  }
});

test('a failed image cannot later acquire a successful status from the clock',async()=>{
  const h=harness();await select(h);const late=[...h.intervals.values()][0];
  [...h.map.layers][0].handlers.error();h.advance(3600000);late();
  assert.match(h.control('status').textContent,/Błąd wyświetlania/);
  assert.equal(h.intervals.size,0);assert.equal(h.map.layers.size,0);
});

test('omitted preview pixels retain the source detection and explain why the image may appear empty',async()=>{
  const h=harness(),result=data();result.counts.flood=0;await select(h,result);
  assert.match(h.control('status').textContent,/Wykryto zalanie/);
  assert.match(h.control('status').textContent,/zbyt drobne.*przybliż mapę/);
  assert.doesNotMatch(h.control('status').textContent,/Brak wykrytego zalania/);
  assert.match(h.control('detail').children.map(e=>e.textContent).join(' '),/Piksele źródłowe.*zalanie 1/);
});

const historicId='ENSEMBLE_FLOOD_20240915T050149_VV_EU020M_E051N018T3';
test('historical trial fetches a fixed AOI and renders the verified observation even on a very wide map',async()=>{
  const h=harness();h.map.getBounds=()=>({getWest:()=>15,getSouth:()=>49,getEast:()=>18,getNorth:()=>52});
  h.control('enabled').checked=true;h.control('enabled').change();h.control('klodzko').click();
  assert.equal(h.requests.length,1);assert.ok(h.map.fitted);
  const query=new URLSearchParams(h.requests[0].url.split('?')[1]);
  assert.equal(query.get('bbox'),'16.55,50.35,16.75,50.55');
  assert.equal(query.get('start'),'2024-09-14');assert.equal(query.get('end'),'2024-09-17');
  const result=data();result.product.id=historicId;
  h.requests[0].resolve({items:[{...result.product,id:'another-product'},result.product]});await flush();
  assert.equal(h.requests.length,2);assert.match(h.requests[1].url,new RegExp(`/render/${historicId}`));
  assert.equal(new URLSearchParams(h.requests[1].url.split('?')[1]).get('bbox'),query.get('bbox'));
  h.requests[1].resolve(result);await flush();assert.equal(h.map.layers.size,1);
  assert.match(h.control('status').textContent,/Wykryto zalanie/);
  assert.match(h.control('area').textContent,/Stały obszar próby historycznej/);
  h.control('search').click();assert.equal(new URLSearchParams(h.requests.at(-1).url.split('?')[1]).get('bbox'),'15,49,18,52');
});

test('historical trial cannot render after disabling, and does not guess a replacement for missing data',async()=>{
  for(const scenario of ['disabled','missing','demo']){
    const h=harness();h.control('enabled').checked=true;h.control('enabled').change();h.control('klodzko').click();
    if(scenario==='disabled'){h.control('enabled').checked=false;h.control('enabled').change();}
    const result=data();result.product.id=historicId;
    h.requests[0].resolve(scenario==='disabled'?{items:[result.product]}:scenario==='demo'?{enabled:false,items:[],message:'Demo offline: brak danych GFM.'}:{items:[]});
    await flush();assert.equal(h.requests.length,1);assert.equal(h.map.layers.size,0);
    assert.match(h.control('status').textContent,scenario==='disabled'?/wyłączona/:scenario==='demo'?/Demo offline/:/nie udostępniło/);
  }
});

test('regional manual query uses viewport intersection rather than entire province and skips outside',()=>{
 const h=harness();let inside=true;h.window.WiciRegion={viewBox:view=>inside?[view.getWest(),view.getSouth(),view.getEast(),view.getNorth()]:null};
 h.control('enabled').checked=true;h.control('search').click();assert.equal(new URLSearchParams(h.requests[0].url.split('?')[1]).get('bbox'),'16.55,50.35,16.75,50.55');
 inside=false;h.control('search').click();assert.equal(h.requests.length,1);assert.match(h.control('area').textContent,/Brak wspólnego obszaru/);assert.ok(h.control('observation').disabled);
});
