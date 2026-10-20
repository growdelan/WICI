'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('src/wici/static/js/tracking.js','utf8');
const shipsSource=fs.readFileSync('src/wici/static/js/ships.js','utf8');
const startTime=Date.parse('2026-10-20T10:00:00Z');
const sample=(seconds,breakBefore=false)=>({
  position_at:new Date(startTime+seconds*1000).toISOString(),latitude:52+seconds*.00001,
  longitude:19,heading:90,break_before:breakBefore
});
const settle=()=>new Promise(resolve=>setImmediate(resolve));

async function environment(trackFields={}){
  const controls=new Map(),timeouts=new Map(),intervals=new Map(),requests=[],panes=new Map();
  let nextId=0,elapsed=0,group;
  class Element{
    constructor(){
      this.value='';this.dataset={};this.style={};this.children=[];this.listeners={};
      this.textContent='';this.disabled=false;this.classes=new Set();
      this.classList={toggle:(name,enabled)=>enabled?this.classes.add(name):this.classes.delete(name)};
    }
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
    setAttribute(name,value){this[name]=value;}
    addEventListener(name,handler){this.listeners[name]=handler;}
    focus(){}
    getBoundingClientRect(){return {width:390,height:300,top:500,bottom:800};}
    click(){assert.equal(this.disabled,false,'Control must be usable');return this.listeners.click?.();}
  }
  const control=id=>{
    if(!controls.has(id))controls.set(id,new Element());
    return controls.get(id);
  };
  control('speed').value='1';
  const mapLayers=new Set();
  const map={
    createPane(name){const pane={style:{}};panes.set(name,pane);return pane;},
    getPane:name=>panes.get(name),hasLayer:layer=>mapLayers.has(layer),
    removeLayer:layer=>mapLayers.delete(layer),invalidateSize(){},closePopup(){},fitBounds(){},
    getSize:()=>({x:1200,y:800}),
    getContainer:()=>({getBoundingClientRect:()=>({top:0,bottom:800})})
  };
  function geometry(type,coordinates,options){
    return {type,coordinates,options,
      addTo(layer){layer.items.push(this);return this;},
      setLatLngs(value){this.coordinates=value;return this;},
      setStyle(value){Object.assign(this.options,value);return this;},
      setLatLng(value){this.coordinates=value;return this;},
      setIcon(value){this.options.icon=value;return this;}};
  }
  const L={
    layerGroup:()=>group={items:[],addTo(){mapLayers.add(this);return this;},clearLayers(){this.items=[];}},
    polyline:(coords,options)=>geometry('line',coords,options),
    marker:(coords,options)=>geometry('marker',coords,options),
    divIcon:options=>options,latLngBounds:coords=>coords
  };
  const feed={
    detail:{track:{id:'old-track',kind:'aircraft',object_id:'48abcd',label:'TEST',
      started_at:new Date(startTime).toISOString(),active:true,status:'live',message:'',...trackFields},
      points:[sample(0,true),sample(30),sample(7200,true),sample(7210)]},
    failStart:false,failStop:false
  };
  class ClockDate extends Date{static now(){return startTime+7210000;}}
  const context={
    window:{},document:{hidden:false,getElementById:id=>control(id.replace(/^tracking-/,'')),
      createElement:()=>new Element(),querySelector:()=>null,addEventListener(){}},
    localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    L,Date:ClockDate,Intl,AbortController,performance:{now:()=>elapsed},
    setTimeout(fn,ms){const id=++nextId;timeouts.set(id,{fn,ms});return id;},
    clearTimeout:id=>timeouts.delete(id),
    setInterval(fn,ms){const id=++nextId;intervals.set(id,{fn,ms});return id;},
    clearInterval:id=>intervals.delete(id),
    async fetch(url,options){
      requests.push({url,method:options.method||'GET'});
      let body,ok=true;
      if(options.method==='POST'){
        assert.equal(options.headers['X-CSRF-Token'],'test-token');
        if(url.endsWith('/stop')){
          if(feed.failStop){ok=false;body={detail:'Nie udało się zakończyć zapisu.'};}
          else{feed.detail.track.active=false;feed.detail.track.status='stopped';body=feed.detail;}
        }else if(feed.failStart){ok=false;body={detail:'Osiągnięto limit aktywnych obserwacji.'};}
        else{
          feed.detail={...feed.detail,track:{...feed.detail.track,id:'new-track',object_id:'48abce'}};
          body=feed.detail;
        }
      }else body=url==='/api/tracks'?{items:[feed.detail.track]}:feed.detail;
      const payload=structuredClone(body);
      return {ok,json:async()=>payload};
    }
  };
  vm.runInNewContext(shipsSource,context);
  vm.runInNewContext(source,context);
  const ui=context.window.WiciTracking;
  ui.init({map,health:{mode:'live',csrf_token:'test-token'}});
  ui.sync({visible:true});
  await settle();
  assert.equal(control('session').value,'old-track');
  return {
    ui,feed,control,intervals,requests,get geometry(){return group.items;},
    seek(seconds){control('timeline').value=String(startTime+seconds*1000);control('timeline').listeners.input();},
    async poll(){
      const entry=[...timeouts.entries()].find(([,timer])=>timer.ms===10000);
      assert.ok(entry,'The production controller must schedule the next history poll');
      timeouts.delete(entry[0]);entry[1].fn();await settle();
    },
    tick(ms=100){elapsed+=ms;for(const timer of [...intervals.values()])timer.fn();},
    close(){ui.sync({visible:false});}
  };
}

