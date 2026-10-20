'use strict';
// The server records observations independently of this map and browser tab.
window.WiciTracking = (() => {
  const $ = id => document.getElementById(`tracking-${id}`);
  const storageKey = 'wici.tracking.selected.v1';
  const time = value => new Intl.DateTimeFormat('pl-PL', {
    timeZone:'Europe/Warsaw',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'
  }).format(new Date(value));
  const node = (tag, text) => {const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  let map,health={},visible=false,selected='',tracks=[],track=null,points=[],cursor=null,live=true;
  let layer,line,halo,marker,timer=null,request=null,revision=0,busy=false,playTimer=null,playAt=0;
  let rendered='',fault='',loaded=false,mutationFault=false;

  function normalizePoints(raw) {
    const result=[];
    for(const item of Array.isArray(raw)?raw:[]){
      const at=Date.parse(item.position_at);
      if(!Number.isFinite(at)||!Number.isFinite(item.latitude)||!Number.isFinite(item.longitude)||
          Math.abs(item.latitude)>90||Math.abs(item.longitude)>180)continue;
      result.push({...item,at,break_before:Boolean(item.break_before)});
    }
    result.sort((a,b)=>a.at-b.at);
    return result.filter((point,index)=>!index||point.at!==result[index-1].at);
  }
  function frameAt(samples,at) {
    let low=0,high=samples.length-1,index=-1;
    while(low<=high){const mid=(low+high)>>1;if(samples[mid].at<=at){index=mid;low=mid+1;}else high=mid-1;}
    const segments=[];let segment=[];
    for(let i=0;i<=index;i++){
      if(samples[i].break_before&&segment.length){segments.push(segment);segment=[];}
      segment.push([samples[i].latitude,samples[i].longitude]);
    }
    if(segment.length)segments.push(segment);
    return {index,point:samples[index]||null,segments,
      inGap:index>=0&&index+1<samples.length&&samples[index+1].break_before&&at>samples[index].at};
  }
  const shown = () => Boolean(map)&&visible&&!document.hidden;
  const kindName = kind => kind==='aircraft'?'Samolot':'Statek';
  function remember(){try{localStorage.setItem(storageKey,selected);}catch{/* Optional preference. */}}
  function pause(){clearInterval(playTimer);playTimer=null;if($('play'))$('play').textContent='Odtwórz';}
  function showError(error){fault=error.name==='AbortError'?'Serwer nie odpowiedział. Ponowimy odczyt historii.':error.message;render();}
  async function api(path,body,signal){
    const controller=signal?null:new AbortController(),deadline=controller?setTimeout(()=>controller.abort(),15000):null;
    const options={signal:signal||controller.signal,headers:{Accept:'application/json'}};
    if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=health.csrf_token||'';options.body=JSON.stringify(body);}
    try{
      const response=await fetch(`/api/tracks${path}`,options);
      const result=await response.json();
      if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Nie udało się odczytać zapisanej trasy.');
      return result;
    }finally{if(deadline)clearTimeout(deadline);}
  }
  function updateOptions(){
    const select=$('session');
    const options=[node('option',tracks.length?'Wybierz zapisaną trasę':'Brak zapisanych tras')];options[0].value='';
    for(const item of tracks){
      const option=node('option',`${item.active?'● ':''}${kindName(item.kind)} · ${item.label||item.object_id} · ${time(item.started_at)}`);
      option.value=String(item.id);options.push(option);
    }
    const signature=options.map(option=>`${option.value}:${option.textContent}`).join('|');
    if(select.dataset.options!==signature){select.replaceChildren(...options);select.dataset.options=signature;}
    select.value=selected;
  }
  function accept(result){
    track=result.track;
    points=normalizePoints(result.points);
    if(points.length<2)pause();
    const index=tracks.findIndex(item=>String(item.id)===String(track.id));
    if(index<0)tracks.unshift(track);else tracks[index]=track;
    if(points.length){
      if(live||cursor===null)cursor=points.at(-1).at;
      else cursor=Math.max(points[0].at,Math.min(cursor,points.at(-1).at));
    }else cursor=null;
    rendered='';if(!mutationFault)fault='';updateOptions();render();
  }
  async function refresh(){
    if(!shown()||request||busy)return;
    const controller=new AbortController(),run=revision;request=controller;
    const deadline=setTimeout(()=>controller.abort(),15000);
    try{
      const result=await api('',undefined,controller.signal);
      if(run!==revision||!shown())return;
      tracks=Array.isArray(result.items)?result.items:[];loaded=true;if(!mutationFault)fault='';
      if(selected&&!tracks.some(item=>String(item.id)===selected)){selected='';track=null;points=[];cursor=null;remember();pause();}
      if(!selected&&tracks.length&&!$('panel').dataset.deselected){
        selected=String(tracks.find(item=>item.active)?.id||tracks[0].id);remember();
      }
      updateOptions();render();
      if(selected){
        const detail=await api(`/${encodeURIComponent(selected)}`,undefined,controller.signal);
        if(run===revision&&shown()&&String(detail.track.id)===selected)accept(detail);
      }
    }catch(error){if(run===revision&&shown())showError(error);}
    finally{
      clearTimeout(deadline);if(request===controller)request=null;
      if(shown()&&!busy){clearTimeout(timer);timer=setTimeout(()=>{timer=null;refresh();},tracks.length?10000:30000);}
    }
  }
  function cancelRead(){revision++;request?.abort();request=null;clearTimeout(timer);timer=null;}
  async function select(id){
    cancelRead();pause();selected=String(id||'');track=null;points=[];cursor=null;live=true;rendered='';fault='';mutationFault=false;
    $('panel').dataset.deselected=selected?'':'true';remember();updateOptions();render();await refresh();
  }
  function cursorIcon(point,history,stale){
    const box=node('span');box.className=`tracking-reticle${history?' tracking-history':''}${stale?' tracking-stale':''}`;
    box.setAttribute('aria-hidden','true');
    for(let i=0;i<4;i++)box.append(node('i'));
    const symbol=node('span');symbol.className='tracking-object';
    if(track.kind==='aircraft'){
      // Share the live layer's classification colors independently of the reticle state.
      const aircraft=node('span','✈');
      aircraft.className=track.military===true?'aircraft-symbol aircraft-military':'aircraft-symbol';
      symbol.append(aircraft);
    }else{
      const ship=node('span');
      const category=window.WiciShips.classification({type_code:track.ship_type_code}).key;
      ship.className=`ship-symbol ship-${category}${Number.isFinite(point.heading)?'':' ship-direction-unknown'}`;
      symbol.append(ship);
    }
    const heading=Number.isFinite(point.heading)?point.heading:0;
    symbol.style.transform=`rotate(${track.kind==='aircraft'?heading-90:heading}deg)`;box.append(symbol);
    return L.divIcon({className:'tracking-marker',html:box,iconSize:[48,48],iconAnchor:[24,24]});
  }
  function draw(frame,stale){
    if(!layer)return;
    if(!frame.point){layer.clearLayers();line=halo=marker=null;rendered='';return;}
    const key=`${selected}:${frame.index}:${points.length}:${live}:${stale}`;
    if(rendered===key)return;rendered=key;
    const color=live?'#087f8c':'#b56a12';
    if(!line){
      halo=L.polyline(frame.segments,{pane:'trackingRoutes',color:'#ffffff',weight:7,opacity:.85,interactive:false}).addTo(layer);
      line=L.polyline(frame.segments,{pane:'trackingRoutes',color,weight:3,opacity:1,interactive:false}).addTo(layer);
    }else{halo.setLatLngs(frame.segments);line.setLatLngs(frame.segments).setStyle({color});}
    const location=[frame.point.latitude,frame.point.longitude],icon=cursorIcon(frame.point,!live,stale);
    if(!marker){
      marker=L.marker(location,{pane:'trackingCursor',icon,keyboard:false,interactive:false,zIndexOffset:1000}).addTo(layer);
    }else marker.setLatLng(location).setIcon(icon);
  }
  function render(){
    if(!map)return;
    const hasPoints=Boolean(points.length),frame=frameAt(points,cursor??-Infinity);
    const last=points.at(-1),maxAge=track?.kind==='aircraft'?120:900;
    const stale=live&&track?.active&&last&&Date.now()-last.at>maxAge*1000;
    $('summary').textContent=track?`${track.label||track.object_id} · ${live?'ostatni zapis':'historia'}`:
      tracks.length?`${tracks.filter(item=>item.active).length} w zapisie · ${tracks.length} tras`:'Samoloty i statki';
    $('empty').hidden=Boolean(track);
    $('empty').textContent=selected?'Wczytywanie zapisanej trasy…':health.mode==='demo'?'Śledzenie jest dostępne w trybie LIVE.':
      'Kliknij samolot lub statek i wybierz „Śledź trasę”. Tutaj wrócisz do zapisanej obserwacji.';
    $('controls').hidden=!track;
    $('recording').textContent=track?.active?'ZAPIS W TLE':'ZAPIS ZAKOŃCZONY';
    $('recording').classList.toggle('is-active',Boolean(track?.active));
    $('title').textContent=track?`${kindName(track.kind)} · ${track.label||track.object_id}`:'';
    $('session').disabled=busy||!tracks.length;
    $('stop').disabled=busy||!track?.active;$('stop').hidden=!track?.active;
    $('exit').disabled=busy||!track;
    $('exit').title=track?.active?'Zakończ zapis i usuń trasę oraz zaznaczenie z mapy. Historia pozostanie dostępna.':
      'Usuń trasę oraz zaznaczenie z mapy. Historia pozostanie dostępna.';
    $('play').disabled=busy||points.length<2;$('fit').disabled=!hasPoints;
    $('live').disabled=!hasPoints;$('live').setAttribute('aria-pressed',String(live));
    $('live').textContent=track?.active?'Najnowsza pozycja':'Koniec zapisu';
    const slider=$('timeline');slider.disabled=!hasPoints||points.length<2;
    slider.min=hasPoints?String(points[0].at):'0';slider.max=hasPoints?String(last.at):'0';
    slider.value=hasPoints?String(cursor):'0';
    slider.setAttribute('aria-valuetext',hasPoints?time(cursor):'Brak zapisanych pozycji');
    $('from').textContent=hasPoints?time(points[0].at):'—';$('to').textContent=hasPoints?time(last.at):'—';
    $('time').textContent=hasPoints?time(cursor):'Oczekiwanie na pierwszy zapis';
    $('mode').textContent=live?(track?.active?'NAJNOWSZA':'KONIEC'):'HISTORIA';
    const gaps=points.reduce((n,p,i)=>n+(i>0&&p.break_before?1:0),0);
    $('metrics').textContent=hasPoints?`${points.length.toLocaleString('pl-PL')} pozycji${gaps?` · przerwy w trasie: ${gaps}`:''}`:'Brak zapisanych pozycji';
    let message=fault||track?.message||'';
    if(!message)message=track?.active?'Zapis trwa także po zamknięciu karty przeglądarki.':track?'Trasa pozostaje dostępna po zakończeniu zapisu.':loaded?'':'Wczytywanie zapisanych obserwacji…';
    if(!fault){
      if(frame.inGap)message=`Przerwa w obserwacji. Ostatni pomiar: ${time(frame.point.at)}.`;
      else if(stale)message=`Brak świeżej pozycji. Ostatni zapis: ${time(last.at)}.`;
      else if(!live&&frame.point)message=`Pomiar z ${time(frame.point.at)}${Number.isFinite(frame.point.speed_kmh)?` · ${Math.round(frame.point.speed_kmh)} km/h`:''}${Number.isFinite(frame.point.altitude_m)?` · ${Math.round(frame.point.altitude_m)} m`:''}.`;
    }
    if($('status').textContent!==message)$('status').textContent=message;
    $('status').classList.toggle('tracking-warning',Boolean(fault||stale||frame.inGap||['stale','disabled','error'].includes(track?.status)));
    if(shown())draw(frame,stale);
  }
  function fit(){
    if(!points.length)return;
    // A responsive layout can resize the container before Leaflet's resize event.
    map.invalidateSize({pan:false});
    const bounds=L.latLngBounds(points.map(point=>[point.latitude,point.longitude]));
    const size=map.getSize(),dock=$('panel').getBoundingClientRect(),mapBox=map.getContainer().getBoundingClientRect();
    const beside=size.x>dock.width+320;
    const heading=document.querySelector('.map-heading')?.getBoundingClientRect();
    const top=beside?95:Math.max(95,(heading?.bottom||mapBox.top)-mapBox.top+30);
    const bottom=beside?45:Math.min(mapBox.bottom-dock.top+30,size.y-top-25);
    map.fitBounds(bounds,{paddingTopLeft:[40,top],paddingBottomRight:[beside?dock.width+40:40,bottom],maxZoom:11,animate:false});
  }
  function playback(){
    if(playTimer){pause();return;}
    if(points.length<2)return;
    if(live||cursor>=points.at(-1).at)cursor=points[0].at;
    live=false;playAt=performance.now();$('play').textContent='Pauza';
    playTimer=setInterval(()=>{
      if(!shown()||points.length<2){pause();return;}
      const now=performance.now(),elapsed=now-playAt;playAt=now;
      cursor=Math.min(points.at(-1).at,cursor+elapsed*Number($('speed').value));
      if(cursor>=points.at(-1).at)pause();
      render();
    },100);
    render();
  }
  async function start(kind,objectId,button){
    if(busy||!map)return;
    busy=true;cancelRead();$('panel').open=true;fault='';mutationFault=false;
    if(button)button.disabled=true;render();$('status').textContent='Rozpoczynanie zapisu trasy…';
    try{
      const result=await api('',{kind,object_id:String(objectId)});
      pause();selected=String(result.track.id);live=true;cursor=null;$('panel').dataset.deselected='';
      remember();accept(result);map.closePopup();fit();$('live').focus();
    }catch(error){mutationFault=true;showError(error);}
    finally{busy=false;if(button)button.disabled=false;render();refresh();}
  }
  async function stop(){
    if(busy||!track?.active)return;
    const id=selected;busy=true;mutationFault=false;cancelRead();pause();render();
    $('status').textContent='Kończenie zapisu trasy…';
    try{
      const result=await api(`/${encodeURIComponent(id)}/stop`,{});
      if(selected===id)accept(result);
      return true;
    }catch(error){mutationFault=true;showError(error);return false;}
    finally{busy=false;render();refresh();}
  }
  async function exit(){
    if(busy||!track)return;
    if(track.active&&!await stop())return;
    const clearing=select('');
    $('panel').open=false;
    $('heading').focus();
    await clearing;
  }
  function button(kind,getItem){
    const control=node('button','Śledź trasę');control.type='button';
    control.addEventListener('click',()=>{const item=getItem();start(kind,kind==='aircraft'?item.hex:item.mmsi,control);});
    return control;
  }
  function sync(options={}){
    if(options.health)health=options.health;if(options.visible!==undefined)visible=options.visible;
    if(!map)return;
    if(!shown()){cancelRead();pause();if(layer&&map.hasLayer(layer))map.removeLayer(layer);return;}
    if(!map.hasLayer(layer))layer.addTo(map);render();
    if(!timer&&!request&&!busy)refresh();
  }
  function init(options){
    if(map||!options.map||!$('panel'))return;
    map=options.map;health=options.health||{};
    try{
      const saved=localStorage.getItem(storageKey);selected=saved||'';
      if(saved==='')$('panel').dataset.deselected='true';
    }catch{/* Optional preference. */}
    map.createPane('trackingRoutes').style.zIndex='605';
    map.createPane('trackingCursor').style.zIndex='640';
    map.getPane('trackingRoutes').style.pointerEvents='none';map.getPane('trackingCursor').style.pointerEvents='none';
    layer=L.layerGroup();
    $('session').addEventListener('change',()=>select($('session').value));
    $('timeline').addEventListener('input',()=>{pause();live=false;cursor=Number($('timeline').value);render();});
    $('timeline').addEventListener('keydown',event=>{
      if(!points.length||!['ArrowLeft','ArrowRight','ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
      event.preventDefault();pause();live=false;
      const first=points[0].at,last=points.at(-1).at;
      cursor=event.key==='Home'?first:event.key==='End'?last:
        Math.max(first,Math.min(last,cursor+(['ArrowRight','ArrowUp'].includes(event.key)?10000:-10000)));
      render();
    });
    $('play').addEventListener('click',playback);
    $('live').addEventListener('click',()=>{pause();live=true;cursor=points.at(-1)?.at??null;render();refresh();});
    $('fit').addEventListener('click',fit);$('stop').addEventListener('click',stop);
    $('exit').addEventListener('click',exit);
    render();
  }
  return {init,sync,start,button,normalizePoints,frameAt};
})();
