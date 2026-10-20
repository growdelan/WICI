const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const NOW = Date.parse('2026-10-17T12:00:00Z');
function harness(mode = 'live') {
  const elements = new Map(), requests = [], timers = new Map(), created = [], attributions = new Set();
  let clock = NOW, timerID = 0;
  const element = tag => ({tag,checked:false,hidden:false,open:false,value:'',textContent:'',children:[],dataset:{},classes:new Set(),
    classList:{toggle(){}},addEventListener(type,fn){this[type]=fn;},append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}},replaceChildren(...children){this.children=[];this.append(...children);},
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;},
    replaceWith(next){const parent=this.parentElement;if(parent){parent.children[parent.children.indexOf(this)]=next;next.parentElement=parent;this.parentElement=null;}},
    contains(target){return target===this||this.children.some(child=>child.contains(target));},querySelector(selector){return this.children.find(child=>child.tag===selector)||this.children.map(child=>child.querySelector(selector)).find(Boolean);},focus(){document.activeElement=this;}});
  const document = {hidden:false,activeElement:null,createElement:element,getElementById(id){if(!elements.has(id))elements.set(id,element('div'));return elements.get(id);}};
  const control = id => document.getElementById('ukraine-'+id);
  const map = {layers:new Set(),fits:[],panes:{},createPane(id){return this.panes[id]={style:{}};},removeLayer(layer){this.layers.delete(layer);},fitBounds(bounds,options){this.fits.push({bounds,options});},attributionControl:{addAttribution(value){attributions.add(value);},removeAttribution(value){attributions.delete(value);}}};
  function layer(kind,geo,options={}) {
    const item = {kind,geo,options,style:{...options.style,...options},
      bindPopup(content){this.popup=content;return this;},bindTooltip(content){this.tooltip=content;return this;},
      setPopupContent(content){this.popup=content;return this;},setTooltipContent(content){this.tooltip=content;return this;},
      setStyle(style){Object.assign(this.style,style);return this;},setLatLng(position){this.geo=position;return this;},addTo(m){m.layers.add(this);return this;}};
    created.push(item);return item;
  }
  const L = {geoJSON:(geo,options)=>layer('geometry',geo,options),circleMarker:(geo,options)=>layer('point',geo,options)};
  class ClockDate extends Date { constructor(...args){super(...(args.length?args:[clock]));} static now(){return clock;} }
  const window = {};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/ukraine.js','utf8'),{window,document,L,Intl,Date:ClockDate,AbortController,
    setTimeout(fn,delay){timers.set(++timerID,{fn,delay,type:'timeout'});return timerID;},clearTimeout(id){timers.delete(id);},
    setInterval(fn,delay){timers.set(++timerID,{fn,delay,type:'interval'});return timerID;},clearInterval(id){timers.delete(id);}});
  window.WiciUkraine.init({map,health:{mode},visible:true,api:(url,_body,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
  const points = () => [...map.layers].filter(item=>item.kind==='point');
  const alerts = () => [...map.layers].filter(item=>/ukraine.*Alerts/.test(item.options.pane));
  const runTimer = type => {const pair=[...timers].find(([,timer])=>timer.type===type);assert.ok(pair,`No ${type} timer`);if(type==='timeout')timers.delete(pair[0]);pair[1].fn();return pair[1].delay;};
  return {window,document,map,requests,timers,created,attributions,control,points,alerts,runTimer,advance(ms){clock+=ms;}};
}
const stamp = offset => new Date(NOW+(offset||0)).toISOString();
const ring = (x1,y1,x2,y2) => [[x1,y1],[x2,y1],[x2,y2],[x1,y2],[x1,y1]];
const feature = (key,geometry) => ({type:'Feature',properties:{key,region:key,rayon:key},geometry});
const collection = features => ({type:'FeatureCollection',features});
const geometry = () => ({status:'ready',fetched_at:stamp(),oblasts:collection([
  feature('same',{type:'Polygon',coordinates:[ring(23,44,32,52),ring(26,49,27,50)]}),
  feature('second',{type:'MultiPolygon',coordinates:[[ring(32,44,40,52)]]})]),
  raions:collection([feature('same',{type:'Polygon',coordinates:[ring(24,46,26,49)]})])});
const report = (id='one',overrides={}) => ({id,type:'uav',title:'Zgłoszenie drona',region:'Obwód',district:'Rejon',locality:'Miasto',latitude:48,longitude:30,updated_at:stamp(),status:'active',advisory:false,area_only:false,position_quality:'approximate',uncertainty_km:8,confidence:'medium',source_count:2,count:1,description:'Źródłowy tekst',...overrides});
const data = (overrides={}) => ({status:'ready',refresh_seconds:15,source_url:'https://neptun.in.ua/',alerts:{status:'ready',items:[{scope:'oblast',key:'same',name:'Obwód',level:'red',since:stamp(-600000),reasons:['тривога']}],fetched_at:stamp(),updated_at:stamp(-600000),stale:false},threats:{status:'ready',items:[report()],fetched_at:stamp(),server_time:stamp(),stale:false},...overrides});
const flush = () => new Promise(resolve=>setImmediate(resolve));
async function enable(h, value=data(), geo=geometry()) {
  h.control('enabled').checked=true;h.control('enabled').change();
  const calls=h.requests.slice(-2);assert.equal(calls[0].url,'/ukraine');assert.equal(calls[1].url,'/ukraine/geometry');
  calls[0].resolve(value);calls[1].resolve(geo);await flush();
}
const text = element => [element?.textContent||'',...(element?.children||[]).map(text)].join(' ');

test('opt-in layer adds verified geometry, reports, source attribution and frames only on enable',async()=>{
  const h=harness();assert.equal(h.requests.length,0);assert.equal(h.attributions.size,0);
  await enable(h);assert.ok(h.requests.every(call=>call.options.timeoutMs===35000));assert.equal(h.alerts().length,1);assert.equal(h.points().length,1);assert.equal(h.map.fits.length,1);
  assert.match([...h.attributions][0],/https:\/\/neptun.in.ua\//);
  assert.match(text(h.points()[0].popup),/8 km/);assert.match(text(h.points()[0].popup),/nie potwierdzone uderzenie/);
  assert.match(text(h.alerts()[0].popup),/тривога/);assert.match(h.control('status').textContent,/Odczyt alarmów/);
  const selected=h.points()[0], card=h.control('list').children[0];card.open=true;card.children[0].focus();
  h.runTimer('timeout');assert.equal(h.requests.length,3);h.requests[2].resolve(data());await flush();
  assert.equal(h.points()[0],selected);assert.equal(h.map.fits.length,1);assert.equal(h.control('list').children[0],card);assert.equal(card.open,true);assert.equal(h.document.activeElement,card.children[0]);
  h.control('fit').click();assert.equal(h.map.fits.length,2);
});

test('exact scope/key joins distinguish oblasts and raions; ambiguous or missing keys remain listed',async()=>{
  const h=harness(), value=data();value.alerts.items=[
    {scope:'oblast',key:'same',name:'Obwód',level:'red'}, {scope:'raion',key:'same',name:'Rejon',level:'yellow'},
    {scope:'raion',key:'missing',name:'Brak',level:'red'}, {scope:'district',key:'same',name:'Zły zakres',level:'red'}];
  await enable(h,value);assert.equal(h.alerts().length,2);
  assert.deepEqual(h.alerts().map(item=>item.options.pane).sort(),['ukraineOblastAlerts','ukraineRaionAlerts']);
  assert.equal(h.control('unmapped').hidden,false);assert.match(text(h.control('unmapped-alerts')),/Brak.*Zły zakres/);
  const duplicate=harness(), geo=geometry();geo.raions.features.push(geo.raions.features[0]);await enable(duplicate,value,geo);
  assert.equal(duplicate.alerts().length,1);
});

test('partial raion geometry still maps raion alerts while positions wait for Ukraine boundaries',async()=>{
  const h=harness(), value=data(), geo=geometry();geo.oblasts.features=[];geo.status='partial';value.alerts.items[0].scope='raion';
  await enable(h,value,geo);assert.equal(h.alerts().length,1);assert.equal(h.points().length,0);assert.match(text(h.control('list')),/Brak granic/);
});

test('geometry expires 24 hours after the backend fetch and maps new alert keys without recentering',async()=>{
  const h=harness(), hour=3600000, initial=geometry();initial.fetched_at=stamp(-23*hour);
  await enable(h,data(),initial);
  const oldBase=[...h.map.layers].find(layer=>layer.options.pane==='ukraineBorders');
  h.advance(hour-1);h.runTimer('timeout');
  assert.deepEqual(h.requests.slice(2).map(call=>call.url),['/ukraine']);
  h.requests[2].resolve(data());await flush();
  h.advance(1);h.runTimer('timeout');
  assert.deepEqual(h.requests.slice(3).map(call=>call.url),['/ukraine','/ukraine/geometry']);
  const next=data(), geo=geometry();next.alerts.fetched_at=stamp(hour);geo.fetched_at=stamp(hour);
  next.alerts.items=[{scope:'oblast',key:'new-oblast',name:'Nowy obwód',level:'red'},
    {scope:'raion',key:'new-raion',name:'Nowy rejon',level:'yellow'}];
  geo.oblasts.features[0].properties.key='new-oblast';geo.raions.features[0].properties.key='new-raion';
  h.requests[3].resolve(next);h.requests[4].resolve(geo);await flush();
  assert.deepEqual(h.alerts().map(layer=>layer.geo.properties.key),['new-oblast','new-raion']);
  assert.equal(h.control('unmapped').hidden,true);assert.equal(h.map.layers.has(oldBase),false);
  assert.equal(h.map.fits.length,1);
  h.advance(15000);h.runTimer('timeout');
  assert.deepEqual(h.requests.slice(5).map(call=>call.url),['/ukraine']);
  h.requests[5].resolve(next);await flush();
});

test('resuming after 25 hours refreshes geometry without fetching while hidden or disabled',async()=>{
  for(const pause of ['hidden','disabled']) {
    const h=harness();await enable(h);
    if(pause==='hidden')h.window.WiciUkraine.sync({visible:false});
    else {h.control('enabled').checked=false;h.control('enabled').change();}
    h.advance(25*3600000);assert.equal(h.requests.length,2);assert.equal(h.timers.size,0);
    if(pause==='hidden')h.window.WiciUkraine.sync({visible:true});
    else {h.control('enabled').checked=true;h.control('enabled').change();}
    assert.deepEqual(h.requests.slice(2).map(call=>call.url),['/ukraine','/ukraine/geometry']);
    const geo=geometry();geo.fetched_at=stamp(25*3600000);
    h.requests[2].resolve(data());h.requests[3].resolve(geo);await flush();
    assert.equal(h.alerts().length,1);assert.equal(h.map.fits.length,pause==='hidden'?1:2);
  }
});

test('failed geometry renewal preserves boundaries and retries until fresh geometry arrives',async()=>{
  const h=harness(), day=24*3600000;await enable(h);
  const oldBase=[...h.map.layers].find(layer=>layer.options.pane==='ukraineBorders');
  const current=data();current.alerts.fetched_at=stamp(day);
  h.advance(day);h.runTimer('timeout');
  assert.deepEqual(h.requests.slice(2).map(call=>call.url),['/ukraine','/ukraine/geometry']);
  h.requests[2].resolve(current);h.requests[3].reject(new Error('offline'));await flush();
  assert.equal(h.map.layers.has(oldBase),true);assert.equal(h.alerts().length,1);
  assert.match(h.control('status').textContent,/Nie udało się odczytać granic/);
  h.advance(15000);h.runTimer('timeout');
  assert.deepEqual(h.requests.slice(4).map(call=>call.url),['/ukraine','/ukraine/geometry']);
  const geo=geometry();geo.fetched_at=stamp(day+15000);
  h.requests[4].resolve(current);h.requests[5].resolve(geo);await flush();
  assert.equal(h.map.layers.has(oldBase),false);assert.equal(h.alerts().length,1);
  assert.doesNotMatch(h.control('status').textContent,/Nie udało się odczytać granic/);
});

test('geometry without a usable fetch timestamp is retried instead of cached indefinitely',async()=>{
  for(const fetched_at of [null,'invalid',stamp(120000)]) {
    const h=harness(), geo=geometry();geo.fetched_at=fetched_at;await enable(h,data(),geo);
    h.runTimer('timeout');
    assert.deepEqual(h.requests.slice(2).map(call=>call.url),['/ukraine','/ukraine/geometry']);
    h.requests[2].resolve(data());h.requests[3].resolve(geometry());await flush();
    assert.equal(h.alerts().length,1);
  }
});

test('area-only and unlocated reports stay on the list; advisory is neutral and holes/outside points excluded',async()=>{
  const h=harness(), value=data();value.threats.items=[
    report('area',{area_only:true}),report('outside',{latitude:52,longitude:19}),report('hole',{latitude:49.5,longitude:26.5}),
    report('advisory',{advisory:true}),report('unknown',{type:'unknown',longitude:34}),report('invalid',{latitude:NaN}),
    report('expired',{updated_at:stamp(-421000)}),report('future',{updated_at:stamp(120000)}),report('resolved',{status:'resolved'})];
  await enable(h,value);assert.equal(h.points().length,2);for(const point of h.points())assert.equal(point.style.fillColor,'#9baab3');
  assert.equal(h.control('list').children.length,9);assert.match(h.control('reports-count').textContent,/bez punktu: 7/);
  assert.match(text(h.control('list')),/Doniesienie obszarowe/);assert.match(text(h.control('list')),/poza geometrią Ukrainy/);
});

test('aging alone removes 7 minute positions and neutralizes stale alerts without claiming all-clear',async()=>{
  const h=harness(), value=data();value.threats.items=[report('aging',{updated_at:stamp(-410000)})];await enable(h,value);
  assert.equal(h.points().length,1);h.advance(15000);h.runTimer('interval');assert.equal(h.points().length,0);
  assert.equal(h.alerts()[0].style.color,'#b43642');h.advance(76000);h.runTimer('interval');
  assert.equal(h.alerts()[0].style.color,'#71818b');assert.match(h.control('status').textContent,/odczyt nieaktualny/);
  assert.match(h.control('status').textContent,/Brak oznaczeń nie oznacza braku zagrożenia/);
});

test('network failure neutralizes retained alerts, removes current points and backs off',async()=>{
  const h=harness();await enable(h);h.runTimer('timeout');h.requests[2].reject(new Error('offline'));await flush();
  assert.equal(h.alerts().length,1);assert.equal(h.alerts()[0].style.color,'#71818b');assert.equal(h.points().length,0);
  assert.match(h.control('status').textContent,/niepotwierdzony/);
  assert.equal([...h.timers.values()].find(timer=>timer.type==='timeout').delay,30000);
});

test('disable/hidden abort all requests and suppress late responses; resuming does not recenter',async()=>{
  const h=harness();h.control('enabled').checked=true;h.control('enabled').change();
  const late=h.requests.slice();h.window.WiciUkraine.sync({visible:false});
  assert.ok(late.every(call=>call.options.signal.aborted));assert.equal(h.timers.size,0);assert.equal(h.attributions.size,0);
  h.window.WiciUkraine.sync({visible:true});assert.equal(h.requests.length,4);
  late[0].resolve(data());late[1].resolve(geometry());await flush();assert.equal(h.map.layers.size,0);
  h.requests[2].resolve(data());h.requests[3].resolve(geometry());await flush();assert.equal(h.points().length,1);assert.equal(h.map.fits.length,1);
  h.control('enabled').checked=false;h.control('enabled').change();assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);assert.equal(h.attributions.size,0);
});

test('demo and unknown mode never fetch; health transitions stop live work',async()=>{
  for(const mode of ['demo','connecting']) {
    const h=harness(mode);h.control('enabled').checked=true;h.control('enabled').change();assert.equal(h.requests.length,0);assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);
  }
  const h=harness();await enable(h);h.window.WiciUkraine.sync({health:{mode:'demo'}});assert.equal(h.map.layers.size,0);assert.equal(h.timers.size,0);assert.match(h.control('status').textContent,/demonstracji/);
});

test('upstream stale feeds and invalid times never create fresh looking alerts or points',async()=>{
  const h=harness(), value=data();value.alerts.stale=true;value.threats.items[0].updated_at='invalid';await enable(h,value);
  assert.equal(h.alerts()[0].style.color,'#71818b');assert.equal(h.points().length,0);
  const missing=harness(), noDate=data();noDate.alerts.fetched_at=null;noDate.threats.fetched_at=null;await enable(missing,noDate);
  assert.equal(missing.alerts()[0].style.color,'#71818b');assert.equal(missing.points().length,0);
});

test('changed report updates preserve focused summary and restore the focused source link',async()=>{
  const h=harness();await enable(h);const card=h.control('list').children[0], summary=card.children[0];summary.focus();
  h.runTimer('timeout');const updated=data();updated.threats.items[0].description='Nowy opis';h.requests[2].resolve(updated);await flush();
  assert.equal(h.document.activeElement,summary);assert.match(text(card),/Nowy opis/);
  const link=card.children[1].querySelector('a');link.focus();h.runTimer('timeout');const next=data();next.threats.fetched_at=stamp(15000);h.requests[3].resolve(next);await flush();
  assert.equal(h.document.activeElement,card.children[1].querySelector('a'));assert.notEqual(h.document.activeElement,link);
});


test('map legend identifies Ukraine only while its live layer is active',async()=>{
  const h=harness();for(const id of ['legend','map-legend','map-label'])assert.equal(h.control(id).hidden,true);
  await enable(h);for(const id of ['legend','map-legend','map-label'])assert.equal(h.control(id).hidden,false);
  h.window.WiciUkraine.sync({visible:false});assert.equal(h.control('map-legend').hidden,true);assert.equal(h.control('map-label').hidden,true);
  h.window.WiciUkraine.sync({visible:true});assert.equal(h.control('map-legend').hidden,false);
  h.control('enabled').checked=false;h.control('enabled').change();assert.equal(h.control('map-legend').hidden,true);assert.equal(h.control('map-label').hidden,true);
  const demo=harness('demo');demo.control('enabled').checked=true;demo.control('enabled').change();assert.equal(demo.control('map-legend').hidden,true);assert.equal(demo.control('map-label').hidden,true);
});