for(const active of [true,false]){
  test(`exit clears selection and playback for an ${active?'active':'archived'} track`,async()=>{
    const env=await environment({active});
    try{
      const points=structuredClone(env.feed.detail.points);
      env.control('panel').open=true;
      env.control('play').click();
      await env.control('exit').click();await settle();
      assert.equal(env.feed.detail.track.active,false);
      assert.deepEqual(env.feed.detail.points,points);
      assert.equal(env.requests.filter(request=>request.method==='POST').length,active?1:0);
      assert.equal(env.geometry.length,0);
      assert.equal(env.intervals.size,0);
      assert.equal(env.control('session').value,'');
      assert.equal(env.control('panel').open,false);
      await env.poll();
      env.ui.sync({visible:false});env.ui.sync({visible:true});await settle();
      assert.equal(env.geometry.length,0);
      assert.equal(env.control('session').value,'');
      env.control('session').value='old-track';
      await env.control('session').listeners.change();
      assert.ok(env.geometry.length>0,'Saved history must remain available for explicit selection');
    }finally{env.close();}
  });
}

test('failed stop during exit keeps the selected track and explains the failure',async()=>{
  const env=await environment();
  try{
    env.control('panel').open=true;
    env.feed.failStop=true;
    await env.control('exit').click();await settle();
    assert.equal(env.control('session').value,'old-track');
    assert.equal(env.control('panel').open,true);
    assert.equal(env.feed.detail.track.active,true);
    assert.ok(env.geometry.length>0);
    assert.match(env.control('status').textContent,/Nie udało się zakończyć zapisu/);
    env.feed.failStop=false;
    await env.control('exit').click();await settle();
    assert.equal(env.geometry.length,0);
    assert.equal(env.feed.detail.track.active,false);
  }finally{env.close();}
});

for(const military of [true,false,null]){
  test(`aircraft classification ${military} survives live, history, playback and stale states`,async()=>{
    const env=await environment({military});
    try{
      function aircraft(){
        const reticle=env.geometry.find(item=>item.type==='marker').options.icon.html;
        const symbol=reticle.children.at(-1);
        const plane=symbol.children.find(child=>child.className?.split(' ').includes('aircraft-symbol'));
        assert.ok(plane,'The tracked aircraft must use the same classification style as the live aircraft layer');
        assert.equal(plane.className.split(' ').includes('aircraft-military'),military===true);
        assert.equal(plane.textContent,'✈');
        return reticle;
      }
      aircraft();
      env.seek(30);
      assert.match(aircraft().className,/tracking-history/);
      env.control('play').click();env.tick();
      aircraft();
      env.control('live').click();await settle();
      env.feed.detail.points=[sample(0,true),{...sample(30),heading:null}];
      await env.poll();
      assert.match(aircraft().className,/tracking-stale/);
      env.control('stop').click();await settle();
      aircraft();
    }finally{env.close();}
  });
}

test('polling updates aircraft classification without requiring a new position',async()=>{
  const env=await environment({military:null});
  try{
    const symbol=()=>env.geometry.find(item=>item.type==='marker').options.icon.html.children.at(-1).children[0];
    env.feed.detail.track.military=true;
    await env.poll();
    assert.ok(symbol());
    assert.match(symbol().className,/\baircraft-military\b/);
    env.feed.detail.track.military=false;
    await env.poll();
    assert.ok(!symbol().className.includes('aircraft-military'));
  }finally{env.close();}
});

