'use strict';
// Building coverage follows the viewport; cached tiles outlive camera movements.
window.WiciBuildings3D = (() => {
  const LEVEL=14, MAX_TILES=25, MAX_BUILDINGS=3000, MAX_VERTICES=120000, RETRY_MS=30500;
  function coverage(viewer,longitude,latitude) {
    const C=window.Cesium, points=[], width=viewer.canvas.clientWidth, height=viewer.canvas.clientHeight;
    for(const u of [0,.5,1])for(const v of [0,.5,1]){
      const pixel=new C.Cartesian2(u*width,v*height),ray=viewer.camera.getPickRay(pixel);
      const point=(ray&&viewer.scene.globe.pick(ray,viewer.scene))||viewer.camera.pickEllipsoid(pixel);
      if(point){const p=C.Cartographic.fromCartesian(point);points.push([C.Math.toDegrees(p.longitude),C.Math.toDegrees(p.latitude)]);}
    }
    if(!points.length)points.push([longitude,latitude]);
    // Snap outward with a margin: a small pan keeps full coverage without
    // rebuilding geometry on every frame or every GPS report.
    const step=180/2**17, xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
    const box=[Math.floor(Math.min(...xs)/step)*step-step,Math.floor(Math.min(...ys)/step)*step-step,
      Math.ceil(Math.max(...xs)/step)*step+step,Math.ceil(Math.max(...ys)/step)*step+step];
    const scheme=new C.WebMercatorTilingScheme(),at=(lon,lat)=>scheme.positionToTileXY(C.Cartographic.fromDegrees(lon,lat),LEVEL);
    const center=at(longitude,latitude),nw=at(Math.max(14,box[0]),Math.min(55,box[3])),se=at(Math.min(24.5,box[2]),Math.max(49,box[1]));
    const core=[],coreCount=Math.max(0,se.x-nw.x+1)*Math.max(0,se.y-nw.y+1),large=coreCount>MAX_TILES;
    for(let x=Math.max(nw.x,large?center.x-3:nw.x);x<=Math.min(se.x,large?center.x+3:se.x);x++)for(let y=Math.max(nw.y,large?center.y-3:nw.y);y<=Math.min(se.y,large?center.y+3:se.y);y++)core.push({x,y,key:`${x}/${y}`,required:true});
    const distance=t=>(t.x-center.x)**2+(t.y-center.y)**2;
    core.sort((a,b)=>distance(a)-distance(b));
    const limited=large,tiles=core.slice(0,MAX_TILES);
    return {box,tiles,limited,key:`${box.join(',')}|${tiles.map(t=>t.key).join(';')}`};
  }
  function select(data,box,longitude,latitude) {
    const candidates=[],seen=new Set();
    for(const tile of data)for(const item of tile.items||[]){
      if(seen.has(item.id)||!item.rings?.length)continue;
      seen.add(item.id);
      const xs=item.rings[0].map(p=>p[0]),ys=item.rings[0].map(p=>p[1]);
      const w=Math.min(...xs),s=Math.min(...ys),e=Math.max(...xs),n=Math.max(...ys);
      if(e<box[0]||w>box[2]||n<box[1]||s>box[3])continue;
      const lon=(w+e)/2,lat=(s+n)/2;
      candidates.push({item,lon,lat,count:item.rings.reduce((sum,ring)=>sum+ring.length,0),distance:((lon-longitude)*Math.cos(latitude*Math.PI/180))**2+(lat-latitude)**2});
    }
    candidates.sort((a,b)=>a.distance-b.distance);
    const selected=[];let vertices=0,limited=false;
    for(const value of candidates){
      if(selected.length>=MAX_BUILDINGS||vertices+value.count>MAX_VERTICES){limited=true;continue;}
      selected.push(value);vertices+=value.count;
    }
    return {selected,limited};
  }
  function create({viewer,terrain,read,groundTarget,report}) {
    const C=window.Cesium,cache=new Map(),queue=[],staging=new Set();
    let dead=false,active=0,wanted=new Set(),key='',generation=0,current,debounce,retryTimer,retryAt=0,last;
    const remove=primitive=>{if(primitive&&!viewer.isDestroyed())viewer.scene.primitives.remove(primitive);};
    const credit=new C.Credit('<a href="https://openfreemap.org/" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> · <a href="https://openmaptiles.org/" target="_blank" rel="noopener noreferrer">© OpenMapTiles</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> · wysokości przybliżone',true);
    function drain(){
      while(!dead&&!document.hidden&&active<2&&queue.length){
        const entry=queue.shift();
        if(!wanted.has(entry.key)){cache.delete(entry.key);entry.resolve({status:'obsolete'});continue;}
        active++;
        read(`/api/scene3d/buildings/${entry.key}`).catch(()=>({status:'unavailable'})).then(data=>{
          if(!data||!['ready','empty','unavailable'].includes(data.status))data={status:'unavailable'};
          entry.data=data;entry.expires=Date.now()+(data.status!=='unavailable'?3600000:RETRY_MS);entry.resolve(data);
        }).finally(()=>{active--;entry.promise=null;drain();});
      }
    }
    function tileData(tile){
      const existing=cache.get(tile.key);
      if(existing?.promise)return existing.promise;
      if(existing?.expires>Date.now()){cache.delete(tile.key);cache.set(tile.key,existing);return Promise.resolve(existing.data);}
      const entry={key:tile.key};entry.promise=new Promise(resolve=>{entry.resolve=resolve;});
      cache.set(tile.key,entry);queue.push(entry);drain();
      for(const [id,value] of cache)if(cache.size>32&&!value.promise&&!wanted.has(id))cache.delete(id);
      return entry.promise;
    }
    function cancelStaging(){for(const stage of [...staging])stage.cancel();}
    function publish(primitive,run){
      return new Promise(resolve=>{
        const stage={cancel(){off();staging.delete(stage);remove(primitive);resolve(false);}};
        const off=viewer.scene.postRender.addEventListener(()=>{
          if(dead||run!==generation){stage.cancel();return;}
          if(!primitive.ready){viewer.scene.requestRender();return;}
          off();staging.delete(stage);remove(current);current=primitive;resolve(true);viewer.scene.requestRender();
        });
        staging.add(stage);viewer.scene.primitives.add(primitive);viewer.scene.requestRender();
      });
    }
    function retry(){
      retryAt=Date.now()+RETRY_MS;clearTimeout(retryTimer);
      retryTimer=setTimeout(()=>{key='';if(!dead&&!document.hidden&&last)update(...last);},RETRY_MS);
    }
    async function load(region,longitude,latitude,run){
      report('Budynki OSM: ładowanie…');
      try{
        const data=await Promise.all(region.tiles.map(tileData));
        if(dead||run!==generation)return;
        const missing=data.some((value,index)=>region.tiles[index].required&&!['ready','empty'].includes(value.status));
        if(missing){report('Budynki OSM: część widoku niedostępna; zachowano poprzednie budynki, ponowienie za 30 s.');retry();return;}
        const {selected,limited}=select(data,region.box,longitude,latitude);
        if(!selected.length){remove(current);current=null;report('Brak budynków OSM w tym miejscu');return;}
        const positions=selected.map(value=>C.Cartographic.fromDegrees(value.lon,value.lat));
        await C.sampleTerrain(terrain,LEVEL,positions);
        if(dead||run!==generation)return;
        const instances=selected.map(({item},index)=>{
          const base=Number.isFinite(positions[index].height)?positions[index].height:0;
          const hierarchy=ring=>new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(ring.slice(0,-1).flat()));
          const polygon=hierarchy(item.rings[0]);polygon.holes=item.rings.slice(1).map(hierarchy);
          return new C.GeometryInstance({id:`building:${item.id}`,geometry:new C.PolygonGeometry({polygonHierarchy:polygon,
            height:base+item.min_height,extrudedHeight:base+item.height,closeBottom:false,vertexFormat:C.PerInstanceColorAppearance.VERTEX_FORMAT}),
            attributes:{color:C.ColorGeometryInstanceAttribute.fromColor(C.Color.fromCssColorString('#c7b8a1'))}});
        });
        const primitive=new C.Primitive({geometryInstances:instances,appearance:new C.PerInstanceColorAppearance({flat:false,translucent:false,closed:true}),asynchronous:true,allowPicking:false});
        if(!await publish(primitive,run))return;
        viewer.scene.frameState.creditDisplay.addStaticCredit(credit);
        report(`Budynki OSM: ${selected.length} brył · wysokości przybliżone${limited||region.limited||data.some(value=>value.truncated)?' · przybliż mapę, aby zobaczyć więcej budynków':''}`);
      }catch{
        if(dead||run!==generation)return;
        report('Budynki OSM niedostępne; zachowano poprzedni widok. Ponowienie za 30 s.');retry();
      }
    }
    function refresh(longitude,latitude,height){
      if(dead||document.hidden)return;
      const point=groundTarget(viewer);
      if(point){const p=C.Cartographic.fromCartesian(point);longitude=C.Math.toDegrees(p.longitude);latitude=C.Math.toDegrees(p.latitude);}
      if(height>12000||longitude<14||longitude>24.5||latitude<49||latitude>55){
        generation++;key='';wanted.clear();cancelStaging();remove(current);current=null;
        report(height>12000?'Budynki: przybliż mapę (poniżej 12 km)':'Budynki OSM: obszar Polski');return;
      }
      const region=coverage(viewer,longitude,latitude);
      if(region.key===key&&(!retryAt||Date.now()<retryAt))return;
      key=region.key;retryAt=0;clearTimeout(retryTimer);wanted=new Set(region.tiles.map(t=>t.key));
      const run=++generation;cancelStaging();load(region,longitude,latitude,run);
    }
    function update(longitude,latitude,height=0){
      last=[longitude,latitude,height];if(dead||document.hidden)return;
      drain();clearTimeout(debounce);debounce=setTimeout(()=>refresh(...last),120);
    }
    return {update,destroy(){dead=true;generation++;clearTimeout(debounce);clearTimeout(retryTimer);cancelStaging();remove(current);
      for(const entry of queue)entry.resolve({status:'obsolete'});queue.length=0;cache.clear();}};
  }
  return {create,coverage,select};
})();
