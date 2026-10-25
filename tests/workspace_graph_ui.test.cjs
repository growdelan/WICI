'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const G = require('../src/wici/static/js/workspace-graph.js');
const S = require('../src/wici/static/js/workspace-store.js');
const data = {nodes: ['A','B','C','D'].map(ref => ({ref, label: ref})), edges: [
  {id:'ab',source_ref:'A',target_ref:'B',directed:true},
  {id:'bc',source_ref:'B',target_ref:'C',directed:false},
]};

test('visible graph excludes hidden endpoints and their edges without mutating saved data', () => {
  const visible = G.visibleData(data, ['B']);
  assert.deepEqual(visible.nodes.map(n=>n.ref), ['A','C','D']); assert.deepEqual(visible.edges, []);
  assert.equal(data.nodes.length, 4); assert.equal(data.edges.length, 2);
});

test('path discovery is restricted to the loaded visible graph and handles disconnected or identical nodes', () => {
  assert.deepEqual(G.pathBetween(data,'A','C'), {nodes:['A','B','C'],edges:['ab','bc']});
  assert.deepEqual(G.pathBetween(data,'C','A'), {nodes:['C','B','A'],edges:['bc','ab']});
  assert.equal(G.pathBetween(data,'A','D'), null); assert.equal(G.pathBetween(data,'A','C',['B']), null);
  assert.equal(G.pathBetween(data,'A','missing'), null); assert.deepEqual(G.pathBetween(data,'A','A'),{nodes:['A'],edges:[]});
});

test('graph transport glyphs preserve aircraft military color and the exact AIS civilian whitelist', () => {
  assert.equal(G.transportStyle({type:'aircraft',metadata:{military:true},position:{heading:90}}).color,'#b45309');
  assert.equal(G.transportStyle({type:'aircraft',metadata:{military:false},position:{heading:180}}).angle,90);
  assert.equal(G.transportStyle({type:'aircraft',metadata:{military:null}}).color,'#17465c');
  assert.equal(G.transportStyle({type:'ship',metadata:{type_code:35}}).color,'#843ba7');
  assert.equal(G.transportStyle({type:'ship',metadata:{type_code:70}}).color,'#126b78');
  for (const code of [null, undefined, 0, 1, 51, 99, '70']) assert.equal(G.transportStyle({type:'ship',metadata:{type_code:code}}).color,'#65717e');
});

test('historical ship styling uses the graph reference time and preserves unknown direction', () => {
  const node={type:'ship',metadata:{type_code:70},position:{position_at:'2026-10-20T12:00:00Z',heading:120}};
  assert.equal(G.transportStyle(node,Date.parse('2026-10-20T12:05:00Z')).old,false);
  assert.equal(G.transportStyle(node,Date.parse('2026-10-20T12:05:01Z')).old,true);
  assert.equal(G.transportStyle({...node,position:{heading:360}}).unknown,true);
  assert.equal(G.transportStyle({...node,position:{heading:null}}).unknown,true);
  assert.equal(G.transportStyle({...node,position:{heading:0}}).unknown,false);
  const decoded=decodeURIComponent(G.symbol(node)); assert.match(decoded,/rotate\(120,24,24\)/);
});

test('graph symbols never interpolate object labels or metadata into SVG', () => {
  const svg=decodeURIComponent(G.symbol({type:'communication',label:'<script>bad</script>',metadata:{name:'<image href="https://evil.test"/>'}}));
  assert.doesNotMatch(svg, /script|evil\.test|image href/); assert.match(svg,/xmlns="http:\/\/www.w3.org\/2000\/svg"/);
});

test('graph view and table scope do not change catalogue filters or temporal selection', () => {
  const store=S.createStore(); store.dispatch({type:'SET_TIME_RANGE',range:{from:'2026-10-20T00:00:00Z',to:'2026-10-21T00:00:00Z'}}); store.dispatch({type:'SET_CURSOR',at:'2026-10-20T12:00:00Z'});
  const before=store.getState(); store.dispatch({type:'SET_GRAPH_MODE',mode:'both'}); store.dispatch({type:'SET_TABLE_SCOPE',scope:'graph'}); store.dispatch({type:'SET_LAYOUT',patch:{mobilePanel:'graph'}});
  const after=store.getState(); assert.equal(after.query,before.query); assert.equal(after.cursorAt,before.cursorAt); assert.equal(after.queryRevision,before.queryRevision);
  assert.equal(after.graphMode,'both'); assert.equal(after.tableScope,'graph'); assert.equal(after.layout.mobilePanel,'graph');
  store.dispatch({type:'SET_GRAPH_MODE',mode:'invalid'}); assert.equal(store.getState(),after);
});

