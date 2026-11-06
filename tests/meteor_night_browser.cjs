'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {environment, camera, distance} = require('./helpers/vehicle3d_browser.cjs');

const id = key => '#meteor-night-' + key;
const nysaId = '20261104215730_pYgTq';

async function openNight(page) {
  for (const selector of ['#layer-panel', id('group')]) {
    const group = page.locator(selector);
    if (!await group.evaluate(element => element.open)) await group.locator(':scope > summary').click();
  }
  await page.locator(id('open')).click();
  await page.locator(id('dialog') + '[open][data-state="ready"]').waitFor();
}

async function assertScene(page) {
  const dialog = page.locator(id('dialog'));
  await page.waitForFunction(() => ['ready', 'unavailable'].includes(document.querySelector('#meteor-night-dialog').dataset.scene));
  assert.equal(await dialog.getAttribute('data-scene'), 'ready', await page.locator(id('scene-note')).textContent());
  assert.equal(await page.evaluate(() => window.__vehicleViewers.at(-1).scene.context.webgl2), true);
}

async function pickVisibleTrack(page) {
  const hit = await page.waitForFunction(() => {
    const view = window.__vehicleViewers.at(-1);
    const bounds = view.canvas.getBoundingClientRect();
    for (const entity of view.entities.values) {
      if (!entity.id.startsWith('meteor-path-')) continue;
      const [a, b] = entity.polyline.positions.getValue(view.clock.currentTime);
      const middle = Cesium.Cartesian3.midpoint(a, b, new Cesium.Cartesian3());
      const pos = view.scene.cartesianToCanvasCoordinates(middle);
      if (!pos || view.scene.pick(pos)?.id !== entity) continue;
      const x = pos.x + bounds.left, y = pos.y + bounds.top;
      if (document.elementFromPoint(x, y) === view.canvas) return {id: entity.id.slice(12), x, y};
    }
    return false;
  });
  const {id: eventId, x, y} = await hit.jsonValue();
  await page.mouse.click(x, y);
  await page.locator(id('dialog') + '[data-mode="trajectory"]').waitFor();
  assert.equal(await page.locator(id('dialog')).getAttribute('data-event-id'), eventId);
}

async function checkHead(page, endpoint) {
  await page.waitForFunction(p => {
    const view = window.__vehicleViewers.at(-1);
    const head = view.entities.getById('meteor-head');
    const point = head?.position?.getValue(view.clock.currentTime);
    return head?.show && point && Cesium.Cartesian3.distance(point, Cesium.Cartesian3.fromDegrees(...p)) < .1;
  }, endpoint);
}

test('a real GMN night can be scrubbed, slowed down and viewed from the ground, offline', {timeout: 100000}, async () => {
  const env = await environment({name: 'meteor-night-desktop'});
  const {page} = env;
  try {
    await openNight(page);
    await assertScene(page);
    const dialog = page.locator(id('dialog'));
    assert.equal(await dialog.getAttribute('data-mode'), 'night');
    assert.ok(await page.locator(id('list') + ' button[data-event-id]').count() > 1);
    // Two independent catalogue IDs have overlapping recorded intervals.
    // At 19:20:07 UTC both trajectories should have an active marker.
    await page.locator(id('time')).evaluate(slider => {
      slider.value = String(1793820007 - Number(slider.dataset.start));
      slider.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await page.waitForFunction(() => {
      const viewer = window.__vehicleViewers.at(-1);
      const ids = ['meteor-head', 'meteor-head-2'].map(id => {
        const head = viewer.entities.getById(id);
        return head?.show && head.name;
      });
      return ids.includes('20261104192006_HOIK4') && ids.includes('20261104192006_1T9cT');
    });
    await pickVisibleTrack(page);
    await page.locator(id('featured')).click();
    assert.equal(await dialog.getAttribute('data-event-id'), nysaId);
    assert.equal(await dialog.getAttribute('data-mode'), 'trajectory');
    const slider = page.locator(id('time'));
    const start = Number(await slider.getAttribute('min'));
    const end = Number(await slider.getAttribute('max'));
    assert.equal(start, 0);
    assert.equal(end, 4080);
    await slider.press('End');
    assert.equal(Number(await slider.inputValue()), end);
    await checkHead(page, [17.792420, 50.831556, 60593.3]);
    await slider.press('Home');
    await checkHead(page, [17.352034, 50.471106, 82665.5]);
    await page.locator(id('speed')).selectOption('0.1');
    await page.locator(id('play')).click();
    await page.waitForFunction(() => Number(document.querySelector('#meteor-night-time').value) >= 5);
    await page.locator(id('play')).click();
    const stopped = Number(await slider.inputValue());
    assert.ok(stopped > start && stopped < end);
    const overview = await camera(page);
    await page.locator(id('ground')).click();
    assert.equal(await dialog.getAttribute('data-mode'), 'ground');
    assert.ok(distance(overview, await camera(page)) > 1000);
    assert.ok(Math.abs(Number(await slider.inputValue()) - stopped) < .002);
    await page.locator(id('observer')).selectOption('warszawa');
    await page.locator(id('pick')).click();
    await page.locator(id('map-prompt')).waitFor();
    // The map's ordinary pointer handler supplies the chosen coordinates.
    await page.locator('#map').click({position: {x: 220, y: 220}});
    await dialog.waitFor();
    await assertScene(page);
    assert.equal(await dialog.getAttribute('data-mode'), 'ground');
    assert.equal(await dialog.getAttribute('data-event-id'), nysaId);
    await page.locator(id('night')).click();
    assert.equal(await dialog.getAttribute('data-mode'), 'night');
    await page.keyboard.press('Escape');
    await dialog.waitFor({state: 'hidden'});
    assert.equal(await page.evaluate(() => window.__vehicleViewers.every(view => view.isDestroyed())), true);
    await env.clean();
  } finally {
    await env.stop();
  }
});

test('mobile catalogue reports an empty night and can return to the packaged recording', {timeout: 75000}, async () => {
  const env = await environment({viewport: {width: 390, height: 844}, name: 'meteor-night-mobile'});
  const {page} = env;
  try {
    await openNight(page);
    await assertScene(page);
    const fits = await page.locator(id('dialog')).evaluate(dialog => dialog.scrollWidth <= dialog.clientWidth + 1);
    assert.ok(fits, 'The player must fit the viewport width');
    await page.route('**/api/meteors/night?date=2026-11-01', route => route.fulfill({json: {
      date: '2026-11-01', start: 1793530800, end: 1793617200, bundled: false,
      events: [], source_url: 'https://globalmeteornetwork.org/data/',
    }}));
    await page.locator(id('date')).fill('2026-11-01');
    await page.locator(id('load')).click();
    await page.locator(id('dialog') + '[data-state="empty"]').waitFor();
    assert.equal(await page.locator(id('play')).isDisabled(), true);
    assert.equal(await page.locator(id('list') + ' button[data-event-id]').count(), 0);
    await page.locator(id('date')).fill('2026-11-04');
    await page.locator(id('load')).click();
    await page.locator(id('featured')).waitFor();
    await page.locator(id('featured')).click();
    await assertScene(page);
    await page.locator(id('close')).click();
    await page.locator(id('dialog')).waitFor({state: 'hidden'});
    await env.clean();
  } finally {
    await env.stop();
  }
});
