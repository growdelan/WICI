'use strict';
window.WiciGFM = (() => {
  const $ = name => document.getElementById('gfm-'+name);
  const node = (tag,text) => {const el=document.createElement(tag);el.textContent=text;return el;};
  const date = value => value ? new Date(value).toLocaleString('pl-PL',{timeZone:'Europe/Warsaw'}) : 'Nie podano';
  const historicalBox=[16.55,50.35,16.75,50.55];
  const historicalObservation='ENSEMBLE_FLOOD_20240915T050149_VV_EU020M_E051N018T3';
  let map,api,visible=true,generation=0,overlay=null,items=[],box=null,selected=null,tick=null;
  const shown=()=>visible&&!document.hidden&&$('enabled').checked;
  const status=text=>{$('status').textContent=text;};
  function clear(){generation++;selected=null;if(tick!==null){clearInterval(tick);tick=null;}if(overlay){map.removeLayer(overlay);overlay=null;}$('detail').replaceChildren();}
  function report(){
    if(!selected||!shown())return;
    const elapsed=Date.now()-Date.parse(selected.product.observed_at);
    const age=Number.isFinite(elapsed)?`${Math.max(0,Math.floor(elapsed/3600000))} h`:'nieznany';
    const messages={flood:'Wykryto zalanie w chwili obserwacji.',no_detection:'Brak wykrytego zalania w ocenionych pikselach źródłowych.',excluded:'Obszar wykluczony z oceny.',no_coverage:'Brak pokrycia / obserwacji w pikselach produktu.',reference_water:'Woda referencyjna; brak ocenionych pikseli lądu.'};
    const omitted=selected.source_counts?.flood>0&&selected.counts.flood===0;
    status(`${messages[selected.status]||'Odczyt zakończony.'} ${elapsed>86400000?'OBSERWACJA ARCHIWALNA / NIEAKTUALNA (>24 h). ':''}Wiek: ${age}. ${omitted?'Wykrycia w pikselach źródłowych są zbyt drobne dla tej nakładki — przybliż mapę i wyszukaj mniejszy obszar. ':''}Brak detekcji nie potwierdza bezpieczeństwa ani braku powodzi.`);
  }
  function sync(options={}){
    if(!map)return;if(options.visible!==undefined)visible=options.visible;
    $('controls').hidden=!shown();
    const automatic=$('mode').value==='auto';
    $('manual').hidden=automatic;$('automatic-note').hidden=!automatic;$('legend').className=automatic?'gfm-legend automatic':'gfm-legend';
    window.WiciGFMAuto?.sync({active:shown()&&automatic});
    if(!shown()){clear();$('observation').value='';status($('enabled').checked?'GFM wstrzymane poza widoczną mapą.':'Warstwa GFM wyłączona.');}
    else if(automatic){if(selected||overlay)clear();}
    else report();
  }
  function bounds(){
    const view=map.getBounds(),box=window.WiciRegion?window.WiciRegion.viewBox(view):[view.getWest(),view.getSouth(),view.getEast(),view.getNorth()];return box?.map(x=>Math.round(x*100000)/100000);
  }
  async function search(options={}){
    if(!shown())return;window.WiciGFMAuto?.sync({active:false});$('mode').value='manual';$('manual').hidden=false;$('automatic-note').hidden=true;$('legend').className='gfm-legend';clear();const run=generation;box=options.box?[...options.box]:bounds();
    if(!box){$('observation').replaceChildren();$('observation').disabled=true;items=[];$('area').textContent='Brak wspólnego obszaru mapy i regionu.';status('Przesuń mapę do wybranego województwa.');return;}
    $('area').textContent=`${options.observation?'Stały obszar próby historycznej':'Wybrany obszar mapy'}: ${box[0]}–${box[2]}°E, ${box[1]}–${box[3]}°N.`;
    $('observation').replaceChildren();$('observation').disabled=true;items=[];status('Wyszukiwanie GFM dla wybranego obszaru…');
    try{
      const result=await api('/gfm?'+new URLSearchParams({bbox:box.join(','),start:$('start').value,end:$('end').value}),undefined,{timeoutMs:55000});
      if(run!==generation||!shown())return;
      items=result.items||[];
      const empty=node('option','Wybierz obserwację');empty.value='';$('observation').append(empty);
      for(const item of items){const o=node('option',`${date(item.observed_at)} · ${item.id}`);o.value=item.id;if(item.renderable===false){o.disabled=true;o.textContent+=` · niedostępny: brak ${item.missing_assets.join(', ')}`;}$('observation').append(o);}
      $('observation').disabled=!items.some(item=>item.renderable!==false);
      status(result.message||`${items.length} produktów${result.truncated?' · Ograniczono do 24; zawęź daty, aby zobaczyć pozostałe.':''}. ${items.length?'Wybierz konkretną obserwację.':'Brak produktów w sprawdzonej części katalogu; nie oznacza braku powodzi.'}`);
      if(options.observation&&result.enabled!==false){
        const item=items.find(item=>item.id===options.observation&&item.renderable!==false);
        if(item){$('observation').value=item.id;await select();}
        else status('Próba historyczna: źródło nie udostępniło sprawdzonej obserwacji z kompletem masek. Wybierz inną obserwację, jeśli jest dostępna.');
      }
    }catch(error){if(run===generation&&shown())status(`Błąd wyszukiwania GFM: ${error.message}`);}
  }
  async function select(){
    clear();if(!shown())return;const run=generation,id=$('observation').value;
    if(!id||!box){status('Wybierz obserwację z wyników wyszukiwania.');return;}status('Odczyt pikseli GFM i reprojekcja…');
    try{
      const result=await api(`/gfm/render/${encodeURIComponent(id)}?`+new URLSearchParams({bbox:box.join(',')}),undefined,{timeoutMs:55000});
      if(run!==generation||!shown()||id!==$('observation').value)return;
      const image=L.imageOverlay('data:image/png;base64,'+result.image,result.bounds,{pane:'gfmPixels',interactive:false,opacity:Number($('opacity').value),attribution:result.product.attribution});
      image.on('error',()=>{if(run===generation){clear();status('Błąd wyświetlania rastra GFM.');}});
      overlay=image;image.addTo(map);
      const p=result.product,c=result.counts;
      selected=result;report();tick=setInterval(report,60000);
      const root=$('detail');
      root.append(node('p',`Obserwacja: ${date(p.observed_at)} · przetwarzanie: ${date(p.processed_at)} · wpis STAC: ${date(p.catalog_created_at)} · pobranie metadanych: ${date(p.fetched_at)} · pobranie rastra: ${date(result.rendered_at)}`));
      root.append(node('p',`Produkt: ${p.id} · ${p.version||'wersja niepodana'} · ${p.facility||'EODC'} · ${p.lineage||'Copernicus GFM'}`));
      root.append(node('p',`Próbki na nakładce (nie powierzchnia): zalanie ${c.flood}, woda referencyjna ${c.reference_water}, wykluczone ${c.excluded}, brak obserwacji ${c.no_observation}, ocenione bez detekcji ${c.assessed_clear}.`));
      if(result.source_counts)root.append(node('p',`Piksele źródłowe w obszarze (przed pomniejszeniem): zalanie ${result.source_counts.flood}, woda referencyjna ${result.source_counts.reference_water}, wykluczone ${result.source_counts.excluded}, brak obserwacji ${result.source_counts.no_observation}, ocenione bez detekcji ${result.source_counts.assessed_clear}. Podsumowanie detekcji opiera się na tych pikselach.`));
      const labels={advisory_flags:'Advisory flags (0 brak, 1 niski sygnał, 2 szorstka woda, 3 oba, 255 NoData)',ensemble_likelihood:'Likelihood klasyfikacji (0–100; 255 NoData), nie prognoza powodzi'};
      for(const [name,label] of Object.entries(labels))root.append(node('p',`${label}: ${result.quality[name]?(name==='advisory_flags'?Object.entries(result.quality[name]).map(([v,n])=>`${v}: ${n} próbek`).join(', '):`zakres ${Object.keys(result.quality[name]).filter(v=>v!=='255').map(Number).sort((a,b)=>a-b).filter((v,i,a)=>i===0||i===a.length-1).join('–')||'brak'}; NoData: ${result.quality[name]['255']||0} próbek`):'brak w produkcie'}.`));
      const a=node('a','Copernicus GFM · metadane źródłowe');a.href=p.source_url;a.target='_blank';a.rel='noopener noreferrer';root.append(a,node('p',p.attribution));
    }catch(error){if(run===generation&&shown())status(`Awaria odczytu GFM: ${error.message}`);}
  }
  function init(options){
    if(map||!options.map)return;map=options.map;api=options.api;
    window.WiciGFMAuto?.init({map,api});
    const pane=map.createPane('gfmPixels');pane.style.zIndex='350';pane.style.pointerEvents='none';
    const end=new Date(),start=new Date(end);start.setUTCDate(start.getUTCDate()-6);
    $('start').value=start.toISOString().slice(0,10);$('end').value=end.toISOString().slice(0,10);
    $('mode').addEventListener('change',()=>{clear();sync();if($('mode').value==='manual')status('Wybierz daty i obserwację lub wczytaj próbę historyczną.');});
    $('enabled').addEventListener('change',()=>sync());$('search').addEventListener('click',()=>search());
    $('observation').addEventListener('change',select);
    for(const name of ['start','end'])$(name).addEventListener('change',()=>{clear();$('observation').replaceChildren();status('Zmieniono daty. Wyszukaj obserwacje.');});
    $('opacity').addEventListener('input',()=>overlay?.setOpacity(Number($('opacity').value)));
    $('recent').addEventListener('click',()=>{const end=new Date(),start=new Date(end);start.setUTCDate(start.getUTCDate()-6);$('start').value=start.toISOString().slice(0,10);$('end').value=end.toISOString().slice(0,10);clear();$('observation').replaceChildren();status('Wybrano ostatnie 7 dni. Wyszukaj obserwacje dla widocznego obszaru.');});
    $('klodzko').addEventListener('click',()=>{if(!shown())return;$('mode').value='manual';window.WiciGFMAuto?.sync({active:false});map.fitBounds([[50.35,16.55],[50.55,16.75]],{animate:false,padding:[25,25],maxZoom:12});$('start').value='2024-09-14';$('end').value='2024-09-17';return search({box:historicalBox,observation:historicalObservation});});
    document.addEventListener('wici:regionchange',()=>{clear();items=[];box=null;$('observation').replaceChildren();sync();});
    document.addEventListener('visibilitychange',()=>sync());sync({visible:options.visible!==false});
  }
  return {init,sync};
})();
