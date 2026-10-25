"""Durable condition detections, revision-checked handling and frozen evidence."""
import hashlib
import json
import uuid
from datetime import timedelta

from wici.event_models import EventCapture, EventComment, EventHandling
from wici.workspace_dossiers import MAX_MATERIAL_BYTES, MAX_MATERIALS
from wici.workspace_repository import encode, iso
from wici.workspace_service import QueryChanged, parse_time


class WorkspaceEvents:
    def __init__(self, workspace):
        self.workspace = workspace
        self.repo, self.db = workspace.repo, workspace.db

    def emit(self, rule, observation, condition_state, description, area=None):
        """Part of the monitor's transaction: NEVER commit its checkpoint early."""
        if condition_state not in ('met', 'unmet', 'unknown'):
            raise ValueError('Nieznany stan warunku')
        rule_id, revision = rule['id'], rule['revision']
        object_ref = observation.get('object_ref') or observation.get('ref') or ''
        if not object_ref:
            raise ValueError('Zdarzenie wymaga obiektu źródłowego')
        observed_at = observation.get('observed_at')
        observed_at = iso(parse_time(observed_at)) if observed_at else None
        if observed_at is None:
            raise ValueError('Zdarzenie wymaga czasu obserwacji')
        basis = observation.get('key', observation.get('id'))
        if basis is None:
            basis = hashlib.sha256(encode(observation).encode()).hexdigest()
        key = hashlib.sha256(encode([rule_id, revision, area.get('revision') if area else None,
                                   basis, observation.get('trigger'), condition_state]).encode()).hexdigest()
        existing = self.db.execute('SELECT id FROM workspace_events WHERE dedup_key=?', (key,)).fetchone()
        if existing:
            return self.detail(existing['id'])
        now = iso(self.repo.clock())
        evidence = {'rule': rule, 'area': area, 'observation': observation,
                    'notice': 'Wykrycie warunku na podstawie lokalnie zaobserwowanych danych. '
                              'Czas wykrycia nie jest czasem rozpoczęcia zjawiska. '
                              'Próg użytkownika jest niezależny od oficjalnego indeksu GIOŚ. '
                              'Przerwy i brak pomiarów oznaczają nieznany stan.'}
        payload = encode(evidence)
        if len(payload.encode()) > MAX_MATERIAL_BYTES:
            raise ValueError('Podstawa zdarzenia przekracza 5 MiB')
        event_id = str(uuid.uuid4())
        self.db.execute('''INSERT INTO workspace_events(id,dedup_key,rule_id,rule_revision,rule_name,
            object_ref,object_type,area_id,priority,condition_state,description,observed_at,detected_at,
            evidence_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (event_id, key, rule_id, revision, rule['name'], object_ref, object_ref.split(':')[0],
             area['id'] if area else None, rule['priority'], condition_state, description, observed_at,
             now, payload, now))
        self._audit(event_id, 1, 'create', {'status': 'new', 'condition_state': condition_state}, now)
        return self.detail(event_id)

    def _row(self, event_id):
        row = self.db.execute('SELECT * FROM workspace_events WHERE id=?', (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return row

    def _decode(self, row, evidence=False):
        result = dict(row)
        payload = result.pop('evidence_json')
        result.pop('dedup_key', None)
        if evidence:
            result['evidence'] = json.loads(payload)
        return result

    def list(self, *, rule_id=None, area_id=None, object_type=None, priority=None,
             start=None, end=None, status=None, condition_state=None, limit=100, offset=0):
        if status is not None and status not in ('new', 'accepted', 'closed'):
            raise ValueError('Nieznany stan obsługi')
        if condition_state is not None and condition_state not in ('met', 'unmet', 'unknown'):
            raise ValueError('Nieznany stan warunku')
        if priority is not None and priority not in ('low', 'normal', 'high'):
            raise ValueError('Nieznany priorytet')
        where, params = ['1=1'], []
        for key, val in (('rule_id', rule_id), ('area_id', area_id), ('object_type', object_type),
                         ('priority', priority), ('status', status), ('condition_state', condition_state)):
            if val is not None:
                where.append(key+'=?')
                params.append(val)
        lower, upper = parse_time(start), parse_time(end)
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError('Przedział czasu musi mieć dodatnią długość')
        for op, val in (('>=', lower), ('<', upper)):
            if val is not None:
                where.append('observed_at'+op+'?')
                params.append(iso(val))
        clause = ' AND '.join(where)
        with self.repo.lock:
            total = self.db.execute('SELECT count(*) FROM workspace_events WHERE '+clause, params).fetchone()[0]
            rows = self.db.execute('SELECT * FROM workspace_events WHERE '+clause+
                ' ORDER BY detected_at DESC,id LIMIT ? OFFSET ?', (*params, max(1, min(limit, 200)), max(0, offset)))
            return {'items': [self._decode(row) for row in rows], 'total': total}

    def detail(self, event_id):
        with self.repo.lock:
            result = self._decode(self._row(event_id), evidence=True)
            result['history'] = [dict(row, payload=json.loads(row['payload_json'])) for row in self.db.execute(
                'SELECT event_revision,action,payload_json,at FROM workspace_event_history WHERE event_id=? ORDER BY id',
                (event_id,))]
            for item in result['history']:
                item.pop('payload_json')
            result['comments'] = [dict(item['payload'], at=item['at'], revision=item['event_revision'])
                                  for item in result['history'] if item['action'] == 'comment']
            return result

    def _audit(self, event_id, revision, action, payload, at):
        self.db.execute('''INSERT INTO workspace_event_history(event_id,event_revision,action,payload_json,at)
            VALUES(?,?,?,?,?)''', (event_id, revision, action, encode(payload), at))

    def _check(self, event_id, revision):
        row = self._row(event_id)
        if row['revision'] != revision:
            raise QueryChanged('Zdarzenie zostało zmienione; odczytaj bieżącą wersję. Szkic nie został zapisany.')
        return row

    def handle(self, event_id, raw):
        value = EventHandling.model_validate(raw)
        with self.repo.lock, self.db:
            row = self._check(event_id, value.revision)
            if row['status'] == value.status:
                return self.detail(event_id)
            if (row['status'], value.status) not in (('new', 'accepted'), ('accepted', 'closed')):
                raise ValueError('Kolejność obsługi: Nowe → Przyjęte → Zamknięte')
            now = iso(self.repo.clock())
            self.db.execute('UPDATE workspace_events SET status=?,revision=revision+1,updated_at=? WHERE id=?',
                            (value.status, now, event_id))
            self._audit(event_id, value.revision+1, 'status', {'from': row['status'], 'status': value.status}, now)
            return self.detail(event_id)

    def comment(self, event_id, raw):
        value = EventComment.model_validate(raw)
        with self.repo.lock, self.db:
            self._check(event_id, value.revision)
            now = iso(self.repo.clock())
            self.db.execute('UPDATE workspace_events SET revision=revision+1,updated_at=? WHERE id=?', (now, event_id))
            self._audit(event_id, value.revision+1, 'comment', {'body': value.body}, now)
            return self.detail(event_id)

    def capture(self, event_id, raw):
        value = EventCapture.model_validate(raw)
        dossiers = self.workspace.dossiers
        with self.repo.lock, self.db:
            dossiers._row(value.dossier_id)
            dossiers._limit('workspace_dossier_materials', MAX_MATERIALS, value.dossier_id)
            event = self.detail(event_id)
            captured = iso(self.repo.clock())
            # Frozen evidence comes from the event, never today's source tables/rule.
            snapshot = {'schema_version': 3, 'captured_at': captured, 'event': event, 'objects': [],
                        'context': {'observed_at': event['observed_at'], 'detected_at': event['detected_at'],
                                    'rule_revision': event['rule_revision'], 'display_timezone': 'Europe/Warsaw'},
                        'notice': 'Niezmienna kopia zdarzenia wraz z pierwotną regułą, obszarem i podstawą. '
                                  'Historia obsługi i komentarze odpowiadają chwili zapisu.'}
            payload = encode(snapshot)
            size = len(payload.encode('utf-8'))
            if size > MAX_MATERIAL_BYTES:
                raise ValueError('Materiał przekracza 5 MiB')
            material_id = str(uuid.uuid4())
            self.db.execute('INSERT INTO workspace_dossier_materials VALUES(?,?,?,?,?,?,?,?,?)',
                (material_id, value.dossier_id, (value.title or event['description'])[:160], 'event',
                 event['object_ref'], captured, hashlib.sha256(payload.encode()).hexdigest(), size, payload))
            dossiers._touch(value.dossier_id)
            return dossiers.material(value.dossier_id, material_id)

    def prune(self):
        with self.repo.lock, self.db:
            before = iso(self.repo.clock()-timedelta(days=90))
            result = self.db.execute('DELETE FROM workspace_events WHERE detected_at<?', (before,))
            return result.rowcount
