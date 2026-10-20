'use strict';
window.WiciLightning = (() => {
  const $ = id => document.getElementById(`lightning-${id}`);
  const node = (tag,text) => { const e=document.createElement(tag);if(text!=null)e.textContent=text;return e; };
  const date = value => new Intl.DateTimeFormat('pl-PL',{timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'short'}).format(new Date(value));
  let map,api,data,layer,pending,visible=true,generation=0,imageRun=0,pointRun=0,fetching=false,refresh=null,selected=null,shownFrame=null,popup=null,legendReady=false;
  const shown = () => visible && !document.hidden && $('enabled').checked;
  function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('notice',error);}
  function closePopup(){pointRun++;if(popup)map.closePopup(popup);popup=null;}
  function removePending(){imageRun++;if(pending)map.removeLayer(pending);pending=null;}
  function report(){
    if(!shown()){status($('enabled').checked?'Wyładowania wstrzymane poza widoczną mapą.':'Warstwa wyładowań wyłączona.');return;}
    if(!data?.enabled){status(data?.message||'Wczytywanie EUMETSAT…',!!data);return;}
    const frame=shownFrame;
    status(`${frame?`Okres ${date(frame.time)} – ${date(frame.end)}`:'Wczytywanie obrazu'} · koniec najnowszych danych ${data.delay_minutes??'—'} min temu${data.message?` · ${data.message}`:''}`,data.stale||data.status==='error');
  }
  function controls(){
    $('time').disabled=!shown()||!data?.frames?.length;
    $('legend').hidden=!shown()||!layer||!legendReady;
  }
  function detail(event){
    if(!shown()||!shownFrame)return;
    closePopup();const run=pointRun,frame=shownFrame,point=event.latlng;
    if(window.WiciRegion&&!window.WiciRegion.contains(point.lat,point.lng))return;
    const box=node('div','Wczytywanie szczegółów obserwacji…');
    popup=L.popup({maxWidth:340,maxHeight:300}).setLatLng(point).setContent(box).openOn(map);
    popup.on('remove',()=>{pointRun++;popup=null;});
    api(`/lightning/point?time=${frame.timestamp}&lat=${point.lat}&lon=${point.lng}`).then(result=>{
      if(run!==pointRun||!shown()||shownFrame!==frame)return;
      const body=node('div');body.append(node('h3','Wykryta aktywność wyładowań'),node('p',result.visible_activity?'W tym pikselu obraz EUMETSAT pokazuje aktywność wyładowań.':'W tym pikselu obrazu nie ma widocznego sygnału; to nie potwierdza braku burzy.'));
      body.append(node('p',`Okres: ${date(result.period_start)} – ${date(result.period_end)}`),node('p',`Kliknięcie: ${point.lat.toFixed(3)}°N, ${point.lng.toFixed(3)}°E. Odczyt wizualizacji, nie dokładna lokalizacja pioruna.`));
      if(result.stale)body.append(node('p','Dane są opóźnione lub nieaktualne.'));
      body.append(node('p','LI obserwuje także wyładowania w chmurach. Nie rozróżnia wyładowań doziemnych; mapa nie podaje liczby pojedynczych uderzeń.'));
      const link=node('a','EUMETSAT · opis produktu');link.href=data.source_url;link.target='_blank';link.rel='noopener noreferrer';body.append(link);popup.setContent(body);
    }).catch(()=>{if(run===pointRun&&popup)popup.setContent(node('p','Nie udało się odczytać szczegółów EUMETSAT.'));});
  }
  function draw(){
    removePending();controls();if(!shown()||!data?.enabled||!data.frames.length){report();return;}
    const frame=data.frames.find(f=>f.timestamp===selected)||data.frames.at(-1);
    selected=frame.timestamp;$('time').value=String(selected);
    const run=imageRun,session=generation;
    const next=L.imageOverlay(frame.image_url,data.bounds,{pane:'lightningActivity',opacity:0,interactive:true,bubblingMouseEvents:false,attribution:'© EUMETSAT · <a href="https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Ali_afa" target="_blank" rel="noopener noreferrer">LI AFA</a>'});pending=next;
    next.on('load',()=>queueMicrotask(()=>{
      if(run!==imageRun||session!==generation||!shown())return;
      closePopup();if(layer)map.removeLayer(layer);layer=next;pending=null;shownFrame=frame;next.setOpacity(1);controls();report();
    }));
    next.on('error',()=>queueMicrotask(()=>{
      if(run!==imageRun||session!==generation||!shown())return;
      map.removeLayer(next);pending=null;status('Nie udało się pobrać obrazu wyładowań. Zachowano poprzedni okres, jeśli był dostępny.',true);
      if(shownFrame){selected=shownFrame.timestamp;$('time').value=String(selected);}
    }));
    next.on('click',detail);status(`Wczytywanie okresu ${date(frame.time)} – ${date(frame.end)}…`);next.addTo(map);
  }
  function schedule(){if(refresh!==null)clearTimeout(refresh);refresh=null;if(shown())refresh=setTimeout(load,300000);}
  async function load(){
    if(!shown()||fetching)return;fetching=true;const run=generation;
    if(!data)status('Wczytywanie EUMETSAT…');
    try{
      const result=await api('/lightning');if(run!==generation||!shown())return;
      const follow=selected===data?.frames?.at(-1)?.timestamp;
      data=result;
      if(follow||!data.frames.some(f=>f.timestamp===selected))selected=data.frames.at(-1)?.timestamp??null;
      $('time').replaceChildren();
      for(const frame of data.frames){const option=node('option',`${date(frame.time)} – ${date(frame.end)}`);option.value=String(frame.timestamp);$('time').append(option);}
      $('time').value=String(selected??'');
      if(!data.enabled||!data.frames.length){removePending();if(layer)map.removeLayer(layer);layer=null;shownFrame=null;closePopup();controls();report();return;}
      if(!legendReady){$('legend-image').src=data.legend_url;}
      if(shownFrame?.timestamp===selected&&layer){report();controls();}else draw();
    }catch{
      if(run!==generation||!shown())return;
      if(data)data={...data,stale:true};status('Nie udało się odświeżyć EUMETSAT; zachowano ostatni obraz.',true);
    }finally{if(run===generation){fetching=false;schedule();}}
  }
  function sync(options={}){
    if(!map)return;if(options.visible!==undefined)visible=options.visible;
    if(!shown()){
      generation++;fetching=false;removePending();closePopup();
      if(refresh!==null)clearTimeout(refresh);refresh=null;
      if(layer)map.removeLayer(layer);layer=null;shownFrame=null;controls();report();return;
    }
    if(!data||refresh===null)load();
    if(data&&data.enabled&&!layer&&!pending&&!fetching)draw();
  }
  function init(options){
    if(map||!options.map)return;map=options.map;api=options.api;
    map.createPane('lightningActivity').style.zIndex='440';
    $('enabled').addEventListener('change',()=>sync());
    $('time').addEventListener('change',()=>{selected=Number($('time').value);closePopup();draw();});
    $('legend-image').addEventListener('load',()=>{legendReady=true;controls();});
    $('legend-image').addEventListener('error',()=>{legendReady=false;controls();if(shown())status('Oficjalna legenda EUMETSAT niedostępna; spróbuj ponownie przy odświeżeniu.',true);});
    sync({visible:options.visible!==false});
  }
  return {init,sync};
})();
