'use strict';
// One spatial scope shared by all layers; retain national caches for instant changes.
window.WiciRegion = (() => {
  const storageKey='wici.region.v1',features=new Map(),rows=new Map(),jobs=new Map(),outcomes=new Map(),explicit=new Map();
  let map,control,country,current='',initialized=false,outline,clipFrame=null,scopeRevision=0,analysisOutsidePoland=false;
  const feature=()=>features.get(current);
  const polygons=geometry=>geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates;
  function ringContains(lat,lon,ring){
    let inside=false;
    for(let i=0,j=ring.length-1;i<ring.length;j=i++){
      const [x,y]=ring[i],[u,v]=ring[j],cross=(lon-x)*(v-y)-(lat-y)*(u-x);
      if(Math.abs(cross)<1e-10&&lon>=Math.min(x,u)-1e-10&&lon<=Math.max(x,u)+1e-10&&lat>=Math.min(y,v)-1e-10&&lat<=Math.max(y,v)+1e-10)return true;
      if((y>lat)!==(v>lat)&&lon<(u-x)*(lat-y)/(v-y)+x)inside=!inside;
    }
    return inside;
  }
  function contains(lat,lon){
    if(!current)return true;
    if(!Number.isFinite(lat)||!Number.isFinite(lon))return false;
    return polygons(feature().geometry).some(p=>ringContains(lat,lon,p[0])&&!p.slice(1).some(h=>ringContains(lat,lon,h)));
  }
  function matchesProvince(name){
    const normalize=value=>String(value||'').toLocaleLowerCase('pl').replace(/^woj(?:ewództwo)?[.\s]+/,'').trim();
    return !current||normalize(name)===normalize(feature().properties.name);
  }
  function bounds(){return current?L.geoJSON(feature()).getBounds():null;}
  function viewBox(view){
    const region=bounds();
    const box=region?[Math.max(view.getWest(),region.getWest()),Math.max(view.getSouth(),region.getSouth()),Math.min(view.getEast(),region.getEast()),Math.min(view.getNorth(),region.getNorth())]:[view.getWest(),view.getSouth(),view.getEast(),view.getNorth()];
    return box[0]<box[2]&&box[1]<box[3]?box:null;
  }
  function clip(){
    if(!map)return;
    const path=current&&!analysisOutsidePoland?'path(evenodd, "'+polygons(feature().geometry).flatMap(p=>p.map(r=>r.map(([lon,lat],i)=>{const p=map.latLngToLayerPoint([lat,lon]);return `${i?'L':'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;}).join(' ')+' Z')).join(' ')+'")':'';
    for(const [name,pane] of Object.entries(map.getPanes()))if(!['mapPane','tilePane','osmBase','administrativeBase','countryBorder','regionBoundary','popupPane','tooltipPane','trackingRoutes','trackingCursor'].includes(name))pane.style.clipPath=path;
  }
  function select(code,{fit=true,notify=true}={}){
    const next=features.has(code)?code:'',changed=next!==current;
    if(changed){scopeRevision++;outcomes.clear();}
    current=next;if(control)control.value=current;
    try{localStorage.setItem(storageKey,current);}catch{/* Storage may be blocked. */}
    outline?.remove();outline=null;
    if(current)outline=L.geoJSON(feature(),{pane:'regionBoundary',interactive:false,style:{color:'#db8524',weight:3,fill:false,interactive:false}}).addTo(map);
    const target=L.geoJSON(current?feature():country).getBounds();
    if(fit&&target.isValid())map.fitBounds(target,{padding:[35,55],maxZoom:current?9:6,animate:false});
    clip();const note=document.getElementById('region-note');
    if(note)note.textContent=current?`Warstwy i komunikaty dla województwa: ${feature().properties.name}.`:'Cała Polska. Region zapamiętujemy w tej przeglądarce.';
    if(changed&&notify){map.closePopup();explicit.clear();document.dispatchEvent(new Event('wici:regionchange'));}
    updateProgress();
  }
  function init(options){
    if(initialized)return;map=options.map;control=options.select;country=options.country;
    for(const f of options.provinces.features)features.set(String(f.properties.admin_code),f);
    map.createPane('regionBoundary').style.zIndex='415';
    let saved='';try{saved=localStorage.getItem(storageKey)||'';}catch{/* Storage may be blocked. */}
    select(saved,{notify:false});initialized=true;
    map.on('moveend zoomend resize',clip);
    map.on('layeradd',()=>{if(clipFrame===null)clipFrame=requestAnimationFrame(()=>{clipFrame=null;clip();});});
  }
  function layerIds(url){
    const path=String(url).replace(/^\/api\//,'/'),root=path.split(/[/?]/)[1];
    if(root==='weather')return ['weather-wind','weather-rain'];
    if(root==='hydro')return [path.includes('warnings')?'hydro-warnings':'hydro-stations'];
    const alias={sentinel2:'s2',sentinel5p:'s5p','position-quality':'quality'};
    const id=(alias[root]||root)+'-enabled';return rows.has(id)?[id]:[];
  }
  function begin(url){
    const ids=layerIds(url),revision=scopeRevision;let finished=false;
    for(const id of ids)jobs.set(id,(jobs.get(id)||0)+1);updateProgress();
    return result=>{if(finished)return;finished=true;for(const id of ids){jobs.set(id,Math.max(0,(jobs.get(id)||0)-1));if(revision===scopeRevision)outcomes.set(id,result||'ready');}updateProgress();};
  }
  async function trackedFetch(url,options){
    const finish=begin(url);
    try{
      const response=await fetch(url,options),json=response.json.bind(response);
      if(!response.ok)finish('error');
      response.json=async()=>{try{const data=await json();finish(data?.status==='error'?'error':data?.stale||data?.status==='partial'?'partial':'ready');return data;}catch(error){finish('error');throw error;}};
      return response;
    }catch(error){finish(error.name==='AbortError'?'cancelled':'error');throw error;}
  }
  function updateProgress(){
    let selected=0,loading=0;
    for(const [id,row] of rows){
      const enabled=document.getElementById(id);row.el.hidden=!enabled?.checked;if(row.el.hidden)continue;selected++;
      const text=row.statuses.map(el=>el?.textContent||'').filter(Boolean).join(' · '),info=explicit.get(id),pending=jobs.get(id)||0;
      const waiting=pending>0||info?.pending||/wczytywanie|odczyt w toku|łączenie|oczekiwanie/i.test(text);
      const phase=enabled.disabled?'Niedostępna':document.hidden||/wstrzyman/i.test(text)?'Wstrzymana':waiting?'Wczytywanie':outcomes.get(id)==='error'?'Błąd odczytu':outcomes.get(id)==='partial'?'Dane częściowe':(info||text||outcomes.has(id))?'Odczyt zakończony':'Oczekuje na włączenie';
      if(phase==='Wczytywanie')loading++;
      const value=[phase,pending?`${pending} zapytań`:null,info?`${info.done}/${info.total}`:null,text].filter(Boolean).join(' · ');
      if(row.text.textContent!==value)row.text.textContent=value;
      row.el.dataset.state=phase;row.meter.hidden=!info?.total;if(info?.total){row.meter.max=info.total;row.meter.value=info.done;}
    }
    const summary=document.getElementById('layer-progress-summary');if(summary)summary.textContent=`Postęp warstw · ${selected} wybranych · ${loading} wczytywanych`;
  }
  function initProgress(names){
    const container=document.getElementById('layer-progress');if(!container)return;
    const overrides={'gios-enabled':['gios-status','gios-index-status'],'hydro-stations':['hydro-stations-status'],'hydro-warnings':['hydro-warnings-status'],'weather-wind':['weather-status'],'weather-rain':['weather-status'],'quality-enabled':['quality-status'],'ioda-enabled':['ioda-map-read'],'trains-enabled':['trains-status','trains-positions-status']};
    const observer=window.MutationObserver?new window.MutationObserver(updateProgress):null;
    for(const [id,name] of Object.entries(names)){
      const el=document.createElement('div'),title=document.createElement('strong'),text=document.createElement('span'),meter=document.createElement('progress');
      el.dataset.layer=id;title.textContent=name;meter.setAttribute('aria-label',name);el.append(title,text,meter);container.append(el);
      const statuses=(overrides[id]||[id.replace(/-(enabled|stations|warnings|wind|rain)$/,'')+'-status']).map(id=>document.getElementById(id));
      for(const status of statuses)if(status)observer?.observe(status,{childList:true,characterData:true,subtree:true});
      rows.set(id,{el,text,meter,statuses});document.getElementById(id)?.addEventListener('change',()=>{explicit.delete(id);updateProgress();});
    }
    document.addEventListener('visibilitychange',updateProgress);updateProgress();
  }
  return {init,select,setAnalysisOutsidePoland(value){analysisOutsidePoland=Boolean(value);if(outline){if(analysisOutsidePoland)map.removeLayer(outline);else if(!map.hasLayer(outline))outline.addTo(map);}clip();},contains,matchesProvince,viewBox,bounds,ready:()=>initialized,code:()=>current,initProgress,progress:(id,value)=>{explicit.set(id,value);updateProgress();},begin,fetch:trackedFetch};
})();