for(const [shipType,category] of [[35,'military'],[70,'civilian'],[null,'unclassified'],[51,'unclassified']]){
  test(`ship type ${shipType} preserves classification in live, history, playback and stale states`,async()=>{
    const env=await environment({kind:'ship',object_id:'261000001',ship_type_code:shipType});
    try{
      function ship(){
        const reticle=env.geometry.find(item=>item.type==='marker').options.icon.html;
        const vessel=reticle.children.at(-1).children.find(child=>child.className?.split(' ').includes('ship-symbol'));
        assert.ok(vessel,'The tracked ship must retain the live layer symbol and classification');
        assert.ok(vessel.className.split(' ').includes(`ship-${category}`));
        return {reticle,vessel};
      }
      ship();
      env.seek(30);
      assert.match(ship().reticle.className,/tracking-history/);
      env.control('play').click();env.tick();
      ship();
      env.control('live').click();await settle();
      env.feed.detail.points=[sample(0,true),{...sample(30),heading:null}];
      await env.poll();
      assert.match(ship().reticle.className,/tracking-stale/);
      assert.match(ship().vessel.className,/ship-direction-unknown/);
      env.control('stop').click();await settle();
      ship();
    }finally{env.close();}
  });
}

test('late ship metadata updates the classification at the same recorded position',async()=>{
  const env=await environment({kind:'ship',object_id:'261000001',ship_type_code:null});
  try{
    const location=JSON.stringify(env.geometry.find(item=>item.type==='marker').coordinates);
    for(const [shipType,category] of [[35,'military'],[70,'civilian'],[51,'unclassified']]){
      env.feed.detail.track.ship_type_code=shipType;
      await env.poll();
      const marker=env.geometry.find(item=>item.type==='marker');
      assert.equal(JSON.stringify(marker.coordinates),location);
      const vessel=marker.options.icon.html.children.at(-1).children[0];
      assert.ok(vessel);
      assert.ok(vessel.className.split(' ').includes(`ship-${category}`));
    }
  }finally{env.close();}
});

for(const operation of ['start','stop']){
  test(`failed ${operation} stays visible inside a history gap until a successful retry`,async()=>{
    const env=await environment();
    try{
      env.seek(3600);
      assert.match(env.control('status').textContent,/Przerwa w obserwacji/);
      const button=operation==='start'
        ?env.ui.button('aircraft',()=>({hex:'48abce'})):env.control('stop');
      const flag=operation==='start'?'failStart':'failStop';
      const error=operation==='start'?'Osiągnięto limit aktywnych obserwacji.':'Nie udało się zakończyć zapisu.';
      env.feed[flag]=true;
      button.click();await settle();
      assert.equal(env.control('status').textContent,error);
      assert.ok(env.control('status').classes.has('tracking-warning'));
      assert.equal(env.control('session').value,'old-track');
      assert.equal(env.feed.detail.track.active,true);
      // Mutation completion itself triggers a successful refresh; another scheduled
      // GET must not erase an error whose failed operation has not been retried.
      await env.poll();
      assert.equal(env.control('status').textContent,error);
      assert.ok(env.requests.filter(request=>request.method==='GET').length>=6);
      env.feed[flag]=false;
      button.click();await settle();
      assert.ok(!env.control('status').textContent.includes(error));
      if(operation==='start')assert.equal(env.control('session').value,'new-track');
      else assert.equal(env.control('recording').textContent,'ZAPIS ZAKOŃCZONY');
    }finally{env.close();}
  });
}

for(const remaining of [0,1]){
  test(`retention leaving ${remaining} points stops playback and fresh history can play again`,async()=>{
    const env=await environment();
    try{
      env.control('play').click();
      assert.equal(env.intervals.size,1);
      assert.equal(env.control('play').textContent,'Pauza');
      const queuedTick=[...env.intervals.values()][0].fn;
      env.tick();
      env.feed.detail.points=remaining?[sample(7210)]:[];
      await env.poll();
      assert.equal(env.intervals.size,0,'Retention must cancel playback before another timer tick');
      assert.equal(env.control('play').textContent,'Odtwórz');
      assert.equal(env.control('play').disabled,true);
      assert.equal(env.control('timeline').disabled,true);
      if(!remaining){
        assert.equal(env.geometry.length,0,'An empty archive must clear both route lines and the cursor marker');
        assert.equal(env.control('timeline').value,'0');
      }
      assert.doesNotThrow(()=>env.tick());
      assert.doesNotThrow(queuedTick,'A playback callback queued before retention must also be harmless');
      assert.equal(env.intervals.size,0);
      env.feed.detail.points=[sample(7220,true),sample(7230)];
      await env.poll();
      assert.equal(env.control('play').disabled,false);
      env.control('play').click();
      const before=Number(env.control('timeline').value);
      env.tick(1000);
      assert.ok(Number(env.control('timeline').value)>before,'Playback must advance after fresh observations arrive');
      assert.equal(env.intervals.size,1);
      env.control('play').click();
      assert.equal(env.intervals.size,0);
    }finally{env.close();}
  });
}
