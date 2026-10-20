'use strict';

// Reuse the same synthetic integration scenarios in WICI Noc without changing
// their default Atlas run or injecting a theme into production code.
async function setTestTheme(page) {
  if (process.env.WICI_TEST_THEME !== 'dark') return;
  await page.addInitScript(() => {
    if (location.protocol === 'http:') localStorage.setItem('wici.ui.theme.v1', 'dark');
  });
}

module.exports = {setTestTheme};
