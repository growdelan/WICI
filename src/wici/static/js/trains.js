'use strict';
window.WiciTrains = (() => {
  const $ = id => document.getElementById(`trains-${id}`);
  const node = (tag, text) => {const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  const REFRESH_MS=60000, MAX_DEPARTURES=30;
  let map, health={}, visible=false, layer, routeLayer, data, timer=null, ageTimer=null, generation=0;
  let selected=null, stationData=null, tripData=null, selectedTrip=null, popupHost=null, selectedPosition=null;
  let positionLayer=null, positionData=null, positionTimer=null, positionMessage='', positionGeneration=0;
  const positionMarkers=new Map();
  const rejectedPositionSources=new Map();
  const courseKey=item=>JSON.stringify([item.trip_id,item.start_date]);
  const markers=new Map(), requests=new Map(), freshnessNodes=new Map();
  const shown=()=>Boolean(map)&&visible&&!document.hidden&&health.mode==='live'&&$('enabled').checked;
  const positionsShown=()=>shown()&&Boolean($('positions-enabled')?.checked)&&data?.enabled!==false;
  const age=value=>{const time=Date.parse(value?.source_updated_at);return Number.isFinite(time)?Math.max(0,(Date.now()-time)/1000):Infinity;};
  const stale=value=>!value||value.stale||age(value)>(value.stale_after_seconds||600);
  const time=value=>{const date=new Date(value);return value&&Number.isFinite(date.getTime())?date.toLocaleTimeString('pl-PL',{timeZone:'Europe/Warsaw',hour:'2-digit',minute:'2-digit'}):'—';};
  const estimateTime=value=>{const date=new Date(value);return value&&Number.isFinite(date.getTime())?date.toLocaleTimeString('pl-PL',{timeZone:'Europe/Warsaw',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';};
  const delay=value=>Number.isFinite(value)?value===0?'punktualnie':Math.abs(value)<60?`${value>0?'+':''}${Math.round(value)} s`:`${value>0?'+':''}${Math.round(value/60)} min`:'brak informacji o opóźnieniu';
  function status(message,warning=false){$('status').textContent=message;$('status').classList.toggle('notice',warning);}
  function freshness(value){
    const seconds=Math.floor(age(value));
    return `PolishTrainsGTFS · ${stale(value)?'DANE NIEAKTUALNE · ':''}${Number.isFinite(seconds)?`aktualizacja źródła ${seconds<60?`${seconds} s`:`${Math.floor(seconds/60)} min`} temu`:'brak czasu aktualizacji źródła'}${value?.message?` · ${value.message}`:''}`;
  }
  function sourceNote(value){const n=node('small',freshness(value));n.className='train-meta';n.classList.toggle('train-stale',stale(value));freshnessNodes.set(n,value);return n;}
  function renderStatus(){
    if($('positions-status'))$('positions-status').textContent=$('positions-enabled')?.checked?!shown()?'Szacowane pozycje wstrzymane poza aktywną warstwą.':`Pozycje szacowane: ${positionMarkers.size} · nie GPS · ${positionMessage||'oczekiwanie na dane'}${positionData?` · ${freshness(positionData)}`:''}. Brak znacznika nie oznacza braku pociągu.`:'Szacowane pozycje wyłączone.';
    if(!data)return;
    if(data.enabled===false){status(`Kolej wyłączona w konfiguracji serwera.${data.message?` ${data.message}`:''}`,true);return;}
    const detail=tripData||stationData;
    const positions=$('positions-enabled')?.checked?` · pozycje szacowane: ${positionMarkers.size}${positionMessage?` · ${positionMessage}`:''}`:'';
    status(`Kolej: ${markers.size} stacji · odświeżanie co 60 s · ${freshness(data)}${detail&&stale(detail)?' · wybrane szczegóły nieaktualne':''}${positions}`,stale(data)||Boolean(detail&&stale(detail)));
  }
  function tick(){
    if(!shown())return;
    pruneRejectedPositions();
    expirePositions();renderStatus();
    for(const [n,value]of freshnessNodes){n.textContent=freshness(value);n.classList.toggle('train-stale',stale(value));}
  }
  async function fetchData(key,url,timeoutMs=120000){
    requests.get(key)?.abort();
    const controller=new AbortController(),run=generation;requests.set(key,controller);
    const timeout=setTimeout(()=>controller.abort(),timeoutMs);
    try{
      const response=await (window.WiciRegion?.fetch || fetch)(url,{signal:controller.signal});
      if(!response.ok)throw new Error('Nieudany odczyt');
      const value=await response.json();
      if(run!==generation||!shown()||requests.get(key)!==controller)return null;
      return value;
    }catch(error){
      if(run!==generation||!shown()||requests.get(key)!==controller)return null;
      throw error;
    }finally{clearTimeout(timeout);if(requests.get(key)===controller)requests.delete(key);}
  }
  function popupBox(title){const box=node('div');box.className='map-popup train-popup';box.append(node('strong',title));return box;}
  function showPopup(box){
    freshnessNodes.clear();
    // Keep only freshness labels belonging to the current popup.
    for(const n of box.querySelectorAll('.train-meta'))freshnessNodes.set(n,n.trainData);
    if(popupHost)popupHost.setPopupContent(box);
  }
  function note(box,value){const n=sourceNote(value);n.trainData=value;box.append(n);}
  function renderStation(){
    if(!selected||!stationData||selectedTrip)return;
    const box=popupBox(stationData.station?.name||markers.get(selected)?.station.name||'Stacja');
    box.append(node('p','Odjazdy: ostatnie 30 min i najbliższe 3 godziny. Czas polski.'));
    const list=node('div');list.className='train-departures';
    for(const trip of (stationData.departures||[]).slice(0,MAX_DEPARTURES)){
      const button=node('button');button.type='button';button.className='train-course';
      button.append(node('strong',`${time(trip.scheduled_at)} → ${time(trip.expected_at)} · ${trip.number||'Pociąg'} ${trip.headsign||''}`),node('span',`${trip.operator||''} · ${trip.cancelled?'ODWOŁANY':delay(trip.delay_seconds)}${trip.realtime?'':' · tylko rozkład'}`));
      // Stop before replacing the DOM: Leaflet otherwise loses the popup ancestor
      // while its map click handler walks the detached event target.
      button.addEventListener('click',event=>{event?.stopPropagation();selectTrip(trip);});list.append(button);
    }
    if(!list.children.length)list.append(node('p','Brak odjazdów w tym przedziale.'));
    box.append(list);
    if((stationData.departures||[]).length>MAX_DEPARTURES)box.append(node('small',`Pokazano pierwszych ${MAX_DEPARTURES} odjazdów.`));
    note(box,stationData);showPopup(box);
  }
  function clearRoute(){if(routeLayer)map.removeLayer(routeLayer);routeLayer=null;}
  function renderTrip(fit=false){
    if(!tripData?.trip||!selectedTrip)return;
    const trip=tripData.trip,box=popupBox(`${trip.number||'Pociąg'} → ${trip.headsign||''}`);
    const back=node('button',selectedPosition?'← Szacowana pozycja':'← Odjazdy ze stacji');back.type='button';back.className='train-route-clear';
    back.addEventListener('click',event=>{event?.stopPropagation();requests.get('trip')?.abort();requests.delete('trip');selectedTrip=null;tripData=null;clearRoute();if(selectedPosition)renderPositionPopup();else renderStation();renderStatus();});
    if(selectedPosition)box.append(estimatedNotice());
    box.append(back,node('p',`${trip.operator||''} · ${trip.start_date||selectedTrip.start_date||''}${trip.cancelled?' · ODWOŁANY':''}${trip.realtime?'':' · tylko rozkład'}`));
    const stops=node('ol');stops.className='train-trip-stops';
    for(const stop of trip.stops||[]){
      const li=node('li');li.append(node('strong',`${stop.name}${stop.skipped?' · POSTÓJ POMINIĘTY':''}`));
      li.append(node('div',`Przyjazd: ${time(stop.scheduled_arrival)} → ${time(stop.expected_arrival)} · Odjazd: ${time(stop.scheduled_departure)} → ${time(stop.expected_departure)} · ${delay(stop.delay_seconds)}`));stops.append(li);
    }
    box.append(node('small','Godziny: rozkład → aktualizacja. Czas polski.'),stops);
    clearRoute();routeLayer=L.layerGroup().addTo(map);
    const points=(trip.geometry?.coordinates||[]).filter(p=>Array.isArray(p)&&Number.isFinite(p[0])&&Number.isFinite(p[1])).map(p=>[p[1],p[0]]);
    if(points.length>1){
      const line=L.polyline(points,{pane:'trainRoutes',color:'#c2410c',weight:4,opacity:.85}).addTo(routeLayer);
      // Finish zooming before Leaflet measures and pans the updated popup.
      if(fit)map.fitBounds(line.getBounds(),{padding:[30,30],maxZoom:11,animate:false});
    }else box.append(node('p',trip.detour?'Zmieniona trasa kursu. Źródło nie udostępnia aktualnej geometrii.':'Brak geometrii trasy w źródle.'));
    note(box,tripData);showPopup(box);renderStatus();
  }
  async function loadTrip(fit=false){
    const chosen=selectedTrip;if(!chosen)return;
    try{
      const value=await fetchData('trip',`/api/trains/trips/${encodeURIComponent(chosen.trip_id)}?start_date=${encodeURIComponent(chosen.start_date||'')}`);
      if(!value||selectedTrip!==chosen)return;
      if(!value.trip||!Array.isArray(value.trip.stops))throw new Error('Nieprawidłowa odpowiedź');
      if(value.trip.cancelled||value.trip.detour||!value.trip.geometry?.coordinates?.length){
        const fromPosition=Boolean(selectedPosition);
        rejectCoursePositions([chosen],value);
        if(fromPosition){if(selectedPosition){selectedTrip=null;tripData=null;renderPositionPopup();}renderStatus();return;}
      }
      tripData=value;checkSource(value);renderTrip(fit);
    }catch{
      if(selectedTrip!==chosen)return;
      suppressPositions('błąd odczytu szczegółów kursu');
      if(tripData){tripData={...tripData,stale:true,message:'Nie udało się odświeżyć trasy.'};renderTrip();}
      else{selectedTrip=null;if(selectedPosition)renderPositionPopup();else renderStation();const marker=popupHost;const error=node('p','Nie udało się pobrać trasy. Wybierz kurs ponownie.');marker?.getPopup().getContent().append(error);}
    }
  }
  function selectTrip(trip){selectedTrip=trip;tripData=null;clearRoute();showPopup(popupBox('Wczytywanie trasy pociągu…'));loadTrip(true);}
  async function loadStation(){
    const id=selected;if(!id)return;
    try{
      const value=await fetchData('station',`/api/trains/stations/${encodeURIComponent(id)}`);
      if(!value||selected!==id)return;
      if(!value.station||!Array.isArray(value.departures))throw new Error('Nieprawidłowa odpowiedź');
      rejectCoursePositions(value.departures.filter(trip=>trip.trip_cancelled||trip.detour),value);
      stationData=value;checkSource(value);renderStation();renderStatus();
    }catch{
      if(selected!==id)return;
      suppressPositions('błąd odczytu odjazdów');
      if(stationData){stationData={...stationData,stale:true,message:'Nie udało się odświeżyć odjazdów.'};renderStation();renderStatus();}
      else showPopup(popupBox('Nie udało się pobrać odjazdów. Zamknij i otwórz stację, aby spróbować ponownie.'));
    }
  }
  function selectStation(id){
    if(selected===id&&(stationData||requests.has('station'))){if(selectedTrip&&tripData)renderTrip();else renderStation();return;}
    requests.get('trip')?.abort();requests.delete('trip');selectedPosition=null;popupHost=markers.get(id);selected=id;stationData=null;tripData=null;selectedTrip=null;clearRoute();freshnessNodes.clear();
    showPopup(popupBox('Wczytywanie odjazdów…'));loadStation();
  }
  function render(){
    if(data.enabled===false){$('enabled').disabled=true;clearInterval(ageTimer);ageTimer=null;stopPositions();}
    if(!layer)layer=L.layerGroup().addTo(map);
    const live=new Set();
    for(const station of data.items){
      if(window.WiciRegion&&!window.WiciRegion.contains(station.latitude,station.longitude))continue;
      if(!station.id||!Number.isFinite(station.latitude)||!Number.isFinite(station.longitude))continue;
      live.add(station.id);let marker=markers.get(station.id);
      if(!marker){
        marker=L.circleMarker([station.latitude,station.longitude],{pane:'trainStations',radius:4,color:'#592d96',weight:1,fillColor:'#c6a7fa',fillOpacity:.9,bubblingMouseEvents:false});
        marker.station=station;marker.bindPopup(()=>popupBox(station.name),{maxWidth:320,maxHeight:360,autoPanPaddingTopLeft:[12,85],autoPanPaddingBottomRight:[12,45]});
        marker.bindTooltip(()=>node('span',station.name));marker.on('popupopen',()=>selectStation(station.id));marker.addTo(layer);markers.set(station.id,marker);
      }
    }
    for(const [id,marker]of markers)if(!live.has(id)){layer.removeLayer(marker);markers.delete(id);}
    if(selected&&!live.has(selected)){selected=null;stationData=null;selectedTrip=null;tripData=null;clearRoute();freshnessNodes.clear();popupHost=null;}
    renderStatus();
  }
  async function load(){
    if(!shown()||requests.has('stations'))return;
    const run=generation;
    if(!data)status('Wczytywanie danych kolejowych… Pierwsze pobranie i przygotowanie rozkładu może potrwać do dwóch minut.');
    try{
      const value=await fetchData('stations','/api/trains/stations');if(!value)return;
      if(!Array.isArray(value.items))throw new Error('Nieprawidłowa odpowiedź');data=value;checkSource(value);render();
    }catch{suppressPositions('błąd odczytu źródła');data={...(data||{items:[]}),stale:true,message:'Nie udało się odświeżyć danych. Ponowna próba za minutę.'};render();}
    finally{if(run===generation&&shown()&&data?.enabled!==false)timer=setTimeout(()=>{timer=null;load();if(selected)loadStation();if(selectedTrip)loadTrip();},REFRESH_MS);}
  }

  function estimatedNotice(){const n=node('strong','POZYCJA SZACOWANA · nie GPS');n.className='train-estimate-notice';return n;}
  const validUntil=value=>{const end=Date.parse(value?.valid_until);return Number.isFinite(end)&&end>Date.now();};
  const currentPositions=value=>value&&!stale(value)&&value.status!=='error'&&value.enabled!==false&&validUntil(value);
  const currentPosition=item=>item?.estimated===true&&!item.cancelled&&!item.detour&&validUntil(item)&&!stale(item)&&Number.isFinite(item.latitude)&&Number.isFinite(item.longitude)&&!(Date.parse(item.source_updated_at)<=(rejectedPositionSources.get(courseKey(item))?.sourceAt??-Infinity));
  function pruneRejectedPositions(){for(const [key,rejection]of rejectedPositionSources)if(rejection.expiresAt<=Date.now())rejectedPositionSources.delete(key);}
  function rejectCoursePositions(courses,metadata){
    const sourceAt=Date.parse(metadata.source_updated_at);if(!courses.length||!Number.isFinite(sourceAt))return;
    pruneRejectedPositions();
    const rejected=new Set();
    for(const course of courses){
      if(!course.trip_id||!course.start_date)continue;
      const key=courseKey(course),previous=rejectedPositionSources.get(key);
      if(!previous||sourceAt>=previous.sourceAt)rejectedPositionSources.set(key,{sourceAt,expiresAt:sourceAt+(metadata.stale_after_seconds||600)*1000});
      rejected.add(key);
    }
    if(!rejected.size)return;
    // Reject the whole older response, then keep rejecting this course until the
    // provider publishes newer data. A restarted request can still hit its cache.
    resetPositionRequest(true);
    for(const [id,marker]of positionMarkers){
      const key=courseKey(marker.trainPosition);
      if(rejected.has(key)&&Date.parse(marker.trainPosition.source_updated_at)<=rejectedPositionSources.get(key).sourceAt)removePosition(id);
    }
  }
  function renderPositionPopup(){
    const marker=positionMarkers.get(selectedPosition),item=marker?.trainPosition;if(!item)return;
    const box=popupBox(`${item.number||'Pociąg'} → ${item.headsign||''}`);box.append(estimatedNotice(),node('p',`${item.operator||''} · ${item.from_station||'—'} → ${item.to_station||'—'}`));
    box.append(node('p',`Oszacowanie na ${estimateTime(item.estimated_at)}. Lokalizacja wyliczona z trasy i aktualizacji przejazdu; może odbiegać od rzeczywistej.`));
    const button=node('button','Pokaż trasę i postoje');button.type='button';button.className='train-course';
    button.addEventListener('click',event=>{event?.stopPropagation();selectTrip(item);});box.append(button);note(box,item);showPopup(box);
  }
  function selectPosition(id){
    requests.get('station')?.abort();requests.delete('station');requests.get('trip')?.abort();requests.delete('trip');
    selected=null;stationData=null;selectedTrip=null;tripData=null;selectedPosition=id;popupHost=positionMarkers.get(id);clearRoute();renderPositionPopup();
  }
  function removePosition(id){
    const marker=positionMarkers.get(id);if(marker)positionLayer?.removeLayer(marker);positionMarkers.delete(id);
    if(selectedPosition===id){requests.get('trip')?.abort();requests.delete('trip');selectedPosition=null;selectedTrip=null;tripData=null;popupHost=null;freshnessNodes.clear();clearRoute();}
  }
  function clearPositions(){for(const id of [...positionMarkers.keys()])removePosition(id);if(positionLayer)map.removeLayer(positionLayer);positionLayer=null;}
  function expirePositions(){
    if(!positionMarkers.size)return;
    if(!positionsShown()||!currentPositions(positionData)){clearPositions();positionMessage='szacowanie wstrzymane: brak aktualnych danych';return;}
    for(const [id,marker]of positionMarkers)if(!currentPosition(marker.trainPosition))removePosition(id);
  }
  function renderPositions(){
    if(!positionsShown())return;
    if(!currentPositions(positionData)){clearPositions();positionMessage=positionData?.message||'szacowanie wstrzymane: brak aktualnych danych';renderStatus();return;}
    positionMessage='co 15 s · nie GPS';
    if(!positionLayer)positionLayer=L.layerGroup().addTo(map);
    const live=new Set();
    for(const item of positionData.items){
      if(window.WiciRegion&&!window.WiciRegion.contains(item.latitude,item.longitude))continue;
      if(!item.id||!currentPosition(item))continue;
      live.add(item.id);let marker=positionMarkers.get(item.id);
      if(!marker){
        const symbol=node('span');symbol.className='train-estimated-symbol';const glyph=node('span','🚆');glyph.className='train-estimated-glyph';const badge=node('small','≈');badge.className='train-estimated-badge';symbol.append(glyph,badge);
        marker=L.marker([item.latitude,item.longitude],{pane:'trainEstimatedPositions',icon:L.divIcon({className:'train-estimated-marker',html:symbol,iconSize:[22,22],iconAnchor:[11,11]}),title:`Pozycja szacowana · ${item.number||item.trip_id}`,bubblingMouseEvents:false});
        marker.bindPopup(()=>popupBox('POZYCJA SZACOWANA · nie GPS'),{maxWidth:320,maxHeight:360,autoPanPaddingTopLeft:[12,85],autoPanPaddingBottomRight:[12,45]});
        marker.bindTooltip(()=>node('span',`POZYCJA SZACOWANA · ${marker.trainPosition.number||'Pociąg'} → ${marker.trainPosition.headsign||''}`));
        marker.on('popupopen',()=>selectPosition(item.id));marker.addTo(positionLayer);positionMarkers.set(item.id,marker);
      }else marker.setLatLng([item.latitude,item.longitude]);
      marker.trainPosition=item;
    }
    for(const id of [...positionMarkers.keys()])if(!live.has(id))removePosition(id);
    if(selectedPosition&&!selectedTrip)renderPositionPopup();renderStatus();
  }
  async function loadPositions(){
    if(!positionsShown()||requests.has('positions'))return;
    const run=generation,positionRun=positionGeneration;
    try{
      const value=await fetchData('positions','/api/trains/positions',data?15000:120000);
      if(!value||run!==generation||positionRun!==positionGeneration||!positionsShown())return;
      if(!Array.isArray(value.items))throw new Error('Nieprawidłowa odpowiedź');positionData=value;renderPositions();
    }catch{if(run!==generation||positionRun!==positionGeneration)return;clearPositions();positionData=null;positionMessage='szacowanie wstrzymane: błąd odświeżania';renderStatus();}
    finally{if(run===generation&&positionRun===positionGeneration&&positionsShown())positionTimer=setTimeout(()=>{positionTimer=null;loadPositions();},15000);}
  }
  function resetPositionRequest(retry=false){
    positionGeneration++;requests.get('positions')?.abort();requests.delete('positions');clearTimeout(positionTimer);positionTimer=null;
    if(retry&&positionsShown())positionTimer=setTimeout(()=>{positionTimer=null;loadPositions();},15000);
  }
  function suppressPositions(reason){
    resetPositionRequest(true);
    clearPositions();positionData=null;positionMessage=`szacowanie wstrzymane: ${reason}`;
    renderStatus();
  }
  function checkSource(value){if(stale(value)||value.status==='error'||value.enabled===false)suppressPositions('brak aktualnego źródła');}
  function stopPositions(){resetPositionRequest();clearPositions();positionData=null;positionMessage='';renderStatus();}

  function sync(options={}){
    if(options.visible!==undefined)visible=options.visible;if(options.health)health=options.health;
    $('enabled').disabled=health.mode!=='live'||data?.enabled===false;
    if($('positions-enabled'))$('positions-enabled').disabled=health.mode!=='live'||data?.enabled===false;
    if(!shown()){
      stopPositions();generation++;for(const controller of requests.values())controller.abort();requests.clear();
      clearTimeout(timer);timer=null;clearInterval(ageTimer);ageTimer=null;
      if(layer)map.removeLayer(layer);layer=null;markers.clear();clearRoute();selected=null;stationData=null;tripData=null;selectedTrip=null;popupHost=null;selectedPosition=null;freshnessNodes.clear();
      status(health.mode==='demo'?'Kolej wyłączona w demonstracji.':$('enabled').checked?'Kolej wstrzymana poza widoczną mapą.':'Warstwa kolejowa wyłączona.');return;
    }
    if(data&&!layer)render();
    if(data?.enabled===false){renderStatus();return;}
    if(ageTimer===null)ageTimer=setInterval(tick,1000);
    if(positionsShown()){if(positionTimer===null&&!requests.has('positions'))loadPositions();}else stopPositions();
    if(timer===null&&!requests.has('stations'))load();
  }
  function init(options){
    if(map||!options.map)return;map=options.map;health=options.health||{};
    map.createPane('trainEstimatedPositions').style.zIndex='605';map.createPane('trainStations').style.zIndex='590';map.createPane('trainRoutes').style.zIndex='580';
    map.attributionControl.addAttribution('<a href="https://mkuran.pl/gtfs/" target="_blank" rel="noopener noreferrer">PolishTrainsGTFS</a> · Mikołaj Kuranowski · PKP PLK / Koleje Mazowieckie');
    $('enabled').addEventListener('change',()=>sync());
    $('positions-enabled')?.addEventListener('change',()=>{sync();renderStatus();});
    $('poland')?.addEventListener('click',()=>map.fitBounds([[49,14.1],[54.9,24.2]],{padding:[20,20]}));
    document.addEventListener('visibilitychange',()=>sync());
  }
  document.addEventListener('wici:regionchange',()=>{if(map&&shown()){if(data)render();renderPositions();}});
  return {init,sync};
})();
