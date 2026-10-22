'use strict';
window.WiciWorkspaceViews = function (host, {request, getConfig, apply, saved, status}) {
  const U = window.WiciWorkspaceUI, details = U.el('details', null, 'analysis-saved-views'), summary = U.el('summary', 'Zapisane stanowiska'), content = U.el('div', null, 'analysis-saved-content');
  const select = U.el('select'); select.id = 'analysis-saved-view'; select.setAttribute('aria-label', 'Zapisane stanowisko');
  const name = U.el('input'); name.type = 'text'; name.maxLength = 100; name.placeholder = 'Nazwa stanowiska'; name.id = 'analysis-view-name'; name.setAttribute('aria-label', 'Nazwa stanowiska');
  const relative = U.el('input'); relative.type = 'checkbox'; relative.id = 'analysis-view-relative';
  const relativeLabel = U.field('Przywracaj zakres względem bieżącego czasu', relative);
  let views = [], selected = null, busy = false;
  function showError(error) {status(error.status === 409 ? 'Stanowisko zmieniono w innym oknie. Wczytaj aktualną wersję przed ponownym zapisem.' : `Nie udało się zapisać stanowiska: ${error.message}`);}
  function payload() {const config = getConfig(); if (relative.checked && config.query.time.mode === 'range') {
    const range = config.query.time.filter_range; config.relative_seconds = Math.round((Date.parse(range.to) - Date.parse(range.from)) / 1000);
  } return {name: name.value.trim(), schema_version: 1, config};}
  async function mutate(kind) {if (busy) return; const body = payload(); if (kind !== 'DELETE' && !body.name) {status('Podaj nazwę stanowiska.'); name.focus(); return;}
    busy = true; controls.forEach(button => {button.disabled = true;});
    try {
      if (kind === 'DELETE') {await request(`/workspace/views/${encodeURIComponent(selected.id)}`, null, {method: 'DELETE'}); selected = null; saved(null); name.value = '';}
      else {const view = await request(selected && kind === 'PUT' ? `/workspace/views/${encodeURIComponent(selected.id)}` : '/workspace/views', selected && kind === 'PUT' ? {...body, revision: selected.revision} : body, {method: kind}); selected = view; saved(view.id); status('Konfiguracja stanowiska została zapisana.');}
      await load();
    } catch (error) {showError(error);} finally {busy = false; updateButtons();}
  }
  const loadButton = U.button('Otwórz', () => {if (!selected) return; const config = structuredClone(selected.config); name.value = selected.name;
    relative.checked = Boolean(config.relative_seconds); apply(config, selected.id); status(`Otwarto stanowisko „${selected.name}”.`);
  }), saveButton = U.button('Zapisz nowe', () => mutate('POST')), updateButton = U.button('Aktualizuj', () => mutate('PUT')), deleteButton = U.button('Usuń konfigurację', () => mutate('DELETE'));
  const controls = [loadButton, saveButton, updateButton, deleteButton];
  function updateButtons() {loadButton.disabled = updateButton.disabled = deleteButton.disabled = busy || !selected; saveButton.disabled = busy;}
  select.addEventListener('change', () => {selected = views.find(view => String(view.id) === select.value) || null; if (selected) {name.value = selected.name; relative.checked = Boolean(selected.config?.relative_seconds);} updateButtons();});
  async function load() {
    try {const result = await request('/workspace/views'); views = Array.isArray(result) ? result : result.items || []; const selectedId = selected?.id;
      select.replaceChildren(); const blank = U.el('option', 'Wybierz zapisane stanowisko'); blank.value = ''; select.append(blank);
      for (const view of views) {const option = U.el('option', view.name); option.value = view.id; select.append(option);} select.value = selectedId || ''; selected = views.find(view => view.id === selectedId) || null; updateButtons();
    } catch (error) {status(`Zapisane stanowiska są niedostępne: ${error.message}`);}
  }
  content.append(select, loadButton, name, relativeLabel, saveButton, updateButton, deleteButton); details.append(summary, content); host.append(details); updateButtons();
  return {load};
};
