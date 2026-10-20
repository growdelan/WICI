'use strict';
// All dates are acquisition times; publication filters never enter these requests.
window.WiciSentinel2 = (() => {
  const $ = n => document.getElementById('s2-'+n);
  const text = (tag,value) => {const e=document.createElement(tag);e.textContent=value;return e;};
  let map,visible=true,generation=0,point=null,picking=false,pickGesture=null,controller=null,items={before:[],after:[]},layers=[],outline=null,marker=null,control=null,slider=null,divider=null;
  const active=()=>visible&&!document.hidden&&$('enabled').checked;
  const when=value=>value.replace('T',' ').replace(/(?:\+00:00|Z)$/,' UTC');
  const percent=value=>value>0&&value<.01?'<0,01':Number(value).toLocaleString('pl-PL',{maximumFractionDigits:2});
  const catalogLabel=item=>{
    const coverage=item.catalog_coverage_percent;
    return coverage===100?'pełny zasięg katalogowy (100%)':Number.isFinite(coverage)
      ?`UWAGA: zasięg ${percent(coverage)}%, brakuje ${percent(100-coverage)}% wg katalogu`
      :'UWAGA: nieznane pokrycie katalogowe';
  };
  const missing=result=>Number.isFinite(result.quality.missing_percent)?result.quality.missing_percent:100-result.quality.coverage;
  const coverageWarning=results=>results.some(r=>missing(r)>0)
    ?`${results.some(r=>missing(r)===100)?'Brak pokrycia jednej ze stron':'Niepełny obraz'} — przed: brak ${percent(missing(results[0]))}%; po: brak ${percent(missing(results[1]))}%. Szachownica = NoData.`:'';
  const status=value=>{$('status').textContent=value;};
  function clear(){
    generation++;controller?.abort();controller=null;if(divider){divider.remove();divider=null;}
    for(const layer of layers)map.removeLayer(layer);layers=[];
    if(control){control.remove();control=null;slider=null;}
    $('detail').replaceChildren();
  }
  function invalidate(sides=['before','after']){clear();for(const side of sides){items[side]=[];$(side).replaceChildren(new Option('Wyszukaj i wybierz obserwację',''));$(side+'-status').textContent='';}}
  async function request(path,params,signal){
    const response=await (window.WiciRegion?.fetch || fetch)('/api/sentinel2/'+path+'?'+new URLSearchParams(params),{signal});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail+(response.headers.has('Retry-After')?` Odczekaj ${response.headers.get('Retry-After')} s.`:''));
    return data;
  }
  function params(){return {lat:point.lat,lon:point.lng,size:$('size').value};}
  function pickMode(value){picking=value;pickGesture=null;if(value)map.closePopup();$('pick').setAttribute('aria-pressed',String(value));map.getContainer().style.cursor=value?'crosshair':'';}
  function choose(value){
    invalidate();pickMode(false);point={lat:Number(value.lat.toFixed(5)),lng:Number(value.lng.toFixed(5))};
    if(outline){outline.remove();outline=null;}if(marker)marker.remove();
    marker=L.circleMarker(point,{pane:'s2Point',radius:7,color:'#fff',weight:2,fillColor:'#176b8a',fillOpacity:1,interactive:false})
      .bindTooltip('Sentinel-2 · wybrany punkt',{permanent:true,direction:'top',offset:[0,-9]}).addTo(map);
    $('point').textContent=`Punkt: ${point.lat}°N, ${point.lng}°E. Bok ${$('size').value} km.`;
    status('Wybrano punkt. Wyszukaj obserwacje.');
  }
  function clip(){
    if(!slider||layers.length!==4)return;
    const ratio=Number(slider.value)/100;
    if(divider){const b=layers[0].getBounds(),lon=b.getWest()+(b.getEast()-b.getWest())*ratio;divider.setLatLngs([[b.getSouth(),lon],[b.getNorth(),lon]]);}
    for(const i of [0,2]){const image=layers[i].getElement();if(image)image.style.clipPath=`inset(0 ${(1-ratio)*100}% 0 0)`;}
    const afterMask=layers[3].getElement();if(afterMask)afterMask.style.clipPath=`inset(0 0 0 ${ratio*100}%)`;
    slider.setAttribute('aria-valuetext',`Przed: ${slider.value}%, po: ${100-Number(slider.value)}%`);
  }
  function quality(){for(const i of [2,3])if(layers[i])layers[i].setOpacity($('quality').checked?1:0);}
  async function search(){
    if(!active())return;if(!point){status('Najpierw wskaż punkt lub wybierz środek mapy.');return;}
    if(window.WiciRegion&&!window.WiciRegion.contains(point.lat,point.lng)){status('Wskaż punkt w wybranym województwie.');return;}
    invalidate();const run=generation;controller=new AbortController();status('Wyszukiwanie obserwacji CDSE…');
    const sides=['before','after'];
    const results=await Promise.allSettled(sides.map(side=>request('search',{
      ...params(),start:$(side+'-start').value,end:$(side+'-end').value,
      cloud:$('cloud').value,full_only:$('full-only').checked},controller.signal)));
    if(run!==generation||!active())return;
    let grid=null;
    const messages=results.map((result,index)=>{
      const side=sides[index],label=index?'Po':'Przed';
      let message;
      if(result.status==='rejected')message=result.reason.name==='AbortError'?'Anulowano.':result.reason.message;
      else{
        const data=result.value;items[side]=data.items||[];
        $(side).replaceChildren(new Option('Wybierz dostępną obserwację',''));
        for(const item of items[side])$(side).append(new Option(`${when(item.observed_at)} · chmury sceny ${item.cloud_cover??'brak danych'}% · ${catalogLabel(item)} · ${item.id}`,item.id));
        grid=grid||data.grid;
        const excluded=(data.excluded_partial_count||0)+(data.excluded_unknown_count||0);
        const summary=items[side].length?`${items[side].length} obserwacji${$('full-only').checked?' z pełnym zasięgiem katalogowym':''}. Wybierz obserwację.`
          :excluded?'Brak obserwacji z pełnym zasięgiem katalogowym. Zmień daty lub odznacz „Tylko pełny zasięg w katalogu”, aby świadomie wybrać niepełny obraz.'
          :'Brak obserwacji dla dat i filtra. Zmień zakres lub zachmurzenie i wybierz dostępne alternatywy.';
        message=data.status==='unconfigured'?data.message:`${data.status==='demo'?'DEMO — syntetyczne dane demonstracyjne. ':''}${summary}${excluded?` Ukryto: ${data.excluded_partial_count||0} częściowych, ${data.excluded_unknown_count||0} o nieznanym pokryciu.`:''}${data.truncated?' Wyniki katalogu ograniczono do 50 przed filtrowaniem pokrycia: zawęź daty.':''}`;
      }
      $(side+'-status').textContent=message;
      return `${label}: ${message}`;
    });
    if(grid){if(outline)outline.remove();outline=L.rectangle(grid.bounds,{color:'#1b7088',fill:false,weight:2}).addTo(map);map.fitBounds(grid.bounds,{maxZoom:14});}
    status(messages.join(' '));
  }

  async function compare(){
    clear();if(!active()||!point)return;
    const before=items.before.find(i=>i.id===$('before').value),after=items.after.find(i=>i.id===$('after').value);
    if(!before||!after||before.id===after.id||before.observed_at>=after.observed_at){status('Wybierz dwie różne obserwacje: „przed” musi być wcześniejsze niż „po”.');return;}
    const run=generation;controller=new AbortController();status('Pobieranie dwóch obserwacji i weryfikacja siatki…');
    try{
      const results=await Promise.all([before,after].map(item=>request('render',{...params(),identifier:item.id},controller.signal)));
      if(run!==generation||!active())return;
      if(JSON.stringify(results[0].grid)!==JSON.stringify(results[1].grid)||results.some((r,i)=>r.item.id!==[before,after][i].id||r.item.observed_at!==[before,after][i].observed_at))throw new Error('Niezgodna geometria lub obserwacja.');
      // Load both sides completely before publishing either one under its date.
      await Promise.all(results.flatMap(r=>['image','mask'].map(key=>new Promise((resolve,reject)=>{const image=new Image();image.onload=resolve;image.onerror=()=>reject(new Error('Błąd dekodowania obrazu.'));image.src='data:image/png;base64,'+r[key];}))));
      if(run!==generation||!active())return;
      for(const [r,key,pane] of [[results[0],'image','s2Before'],[results[1],'image','s2After'],[results[0],'mask','s2BeforeQuality'],[results[1],'mask','s2AfterQuality']]){
        layers.push(L.imageOverlay('data:image/png;base64,'+r[key],r.bounds,{pane,interactive:false,attribution:r.item.attribution}).addTo(map));
      }
      divider=L.polyline([],{pane:'s2Divider',color:'#ffffff',weight:2,interactive:false}).addTo(map);
      const warning=coverageWarning(results);
      control=L.control({position:'bottomleft'});
      control.onAdd=()=>{
        const box=L.DomUtil.create('div','s2-swipe');L.DomEvent.disableClickPropagation(box);L.DomEvent.disableScrollPropagation(box);
        const labels=text('div','');labels.className='s2-dates';labels.append(text('span','Przed · '+when(before.observed_at)),text('span','Po · '+when(after.observed_at)));box.append(labels);
        const label=text('label','Odsłoń „przed” / „po”');slider=document.createElement('input');slider.type='range';slider.min=0;slider.max=100;slider.value=50;slider.setAttribute('aria-label','Porównanie przed i po');slider.addEventListener('input',clip);label.append(slider);box.append(label);if(warning){const note=text('p',warning);note.className='s2-warning notice';note.setAttribute('role','alert');box.append(note);}return box;
      };control.addTo(map);clip();quality();
      for(const [i,r] of results.entries())$('detail').append(text('p',`${i?'Po':'Przed'}: ${when(r.item.observed_at)} · ${r.item.id}. Chmury całej sceny: ${r.item.cloud_cover??'brak danych'}%. Pokrycie obszaru: ${percent(r.quality.coverage)}%. Brakuje ${percent(missing(r))}% obrazu (NoData). W pokryciu: chmury ${r.quality.cloud}%, cienie ${r.quality.shadow}%, śnieg ${r.quality.snow}%.`));
      status(`${before.id.startsWith('DEMO')?'DEMO — syntetyczne dane demonstracyjne. ':''}${warning||'Porównanie gotowe.'} Suwak: mysz, dotyk lub strzałki klawiatury. Szachownica: NoData.`);
    }catch(error){if(run===generation&&active()){clear();status(error.name==='AbortError'?'Anulowano.':error.message);}}
  }
  function sync(options={}){
    if(!map)return;if(options.visible!==undefined)visible=options.visible;$('controls').hidden=!active();
    if(!active()){clear();pickMode(false);if(outline){outline.remove();outline=null;}if(marker){marker.remove();marker=null;}status('Warstwa Sentinel-2 wyłączona lub wstrzymana poza mapą.');}
  }
  function init(options){
    if(map||!options.map)return;map=options.map;
    for(const [name,z] of [['s2After',360],['s2Before',361],['s2AfterQuality',362],['s2BeforeQuality',363],['s2Divider',364],['s2Point',660]]){const pane=map.createPane(name);pane.style.zIndex=z;pane.style.pointerEvents='none';}
    const end=new Date(),start=new Date(end);start.setUTCDate(start.getUTCDate()-30);for(const side of ['before','after']){$(side+'-start').value=start.toISOString().slice(0,10);$(side+'-end').value=end.toISOString().slice(0,10);}
    $('enabled').addEventListener('change',async()=>{sync();if(!active())return;const run=generation;try{const data=await request('status',{});if(run===generation&&active())status(data.message);}catch(e){if(run===generation&&active())status(e.message);}});
    $('pick').addEventListener('click',()=>{pickMode(!picking);if(picking)document.getElementById('layer-panel').open=false;status(picking?'Kliknij punkt na mapie. Escape anuluje wskazywanie.':'Anulowano wskazywanie.');});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&picking)pickMode(false);});
    // Capture before Leaflet's markers/popups can consume the click. Other modes keep their normal events.
    const container=map.getContainer();
    container.addEventListener('pointerdown',event=>{
      pickGesture=active()&&picking?{x:event.clientX,y:event.clientY,moved:false}:null;
    },true);
    container.addEventListener('pointermove',event=>{
      if(pickGesture&&Math.hypot(event.clientX-pickGesture.x,event.clientY-pickGesture.y)>5)pickGesture.moved=true;
    },true);
    container.addEventListener('click',event=>{
      if(!active()||!picking||event.detail===0||event.target.closest('.leaflet-control,.leaflet-popup')
        ||map.dragging?.moved()||map.boxZoom?.moved()
        ||(pickGesture&&(pickGesture.moved||Math.hypot(event.clientX-pickGesture.x,event.clientY-pickGesture.y)>5)))return;
      const point=map.mouseEventToLatLng(event);
      event.preventDefault();event.stopImmediatePropagation();choose(point);
    },true);
    $('center').addEventListener('click',()=>choose(map.getCenter()));
    $('search').addEventListener('click',search);$('compare').addEventListener('click',compare);$('quality').addEventListener('change',quality);
    for(const name of ['cloud','size','full-only'])$(name).addEventListener('change',()=>{invalidate();if(point&&name==='size')choose(point);else status('Parametry zmienione. Wyszukaj obserwacje ponownie.');});
    for(const side of ['before','after'])for(const edge of ['start','end'])$(side+'-'+edge).addEventListener('change',()=>{invalidate([side]);status(`Zmieniono zakres „${side==='before'?'przed':'po'}”. Wyszukaj obserwacje ponownie.`);});
    for(const name of ['before','after'])$(name).addEventListener('change',()=>{clear();for(const side of ['before','after']){const item=items[side].find(i=>i.id===$(side).value);if(item)$('detail').append(text('p',`${side==='before'?'Przed':'Po'}: ${when(item.observed_at)} · ${item.id}. Chmury sceny: ${item.cloud_cover??'brak danych'}%; ${catalogLabel(item)}.`));}status('Wybór zmieniony. Kliknij „Porównaj wybrane obserwacje”.');});
    document.addEventListener('wici:regionchange',()=>{
      if(!point||!window.WiciRegion||window.WiciRegion.contains(point.lat,point.lng))return;
      invalidate();pickMode(false);point=null;
      if(outline){outline.remove();outline=null;}if(marker){marker.remove();marker=null;}
      $('point').textContent='Nie wybrano punktu.';status('Zmieniono obszar. Wskaż punkt w wybranym województwie.');
    });
  }
  return {init,sync};
})();
