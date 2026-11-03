'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const Motion = require('../src/wici/static/js/workspace-motion.js');
const at = '2020-01-01T12:00:00Z', range = {from: at, to: '2020-01-01T12:20:00Z'};
function setup() {
  const added = [], selected = [], mutations = {positions: 0, icons: 0, styles: 0, radii: 0, tooltips: 0, removed: 0};
  const node = (tag, text) => ({tagName: tag, textContent: text, children: [], style: {}, append(...items) {this.children.push(...items);}});
  const layer = (kind, coords, options) => ({kind, coords, options, radius:options?.radius, handlers: {}, addTo(group) {this.group = group; added.push(this); return this;},
    bindTooltip(content) {this.tooltip = content; return this;}, setTooltipContent(content) {mutations.tooltips++;this.tooltip = content; return this;},
    on(event, action) {this.handlers[event] = action; return this;}, setIcon(icon) {mutations.icons++;this.options.icon = icon; return this;},
    setLatLng(value) {mutations.positions++;this.coords=value;return this;}, removeLayer(value) {mutations.removed++;value.removed=true;return this;},
    setStyle(value) {mutations.styles++;this.style=value;this.options={...this.options,...value};return this;}, setRadius(value) {mutations.radii++;this.radius=value;return this;}, bindPopup(content) {this.popup=content;return this;}, setPopupContent(content) {this.popup=content;return this;}});
  const L = {divIcon: options => options, layerGroup: () => layer('group'), marker: (coords, options) => layer('icon', coords, options),
    circleMarker: (coords, options) => layer('circle', coords, options), polyline: (coords, options) => layer('path', coords, options), geoJSON: (feature, options) => Object.assign(layer('area', null, options), {feature})};
  const window = {L, WiciWorkspaceMotion: Motion, WiciWorkspaceUI: {el: node, button: (text, click) => ({textContent:text,click}), typeNames:{communication:'Komunikat'}, date: value => value, measurement: item => item.measurement, value: () => 'Pomiar', statusNames: {fresh: 'Aktualne'}}};
  const context = {window, L, document: {createElement: node, addEventListener() {}}, Date};
  for (const file of ['aircraft', 'ships', 'workspace-map']) vm.runInNewContext(fs.readFileSync(`src/wici/static/js/${file}.js`, 'utf8'), context);
  const geometries=new Map(), map = window.WiciWorkspaceMap({map: {removeLayer() {}}, geometries, select: ref => selected.push(ref)});
  map.setActive(true);
  return {map, added, selected, window, mutations, geometries};
}
function item(type, metadata = {}, heading = 90) {
  const ref = type === 'aircraft' ? 'aircraft:icao:abc123' : 'ship:mmsi:261000001';
  return {ref, type, label: type === 'aircraft' ? 'LOT123' : 'BALTIC', metadata, freshness: 'fresh', latitude: 52, longitude: 21,
    position: {position_at: at, latitude: 52, longitude: 21, heading, speed_kmh: 100}};
}
const state = (patch = {}) => ({detailOpen: false, comparedRefs: [], query: {time: {mode: 'live'}}, ...patch});

test('unchanged and refreshed catalogue points retain their Leaflet nodes without DOM mutations', () => {
  const h=setup(), first=item('aircraft'), second={...item('ship'),ref:'ship:mmsi:261000002'}, data={as_of:at,map:{points:[first,second]}};
  h.map.render(data,state());const markers=h.added.filter(entry=>entry.kind==='icon');
  const before={...h.mutations};
  h.map.render(data,state());
  h.map.render(JSON.parse(JSON.stringify(data)),state());
  assert.equal(h.added.filter(entry=>entry.kind==='icon').length,2,'An unchanged API refresh must retain markers');
  assert.deepEqual(h.mutations,before,'Unchanged positions, icons and tooltips must not touch Leaflet');
  const moved={...first,label:'NEW123',latitude:53,position:{...first.position,latitude:53,heading:180}};
  h.map.render({as_of:at,map:{points:[moved,second]}},state());
  assert.equal(h.added.filter(entry=>entry.kind==='icon').length,2);
  assert.deepEqual(Array.from(markers[0].coords),[53,21]);assert.equal(markers[0].options.icon.html.style.transform,'rotate(90deg)');
  assert.match(markers[0].tooltip.textContent,/NEW123/);assert.equal(markers[0].options.title,'NEW123');
  assert.equal(h.mutations.positions-before.positions,1);assert.equal(h.mutations.icons-before.icons,1);
  h.map.render({as_of:at,map:{points:[second]}},state());assert.equal(markers[0].removed,true);assert.ok(!markers[1].removed);
});

