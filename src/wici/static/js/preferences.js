'use strict';
// Restore choices before modules initialize their layers or start data requests.
window.WiciPreferences = (() => {
  const key = 'wici.ui.checkboxes.v1';
  const controls = new Map([...document.querySelectorAll('input[type="checkbox"][id]')]
    .map(control => [control.id, control]));
  const choices = Object.create(null);
  try {
    const saved = JSON.parse(window.localStorage.getItem(key));
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      for (const [id, control] of controls) {
        if (Object.hasOwn(saved, id) && typeof saved[id] === 'boolean') {
          choices[id] = saved[id];
          control.checked = saved[id];
        }
      }
    }
  } catch { /* Unavailable storage or invalid data must not prevent startup. */ }

  function value(id, fallback) {
    return choices[id] ?? fallback;
  }
  function remember(control) {
    if (!control || controls.get(control.id) !== control) return;
    choices[control.id] = control.checked;
    try {
      window.localStorage.setItem(key, JSON.stringify(choices));
    } catch { /* Keep choices in memory when storage is unavailable. */ }
  }
  // Capture also handles the non-bubbling changes emitted by module controls.
  document.addEventListener('change', event => remember(event.target), true);
  return {value, remember};
})();
