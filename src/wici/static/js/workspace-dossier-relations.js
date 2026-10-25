'use strict';
/* Dossier-owned assertions and working layouts. Graph facts stay server-owned. */
window.WiciDossierRelations = function (host, {request, getContext, mutate, notify, ask, close, materialTitle, showMaterial,
  getNavigationToken, isNavigationCurrent, clearMaterialTitle}) {
  const U = window.WiciWorkspaceUI, base = '/workspace/dossiers';
  const el = (tag, text, id) => {const node = U.el(tag, text); if (id) node.id = id; return node;};
  const button = (text, id, fn) => {const node = U.button(text, fn); node.id = id; return node;};
  const block = (title) => {const node = U.el('section', null, 'analysis-dossier-section'); node.append(el('h3', title)); host.append(node); return node;};
  const graphBox = block('Graf teczki'), seedList = el('div', null, 'analysis-dossier-graph-seeds');
  const hint = el('p', 'Wybierz do 20 przypiętych obiektów początkowych. Graf korzysta z aktualnych lokalnych danych.', 'analysis-dossier-graph-hint');
  const graphActions = U.el('div', null, 'analysis-dossier-actions');
  const open = button('Otwórz graf teczki', 'analysis-dossier-graph-open', openGraph);
  const save = button('Zapisz układ grafu', 'analysis-dossier-graph-save', saveGraph);
  const load = button('Wczytaj zapisany układ', 'analysis-dossier-graph-load', loadGraph);
  const capture = button('Zapisz kopię grafu', 'analysis-dossier-graph-capture', captureGraph);
  graphActions.append(open, save, load, capture); graphBox.append(hint, seedList, graphActions);
  const editor = block('Powiązania analityczne'), intro = el('p', 'Ręczne powiązania należą do tej teczki. Wymagają uzasadnienia i pozostają interpretacją analityka; nie zmieniają faktów źródłowych.');
  const source = el('select', null, 'analysis-relation-source'), target = el('select', null, 'analysis-relation-target');
  const justification = el('textarea', null, 'analysis-relation-justification'); justification.rows = 3; justification.maxLength = 5000;
  const note = el('select', null, 'analysis-relation-note'), material = el('select', null, 'analysis-relation-material');
  const actions = U.el('div', null, 'analysis-dossier-actions');
  const submit = button('Dodaj powiązanie', 'analysis-relation-save', saveRelation);
  const cancel = button('Odrzuć szkic powiązania', 'analysis-relation-cancel', () => ask('Odrzucić niezapisany szkic powiązania?', () => {drafts.delete(owner); paintForm();}));
  const refresh = button('Wczytaj aktualne powiązania', 'analysis-relations-reload', () => loadRelations(true));
  const showDeleted = el('input', null, 'analysis-relations-show-deleted'); showDeleted.type = 'checkbox';
  showDeleted.addEventListener('change', () => loadRelations(true));
  const deletedToggle = U.field('Pokaż usunięte powiązania i ich historię', showDeleted); deletedToggle.className = 'analysis-graph-seed';
  const list = el('div', null, 'analysis-relations-list'), status = el('p', '', 'analysis-relations-status'); status.setAttribute('role', 'status');
  actions.append(submit, cancel, refresh);
  editor.append(intro, U.field('Obiekt A', source), U.field('Obiekt B', target), U.field('Uzasadnienie powiązania', justification),
    U.field('Notatka stanowiąca podstawę (opcjonalnie)', note), U.field('Zapisany materiał (opcjonalnie)', material), actions,
    deletedToggle, status, list);
  let owner = null, ownerRevision = null, relationRun = 0, configRun = 0, loading = false, configLoading = false, objectKey = '', seedKey = '', rows = [];
  const drafts = new Map(), selectedSeeds = new Map(), configurations = new Map();
  const workspace = () => window.WiciWorkspace;
  const draft = () => {if (!drafts.has(owner)) drafts.set(owner, {id: null, revision: null, source_ref: '', target_ref: '', justification: '', note_id: '', material_id: ''}); return drafts.get(owner);};
  function values() {
    const context = getContext(), objects = new Map();
    for (const object of [...(context.dossier?.pins || []), ...(workspace()?.getGraphData?.()?.nodes || []), context.object].filter(Boolean)) {
      objects.set(object.ref, object);
    }
    for (const relation of rows) for (const side of ['source', 'target']) {
      const ref = relation[side+'_ref']; if (!objects.has(ref)) objects.set(ref, {ref, label: relation[side+'_label'] || ref});
    }
    return [...objects.values()];
  }
  function options(select, entries, value, placeholder) {
    select.replaceChildren(); const blank = el('option', placeholder); blank.value = ''; select.append(blank);
    for (const [id, label] of entries) {const option = el('option', label); option.value = id; select.append(option);}
    if (value && !entries.some(([id]) => id === value)) {const missing = el('option', `Niedostępne: ${value}`); missing.value = value; select.append(missing);}
    select.value = value || '';
  }
  function paintForm() {
    const current = draft(), context = getContext(), objects = values();
    const entries = objects.map(object => [object.ref, `${object.label || object.ref}${object.available === false ? ' · niedostępny' : ''}`]);
    options(source, entries, current.source_ref, 'Wybierz obiekt'); options(target, entries, current.target_ref, 'Wybierz obiekt');
    options(note, (context.dossier?.notes || []).map(item => [item.id, item.body.slice(0,100)]), current.note_id, 'Bez notatki');
    options(material, (context.dossier?.materials || []).map(item => [item.id, item.title]), current.material_id, 'Bez materiału');
    justification.value = current.justification; submit.textContent = current.id ? 'Zapisz powiązanie' : 'Dodaj powiązanie'; controls();
  }
  for (const [control, key] of [[source, 'source_ref'], [target, 'target_ref'], [note, 'note_id'], [material, 'material_id']]) {
    control.addEventListener('change', () => {draft()[key] = control.value; controls();});
  }
  justification.addEventListener('input', () => {draft().justification = justification.value; controls();});
  function controls() {
    const context = getContext(), blocked = context.busy || loading || !context.dossier;
    for (const node of [source, target, justification, note, material, submit, cancel, refresh, showDeleted]) node.disabled = Boolean(blocked);
    const current = draft(); submit.disabled ||= !current.source_ref || !current.target_ref || current.source_ref === current.target_ref || !current.justification.trim();
    cancel.disabled ||= !current.id && !current.justification && !current.source_ref && !current.target_ref;
    open.disabled = Boolean(context.busy || !context.dossier || !(selectedSeeds.get(owner)?.size));
    capture.disabled = Boolean(context.busy || !context.dossier || !workspace()?.getGraphCapture?.());
    save.disabled = capture.disabled || configLoading;
    // A missing layout may be created by another window; an explicit read must remain available.
    load.disabled = Boolean(context.busy || configLoading || !context.dossier);
    for (const control of seedList.querySelectorAll('input')) control.disabled = Boolean(context.busy);
    for (const control of list.querySelectorAll('button')) control.disabled = Boolean(blocked);
  }
  function paintSeeds() {
    const pins = getContext().dossier?.pins || [], key = JSON.stringify([owner, pins.map(item => [item.ref,item.label,item.available])]);
    if (key === seedKey) return; seedKey = key;
    if (!selectedSeeds.has(owner)) selectedSeeds.set(owner, new Set(pins.length <= 20 ? pins.map(item => item.ref) : []));
    const selected = selectedSeeds.get(owner), valid = new Set(pins.map(item => item.ref));
    for (const ref of selected) if (!valid.has(ref)) selected.delete(ref);
    seedList.replaceChildren();
    for (const pin of pins) {
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = pin.ref; checkbox.checked = selected.has(pin.ref);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked && selected.size >= 20) {checkbox.checked = false; notify('Graf może zaczynać się od najwyżej 20 obiektów.'); return;}
        if (checkbox.checked) selected.add(pin.ref); else selected.delete(pin.ref); controls();
      });
      const field = U.field(`${pin.label || pin.ref}${pin.available === false ? ' · niedostępny w katalogu' : ''}`, checkbox); field.className = 'analysis-graph-seed'; seedList.append(field);
    }
    if (!pins.length) seedList.append(el('p', 'Przypnij obiekty do teczki lub rozpocznij graf z karty obiektu.'));
    if (pins.length > 20) seedList.prepend(el('p', 'Teczka ma ponad 20 przypięć. Wybierz jawnie do 20 obiektów początkowych.'));
  }
  function openGraph() {
    const refs = [...(selectedSeeds.get(owner) || [])]; if (!refs.length || refs.length > 20) return;
    const id = owner; close(); workspace()?.openGraph?.({seed_refs: refs, dossier_id: id});
  }
  async function configMeta() {
    const id = owner, run = ++configRun; configLoading = true; controls();
    try {const result = await request(`${base}/${id}/graph`); if (id === owner && run === configRun) configurations.set(id, result);}
    catch (error) {if (id === owner && run === configRun) {if (error.status === 404) configurations.set(id, {revision:0,exists:false}); else notify(`Nie udało się wczytać układu grafu: ${error.message}`, true);}}
    finally {if (id === owner && run === configRun) {configLoading = false; controls();}}
  }
  async function saveGraph() {
    const config = workspace()?.getGraphConfig?.(); if (!config || !owner) return;
    if (config.graph?.dossier_id !== owner) {notify('Otwórz graf tej teczki przed zapisaniem układu.', true); return;}
    await mutate(async id => {
      const body = {graph:config.graph, positions:config.positions || {}, hidden_refs:config.hidden_refs || [],
        layout:config.layout || 'breadthfirst', node_type:config.node_type || null, revision:configurations.get(id)?.revision || 0};
      const result = await request(`${base}/${id}/graph`, body, {method:'PUT'}); configurations.set(id, result);
    }, 'Zapisano roboczy układ grafu. Dane odświeżą się przy otwarciu.',
    'Układ zmieniono w innym oknie. Twój bieżący graf pozostał zachowany. Użyj „Wczytaj zapisany układ”, aby otworzyć aktualną wersję.');
  }
  async function loadGraph() {
    if (!owner) return; const id = owner, run = ++configRun, navigationToken = getNavigationToken(); configLoading = true; controls();
    try {const config = await request(`${base}/${id}/graph`); if (id !== owner || run !== configRun || !isNavigationCurrent(navigationToken)) return; configurations.set(id, config); close(); workspace()?.openGraph?.({dossier_id: id, config});}
    catch (error) {if (id === owner && run === configRun && isNavigationCurrent(navigationToken)) notify(error.status === 404 ? 'Ta teczka nie ma zapisanego układu grafu.' : `Nie udało się wczytać grafu: ${error.message}`, true);}
    finally {if (id === owner && run === configRun) {configLoading = false; controls();}}
  }
  async function captureGraph() {
    const config = workspace()?.getGraphCapture?.(); if (!owner || !config) return;
    if (config.graph?.dossier_id !== owner) {notify('Otwórz graf tej teczki przed zapisaniem kopii.', true); return;}
    let result, navigationToken;
    await mutate(async id => {navigationToken = getNavigationToken(); result = await request(`${base}/${id}/materials`, {kind:'graph', graph:config.graph, positions:config.positions,
      hidden_refs:config.hidden_refs || [], node_type:config.node_type || null, layout:config.layout || 'breadthfirst', title:materialTitle.value.trim() || 'Graf powiązań',
      display_timezone:getContext().state.displayTimezone || 'Europe/Warsaw'}, {method:'POST'}); clearMaterialTitle();}, 'Zapisano niezmienną kopię grafu.',
    'Graf zmienił się lub jego kontekst wygasł. Otwórz graf, odśwież powiązania i spróbuj ponownie. Tytuł zachowano.');
    if (result && owner === result.dossier_id && isNavigationCurrent(navigationToken)) showMaterial(result);
  }
  async function saveRelation() {
    const current = {...draft()}; if (!owner || !current.justification.trim() || current.source_ref === current.target_ref) return;
    await mutate(async id => {
      await request(`${base}/${id}/relations${current.id ? '/'+current.id : ''}`, {source_ref:current.source_ref, target_ref:current.target_ref,
        justification:current.justification.trim(), note_id:current.note_id || null, material_id:current.material_id || null,
        ...(current.id ? {revision:current.revision} : {})}, {method:current.id ? 'PUT' : 'POST'});
      drafts.delete(id); workspace()?.refreshGraph?.();
    }, 'Zapisano powiązanie analityczne. Podstawa jest widoczna w szczegółach relacji.');
  }
  async function loadRelations(force = false) {
    if (!owner || loading && !force) return; const id = owner, run = ++relationRun; loading = true; controls();
    try {const result = await request(`${base}/${id}/relations${showDeleted.checked ? '?include_deleted=true' : ''}`); if (id !== owner || run !== relationRun) return; rows = result.items || []; paintRows(); objectKey = ''; paintForm();}
    catch (error) {if (id === owner && run === relationRun) notify(`Nie udało się wczytać powiązań: ${error.message}`, true);}
    finally {if (id === owner && run === relationRun) {loading = false; controls();}}
  }
  function paintRows() {
    list.replaceChildren(); status.textContent = `${rows.filter(item => !item.deleted).length} aktywnych powiązań analitycznych${showDeleted.checked ? ` · ${rows.filter(item => item.deleted).length} usuniętych` : ''}.`;
    for (const relation of rows) {
      const row = U.el('article', null, 'analysis-dossier-entry'); row.dataset.relationId = relation.id;
      row.append(el('strong', `${relation.source_label || relation.source_ref} ↔ ${relation.target_label || relation.target_ref}`),
        U.el('p', relation.justification, 'analysis-note-text'), el('small', `Relacja analityka · rewizja ${relation.revision} · ${U.date(relation.updated_at)}`));
      if (relation.deleted) row.append(U.el('p', 'Powiązanie usunięte. Pozostaje wyłącznie historia zmian.', 'muted'));
      if (Array.isArray(relation.evidence_missing) ? relation.evidence_missing.length : relation.evidence_missing) row.append(U.el('p', 'Wskazana notatka lub zapisany materiał nie są już dostępne. Uzasadnienie i historia relacji pozostają zachowane.', 'notice'));
      const edit = U.button('Edytuj', () => {
        const apply = () => {drafts.set(owner, {id:relation.id,revision:relation.revision,source_ref:relation.source_ref,target_ref:relation.target_ref,
          justification:relation.justification,note_id:relation.note_id || '',material_id:relation.material_id || ''}); paintForm(); justification.focus();};
        if (draft().justification || draft().id) ask('Odrzucić szkic powiązania i otworzyć wybraną relację?', apply); else apply();
      });
      const history = el('details'), summary = el('summary', 'Historia zmian'); history.append(summary);
      history.addEventListener('toggle', async () => {
        if (!history.open || history.dataset.loaded) return; const id = owner, run = relationRun;
        try {const result = await request(`${base}/${id}/relations/${relation.id}/history`); if (owner !== id || run !== relationRun || !row.isConnected) return;
          for (const item of result.items || []) {
            const payload = item.payload || {}, action = {create:'Utworzono',update:'Zmieniono',delete:'Usunięto'}[item.action] || item.action;
            const entry = el('article'); entry.append(el('p', `Rewizja ${item.revision} · ${action} · ${U.date(item.at)} — ${payload.justification || ''}`));
            const recordedNote = payload.evidence?.note_id, recordedMaterial = payload.evidence?.material_id;
            if (recordedNote) {const noteCopy = el('details'); noteCopy.append(el('summary', `Zachowana podstawa: notatka · rewizja ${recordedNote.revision}`), U.el('p', recordedNote.body, 'analysis-note-text')); entry.append(noteCopy);}
            if (recordedMaterial) entry.append(el('p', `Zachowana podstawa: ${recordedMaterial.title} · SHA-256 ${recordedMaterial.sha256}`));
            history.append(entry);
          }
          history.dataset.loaded = 'true';
        } catch (error) {notify(`Nie udało się odczytać historii relacji: ${error.message}`, true);}
      });
      const remove = U.button('Usuń powiązanie', () => ask('Usunąć to powiązanie analityczne? W historii zmian pozostanie zapis jego usunięcia.', () => mutate(async id => {
        await request(`${base}/${id}/relations/${relation.id}?revision=${relation.revision}`, null, {method:'DELETE'});
        if (draft().id === relation.id) drafts.delete(id); workspace()?.refreshGraph?.();
      }, 'Usunięto powiązanie analityczne; zapis historii pozostaje w teczce.')));
      if (!relation.deleted) row.append(edit, remove); row.append(history); list.append(row);
    }
    if (!rows.length) list.append(el('p', 'Brak ręcznych powiązań. Obiekty do wyboru pochodzą z przypięć i bieżącego grafu.'));
  }
  function update() {
    const context = getContext(), id = context.selectedId || null;
    if (id !== owner) {
      ++relationRun; ++configRun; owner = id; ownerRevision = null; rows = []; loading = configLoading = false; objectKey = seedKey = '';
      list.replaceChildren(); workspace()?.setGraphDossier?.(id);
      if (id && context.dossier && !configurations.has(id)) configMeta();
    }
    graphBox.hidden = editor.hidden = !context.dossier;
    if (!context.dossier) return;
    if (!configurations.has(id) && !configLoading && ownerRevision === null) configMeta();
    if (context.dossier.revision !== ownerRevision) {ownerRevision = context.dossier.revision; loadRelations(true);}
    const key = JSON.stringify([id, values().map(item => [item.ref,item.label]), context.dossier.notes?.map(item => [item.id,item.revision]), context.dossier.materials?.map(item => item.id)]);
    if (objectKey !== key) {objectKey = key; paintForm();}
    paintSeeds(); controls();
  }
  return {update};
};