test('selecting one station preserves all other station presentation and restores it on close', () => {
  const h=setup(), points=['1','2'].map(id=>({ref:`hydro_station:imgw:${id}`,type:'hydro_station',label:id,latitude:52,longitude:21,measurement:{value:100}})),data={as_of:at,map:{points}};
  h.map.render(data,state());const markers=h.added.filter(entry=>entry.kind==='circle'),before={...h.mutations};
  h.map.render(data,state({detailOpen:true,selectedRef:points[0].ref}));
  assert.equal(h.mutations.styles-before.styles,1);assert.equal(h.mutations.radii-before.radii,1);
  assert.equal(markers[0].radius,10);assert.equal(markers[1].radius,6);
  h.map.render(data,state());assert.equal(markers[0].radius,6);assert.equal(h.added.filter(entry=>entry.kind==='circle').length,2);
});

test('shared administrative areas retain their layer and update popup labels, selection and membership', () => {
  const h=setup(), feature={type:'Feature',properties:{admin_code:'14'},geometry:{type:'Polygon',coordinates:[[[21,52],[22,52],[22,53],[21,52]]]}}, first={ref:'communication:1',type:'communication',label:'Pierwszy',areas:[{admin_code:'14'}]}, second={...first,ref:'communication:2',label:'Drugi'};
  h.geometries.set('14',feature);h.map.render({as_of:at,map:{areas:[first,second]}},state());
  const area=h.added.find(entry=>entry.kind==='area');assert.equal(h.added.filter(entry=>entry.kind==='area').length,1);
  assert.equal(area.popup.children.length,3);
  h.map.render({as_of:at,map:{areas:[{...first,label:'Zmieniony'},second]}},state({detailOpen:true,selectedRef:second.ref}));
  assert.equal(h.added.filter(entry=>entry.kind==='area').length,1);assert.equal(area.popup.children[1].textContent,'Zmieniony');assert.equal(area.style.weight,4);
  area.popup.children[2].click();assert.deepEqual(h.selected,[second.ref]);
  h.map.render({as_of:at,map:{areas:[first]}},state());area.handlers.click();assert.deepEqual(h.selected,[second.ref,first.ref]);assert.equal(area.popup.children.length,2);
  h.map.render({as_of:at,map:{areas:[]}},state());assert.equal(area.removed,true);
});

test('equal custom geometry survives refresh and only a changed geometry replaces its layer', () => {
  const h=setup(), object={ref:'custom_area:1',type:'custom_area',label:'Obszar',geometry:{type:'Polygon',coordinates:[[[21,52],[22,52],[22,53],[21,52]]]}};
  h.map.render({as_of:at,map:{areas:[object]}},state());const first=h.added.find(entry=>entry.kind==='area');
  h.map.render({as_of:at,map:{areas:[JSON.parse(JSON.stringify(object))]}},state());assert.equal(h.added.filter(entry=>entry.kind==='area').length,1);
  const updated={...object,geometry:{...object.geometry,coordinates:[[[21,52],[23,52],[23,53],[21,52]]]}};
  h.map.render({as_of:at,map:{areas:[updated]}},state());assert.equal(first.removed,true);assert.equal(h.added.filter(entry=>entry.kind==='area').length,2);
});

test('Analysis live markers share main-map aircraft and AIS symbols, colors, bearing and labels', () => {
  for (const [type, metadata, expected] of [
    ['aircraft', {military: true}, 'aircraft-military'], ['aircraft', {military: false}, 'aircraft-symbol'],
    ['ship', {type_code: 35}, 'ship-military'], ['ship', {type_code: 70}, 'ship-civilian'], ['ship', {}, 'ship-unclassified'],
  ]) {
    const h = setup(), value = item(type, metadata), data = {as_of: at, map: {points: [value]}};
    h.map.render(data, state());
    const marker = h.added.find(entry => entry.kind === 'icon'); assert.ok(marker); assert.equal(h.added.some(entry => entry.kind === 'circle'), false);
    const main = type === 'aircraft' ? h.window.WiciAircraft.icon({...metadata, track: 90})
      : h.window.WiciShips.icon({...metadata, heading: 90, position_at: at}, {referenceAt: Date.parse(at)});
    assert.equal(marker.options.icon.html.className, main.html.className);
    assert.equal(marker.options.icon.html.style.transform, main.html.style.transform);
    assert.ok(marker.options.icon.html.className.includes(expected)); assert.equal(marker.options.title, value.label);
    assert.ok(marker.tooltip.textContent.includes(value.label));
    if (type === 'ship') assert.ok(marker.tooltip.textContent.includes(h.window.WiciShips.classification(metadata).label));
    marker.handlers.click(); assert.deepEqual(h.selected, [value.ref]);
    h.map.render(data, state({detailOpen: true, selectedRef: value.ref}));
    assert.ok(marker.options.icon.className.includes('analysis-transport-selected'));
    assert.equal(marker.options.icon.html.className, main.html.className, 'selection preserves the classification color');
  }
});

