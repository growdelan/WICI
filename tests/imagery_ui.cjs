const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function harness() {
  const elements = new Map(), requests = [], listeners = {};
  const element = tag => ({tag,children:[],checked:false,disabled:false,hidden:false,textContent:'',classList:{toggle(){}},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(name,fn){this[name]=fn;},focus(){},scrollIntoView(){}});
  const document = {hidden:false,createElement:element,getElementById(id){if(!elements.has(id))elements.set(id,element('div'));return elements.get(id);},addEventListener(name,fn){listeners[name]=fn;}};
  const group = {layers:[],addTo(){return this;},clearLayers(){this.layers=[];}};
  const layer = (bounds,options) => ({bounds,options,bindPopup(content){this.popup=content;return this;},bindTooltip(content){this.tooltip=content;return this;},addTo(target){target.layers.push(this);return this;}});
  const container = {addEventListener(name,fn,capture){this[name]=fn;this.capture=capture;}};
  const map = {handlers:{click(event){container.click({button:0,stopPropagation(){},...event,target:event.originalEvent?.target || {closest:()=>null}});}},getContainer:()=>container,mouseEventToLatLng:event=>event.latlng,getCenter(){return {lat:50.4,lng:16.6};},closePopup(){this.closed=(this.closed||0)+1;}};
  // Model native capture before Leaflet's SVG path click handler opens its bound popup.
  function clickLayer(item) {
    const classes = new Set(['leaflet-interactive', ...(item.options.className || '').split(/\s+/)]);
    const target = {closest:selectors=>selectors.split(',').some(selector=>classes.has(selector.trim().slice(1))) ? target : null};
    let stopped = false;
    container.click({button:0,target,latlng:map.getCenter(),stopPropagation(){stopped=true;}});
    if (!stopped) map.popup = item.popup;
    return stopped;
  }
  const window = {};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/imagery.js','utf8'),{window,document,URL,Date,Intl,L:{layerGroup:()=>group,circleMarker:layer,rectangle:layer}});
  window.WiciImagery.init({map,api:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject})),visible:true});
  const control = name=>document.getElementById('imagery-'+name);
  return {window,document,control,map,group,requests,listeners,container,clickLayer};
}
const flush = () => new Promise(resolve=>setImmediate(resolve));
const data = () => ({enabled:true,status:'ready',fetched_at:'2024-09-27T12:00:00Z',providers:[{source:'Copernicus EMS',status:'error',message:'Błąd katalogu'}],items:[{id:'cems-abc',title:'Zdjęcie <test>',source:'Copernicus EMS',source_url:'https://mapping.emergency.copernicus.eu/activations/EMSR756/',kind:'mapping',acquired_at:'2024-09-27T10:00:00Z',product_at:'2024-09-28T10:00:00Z',preview_url:'/api/imagery/preview/cems-abc',bounds:[[50,16],[51,17]],attribution:'© European Union, Copernicus EMS',license:'Copernicus EMS'}]});
const text = node => [node.textContent,...node.children.map(text)].join(' ');
function enable(h){h.control('enabled').checked=true;h.control('enabled').change();}

test('default off and enabling do not fetch; only deliberate point or center searches', async()=>{
 const h=harness();assert.equal(h.requests.length,0);enable(h);assert.equal(h.requests.length,0);assert.equal(h.control('center').disabled,false);
 h.control('center').click();assert.equal(h.requests[0].url,'/imagery?lat=50.4&lon=16.6');
 h.requests[0].resolve(data());await flush();assert.equal(h.group.layers.length,2);assert.match(text(h.control('gallery')),/Zdjęcie <test>.*Copernicus EMS/);
 assert.match(text(h.control('providers')),/Błąd katalogu/);assert.match(text(h.control('gallery')),/Wykonanie zobrazowania.*Publikacja produktu/);
 const preview=h.control('gallery').children[0].children.find(n=>n.tag==='a' && n.href==='https://mapping.emergency.copernicus.eu/activations/EMSR756/');
 assert.equal(preview.target,'_blank');assert.match(preview.textContent,/materiał źródłowy/);
 assert.equal(h.control('gallery').children[0].children.filter(n=>n.tag==='a').length,1,'Copernicus has one source link');
 const image=preview.children.find(n=>n.tag==='img');assert.equal(image.src,'/api/imagery/preview/cems-abc');
 const popup=h.group.layers[1].popup();
 assert.ok(popup.children.some(n=>n.tag==='a' && n.href===preview.href && n.target==='_blank'),'footprint popup also opens the source product');
 const button=h.group.layers[0].popup.children.find(n=>n.tag==='button');button.click();assert.equal(h.document.getElementById('layer-panel').open,true);
});

