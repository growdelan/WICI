'use strict';
window.WiciGFMAuto = (() => {
  const $=name=>document.getElementById('gfm-'+name);
  const node=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el;};
  const date=value=>value?new Date(value).toLocaleString('pl-PL',{timeZone:'Europe/Warsaw'}):'Nie podano';
  let map,api,active=false,generation=0,pending=false,request=null,timer=null,viewTimer=null,group=null,canvas=null,data=null,signature=null;
  const shown=()=>active&&!document.hidden;
  function cancel(){generation++;request?.abort();request=null;pending=false;if(timer!==null)clearTimeout(timer);if(viewTimer!==null)clearTimeout(viewTimer);timer=viewTimer=null;}
  function body(feature){
    const p=feature.properties.product,b=node('div','');
    b.append(node('strong',`${feature.properties.pixels} wykrytych pikseli źródłowych 20 m`),
      node('p',`Obserwacja: ${date(p.observed_at)} · wiek: ${Math.max(0,Math.floor((Date.now()-Date.parse(p.observed_at))/3600000))} h${Date.now()-Date.parse(p.observed_at)>86400000?' · NIEAKTUALNA (>24 h)':''}`),
      node('p',`Przetwarzanie: ${date(p.processed_at)} · pobranie metadanych: ${date(p.fetched_at)}`),
      node('p',`${p.id} · ${p.version||'wersja niepodana'}`),
      node('p',`Advisory flags: ${feature.properties.flags.join(', ')} (255 = brak danych). Likelihood klasyfikacji: ${feature.properties.likelihood.join(', ')} (255 = brak danych), nie prognoza powodzi.`));
    const a=node('a','Copernicus GFM · produkt źródłowy');a.href=p.source_url;a.target='_blank';a.rel='noopener noreferrer';
    b.append(a,node('p',p.attribution));return b;
  }
  function opacity(){
    if(!group)return;const value=Number($('opacity').value);
    group.eachLayer(layer=>{if(layer.setStyle)layer.setStyle({opacity:value,fillOpacity:.7*value});});
  }
  function draw(result,key){
    const detail=map.getZoom()>=10;
    const next=`${result.revision}:${key}:${detail}`;if(signature===next)return;
    signature=next;group.clearLayers();
    if(!result.enabled)return;
    const attribution=p=>`Contains modified Copernicus Emergency Management Service information [${p.observed_at.slice(0,4)}]`;
    const credits=[...new Set((result.clusters||[]).map(f=>attribution(f.properties.product)))].join(' · ');
    if(detail&&result.features?.length){
      const layer=L.geoJSON({type:'FeatureCollection',features:result.features},{pane:'gfmDetections',renderer:canvas,attribution:credits,
        style:{color:'#b60050',weight:1,fillColor:'#e11e69',fillOpacity:.7},
        onEachFeature:(feature,item)=>item.bindPopup(()=>body(feature),{maxWidth:380,maxHeight:330})});
      layer.addTo(group);
    }
    // Markers locate groups, not flood extents; remain available when detail is capped or not yet loaded.
    if(!detail||result.truncated||!result.features?.length)for(const feature of result.clusters||[]){
      const [lon,lat]=feature.geometry.coordinates;
      L.circleMarker([lat,lon],{pane:'gfmDetections',renderer:canvas,attribution:attribution(feature.properties.product),radius:6,weight:2,color:'#b60050',fillColor:'#e11e69',fillOpacity:.8})
        .bindTooltip(`GFM · ${feature.properties.pixels} pikseli · ${date(feature.properties.product.observed_at)}`)
        .bindPopup(()=>{const b=body(feature);const button=node('button','Przybliż wykrycia');button.type='button';button.addEventListener('click',()=>map.setView([lat,lon],13));b.append(button);return b;},{maxWidth:380,maxHeight:350}).addTo(group);
    }
    opacity();
  }
  function report(){
    if(!shown()||!data)return;
    const d=data;
    if(!d.enabled){$('status').textContent=d.message||'GFM wyłączone.';return;}
    const age=d.checked_at?Date.now()-Date.parse(d.checked_at):Infinity;
    $('status').textContent=`Automatycznie · Polska · ostatnie 48 h. ${d.busy?'Odczyt w toku. ':''}Przetworzono ${d.processed||0}/${d.products||0} produktów. ${d.pixels?`${d.pixels} wykrytych pikseli po uwzględnieniu nowszych ocen.`:'Brak wykryć w dotychczas ocenionych pikselach; nie oznacza pełnego pokrycia ani braku powodzi.'} Katalog: ${date(d.checked_at)}.${age>900000?' Sprawdzenie katalogu nieaktualne / jeszcze niezakończone.':''}${d.unavailable?` ${d.unavailable} produktów bez wymaganych masek.`:''}${d.failed?` ${d.failed} nieudanych odczytów.`:''}${d.truncated?' Ograniczony wynik — osiągnięto limit danych.':''}${d.message?` ${d.message}`:''}`;
  }
  async function load(){
    if(!shown()||pending)return;
    const view=map.getBounds(),box=window.WiciRegion?window.WiciRegion.viewBox(view):[view.getWest(),view.getSouth(),view.getEast(),view.getNorth()];
    if(!box){group.clearLayers();signature=null;$('status').textContent='Przesuń mapę do wybranego województwa.';return;}
    pending=true;const run=generation;
    const controller=new AbortController();request=controller;
    const key=(window.WiciRegion?.code()||map.getZoom()>=10)?box.map(v=>Math.round(v*100000)/100000).join(','):'';
    if(!data)$('status').textContent='Sprawdzanie nowych obserwacji GFM dla Polski…';
    try{
      const result=await api('/gfm/monitor'+(key?'?'+new URLSearchParams({bbox:key}):''),undefined,{timeoutMs:55000,signal:controller.signal});
      if(run!==generation||!shown())return;
      data=result;draw(result,key);report();
    }catch(error){
      if(run!==generation||!shown())return;
      $('status').textContent=`Błąd automatycznego odczytu GFM: ${error.message}. Poprzednie odczyty zachowano; kolejna próba za 30 s.`;
    }finally{
      if(request===controller)request=null;
      if(run===generation){pending=false;if(shown()&&data?.enabled!==false)timer=setTimeout(()=>{timer=null;load();},1000*Math.max(3,Math.min(60,data?.poll_after_seconds||30)));}
    }
  }
  function viewChanged(){
    if(!shown())return;cancel();viewTimer=setTimeout(()=>{viewTimer=null;load();},500);
  }
  function sync(options){
    if(!map)return;const next=options.active===true&&!document.hidden;
    if(!next){if(active||pending||timer!==null||viewTimer!==null)cancel();active=false;group.clearLayers();signature=null;return;}
    active=true;report();if(data?.enabled===false)return;if(!pending&&timer===null&&viewTimer===null)load();
  }
  function init(options){
    if(map)return;map=options.map;api=options.api;
    map.createPane('gfmDetections').style.zIndex='440';canvas=L.canvas({pane:'gfmDetections'});group=L.layerGroup().addTo(map);
    document.addEventListener?.('wici:regionchange',viewChanged);
    map.on('moveend',viewChanged);map.on('zoomend',viewChanged);$('opacity').addEventListener('input',opacity);
  }
  return {init,sync};
})();
