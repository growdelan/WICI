'use strict';
window.WiciIoda = (() => {
  const $ = id => document.getElementById(`ioda-${id}`);
  const node = (tag,text) => {const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);return e;};
  const names = {country:'Kraj',region:'Region',asn:'ASN'};
  let ctx=null, key=null, revision=0, layer=null, data=null, emptyNode=null, popupMap=null;
  const records=new Map(), polygons=new Map();
  function stateOf(item){return item.ended_at!=null?'ended':item.measurement_age_seconds>3600?'stale':'unconfirmed';}
  const stateLabels={ended:'Zakończona',stale:'Koniec niepotwierdzony · stary alert',unconfirmed:'Koniec niepotwierdzony'};
  function stateBadge(item){const badge=node('span',stateLabels[stateOf(item)]);badge.className=`ioda-state ioda-state-${stateOf(item)}`;return badge;}
  function areaStyle(item){
    const status=stateOf(item),ended=status==='ended';
    return {color:ended?'#475569':'#6d28d9',weight:3,opacity:1,
      fill:true,fillColor:ended?'#64748b':'#6d28d9',fillOpacity:ended?.16:status==='stale'?.07:.18,
      dashArray:ended?'4 4':status==='stale'?'8 6':null,className:`ioda-area ioda-area-${status}`};
  }
  function popupOptions(){const size=ctx.map.getSize();return {className:'ioda-popup',maxWidth:Math.max(140,Math.min(350,size.x-64)),maxHeight:Math.max(100,Math.min(360,size.y-240)),autoPanPaddingTopLeft:[12,155],autoPanPaddingBottomRight:[12,20]};}
  function resizePopups(){for(const entry of polygons.values()){Object.assign(entry.layer.getPopup().options,popupOptions());if(entry.layer.isPopupOpen())entry.layer.getPopup().update();}}
  function showCommunications(){if(document.getElementById('communications-enabled')?.checked===false)return;if($('enabled').checked&&!$('communications').checked){$('communications').checked=true;$('communications').dispatchEvent(new Event('change'));}}
  const at = value => value ? new Intl.DateTimeFormat('pl-PL',{timeZone:'Europe/Warsaw',dateStyle:'short',timeStyle:'short'}).format(new Date(typeof value==='number'?value*1000:value)) : 'Nie podano';
  function link(url){const a=node('a','IODA · oryginał');a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
  function remove(){if(layer&&ctx?.map)ctx.map.removeLayer(layer);layer=null;polygons.clear();}
  function geometry(item){
    if(item.entity_type==='asn'||!item.geometry_ref)return null;
    return ctx?.geometries?.get(item.geometry_ref);
  }
  function details(item){
    const d=node('div');
    d.append(stateBadge(item),node('p',`${item.synthetic?'DEMO · dane syntetyczne · ':''}Anomalia dostępności internetu · detekcja IODA`),
      node('p',`${names[item.entity_type]}: ${item.name} (${item.entity_code})`),
      node('p',`Początek: ${at(item.started_at)} · ${item.ended_at?`Koniec według alertu normal: ${at(item.ended_at)}`:'Zakończenie niepotwierdzone; brak rekordu nie oznacza końca.'}`),
      node('p',`Granica okresu źródła: ${at(item.source_until)} · nie musi być końcem anomalii.`),
      node('p',`Sygnał: ${item.datasource} · metoda: ${item.method} · jednostka: ${item.signal_unit}`),
      node('p',item.signal_meaning),
      node('p',`Wskaźnik: ${item.score} · ${item.score_unit}`),
      node('p',`Ostatni alert: ${at(item.measured_at)} · wiek: ${Math.floor(item.measurement_age_seconds/60)} min`),
      node('p',`Pobrano: ${at(item.fetched_at)} · wiek odczytu: ${Math.floor(item.fetch_age_seconds/60)} min`));
    const table=node('table'), head=node('tr');
    for(const title of ['Czas alertu','Poziom IODA','Wartość','Odniesienie'])head.append(node('th',title));
    table.append(head);
    for(const a of item.raw.alerts||[]){const row=node('tr');for(const v of [at(a.time),a.level,a.value,a.historyValue])row.append(node('td',v));table.append(row);}
    d.append(table,node('small',`Wartość i odniesienie w jednostce ${item.signal_unit}. Poziom alertu pochodzi z IODA.`));
    if(item.entity_type==='asn')d.append(node('p','ASN powiązany z Polską; pomiary mogą obejmować inne kraje. Brak geolokalizacji awarii ASN.'));
    else if(!item.geometry_ref)d.append(node('p','Brak zweryfikowanej geometrii; rekord wyłącznie na liście.'));
    d.append(link(item.url));return d;
  }
  function chart(series){
    const box=node('section');box.append(node('h4',`${series.datasource} · ${series.unit}`),node('p',series.meaning));
    if(series.last_check?.result==='error')box.append(node('p','Błąd ostatniej próby sygnału; poniżej zachowane pomiary.'));
    if(series.last_check?.result==='success'&&series.last_check.measurement_at===null)box.append(node('p','Ostatni odczyt: brak pomiarów; poniżej ewentualna zapisana historia.'));
    const valid=series.points.filter(p=>p.value!==null);
    if(!valid.length){box.append(node('p','Brak pomiarów w zapisanym oknie.'));return box;}
    const steps=[...new Set(series.points.map(p=>p.step))].join(', '), native=[...new Set(series.points.map(p=>p.native_step))].join(', ');
    box.append(node('p',`${series.stale?'Nieaktualne pomiary · ':''}Ostatni pomiar: ${at(series.measurement_at)} · krok ${steps} s · natywny ${native} s. Maks. 288 punktów; agregacja źródła, możliwe luki.`));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 320 110');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${series.datasource}; ${series.unit}; czas Europe/Warsaw`);
    const lo=Math.min(...valid.map(p=>p.value)),hi=Math.max(...valid.map(p=>p.value));
    const t0=series.points[0].measured_at,t1=series.points.at(-1).measured_at;
    let segment=[];
    function flush(){if(!segment.length)return;const line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',segment.join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#8051a5');line.setAttribute('stroke-width','2');svg.append(line);segment=[];}
    let previous=null;
    for(const p of series.points){if(p.value===null){flush();previous=null;continue;}if(previous&&p.measured_at-previous.measured_at>Math.max(p.step,previous.step)*1.5)flush();segment.push(`${10+300*(p.measured_at-t0)/Math.max(1,t1-t0)},${95-80*(p.value-lo)/Math.max(1,hi-lo)}`);previous=p;}flush();
    box.append(svg,node('small',`Zakres wartości ${lo}–${hi} ${series.unit} · ${at(t0)} — ${at(t1)}. Czas Europe/Warsaw. Luki nie oznaczają wartości zero.`));return box;
  }
  function renderSignals(){
    const selected=data?.entities.find(e=>`${e.type}/${e.code}`===$('entity').value);
    $('signals').replaceChildren();if(!selected)return;
    for(const s of selected.signals)$('signals').append(chart(s));
  }
  function render(){
    if(!data||!ctx?.visible||!$('enabled').checked)return;
    const s=data.status;
    const coverage=s.signal_coverage||{};
    $('status').textContent=`${s.synthetic?'DEMO · dane syntetyczne · ':''}Okno zapisu: ${at(data.window_start)} — ${at(data.window_end)}. Ostatnia próba: ${at(s.last_attempt_at)} · pełny sukces: ${at(s.last_successful_check)} · ${s.result||'brak odczytu'}. Pomiary: ${s.measurement_state==='no_measurements'?'brak danych':s.measurement_stale?'nieaktualne':'dostępne'}; ostatni ${at(s.measurement_at)}${s.measurement_age_seconds!==null?` (${Math.floor(s.measurement_age_seconds/60)} min)`:''}. Pokrycie jednostka/sygnał: ${coverage.available||0} aktualnych, ${coverage.stale||0} nieaktualnych, ${coverage.no_measurements||0} bez pomiarów, ${coverage.read_error||0} błędów. ${data.total} zapisanych detekcji; poziomy mogą opisywać tę samą anomalię.${data.limited?' Lista ograniczona do 500 rekordów.':''}`;
    $('errors').textContent=(s.errors||[]).join(' · ');
    $('note').textContent=`${data.filter_note} ${data.history_note} ${data.scope_note} Brak zdarzeń nie potwierdza prawidłowej dostępności internetu. Detekcja nie określa przyczyny ani liczby użytkowników bez internetu.`;
    const ended=data.items.filter(item=>stateOf(item)==='ended').length;
    const mapped=data.items.filter(item=>geometry(item)).length;
    $('map-label').textContent=`IODA · ${data.hours} h · ${mapped} na mapie`;
    $('map-count').textContent=`Detekcje: ${data.items.length-ended} bez potwierdzonego końca · ${ended} zakończonych${data.limited?' · lista niepełna':''}`;
    $('map-window').textContent=`${data.hours} h · ${at(data.window_start)} — ${at(data.window_end)} · Europe/Warsaw`;
    $('map-mapping').textContent=`Na mapie: ${mapped} · tylko na liście: ${data.items.length-mapped} (ASN lub brak geometrii).`;
    $('map-empty').hidden=mapped>0;
    $('map-empty').textContent=data.items.length
      ?'Detekcje dostępne na liście warstwy. ASN i rekordy bez zweryfikowanej geometrii nie mają oznaczenia na mapie.'
      :`Brak zapisanych detekcji w wybranym oknie ${data.hours} h i filtrach. Mapa nie ma obszarów IODA do zaznaczenia.`;
    $('map-expand').hidden=data.hours!==24||data.items.length>0;
    $('map-read').textContent=s.errors?.length?'Błędy źródła IODA — pokazano zachowane zapisy. Szczegóły w panelu warstwy.':'';
    $('map-read').hidden=!$('map-read').textContent;
    // Keep keyed DOM nodes and Leaflet layers alive during routine polling.
    // Only records leaving the selected window/filter lose their details/popup.
    const retained=new Set(data.items.map(item=>item.id));
    for(const [id,record] of records)if(!retained.has(id)){record.node.remove();records.delete(id);}
    for(const [id,entry] of polygons)if(!retained.has(id)){layer.removeLayer(entry.layer);polygons.delete(id);}
    if(data.items.length&&emptyNode){emptyNode.remove();emptyNode=null;}
    if(!data.items.length&&!emptyNode){emptyNode=node('p','Brak zapisanych zdarzeń w wybranym zakresie. Sprawdź osobno stan pomiarów i odczytu.');$('list').append(emptyNode);}
    if(ctx.map&&!layer){
      if(!ctx.map.getPane('iodaDetections'))ctx.map.createPane('iodaDetections').style.zIndex='440';
      layer=L.layerGroup().addTo(ctx.map);
      if(popupMap!==ctx.map){popupMap?.off('resize',resizePopups);popupMap=ctx.map;popupMap.on('resize',resizePopups);}
    }
    for(const [index,item] of data.items.entries()){
      let record=records.get(item.id);
      if(!record){
        record={node:node('details'),summary:node('summary'),body:node('div')};
        record.node.dataset.iodaId=item.id;
        record.node.append(record.summary,record.body);records.set(item.id,record);
      }
      record.summary.replaceChildren(node('span',`${item.synthetic?'DEMO · ':''}${names[item.entity_type]} · ${item.name} · ${at(item.started_at)}`),stateBadge(item));
      record.body.replaceChildren(details(item));
      if($('list').children[index]!==record.node)$('list').insertBefore(record.node,$('list').children[index]||null);
      const geo=geometry(item),style=areaStyle(item);
      let entry=polygons.get(item.id);
      if(entry&&entry.geometry!==geo){layer.removeLayer(entry.layer);polygons.delete(item.id);entry=null;}
      if(geo&&layer){
        if(!entry){
          entry={layer:L.geoJSON(geo,{pane:'iodaDetections',style}),geometry:geo,item};
          const current=entry;
          entry.layer.bindPopup(()=>details(current.item),popupOptions());
          entry.layer.bindTooltip(()=>node('span',`IODA · ${current.item.name} · ${stateLabels[stateOf(current.item)]}`),{sticky:true});
          entry.layer.addTo(layer);polygons.set(item.id,entry);
        }else{
          entry.item=item;entry.layer.setStyle(style);
          entry.layer.eachLayer(part=>{const element=part.getElement?.();if(element){element.classList.remove('ioda-area-ended','ioda-area-stale','ioda-area-unconfirmed');element.classList.add(`ioda-area-${stateOf(item)}`);}});
          if(entry.layer.isPopupOpen())entry.layer.getPopup().update();
          if(entry.layer.isTooltipOpen())entry.layer.getTooltip().update();
        }
      }
    }
    // Country aggregation stays below regional boundaries even after a refresh.
    for(const entry of polygons.values())if(entry.item.entity_type==='country')entry.layer.bringToBack();
    const previous=$('entity').value;$('entity').replaceChildren();
    for(const e of data.entities){const o=node('option',`${names[e.type]} · ${e.name}`);o.value=`${e.type}/${e.code}`;$('entity').append(o);}
    if(data.entities.some(e=>`${e.type}/${e.code}`===previous))$('entity').value=previous;
    renderSignals();
  }
  async function sync(options){
    ctx=options;
    $('content').hidden=!$('enabled').checked;
    $('map-legend').hidden=!$('enabled').checked;
    $('map-label').hidden=!$('enabled').checked;
    if(!ctx.visible||!$('enabled').checked){key=null;revision++;remove();return;}
    const next=JSON.stringify([ctx.geometries?.size,Boolean(ctx.map),ctx.day,ctx.province,$('level').value,$('hours').value,ctx.now]);
    if(key===next)return;key=next;const run=++revision;
    $('map-read').hidden=false;$('map-read').textContent='Odczyt zapisanych detekcji…';
    $('map-expand').hidden=true;
    const query=new URLSearchParams({hours:$('hours').value||'48',date:ctx.day});
    if(ctx.province)query.set('voivodeship',ctx.province);
    if($('level').value)query.set('level',$('level').value);
    try{const result=await ctx.api(`/ioda?${query}`);if(run!==revision)return;data=result;render();}
    catch(e){if(run!==revision)return;key=null;$('errors').textContent='Błąd odczytu zapisu WICI. Zachowano ostatni widok; jego dane mogą być nieaktualne.';$('map-read').hidden=false;$('map-read').textContent=$('errors').textContent;}
  }
  for(const id of ['enabled','level','hours'])$(id)?.addEventListener('change',()=>{key=null;if(id==='enabled'&&$('enabled').checked)document.querySelector('.map-legend').open=true;if(ctx)sync(ctx);});
  $('entity')?.addEventListener('change',renderSignals);
  $('map-expand')?.addEventListener('click',()=>{$('hours').value='48';$('hours').dispatchEvent(new Event('change'));});
  return {sync,geometry,showCommunications};
})();
