'use strict';
const {spawn} = require('node:child_process'), {once} = require('node:events');
const net = require('node:net'), path = require('node:path'), fs = require('node:fs');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../..');

async function setup(count = 1000) {
  const socket = net.createServer(); socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  const child = spawn(path.join(root, '.venv/bin/python'), ['-u', '-c', `
import tempfile
from pathlib import Path
import uvicorn
from wici.app import create_app
from wici.config import Config
with tempfile.TemporaryDirectory(prefix='wici-atlas-refresh-') as directory:
    uvicorn.run(create_app(demo=True, root=Path(directory), config=Config(port=${port})), host='127.0.0.1', port=${port}, log_level='error')
`], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  const url = `http://127.0.0.1:${port}`, errors = [], external = [], queries = [];
  let logs = '', browser, records, responseExtra = {};
  child.stdout.on('data', chunk => logs += chunk); child.stderr.on('data', chunk => logs += chunk);
  const stop = async () => {if (child.exitCode === null) {const done = once(child, 'exit'); child.kill('SIGTERM'); await done;}};
  try {
    let ready = false;
    for (let attempt = 0; attempt < 200; attempt++) {
      if (child.exitCode !== null) throw Error(logs);
      try {if ((await fetch(url + '/api/health')).ok) {ready = true; break;}} catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    if (!ready) throw Error('Demo startup timeout: ' + logs);
    const provinces = JSON.parse(fs.readFileSync(path.join(root, 'src/wici/static/geo/provinces.geojson'), 'utf8')).features;
    const sources = ['imgw_meteo', 'rso', 'rcb', 'sg'];
    records = Array.from({length: count}, (_, index) => {
      const province = provinces[index % provinces.length], source = sources[Math.floor(index / provinces.length) % sources.length];
      return {id: `atlas-${index}`, title: `Syntetyczny komunikat ${index}`, source_id: source, source_name: source.toUpperCase(),
        summary: `Syntetyczna treść ${index}`, publication_day: '2026-11-05', version_number: 1,
        source_updated_at: '2026-11-05T12:00:00Z', last_checked_at: '2026-11-05T12:00:00Z',
        communication_type: source === 'imgw_meteo' ? 'warning' : 'notice', warning_status: 'active',
        official_severity: source === 'imgw_meteo' ? 1 : null, category: 'weather',
        locations: [{admin_code: province.properties.admin_code, geometry_ref: province.properties.admin_code,
          name: province.properties.name, role: source === 'imgw_meteo' ? 'warning_area' : 'notification_area'}]};
    });
    browser = await chromium.launch({headless: true, ...(process.env.WICI_CHROMIUM_EXECUTABLE ? {executablePath: process.env.WICI_CHROMIUM_EXECUTABLE} : {})});
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const target = new URL(route.request().url());
      if (target.origin !== url) {external.push(target.href); return route.abort();}
      if (target.pathname === '/api/communications') {
        queries.push(target.search);
        const province = target.searchParams.get('voivodeship');
        const items = province ? records.filter(item => item.locations.some(location => location.admin_code.startsWith(province))) : records;
        return route.fulfill({json: {items, total: items.length, limited: false, ...responseExtra}});
      }
      if (target.pathname.startsWith('/api/communications/atlas-')) {
        return route.fulfill({json: records.find(item => item.id === target.pathname.split('/').at(-1))});
      }
      return route.continue();
    });
    await page.goto(url);
    await page.waitForFunction(() => typeof state !== 'undefined' && state.map && !document.getElementById('refresh').disabled && state.communications.length > 0);
    return {page, errors, external, queries, browserVersion: browser.version(), records,
      setRecords(value) {records = value;}, setResponseExtra(value) {responseExtra = value;},
      async close() {await browser.close(); await stop();}};
  } catch (error) {if (browser) await browser.close(); await stop(); throw error;}
}
module.exports = {setup};
