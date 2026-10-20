'use strict';
window.WiciBuses = (() => {
  const $ = id => document.getElementById(`buses-${id}`);
  const node = (tag, text) => {const n=document.createElement(tag); if(text!=null)n.textContent=text; return n;};
  const cities={
    szczecin:{name:'Szczecin',source:'ZDiTM Szczecin',url:'https://www.zditm.szczecin.pl/',bounds:[[53.33,14.4],[53.57,14.8]],license:' · CC0'},
    krakow:{name:'Kraków',source:'ZTP Kraków',url:'https://gtfs.ztp.krakow.pl/',bounds:[[49.94,19.75],[50.16,20.17]]},
    poznan:{name:'Poznań',source:'ZTM Poznań',url:'https://www.ztm.poznan.pl/otwarte-dane/',bounds:[[52.28,16.72],[52.52,17.1]]},
    warszawa:{name:'Warszawa',focusName:'Warszawę',source:'Miasto Stołeczne Warszawa',url:'https://dane.um.warszawa.pl/',bounds:[[52.08,20.8],[52.38,21.3]]}
  };
  let city='szczecin',attribution;
  const enabledByCity=new Map();
  let map, health={}, visible=false, layer, data, timer=null, ageTimer=null, request=null, requestTimeout=null, generation=0, backendDisabled=false;
  const markers=new Map();
  const shown = () => Boolean(map) && visible && !document.hidden && health.mode==='live' && $('enabled').checked && !backendDisabled;
  const age = item => {const time=Date.parse(item.position_at); return Number.isFinite(time)?Math.max(0,(Date.now()-time)/1000):Infinity;};
  const number = (value, unit) => Number.isFinite(value)?`${Math.round(value).toLocaleString('pl-PL')} ${unit}`:'Brak danych';
  const refresh = () => Math.max(10,Number(data?.refresh_seconds)||10);
  function status(message, warning=false){$('status').textContent=message; $('status').classList.toggle('notice',warning);}
  function delay(value){return !Number.isFinite(value)?'Brak danych':value===0?'Zgodnie z rozkładem':`${number(Math.abs(value),'s')} ${value>0?'opóźnienia':'przed rozkładem'}`;}
  const canFollow = item => !backendDisabled && !data?.stale && data?.status!=='error' && age(item)<=60;
  function popup(marker){
    const item=marker.bus;
    if(!marker.popupView){
      const box=node('div');box.className='map-popup';
      const heading=node('strong'),list=node('dl'),source=node('small');
      box.append(heading,list,source);
      marker.popupView={box,heading,list,source,values:[]};
    }
    const view=marker.popupView;
    view.heading.textContent=`Autobus · linia ${item.line||'—'}`;
    const fields=[
      ['Kierunek',item.headsign||'Brak danych'],['Numer pojazdu',item.vehicle_number||'Brak danych'],
      ['Model',item.model||'Brak danych'],['Operator',item.operator||'Brak danych'],
      ['Prędkość',number(item.speed_kmh,'km/h')],['Opóźnienie',delay(item.delay_seconds)],
      ['Poprzedni przystanek',item.previous_stop||'Brak danych'],['Następny przystanek',item.next_stop||'Brak danych'],
      ['Niska podłoga',item.low_floor===true?'Tak':item.low_floor===false?'Nie':'Brak danych'],
      ['Wiek pozycji',number(age(item),'s')]
    ];
    fields.forEach(([label,value],index)=>{
      if(!view.values[index]){const entry=node('dd');view.list.append(node('dt',label),entry);view.values.push(entry);}
      view.values[index].textContent=value;
    });
    view.source.textContent=`${cities[city].source}${data?.stale?' · ostatni odczyt, odświeżanie niedostępne':age(item)>60?' · starsza pozycja':' · bieżące pozycje'}`;
    if(window.WiciBuses3D&&!view.follow){
      const button=node('button','Podążaj w 3D');button.type='button';
      button.addEventListener('click',()=>{
        if(!canFollow(marker.bus)){popup(marker);return;}
        window.WiciBuses3D?.open(marker.bus,data,button,marker.getPopup(),{city,source:cities[city]});
      });
      view.follow=button;view.box.append(button);
    }
    if(view.follow)view.follow.disabled=!canFollow(item);
    return view.box;
  }
  function icon(item){
    const wrap=node('span');wrap.className=`buses-symbol${data?.stale||age(item)>60?' buses-old':''}`;wrap.textContent=item.line||'BUS';
    return L.divIcon({className:'buses-marker',html:wrap,iconSize:[36,28],iconAnchor:[18,14]});
  }
  function updateLines(){
    const selected=$('line').value||'';
    const lines=new Set((data?.items||[]).map(item=>String(item.line||'')).filter(Boolean));
    if(selected)lines.add(selected);
    $('line').replaceChildren(node('option','Wszystkie linie'));
    $('line').children[0].value='';
    for(const line of [...lines].sort((a,b)=>a.localeCompare(b,'pl',{numeric:true}))){const option=node('option',line);option.value=line;$('line').append(option);}
    $('line').value=selected;
  }
  function render(){
    if(!shown())return;
    if(!layer){layer=L.layerGroup();layer.addTo(map);}
    const live=new Set();let total=0,old=0;
    for(const item of data?.items||[]){
      if(window.WiciRegion&&!window.WiciRegion.contains(item.latitude,item.longitude))continue;
      if(!Number.isFinite(item.latitude)||!Number.isFinite(item.longitude)||age(item)>120)continue;
      total++;
      if($('line').value&&String(item.line)!==$('line').value)continue;
      if(age(item)>60||data.stale)old++;
      live.add(item.id);let marker=markers.get(item.id);
      if(!marker){
        marker=L.marker([item.latitude,item.longitude],{pane:'busPositions',icon:icon(item),title:`Linia ${item.line||'—'} · ${item.headsign||'autobus'}`,bubblingMouseEvents:false});
        marker.bus=item;
        marker.bindPopup(()=>popup(marker),{minWidth:260,maxWidth:300});
        marker.bindTooltip(()=>node('span',`Linia ${marker.bus.line||'—'} · ${marker.bus.headsign||'autobus'}`));
        marker.addTo(layer);markers.set(item.id,marker);
      }else{
        // Leaflet can re-evaluate popup content while replacing the marker icon.
        marker.bus=item;
        marker.setLatLng([item.latitude,item.longitude]).setIcon(icon(item));
      }
      // Stable nodes preserve the reading position and the 3D button's focus.
      if(marker.isPopupOpen())popup(marker);
    }
    for(const [id,marker] of markers)if(!live.has(id)){layer.removeLayer(marker);markers.delete(id);}
    if(data)status(`${cities[city].name} · Autobusy: ${markers.size}${$('line').value?` / ${total} · linia ${$('line').value}`:''} · odświeżanie co ${refresh()} s${old?` · starsze pozycje: ${old}`:''}${data.stale?' · dane nieaktualne':''}${data.message?` · ${data.message}`:''}`,Boolean(data.stale||data.status==='error'||old));
  }
  async function load(){
    if(!shown()||request)return;
    const run=generation,controller=new AbortController();request=controller;
    const timeout=setTimeout(()=>controller.abort(),60000);requestTimeout=timeout;
    if(!data)status(`Wczytywanie autobusów: ${cities[city].name}…`);
    try{
      const response=await (window.WiciRegion?.fetch || fetch)(`/api/buses?city=${city}`,{signal:controller.signal});
      if(!response.ok)throw new Error('Nieudany odczyt');
      const result=await response.json();
      if(run!==generation||!shown())return;
      if(!Array.isArray(result.items))throw new Error('Nieprawidłowa odpowiedź');
      data=result;backendDisabled=result.enabled===false;
      window.WiciBuses3D?.update(data,{city,source:cities[city]});
      if(backendDisabled){sync();return;}
      // A report can move the selected vehicle to another line. Forward the
      // current filter after updating 3D so that selection leaves its scope.
      updateLines();sync();
    }catch{
      if(run!==generation||!shown())return;
      data={...(data||{items:[]}),stale:true,status:'error',message:'Nie udało się odświeżyć danych. Ponowna próba za 10 s.'};
      window.WiciBuses3D?.update(data,{city,source:cities[city]});render();
    }finally{
      clearTimeout(timeout);if(request===controller){request=null;requestTimeout=null;}
      if(run===generation&&shown())timer=setTimeout(()=>{timer=null;load();},refresh()*1000);
    }
  }
  function stop(){
    generation++;request?.abort();request=null;clearTimeout(requestTimeout);requestTimeout=null;clearTimeout(timer);timer=null;clearInterval(ageTimer);ageTimer=null;
    if(layer)map.removeLayer(layer);layer=null;markers.clear();
  }
  function updateAttribution(){
    if(attribution)map.attributionControl.removeAttribution(attribution);
    const source=cities[city];
    attribution=`<a href="${source.url}" target="_blank" rel="noopener noreferrer">${source.source}</a>${source.license||''}`;
    map.attributionControl.addAttribution(attribution);
    $('focus').textContent=`Pokaż ${source.focusName||source.name}`;
    if($('source')){$('source').textContent=source.source;$('source').href=source.url;}
    if($('license'))$('license').textContent=source.license||'';
    if($('description'))$('description').textContent=`${source.name}: bieżące pozycje autobusów. Dane przetworzone i ujednolicone przez WICI; czas ostatniej pozycji w szczegółach pojazdu.`;
  }
  function changeCity(){
    const next=$('city').value;
    if(!cities[next]||next===city)return;
    enabledByCity.set(city,$('enabled').checked);
    const enabled=$('enabled').checked;
    stop();city=next;data=undefined;backendDisabled=false;
    $('enabled').checked=enabledByCity.get(city)??enabled;
    window.WiciPreferences?.remember($('enabled'));
    $('line').value='';updateLines();updateAttribution();sync();
    window.WiciLayers?.update();
  }
  function sync(options={}){
    if(options.visible!==undefined)visible=options.visible;if(options.health)health=options.health;
    $('enabled').disabled=health.mode!=='live';
    $('city').disabled=health.mode!=='live';
    window.WiciBuses3D?.sync({visible,enabled:$('enabled').checked&&!backendDisabled,mode:health.mode,hidden:document.hidden,city,line:$('line').value});
    if(!shown()){
      stop();
      status(backendDisabled?(data?.message||'Warstwa autobusów wyłączona przez serwer.'):health.mode==='demo'?'Autobusy wyłączone w demonstracji.':$('enabled').checked?'Autobusy wstrzymane poza widoczną mapą.':'Warstwa autobusów wyłączona.');return;
    }
    render();if(ageTimer===null)ageTimer=setInterval(render,1000);
    if(timer===null&&!request)load();
  }
  function init(options){
    if(map||!options.map)return;map=options.map;health=options.health||{};
    window.WiciBuses3D?.init({map});
    map.createPane('busPositions').style.zIndex='615';
    city=cities[$('city').value]?$('city').value:'szczecin';$('city').value=city;updateAttribution();
    $('enabled').addEventListener('change',()=>sync());$('line').addEventListener('change',()=>sync());
    $('city').addEventListener('change',changeCity);
    $('focus').addEventListener('click',()=>map.fitBounds(cities[city].bounds));
  }
  document.addEventListener?.('wici:regionchange',()=>{if(map)render();});
  return {init,sync};
})();