class Element {
  constructor(tag,text='') {this.tag=tag;this.text=text==null?'':String(text);this.children=[];}
  append(...nodes) {this.children.push(...nodes);}
  get textContent() {return this.text+' '+this.children.map(node=>node.textContent).join(' ');}
  set textContent(value) {this.text=String(value);this.children=[];}
}
const U={el:(tag,text)=>new Element(tag,text),safeLink(url){try {const parsed=new URL(url);return ['http:','https:'].includes(parsed.protocol)?new Element('a',url):null;}catch{return null;}}};

test('edge facts expose exact source version and uncertain time bounds without declaring missing evidence for empty arrays',()=>{
  const host=new Element('section');G.renderEdgeFacts(host,{provenance:{source_id:'ukraine_alerts',source_url:'https://neptun.in.ua/',document_version_id:44,evidence_missing:[],basis:'Wybrany epizod'},time:{kind:'interval',first_seen_at:'2026-10-20T12:00:00Z',ended_after:'2026-10-20T12:10:00Z',ended_before:'2026-10-20T12:15:00Z'}},U);
  assert.match(host.textContent,/Wersja dokumentu\s+44/);assert.match(host.textContent,/Koniec później niż[\s\S]*2026-10-20T12:10:00Z/);assert.match(host.textContent,/Koniec nie później niż[\s\S]*2026-10-20T12:15:00Z/);
  assert.doesNotMatch(host.textContent,/Niedostępne materiały/);assert.match(host.textContent,/https:\/\/neptun.in.ua\//);
});

test('edge explanations preserve analyst text literally and refuse executable evidence links',()=>{
  const host=new Element('section');G.renderEdgeFacts(host,{provenance:{justification:'current',source_url:'javascript:alert(1)',evidence_missing:['note']},time:{kind:'analyst_assertion'}},U);
  assert.match(host.textContent,/Uzasadnienie analityka\s+current/);assert.match(host.textContent,/Powiązanie dodane przez analityka/);assert.match(host.textContent,/Niedostępne materiały/);assert.doesNotMatch(host.textContent,/javascript/);
});

test('edge limit disclosure explains the loaded count and requires narrowing rather than implying all edges are available',()=>{
  assert.match(G.limitMessage({edge_limit_reached:true,edges:new Array(500),edge_total:620,limits:{max_edges:500}}),/Pokazano 500 z 620 relacji/);
  assert.match(G.limitMessage({edge_limit_reached:true,edges:[],edge_total:620}),/zawęź rodzaj lub podstawę/);
  assert.equal(G.limitMessage({edge_limit_reached:false}), '');
});


test('saved graph time formatting uses its frozen timezone and preserves raw instants and day precision',()=>{
  const edge={provenance:{source_published_date:'2026-06-20'},time:{kind:'observation',observed_at:'2026-06-20T12:00:00Z'}};
  const first=new Element('section');G.renderEdgeFacts(first,edge,{...U,date:()=>{throw Error('Global time formatter must not be used');}},'Europe/Kyiv');
  const second=new Element('section');G.renderEdgeFacts(second,edge,{...U,date:()=>'UTC global changed'},'Europe/Kyiv');
  assert.equal(first.textContent,second.textContent);assert.match(first.textContent,/15:00:00/);assert.match(first.textContent,/2026-06-20T12:00:00Z/);assert.match(first.textContent,/2026-06-20 · sama data/);
});


test('highlighting a discovered path preserves square node badges and their symbols in both themes',()=>{
  for(const dark of [false,true]) {
    const rules=G.styles(dark),nodeStyle=Object.assign({},...rules.filter(rule=>['node','node.graph-path'].includes(rule.selector)).map(rule=>rule.style));
    assert.equal(nodeStyle.width,44);assert.equal(nodeStyle.height,44);assert.equal(nodeStyle['background-image'],'data(symbol)');assert.equal(nodeStyle['border-width'],4);
    assert.equal(rules.find(rule=>rule.selector==='edge.graph-path').style.width,4);
    assert.equal(rules.some(rule=>rule.selector==='.graph-path'),false);
  }
});
