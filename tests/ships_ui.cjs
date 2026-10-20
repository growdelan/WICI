// Lifecycle regression: polling, aborted sessions, age expiry, and popup values.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let now=Date.now(), nextId=0, pending=[];
const timers=new Map(), intervals=new Map(), created=[];
class Element {
  constructor(){this.children=[];this.style={};this.textContent='';this.checked=false;this.disabled=false;this.listeners={};this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  addEventListener(event,callback){this.listeners[event]=callback;}
}
const controls={'ships-enabled':new Element(),'ships-status':new Element(),'ships-baltic':new Element(),'ships-map-legend':new Element()};
const doc={hidden:false,getElementById:id=>controls[id],createElement:()=>new Element(),addEventListener(){}};
const map={fitBounds(bounds){this.bounds=bounds;},createPane:()=>({style:{}}),attributionControl:{addAttribution(){}},removeLayer(layer){layer.removed=true;}};
const L={layerGroup:()=>({addTo(){return this;},removeLayer(marker){marker.removed=true;}}),divIcon:options=>options,
 marker:(coords,options)=>{const marker={coords,options,opened:false,iconChanges:0,bindPopup(fn){this.popup=fn;return this;},bindTooltip(fn){this.tooltip=fn;return this;},addTo(){return this;},setLatLng(value){this.coords=value;return this;},setIcon(value){this.iconChanges++;this.options.icon=value;return this;},isPopupOpen(){return this.opened;},setPopupContent(value){this.content=value;return this;}};created.push(marker);return marker;}};
class ClockDate extends Date {static now(){return now;}}
const context={window:{},document:doc,L,Date:ClockDate,Number,Math,Map,Set,Boolean,AbortController,
 setTimeout(fn,ms){const id=++nextId;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
 setInterval(fn,ms){const id=++nextId;intervals.set(id,{fn,ms});return id;},clearInterval(id){intervals.delete(id);},
 fetch(url,options){assert.equal(url,'/api/ships');return new Promise(resolve=>pending.push({resolve,signal:options.signal}));}};
vm.runInNewContext(fs.readFileSync('src/wici/static/js/ships.js','utf8'),context);
const ui=context.window.WiciShips;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const item={mmsi:'261000001',name:'BALTIC TEST',imo:'1234567',type_code:70,latitude:55,longitude:19,speed_knots:12.5,course:90,heading:90,destination:'GDANSK',position_at:new Date(now-2000).toISOString()};
const response={ok:true,json:async()=>({items:[item],stale:false,status:'ready',message:''})};
(async()=>{
 ui.init({map,health:{mode:'live'}});controls['ships-baltic'].listeners.click();assert.equal(JSON.stringify(map.bounds),JSON.stringify([[53.4,9.4],[66,30.5]]));ui.sync({visible:true});assert.equal(pending.length,0);assert.equal(controls['ships-map-legend'].hidden,true);
 controls['ships-enabled'].checked=true;controls['ships-enabled'].listeners.change();assert.equal(pending.length,1);
 pending.shift().resolve(response);await settle();assert.equal(created.length,1);assert.equal(controls['ships-map-legend'].hidden,false);assert.ok(created[0].options.icon.html.className.includes('ship-civilian'));assert.equal(created[0].options.icon.html.style.transform,'rotate(90deg)');
 created[0].opened=true;const popup=created[0].popup();const texts=popup.children[1].children.map(x=>x.textContent);
 for(const value of ['261000001','1234567',70,'12.5 w.','GDANSK','0 min 2 s'])assert.ok(texts.includes(value));
 const refresh=[...timers.entries()].find(([,x])=>x.ms===10000);
 assert.ok(refresh);
 timers.delete(refresh[0]);refresh[1].fn();assert.equal(pending.length,1);
 pending.shift().resolve(response);await settle();
 assert.equal(created.length,1); // Refresh updates the existing marker.
 const pausedRefresh=[...timers.values()].find(x=>x.ms===10000);
 ui.sync({visible:false});assert.equal(timers.size,0);assert.equal(intervals.size,0);assert.equal(controls['ships-map-legend'].hidden,true);
 pausedRefresh.fn();assert.equal(pending.length,0);
 ui.sync({visible:true});assert.equal(pending.length,1);const old=pending.shift();
 controls['ships-enabled'].checked=false;controls['ships-enabled'].listeners.change();assert.equal(old.signal.aborted,true);
 old.resolve(response);await settle();assert.equal(timers.size,0);
 controls['ships-enabled'].checked=true;controls['ships-enabled'].listeners.change();pending.shift().resolve(response);await settle();
 const latest=created.at(-1);[...intervals.values()][0].fn();[...intervals.values()][0].fn();assert.equal(latest.iconChanges,0);now+=301000;[...intervals.values()][0].fn();assert.equal(latest.iconChanges,1);assert.ok(latest.options.icon.html.className.includes('ship-old'));assert.ok(!latest.removed);[...intervals.values()][0].fn();assert.equal(latest.iconChanges,1);
 const nextRefresh=[...timers.entries()].find(([,x])=>x.ms===10000);timers.delete(nextRefresh[0]);nextRefresh[1].fn();item.position_at=new Date(now).toISOString();pending.shift().resolve(response);await settle();assert.equal(latest.shipOld,false);assert.ok(!latest.options.icon.html.className.includes('ship-old'));assert.equal(latest.iconChanges,2);[...intervals.values()][0].fn();assert.equal(latest.iconChanges,2);now+=901000;[...intervals.values()][0].fn();assert.equal(latest.removed,true);
 doc.hidden=true;ui.sync({visible:true});assert.equal(timers.size,0);assert.equal(intervals.size,0);
 doc.hidden=false;ui.sync({visible:true,health:{mode:'demo'}});assert.equal(pending.length,0);assert.equal(controls['ships-enabled'].disabled,true);
 // Exercise all three categories, reserved/ambiguous values, and later metadata updates.
 doc.hidden=false;ui.sync({visible:true,health:{mode:'live'}});
 const codes=[35,70,30,60,36,50,52,80,null,0,1,19,25,38,45,55,51,56,58,65,75,85,90,99,100,'35',35.5];
 let records=codes.map((type_code,index)=>({...item,mmsi:String(261100000+index),type_code,position_at:new Date(now).toISOString()}));
 let start=created.length;
 pending.shift().resolve({ok:true,json:async()=>({items:records,status:'ready',stale:false})});await settle();
 const labels=['Wojskowe według AIS (kod 35)','Typ cywilny według AIS','Nieustalone'];
 for(let i=0;i<codes.length;i++){
  const marker=created[start+i],category=i===0?'military':i<8?'civilian':'unclassified';
  assert.ok(marker.options.icon.html.className.includes(`ship-${category}`),`code ${codes[i]}`);
  const values=marker.popup().children[1].children.map(x=>x.textContent);
  assert.ok(values.includes(labels[i===0?0:i<8?1:2]));
  assert.ok(marker.tooltip().textContent.includes(labels[i===0?0:i<8?1:2]));
  assert.ok(marker.popup().children.some(x=>x.textContent.includes('Brak kodu 35 nie oznacza')));
 }
 now+=301000;[...intervals.values()][0].fn();
 assert.ok(created[start].options.icon.html.className.includes('ship-military'));
 assert.ok(created[start].options.icon.html.className.includes('ship-old'));
 const metadataRefresh=[...timers.entries()].find(([,x])=>x.ms===10000);timers.delete(metadataRefresh[0]);metadataRefresh[1].fn();
 const updated={...records[8],type_code:35,position_at:new Date(now).toISOString()};
 pending.shift().resolve({ok:true,json:async()=>({items:[updated],status:'ready',stale:false})});await settle();
 assert.ok(created[start+8].options.icon.html.className.includes('ship-military'));
 assert.ok(!created[start+8].options.icon.html.className.includes('ship-old'));
 ui.sync({visible:false});assert.equal(controls['ships-map-legend'].hidden,true);
 console.log('Ships UI lifecycle and AIS classification passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