test('out of order replies and disable cannot resurrect earlier place or gallery',async()=>{
 const h=harness();enable(h);h.map.handlers.click({latlng:{lat:50,lng:16}});h.map.handlers.click({latlng:{lat:51,lng:17}});
 h.requests[1].resolve(data());await flush();h.requests[0].resolve({...data(),items:[]});await flush();assert.match(h.control('status').textContent,/Znaleziono materiałów: 1/);
 h.map.handlers.click({latlng:{lat:52,lng:18}});h.control('enabled').checked=false;h.control('enabled').change();h.requests[2].resolve(data());await flush();assert.equal(h.group.layers.length,0);assert.equal(h.control('gallery').children.length,0);
});

test('hidden view and hidden browser invalidate pending replies without automatic searches',async()=>{
 const h=harness();enable(h);h.control('center').click();h.window.WiciImagery.sync({visible:false});h.requests[0].resolve(data());await flush();assert.equal(h.group.layers.length,0);
 h.window.WiciImagery.sync({visible:true});assert.equal(h.requests.length,1);assert.equal(h.group.layers.length,1);h.control('center').click();
 h.document.hidden=true;h.listeners.visibilitychange();h.requests[1].resolve(data());await flush();assert.equal(h.group.layers.length,0);
 h.document.hidden=false;h.listeners.visibilitychange();assert.equal(h.requests.length,2);assert.equal(h.control('gallery').children.length,0);
});

test('cached gallery restores after hiding, health sync causes no requests, unsafe image/link rejected',async()=>{
 const h=harness();enable(h);h.control('center').click();const result=data();result.items[0].preview_url='https://evil.example/image.jpg';result.items[0].source_url='javascript:alert(1)';result.items[0].acquired_at=null;
 h.requests[0].resolve(result);await flush();const article=h.control('gallery').children[0];assert.ok(!article.children.some(n=>['img','a'].includes(n.tag)));assert.match(text(article),/Data nieudostępniona/);
 h.window.WiciImagery.sync({visible:false});h.window.WiciImagery.sync({visible:true});h.window.WiciImagery.sync({visible:true});assert.equal(h.requests.length,1);assert.equal(h.control('gallery').children.length,1);
});

test('provider empty and request error retain honest state and allow deliberate retry',async()=>{
 const h=harness();enable(h);h.control('center').click();h.requests[0].resolve({enabled:true,status:'empty',items:[],providers:[{source:'Copernicus EMS',status:'empty',message:'Brak pokrycia'}]});await flush();assert.match(h.control('status').textContent,/Brak materiałów/);assert.match(text(h.control('providers')),/Brak pokrycia/);
 h.control('center').click();h.requests[1].reject(new Error('Awaria'));await flush();assert.match(h.control('status').textContent,/Awaria/);assert.equal(h.control('gallery').children.length,0);h.control('center').click();assert.equal(h.requests.length,3);
});


test('footprint details and controls do not select; province polygons remain selectable', async()=>{
 const h=harness();enable(h);
 h.map.handlers.click({latlng:{lat:50,lng:16},originalEvent:{target:{closest:selector=>selector.includes('.imagery-footprint') ? {} : null}}});
 h.map.handlers.click({latlng:{lat:50,lng:16},originalEvent:{target:{closest:()=>({})}}});
 assert.equal(h.requests.length,0);
 h.map.handlers.click({latlng:{lat:50,lng:16},sourceTarget:{getPopup:()=>({})}});
 h.requests[0].resolve(data());await flush();assert.equal(h.group.layers[1].options.fill,false);
});


test('disabled imagery leaves normal map popups untouched',()=>{
 const h=harness();h.map.handlers.click({latlng:{lat:50,lng:16},sourceTarget:{getPopup:()=>({})}});assert.equal(h.map.closed,undefined);assert.equal(h.requests.length,0);
});


test('native capture makes point picking exclusive and ignores completed drag clicks',()=>{
 const h=harness();enable(h);assert.equal(h.container.capture,true);
 let stopped=false;h.map.handlers.click({latlng:{lat:50,lng:16},stopPropagation(){stopped=true;}});assert.equal(stopped,true);assert.equal(h.requests.length,1);
 h.map.dragging={moved:()=>true};h.map.handlers.click({latlng:{lat:51,lng:17}});assert.equal(h.requests.length,1);
});

