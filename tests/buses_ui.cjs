// Bus layer: line filtering, freshness, polling, and aborted sessions.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
let now=Date.now(),nextId=0,pending=[];
const timers=new Map(),intervals=new Map(),created=[];
class Element {
 constructor(){this.children=[];this.scrollTop=0;this.style={};this.textContent='';this.value='';this.checked=false;this.disabled=false;this.listeners={};this.classList={toggle(){}};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 addEventListener(event,callback){this.listeners[event]=callback;}
 focus(){doc.activeElement=this;}
}
const controls=Object.fromEntries(['enabled','status','line','city','focus','source','license','description'].map(name=>[`buses-${name}`,new Element()]));
const doc={hidden:false,activeElement:null,getElementById:id=>controls[id],createElement:()=>new Element()};
const attributions=new Set();
const map={createPane:()=>({style:{}}),attributionControl:{addAttribution(value){attributions.add(value);},removeAttribution(value){attributions.delete(value);}},removeLayer(layer){layer.removed=true;},fitBounds(bounds){this.bounds=bounds;}};
const L={layerGroup:()=>({addTo(){return this;},removeLayer(marker){marker.removed=true;}}),divIcon:options=>options,
 marker:(coords,options)=>{const marker={coords,options,opened:false,bindPopup(fn){this.popup=fn;return this;},bindTooltip(){return this;},addTo(){return this;},setLatLng(value){this.coords=value;return this;},setIcon(value){this.options.icon=value;if(this.opened)this.content=this.popup();return this;},isPopupOpen(){return this.opened;},getPopup(){return this.popupObject;},setPopupContent(value){this.content=value;return this;}};marker.popupObject={getElement:()=>({querySelector:()=>marker.content})};created.push(marker);return marker;}};
class ClockDate extends Date {static now(){return now;}}
const calls={init:[],sync:[],update:[],open:[]};
const trackingEvents=[];
const tracking=Object.fromEntries(Object.keys(calls).map(method=>[method,(...args)=>{calls[method].push(args);trackingEvents.push({method,args});}]));
const context={window:{WiciBuses3D:tracking},document:doc,L,Date:ClockDate,Number,Math,Map,Set,Boolean,String,AbortController,
 setTimeout(fn,ms){const id=++nextId;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
 setInterval(fn,ms){const id=++nextId;intervals.set(id,{fn,ms});return id;},clearInterval(id){intervals.delete(id);},
 fetch(url,options){assert.match(url,/^\/api\/buses\?city=(szczecin|krakow|poznan|warszawa)$/);return new Promise(resolve=>pending.push({url,resolve,signal:options.signal}));}};
vm.runInNewContext(fs.readFileSync('src/wici/static/js/buses.js','utf8'),context);
const ui=context.window.WiciBuses;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const item={id:'szczecin:3',line:'75',vehicle_number:'123',model:'Solaris',operator:'Operator',headsign:'Dworzec',latitude:53.4,longitude:14.5,speed_kmh:30,delay_seconds:-20,previous_stop:'Plac',next_stop:'Dworzec',low_floor:true,position_at:new Date(now-2000).toISOString()};
const payload=items=>({items,stale:false,status:'ready',enabled:true,refresh_seconds:10,message:''});
const respond=data=>({ok:true,json:async()=>data});
function poll(){const next=[...timers.entries()].find(([,x])=>x.ms===10000);assert.ok(next);timers.delete(next[0]);next[1].fn();}
function tick(){[...intervals.values()][0].fn();}
(async()=>{
 ui.init({map,health:{mode:'live'}});assert.equal(calls.init.length,1);assert.equal(calls.init[0][0].map,map);assert.equal(controls['buses-license'].textContent,' · CC0');assert.equal(controls['buses-focus'].textContent,'Pokaż Szczecin');ui.sync({visible:true});assert.equal(pending.length,0);
 controls['buses-enabled'].checked=true;controls['buses-enabled'].listeners.change();assert.equal(pending.length,1);
 pending.shift().resolve(respond(payload([item,{...item,id:'szczecin:4',line:'80'}])));await settle();assert.equal(created.length,2);
 assert.equal(calls.update.length,1);assert.equal(calls.update[0][1].city,'szczecin');assert.equal(calls.update[0][1].source.source,'ZDiTM Szczecin');
 assert.equal(calls.sync.at(-1)[0].enabled,true);assert.equal(calls.sync.at(-1)[0].city,'szczecin');assert.equal(calls.sync.at(-1)[0].line,'');
 assert.equal(created[0].options.icon.html.textContent,'75');assert.equal(created[0].options.icon.html.className,'buses-symbol');
 const texts=created[0].popup().children[1].children.map(x=>x.textContent);
 for(const value of ['Dworzec','123','Solaris','Operator','30 km/h','20 s przed rozkładem','2 s','Tak'])assert.ok(texts.includes(value),value);
 // Missing course or altitude must not prevent the external bus camera.
 const follow=created[0].popup().children.at(-1);
 assert.equal(follow.textContent,'Podążaj w 3D');assert.equal(follow.disabled,false);follow.listeners.click();
 assert.equal(calls.open.length,1);assert.equal(calls.open[0][0],item);assert.equal(calls.open[0][1],calls.update[0][0]);
 assert.equal(calls.open[0][2],follow);assert.equal(calls.open[0][3],created[0].getPopup());assert.equal(calls.open[0][4].city,'szczecin');
 // Reading lower fields and keyboard focus survive the age tick, setIcon popup
 // re-evaluation, and a new API snapshot. Keep every popup node stable.
 const reading=created[0];reading.opened=true;reading.content=reading.popup();reading.content.scrollTop=90;
 const originalContent=reading.content,originalValues=[...reading.content.children[1].children];follow.focus();
 now+=1000;tick();
 assert.equal(reading.content.scrollTop,90,'Age refresh must preserve the reading position');
 assert.equal(reading.content,originalContent);assert.equal(reading.content.children.at(-1),follow);assert.equal(doc.activeElement,follow);
 assert.ok(reading.content.children[1].children.some(node=>node.textContent==='3 s'));
 poll();pending.shift().resolve(respond(payload([{...item,model:'Solaris Urbino 18',delay_seconds:45},
  {...item,id:'szczecin:4',line:'80'}])));await settle();
 assert.equal(reading.content.scrollTop,90,'New vehicle data must preserve the reading position');
 assert.equal(reading.content,originalContent);assert.equal(reading.content.children.at(-1),follow);assert.equal(doc.activeElement,follow);
 originalValues.forEach((value,index)=>assert.equal(reading.content.children[1].children[index],value));
 const updated=reading.content.children[1].children.map(node=>node.textContent);
 assert.ok(updated.includes('Solaris Urbino 18'));assert.ok(updated.includes('45 s opóźnienia'));
 follow.listeners.click();assert.equal(calls.open.at(-1)[0].model,'Solaris Urbino 18','Stable button must follow the current report');
 assert.equal(calls.open.at(-1)[1],calls.update.at(-1)[0]);
 // Cached errors block following even with fresh coordinates; stale/error feed
 // reports are also forwarded to the existing shared renderer.
 for(const sourceState of [{stale:true},{status:'error'}]){
   poll();pending.shift().resolve(respond({...payload([item]),...sourceState}));await settle();
   assert.equal(follow.disabled,true);const previous=calls.open.length;follow.listeners.click();assert.equal(calls.open.length,previous);
   assert.equal(calls.update.at(-1)[0][Object.keys(sourceState)[0]],Object.values(sourceState)[0]);
 }
 poll();pending.shift().resolve(respond(payload([item,{...item,id:'szczecin:4',line:'80'}])));await settle();
 assert.equal(follow.disabled,false);
 const currentTime=now;now=Date.parse(item.position_at)+60000;tick();assert.equal(follow.disabled,false,'A position exactly 60 seconds old remains eligible');
 now++;tick();assert.equal(follow.disabled,true,'Eligibility expires immediately after 60 seconds');
 now=currentTime;tick();assert.equal(follow.disabled,false);
 reading.opened=false;
 controls['buses-line'].value='75';controls['buses-line'].listeners.change();assert.equal(created[1].removed,true);assert.match(controls['buses-status'].textContent,/1 \/ 2/);
 assert.equal(calls.sync.at(-1)[0].line,'75','Line scope reaches the renderer so unmatched targets can close');
 controls['buses-focus'].listeners.click();assert.equal(map.bounds[0][0],53.33);
 now+=60000;tick();assert.equal(created[0].options.icon.html.className,'buses-symbol buses-old');assert.match(controls['buses-status'].textContent,/starsze pozycje: 1/);
 assert.equal(reading.popup().children.at(-1).disabled,true);const expiredOpenCount=calls.open.length;follow.listeners.click();assert.equal(calls.open.length,expiredOpenCount,'An expired position cannot enter 3D through a retained button');
 poll();pending.shift().resolve({ok:false});await settle();assert.match(controls['buses-status'].textContent,/dane nieaktualne/);
 assert.equal(calls.update.at(-1)[0].stale,true);assert.equal(calls.update.at(-1)[0].status,'error');
 now+=60000;tick();assert.equal(created[0].removed,true);assert.match(controls['buses-status'].textContent,/Autobusy: 0/);
 poll();pending.shift().resolve(respond(payload([{...item,line:'80',position_at:new Date(now).toISOString()}])));await settle();
 assert.ok(controls['buses-line'].children.some(option=>option.value==='75'));assert.equal(controls['buses-line'].value,'75');
 controls['buses-line'].value='';controls['buses-line'].listeners.change();assert.equal(created.at(-1).options.icon.html.textContent,'80');
 poll();const old=pending.shift();ui.sync({visible:false});assert.equal(old.signal.aborted,true);assert.equal(timers.size,0);assert.equal(intervals.size,0);
 assert.equal(calls.sync.at(-1)[0].visible,false);
 ui.sync({visible:true});const current=pending.shift();old.resolve(respond(payload([item])));await settle();assert.equal(timers.size,1); // Only current request timeout; old request cannot schedule another poll.
 current.resolve(respond(payload([{...item,position_at:new Date(now).toISOString()}])));await settle();assert.equal(timers.size,1);
 doc.hidden=true;ui.sync();assert.equal(timers.size,0);assert.equal(intervals.size,0);
 assert.equal(calls.sync.at(-1)[0].hidden,true);assert.equal(calls.sync.at(-1)[0].visible,true);assert.equal(calls.sync.at(-1)[0].enabled,true,'Hidden document pauses tracking without disabling its session');
 doc.hidden=false;ui.sync({health:{mode:'demo'}});assert.equal(pending.length,0);assert.equal(controls['buses-enabled'].disabled,true);
 assert.equal(calls.sync.at(-1)[0].mode,'demo');
 ui.sync({health:{mode:'live'}});pending.shift().resolve(respond({...payload([]),enabled:false,message:'Wyłączone w konfiguracji.'}));await settle();
 assert.equal(timers.size,0);assert.equal(intervals.size,0);assert.equal(controls['buses-enabled'].disabled,false);assert.equal(controls['buses-city'].disabled,false);assert.equal(controls['buses-enabled'].checked,true);assert.equal(controls['buses-status'].textContent,'Wyłączone w konfiguracji.');
 assert.equal(calls.sync.at(-1)[0].enabled,false,'Backend disable closes tracking without trapping the enabled checkbox');
 ui.sync();assert.equal(pending.length,0);
 // A disabled provider never traps the controls or stops polling other cities.
 const selectCity=city=>{controls['buses-city'].value=city;controls['buses-city'].listeners.change();};
 selectCity('warszawa');assert.equal(pending[0].url,'/api/buses?city=warszawa');
 assert.equal(calls.sync.at(-1)[0].city,'warszawa');
 pending.shift().resolve(respond({...payload([]),enabled:false,message:'Brak klucza Warszawy.'}));await settle();
 assert.equal(controls['buses-status'].textContent,'Brak klucza Warszawy.');assert.equal(timers.size,0);
 assert.equal(controls['buses-city'].disabled,false);assert.equal(controls['buses-enabled'].checked,true);
 selectCity('krakow');assert.equal(pending[0].url,'/api/buses?city=krakow');
 const krakowItem={...item,id:'krakow:A:3',line:'179',position_at:new Date(now).toISOString()};
 pending.shift().resolve(respond(payload([krakowItem])));await settle();
 assert.match(controls['buses-status'].textContent,/Kraków · Autobusy: 1/);assert.equal(intervals.size,1);
 assert.ok(created.at(-1).popup().children[2].textContent.startsWith('ZTP Kraków'));
 created.at(-1).popup().children.at(-1).listeners.click();assert.equal(calls.open.at(-1)[4].city,'krakow');assert.equal(calls.open.at(-1)[4].source.source,'ZTP Kraków');
 assert.equal(controls['buses-focus'].textContent,'Pokaż Kraków');assert.match(controls['buses-description'].textContent,/Dane przetworzone i ujednolicone przez WICI/);
 assert.equal(controls['buses-source'].textContent,'ZTP Kraków');assert.equal(controls['buses-source'].href,'https://gtfs.ztp.krakow.pl/');assert.equal(controls['buses-license'].textContent,'');
 assert.equal(attributions.size,1);assert.match([...attributions][0],/ZTP Kraków/);assert.doesNotMatch([...attributions][0],/ZDiTM/);
 controls['buses-focus'].listeners.click();assert.equal(map.bounds[0][0],49.94);
 controls['buses-line'].value='179';controls['buses-line'].listeners.change();
 // Ignore a former city's response even if it arrives while its JSON is being read.
 poll();let finishOldJson;const inJson=pending.shift();
 inJson.resolve({ok:true,json:()=>new Promise(resolve=>{finishOldJson=resolve;})});await settle();
 selectCity('poznan');assert.equal(inJson.signal.aborted,true);assert.equal(pending[0].url,'/api/buses?city=poznan');
 assert.equal(controls['buses-line'].value,'');assert.equal(controls['buses-line'].children.length,1);
 const beforeOldJson=calls.update.length;finishOldJson(payload([krakowItem]));await settle();assert.equal(timers.size,1);assert.equal(calls.update.length,beforeOldJson,'Old-city JSON cannot enter the renderer');
 assert.match(controls['buses-status'].textContent,/Wczytywanie autobusów: Poznań/);
 const poznanItem={...item,id:'poznan:3',line:'163',position_at:new Date(now).toISOString()};
 pending.shift().resolve(respond(payload([poznanItem])));await settle();
 assert.equal(created.at(-1).options.icon.html.textContent,'163');assert.match(controls['buses-status'].textContent,/Poznań · Autobusy: 1/);
 assert.equal(attributions.size,1);assert.match([...attributions][0],/ZTM Poznań/);assert.equal(controls['buses-focus'].textContent,'Pokaż Poznań');assert.match(controls['buses-description'].textContent,/Dane przetworzone i ujednolicone przez WICI/);
 controls['buses-focus'].listeners.click();assert.equal(map.bounds[0][0],52.28);
 // Ignore a response still awaiting headers after a city switch, too.
 poll();const previous=pending.shift();selectCity('warszawa');assert.equal(previous.signal.aborted,true);
 const warsaw=pending.shift();assert.equal(warsaw.url,'/api/buses?city=warszawa');
 const beforeOldHeaders=calls.update.length;previous.resolve(respond(payload([poznanItem])));await settle();assert.equal(timers.size,1);assert.equal(calls.update.length,beforeOldHeaders,'Old-city headers cannot enter the renderer');
 warsaw.resolve(respond(payload([{...item,id:'warszawa:3',line:'175',position_at:new Date(now).toISOString()}])));await settle();
 assert.equal(controls['buses-focus'].textContent,'Pokaż Warszawę');assert.match(controls['buses-status'].textContent,/Warszawa · Autobusy: 1/);assert.equal(timers.size,1);
 assert.ok(created.at(-1).popup().children[2].textContent.startsWith('Miasto Stołeczne Warszawa'));
 controls['buses-focus'].listeners.click();assert.equal(map.bounds[0][0],52.08);
 // Explicitly disabling a city is remembered independently of the other city.
 controls['buses-enabled'].checked=false;controls['buses-enabled'].listeners.change();
 assert.equal(calls.sync.at(-1)[0].enabled,false);
 selectCity('poznan');assert.equal(controls['buses-enabled'].checked,true);assert.equal(pending.length,1);
 pending.shift().resolve(respond(payload([poznanItem])));await settle();
 selectCity('warszawa');assert.equal(controls['buses-enabled'].checked,false);assert.equal(pending.length,0);
 assert.equal(timers.size,0);assert.equal(intervals.size,0);
 // An accepted report may change the same vehicle's line while the UI filter
 // stays selected. The 3D controller must receive its new report before a
 // scope sync closes it; syncing during the active request must not poll twice.
 selectCity('szczecin');const lineVehicle={...item,position_at:new Date(now).toISOString()};
 pending.shift().resolve(respond(payload([lineVehicle])));await settle();
 controls['buses-line'].value='75';controls['buses-line'].listeners.change();
 created.at(-1).popup().children.at(-1).listeners.click();
 assert.equal(calls.open.at(-1)[0].id,lineVehicle.id);assert.equal(calls.open.at(-1)[0].line,'75');
 const eventStart=trackingEvents.length;
 poll();const changedLine={...lineVehicle,line:'80',position_at:new Date(now+1000).toISOString()};
 pending.shift().resolve(respond(payload([changedLine])));await settle();
 const lineEvents=trackingEvents.slice(eventStart);
 assert.deepEqual(lineEvents.map(event=>event.method),['update','sync'],'A successful report must refresh selection and then apply the active filter');
 assert.equal(lineEvents[0].args[0].items[0].id,lineVehicle.id);assert.equal(lineEvents[0].args[0].items[0].line,'80');
 assert.equal(lineEvents[1].args[0].line,'75','3D receives the unmatched filter so it can close the modal');
 assert.equal(lineEvents[1].args[0].city,'szczecin');assert.equal(controls['buses-line'].value,'75');
 assert.match(controls['buses-status'].textContent,/Autobusy: 0 \/ 1/);
 assert.equal(pending.length,0,'The post-report scope sync must not start a second city read');
 assert.equal(timers.size,1,'Exactly the original poller schedules the next city read');
 console.log('Bus UI lifecycle passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
