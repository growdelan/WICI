'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('late communications for old province cannot overwrite the current region',async()=>{
 const source=fs.readFileSync('src/wici/static/js/app.js','utf8'),start=source.indexOf('let communicationRun=0;'),end=source.indexOf('\nfunction compactGroups',start);
 const controls=new Map(),requests=[],state={};let region='02',renders=0;
 const context=vm.createContext({state,$:id=>{if(!controls.has(id))controls.set(id,{value:'2026-10-18'});return controls.get(id);},api:url=>new Promise(resolve=>requests.push({url,resolve})),filters:()=>`voivodeship=${region}`,items:data=>data.items,renderCommunications(){renders++;},renderMap(){}});
 vm.runInContext(source.slice(start,end),context);const old=context.loadCommunications();region='14';const current=context.loadCommunications();
 requests[1].resolve({items:[{id:'Warsaw'}]});await current;requests[0].resolve({items:[{id:'Wroclaw'}]});await old;assert.equal(state.communications[0].id,'Warsaw');assert.equal(renders,1);assert.match(requests[0].url,/02/);assert.match(requests[1].url,/14/);
});
test('communication refresh keeps unchanged presentation but invalidates every visible field and filter',async()=>{
 const source=fs.readFileSync('src/wici/static/js/app.js','utf8'),start=source.indexOf('let communicationRun=0;'),end=source.indexOf('\nfunction compactGroups',start);
 const controls=new Map(),state={};let response,query='date=2026-11-05',listRenders=0,mapRenders=0;
 const context=vm.createContext({state,$:id=>{if(!controls.has(id))controls.set(id,{value:'2026-11-05'});return controls.get(id);},api:async()=>response,filters:()=>query,items:data=>data.items,renderCommunications(){listRenders++;},renderMap(){mapRenders++;}});
 vm.runInContext(source.slice(start,end),context);
 const base={id:'first',source_id:'imgw_meteo',title:'Ostrzeżenie',warning_status:'active',locations:[{admin_code:'14'}]};
 response={items:[base]};await context.loadCommunications();assert.equal(listRenders,1);
 response={items:[{...base,last_checked_at:'2026-11-05T13:00:00Z',summary:'Nowa treść'}],total:9,limited:true};await context.loadCommunications();
 assert.equal(listRenders,1);assert.equal(mapRenders,1);assert.equal(state.communications[0].summary,'Nowa treść');
 assert.equal(controls.get('communication-count').textContent,'1 z 9');assert.equal(controls.get('limit-warning').hidden,false);
 for(const [field,value]of Object.entries({id:'next',source_id:'rso',source_name:'Źródło',title:'Zmiana',communication_type:'exercise',official_severity:3,warning_status:'expired',redacted:true,selection_basis:'display_window',publication_day:'2026-11-04',version_number:2,source_updated_at:'2026-11-05T12:00:00Z',compact_group_key:'grupa',locations:[{admin_code:'02'}]})){
  const before=listRenders;response={items:[{...base,[field]:value}]};await context.loadCommunications();assert.equal(listRenders,before+1,field);
  response={items:[base]};await context.loadCommunications();assert.equal(listRenders,before+2,`${field} restored`);
 }
 const before=listRenders;query='date=2026-11-04';await context.loadCommunications();assert.equal(listRenders,before+1);
 response={items:[]};await context.loadCommunications();assert.equal(listRenders,before+2);assert.equal(mapRenders,listRenders);
});
