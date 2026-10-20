'use strict';
window.WiciHydro = (() => {
  const $ = id => document.getElementById(`hydro-${id}`);
  const node = (tag,text) => {const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
  const date = value => value ? new Intl.DateTimeFormat('pl-PL',{timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'short'}).format(new Date(value)) : 'Nie podano';
  const states={active:'Obowiązuje',upcoming:'Zapowiedziane',expired:'Ważność upłynęła',unknown:'Nieznana ważność'};
  let map,api,visible=true,layer,tick=null;
  const stationMarkers=new Map();
  const data={},runs={stations:0,warnings:0},timers={},pending={};
  const shown = kind => visible&&!document.hidden&&$(kind).checked;
  function stale(result){return !!result.stale||!result.fetched_at||Date.now()-Date.parse(result.fetched_at)>600000;}
  function current(measurement){
    if(measurement.value==null)return 'Brak danych';
    const age=Date.now()-Date.parse(measurement.observed_at);
    if(!Number.isFinite(age))return 'Brak czasu pomiaru';
    return age < -900000 ? 'Przyszły czas pomiaru' : age>10800000 ? 'NIEAKTUALNY POMIAR' : '';
  }
  function stationBody(item){
    const body=node('div');body.className='hydro-station-popup';
    body.append(node('h3',`${item.name} · ${item.river||'Rzeka niepodana'}`),node('p',`Województwo: ${item.province||'Nie podano'} · ID: ${item.id}`));
    if(stale(data.stations))body.append(node('p','NIEAKTUALNY ODCZYT ŹRÓDŁA — aktualność niepotwierdzona.'));
    for(const [key,label] of [['water_level','Stan wody'],['discharge','Przepływ'],['temperature','Temperatura wody']]){
      const m=item.measurements[key],notice=m.value==null?'':current(m);
      body.append(node('p',`${label}: ${m.value==null?'Brak danych':`${m.value} ${m.unit}`} · ${date(m.observed_at)}${notice?` · ${notice}`:''}`));
    }
    body.append(node('p',`Próg ostrzegawczy: ${item.warning_level_cm??'Nie podano'} cm · alarmowy: ${item.alarm_level_cm??'Nie podano'} cm`));
    if(item.latitude==null)body.append(node('p','Źródło nie podało prawidłowej lokalizacji; stacja dostępna tylko na liście.'));
    const link=node('a','IMGW-PIB · dane źródłowe');link.href=data.stations.source_url;link.target='_blank';link.rel='noopener noreferrer';body.append(link);return body;
  }
  function warningState(item){
    const start=Date.parse(item.valid_from),end=Date.parse(item.valid_until);
    if(!Number.isFinite(start)||(!item.open_ended&&!Number.isFinite(end))||(Number.isFinite(end)&&end<start))return 'unknown';
    return Number.isFinite(end)&&end<=Date.now()?'expired':start>Date.now()?'upcoming':'active';
  }
  function stationOptions(){
    const selected=$('station').value;$('station').replaceChildren();
    const first=node('option','Wybierz wodowskaz');first.value='';$('station').append(first);
    for(const item of [...(data.stations?.items||[])].filter(i=>!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude)).sort((a,b)=>a.name.localeCompare(b.name,'pl'))){const option=node('option',`${item.name} · ${item.river||'IMGW'}`);option.value=item.id;$('station').append(option);}
    $('station').value=selected;stationDetail();
  }
  function stationDetail(){
    const root=$('station-detail');root.replaceChildren();
    const item=data.stations?.items.find(i=>i.id===$('station').value);
    if(item)root.append(stationBody(item));
  }
  function drawStations(){
    if(!shown('stations')||!data.stations?.enabled){
      if(layer)map.removeLayer(layer);layer=null;stationMarkers.clear();return;
    }
    if(!layer)layer=L.layerGroup().addTo(map);
    const retained=new Set();
    for(const item of data.stations.items){
      if(window.WiciRegion&&!window.WiciRegion.contains(item.latitude,item.longitude))continue;
      if(!Number.isFinite(item.latitude)||!Number.isFinite(item.longitude))continue;
      const m=item.measurements.water_level;
      let color='#6b7780';
      if(!stale(data.stations)&&!current(m)){
        if(item.alarm_level_cm!=null&&m.value>=item.alarm_level_cm)color='#c32b35';
        else if(item.warning_level_cm!=null)color=m.value>=item.warning_level_cm?'#c87508':'#167cba';
      }
      retained.add(item.id);
      let marker=stationMarkers.get(item.id);
      if(!marker){
        marker=L.circleMarker([item.latitude,item.longitude],{pane:'hydroStations',radius:5,weight:2,fillOpacity:.7,bubblingMouseEvents:false});
        marker.bindTooltip(node('span',`${item.name} · ${item.river||'IMGW'}`))
          .bindPopup(()=>stationBody(marker.hydroItem),{maxWidth:360,maxHeight:340});
        stationMarkers.set(item.id,marker);marker.addTo(layer);
      }
      marker.hydroItem=item;
      marker.setLatLng([item.latitude,item.longitude]).setStyle({color,fillColor:color});
      marker.setTooltipContent(node('span',`${item.name} · ${item.river||'IMGW'}`));
      if(marker.isPopupOpen())marker.getPopup().update();
    }
    for(const [id,marker] of stationMarkers)if(!retained.has(id)){layer.removeLayer(marker);stationMarkers.delete(id);}
    stationDetail();
  }
  function drawWarnings(){
    const root=$('warning-list'),expanded=new Set([...root.children].filter(e=>e.open).map(e=>e.hydroId));root.replaceChildren();
    if(!shown('warnings')||!data.warnings?.enabled)return;
    const filter=$('filter').value.trim().toLocaleLowerCase('pl');
    const items=data.warnings.items.filter(item=>!window.WiciRegion?.code()||item.areas.some(a=>window.WiciRegion.matchesProvince(a.province))).filter(item=>[item.event,...item.areas.map(a=>`${a.province} ${a.description}`)].join(' ').toLocaleLowerCase('pl').includes(filter));
    root.append(node('p',`${items.length} ostrzeżeń w wykazie${filter?' dla filtra':''}.`));
    for(const item of items){
      const detail=node('details'),state=warningState(item);detail.hydroId=item.id;detail.open=expanded.has(item.id);
      detail.append(node('summary',`${item.event} · ${item.severity?`stopień ${item.severity}`:item.severity_code==='-1'?'bez stopnia':`stopień nieznany (${item.severity_code})`} · ${states[state]}`));
      if(stale(data.warnings))detail.append(node('p','NIEAKTUALNY ODCZYT ŹRÓDŁA — sprawdź ostrzeżenie u wydawcy.'));
      detail.append(node('p',`Nr ${item.number||'nie podano'} · ${item.office}`),node('p',`Publikacja: ${date(item.published_at)}`),
        node('p',`Od: ${date(item.valid_from)} · do: ${item.open_ended?'Bez określonego końca (kod źródła 9999)':date(item.valid_until)}`));
      if(state==='unknown')detail.append(node('p',`Okres w źródle: ${item.source_valid_from||'Nie podano'} – ${item.source_valid_until||'Nie podano'} (czas polski).`));
      detail.append(node('p',item.description));
      if(item.comment)detail.append(node('p',`Uwagi: ${item.comment}`));
      detail.append(node('p',`Prawdopodobieństwo: ${item.probability_percent==null?'Nie podano':`${item.probability_percent}%`}`));
      for(const area of item.areas)detail.append(node('p',`${area.description||area.province} · kody zlewni: ${area.basin_codes.join(', ')||'Nie podano'}`));
      root.append(detail);
    }
  }
  function report(kind){
    const result=data[kind],enabled=shown(kind),status=$(kind+'-status');
    $(kind==='stations'?'station-controls':'warning-controls').hidden=!enabled||!result?.enabled;
    if(!enabled){status.textContent=$(kind).checked?'Pobieranie hydrologii wstrzymane poza widoczną mapą.':'Warstwa hydrologiczna wyłączona.';return;}
    if(!result){status.textContent='Wczytywanie IMGW…';return;}
    let counts='';
    if(kind==='stations'&&result.enabled){const scoped=result.items.filter(i=>!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude));const old=scoped.filter(i=>!!current(i.measurements.water_level)).length;const unmapped=scoped.filter(i=>i.latitude==null).length;counts=` · ${old} bez aktualnego stanu wody · ${unmapped} bez punktu na mapie`;}
    status.textContent=`${result.items.filter(i=>kind!=='stations'||!window.WiciRegion||window.WiciRegion.contains(i.latitude,i.longitude)).length} ${kind==='stations'?'stacji':'ostrzeżeń'}${counts} · odczyt: ${date(result.fetched_at)}${stale(result)&&result.enabled?' · NIEAKTUALNY ODCZYT':''}${result.message?` · ${result.message}`:''}`;
    status.classList.toggle('notice',result.status==='error'||result.status==='partial'||(result.enabled&&stale(result)));
  }
  function render(kind){report(kind);if(kind==='stations')drawStations();else drawWarnings();}
  async function load(kind){
    if(!shown(kind)||pending[kind])return;
    pending[kind]=true;const run=runs[kind];report(kind);
    try{
      const result=await api(`/hydro?kind=${kind}`);
      if(run!==runs[kind]||!shown(kind))return;
      data[kind]=result;
      if(kind==='stations'){
        stationOptions();
      }
      render(kind);
    }catch{
      if(run!==runs[kind]||!shown(kind))return;
      data[kind]={...(data[kind]||{items:[],enabled:true}),stale:true,status:'error',message:'Nie udało się odświeżyć hydrologii; ponowna próba za 5 minut.'};render(kind);
    }finally{
      if(run===runs[kind]){pending[kind]=false;if(shown(kind)&&data[kind]?.enabled!==false)timers[kind]=setTimeout(()=>{timers[kind]=null;load(kind);},300000);}
    }
  }
  function sync(options={}){
    if(!map)return;if(options.visible!==undefined)visible=options.visible;
    for(const kind of ['stations','warnings']){
      if(!shown(kind)){
        runs[kind]++;pending[kind]=false;if(timers[kind])clearTimeout(timers[kind]);timers[kind]=null;render(kind);
      }else if(!pending[kind]&&!timers[kind]&&data[kind]?.enabled!==false)load(kind);
    }
    // app.js synchronizes layers on every health reload; keep the existing clock deadline.
    if(shown('stations')||shown('warnings')){
      if(tick===null)tick=setInterval(()=>{for(const kind of ['stations','warnings'])if(shown(kind)&&data[kind])render(kind);},60000);
    }else if(tick!==null){clearInterval(tick);tick=null;}
  }
  function init(options){
    if(map||!options.map)return;map=options.map;api=options.api;
    map.createPane('hydroStations').style.zIndex='475';
    for(const kind of ['stations','warnings'])$(kind).addEventListener('change',()=>sync());
    $('filter').addEventListener('input',drawWarnings);
    $('station').addEventListener('change',()=>{stationDetail();const item=data.stations?.items.find(i=>i.id===$('station').value);if(item?.latitude!=null)map.setView([item.latitude,item.longitude],10);});
    sync({visible:options.visible!==false});
  }
  document.addEventListener?.('wici:regionchange',()=>{if(map){stationOptions();for(const kind of ['stations','warnings'])render(kind);}});
  return {init,sync};
})();
