const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function harness({reduced = false} = {}) {
  const elements = new Map(), requests = [], markers = [], circles = [], timeouts = new Map(), intervals = new Map(), frames = new Map(), listeners = {}, panes = new Map();
  let id = 0;
  const segments=[]; let origin;
  const context2d = {clearRect(){},beginPath(){},moveTo(x,y){origin=[x,y];},lineTo(x,y){segments.push({from:origin,to:[x,y]});},stroke(){}};
  function element(tag = 'div') {return {tag, children:[],style:{},checked:false,disabled:false,value:'0',textContent:'',classList:{toggle(){}},attributes:{},append(...items){this.children.push(...items);},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,fn){this[k]=fn;},getContext(){return context2d;}};}
  const document = {hidden:false,createElement:element,getElementById(name){if(!elements.has(name)) elements.set(name,element());return elements.get(name);},addEventListener(type,fn){listeners[type]=fn;}};
  document.getElementById('weather-mode').value='measurement';
  const group = {layers:[],clearLayers(){this.layers=[];},addTo(){return this;}};
  const map = {getSize(){return {x:800,y:600};},createPane(name){const pane=element();panes.set(name,pane);return pane;},getPane(name){return panes.get(name);},containerPointToLayerPoint(){return {x:0,y:0};},latLngToContainerPoint([lat,lon]){return {x:(lon-14)*70,y:(55-lat)*75};},handlers:{},on(types,fn){for(const type of types.split(' '))this.handlers[type]=fn;}};
  const layer = (latlng,options,list) => {const item={latlng,options,bindPopup(fn){this.popup=fn;return this;},bindTooltip(content){this.tooltip=content;return this;},addTo(target){target.layers.push(this);list.push(this);return this;}};return item;};
  const L = {layerGroup(){return group;},divIcon(options){return options;},marker(latlng,options){return layer(latlng,options,markers);},circleMarker(latlng,options){return layer(latlng,options,circles);},DomUtil:{setPosition(){}}};
  const window = {matchMedia(){return {matches:reduced};}};
  const ctx = vm.createContext({window,document,L,URL,Intl,Date,console,setTimeout(fn,ms){timeouts.set(++id,{fn,ms});return id;},clearTimeout(id){timeouts.delete(id);},setInterval(fn,ms){intervals.set(++id,{fn,ms});return id;},clearInterval(id){intervals.delete(id);},requestAnimationFrame(fn){frames.set(++id,fn);return id;},cancelAnimationFrame(id){frames.delete(id);}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/wici/static/js/weather.js'),'utf8'),ctx);
  const api = url => new Promise((resolve,reject)=>requests.push({url,resolve,reject}));
  const control = name => document.getElementById('weather-'+name);
  window.WiciWeather.init({map,api,health:{mode:'live'}});
  return {window,document,control,requests,group,markers,circles,timeouts,intervals,frames,listeners,map,segments};
}
const flush = () => new Promise(resolve=>setImmediate(resolve));
function data(mode='measurement', samples) {
  return {mode,enabled:true,status:'ready',times:['2026-10-14T12:00:00Z','2026-10-14T13:00:00Z'],fetched_at:'2026-10-14T12:00:00Z',refresh_seconds:mode==='forecast'?3600:600,precipitation_period_minutes:mode==='forecast'?60:10,source_url:'https://example.com/',points:[{name:'Stacja <test>',latitude:52,longitude:19,samples:samples || [{time:'2026-10-14T12:00:00Z',wind_speed_kmh:20,wind_direction_deg:270,precipitation_mm:2},{time:'2026-10-14T13:00:00Z',wind_speed_kmh:60,wind_direction_deg:0,precipitation_mm:10}]}]};
}
async function enable(h,mode='measurement') {
  h.control('mode').value=mode;
  if(mode==='forecast')h.control('mode').change();
  h.control('wind').checked=true;h.control('wind').change();
  assert.equal(h.requests.at(-1).url,`/weather?mode=${mode}`);
  h.requests.at(-1).resolve(data(mode));await flush();
}
function textOf(node){return [node.textContent,...node.children.map(textOf)].join(' ');}

test('weather defaults off; western wind arrow and animation travel east, zero remains calm',async()=>{
  const h=harness();assert.equal(h.requests.length,0);
  assert.equal(h.window.WiciWeather.helpers.toDirection(270),90);
  assert.equal(h.window.WiciWeather.helpers.toDirection(0),180);
  await enable(h);
  assert.equal(h.group.layers[0].options.icon.html.style.transform,'rotate(90deg)');
  h.control('animation').checked=true;h.control('animation').change();
  const frame=[...h.frames.entries()][0];h.frames.delete(frame[0]);frame[1](1000);
  assert.ok(h.segments[0].to[0]>h.segments[0].from[0]);
  assert.ok(Math.abs(h.segments[0].to[1]-h.segments[0].from[1])<1e-9);
  assert.match(textOf(h.group.layers[0].popup()),/20 km\/h/);
  assert.match(textOf(h.group.layers[0].popup()),/270° z · 90° do/);
  const calm=harness();calm.control('wind').checked=true;calm.control('wind').change();
  calm.requests[0].resolve(data('measurement',[{wind_speed_kmh:0,wind_direction_deg:null,precipitation_mm:0}]));await flush();
  assert.equal(calm.group.layers[0].options.icon.html.textContent,'○');
  assert.match(textOf(calm.group.layers[0].popup()),/0 km\/h/);
});

test('missing speed and missing direction do not create a wind vector; rain remains separate',async()=>{
  const h=harness();h.control('wind').checked=true;h.control('rain').checked=true;h.control('wind').change();
  const result=data();result.points.push({name:'Brak prędkości',latitude:53,longitude:20,samples:[{wind_speed_kmh:null,wind_direction_deg:90,precipitation_mm:0}]});
  result.points[0].samples[0].wind_direction_deg=null;
  h.requests[0].resolve(result);await flush();
  assert.equal(h.markers.length,0);assert.equal(h.circles.length,1);
  assert.match(textOf(h.circles[0].popup()),/Brak kierunku/);
  assert.match(textOf(h.circles[0].popup()),/2 mm \/ 10 min/);
});

test('forecast slider changes vector, rain, timestamp and autoplay advances without more network calls',async()=>{
  const h=harness();h.control('rain').checked=true;await enable(h,'forecast');
  assert.equal(h.control('hour').max,1);assert.equal(h.control('hour').disabled,false);
  h.control('hour').value='1';h.control('hour').input();
  const vector=h.group.layers.find(l=>l.options.icon);
  assert.equal(vector.options.icon.html.style.transform,'rotate(180deg)');
  assert.match(textOf(vector.popup()),/60 km\/h/);assert.match(textOf(vector.popup()),/10 mm \/ 60 min/);
  assert.match(h.control('time').textContent,/15:00/);
  h.control('play').click();assert.equal(h.intervals.size,1);[...h.intervals.values()][0].fn();
  assert.equal(h.control('hour').value,0);assert.equal(h.requests.length,1);
  h.control('play').click();assert.equal(h.intervals.size,0);
});

test('hidden map cancels playback, motion and refresh; late response cannot resurrect layers',async()=>{
  const h=harness();h.control('animation').checked=true;await enable(h,'forecast');
  h.control('play').click();assert.equal(h.frames.size,1);assert.equal(h.timeouts.size,1);assert.equal(h.intervals.size,1);
  h.window.WiciWeather.sync({visible:false});
  assert.equal(h.group.layers.length,0);assert.equal(h.frames.size,0);assert.equal(h.timeouts.size,0);assert.equal(h.intervals.size,0);
  h.window.WiciWeather.sync({visible:true});assert.equal(h.requests.length,2);
  h.document.hidden=true;h.listeners.visibilitychange();h.requests[1].resolve(data('forecast'));await flush();
  assert.equal(h.group.layers.length,0);assert.equal(h.frames.size,0);assert.equal(h.timeouts.size,0);
  h.document.hidden=false;h.listeners.visibilitychange();assert.equal(h.requests.length,3);
  h.requests[2].resolve(data('forecast'));await flush();assert.ok(h.group.layers.length>0);
});

test('out of order measurement response cannot replace forecast or arm duplicate timers',async()=>{
  const h=harness();h.control('wind').checked=true;h.control('wind').change();
  h.control('mode').value='forecast';h.control('mode').change();assert.equal(h.requests.length,2);
  h.requests[1].resolve(data('forecast'));await flush();
  h.control('hour').value='1';h.control('hour').input();
  h.requests[0].resolve(data());await flush();
  assert.equal(h.group.layers[0].options.icon.html.style.transform,'rotate(180deg)');
  assert.equal(h.control('hour').disabled,false);assert.equal(h.timeouts.size,1);
  assert.equal([...h.timeouts.values()][0].ms,3600000);
});

test('refresh errors retain marked stale data and reduced motion suppresses continuous frames',async()=>{
  const h=harness({reduced:true});h.control('animation').checked=true;await enable(h);
  const frame=[...h.frames.entries()][0];h.frames.delete(frame[0]);frame[1](1000);assert.equal(h.frames.size,0);
  [...h.timeouts.values()][0].fn();h.requests[1].reject(new Error('awaria'));await flush();
  assert.ok(h.group.layers.length);assert.match(h.control('status').textContent,/nieaktualne.*awaria/);
  assert.match(textOf(h.group.layers[0].popup()),/nieaktualne/);
});


test('periodic health sync preserves existing weather layers and timers',async()=>{
  const h=harness();await enable(h);
  const marker=h.group.layers[0], timeout=[...h.timeouts.keys()][0];
  h.window.WiciWeather.sync({visible:true,health:{mode:'live',now:'2026-10-14T12:01:00Z'}});
  assert.equal(h.group.layers[0],marker);
  assert.equal([...h.timeouts.keys()][0],timeout);
  assert.equal(h.requests.length,1);
});


test('play from default off enables wind, switches to forecast and starts after loading',async()=>{
  const h=harness();h.control('play').click();
  assert.equal(h.control('wind').checked,true);
  assert.equal(h.control('mode').value,'forecast');
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/weather?mode=forecast');
  assert.equal(h.intervals.size,0);
  h.requests[0].resolve(data('forecast'));await flush();
  assert.equal(h.intervals.size,1);assert.match(h.control('play').textContent,/Wstrzymaj/);
  [...h.intervals.values()][0].fn();assert.equal(Number(h.control('hour').value),1);
  h.control('play').click();assert.equal(h.intervals.size,0);
});

test('play in measurement switches source; cancelling pending playback prevents late start',async()=>{
  const h=harness();await enable(h);h.control('play').click();
  assert.equal(h.requests.at(-1).url,'/weather?mode=forecast');
  h.control('play').click();h.requests.at(-1).resolve(data('forecast'));await flush();
  assert.equal(h.intervals.size,0);assert.equal(h.control('play').disabled,false);
  h.control('play').click();assert.equal(h.intervals.size,1);
});

test('forecast failure releases queued playback and permits retry',async()=>{
  const h=harness();h.control('play').click();
  h.requests[0].reject(new Error('awaria'));await flush();
  assert.equal(h.intervals.size,0);assert.match(h.control('status').textContent,/awaria/);
  assert.equal(h.control('play').disabled,false);
  h.control('play').click();assert.equal(h.requests.length,2);
  h.requests[1].resolve(data('forecast'));await flush();
  assert.equal(h.intervals.size,1);
});


test('map autopan retains weather popup but a new forecast frame closes old details',async()=>{
  const h=harness();await enable(h,'forecast');
  const popup={options:{},getElement(){return {querySelector(selector){return selector==='.weather-popup' ? {} : null;}};},openOn(map){this.opened=map;}};
  h.map.closePopup=point=>{h.map.closed=point;h.map.handlers.popupclose({popup:point});};
  h.group.clearLayers=()=>{h.group.layers=[];h.map.handlers.popupclose({popup});};
  h.map.handlers.popupopen({popup});h.map.handlers.moveend();
  assert.equal(popup.opened,h.map);assert.equal(popup.options.autoPan,false);
  h.map.handlers.popupopen({popup});h.control('hour').value=1;h.control('hour').input();
  assert.equal(h.map.closed,popup);
});

test('forecast region changes request scoped data and ignore previous region response',async()=>{
 const h=harness();let code='02';h.window.WiciRegion={code:()=>code,contains:()=>true};h.control('mode').value='forecast';h.control('mode').change();h.control('wind').checked=true;h.control('wind').change();
 assert.equal(h.requests[0].url,'/weather?mode=forecast&voivodeship=02');code='14';h.listeners['wici:regionchange']();assert.equal(h.requests[1].url,'/weather?mode=forecast&voivodeship=14');
 const fresh=data('forecast');fresh.points[0].name='Mazowieckie';h.requests[1].resolve(fresh);await flush();h.requests[0].resolve(data('forecast'));await flush();assert.match(textOf(h.group.layers[0].popup()),/Mazowieckie/);
 code='';h.listeners['wici:regionchange']();assert.equal(h.requests[2].url,'/weather?mode=forecast');
});
