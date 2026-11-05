'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {setup} = require('./helpers/atlas_refresh.cjs');

test('unchanged Atlas refresh retains list focus, selection, geometry and open popup while accepting new metadata', {timeout: 90000}, async () => {
  const env = await setup(80), {page} = env;
  try {
    await page.evaluate(async () => {
      await selectCommunication('atlas-0');
      state.cards[0].openPopup();
      window.savedAtlas = {button: document.querySelector('[data-communication-id="atlas-0"]'),
        layers: state.layers.map(item => item.layer), cards: [...state.cards], popup: state.cards[0].getPopup()};
      savedAtlas.button.focus();
    });
    env.setRecords(env.records.map(item => ({...item, last_checked_at: '2026-11-05T12:01:00Z', summary: 'Nowsza pełna treść źródła'})));
    env.setResponseExtra({total: 85, limited: true});
    const retained = await page.evaluate(async () => {
      await loadCommunications(); await loadCommunications();
      return {button: savedAtlas.button === document.querySelector('[data-communication-id="atlas-0"]'),
        focused: document.activeElement === savedAtlas.button, selected: state.selected,
        layers: savedAtlas.layers.every((layer, i) => layer === state.layers[i].layer),
        cards: savedAtlas.cards.every((layer, i) => layer === state.cards[i]), popup: state.map.hasLayer(savedAtlas.popup),
        checked: state.communications[0].last_checked_at, count: document.getElementById('communication-count').textContent,
        limited: !document.getElementById('limit-warning').hidden};
    });
    assert.deepEqual(retained, {button: true, focused: true, selected: 'atlas-0', layers: true, cards: true, popup: true,
      checked: '2026-11-05T12:01:00Z', count: '80 z 85', limited: true});
    await page.evaluate(() => selectCommunication('atlas-0'));
    assert.match(await page.locator('#details .document-text').innerText(), /Nowsza pełna treść/);
    // Today can be selected again without changing the query string.
    await page.evaluate(async () => {await changeDay(state.day);});
    assert.equal(await page.locator('#communication-list .record.active').count(), 0);
    assert.equal(await page.evaluate(() => state.selected), null);
    assert.deepEqual(env.errors, []); assert.deepEqual(env.external, []);
  } finally {await env.close();}
});

test('Atlas refresh invalidates presentation for warning/data changes, regions, days and an empty result', {timeout: 90000}, async () => {
  const env = await setup(80), {page} = env;
  try {
    await page.evaluate(() => {window.previousAtlasButton = document.querySelector('[data-communication-id="atlas-0"]');});
    const records = env.records.map(item => ({...item}));
    records[0] = {...records[0], title: 'Zmienione ostrzeżenie', official_severity: 3, version_number: 2,
      locations: [{...records[1].locations[0], role: 'warning_area'}]};
    env.setRecords(records);
    await page.evaluate(() => loadCommunications());
    assert.match(await page.locator('[data-communication-id="atlas-0"]').innerText(), /Zmienione ostrzeżenie/);
    assert.match(await page.locator('[data-communication-id="atlas-0"]').innerText(), /Stopień 3/);
    assert.equal(await page.evaluate(() => previousAtlasButton === document.querySelector('[data-communication-id="atlas-0"]')), false);
    assert.equal(await page.evaluate(() => state.layers.find(item => item.events.includes('atlas-0')).style.color), '#bf3232');
    const province = records[0].locations[0].admin_code;
    await page.evaluate(async code => {document.getElementById('province').value = code; WiciRegion.select(code, {fit: false}); await loadCommunications();}, province);
    assert.equal(await page.locator('#communication-list .record').count(), records.filter(item => item.locations.some(location => location.admin_code.startsWith(province))).length);
    await page.evaluate(async () => {
      window.previousDayButton = document.querySelector('#communication-list .record');
      const day = new Date(state.day + 'T12:00:00Z'); day.setUTCDate(day.getUTCDate() - 1);
      await changeDay(day.toISOString().slice(0, 10));
    });
    assert.equal(await page.evaluate(() => previousDayButton === document.querySelector('#communication-list .record')), false);
    assert.match(env.queries.at(-1), /date=/);
    env.setRecords([]); await page.evaluate(() => loadCommunications());
    assert.equal(await page.locator('#communication-list .record').count(), 0);
    assert.match(await page.locator('#communication-list').innerText(), /Brak zapisanych komunikatów/);
    assert.deepEqual(await page.evaluate(() => [state.layers.length, state.cards.length]), [0, 0]);
    assert.deepEqual(env.errors, []); assert.deepEqual(env.external, []);
  } finally {await env.close();}
});
