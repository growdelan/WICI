'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const Store = require('../src/wici/static/js/workspace-store.js');

test('workspace time formatting preserves DST, date precision and timezone changes with bounded formatters', () => {
  let constructions = 0;
  class CountingFormatter extends Intl.DateTimeFormat {constructor(...args) {super(...args); constructions++;}}
  const window = {};
  vm.runInNewContext(fs.readFileSync('src/wici/static/js/workspace-table.js', 'utf8'), {window, Date, Intl: {DateTimeFormat: CountingFormatter}});
  const U = window.WiciWorkspaceUI;
  const dates = ['2026-03-29T00:59:00Z', '2026-03-29T01:00:00Z', '2026-10-25T00:30:00Z', '2026-10-25T01:30:00Z'];
  for (let repeat = 0; repeat < 3; repeat++) for (const timeZone of ['Europe/Warsaw', 'Europe/Kyiv', 'UTC']) {
    U.setTimezone(timeZone);
    for (const value of dates) {
      assert.equal(U.date(value), new Intl.DateTimeFormat('pl-PL', {timeZone, dateStyle: 'short', timeStyle: 'short'}).format(new Date(value)));
      assert.equal(U.shortTime(value), new Intl.DateTimeFormat('pl-PL', {timeZone, hour: '2-digit', minute: '2-digit'}).format(new Date(value)));
    }
    assert.equal(U.date('2026-11-05'), '2026-11-05 · sama data');
    assert.equal(U.shortTime('2026-11-05'), '2026-11-05 · sama data');
    assert.equal(U.date(null), 'Brak czasu'); assert.equal(U.shortTime(null), 'Brak czasu');
    assert.equal(U.date('not-a-date'), 'Czas nieznany'); assert.equal(U.shortTime('not-a-date'), 'Brak czasu');
  }
  U.setTimezone('invalid'); assert.equal(U.shortTime('2026-11-05T00:00:00Z'), '01:00');
  assert.equal(constructions, 6, 'Only two styles for each of the three supported timezones are constructed');
});

test('station cursor selects the latest eligible revision from unsorted history without mutating it', () => {
  const range = {from: '2026-11-05T00:00:00Z', to: '2026-11-05T04:00:00Z'};
  const base = {observed_at: '2026-11-05T02:00:00Z', sensor_id: '1', metric: 'water_level', quality: 'valid', revision: 1, value: 17};
  const correction = {...base, revision: 3, value: null}, tie = {...correction, value: 99};
  const samples = [
    {...base, observed_at: range.to, value: 900}, {...base, sensor_id: '2', revision: 20},
    {...base, metric: 'temperature', revision: 20}, {...base, observed_at: 'invalid'},
    {...base, quality: 'future', revision: 20}, correction, {...base}, tie,
    {...base, observed_at: '2026-11-04T23:59:00Z'}, {...base, quality: 'unknown_time', revision: 20},
    {...base, observed_at: range.from, value: 0}
  ].map(Object.freeze);
  Object.freeze(samples);
  assert.equal(Store.sampleAt(samples, '2026-11-05T02:00:00Z', range, 1, 'water_level'), correction);
  assert.equal(Store.sampleAt(samples, null, range, '1', 'water_level'), correction);
  assert.equal(Store.sampleAt(samples, '2026-11-05T01:59:59Z', range, '1', 'water_level').value, 0);
  assert.equal(Store.sampleAt(samples, '2026-11-04T23:59:59Z', range, '1', 'water_level'), null);
  assert.equal(Store.sampleAt(samples, 'invalid', range, '1', 'water_level'), null);
  assert.equal(Store.sampleAt(samples, null, range, 'missing', 'water_level'), null);
  assert.equal(Store.sampleAt([{at: range.from, value: 12, time_status: 'unknown_time'}], null, range), null);
  assert.equal(Store.sampleAt([{at: range.from, value: 12}], null, range).value, 12);
});
