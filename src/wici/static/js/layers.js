'use strict';
window.WiciLayers = (() => {
  const names = {'communications-enabled':'Komunikaty i ostrzeżenia','ukraine-enabled':'Ukraina — NEPTUN','s5p-enabled':'Sentinel-5P — atmosfera','s2-enabled':'Sentinel-2 — przed / po','gfm-enabled':'Zalania satelitarne GFM','quality-enabled':'Jakość pozycji / GNSS','ioda-enabled':'Problemy łączności internetowej','gios-enabled':'Jakość powietrza GIOŚ','imagery-enabled':'Zobrazowania po katastrofach','fires-enabled':'FIRMS','effis-enabled':'FWI','traffic-enabled':'Ruch',
    'buses-enabled':'Autobusy','trains-enabled':'Kolej','ships-enabled':'Statki AIS','aircraft-enabled':'Samoloty','gddkia-enabled':'Utrudnienia','hydro-stations':'Wodowskazy','hydro-warnings':'Ostrzeżenia hydro','weather-wind':'Wiatr','weather-rain':'Opady punktowe','radar-enabled':'Radar','lightning-enabled':'Wyładowania'};
  function update() {
    const chosen = Object.entries(names).filter(([id]) => { const control = document.getElementById(id); return control?.checked && !control.disabled; }).map(([,name]) => name);
    document.getElementById('layer-selection').textContent = `· ${chosen.length} aktywnych`;
  }
  // Only primary data layers count; the base map, animation, masks and module
  // helper checkboxes never become additional layers. Native groups keep their state.
  const observer = window.MutationObserver ? new window.MutationObserver(update) : null;
  for (const id of Object.keys(names)) {
    const control = document.getElementById(id);
    control?.addEventListener('change', update);
    if (control) observer?.observe(control, {attributes: true, attributeFilter: ['disabled', 'checked']});
  }
  window.WiciRegion?.initProgress(names);
  update(); return {update};
})();
