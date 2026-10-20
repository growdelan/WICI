// Lifecycle regression: polling, aborted sessions, age expiry, and popup values.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let now=Date.now(), nextId=0, pending=[], attribution='';
const timers=new Map(), intervals=new Map(), created=[];
const followCalls={init:[],sync:[],update:[],open:[]};
const followController=Object.fromEntries(Object.keys(followCalls).map(name=>[name,(...args)=>followCalls[name].push(args)]));
class Element {
  constructor(){this.children=[];this.style={};this.textContent='';this.checked=false;this.disabled=false;this.listeners={};this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  addEventListener(event,callback){this.listeners[event]=callback;}
  focus(){doc.activeElement=this;}
}
const controls={'aircraft-enabled':new Element(),'aircraft-status':new Element()};
const doc={hidden:false,getElementById:id=>controls[id],createElement:()=>new Element()};
const map={createPane:()=>({style:{}}),attributionControl:{addAttribution(value){attribution=value;}},removeLayer(layer){layer.removed=true;}};
const L={layerGroup:()=>({addTo(){return this;},removeLayer(marker){marker.removed=true;}}),divIcon:options=>options,
 marker:(coords,options)=>{const marker={coords,options,opened:false,overlay:{options:{autoPan:true}},bindPopup(fn){this.popup=fn;return this;},getPopup(){return this.overlay;},bindTooltip(){return this;},addTo(){return this;},setLatLng(value){this.coords=value;return this;},setIcon(value){this.options.icon=value;if(this.opened)this.content=this.popup();return this;},isPopupOpen(){return this.opened;},setPopupContent(value){this.content=value;return this;}};created.push(marker);return marker;}};
class ClockDate extends Date {static now(){return now;}}
const context={window:{WiciAircraft3D:followController},document:doc,L,Date:ClockDate,Number,Math,Map,Set,Boolean,AbortController,TypeError,SyntaxError,
 setTimeout(fn,ms){const id=++nextId;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
 setInterval(fn,ms){const id=++nextId;intervals.set(id,{fn,ms});return id;},clearInterval(id){intervals.delete(id);},
 fetch(url,options){assert.equal(url,'/api/aircraft');return new Promise((resolve,reject)=>pending.push({resolve,reject,signal:options.signal}));}};
vm.runInNewContext(fs.readFileSync('src/wici/static/js/aircraft.js','utf8'),context);
const ui=context.window.WiciAircraft;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const item={hex:'48abcd',id:'LOT3JK',registration:'SP-LIO',type_code:'E75S',latitude:52,longitude:19,altitude_m:10973,speed_kmh:800,track:90,position_at:new Date(now-2000).toISOString()};
const response={ok:true,json:async()=>({items:[item],stale:false,status:'ready',message:''})};
(async()=>{
 ui.init({map,health:{mode:'live'}});ui.sync({visible:true});assert.equal(pending.length,0);
 assert.equal(followCalls.init.length,1);assert.equal(followCalls.init[0][0].map,map);
 assert.equal(followCalls.sync.at(-1)[0].visible,true);assert.equal(followCalls.sync.at(-1)[0].enabled,false);
 assert.ok(attribution.includes('https://adsb.fi/') && !attribution.includes('ODbL'));
 assert.ok(attribution.includes('niekomercyjny'));
 controls['aircraft-enabled'].checked=true;controls['aircraft-enabled'].listeners.change();assert.equal(pending.length,1);
 assert.ok([...timers.values()].some(x=>x.ms===15000)); // Backend has 10 s to return a diagnostic.
 pending.shift().resolve(response);await settle();assert.equal(created.length,1);assert.equal(created[0].options.icon.html.style.transform,'rotate(0deg)');
 assert.equal(created[0].options.icon.html.className,'aircraft-symbol');
 assert.equal(followCalls.update.length,1);assert.equal(followCalls.update[0][0].items[0],item);
 created[0].opened=true;
 delete context.window.WiciAircraft3D;const popup=created[0].popup();assert.equal(popup.children.length,3);
 context.window.WiciAircraft3D=followController;assert.equal(created[0].popup(),popup);
 const texts=popup.children[1].children.map(x=>x.textContent);
 assert.ok(popup.children[2].textContent.includes('adsb.fi'));
 for(const value of ['LOT3JK','SP-LIO','E75S','800 km/h','2 s'])assert.ok(texts.includes(value));
 const follow=popup.children[3];assert.equal(follow.textContent,'Podążaj w 3D');assert.equal(follow.disabled,false);
 follow.focus();[...intervals.values()][0].fn();assert.equal(doc.activeElement,follow);assert.equal(created[0].popup(),popup);
 follow.listeners.click();assert.equal(followCalls.open.length,1);assert.equal(followCalls.open[0][0],item);assert.equal(followCalls.open[0][1],followCalls.update[0][0]);assert.equal(followCalls.open[0][2],follow);
 assert.equal(followCalls.open[0][3],created[0].getPopup());
 const refresh=[...timers.entries()].find(([,x])=>x.ms===10000);
 assert.ok(refresh);
 timers.delete(refresh[0]);refresh[1].fn();assert.equal(pending.length,1);
 const latestItem={...item,id:'LOT9ZZ',military:true,latitude:52.1};
 const latestSnapshot={items:[latestItem],stale:false,status:'ready',message:''};
 pending.shift().resolve({ok:true,json:async()=>latestSnapshot});await settle();
 assert.equal(created.length,1); // Refresh updates the existing marker.
 assert.equal(created[0].options.icon.html.className,'aircraft-symbol aircraft-military');
 assert.equal(doc.activeElement,follow);assert.equal(created[0].content,popup);assert.equal(popup.children[3],follow);
 assert.equal(popup.children[0].textContent,'LOT9ZZ');
 follow.listeners.click();assert.equal(followCalls.open.at(-1)[0],latestItem);assert.equal(followCalls.open.at(-1)[1],latestSnapshot);
 latestItem.altitude_m=null;[...intervals.values()][0].fn();assert.equal(follow.disabled,true);
 const opened=followCalls.open.length;follow.listeners.click();assert.equal(followCalls.open.length,opened);
 latestItem.altitude_m=item.altitude_m;now+=29000;[...intervals.values()][0].fn();assert.equal(follow.disabled,true);
 follow.listeners.click();assert.equal(followCalls.open.length,opened);
 now-=29000;[...intervals.values()][0].fn();assert.equal(follow.disabled,false);
 const pausedRefresh=[...timers.values()].find(x=>x.ms===10000);
 ui.sync({visible:false});assert.equal(timers.size,0);assert.equal(intervals.size,0);
 assert.equal(followCalls.sync.at(-1)[0].visible,false);assert.equal(followCalls.sync.at(-1)[0].hidden,false);
 pausedRefresh.fn();assert.equal(pending.length,0);
 ui.sync({visible:true});assert.equal(pending.length,1);const old=pending.shift();
 controls['aircraft-enabled'].checked=false;controls['aircraft-enabled'].listeners.change();assert.equal(old.signal.aborted,true);
 old.resolve(response);await settle();assert.equal(timers.size,0);
 controls['aircraft-enabled'].checked=true;controls['aircraft-enabled'].listeners.change();pending.shift().resolve(response);await settle();
 const failedRefresh=[...timers.entries()].find(([,x])=>x.ms===10000);
 timers.delete(failedRefresh[0]);failedRefresh[1].fn();
 pending.shift().reject(new TypeError('Failed to fetch'));await settle();
 assert.ok(controls['aircraft-status'].textContent.includes('Brak połączenia z lokalnym serwerem WICI'));
 assert.equal(followCalls.update.at(-1)[0].stale,true);assert.equal(followCalls.update.at(-1)[0].status,'error');
 const staleMarker=created.at(-1);staleMarker.opened=true;const staleFollow=staleMarker.popup().children[3];assert.equal(staleFollow.disabled,true);
 staleFollow.listeners.click();assert.equal(followCalls.open.length,opened);
 const timeoutRefresh=[...timers.entries()].find(([,x])=>x.ms===10000);
 timers.delete(timeoutRefresh[0]);timeoutRefresh[1].fn();
 const abort=new Error('Aborted');abort.name='AbortError';pending.shift().reject(abort);await settle();
 assert.ok(controls['aircraft-status'].textContent.includes('nie odpowiedział w ciągu 15 s'));
 const latest=created.at(-1);now+=121000;[...intervals.values()][0].fn();assert.equal(latest.removed,true);
 doc.hidden=true;ui.sync({visible:true});assert.equal(timers.size,0);assert.equal(intervals.size,0);
 assert.equal(followCalls.sync.at(-1)[0].hidden,true);
 doc.hidden=false;ui.sync({visible:true,health:{mode:'demo'}});assert.equal(pending.length,0);assert.equal(controls['aircraft-enabled'].disabled,true);
 assert.equal(followCalls.sync.at(-1)[0].mode,'demo');
 console.log('Aircraft UI lifecycle passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
