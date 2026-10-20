'use strict';
window.WiciAircraftMotion = (() => {
  const EARTH_METRES=6371008.8, MAX_SAMPLES=32, MAX_SPEED_MPS=600, JUMP_TOLERANCE_METRES=1500;
  const radians=value=>value*Math.PI/180, degrees=value=>value*180/Math.PI;
  const wrap=value=>((value+180)%360+360)%360-180;
  const heading=value=>((value%360)+360)%360;
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const optional=value=>finite(value)?value:null;
  const duration=(value,fallback)=>finite(value)&&value>=0?value:fallback;
  const vector=point=>{
    const lat=radians(point.latitude),lon=radians(point.longitude),cos=Math.cos(lat);
    return [cos*Math.cos(lon),cos*Math.sin(lon),Math.sin(lat)];
  };
  function separation(a,b){
    const lat1=radians(a.latitude),lat2=radians(b.latitude);
    const value=Math.sin((lat2-lat1)/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin(radians(wrap(b.longitude-a.longitude))/2)**2;
    return 2*Math.asin(Math.sqrt(Math.min(1,Math.max(0,value))));
  }
  function between(a,b,fraction){
    const first=vector(a),second=vector(b),angle=separation(a,b),sine=Math.sin(angle);
    // Linear unit vectors avoid division by zero for coincident positions.
    const left=Math.abs(sine)<1e-10?1-fraction:Math.sin((1-fraction)*angle)/sine;
    const right=Math.abs(sine)<1e-10?fraction:Math.sin(fraction*angle)/sine;
    const [x,y,z]=first.map((value,index)=>left*value+right*second[index]);
    return {latitude:degrees(Math.atan2(z,Math.hypot(x,y))),longitude:wrap(degrees(Math.atan2(y,x)))};
  }
  function forward(point,milliseconds){
    const distance=point.speed_kmh/3.6*milliseconds/1000/EARTH_METRES;
    const lat=radians(point.latitude),lon=radians(point.longitude),bearing=radians(point.track);
    const nextLat=Math.asin(Math.max(-1,Math.min(1,Math.sin(lat)*Math.cos(distance)+Math.cos(lat)*Math.sin(distance)*Math.cos(bearing))));
    const nextLon=lon+Math.atan2(Math.sin(bearing)*Math.sin(distance)*Math.cos(lat),Math.cos(distance)-Math.sin(lat)*Math.sin(nextLat));
    return {latitude:degrees(nextLat),longitude:wrap(degrees(nextLon))};
  }
  function blend(a,b,key,fraction){
    if(fraction===0)return a[key];
    if(fraction===1)return b[key];
    if(a[key]===null||b[key]===null)return null;
    return key==='track'?heading(a[key]+wrap(b[key]-a[key])*fraction):a[key]+(b[key]-a[key])*fraction;
  }
  function createTrack({delayMs=12000,maxExtrapolationMs=5000,maxAgeMs=30000,maxSpeedMps=MAX_SPEED_MPS,jumpToleranceMetres=JUMP_TOLERANCE_METRES}={}){
    delayMs=duration(delayMs,12000);maxExtrapolationMs=duration(maxExtrapolationMs,5000);maxAgeMs=duration(maxAgeMs,30000);
    maxSpeedMps=duration(maxSpeedMps,MAX_SPEED_MPS);jumpToleranceMetres=duration(jumpToleranceMetres,JUMP_TOLERANCE_METRES);
    let points=[],segment=0;
    // Presentation smoothing must not connect a fresh track to a disconnected old one.
    function clear(){points=[];segment++;}
    function push(item){
      if(!item||!finite(item.latitude)||Math.abs(item.latitude)>90||!finite(item.longitude)||Math.abs(item.longitude)>180||typeof item.position_at!=='string')return false;
      const time=Date.parse(item.position_at);
      if(!Number.isFinite(time))return false;
      const last=points.at(-1);
      if(last&&time<=last.time)return false;
      const point={time,latitude:item.latitude,longitude:wrap(item.longitude),altitude_m:optional(item.altitude_m),
        track:finite(item.track)&&item.track>=0&&item.track<=360?heading(item.track):null,
        speed_kmh:finite(item.speed_kmh)&&item.speed_kmh>=0?item.speed_kmh:null};
      if(last){
        const elapsed=time-last.time;
        // A disconnected or implausible report starts a new track, never a flight across the map.
        if(elapsed>maxAgeMs||separation(last,point)*EARTH_METRES>maxSpeedMps*elapsed/1000+jumpToleranceMetres)clear();
      }
      points.push(point);
      if(points.length>MAX_SAMPLES)points.shift();
      return true;
    }
    function sample(nowMs=Date.now()){
      if(!points.length||!finite(nowMs))return null;
      const first=points[0],last=points.at(-1),ageMs=Math.max(0,nowMs-last.time);
      // Freshness also limits the playback clock, including custom prediction windows.
      const target=Math.min(nowMs,last.time+maxAgeMs)-delayMs;
      const result=(point,time,state)=>({latitude:point.latitude,longitude:point.longitude,altitude_m:point.altitude_m,
        track:point.track,speed_kmh:point.speed_kmh,position_at:new Date(time).toISOString(),ageMs,segment,state:ageMs>maxAgeMs?'stale':state});
      if(points.length===1||target<=first.time)return result(first,first.time,'warming');
      if(target<=last.time){
        const index=points.findIndex(point=>point.time>=target),a=points[index-1],b=points[index],fraction=(target-a.time)/(b.time-a.time);
        return result({...between(a,b,fraction),altitude_m:blend(a,b,'altitude_m',fraction),
          track:blend(a,b,'track',fraction),speed_kmh:blend(a,b,'speed_kmh',fraction)},target,'interpolated');
      }
      // Clamp the prediction time even after it expires: holding and stale never snap backwards.
      const elapsed=Math.min(target-last.time,maxExtrapolationMs);
      if(last.track===null||last.speed_kmh===null||maxExtrapolationMs===0)return result(last,last.time,'holding');
      return result({...last,...forward(last,elapsed)},last.time+elapsed,target-last.time<=maxExtrapolationMs?'predicted':'holding');
    }
    return {push,sample,clear};
  }
  return {createTrack};
})();
