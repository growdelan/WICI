'use strict';
window.WiciGios = (() => {
  const $=id=>document.getElementById(`gios-${id}`);
  const node=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
  const date=value=>value?new Intl.DateTimeFormat('pl-PL',{timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'Czas niejednoznaczny lub niepodany';
  const labels={PM10:'PM10','PM2.5':'PM2,5',NO2:'NO₂',SO2:'SO₂',O3:'O₃',CO:'CO',C6H6:'Benzen (C₆H₆)'};
  let map,api,visible=true,layer,timer=null,tick=null,epoch=0,selection=0,busy=false,detailBusy=false;
  let stations=null,sensors=null,series=null;
  // GIOŚ category palette; synthetic UI contract expectations in tests/fixtures/gios/legend.json.
  const indexColors=['#57b108','#b0dd10','#ffd911','#e58100','#e50000','#990000'];
  const indexNames=['Bardzo dobry','Dobry','Umiarkowany','Dostateczny','Zły','Bardzo zły'];
  const grey='#bfbfbf',indexCache=new Map(),indexJobs=new Map();
  let indexTimer=null,nextIndexStart=0,indexRetryAt=0,moving=false;
  const attribution='Źródło: <a href="https://powietrze.gios.gov.pl/pjp/content/api">GIOŚ - EKOINFONET</a> · wyniki niezweryfikowane';
  const markers=new Map(),requests=new Map();
  function cancel(test=()=>true){for(const [controller,url] of requests)if(test(url))controller.abort();}
  const active=()=>visible&&!document.hidden&&$('enabled').checked;
  const old=result=>!!result?.stale||!result?.fetched_at||Date.now()-Date.parse(result.fetched_at)>result.refresh_seconds*2000;
  function freshness(item){
    if(!item?.observed_at)return 'Nieustalony czas — bez oceny wieku';
    const age=(Date.now()-Date.parse(item.observed_at))/1000;
    return `wiek: ${Math.max(0,Math.floor(age/60))} min${age>10800?' · NIEAKTUALNY (>3 h)':age < -900?' · czas w przyszłości':''}`;
  }
  function measurement(item){return `${item?.value==null?'Brak pomiaru':`${item.value} ${item.unit}`} · ${date(item?.observed_at)} · ${freshness(item)}${item?.source_time?` · czas źródła: ${item.source_time}`:''}`;}
  function chosen(){return stations?.items.find(i=>String(i.id)===$('station').value);}
  function inView(item){
    return (!window.WiciRegion||window.WiciRegion.contains(item?.latitude,item?.longitude))&&Number.isFinite(item?.latitude)&&Number.isFinite(item?.longitude)&&map.getBounds().contains([item.latitude,item.longitude]);
  }
  function visibleStations(){return active()?(stations?.items||[]).filter(inView):[];}
  function indexColor(result){
    const item=result?.items[0],age=Date.now()-Date.parse(item?.observed_at);
    return result?.status==='ready'&&!old(result)&&Number.isInteger(item?.value)&&item.value>=0&&item.value<=5&&Number.isFinite(age)&&age>=-900000&&age<=10800000?indexColors[item.value]:grey;
  }
  function indexBody(root,item){
    const result=indexCache.get(item.id)?.result,i=result?.items[0];
    root.append(node('h4','Oficjalny polski indeks jakości powietrza GIOŚ'));
    root.append(node('p',`${i?.value==null?'Brak indeksu — jakość powietrza nieznana':i.name} · ${date(i?.observed_at)} · ${freshness(i)}`));
    if(result){
      root.append(node('p',`Czas obliczenia: ${date(i?.calculated?.observed_at)} · surowy czas: ${i?.source_time||'brak'} · obliczenie w źródle: ${i?.calculated?.source_time||'brak'}`));
      root.append(node('p',`Pobranie indeksu: ${date(result.fetched_at)}${old(result)?' · NIEAKTUALNY ODCZYT':''} ${result.message||''}`));
    }else root.append(node('p',inView(item)?'Oczekiwanie na indeks stacji w widoku mapy.':'Indeks pobieramy wyłącznie dla stacji widocznych na mapie.'));
  }
  function stopIndexes(test=()=>true){
    if(indexTimer!==null)clearTimeout(indexTimer);indexTimer=null;
    for(const [id,job] of indexJobs)if(test(id)){job.cancelled=true;job.controller.abort();}
  }
  // Two in flight; logical reads start at least 600 ms apart (at most 100/min).
  function scheduleIndexes(){
    if(!active()||moving||stations?.enabled===false||indexTimer!==null||indexJobs.size>=2)return;
    const now=Date.now(),items=visibleStations();
    const item=items.find(i=>!indexJobs.has(i.id)&&(!indexCache.has(i.id)||indexCache.get(i.id).nextAt<=now));
    if(!item)return;
    const delay=Math.max(0,nextIndexStart-now,indexRetryAt-now);
    indexTimer=setTimeout(()=>{indexTimer=null;startIndex();},delay);
  }
  function startIndex(){
    if(!active()||moving||indexJobs.size>=2)return;
    const now=Date.now(),items=visibleStations();
    items.sort((a,b)=>(String(b.id)===$('station').value)-(String(a.id)===$('station').value));
    const item=items.find(i=>!indexJobs.has(i.id)&&(!indexCache.has(i.id)||indexCache.get(i.id).nextAt<=now));
    if(!item)return;
    if(now<nextIndexStart||now<indexRetryAt){scheduleIndexes();return;}
    const job={controller:new AbortController(),life:epoch,cancelled:false};indexJobs.set(item.id,job);nextIndexStart=now+600;
    safe(`/gios?kind=index&id=${item.id}`,indexCache.get(item.id)?.result,job.controller).then(result=>{
      if(job.cancelled||job.life!==epoch||!active()||!inView(item))return;
      const now=Date.now(),fetched=Date.parse(result.fetched_at);
      const nextAt=result.status==='error'||result.status==='partial'||!Number.isFinite(fetched)?now+300000:Math.max(now+1000,fetched+1800000);
      indexCache.delete(item.id);indexCache.set(item.id,{result,nextAt});
      while(indexCache.size>1024)indexCache.delete(indexCache.keys().next().value);
      if(!result.transport_error)indexRetryAt=Math.max(indexRetryAt,now+Math.max(0,result.service_retry_after_seconds||0)*1000);
      render();
    }).finally(()=>{indexJobs.delete(item.id);scheduleIndexes();});
    scheduleIndexes();
  }
  function syncIndexes(){
    if(!active()||moving){stopIndexes();return;}
    const visible=new Set(visibleStations().map(i=>i.id));stopIndexes(id=>!visible.has(id));
    render();scheduleIndexes();
  }
  function body(item){
    const root=node('div');root.className='gios-popup';
    root.append(node('h3',item.name),node('p',item.address||'Adres niepodany'));
    if(item.latitude==null)root.append(node('p','Brak poprawnych współrzędnych — stacja dostępna na liście.'));
    if(old(stations))root.append(node('p','NIEAKTUALNY wykaz stacji — aktualność niepotwierdzona.'));
    indexBody(root,item);
    if(String(item.id)!==$('station').value){root.append(node('p','Wybierz stację, aby pobrać pomiary.'));return root;}
    if(detailBusy)root.append(node('p','Wczytywanie danych GIOŚ…'));
    if(sensors&&!sensors.items.some(s=>s.parameter===$('parameter').value))root.append(node('p',`${labels[$('parameter').value]}: ${['error','partial'].includes(sensors.status)?'dostępność niepotwierdzona':'brak parametru na stacji'}`));
    if(series){
      root.append(node('h4',`Stężenie ${labels[$('parameter').value]} · stanowisko ${$('sensor').value}`));
      root.append(node('p',series.status==='manual'?'Stanowisko manualne — brak bieżących godzinowych wyników.':measurement(series.latest)));
      root.append(node('p',`Pobranie wyników: ${date(series.fetched_at)}${old(series)?' · NIEAKTUALNY ODCZYT':''} ${series.message||''}`));
      if(series.unresolved_value_count)root.append(node('p',`${series.unresolved_value_count} wartości z niejednoznacznym lub błędnym czasem — dostępne w tabeli, pominięte przy wyborze najnowszej.`));
    }
    if(sensors){
      root.append(node('p',`Stanowiska · pobranie: ${date(sensors.fetched_at)}${old(sensors)?' · NIEAKTUALNY ODCZYT':''} ${sensors.message||''}`));
      const availability=[];
      for(const [code,label] of Object.entries(labels)){
        const found=sensors.items.filter(s=>s.parameter===code);
        availability.push(`${label}: ${found.length?`${found.length} stanowisk — ${code===$('parameter').value?'wybrany parametr':'wybierz parametr, aby pobrać wyniki'}`:sensors.status==='error'||sensors.status==='partial'?'dostępność niepotwierdzona':'brak parametru na stacji'}`);
      }
      root.append(node('p',availability.join(' · ')));
    }
    const link=node('a','Źródło: GIOŚ · dokumentacja i dane');link.href='https://powietrze.gios.gov.pl/pjp/content/api';link.target='_blank';link.rel='noopener noreferrer';root.append(link);
    return root;
  }
  let rendering=false;
  function render(){
    // Popup auto-pan can synchronously emit moveend and request another render.
    if(rendering)return;
    rendering=true;
    try{renderContent();}finally{rendering=false;}
  }
  function renderContent(){
    const enabled=active();$('legend').hidden=!enabled||stations?.enabled===false;$('parameter').disabled=!sensors||detailBusy;$('sensor').disabled=!sensors||detailBusy;$('controls').hidden=!enabled||stations?.enabled===false;
    $('status').textContent=!enabled?'Pobieranie GIOŚ wstrzymane; warstwa wyłączona lub mapa ukryta.':!stations?'Wczytywanie GIOŚ…':`${stations.items.filter(i=>!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude)).length} stacji w obszarze · ${stations.items.filter(i=>i.latitude==null&&(!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude))).length} bez punktu na mapie · pobranie: ${date(stations.fetched_at)}${old(stations)&&stations.enabled?' · NIEAKTUALNY ODCZYT':''} ${stations.message||''}`;
    if(!enabled||stations?.enabled===false){if(layer)map.removeLayer(layer);map.attributionControl?.removeAttribution(attribution);layer=null;markers.clear();return;}
    if(!layer){layer=L.layerGroup().addTo(map);map.attributionControl?.addAttribution(attribution);}
    const retained=new Set();
    for(const item of stations?.items||[]){
      if(window.WiciRegion&&!window.WiciRegion.contains(item.latitude,item.longitude))continue;
      if(!Number.isFinite(item.latitude)||!Number.isFinite(item.longitude))continue;
      retained.add(item.id);let marker=markers.get(item.id);
      if(!marker){
        marker=L.circleMarker([item.latitude,item.longitude],{pane:'giosStations',radius:5,color:grey,weight:2,fillOpacity:1,bubblingMouseEvents:false});
        marker.bindTooltip(node('span',item.name)).bindPopup(()=>body(marker.giosItem),{maxWidth:360,maxHeight:360});
        marker.on('click',()=>selectStation(String(marker.giosItem.id),false));marker.addTo(layer);markers.set(item.id,marker);
      }
      marker.giosItem=item;marker.setLatLng([item.latitude,item.longitude]);
      const result=indexCache.get(item.id)?.result,color=indexColor(result);
      marker.setStyle({color,fillColor:color});
      marker.setTooltipContent(node('span',`${item.name} · ${color===grey?'Brak aktualnego indeksu':result.items[0].name}`));
      if(marker.isPopupOpen())marker.getPopup().update();
    }
    for(const [id,marker] of markers)if(!retained.has(id)){layer.removeLayer(marker);markers.delete(id);}
    const viewport=visibleStations(),colored=viewport.filter(i=>indexColor(indexCache.get(i.id)?.result)!==grey).length;
    const done=viewport.filter(i=>(indexCache.get(i.id)?.nextAt||0)>Date.now()).length;
    window.WiciRegion?.progress('gios-enabled',{done,total:viewport.length,pending:done<viewport.length});
    $('index-status').textContent=`Odczytano ${done}/${viewport.length} indeksów · ${viewport.length} stacji w widoku · ${colored} z aktualnym indeksem · pozostałe szare. Indeksy GIOŚ z cache do 30 min.`;
    const detail=$('detail');detail.replaceChildren();if(chosen())detail.append(body(chosen()));
    const root=$('history'),wasOpen=root.open;root.replaceChildren(node('summary','Godzinowe wyniki · okno bieżącej usługi (do 3 dób)'));root.open=wasOpen;
    if(series?.items.length){
      const table=node('table'),head=node('tr');head.append(node('th','Czas Europe/Warsaw / źródła'),node('th','Stężenie µg/m³'));table.append(head);
      for(const item of [...series.items].sort((a,b)=>(b.observed_at||b.source_time||'').localeCompare(a.observed_at||a.source_time||''))){
        const row=node('tr');row.append(node('td',`${date(item.observed_at)} · ${item.source_time||'brak'}${!item.observed_at?' (DST / błędny czas)':''}`),node('td',item.value??'Brak pomiaru (null)'));table.append(row);
      }
      root.append(table);
    }else root.append(node('p',series?.message||'Wybierz stację, parametr i stanowisko.'));
  }
  function options(control,items,label,placeholder){
    const previous=control.value;control.replaceChildren();const first=node('option',placeholder);first.value='';control.append(first);
    for(const item of items){const e=node('option',label(item));e.value=String(item.id);control.append(e);}control.value=previous;
  }
  function sensorOptions(){
    const list=(sensors?.items||[]).filter(s=>s.parameter===$('parameter').value);
    options($('sensor'),list,s=>`${s.name} · ID ${s.id}`,'Wybierz stanowisko');
    if(!list.some(s=>String(s.id)===$('sensor').value))$('sensor').value=list.length?String(list[0].id):'';
  }
  async function safe(url,previous,controller=new AbortController()){
    requests.set(controller,url);
    try{return await api(url,undefined,{signal:controller.signal});}catch{return {...(previous||{items:[],enabled:true,refresh_seconds:300}),transport_error:true,status:'error',stale:true,message:'Błąd połączenia z lokalnym API; ostatnie dane zachowane.'};}finally{requests.delete(controller);}
  }
  function retainSeries(result){
    // Another request for this selection may have succeeded while this read was pending.
    return result?.transport_error&&series?{...series,transport_error:true,status:'error',stale:true,message:result.message}:result;
  }
  async function loadSeries(){
    const id=$('sensor').value,run=++selection,life=epoch;
    if(!id||!active()){series=null;detailBusy=false;render();return;}
    detailBusy=true;render();const result=await safe(`/gios?kind=data&id=${id}`,series);
    if(run!==selection||life!==epoch||!active())return;
    series=retainSeries(result);detailBusy=false;render();
  }
  async function selectStation(id,pan=true){
    cancel(url=>url!=='/gios'&&!url.includes('kind=index'));$('station').value=id;const item=chosen(),run=++selection,life=epoch;
    sensors=series=null;$('sensor').replaceChildren();detailBusy=!!item;render();
    if(!item||!active())return;
    if(pan&&item.latitude!=null)map.setView([item.latitude,item.longitude],10);
    syncIndexes();const s=await safe(`/gios?kind=sensors&id=${id}`);
    if(run!==selection||life!==epoch||!active())return;
    sensors=s;detailBusy=false;sensorOptions();render();await loadSeries();
  }
  async function load(){
    if(!active()||busy)return;busy=true;const life=epoch,run=selection;
    try{
      const result=await safe('/gios',stations);
      if(life!==epoch||!active())return;
      stations=result;
      if($('station').value&&!result.items.some(i=>String(i.id)===$('station').value)){selection++;detailBusy=false;sensors=series=null;$('station').value='';$('sensor').replaceChildren();}
      if(!result.enabled&&tick!==null){clearInterval(tick);tick=null;}options($('station'),[...result.items].filter(i=>!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude)).sort((a,b)=>a.name.localeCompare(b.name,'pl')),i=>i.name,'Wybierz stację');render();
      syncIndexes();const id=$('station').value,sid=$('sensor').value;
      if(id&&run===selection){
        const [s,d]=await Promise.all([safe(`/gios?kind=sensors&id=${id}`,sensors),sid?safe(`/gios?kind=data&id=${sid}`,series):Promise.resolve(null)]);
        if(life!==epoch||run!==selection||!active())return;
        sensors=s;series=retainSeries(d);sensorOptions();
        if($('sensor').value!==sid){series=null;render();await loadSeries();}else render();
      }
    }finally{
      if(life===epoch){busy=false;if(active()&&stations?.enabled!==false)timer=setTimeout(()=>{timer=null;load();},300000);}
    }
  }
  function sync(options={}){
    if(!map)return;if(options.visible!==undefined)visible=options.visible;
    if(!active()){
      stopIndexes();cancel();epoch++;selection++;busy=detailBusy=false;if(timer!==null)clearTimeout(timer);timer=null;if(tick!==null)clearInterval(tick);tick=null;render();
    }else if(stations?.enabled!==false){
      if(tick===null)tick=setInterval(()=>{render();scheduleIndexes();},60000);
      if(!busy&&timer===null&&stations?.enabled!==false)load();
    }
  }
  function init(options){
    if(map||!options.map)return;map=options.map;api=options.api;map.createPane('giosStations').style.zIndex='476';
    for(let i=0;i<indexColors.length;i++){const entry=node('span'),swatch=node('i');swatch.style.backgroundColor=indexColors[i];entry.append(swatch,node('span',indexNames[i]));$('legend-items').append(entry);}
    const entry=node('span'),swatch=node('i');swatch.style.backgroundColor=grey;entry.append(swatch,node('span','Brak / nieaktualny indeks'));$('legend-items').append(entry);
    map.on('movestart',()=>{moving=true;stopIndexes();});map.on('moveend',()=>{moving=false;syncIndexes();});
    $('enabled').addEventListener('change',()=>sync());$('station').addEventListener('change',()=>selectStation($('station').value));
    $('parameter').addEventListener('change',()=>{cancel(url=>url.includes('kind=data'));series=null;sensorOptions();loadSeries();});
    $('sensor').addEventListener('change',()=>{cancel(url=>url.includes('kind=data'));series=null;loadSeries();});
    document.addEventListener('visibilitychange',()=>sync());sync({visible:options.visible!==false});
  }
  document.addEventListener('wici:regionchange',()=>{
    if(!map)return;
    const resumeDetail=detailBusy;
    stopIndexes();cancel();epoch++;selection++;busy=detailBusy=false;
    if(timer!==null)clearTimeout(timer);timer=null;
    const list=(stations?.items||[]).filter(i=>!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude));
    options($('station'),list.sort((a,b)=>a.name.localeCompare(b.name,'pl')),i=>i.name,'Wybierz stację');
    if(!list.some(i=>String(i.id)===$('station').value)){$('station').value='';sensors=series=null;$('sensor').replaceChildren();}
    if(stations&&active()&&stations.enabled!==false)timer=setTimeout(()=>{timer=null;load();},300000);
    render();sync();syncIndexes();
    if(resumeDetail&&active()&&chosen())selectStation($('station').value,false);
  });
  return {init,sync};
})();
