'use strict';
/* Dossiers keep user drafts separate from refreshing catalog state and immutable evidence. */
(function (root) {
  const kinds = {object: 'Karta obiektu', timeline: 'Historia obiektu', comparison: 'Porównanie', graph: 'Graf powiązań', event: 'Zdarzenie reguły'};
  const states = {red: 'Alarm czerwony', yellow: 'Alarm żółty', none: 'Bez alarmu', unknown: 'Brak obserwacji'};
  function capturePayload(context, kind, title = '') {
    const state = context.state, ref = state.selectedRef;
    const payload = {kind, query: structuredClone(state.query), as_of: state.asOf,
      data_revision: state.dataRevision, display_timezone: state.displayTimezone || 'Europe/Warsaw',
      cursor_at: state.cursorAt || null, title: title.trim() || null};
    delete payload.query.cursor; delete payload.query.query_revision;
    if (kind === 'comparison') {
      payload.moving_refs = [...state.comparedRefs]; payload.region_refs = [...(state.comparedRegionRefs || [])];
    } else {
      payload.ref = ref; payload.sensor_id = state.selectedSensor || null;
      payload.metric = state.selectedMetric || (ref?.startsWith('hydro_station:') ? 'water_level' : null);
      payload.version_id = state.selectedVersion || null;
    }
    return payload;
  }
  function canCapture(context, kind) {
    if (!context?.ready) return false;
    const state = context.state, range = state.query.time.mode === 'range';
    if (kind === 'comparison') return range && context.comparisonReady && Boolean(state.comparedRefs.length || state.comparedRegionRefs?.length);
    return Boolean(context.detailReady && context.inScope !== false && state.selectedRef && (kind !== 'timeline' || range));
  }
  root.WiciWorkspaceDossiers = function (host, {request, getContext, openObject, status}) {
    const U = root.WiciWorkspaceUI, base = '/workspace/dossiers';
    const make = (tag, id, text, cls) => {const node = U.el(tag, text, cls); if (id) node.id = id; return node;};
    const button = (id, text, fn) => {const node = U.button(text, fn); if (id) node.id = id; return node;};
    const section = (parent, title) => {const node = U.el('section', null, 'analysis-dossier-section'); node.append(U.el('h3', title)); parent.append(node); return node;};
    const details = make('details', 'analysis-dossiers', null, 'analysis-dossiers'), summary = U.el('summary', 'Teczki analiz');
    const toolbar = U.el('div', null, 'analysis-dossier-toolbar'), select = make('select', 'analysis-dossier-select'); select.setAttribute('aria-label', 'Teczka analizy');
    const open = button('analysis-dossier-open', 'Otwórz teczkę', () => show()), create = button('analysis-dossier-new', 'Nowa teczka', () => choose(null, true));
    const toolbarStatus = make('p', 'analysis-dossier-toolbar-status', '', 'muted'); toolbarStatus.setAttribute('role', 'status');
    toolbar.append(select, open, create); details.append(summary, toolbar, toolbarStatus); host.append(details);
    const dialog = make('dialog', 'analysis-dossier-dialog'), heading = U.el('div', null, 'analysis-dossier-heading');
    const title = make('h2', 'analysis-dossier-heading', 'Teczka analizy'); title.tabIndex = -1; dialog.setAttribute('aria-labelledby', title.id);
    const close = button('analysis-dossier-close', 'Zamknij ×', () => dialog.close()); heading.append(title, close);
    const message = make('p', 'analysis-dossier-status', '', 'analysis-dossier-status'); message.setAttribute('role', 'status');
    const confirm = make('div', 'analysis-dossier-confirm', null, 'analysis-dossier-confirm'); confirm.hidden = true;
    const manager = make('div', 'analysis-dossier-manager'), viewer = make('div', 'analysis-material-viewer'); viewer.hidden = true;
    dialog.append(heading, message, confirm, manager, viewer); document.body.append(dialog);
    const intro = U.el('p', 'Teczka łączy własne notatki, odnośniki do obiektów i zapisane kopie danych. Przypięcie nie włącza obserwowania ani rejestracji.', 'muted');
    const form = section(manager, 'Nazwa i cel analizy'), name = make('input', 'analysis-dossier-name'), description = make('textarea', 'analysis-dossier-description');
    name.type = 'text'; name.maxLength = 120; description.maxLength = 5000; description.rows = 3;
    const save = button('analysis-dossier-save', 'Utwórz teczkę', saveDossier), reload = button('analysis-dossier-reload', 'Wczytaj aktualną teczkę', () => loadSelected()), remove = button('analysis-dossier-delete', 'Usuń teczkę', () => ask('Usunąć teczkę wraz z notatkami, przypięciami i zapisanymi materiałami? Tego nie można cofnąć.', () => mutate(async id => {
      await request(`${base}/${id}?revision=${selected.revision}`, null, {method: 'DELETE'}); drafts.delete(id); selectedId = null; selected = null;
    }, 'Teczka została usunięta.')));
    const discard = button('analysis-dossier-description-discard', 'Odrzuć zmiany opisu', () => ask('Odrzucić niezapisane zmiany nazwy i opisu? Zostanie wczytana ostatnia odczytana wersja teczki.', () => {
      const draft = getDraft(); Object.assign(draft, {name: selected?.name || '', description: selected?.description || '', baseName: selected?.name || '', baseDescription: selected?.description || '', revision: selected?.revision || null, dirty: false}); render();
    }));
    const metadataConflict = make('p', 'analysis-dossier-description-conflict', '', 'notice'); metadataConflict.hidden = true;
    const formActions = U.el('div', null, 'analysis-dossier-actions'); formActions.append(save, reload, discard, remove);
    form.append(intro, U.field('Nazwa teczki', name), U.field('Opis / pytanie analityczne', description), metadataConflict, formActions);
    const content = make('div', 'analysis-dossier-content'); manager.append(content);
    const pinsSection = section(content, 'Przypięte obiekty'), selection = make('p', 'analysis-dossier-selection', '', 'muted');
    const pin = button('analysis-dossier-pin-selected', 'Przypnij wybrany obiekt', pinSelected), pins = make('div', 'analysis-dossier-pins');
    pinsSection.append(selection, pin, pins);
    const notesSection = section(content, 'Notatki analityka'), notes = make('div', 'analysis-dossier-notes'), noteBody = make('textarea', 'analysis-dossier-note-body');
    noteBody.maxLength = 20000; noteBody.rows = 4;
    const noteSave = button('analysis-dossier-note-save', 'Dodaj notatkę', saveNote), noteCancel = button('analysis-dossier-note-cancel', 'Odrzuć szkic', () => ask('Odrzucić niezapisany szkic notatki w tym oknie?', () => {getDraft().note = {body: '', id: null, revision: null}; render();}));
    const noteActions = U.el('div', null, 'analysis-dossier-actions'); noteActions.append(noteSave, noteCancel);
    notesSection.append(U.el('p', 'Notatki są własną interpretacją, oddzieloną od materiału źródłowego. Szkice pozostają w tym oknie do zapisania lub odrzucenia.', 'muted'), notes, U.field('Treść notatki', noteBody), noteActions);
    const materialsSection = section(content, 'Zapisany materiał'), materialTitle = make('input', 'analysis-material-title'); materialTitle.type = 'text'; materialTitle.maxLength = 160;
    const captureActions = U.el('div', null, 'analysis-dossier-actions'), captureButtons = new Map();
    for (const [kind, label] of [['object', 'Zapisz kartę obiektu'], ['timeline', 'Zapisz historię z przedziału'], ['comparison', 'Zapisz porównanie z przedziału']]) {
      const control = button(`analysis-capture-${kind}`, label, () => capture(kind)); captureButtons.set(kind, control); captureActions.append(control);
    }
    const captureHint = make('p', 'analysis-dossier-capture-hint', '', 'muted'), materials = make('div', 'analysis-dossier-materials');
    materialsSection.append(U.el('p', 'Kopia obejmuje lokalnie zapisane dane, źródła i kontekst czasu. Pozostaje dostępna po wygaśnięciu historii. Nie pobiera nowych danych. Do historii i porównania wybierz przedział na osi czasu.', 'muted'), U.field('Tytuł materiału (opcjonalnie)', materialTitle), captureActions, captureHint, materials);
    let items = [], selectedId = null, selected = null, busy = false, loading = false, listLoading = false, listRun = 0, detailRun = 0, materialRun = 0, returnFocus = null;
    const drafts = new Map(); let relationsView = null, materialGraph = null;
    function clearMaterialGraph() {materialGraph?.destroy?.(); materialGraph = null;}
    function getDraft() {
      const key = selectedId || '_new';
      if (!drafts.has(key)) drafts.set(key, {name: selected?.name || '', description: selected?.description || '', baseName: selected?.name || '', baseDescription: selected?.description || '', revision: selected?.revision || null, dirty: false, note: {body: '', id: null, revision: null}, materialTitle: ''});
      return drafts.get(key);
    }
    function notify(text, error = false) {message.textContent = text; message.dataset.error = String(error); toolbarStatus.textContent = text; status?.(text);}
    function show() {
      ++materialRun;
      manager.hidden = false; viewer.hidden = true; title.textContent = selected?.name || 'Nowa teczka analizy';
      returnFocus = document.activeElement; if (!dialog.open) dialog.showModal(); title.focus(); render();
      if (selectedId && !selected && !loading) loadSelected();
    }
    dialog.addEventListener('close', () => {++materialRun; clearMaterialGraph(); confirm.hidden = true; if (returnFocus?.isConnected) returnFocus.focus();});
    dialog.addEventListener('keydown', event => {if (event.key === 'Escape') event.stopPropagation();});
    function ask(text, action) {
      ++materialRun;
      const origin = document.activeElement; confirm.replaceChildren(U.el('p', text)); confirm.hidden = false;
      const yes = button(null, 'Usuń trwale', () => {confirm.hidden = true; action();}), no = button(null, 'Anuluj', () => {confirm.hidden = true; origin?.focus?.();});
      if (text.startsWith('Odrzucić')) yes.textContent = 'Odrzuć szkic';
      confirm.append(yes, no); no.focus();
    }
    function choose(id, openDialog = false) {
      if (busy) return; ++detailRun; ++materialRun; clearMaterialGraph(); selectedId = id || null; selected = null; loading = false; confirm.hidden = true; manager.hidden = false; viewer.hidden = true;
      select.value = selectedId || ''; render(); if (openDialog) show(); if (selectedId) loadSelected();
    }
    select.addEventListener('change', () => choose(select.value));
    manager.addEventListener('input', () => {++materialRun;});
    name.addEventListener('input', () => {const draft = getDraft(); draft.name = name.value; draft.dirty = true; updateControls();});
    description.addEventListener('input', () => {const draft = getDraft(); draft.description = description.value; draft.dirty = true; updateControls();});
    noteBody.addEventListener('input', () => {getDraft().note.body = noteBody.value; updateControls();});
    materialTitle.addEventListener('input', () => {getDraft().materialTitle = materialTitle.value;});
    async function load() {
      const run = ++listRun; listLoading = true; updateControls();
      try {
        const result = await request(base); if (run !== listRun) return; items = result.items || [];
        select.replaceChildren(); const blank = U.el('option', 'Wybierz teczkę'); blank.value = ''; select.append(blank);
        for (const item of items) {const option = U.el('option', item.name); option.value = item.id; select.append(option);}
        select.value = selectedId || ''; summary.textContent = `Teczki analiz (${items.length})`;
      } catch (error) {if (run === listRun) notify(`Nie udało się wczytać teczek: ${error.message}`, true);}
      finally {if (run === listRun) {listLoading = false; updateControls();}}
    }
    async function loadSelected() {
      if (!selectedId) return;
      const id = selectedId, run = ++detailRun; loading = true; updateControls();
      try {
        const result = await request(`${base}/${id}`); if (run !== detailRun || id !== selectedId) return;
        selected = result; const draft = getDraft();
        if (draft.dirty && draft.baseName === result.name && draft.baseDescription === result.description) draft.revision = result.revision;
        if (!draft.dirty) Object.assign(draft, {name: selected.name, description: selected.description, baseName: selected.name, baseDescription: selected.description, revision: selected.revision});
        title.textContent = selected.name; render();
      } catch (error) {if (run === detailRun) notify(`Nie udało się wczytać teczki: ${error.message}`, true);}
      finally {if (run === detailRun) {loading = false; updateControls();}}
    }
    async function mutate(action, success, conflictMessage) {
      if (busy || loading) return;
      ++materialRun; busy = true; const id = selectedId; updateControls();
      try {await action(id); if (selectedId) await loadSelected(); await load(); notify(success); render();}
      catch (error) {notify(error.status === 409 ? conflictMessage || 'Zapisano nowszą wersję w innym oknie. Twój szkic zachowano. Wczytaj aktualną teczkę, porównaj treść i odrzuć szkic przed ponowną edycją aktualnej wersji.' : `Nie udało się zapisać: ${error.message}`, true);}
      finally {busy = false; updateControls();}
    }
    function saveDossier() {
      const draft = getDraft(); if (!draft.name.trim()) {notify('Podaj nazwę teczki.', true); name.focus(); return;}
      mutate(async id => {
        const body = {name: draft.name.trim(), description: draft.description.trim()}; if (id) body.revision = draft.revision;
        const result = await request(id ? `${base}/${id}` : base, body, {method: id ? 'PUT' : 'POST'});
        selectedId = result.id; selected = result; draft.dirty = false; draft.revision = result.revision; draft.baseName = result.name; draft.baseDescription = result.description; drafts.set(result.id, draft); if (!id) drafts.delete('_new');
      }, selectedId ? 'Opis teczki został zapisany.' : 'Utworzono teczkę analizy.');
    }
    function requireDossier() {if (selectedId && selected) return true; show(); notify('Utwórz lub wybierz teczkę, zanim dodasz materiał.'); name.focus(); return false;}
    function pinSelected() {
      if (!requireDossier()) return; const context = getContext(); if (!context?.detailReady) return;
      mutate(id => request(`${base}/${id}/pins`, {ref: context.state.selectedRef}, {method: 'POST'}), 'Obiekt przypięty do teczki. Przypięcie nie uruchamia rejestracji.');
    }
    function saveNote() {
      if (!selected) return; const draft = getDraft().note; if (!draft.body.trim()) return;
      mutate(async id => {
        await request(`${base}/${id}/notes${draft.id ? '/'+draft.id : ''}`, {body: draft.body.trim(), ...(draft.id ? {revision: draft.revision} : {})}, {method: draft.id ? 'PUT' : 'POST'});
        getDraft().note = {body: '', id: null, revision: null};
      }, 'Notatka została zapisana.');
    }
    async function capture(kind) {
      if (!requireDossier()) return; const context = getContext(); if (!canCapture(context, kind)) return;
      const payload = capturePayload(context, kind, getDraft().materialTitle); let result, run;
      await mutate(async id => {run = materialRun; result = await request(`${base}/${id}/materials`, payload, {method: 'POST'}); getDraft().materialTitle = '';}, 'Zapisano niezmienną kopię materiału.', 'Zestaw danych zmienił się lub wygasł. Zamknij teczkę, użyj „Odśwież zestaw” w Analizie i zapisz materiał ponownie. Tytuł zachowano.');
      if (result && dialog.open && run === materialRun) showMaterial(result);
    }
    function updateControls() {
      const context = getContext(), blocked = busy || loading;
      dialog.setAttribute('aria-busy', String(blocked));
      select.disabled = busy || listLoading; create.disabled = busy; open.disabled = !selectedId || busy;
      for (const node of [name, description, save]) node.disabled = blocked;
      reload.disabled = !selectedId || blocked; remove.disabled = !selected || blocked; discard.disabled = blocked || !getDraft().dirty;
      for (const node of [noteBody, materialTitle]) node.disabled = !selected || blocked;
      noteSave.disabled = !selected || blocked || !getDraft().note.body.trim(); noteCancel.disabled = blocked || !getDraft().note.body;
      pin.disabled = !selected || blocked || !context?.detailReady || selected.pins?.some(item => item.ref === context.state.selectedRef);
      for (const [kind, node] of captureButtons) node.disabled = !selected || blocked || !canCapture(context, kind);
      for (const node of manager.querySelectorAll('[data-mutation]')) node.disabled = blocked;
      selection.textContent = context?.object ? `Wybrany obiekt: ${context.object.label} · ${context.object.ref}` : 'Wybierz obiekt w katalogu lub na mapie.';
      captureHint.textContent = blocked ? 'Zapisywanie lub wczytywanie…' : context?.inScope === false ? 'Wybrany obiekt jest poza zakresem zestawu. Włącz jego typ i dopasuj filtry przed zapisaniem kopii.' : context?.ready ? `Czas odczytu zestawu: ${U.date(context.state.asOf)}${context.state.cursorAt ? ` · kursor ${U.date(context.state.cursorAt)}` : ''}. Karta zapisuje wybrany obiekt, historia cały wskazany przedział, porównanie wskazane trasy i regiony.` : 'Poczekaj na spójny zestaw danych lub użyj „Odśwież zestaw”.';
      const cardPin = document.getElementById('analysis-pin-object'), cardSave = document.getElementById('analysis-save-object');
      if (cardPin) cardPin.disabled = blocked || !context?.detailReady;
      if (cardSave) cardSave.disabled = blocked || !canCapture(context, 'object');
      relationsView?.update();
    }
    function rowButton(text, fn) {const control = button(null, text, fn); control.dataset.mutation = 'true'; return control;}
    function render() {
      const draft = getDraft(); name.value = draft.name; description.value = draft.description; noteBody.value = draft.note.body; materialTitle.value = draft.materialTitle;
      save.textContent = selectedId ? 'Zapisz opis' : 'Utwórz teczkę'; noteSave.textContent = draft.note.id ? 'Zapisz notatkę' : 'Dodaj notatkę';
      metadataConflict.hidden = !selected || !draft.dirty || (draft.baseName === selected.name && draft.baseDescription === selected.description);
      metadataConflict.textContent = metadataConflict.hidden ? '' : `Aktualny zapis: ${selected.name} — ${selected.description || 'bez opisu'}. Twój szkic pozostał w polach formularza.`;
      content.hidden = !selected; remove.hidden = !selectedId; reload.hidden = !selectedId;
      pins.replaceChildren(); notes.replaceChildren(); materials.replaceChildren();
      for (const item of selected?.pins || []) {
        const row = U.el('article', null, 'analysis-dossier-entry'); row.dataset.ref = item.ref;
        const link = button(null, item.label || item.ref, () => {dialog.close(); openObject(item.ref);}); link.disabled = !item.available;
        row.append(link, U.el('small', `${U.typeNames[item.type] || item.type} · ${item.ref} · ${item.available ? 'Otwiera aktualną kartę' : 'Obiekt nie jest już dostępny w katalogu'}`));
        row.append(rowButton('Odepnij', () => mutate(id => request(`${base}/${id}/pins/${encodeURIComponent(item.ref)}`, null, {method: 'DELETE'}), 'Odpięto obiekt. Zapisane materiały pozostają w teczce.'))); pins.append(row);
      }
      if (!selected?.pins?.length) pins.append(U.el('p', 'Brak przypiętych obiektów.', 'muted'));
      for (const note of selected?.notes || []) {
        const row = U.el('article', null, 'analysis-dossier-entry'); row.dataset.noteId = note.id;
        row.append(U.el('p', note.body, 'analysis-note-text'), U.el('small', `Zmieniono ${U.date(note.updated_at)} · wersja ${note.revision}`));
        row.append(rowButton('Edytuj', () => {
          const edit = () => {++materialRun; getDraft().note = {id: note.id, body: note.body, revision: note.revision}; render(); noteBody.focus();};
          if (getDraft().note.body) ask('Odrzucić niezapisany szkic i otworzyć tę notatkę?', edit); else edit();
        }), rowButton('Usuń', () => ask('Usunąć tę notatkę?', () => mutate(async id => {await request(`${base}/${id}/notes/${note.id}?revision=${note.revision}`, null, {method: 'DELETE'}); if (getDraft().note.id === note.id) getDraft().note = {body: '', id: null, revision: null};}, 'Notatka została usunięta.')))); notes.append(row);
      }
      if (!selected?.notes?.length) notes.append(U.el('p', 'Brak zapisanych notatek.', 'muted'));
      for (const material of selected?.materials || []) {
        const row = U.el('article', null, 'analysis-dossier-entry'); row.dataset.materialId = material.id;
        row.append(U.el('strong', material.title), U.el('small', `${kinds[material.kind] || material.kind} · zapisano ${U.date(material.captured_at)} · ${(material.byte_size / 1024).toFixed(1)} KB`));
        row.append(rowButton('Otwórz zapis', () => openMaterial(material.id)), rowButton('Usuń materiał', () => ask('Usunąć zapisaną kopię materiału? Nie będzie można jej odzyskać po wygaśnięciu historii źródłowej.', () => mutate(id => request(`${base}/${id}/materials/${material.id}`, null, {method: 'DELETE'}), 'Usunięto zapisaną kopię materiału.')))); materials.append(row);
      }
      if (!selected?.materials?.length) materials.append(U.el('p', 'Brak zapisanych materiałów.', 'muted')); updateControls();
    }
    async function openMaterial(id) {
      const owner = selectedId, run = ++materialRun;
      try {const result = await request(`${base}/${owner}/materials/${id}`); if (dialog.open && owner === selectedId && run === materialRun) showMaterial(result);}
      catch (error) {if (dialog.open && run === materialRun) notify(`Nie udało się otworzyć materiału: ${error.message}`, true);}
    }
    function showMaterial(material) {
      clearMaterialGraph(); manager.hidden = true; viewer.hidden = false; confirm.hidden = true; viewer.replaceChildren(); title.textContent = material.title;
      viewer.append(button('analysis-material-back', '← Wróć do teczki', () => {++materialRun; clearMaterialGraph(); viewer.hidden = true; manager.hidden = false; title.textContent = selected?.name || 'Teczka analizy'; title.focus();}));
      materialGraph = renderMaterial(viewer, material, U); title.focus(); dialog.scrollTop = 0;
    }
    relationsView = root.WiciDossierRelations?.(content, {request, mutate, notify, ask, materialTitle, showMaterial,
      getContext: () => ({...getContext(), selectedId, dossier:selected, busy:busy || loading}), close: () => dialog.close(),
      getNavigationToken: () => materialRun, isNavigationCurrent: token => dialog.open && token === materialRun,
      clearMaterialTitle: () => {getDraft().materialTitle = ''; materialTitle.value = '';}});
    render();
    return {load, update: updateControls, open: show, pin: pinSelected, capture, close: () => {if (dialog.open) dialog.close();}};
  };
  function renderMaterial(host, material, U) {
    const snapshot = material.snapshot || {}, context = snapshot.context || {}, zone = context.display_timezone || 'Europe/Warsaw';
    const stamp = value => {if (!value) return 'Brak czasu'; if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return `${value} · sama data`; const parsed = new Date(value); if (!Number.isFinite(parsed.getTime())) return String(value); return `${new Intl.DateTimeFormat('pl-PL', {timeZone: zone, dateStyle: 'short', timeStyle: 'medium'}).format(parsed)} (${value})`;};
    const format = value => value == null ? 'Nie podano' : typeof value === 'boolean' ? value ? 'Tak' : 'Nie' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    const section = (title) => {const node = U.el('section', null, 'analysis-dossier-section'); node.append(U.el('h3', title)); host.append(node); return node;};
    const facts = (parent, entries) => {const dl = U.el('dl', null, 'analysis-material-facts'); for (const [key, value] of entries) dl.append(U.el('dt', key), U.el('dd', format(value))); parent.append(dl);};
    host.append(U.el('p', 'Zapisana kopia · treść nie odświeża się ze źródła. Notatki analityka są przechowywane osobno.', 'notice'));
    const about = section('Pochodzenie i kontekst zapisu'), range = context.query?.time?.filter_range;
    if (snapshot.event) facts(about, [['Rodzaj', 'Zdarzenie reguły'], ['Zapisano', stamp(material.captured_at || snapshot.captured_at)], ['Strefa wyświetlania', zone], ['Czas obserwacji', stamp(snapshot.event.observed_at)], ['Wykrycie przez WICI', stamp(snapshot.event.detected_at)], ['Reguła i rewizja', `${snapshot.event.rule_name || snapshot.event.rule_id} · ${snapshot.event.rule_revision}`]]);
    else facts(about, [['Rodzaj', kinds[material.kind] || material.kind], ['Zapisano', stamp(material.captured_at || snapshot.captured_at)], ['Strefa wyświetlania', zone], ['Zestaw na', stamp(context.as_of)], ['Przedział [od, do)', range ? `${stamp(range.from || range.start)} — ${stamp(range.to || range.end)}` : 'Tryb bieżący'], ['Kursor', context.cursor_at ? stamp(context.cursor_at) : 'Nie wybrano'], ['Stanowisko / parametr', [context.sensor_id, context.metric].filter(Boolean).join(' · ') || 'Według wyboru karty'], ['Wersja dokumentu', context.version_id || 'Aktualna przy zapisie']]);
    function table(parent, rows, columns, caption) {
      parent.append(U.el('p', `${caption} · ${rows.length} rekordów`, 'muted')); if (!rows.length) {parent.append(U.el('p', 'Brak zapisanych rekordów w tym zakresie. Brak obserwacji nie oznacza braku zdarzeń.', 'muted')); return;}
      const wrap = U.el('div', null, 'analysis-material-table-scroll'), grid = U.el('table'), head = U.el('thead'), tr = U.el('tr'), body = U.el('tbody');
      for (const [label] of columns) {const th = U.el('th', label); th.scope = 'col'; tr.append(th);} head.append(tr); grid.append(head, body); wrap.append(grid); parent.append(wrap);
      let page = 0; const pages = Math.ceil(rows.length / 50), navigation = U.el('div', null, 'analysis-dossier-actions'), count = U.el('span');
      const previous = U.button('← Poprzednie rekordy', () => {page--; paint();}), next = U.button('Następne rekordy →', () => {page++; paint();}); navigation.append(previous, count, next); parent.append(navigation);
      function paint() {body.replaceChildren(); for (const row of rows.slice(page * 50, (page + 1) * 50)) {const tr = U.el('tr'); for (const [, extract] of columns) tr.append(U.el('td', format(extract(row)))); body.append(tr);} count.textContent = `Strona ${page + 1} z ${pages}`; previous.disabled = page === 0; next.disabled = page + 1 === pages;}
      paint();
    }
    const measurementColumns = [['Czas obserwacji', row => stamp(row.observed_at || row.at)], ['Parametr / stanowisko', row => [U.metricNames[row.metric] || row.metric || row.kind, row.sensor_id].filter(Boolean).join(' · ')], ['Wartość', row => row.name || U.value(row)], ['Rewizja / jakość', row => [row.revision, row.quality].filter(value => value != null).join(' · ')], ['Pobrano', row => stamp(row.fetched_at)]];
    const pointColumns = [['Czas raportu', row => stamp(row.position_at)], ['Szer. / dł. geogr.', row => `${format(row.latitude)}, ${format(row.longitude)}`], ['Prędkość km/h', row => row.speed_kmh], ['Wysokość m', row => row.altitude_m], ['Kierunek °', row => row.heading], ['Przerwa przed punktem', row => row.break_before]];
    const segmentColumns = [['Od', row => stamp(row.from || row.observed_at || row.at)], ['Do', row => stamp(row.to)], ['Stan', row => states[row.state] || row.state || row.level], ['Początek wg źródła', row => stamp(row.source_since)], ['Powód / epizod', row => [row.reason, row.episode_ref].filter(Boolean).join(' · ')]];
    const ukraineStats = (parent, stats) => {if (stats) facts(parent, [['Epizody', stats.episode_count], ['Zaobserwowany alarm (s)', stats.alarm_seconds], ['Pokrycie', Number.isFinite(stats.coverage_ratio) ? `${(stats.coverage_ratio * 100).toFixed(1)}%` : 'Brak danych'], ['Nieznany stan (s)', stats.unknown_seconds]]);};
    let graphView = null;
    if (snapshot.event) {
      const event = snapshot.event, eventSection = section('Zachowane zdarzenie reguły'), evidence = event.evidence || {};
      eventSection.append(U.el('p', event.description || 'Zdarzenie reguły'));
      facts(eventSection, [['Reguła i rewizja', `${event.rule_name || event.rule_id} · ${event.rule_revision}`], ['Obiekt', event.object_ref], ['Obserwacja', stamp(event.observed_at)], ['Wykrycie przez WICI', stamp(event.detected_at)], ['Stan obsługi przy zapisie', ({new:'Nowe',accepted:'Przyjęte',closed:'Zamknięte'})[event.status] || event.status], ['Stan warunku przy zapisie', ({met:'Spełniony',unmet:'Niespełniony',unknown:'Nieznany'})[event.condition_state] || event.condition_state]]);
      if (evidence.area) facts(eventSection, [['Własny obszar', evidence.area.name || evidence.area.id], ['Rewizja geometrii', evidence.area.revision]]);
      eventSection.append(U.el('p', evidence.notice || snapshot.notice || 'Podstawa z chwili wykrycia; kopia nie odpytuje źródeł.', 'muted'));
      const basis = U.el('details'); basis.append(U.el('summary', 'Reguła, obszar i dane stanowiące podstawę'), U.el('pre', JSON.stringify(evidence, null, 2))); eventSection.append(basis);
      const comments = section('Komentarze i obsługa zachowane w kopii'); for (const entry of event.comments || []) comments.append(U.el('p', entry.body, 'analysis-note-text'), U.el('small', stamp(entry.at || entry.created_at)));
      const handlingNames={new:'Nowe',accepted:'Przyjęte',closed:'Zamknięte'};
      const handlingTransition=row=>[row.payload?.from,row.payload?.status||row.status].filter(Boolean).map(value=>handlingNames[value]||value).join(' → ');
      table(comments, event.history || [], [['Czas', row => stamp(row.at || row.created_at)], ['Działanie', row => ({create:'Utworzenie',status:'Zmiana stanu',comment:'Komentarz'})[row.action]||row.action], ['Stan', handlingTransition]], 'Historia obsługi');
    }
    if (snapshot.graph) {
      const graphSection = section('Zapisany graf powiązań');
      graphSection.append(U.el('p', snapshot.graph.partial ? 'Zapisany fragment grafu. Niewczytane powiązania nie są częścią tej kopii.' : 'Kopia widocznego grafu z chwili zapisu; pochodzenie relacji zachowano.', 'muted'));
      graphView = root.WiciWorkspaceGraph?.createReadOnly?.(graphSection, snapshot.graph);
      if (!graphView) graphSection.append(U.el('p', 'Graf można odczytać w pełnym zapisie JSON poniżej.'));
    }
    for (const detail of snapshot.objects || []) {
      const object = detail.object || detail, card = section(object.label || object.ref || 'Obiekt');
      facts(card, [['Identyfikator', object.ref], ['Typ / źródło', `${U.typeNames[object.type] || object.type} · ${object.source_id || ''}`], ['Aktualność przy zapisie', U.statusNames[object.freshness] || object.freshness || object.availability], ['Metadane / geometria', detail.geometry_context || 'Według katalogu w chwili zapisu']]);
      if (detail.communication) {const content = detail.selected_version || detail.communication; card.append(U.el('h4', content.title || 'Treść komunikatu'), U.el('p', content.text || 'Brak tekstu', 'analysis-note-text')); facts(card, [['Publikacja źródłowa', stamp(content.source_published_at || content.source_published_date || content.source_date)], ['Aktualizacja źródłowa', stamp(content.source_updated_at)]]);}
      if (object.type?.endsWith('_station')) {
        const noSensor = object.type === 'air_quality_station' && !context.sensor_id;
        const sample = noSensor ? null : detail.selected_measurement || object.measurement;
        facts(card, noSensor ? [['Wybrany pomiar', 'Nie wybrano stanowiska']] : [['Wybrany pomiar', U.value(sample)], ['Czas obserwacji', stamp(sample?.observed_at)]]);
        table(card, detail.measurements || [], measurementColumns, 'Parametry zachowane w karcie');
        if (object.type === 'air_quality_station') {
          const index = object.official_index || detail.official_index;
          facts(card, [['Oficjalny indeks ogólny GIOŚ', index?.name || (index?.value ?? 'Brak zapisanego indeksu')], ['Czas obserwacji indeksu', stamp(index?.observed_at)], ['Czas obliczenia indeksu', stamp(index?.calculated_at)]]);
          card.append(U.el('p', 'Oficjalny indeks jest odrębny od stężenia wybranej substancji.', 'muted'));
        }
      }
      if (['aircraft', 'ship'].includes(object.type)) {const meta = object.metadata || {}; facts(card, object.type === 'aircraft' ? [['ICAO', object.native_id || object.ref?.split(':').at(-1)], ['Znak wywoławczy', meta.callsign], ['Rejestracja', meta.registration], ['Typ samolotu według źródła', meta.type_code], ['Klasyfikacja wojskowa według źródła', meta.military == null ? 'Nie podano' : meta.military ? 'Wojskowy według źródła' : 'Brak oznaczenia wojskowego'], ['Dostawca', meta.source_name]] : [['MMSI', object.native_id || object.ref?.split(':').at(-1)], ['IMO', meta.imo], ['Nazwa według źródła', meta.name], ['Typ jednostki AIS', meta.type_code], ['Deklarowany cel', meta.destination], ['Dostawca', meta.source_name]]); const position = object.position || object.last_known_position; if (!object.position && context.query?.time?.mode === 'range') card.append(U.el('p', 'Brak zapisanej pozycji przy wybranym kursorze. Ostatni raport z katalogu poniżej nie odtwarza tej chwili.', 'notice')); if (position) table(card, [position], pointColumns, object.position ? context.query?.time?.mode === 'range' ? 'Pozycja odtworzona dla wybranego czasu' : 'Pozycja przy zapisie' : 'Ostatnia znana pozycja z katalogu · nie potwierdza lokalizacji przy kursorze ani lokalizacji bieżącej');}
      if (detail.ukraine) {ukraineStats(card, detail.ukraine.stats); table(card, detail.ukraine.segments || [], segmentColumns, 'Zapisany stan regionu');}
    }
    if (snapshot.timeline) {
      const history = section('Pełny zapis wybranej historii'), rows = snapshot.timeline.items || [], type = snapshot.objects?.[0]?.object?.type;
      const columns = ['aircraft', 'ship'].includes(type) ? pointColumns : ['ua_region', 'civil_alert'].includes(type) ? segmentColumns : type === 'communication' ? [['Czas', row => stamp(row.date_precision === 'day' ? row.source_date : row.at)], ['Zdarzenie', row => row.kind], ['Wersja', row => row.version_id || row.version_number], ['Tytuł', row => row.title]] : measurementColumns;
      table(history, rows, columns, 'Zapisane rekordy'); if (snapshot.timeline.official_indices?.length) table(history, snapshot.timeline.official_indices, measurementColumns, 'Oficjalne indeksy GIOŚ');
      history.append(U.el('p', snapshot.timeline.note || 'Wyłącznie zachowane obserwacje; braki nie są uzupełniane.', 'muted'));
    }
    for (const series of snapshot.moving?.series || []) {const motion = section(`Trasa · ${series.label || series.ref}`); motion.append(U.el('p', 'Wszystkie zapisane raporty z przedziału. Przerwy pozostają przerwami. Klasyfikacja pochodzi z katalogu w chwili zapisu kopii.', 'muted')); table(motion, series.points || [], pointColumns, series.ref);}
    for (const series of snapshot.ukraine?.series || []) {const region = section(`Alarmy · ${series.label || series.ref}`); region.append(U.el('p', 'Geometria odpowiada katalogowi przy zapisie. Statystyki opisują zaobserwowany czas; luki nie oznaczają braku alarmu.', 'muted')); ukraineStats(region, series.stats); table(region, series.segments || [], segmentColumns, series.ref);}
    const urls = new Set(); function collect(value, key = '') {if (!value || typeof value !== 'object') return; for (const [name, item] of Object.entries(value)) {if (typeof item === 'string' && /url|href/i.test(name)) urls.add(item); else if (item && typeof item === 'object') collect(item, key);}}
    collect(snapshot); const sources = section('Źródła zachowane w materiale'); let count = 0;
    for (const url of urls) {const link = U.safeLink(url, url); if (link) {const line = U.el('p'); line.append(link); sources.append(line); count++;}}
    if (!count) sources.append(U.el('p', 'Źródło jest oznaczone w karcie; zapis nie zawiera osobnego adresu materiału.', 'muted'));
    const raw = U.el('details'), summary = U.el('summary', 'Pełny zapis danych i metadanych (JSON)'), pre = U.el('pre', JSON.stringify(snapshot, null, 2)); raw.append(summary, U.el('p', `SHA-256 zapisanego materiału: ${material.sha256 || 'Nie podano'}`), pre); host.append(raw);
    return graphView;
  }
  root.WiciDossierHelpers = {capturePayload, canCapture, renderMaterial};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.WiciDossierHelpers;
})(typeof window !== 'undefined' ? window : globalThis);
