'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
test('late communications for old province cannot overwrite the current region',async()=>{
 const source=fs.readFileSync('src/wici/static/js/app.js','utf8'),start=source.indexOf('let communicationRun=0;'),end=source.indexOf('\nfunction compactGroups',start);
 const controls=new Map(),requests=[],state={};let region='02',renders=0;
 const context=vm.createContext({state,$:id=>{if(!controls.has(id))controls.set(id,{value:'2026-10-18'});return controls.get(id);},api:url=>new Promise(resolve=>requests.push({url,resolve})),filters:()=>`voivodeship=${region}`,items:data=>data.items,renderCommunications(){renders++;},renderMap(){}});
 vm.runInContext(source.slice(start,end),context);const old=context.loadCommunications();region='14';const current=context.loadCommunications();
 requests[1].resolve({items:[{id:'Warsaw'}]});await current;requests[0].resolve({items:[{id:'Wroclaw'}]});await old;assert.equal(state.communications[0].id,'Warsaw');assert.equal(renders,1);assert.match(requests[0].url,/02/);assert.match(requests[1].url,/14/);
});