test('selected SVG point opens its popup and gallery without searching again',async()=>{
 const h=harness();enable(h);h.control('center').click();h.requests[0].resolve(data());await flush();
 const marker=h.group.layers[0], requestCount=h.requests.length, closed=h.map.closed;
 assert.equal(h.clickLayer(marker),false,'capture must let Leaflet receive the SVG marker click');
 assert.equal(h.map.popup,marker.popup,'Leaflet can open the bound popup');
 assert.equal(h.requests.length,requestCount,'marker click must not issue another search');
 assert.equal(h.group.layers[0],marker,'marker and existing results must remain attached');
 assert.equal(h.map.closed,closed,'marker click must not close its popup');
 const button=h.map.popup.children.find(item=>item.tag==='button');
 assert.equal(button.textContent,'Pokaż materiały i stan źródeł');
 button.click({stopPropagation(){}});
 assert.equal(h.document.getElementById('layer-panel').open,true);
 assert.equal(h.document.getElementById('imagery-group').open,true);
 assert.equal(h.requests.length,requestCount,'opening the gallery must reuse the current results');
});

test('Copernicus thumbnail and popup open the source product instead of the small preview',async()=>{
 const h=harness();enable(h);h.control('center').click();
 const result=data(), item=result.items[0];
 Object.assign(item,{source:'Copernicus EMS',kind:'mapping',source_url:'https://mapping.emergency.copernicus.eu/activations/EMSR756/',preview_url:'/api/imagery/preview/cems-abc'});
 h.requests[0].resolve(result);await flush();
 const article=h.control('gallery').children[0], links=article.children.filter(n=>n.tag==='a');
 assert.equal(links.length,1);
 assert.equal(links[0].href,item.source_url);
 assert.equal(links[0].target,'_blank');
 assert.match(links[0].textContent,/materiał źródłowy/);
 assert.doesNotMatch(links[0].textContent,/duży podgląd/);
 assert.equal(links[0].children.find(n=>n.tag==='img').src,item.preview_url,'only the inline thumbnail uses the local image');
 const popupLinks=h.group.layers[1].popup().children.filter(n=>n.tag==='a');
 assert.equal(popupLinks.length,1);assert.equal(popupLinks[0].href,item.source_url);
 assert.equal(h.requests.length,1);
});

test('outside click during search preserves valid point and pending results',async()=>{
 const h=harness();h.window.WiciRegion={contains:(lat,lon)=>lon<18};enable(h);h.control('center').click();
 h.map.handlers.click({latlng:{lat:52,lng:21}});assert.equal(h.requests.length,1);h.requests[0].resolve(data());await flush();assert.match(h.control('location').textContent,/16.60000/);assert.equal(h.group.layers.length,2);
});
for(const failed of [false,true])test(`region switch invalidates pending imagery ${failed?'failure':'success'} without clobbering new request`,async()=>{
 const h=harness();let west=true;h.window.WiciRegion={contains:(lat,lon)=>west?lon<18:lon>20};enable(h);h.control('center').click();const old=h.requests[0];west=false;h.listeners['wici:regionchange']();assert.equal(h.group.layers.length,0);assert.equal(h.control('location').textContent,'Nie wybrano miejsca.');
 h.map.getCenter=()=>({lat:52.23,lng:21.01});h.control('center').click();if(failed)old.reject(Error('old error'));else old.resolve(data());await flush();assert.match(h.control('status').textContent,/Wyszukiwanie/);assert.equal(h.control('gallery').children.length,0);
 h.requests[1].resolve(data());await flush();assert.match(h.control('location').textContent,/21.01000/);assert.equal(h.control('gallery').children.length,1);
});
test('completed imagery is cleared outside scope and cannot resurrect on returning or hiding',async()=>{
 const h=harness();let inside=true;h.window.WiciRegion={contains:()=>inside};enable(h);h.control('center').click();h.requests[0].resolve(data());await flush();inside=false;h.listeners['wici:regionchange']();
 assert.equal(h.group.layers.length,0);assert.equal(h.control('gallery').children.length,0);assert.equal(h.control('providers').children.length,0);assert.ok(h.control('results').hidden);
 inside=true;h.listeners['wici:regionchange']();h.window.WiciImagery.sync({visible:false});h.window.WiciImagery.sync({visible:true});assert.equal(h.group.layers.length,0);assert.equal(h.requests.length,1);
});
test('region expansion preserves valid imagery point and pending response',async()=>{
 const h=harness();h.window.WiciRegion={contains:()=>true};enable(h);h.control('center').click();h.listeners['wici:regionchange']();h.requests[0].resolve(data());await flush();assert.equal(h.group.layers.length,2);assert.equal(h.control('gallery').children.length,1);
});