test('historical ship styling uses cursor time and recorded bearing rather than wall time or live coordinates', () => {
  const h = setup(), live = item('ship', {type_code: 35}, 200);
  const recorded = {...live.position, heading: 50, latitude: 55, longitude: 18};
  const series = {...live, points: [recorded], gap_seconds: 900}, replay = {range, series: [series]};
  function render(cursor) {
    const frame = Motion.frameAt(series, cursor, range);
    h.map.render({map: {points: [live]}}, state({cursorAt: cursor, comparedRefs: [live.ref], query: {time: {mode: 'range', filter_range: range}}}), null, null,
      {data: replay, frames: new Map([[live.ref, {...frame, label: live.label}]])});
    return h.added.filter(entry => entry.kind === 'icon').at(-1);
  }
  const fresh = render(at);
  assert.deepEqual(Array.from(fresh.coords), [55, 18]); assert.equal(fresh.options.icon.html.style.transform, 'rotate(50deg)');
  assert.equal(fresh.options.icon.html.className, 'ship-symbol ship-military', 'old archive timestamps are fresh at their own cursor');
  const old = render('2020-01-01T12:05:01Z');
  assert.equal(old.options.icon.html.className, 'ship-symbol ship-military ship-old');
  assert.ok(old.tooltip.textContent.includes('klasyfikacja z bieżącego katalogu'));
  assert.ok(old.options.icon.className.includes('analysis-replay-marker'));
});

test('historical aircraft uses shared military color and recorded heading; ships retain unknown direction', () => {
  for (const type of ['aircraft', 'ship']) {
    const h = setup(), value = item(type, type === 'aircraft' ? {military: true} : {}, type === 'aircraft' ? 180 : null);
    const series = {...value, points: [value.position]}, replay = {range, series: [series]};
    h.map.render({map: {points: []}}, state({cursorAt: at, query: {time: {mode: 'range', filter_range: range}}}), null, null,
      {data: replay, frames: new Map([[value.ref, {...Motion.frameAt(series, at, range), label: value.label, color: '#ff00ff'}]])});
    const marker = h.added.find(entry => entry.kind === 'icon');
    if (type === 'aircraft') {assert.equal(marker.options.icon.html.className, 'aircraft-symbol aircraft-military'); assert.equal(marker.options.icon.html.style.transform, 'rotate(90deg)');}
    else assert.equal(marker.options.icon.html.className, 'ship-symbol ship-unclassified ship-direction-unknown');
  }
});

test('non-transport station markers retain their existing measurement rendering', () => {
  const h = setup(), value = {ref: 'hydro_station:imgw:1', type: 'hydro_station', label: 'Wisła', latitude: 52, longitude: 21};
  h.map.render({as_of: at, map: {points: [value]}}, state());
  assert.equal(h.added.filter(entry => entry.kind === 'circle').length, 1);
  assert.equal(h.added.some(entry => entry.kind === 'icon'), false);
});

test('graph stations at a shared cursor override every catalogue marker while preserving the selected sensor context', () => {
  const h = setup(), observed = '2020-01-01T10:00:00Z', cursorAt = '2020-01-01T10:15:00Z';
  h.window.WiciWorkspaceUI.value = sample => sample?.value == null ? 'Brak pomiaru' : `${sample.value} µg/m³`;
  const nodes = ['1','2'].map(id => ({ref:`air_quality_station:gios:${id}`,type:'air_quality_station',label:`GIOŚ ${id}`,latitude:52+Number(id)/100,longitude:21,
    measurement:{value:10,observed_at:observed}, official_index:{value:0,observed_at:observed}}));
  const catalog = nodes.map(node => ({...node,measurement:{value:90,observed_at:'2020-01-01T11:00:00Z'},official_index:{value:5,observed_at:'2020-01-01T11:00:00Z'}}));
  h.map.render({map:{points:catalog}}, state({detailOpen:true,selectedRef:nodes[0].ref,cursorAt,query:{time:{mode:'range',filter_range:{from:observed,to:at}}}}),
    {value:12,observed_at:observed}, {value:1,observed_at:observed}, null, null, {nodes});
  const markers=h.added.filter(layer=>layer.kind==='circle');
  assert.equal(markers.length,2,'catalogue period markers are replaced by graph cursor markers');
  const first=markers.find(layer=>layer.tooltip.textContent.includes('GIOŚ 1')),second=markers.find(layer=>layer.tooltip.textContent.includes('GIOŚ 2'));
  assert.match(first.tooltip.textContent,/12 µg\/m³/);assert.equal(first.options.color,'#80a24c','selected card index remains independent');
  assert.match(second.tooltip.textContent,/10 µg\/m³/);assert.doesNotMatch(second.tooltip.textContent,/90 µg/);assert.equal(second.options.color,'#459a77');
});
