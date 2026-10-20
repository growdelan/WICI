'use strict';
// Presentation controls stay independent of data loading and map layer ownership.
window.WiciAtlas = (() => {
  const panel = document.getElementById('detail-panel');
  const heading = document.getElementById('detail-title');
  const layers = document.getElementById('layer-panel');
  const mapElement = document.getElementById('map');
  let map = null;
  let selectedId = null;
  let detailRevision = 0;
  let framePending = false;
  const schedule = window.requestAnimationFrame?.bind(window) || (fn => setTimeout(fn, 0));

  function refreshLayout() {
    if (framePending) return;
    framePending = true;
    schedule(() => {
      framePending = false;
      if (!document.getElementById('situation')?.hidden) map?.invalidateSize({pan: false});
    });
  }
  function revealOnStackedLayout(target) {
    // On phones the list and map stack vertically; focus alone keeps the drawer offscreen.
    if (window.matchMedia?.('(max-width: 600px)').matches) {
      target?.scrollIntoView({block: 'nearest', behavior: 'auto'});
    }
  }
  function closeDetails(restoreFocus = true) {
    if (!panel || panel.hidden) return;
    detailRevision++;
    const focusedInside = panel.contains(document.activeElement);
    panel.hidden = true;
    if (restoreFocus && focusedInside) {
      const record = [...document.querySelectorAll('[data-communication-id]')]
        .find(button => button.getAttribute('data-communication-id') === String(selectedId));
      const target = record || mapElement;
      target?.focus({preventScroll: true});
      revealOnStackedLayout(target);
    }
    refreshLayout();
  }
  function openDetails(id) {
    if (!panel) return;
    selectedId = id;
    panel.hidden = false;
    if (layers) layers.open = false;
    heading?.focus({preventScroll: true});
    revealOnStackedLayout(panel);
    refreshLayout();
  }
  function updateFilterSummary() {
    const summary = document.getElementById('filter-selection');
    const controls = document.getElementById('filters')?.elements;
    if (!summary || !controls) return;
    const chosen = ['category', 'voivodeship'].filter(name => controls.namedItem(name)?.value).length
      + (controls.namedItem('include_active')?.checked ? 1 : 0);
    summary.textContent = chosen === 0 ? 'Bez dodatkowych filtrów'
      : chosen === 1 ? '1 aktywny filtr' : `${chosen} aktywne filtry`;
  }
  document.getElementById('filters')?.addEventListener('change', updateFilterSummary);
  updateFilterSummary();
  document.getElementById('close-details')?.addEventListener('click', () => closeDetails());
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (layers?.open) {
      layers.open = false;
      layers.querySelector('summary')?.focus({preventScroll: true});
      event.preventDefault();
    } else if (panel && !panel.hidden) {
      closeDetails();
      event.preventDefault();
    }
  });
  document.addEventListener('click', event => {
    const themeToggle = document.getElementById('theme-toggle');
    if (layers?.open && !layers.contains(event.target) && !themeToggle?.contains(event.target)) layers.open = false;
  });
  layers?.addEventListener('toggle', refreshLayout);
  for (const tab of document.querySelectorAll('.tab')) {
    tab.addEventListener('click', () => {
      if (layers) layers.open = false;
      refreshLayout();
    });
  }
  window.addEventListener('resize', refreshLayout);
  if (window.ResizeObserver && mapElement) {
    new window.ResizeObserver(refreshLayout).observe(mapElement);
  }
  return {
    get revision() { return detailRevision; },
    openDetails,
    closeDetails,
    resetDetails() { closeDetails(false); selectedId = null; },
    refreshLayout,
    updateFilterSummary,
    setMap(value) { map = value; refreshLayout(); }
  };
})();
