"""Durable analyst work and immutable local copies, isolated from source retention.

A capture contains server-read records, never caller-provided evidence. The shared
repository lock freezes all source writers across context validation, pagination
and serialization. Notes remain separate from source material.
"""
import hashlib
import json
import uuid

from wici.dossier_models import DossierInput, DossierNote, DossierPin, MaterialCapture
from wici.workspace_models import MovingReplay
from wici.workspace_repository import encode, iso
from wici.workspace_service import QueryChanged

MAX_DOSSIERS = 100
MAX_PINS = 500
MAX_NOTES = 500
MAX_MATERIALS = 100
MAX_MATERIAL_BYTES = 5 * 1024 * 1024
MAX_TIMELINE_ROWS = 20000


class WorkspaceDossiers:
    def __init__(self, workspace):
        self.workspace = workspace
        self.repo, self.db = workspace.repo, workspace.db

    def _row(self, dossier_id):
        row = self.db.execute('SELECT * FROM workspace_dossiers WHERE id=?', (dossier_id,)).fetchone()
        if row is None:
            raise KeyError(dossier_id)
        return dict(row)

    def _touch(self, dossier_id):
        self.db.execute('UPDATE workspace_dossiers SET revision=revision+1,updated_at=? WHERE id=?',
                        (iso(self.repo.clock()), dossier_id))

    def _limit(self, table, limit, dossier_id=None):
        clause = ' WHERE dossier_id=?' if dossier_id else ''
        count = self.db.execute(f'SELECT count(*) FROM {table}{clause}',
                                (dossier_id,) if dossier_id else ()).fetchone()[0]
        if count >= limit:
            raise ValueError(f'Osiągnięto limit {limit} elementów; usuń niepotrzebne elementy')

    def _summary(self, row):
        result = dict(row)
        for name in ('pin', 'note', 'material'):
            result[name+'_count'] = self.db.execute(
                f'SELECT count(*) FROM workspace_dossier_{name}s WHERE dossier_id=?', (result['id'],)
            ).fetchone()[0]
        return result

    def list(self):
        with self.repo.lock:
            return {'items': [self._summary(row) for row in self.db.execute(
                'SELECT * FROM workspace_dossiers ORDER BY updated_at DESC,id')]}

    def detail(self, dossier_id):
        with self.repo.lock:
            result = self._summary(self._row(dossier_id))
            result['pins'] = [dict(row, available=bool(row['available'])) for row in self.db.execute('''
                SELECT p.ref,p.label,p.type,p.source_id,p.pinned_at,
                    EXISTS(SELECT 1 FROM catalog_objects o WHERE o.ref=p.ref) available
                FROM workspace_dossier_pins p WHERE p.dossier_id=? ORDER BY p.pinned_at,p.ref''', (dossier_id,))]
            result['notes'] = [dict(row) for row in self.db.execute('''SELECT * FROM workspace_dossier_notes
                WHERE dossier_id=? ORDER BY created_at,id''', (dossier_id,))]
            result['materials'] = [dict(row) for row in self.db.execute('''
                SELECT id,dossier_id,title,kind,object_ref,captured_at,sha256,byte_size
                FROM workspace_dossier_materials WHERE dossier_id=? ORDER BY captured_at DESC,id''', (dossier_id,))]
            return result

    def save(self, raw, dossier_id=None):
        value = DossierInput.model_validate(raw)
        now = iso(self.repo.clock())
        with self.repo.lock, self.db:
            if dossier_id:
                previous = self._row(dossier_id)
                if value.revision != previous['revision']:
                    raise QueryChanged('Teczka została zmieniona; odczytaj jej bieżącą wersję')
                self.db.execute('''UPDATE workspace_dossiers SET name=?,description=?,revision=revision+1,
                    updated_at=? WHERE id=?''', (value.name, value.description, now, dossier_id))
            else:
                self._limit('workspace_dossiers', MAX_DOSSIERS)
                dossier_id = str(uuid.uuid4())
                self.db.execute('INSERT INTO workspace_dossiers VALUES(?,?,?,?,?,?)',
                                (dossier_id, value.name, value.description, 1, now, now))
            return self.detail(dossier_id)

    def delete(self, dossier_id, revision):
        with self.repo.lock, self.db:
            previous = self._row(dossier_id)
            if revision != previous['revision']:
                raise QueryChanged('Teczka została zmieniona; odczytaj jej bieżącą wersję przed usunięciem')
            self.db.execute('DELETE FROM workspace_dossiers WHERE id=?', (dossier_id,))
            return {'deleted': True}

    def pin(self, dossier_id, raw):
        value = DossierPin.model_validate(raw)
        with self.repo.lock, self.db:
            self._row(dossier_id)
            existing = self.db.execute('SELECT * FROM workspace_dossier_pins WHERE dossier_id=? AND ref=?',
                                       (dossier_id, value.ref)).fetchone()
            if existing:
                return dict(existing, available=self.workspace.catalog.object(value.ref) is not None)
            obj = self.workspace.catalog.object(value.ref)
            if obj is None:
                raise KeyError(value.ref)
            self._limit('workspace_dossier_pins', MAX_PINS, dossier_id)
            now = iso(self.repo.clock())
            self.db.execute('INSERT INTO workspace_dossier_pins VALUES(?,?,?,?,?,?)',
                            (dossier_id, value.ref, obj['label'], obj['type'], obj['source_id'], now))
            self._touch(dossier_id)
            return {'ref': value.ref, 'label': obj['label'], 'type': obj['type'],
                    'source_id': obj['source_id'], 'pinned_at': now, 'available': True}

    def unpin(self, dossier_id, ref):
        with self.repo.lock, self.db:
            self._row(dossier_id)
            if not self.db.execute('DELETE FROM workspace_dossier_pins WHERE dossier_id=? AND ref=?',
                                   (dossier_id, ref)).rowcount:
                raise KeyError(ref)
            self._touch(dossier_id)
            return {'deleted': True}

    def save_note(self, dossier_id, raw, note_id=None):
        value = DossierNote.model_validate(raw)
        now = iso(self.repo.clock())
        with self.repo.lock, self.db:
            self._row(dossier_id)
            if note_id:
                previous = self.db.execute('SELECT * FROM workspace_dossier_notes WHERE dossier_id=? AND id=?',
                                           (dossier_id, note_id)).fetchone()
                if previous is None:
                    raise KeyError(note_id)
                if value.revision != previous['revision']:
                    raise QueryChanged('Notatka została zmieniona; odczytaj jej bieżącą wersję')
                self.db.execute('UPDATE workspace_dossier_notes SET body=?,revision=revision+1,updated_at=? WHERE id=?',
                                (value.body, now, note_id))
            else:
                self._limit('workspace_dossier_notes', MAX_NOTES, dossier_id)
                note_id = str(uuid.uuid4())
                self.db.execute('INSERT INTO workspace_dossier_notes VALUES(?,?,?,?,?,?)',
                                (note_id, dossier_id, value.body, 1, now, now))
            self._touch(dossier_id)
            return dict(self.db.execute('SELECT * FROM workspace_dossier_notes WHERE id=?', (note_id,)).fetchone())

    def delete_note(self, dossier_id, note_id, revision):
        with self.repo.lock, self.db:
            self._row(dossier_id)
            row = self.db.execute('SELECT revision FROM workspace_dossier_notes WHERE dossier_id=? AND id=?',
                                  (dossier_id, note_id)).fetchone()
            if row is None:
                raise KeyError(note_id)
            if row['revision'] != revision:
                raise QueryChanged('Notatka została zmieniona; odczytaj jej bieżącą wersję przed usunięciem')
            self.db.execute('DELETE FROM workspace_dossier_notes WHERE id=?', (note_id,))
            self._touch(dossier_id)
            return {'deleted': True}

    def _context(self, capture):
        expected = capture.data_revision
        if expected:
            as_of = iso(capture.as_of)
            _, old = self.workspace._context(expected, as_of)
            requested = capture.query.model_dump(mode='json', by_alias=True, exclude={'cursor', 'query_revision'})
            original = old[2].model_dump(mode='json', by_alias=True, exclude={'cursor', 'query_revision'})
            if requested != original:
                raise ValueError('Zapytanie materiału nie odpowiada wyświetlanej rewizji danych')
        else:
            result = self.workspace.query(capture.query)
            expected, as_of = result['data_revision'], result['as_of']
        return as_of, expected

    def _timeline(self, ref, capture, as_of, revision):
        interval = capture.query.time.filter_range
        kwargs = {'start': iso(interval.start), 'end': iso(interval.end), 'as_of': as_of,
                  'data_revision': revision, 'sensor_id': capture.sensor_id, 'metric': capture.metric}
        result = self.workspace.timeline(ref, **kwargs)
        if result['total'] + result['official_indices_total'] > MAX_TIMELINE_ROWS:
            raise ValueError(f'Historia przekracza {MAX_TIMELINE_ROWS} rekordów. Zawęź przedział; dane nie są pomijane.')
        # Measurements and official indices have independent pagination. Exhaust
        # each stream once; do not append the other stream again on later pages.
        cursor = result['next_cursor']
        while cursor is not None:
            page = self.workspace.timeline(ref, cursor=cursor, **kwargs)
            result['items'].extend(page['items'])
            cursor = page['next_cursor']
        cursor = result['official_indices_next_cursor']
        while cursor is not None:
            page = self.workspace.timeline(ref, index_cursor=cursor, **kwargs)
            result['official_indices'].extend(page['official_indices'])
            cursor = page['official_indices_next_cursor']
        result['next_cursor'] = result['official_indices_next_cursor'] = None
        if len(result['items']) != result['total'] or len(result['official_indices']) != result['official_indices_total']:
            raise ValueError('Nie udało się zapisać całej historii; odśwież dane')
        return result

    def capture(self, dossier_id, raw):
        value = MaterialCapture.model_validate(raw)
        with self.repo.lock, self.db:
            self._row(dossier_id)
            self._limit('workspace_dossier_materials', MAX_MATERIALS, dossier_id)
            if value.kind == 'graph':
                return self._capture_graph(dossier_id, value)
            as_of, revision = self._context(value)
            captured = iso(self.repo.clock())
            context = value.model_dump(mode='json', by_alias=True,
                exclude={'title', 'kind', 'graph', 'positions', 'hidden_refs', 'layout', 'node_type'})
            context.update(as_of=as_of, data_revision=revision)
            snapshot = {'schema_version': 1, 'captured_at': captured, 'context': context, 'objects': [],
                        'notice': 'Niezmienna kopia lokalnych danych odczytanych w chwili zapisu. '
                                  'Czas zapisu nie jest czasem obserwacji. Metadane i geometria katalogu są bieżące '
                                  'w chwili zapisu; braki danych nie oznaczają zera ani braku zagrożenia.'}
            refs = [value.ref] if value.kind != 'comparison' else value.moving_refs + value.region_refs
            for ref in refs:
                selected = value.kind != 'comparison'
                obj = self.workspace.detail(ref, as_of=as_of, data_revision=revision,
                    cursor_at=iso(value.cursor_at) if value.cursor_at else None,
                    sensor_id=value.sensor_id if selected else None, metric=value.metric if selected else None,
                    version_id=value.version_id if selected else None)
                if not obj['in_scope']:
                    raise ValueError('Obiekt nie należy do bieżącego wyniku. Włącz wszystkie wybrane typy, '
                                     'usuń wykluczające filtry i odśwież wynik przed zapisem materiału.')
                if selected and value.version_id is not None:
                    # The ordinary card history omits publisher fields. A durable
                    # selected version must keep its own date precision and fields,
                    # never inherit the current document's publication date.
                    row = self.db.execute('SELECT fields_json FROM document_versions WHERE id=? AND document_id=?',
                                          (value.version_id, obj['object']['document_id'])).fetchone()
                    fields = json.loads(row['fields_json'])
                    version = dict(obj['selected_version'])
                    obj['selected_version'] = version
                    version['fields'] = fields
                    version['source_published_date'] = fields.get('source_published_date')
                    version['date_precision'] = ('instant' if version.get('source_published_at')
                        or version.get('source_updated_at') else 'day' if version['source_published_date'] else 'unknown')
                snapshot['objects'].append(obj)
            if value.kind == 'timeline':
                snapshot['timeline'] = self._timeline(value.ref, value, as_of, revision)
            elif value.kind == 'comparison':
                interval = value.query.time.filter_range
                if value.moving_refs:
                    snapshot['moving'] = self.workspace.moving.replay(MovingReplay.model_validate(
                        {'refs': value.moving_refs, 'from': interval.start, 'to': interval.end}))
                if value.region_refs:
                    snapshot['ukraine'] = self.workspace.ukraine.replay(value.region_refs, interval.start, interval.end)
            payload = encode(snapshot)
            size = len(payload.encode('utf-8'))
            if size > MAX_MATERIAL_BYTES:
                raise ValueError('Materiał przekracza 5 MiB. Zawęź przedział lub wybór; dane nie są pomijane.')
            title = value.title or (snapshot['objects'][0]['object']['label'] if value.kind != 'comparison'
                                    else 'Porównanie obiektów')
            material_id = str(uuid.uuid4())
            self.db.execute('INSERT INTO workspace_dossier_materials VALUES(?,?,?,?,?,?,?,?,?)',
                            (material_id, dossier_id, title[:160], value.kind,
                             value.ref if value.kind != 'comparison' else None,
                             captured, hashlib.sha256(payload.encode('utf-8')).hexdigest(), size, payload))
            self._touch(dossier_id)
            return self.material(dossier_id, material_id)

    def _capture_graph(self, dossier_id, value):
        """Server rebuilds the selected fragment; client supplies layout only."""
        if value.graph.get('dossier_id') not in (None, dossier_id):
            raise ValueError('Graf musi należeć do tej teczki')
        graph = self.workspace.relations.query(value.graph)
        graph.update(positions=value.positions, hidden_refs=value.hidden_refs, layout=value.layout, node_type=value.node_type)
        captured = iso(self.repo.clock())
        snapshot = {'schema_version': 2, 'captured_at': captured, 'graph': graph,
            'context': {'query': {'time': graph['selector']['time']},
                'as_of': graph['as_of'], 'data_revision': graph['revision'],
                'cursor_at': graph['selector'].get('cursor_at'), 'display_timezone': value.display_timezone},
            'objects': [{'object': node} for node in graph['nodes']],
            'notice': 'Niezmienna kopia wybranego fragmentu grafu. Relacje źródłowe, wyliczone i analityczne '
                      'zachowują własne pochodzenie. Aktualne metadane nie odtwarzają dawnego katalogu.'}
        payload = encode(snapshot)
        size = len(payload.encode('utf-8'))
        if size > MAX_MATERIAL_BYTES:
            raise ValueError('Materiał przekracza 5 MiB. Ogranicz graf; dane nie są pomijane.')
        material_id = str(uuid.uuid4())
        self.db.execute('INSERT INTO workspace_dossier_materials VALUES(?,?,?,?,?,?,?,?,?)',
            (material_id, dossier_id, value.title or 'Graf powiązań', 'graph', None, captured,
             hashlib.sha256(payload.encode('utf-8')).hexdigest(), size, payload))
        self._touch(dossier_id)
        return self.material(dossier_id, material_id)

    def material(self, dossier_id, material_id):
        with self.repo.lock:
            self._row(dossier_id)
            row = self.db.execute('SELECT * FROM workspace_dossier_materials WHERE dossier_id=? AND id=?',
                                  (dossier_id, material_id)).fetchone()
            if row is None:
                raise KeyError(material_id)
            result = dict(row)
            result['snapshot'] = json.loads(result.pop('snapshot_json'))
            return result

    def delete_material(self, dossier_id, material_id):
        with self.repo.lock, self.db:
            self._row(dossier_id)
            if not self.db.execute('DELETE FROM workspace_dossier_materials WHERE dossier_id=? AND id=?',
                                   (dossier_id, material_id)).rowcount:
                raise KeyError(material_id)
            self._touch(dossier_id)
            return {'deleted': True}
