'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {environment} = require('./helpers/vehicle3d_browser.cjs');

test('the meteor catalogue works without WebGL, keeps full card heights and finds the closest observed beginning', {timeout:60000}, async () => {
  const env = await environment({name:'meteor-night-fallback',viewport:{width:1390,height:660}});
  const {page} = env, ui = name => page.locator('#meteor-night-' + name);
  try {
    const night = await (await page.request.get(new URL('/api/meteors/night?date=2026-11-04',page.url()).href)).json();
    await page.evaluate(() => {window.WiciScene3D.loadEngine = () => Promise.reject(Error('WebGL niedostępny'));});
    await page.locator('#layer-panel > summary').click();
    await page.locator('#meteor-night-group > summary').click();
    await ui('open').click();
    await page.locator('#meteor-night-dialog[data-scene="unavailable"][data-state="ready"]').waitFor();
    assert.equal(await ui('list').locator('button').count(),night.events.length);
    const bounds = await ui('featured').evaluate(button => {
      const rect = button.getBoundingClientRect(), text = button.querySelector('span').getBoundingClientRect();
      return {card:rect.bottom, text:text.bottom, next:document.querySelector('.mn-event').getBoundingClientRect().top};
    });
    assert.ok(bounds.text <= bounds.card && bounds.card < bounds.next, JSON.stringify(bounds));
    await ui('featured').click();
    const original = await ui('dialog').getAttribute('data-event-id');
    await ui('observer').selectOption('warszawa');
    assert.equal(await ui('dialog').getAttribute('data-event-id'),original);
    // Independent great-circle reference using the spherical law of cosines.
    const radians = Math.PI/180, lat = 52.230*radians, lon = 21.012*radians;
    const distance = event => Math.acos(Math.sin(lat)*Math.sin(event.begin.lat*radians) +
      Math.cos(lat)*Math.cos(event.begin.lat*radians)*Math.cos(lon-event.begin.lon*radians));
    const expected = [...night.events].sort((a,b) => distance(a)-distance(b))[0];
    assert.equal(await ui('nearest').getAttribute('data-event-id'),expected.id);
    await ui('nearest').click();
    assert.equal(await ui('dialog').getAttribute('data-event-id'),expected.id);
    assert.equal(await ui('dialog').getAttribute('data-mode'),'ground');
    assert.ok(await ui('duration').innerText() !== '—');
    // Supersede a slow night lookup while its response is still in flight.
    let unblock;
    const blocked = new Promise(resolve => {unblock = resolve;});
    await page.route('**/api/meteors/night?date=2026-11-02', async route => {
      await blocked;
      await route.fulfill({json:{...night,date:'2026-11-02'}}).catch(() => {});
    });
    const pending = page.waitForRequest('**/api/meteors/night?date=2026-11-02');
    await ui('date').fill('2026-11-02'); await ui('load').click(); await pending;
    await page.route('**/api/meteors/night?date=2026-11-01', route =>
      route.fulfill({json:{...night,date:'2026-11-01',events:[]}}));
    await ui('date').fill('2026-11-01'); await ui('load').click();
    await page.locator('#meteor-night-dialog[data-state="empty"]').waitFor(); unblock();
    assert.equal(await ui('list').locator('button').count(),0);
    assert.equal(await ui('nearest').isDisabled(),true);
    await page.keyboard.press('Escape');
    assert.equal(await ui('open').evaluate(button => document.activeElement === button),true);
    await env.clean();
  } finally {await env.stop();}
});
