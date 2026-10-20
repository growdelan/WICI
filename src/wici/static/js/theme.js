'use strict';
// Run before stylesheets so a stored night theme is applied before first paint.
// This module owns presentation only: no data requests, timers or layer controls.
(() => {
  const key = 'wici.ui.theme.v1';
  const root = document.documentElement;
  let theme = 'light';
  try {
    if (window.localStorage.getItem(key) === 'dark') theme = 'dark';
  } catch {
    // Private/restricted browser storage must not prevent using either theme.
  }
  root.setAttribute('data-theme', theme);

  function bindToggle() {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    function updateButton() {
      button.setAttribute('aria-pressed', String(theme === 'dark'));
      button.title = theme === 'dark' ? 'Wróć do Atlasu (motyw jasny)' : 'Włącz WICI Noc (motyw ciemny)';
    }
    updateButton();
    button.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', theme);
      updateButton();
      try {
        window.localStorage.setItem(key, theme);
      } catch {
        // The current tab can still switch appearance without persistence.
      }
      document.dispatchEvent(new CustomEvent('wici:themechange', {detail: {theme}}));
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bindToggle, {once: true});
  else bindToggle();
})();
