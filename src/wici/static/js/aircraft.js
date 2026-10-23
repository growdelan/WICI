'use strict';
window.WiciAircraft = (() => {
  const $ = id => document.getElementById(`aircraft-${id}`);
  const node = (tag, text) => {const n=document.createElement(tag); if(text!=null)n.textContent=text; return n;};
  const REFRESH_MS = 10000;
  let map, health={}, visible=false, layer, data, timer=null, ageTimer=null, request=null, generation=0;
  const markers = new Map();
  const shown = () => Boolean(map) && visible && !document.hidden && health.mode==='live' && $('enabled').checked;
  const age = item => {const time=Date.parse(item.position_at); return Number.isFinite(time)?Math.max(0,(Date.now()-time)/1000):Infinity;};
  const number = (value, unit) => Number.isFinite(value)?`${Math.round(value).toLocaleString('pl-PL')} ${unit}`:'Brak danych';
  function status(message, warning=false){$('status').textContent=message; $('status').classList.toggle('notice',warning);}
  const canFollow = item => !data?.stale && age(item)<=30 && Number.isFinite(item.altitude_m);
  function popup(marker){
    const item=marker.aircraft;
    if(!marker.popupView){
      const box=node('div');box.className='map-popup';
      const heading=node('strong'),list=node('dl'),source=node('small');
      box.append(heading,list,source);
      marker.popupView={box,heading,list,source,values:[]};
    }
    const view=marker.popupView;
    view.heading.textContent=item.id||item.registration||'Samolot';
    const fields=[
      ['Identyfikator lotu',item.id||'Brak danych'], ['Rejestracja',item.registration||'Brak danych'],
      ['Typ',item.type_code||'Brak danych'], ['Wysokość barometryczna',number(item.altitude_m,'m')],
      ['Prędkość względem ziemi',number(item.speed_kmh,'km/h')], ['Wiek pozycji',number(age(item),'s')]
    ];
    fields.forEach(([label,value],index)=>{
      if(!view.values[index]){const entry=node('dd');view.list.append(node('dt',label),entry);view.values.push(entry);}
      view.values[index].textContent=value;
    });
    view.source.textContent=data?.stale?'adsb.fi · ostatni odczyt, odświeżanie niedostępne':'adsb.fi · znak wywoławczy może różnić się od numeru rejsu';
    if(window.WiciAircraft3D&&!view.follow){
      const button=node('button','Podążaj w 3D');button.type='button';
      button.addEventListener('click',()=>{
        if(!canFollow(marker.aircraft)){popup(marker);return;}
        window.WiciAircraft3D?.open(marker.aircraft,data,button,marker.getPopup());
      });
      view.follow=button;view.box.append(button);
    }
    if(view.follow)view.follow.disabled=!canFollow(item);
    if(window.WiciTracking&&!view.tracking){
      view.tracking=window.WiciTracking.button('aircraft',()=>marker.aircraft);
      view.box.append(view.tracking);
    }
    return view.box;
  }
  function icon(item,{className='',selected=false}={}){
    const wrap=node('span'); wrap.className=item.military===true?'aircraft-symbol aircraft-military':'aircraft-symbol';
    wrap.textContent='✈'; // Glyph points east; track is measured clockwise from north.
    wrap.style.transform=`rotate(${Number.isFinite(item.track)?item.track-90:-90}deg)`;
    return L.divIcon({className:`aircraft-marker ${className}${selected?' analysis-transport-selected':''}`.trim(),html:wrap,iconSize:[28,28],iconAnchor:[14,14]});
  }
  function render(){
    if(!shown())return;
    if(!layer){layer=L.layerGroup(); layer.addTo(map);}
    const live=new Set();
    for(const item of data?.items||[]){
      if(window.WiciRegion&&!window.WiciRegion.contains(item.latitude,item.longitude))continue;
      if(!Number.isFinite(item.latitude)||!Number.isFinite(item.longitude)||age(item)>120)continue;
      live.add(item.hex);
      let marker=markers.get(item.hex);
      if(!marker){
        marker=L.marker([item.latitude,item.longitude],{pane:'aircraftPositions',icon:icon(item),
          title:item.id||item.registration||'Samolot',bubblingMouseEvents:false});
        marker.aircraft=item;
        marker.bindPopup(()=>popup(marker));
        marker.bindTooltip(()=>node('span',marker.aircraft.id||marker.aircraft.registration||'Samolot'));
        marker.addTo(layer); markers.set(item.hex,marker);
      }else{
        marker.aircraft=item;
        marker.setLatLng([item.latitude,item.longitude]).setIcon(icon(item));
      }
      // Keep popup nodes stable so periodic age/position updates retain button focus.
      if(marker.isPopupOpen())popup(marker);
    }
    for(const [hex,marker] of markers)if(!live.has(hex)){layer.removeLayer(marker);markers.delete(hex);}
    if(data)status(`Samoloty: ${markers.size} · odświeżanie co 10 s${data.stale?' · dane nieaktualne':''}${data.message?` · ${data.message}`:''}`,data.stale||data.status==='error');
  }
  function tick(){
    if(!shown())return;
    // Age continues to advance even if a network request fails.
    for(const [hex,marker] of markers){
      if(age(marker.aircraft)>120){layer.removeLayer(marker);markers.delete(hex);}
      else if(marker.isPopupOpen())popup(marker);
    }
    if(data)status(`Samoloty: ${markers.size} · odświeżanie co 10 s${data.stale?' · dane nieaktualne':''}${data.message?` · ${data.message}`:''}`,data.stale||data.status==='error');
  }
  async function load(){
    if(!shown()||request)return;
    const run=generation, controller=new AbortController(); request=controller;
    // Allow the backend's 10-second deadline to return its diagnostic response.
    const timeout=setTimeout(()=>controller.abort(),15000);
    if(!data)status('Wczytywanie samolotów adsb.fi…');
    try{
      const response=await (window.WiciRegion?.fetch || fetch)('/api/aircraft',{signal:controller.signal});
      if(!response.ok)throw new Error(`Lokalny serwer WICI zwrócił HTTP ${response.status}.`);
      const result=await response.json();
      if(run!==generation||!shown())return;
      if(!Array.isArray(result.items))throw new Error('Nieprawidłowa odpowiedź lokalnego serwera WICI.');
      data=result;window.WiciAircraft3D?.update(data);render();
    }catch(err){
      if(run!==generation||!shown())return;
      const reason=err.name==='AbortError'?'Lokalny serwer WICI nie odpowiedział w ciągu 15 s.'
        :err instanceof TypeError?'Brak połączenia z lokalnym serwerem WICI. Sprawdź, czy aplikacja działa.'
        :err instanceof SyntaxError?'Nieprawidłowa odpowiedź lokalnego serwera WICI.':err.message;
      data={...(data||{items:[]}),stale:true,status:'error',message:`${reason} Ponowna próba za 10 s.`};
      window.WiciAircraft3D?.update(data);
      render();
    }finally{
      clearTimeout(timeout);
      if(request===controller)request=null;
      if(run===generation&&shown())timer=setTimeout(()=>{timer=null;load();},REFRESH_MS);
    }
  }
  function sync(options={}){
    if(options.visible!==undefined)visible=options.visible;
    if(options.health)health=options.health;
    $('enabled').disabled=health.mode!=='live';
    window.WiciAircraft3D?.sync({visible,enabled:$('enabled').checked,mode:health.mode,hidden:document.hidden});
    if(!shown()){
      generation++; request?.abort(); request=null;
      clearTimeout(timer); timer=null; clearInterval(ageTimer); ageTimer=null;
      if(layer)map.removeLayer(layer);layer=null;markers.clear();
      status(health.mode==='demo'?'Samoloty wyłączone w demonstracji.':$('enabled').checked?'Samoloty wstrzymane poza widoczną mapą.':'Warstwa samolotów wyłączona.');
      return;
    }
    if(ageTimer===null)ageTimer=setInterval(tick,1000);
    if(timer===null&&!request)load();
  }
  function init(options){
    if(map||!options.map)return;
    map=options.map; health=options.health||{};
    window.WiciAircraft3D?.init({map});
    map.createPane('aircraftPositions').style.zIndex='620';
    map.attributionControl.addAttribution('<a href="https://adsb.fi/" target="_blank" rel="noopener noreferrer">adsb.fi</a> · użytek osobisty, niekomercyjny');
    $('enabled').addEventListener('change',()=>sync());
  }
  document.addEventListener?.('wici:regionchange',()=>{if(map)render();});
  return {init,sync,icon};
})();
