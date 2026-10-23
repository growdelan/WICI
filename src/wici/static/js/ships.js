'use strict';
window.WiciShips = (() => {
  const $ = id => document.getElementById(`ships-${id}`);
  const node = (tag, text) => {const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  const REFRESH_MS=10000, MAX_AGE=900, OLD_AGE=300;
  let map, health={}, visible=false, layer, data, timer=null, ageTimer=null, request=null, generation=0;
  const markers=new Map();
  const shown=()=>Boolean(map)&&visible&&!document.hidden&&health.mode==='live'&&$('enabled').checked;
  const age=item=>{const time=Date.parse(item.position_at);return Number.isFinite(time)?Math.max(0,(Date.now()-time)/1000):Infinity;};
  const number=(value,unit)=>Number.isFinite(value)?`${Math.round(value*10)/10} ${unit}`:'Brak danych';
  const bearing=value=>Number.isFinite(value)&&value>=0&&value<360;
  const AIS_WARNING='Brak kodu 35 nie oznacza, że jednostka jest cywilna. Klasyfikacja opiera się na deklarowanym typie AIS, nie na potwierdzonej przynależności.';
  const CIVIL_TYPES=new Set([20,21,22,23,24,29,30,31,32,33,34,36,37,40,41,42,43,44,49,50,52,53,54,
    60,61,62,63,64,69,70,71,72,73,74,79,80,81,82,83,84,89]);
  function classification(item){
    const code=item.type_code;
    if(code===35)return {key:'military',label:'Wojskowe według AIS (kod 35)'};
    if(Number.isInteger(code)&&CIVIL_TYPES.has(code))return {key:'civilian',label:'Typ cywilny według AIS'};
    return {key:'unclassified',label:'Nieustalone'};
  }
  function status(message,warning=false){$('status').textContent=message;$('status').classList.toggle('notice',warning);}
  function renderStatus(){
    if(!data)return;
    const old=[...markers.values()].filter(marker=>age(marker.ship)>OLD_AGE).length;
    const phase=data.status==='connecting'?' · łączenie i zbieranie pozycji':data.status==='disabled'?' · źródło niedostępne':'';
    status(`Statki: ${markers.size}${old?` · ${old} pozycji starszych niż 5 min`:''}${phase} · odświeżanie co 10 s${data.stale?' · dane nieaktualne':''}${data.message?` · ${data.message}`:''}`,data.stale||data.status==='error'||data.status==='disabled');
  }
  function popup(marker){
    const item=marker.ship;
    if(!marker.popupView){
      const box=node('div');box.className='map-popup';
      const heading=node('strong'),list=node('dl'),source=node('small'),warning=node('small',AIS_WARNING);
      box.append(heading,list,source,warning);
      marker.popupView={box,heading,list,source,values:[]};
    }
    const view=marker.popupView;
    view.heading.textContent=item.name||`Statek ${item.mmsi}`;
    const fields=[
      ['MMSI',item.mmsi],['IMO',item.imo||'Brak danych'],['Klasyfikacja AIS',classification(item).label],['Typ AIS (kod)',item.type_code??'Brak danych'],
      ['Prędkość',number(item.speed_knots,'w.')],['Kurs nad dnem',number(item.course,'°')],
      ['Kierunek dziobu',number(item.heading,'°')],['Cel podróży',item.destination||'Brak danych'],
      ['Wiek pozycji',`${Math.floor(age(item)/60)} min ${Math.floor(age(item)%60)} s`]
    ];
    fields.forEach(([label,value],index)=>{
      if(!view.values[index]){const entry=node('dd');view.list.append(node('dt',label),entry);view.values.push(entry);}
      view.values[index].textContent=value;
    });
    view.source.textContent=`AISStream · ${age(item)>OLD_AGE?'pozycja starsza niż 5 min · ':''}${data?.stale?'ostatni odczyt; odświeżanie niedostępne':'niepełne pokrycie AIS'}`;
    if(window.WiciTracking&&!view.tracking){
      view.tracking=window.WiciTracking.button('ship',()=>marker.ship);view.box.append(view.tracking);
    }
    return view.box;
  }
  function icon(item,{referenceAt=Date.now(),className='',selected=false}={}){
    const positionAt=Date.parse(item.position_at),old=!Number.isFinite(positionAt)||(referenceAt-positionAt)/1000>OLD_AGE;
    const wrap=node('span');wrap.className=`ship-symbol ship-${classification(item).key}${old?' ship-old':''}`;
    const direction=bearing(item.heading)?item.heading:bearing(item.course)?item.course:null;
    if(direction===null)wrap.className+=' ship-direction-unknown';
    wrap.style.transform=`rotate(${direction??0}deg)`;
    return L.divIcon({className:`ship-marker ${className}${selected?' analysis-transport-selected':''}`.trim(),html:wrap,iconSize:[24,28],iconAnchor:[12,14]});
  }
  function render(){
    if(!shown())return;
    if(!layer){layer=L.layerGroup();layer.addTo(map);}
    const live=new Set();
    for(const item of data?.items||[]){
      if(window.WiciRegion&&!window.WiciRegion.contains(item.latitude,item.longitude))continue;
      if(!item.mmsi||!Number.isFinite(item.latitude)||!Number.isFinite(item.longitude)||age(item)>MAX_AGE)continue;
      const key=String(item.mmsi);live.add(key);
      let marker=markers.get(key);
      if(!marker){
        marker=L.marker([item.latitude,item.longitude],{pane:'shipPositions',icon:icon(item),title:item.name||`Statek ${key}`,bubblingMouseEvents:false});
        marker.bindPopup(()=>popup(marker));
        marker.bindTooltip(()=>node('span',`${marker.ship.name||`Statek ${marker.ship.mmsi}`} · ${classification(marker.ship).label}`));
        marker.addTo(layer);markers.set(key,marker);
      }else marker.setLatLng([item.latitude,item.longitude]).setIcon(icon(item));
      marker.ship=item;marker.shipOld=age(item)>OLD_AGE;
      if(marker.isPopupOpen())popup(marker);
    }
    for(const [key,marker]of markers)if(!live.has(key)){layer.removeLayer(marker);markers.delete(key);}
    renderStatus();
  }
  function tick(){
    if(!shown())return;
    for(const [key,marker]of markers){
      if(age(marker.ship)>MAX_AGE){layer.removeLayer(marker);markers.delete(key);}
      else{
        const old=age(marker.ship)>OLD_AGE;
        if(old!==marker.shipOld){marker.setIcon(icon(marker.ship));marker.shipOld=old;}
        if(marker.isPopupOpen())popup(marker);
      }
    }
    renderStatus();
  }
  async function load(){
    if(!shown()||request)return;
    const run=generation,controller=new AbortController();request=controller;
    const timeout=setTimeout(()=>controller.abort(),10000);
    if(!data)status('Łączenie ze strumieniem AISStream; pozycje będą pojawiać się stopniowo…');
    try{
      const response=await (window.WiciRegion?.fetch || fetch)('/api/ships',{signal:controller.signal});
      if(!response.ok)throw new Error('Nieudany odczyt');
      const result=await response.json();
      if(run!==generation||!shown())return;
      if(!Array.isArray(result.items))throw new Error('Nieprawidłowa odpowiedź');
      data=result;render();
    }catch{
      if(run!==generation||!shown())return;
      data={...(data||{items:[]}),stale:true,status:'error',message:'Nie udało się odświeżyć danych. Ponowna próba za 10 s.'};render();
    }finally{
      clearTimeout(timeout);if(request===controller)request=null;
      if(run===generation&&shown())timer=setTimeout(()=>{timer=null;load();},REFRESH_MS);
    }
  }
  function sync(options={}){
    if(options.visible!==undefined)visible=options.visible;
    if(options.health)health=options.health;
    $('enabled').disabled=health.mode!=='live';
    $('map-legend').hidden=!shown();
    if(!shown()){
      generation++;request?.abort();request=null;clearTimeout(timer);timer=null;clearInterval(ageTimer);ageTimer=null;
      if(layer)map.removeLayer(layer);layer=null;markers.clear();
      status(health.mode==='demo'?'Statki wyłączone w demonstracji.':$('enabled').checked?'Statki wstrzymane poza widoczną mapą.':'Warstwa statków wyłączona.');return;
    }
    if(ageTimer===null)ageTimer=setInterval(tick,1000);
    if(timer===null&&!request)load();
  }
  function init(options){
    if(map||!options.map)return;
    map=options.map;health=options.health||{};
    map.createPane('shipPositions').style.zIndex='610';
    map.attributionControl.addAttribution('<a href="https://aisstream.io/" target="_blank" rel="noopener noreferrer">AISStream</a>');
    $('enabled').addEventListener('change',()=>sync());
    $('baltic').addEventListener('click',()=>map.fitBounds([[53.4,9.4],[66,30.5]],{padding:[20,20]}));
  }
  document.addEventListener('wici:regionchange',()=>{if(map)render();});
  return {init,sync,classification,icon};
})();
