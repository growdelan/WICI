const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../src/wici/static/js/requests.js'), 'utf8');
function client(fetch, timers = setTimeout) {
  const ctx = vm.createContext({fetch, TypeError, AbortController, setTimeout: timers, clearTimeout,
    console: {warn() {}}});
  vm.runInContext(script, ctx);
  return ctx.fetchJSON;
}
const ok = () => ({ok: true, json: async () => ({items: [1]})});
test('interrupted GET retries and returns communications', async () => {
  let calls = 0;
  const read = client(async () => {if (++calls === 1) throw new TypeError('Load failed'); return ok();});
  const result = await read('/api/communications', {}, 'komunikatów');
  assert.equal(calls, 2); assert.equal(result.data.items.length, 1);
});
test('interrupted JSON body also retries the map read', async () => {
  let calls = 0;
  const read = client(async () => ++calls === 1
    ? {ok: true, json: async () => {throw new TypeError('Load failed');}} : ok());
  assert.equal((await read('/static/geo/provinces.geojson')).data.items.length, 1);
  assert.equal(calls, 2);
});
test('permanent interruption is bounded and explains which view failed', async () => {
  let calls = 0;
  const read = client(async () => {calls++; throw new TypeError('Load failed');});
  await assert.rejects(read('/api/communications', {}, 'komunikatów'), /komunikatów.*Odśwież widok/);
  assert.equal(calls, 3);
});
test('interrupted source-refresh POST is never replayed', async () => {
  let calls = 0;
  const read = client(async () => {calls++; throw new TypeError('Load failed');});
  await assert.rejects(read('/api/sources/rso/refresh', {method: 'POST'}), /mogło już zostać zaplanowane/);
  assert.equal(calls, 1);
});
test('HTTP error and malformed JSON do not trigger network retries', async () => {
  let calls = 0;
  const read = client(async () => {calls++; return {ok: false, status: 403, json: async () => ({detail: 'CSRF'})};});
  assert.equal((await read('/api/communications')).response.status, 403); assert.equal(calls, 1);
  const malformed = client(async () => {calls++; return {json: async () => {throw new SyntaxError('Invalid JSON');}};});
  await assert.rejects(malformed('/api/communications'), /nieprawidłowe dane/); assert.equal(calls, 2);
});
test('timeout aborts the request and remains bounded', async () => {
  let calls = 0;
  const read = client(async (url, options) => {calls++; return new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Timeout', 'AbortError')));
  });}, (fn, ms) => setTimeout(fn, ms === 10000 ? 5 : 0));
  await assert.rejects(read('/api/communications'), /lokalnego serwera/); assert.equal(calls, 3);
});

test('external layer cancellation aborts in-flight read without retries', async () => {
 const controller=new AbortController();let calls=0;
 const read=client(async (url,options)=>{calls++;return new Promise((resolve,reject)=>{
  options.signal.addEventListener('abort',()=>reject(new DOMException('Hidden layer','AbortError')));
 });});
 const pending=read('/api/gios',{signal:controller.signal});controller.abort();
 await assert.rejects(pending,{name:'AbortError'});assert.equal(calls,1);
 await assert.rejects(read('/api/gios',{signal:controller.signal}),{name:'AbortError'});assert.equal(calls,1);
});
