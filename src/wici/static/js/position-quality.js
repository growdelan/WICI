'use strict';
window.WiciPositionQuality = (() => {
  const $ = id => document.getElementById(`quality-${id}`);
  const node = (tag, text) => {const e=document.createElement(tag);if(text!=null)e.textContent=String(text);return e;};
  const at = value => new Intl.DateTimeFormat('pl-PL',{timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'short'}).format(new Date(value*1000));
  const pct = value => value==null?'brak':`${Math.round(value*100)}%`;
  let ctx, data, layer, timer, key, scope, loadError=null, latestTime=null, followLatest=true, revision=0;
  const shown = () => ctx?.map && ctx.visible && $('enabled').checked;
  function clear(){if(layer&&ctx?.map)ctx.map.removeLayer(layer);layer=null;}
  function popup(item){
    const box=node('div');box.className='map-popup';
    box.append(node('strong',item.label),node('p',`${at(item.window_start)} – ${at(item.window_end)} · Europe/Warsaw`),
      node('p',`Źródło: ${item.provider??'nieustalone'}. ${item.provenance==='unknown'?'Historia bez pochodzenia: poza oceną i tłem.':item.provenance==='mixed'?'Okno obejmuje różne okresy źródła: poza oceną i tłem.':'Porównanie wyłącznie w obrębie tego samego okresu źródła.'}`),
      node('p',`Komórka ${item.cell} · różne samoloty: ${item.aircraft}, pogorszone: ${item.degraded_aircraft} (${pct(item.share)}).`),
      node('p',`Raporty: ${item.reports}; kwalifikowane: ${item.eligible_reports}; udział pogorszonych raportów: ${pct(item.degraded_report_share)}. Każdy samolot ma równą wagę w detekcji.`),
      node('p',`Tło: ${pct(item.baseline)} · wystarczające okna tła: ${item.background_windows}. Niepewny kontekst: ${item.context_reports} raportów (poza detekcją).`),
      node('p',`Ostatnia obserwacja: ${at(item.last_observed)}. Dostępność pól / ${item.reports} raportów: ${Object.entries(item.availability).map(([k,v])=>`${k}: ${v}`).join(' · ')}`),
      node('small','Obszar obserwacji, nie lokalizacja nadajnika. To nie jest potwierdzenie zakłóceń GNSS.'));
    return box;
  }
  function render(){
    clear();if(!shown())return;
    $('follow').textContent=followLatest?'Śledzenie najnowszego zakończonego okna':'Ręcznie wybrane okno historii';
    if(!data){
      $('summary').textContent='';
      if(loadError){$('status').textContent=loadError;$('status').classList.toggle('notice',true);}
      return;
    }
    const t=Number($('window').value), selected=data.items.filter(i=>i.window_start===t);
    layer=L.layerGroup().addTo(ctx.map);
    const sourceProblem=Boolean(loadError)||['error','stale'].includes(data.status);
    for(const item of selected){
      const color=sourceProblem?'#9a6639':({anomaly:'#c53535',normal:'#298269',insufficient:'#76818b'}[item.state]);
      L.geoJSON(item.geometry,{style:{color,weight:2,fillOpacity:.25,dashArray:sourceProblem?'5 5':null}})
        .bindPopup(()=>popup(item)).bindTooltip(()=>node('span',`${item.label} · ${item.aircraft} samolotów`)).addTo(layer);
    }
    $('status').textContent=loadError||`${data.synthetic?'DEMO · wyłącznie dane syntetyczne · ':''}${data.status_label}. Wiek kwalifikowanej obserwacji względem końca zakresu: ${data.observation_age_seconds==null?'brak':Math.floor(data.observation_age_seconds)+' s'}. Wiek ostatniego odczytu: ${data.age_seconds==null?'brak':Math.floor(data.age_seconds)+' s'}. Zapis od: ${data.source.started?at(data.source.started):'jeszcze nie uruchomiono'}. Ostatnia próba: ${data.source.attempt?at(data.source.attempt):'brak'}.`;
    $('status').classList.toggle('notice',sourceProblem);
    $('summary').textContent=`${selected.length?`${at(t)}: komórki ${selected.length}, anomalie ${selected.filter(i=>i.state==='anomaly').length}, bez wykrycia ${selected.filter(i=>i.state==='normal').length}, za mało danych ${selected.filter(i=>i.state==='insufficient').length}`:'Brak zapisanych obserwacji w wybranym okresie.'} · Zakres ${at(data.window_start)} – ${at(data.window_end)}. Raporty bez lokalizacji (z tłem): ${data.coverage.unlocated_reports}. Oczekujące zapisy: ${data.pending_writes??0}; pominięte snapshoty od uruchomienia: ${data.dropped_snapshots??0}. ${sourceProblem?'Klasy historyczne zachowane; aktualny stan źródła nie pozwala wnioskować o bieżącej sytuacji.':''}`;
    $('method').textContent=data.method;$('note').textContent=`${data.note} Historia bez ustalonego źródła: ${data.coverage.unknown_provenance_reports??0} raportów (poza oceną i tłem). Po zmianie źródła wymagana jest nowa rozgrzewka.`;
  }
  async function load(){
    if(!shown())return;
    const run=++revision;
    try{
      const params=new URLSearchParams({date:ctx.day,hours:$('hours').value});
      if(ctx.province)params.set('voivodeship',ctx.province);
      const result=await ctx.api(`/position-quality?${params}`);
      if(run!==revision||!shown())return;
      const prior=$('window').value;
      data=result;loadError=null;
      const times=[...new Set(data.items.map(i=>i.window_start))].sort((a,b)=>a-b);
      $('window').replaceChildren(...times.map(t=>{const o=node('option',`${at(t)} – ${at(t+300)}${t+300>data.window_end?' (niepełne)':''}`);o.value=t;return o;}));
      latestTime=times.filter(t=>t+300<=data.window_end).at(-1)??times.at(-1)??null;
      if(!times.includes(Number(prior)))followLatest=true;
      $('window').value=String(followLatest?latestTime??'':prior);render();
    }catch{
      if(run!==revision)return;
      loadError='Błąd odczytu lokalnych danych jakości pozycji. Brak oceny aktualnej sytuacji.';
      render();
    }finally{if(run===revision&&shown())timer=setTimeout(load,60000);}
  }
  function sync(options){
    ctx=options;
    const nextScope=JSON.stringify([ctx.day,ctx.province,$('hours').value]);
    if(scope!==nextScope){
      scope=nextScope;data=null;loadError=null;followLatest=true;latestTime=null;$('window').replaceChildren();
    }
    const next=JSON.stringify([scope,shown()]);
    if(key===next)return;
    key=next;revision++;clearTimeout(timer);clear();
    if(shown())load();else $('status').textContent='Warstwa jakości pozycji wyłączona lub mapa niewidoczna. Kolektor działa według konfiguracji aplikacji.';
  }
  for(const id of ['enabled','hours'])$(id).addEventListener('change',()=>{key=null;if(ctx)sync(ctx);});
  $('window').addEventListener('change',()=>{followLatest=false;render();});
  $('latest').addEventListener('click',()=>{followLatest=true;$('window').value=String(latestTime??'');render();});
  return {sync};
})();
