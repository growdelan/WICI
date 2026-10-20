// Deterministic polling, history selection, failed API reads and recovery regression.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const controls={},timers=new Map(),pending=[],layers=new Set();let timerId=0;
class Element{
 constructor(){this.children=[];this.textContent='';this.listeners={};this.checked=false;this._value='';this.classList={toggle(){}};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;if(this.select)this._value=nodes[0]?.value??'';}
 addEventListener(name,fn){this.listeners[name]=fn;}
 get value(){return this._value;}
 set value(v){this._value=String(v);}
}
for(const id of ['enabled','hours','window','status','summary','method','note','latest','follow'])controls[`quality-${id}`]=new Element();
const $=id=>controls[`quality-${id}`];$('enabled').checked=true;$('hours').value='24';$('window').select=true;
const map={removeLayer(layer){layers.delete(layer);}};
const context={window:{},document:{getElementById:id=>controls[id],createElement:()=>new Element()},
 L:{layerGroup:()=>({shapes:[],addTo(){layers.add(this);return this;}}),geoJSON:(geometry,options)=>({options,bindPopup(){return this;},bindTooltip(){return this;},addTo(layer){layer.shapes.push(this);return this;}})},
 setTimeout(fn,ms){assert.equal(ms,60000);const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},URLSearchParams,Intl,Date,Number,Boolean,Set,JSON};
vm.runInNewContext(fs.readFileSync('src/wici/static/js/position-quality.js','utf8'),context);
const ui=context.window.WiciPositionQuality;
let ctx={map,visible:true,day:'2026-10-17',province:'',api:url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject}))};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const response=(times,end=times.at(-1)+300)=>({items:times.map(t=>({window_start:t,window_end:t+300,state:'normal',geometry:{},aircraft:6})),window_end:end,window_start:0,source:{},coverage:{unlocated_reports:0},status:'ready',status_label:'Odczyt źródła poprawny'});
async function answer(data){assert.equal(pending.length,1);pending.shift().resolve(data);await settle();}
function poll(){assert.equal(timers.size,1);const [id,fn]=timers.entries().next().value;timers.delete(id);fn();}
function choose(t){$('window').value=t;$('window').listeners.change();}
const colors=()=>[...layers].flatMap(l=>l.shapes.map(s=>s.options.style.color));
(async()=>{
 ui.sync(ctx);await answer({...response([300,600]),pending_writes:3,dropped_snapshots:7,coverage:{unlocated_reports:0,unknown_provenance_reports:42}});
 assert.match($('note').textContent,/Historia bez ustalonego źródła: 42 raportów/);assert.match($('note').textContent,/Po zmianie źródła wymagana jest nowa rozgrzewka/);
 assert.match($('summary').textContent,/Oczekujące zapisy: 3/);assert.match($('summary').textContent,/pominięte snapshoty od uruchomienia: 7/);assert.equal($('window').value,'600');assert.match($('follow').textContent,/Śledzenie/);
 poll();await answer(response([300,600,900]));assert.equal($('window').value,'900');
 choose(300);poll();await answer(response([300,600,900,1200]));assert.equal($('window').value,'300');assert.match($('follow').textContent,/Ręcznie/);
 $('latest').listeners.click();assert.equal($('window').value,'1200');
 poll();await answer(response([300,600,900,1200,1500],1570));assert.equal($('window').value,'1200');
 poll();await answer(response([300,600,900,1200,1500],1850));assert.equal($('window').value,'1500');
 poll();pending.shift().reject(Error('local API unavailable'));await settle();assert.match($('status').textContent,/Błąd odczytu/);assert.deepEqual(colors(),['#9a6639']);
 choose(600);assert.match($('status').textContent,/Błąd odczytu/);assert.deepEqual(colors(),['#9a6639']);
 $('latest').listeners.click();assert.match($('status').textContent,/Błąd odczytu/);
 poll();await answer(response([300,600,900,1200,1500,1800]));assert.equal($('window').value,'1800');assert.equal($('status').textContent.includes('Błąd'),false);assert.deepEqual(colors(),['#298269']);
 // A new scope cannot redraw records from the previous province/day on a failed read.
 ctx={...ctx,province:'32'};ui.sync(ctx);pending.shift().reject(Error('new scope unavailable'));await settle();choose(600);assert.equal(layers.size,0);assert.match($('status').textContent,/Błąd odczytu/);
 poll();await answer(response([2100,2400]));assert.equal($('window').value,'2400');
 // Stale in-flight responses cannot overwrite the newest filter or restart a timer.
 ctx={...ctx,day:'2026-10-16'};ui.sync(ctx);const old=pending.shift();ctx={...ctx,day:'2026-10-15'};ui.sync(ctx);old.resolve(response([2700,3000]));await settle();assert.equal(layers.size,0);
 await answer(response([3300,3600]));assert.equal($('window').value,'3600');assert.equal(timers.size,1);
 ui.sync({...ctx,visible:false});assert.equal(layers.size,0);assert.equal(timers.size,0);
 console.log('Position quality lifecycle: follow latest, manual history, API errors, recovery, scope races and pause passed.');
})().catch(e=>{console.error(e);process.exit(1);});
