"""Durable observation stream and explicit, idempotent local rule evaluation.

Source writers append inside their existing transaction. UI queries, replay and
material readers never call this module. The worker checkpoints the event and
condition state in the same transaction, so a restart can safely retry a batch.
"""
import asyncio
import hashlib
import json
import logging
import math
import sqlite3
from datetime import UTC, datetime, timedelta

from wici.tracking import MAX_AGE, timestamp
from wici.workspace_repository import encode, iso

LOG = logging.getLogger(__name__)
RETENTION_DAYS = 90
MAX_STREAM = 200000
BATCH = 256


def append_observation(repo, kind, object_ref, source_id, observed_at, identity, payload, trusted=True):
    """Append without committing; the caller owns the lock and transaction."""
    observed = observed_at.astimezone(UTC) if isinstance(observed_at, datetime) and observed_at.tzinfo else timestamp(observed_at)
    now = repo.clock().astimezone(UTC)
    if observed is None:
        observed = now
        trusted = False
    if observed > now+timedelta(seconds=30) or observed < now-timedelta(days=RETENTION_DAYS):
        trusted = False
    key = hashlib.sha256(encode([kind, object_ref, source_id, identity]).encode()).hexdigest()
    # A bounded retained stream also bounds disk growth between maintenance runs.
    # Overflow is sticky and visible; the next successful batch inserts a gap.
    count = getattr(repo, '_monitor_stream_count', None)
    if count is None:
        count = repo.db.execute('SELECT count(*) FROM workspace_observations').fetchone()[0]
    if count >= MAX_STREAM:
        # The stream is a queue, not a second 90-day archive of every aircraft.
        # Under pressure discard already checkpointed observations, retaining a
        # useful recent tail. Unprocessed observations are never silently evicted.
        checkpoint = repo.db.execute('SELECT min(checkpoint_id) FROM workspace_rules WHERE enabled=1').fetchone()[0]
        maximum = repo.db.execute('SELECT COALESCE(max(id),0) FROM workspace_observations').fetchone()[0]
        tail = max(1, min(10000, MAX_STREAM//2))
        floor = min(checkpoint if checkpoint is not None else maximum, maximum-tail)
        repo.db.execute('DELETE FROM workspace_observations WHERE id<=?', (floor,))
        count = repo.db.execute('SELECT count(*) FROM workspace_observations').fetchone()[0]
    repo._monitor_stream_count = count
    if count >= MAX_STREAM:
        repo.db.execute("INSERT INTO workspace_monitor_meta VALUES('overload',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (iso(now),))
        maximum = repo.db.execute('SELECT COALESCE(max(id),0) FROM workspace_observations').fetchone()[0]
        repo.db.execute("INSERT INTO workspace_monitor_meta VALUES('overload_after_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(maximum),))
        return None
    result = repo.db.execute('''INSERT OR IGNORE INTO workspace_observations
        (observation_key,kind,object_ref,source_id,observed_at,recorded_at,trusted,payload_json)
        VALUES(?,?,?,?,?,?,?,?)''',
        (key, kind, object_ref, source_id, iso(observed), iso(now), int(trusted), encode(payload)))
    if result.rowcount:
        repo._monitor_stream_count += 1
    return result.lastrowid if result.rowcount else None


def moving_observations(repo, kind, snapshot):
    from wici.workspace_moving import MovingObjects, object_ref
    now = repo.clock().astimezone(UTC)
    source = 'aircraft' if kind == 'aircraft' else 'ships'
    available = snapshot.get('status') == 'ready' and not snapshot.get('stale') and not snapshot.get('demo')
    fetched = snapshot.get('fetched_at') or iso(now)
    if not available:
        append_observation(repo, 'gap', '*', source, fetched, [fetched, snapshot.get('status')],
                           {'reason': snapshot.get('status', 'unknown')}, False)
        return
    for item in snapshot.get('items', []):
        try:
            ref = object_ref(kind, item.get('hex' if kind == 'aircraft' else 'mmsi', ''))
            point = MovingObjects._point(kind, item)
            if not point:
                continue
            at = timestamp(point['position_at'])
            fresh = 0 <= (now-at).total_seconds() <= MAX_AGE[kind]
            payload = dict(point, object_type=kind, source_name=snapshot.get('source_name'),
                           source_url=snapshot.get('source_url'), fetched_at=fetched)
            append_observation(repo, 'transport', ref, source, point['position_at'],
                               [point['position_at'], point['longitude'], point['latitude']], payload, fresh)
        except (KeyError, ValueError, TypeError):
            continue


def decode_observation(row):
    result = dict(row)
    result['payload'] = json.loads(result.pop('payload_json'))
    result['key'] = result['observation_key']
    result['trusted'] = bool(result['trusted'])
    return result


def _matches(rule, observation):
    config, kind, ref = rule['config'], observation['kind'], observation['object_ref']
    if kind == 'gap':
        target = config.get('object_ref') or config.get('region_ref')
        if ref != '*' and target and ref != target:
            return False
        sources = {'transport': {'aircraft', 'ships'}, 'measurement': {'imgw', 'gios'},
                   'communication': {'imgw_meteo', 'rso', 'rcb', 'sg'}, 'ukraine': {'ukraine_alerts'}}
        if observation['source_id'] not in sources[rule['template']]:
            return False
        if rule['template'] == 'transport':
            typ = config.get('object_type') or config['object_ref'].split(':')[0]
            return observation['source_id'] == ('aircraft' if typ == 'aircraft' else 'ships')
        if rule['template'] == 'measurement':
            provider = 'gios' if config['object_ref'].startswith('air_quality_station:') else 'imgw'
            if observation['source_id'] != provider:
                return False
            resource = observation['payload'].get('resource', '')
            if resource.startswith('gios:data:'):
                return resource.rsplit(':', 1)[-1] == config['sensor_id']
            if resource.startswith('gios:sensors:'):
                return resource.rsplit(':', 1)[-1] == config['object_ref'].rsplit(':', 1)[-1]
            return not resource.startswith('gios:index:')
        return True
    if kind != rule['template']:
        return False
    if kind == 'transport':
        return ((not config.get('object_ref') or config['object_ref'] == ref)
                and (not config.get('object_type') or ref.startswith(config['object_type']+':')))
    if kind == 'measurement':
        value = observation['payload']
        return (ref == config['object_ref'] and str(value.get('sensor_id', '')) == config['sensor_id']
                and value.get('metric') == config['metric'] and value.get('unit') == config['unit'])
    if kind == 'communication':
        if config.get('source_ids') and observation['source_id'] not in config['source_ids']:
            return False
        code = config['admin_code']
        return any((area.get('admin_code') or '').startswith(code)
                   for area in observation['payload'].get('areas', []))
    return ref == config['region_ref']


def evaluate(rule, observation, previous=None, area=None):
    """Pure transition function shared by live processing and Preview."""
    if not _matches(rule, observation):
        return None, None
    at = timestamp(observation['observed_at'])
    old_at = timestamp(previous.get('observed_at')) if previous else None
    # Corrections at the same source timestamp are meaningful (65 -> 40 is
    # a new sensor revision). Stream identity prevents repeated cache reads.
    if old_at and at < old_at:
        return None, None
    state = {'condition_state': 'unknown', 'observed_at': observation['observed_at']}
    if not observation['trusted'] or observation['kind'] == 'gap':
        return state, None
    config, payload, template = rule['config'], observation['payload'], rule['template']
    old_known = bool(previous and previous.get('condition_state') != 'unknown')
    description = trigger = None
    if template == 'transport':
        from wici.workspace_areas import contains
        if not area or area['archived']:
            return state, None
        if old_at and (at-old_at).total_seconds() > MAX_AGE[payload['object_type']]:
            old_known = False
        inside = contains(area, payload['longitude'], payload['latitude'])
        state['condition_state'] = 'met' if inside else 'unmet'
        state['inside'] = inside
        if inside and not old_known and config['transition'] != 'exit':
            description, trigger = 'Zaobserwowano obiekt wewnątrz obszaru; brak potwierdzonego przekroczenia granicy.', 'observed_inside'
        elif old_known and inside != previous.get('inside'):
            transition = 'enter' if inside else 'exit'
            if config['transition'] in ('both', transition):
                description = ('Zaobserwowano wejście obiektu do obszaru.' if inside
                               else 'Zaobserwowano wyjście obiektu z obszaru.')
                trigger = transition
    elif template == 'measurement':
        value = payload.get('value')
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            return state, None
        if old_at and (at-old_at).total_seconds() > 7200:
            old_known = False
        was_high = old_known and previous['condition_state'] == 'met'
        high = value > (config.get('return_threshold') if was_high and config.get('return_threshold') is not None else config['threshold'])
        state['condition_state'] = 'met' if high else 'unmet'
        state['value'] = value
        if high and not was_high:
            prefix = 'Zaobserwowano wartość powyżej progu użytkownika' if not old_known else 'Przekroczono próg użytkownika'
            description = f'{prefix}: {value} {config["unit"]} > {config["threshold"]} {config["unit"]}. To nie oficjalny indeks.'
            trigger = 'threshold'
    elif template == 'communication':
        state['condition_state'] = 'met'
        description = ('Nowa publikacja' if payload.get('version_number') == 1 else 'Istotna aktualizacja komunikatu')
        description += f' dotycząca obszaru administracyjnego {config["admin_code"]}; dokładność publikacji pozostaje administracyjna.'
        trigger = 'new_version'
    else:
        level = payload.get('state')
        if level not in ('red', 'yellow', 'none'):
            return state, None
        if old_at and (at-old_at).total_seconds() > 60:
            old_known = False
        state.update(condition_state='unmet' if level == 'none' else 'met', level=level)
        if not old_known:
            if level != 'none':
                description = 'Zaobserwowano aktywny stan alarmowy po rozpoczęciu oceny lub luce; nie jest to dokładny moment rozpoczęcia alarmu.'
                trigger = 'observed_active'
        elif previous.get('level') != level:
            description = f'Zaobserwowano zmianę znanego stanu alarmowego: {previous.get("level")} → {level}.'
            trigger = 'state_change'
    if description is None:
        return state, None
    return state, {'condition_state': state['condition_state'], 'description': description, 'trigger': trigger}


def historical_observations(workspace, rule, start, end):
    """Use retained source histories plus the durable stream, never the network."""
    db, config, kind = workspace.db, rule['config'], rule['template']
    ref = config.get('object_ref') or config.get('region_ref')
    where, params = '', [iso(start), iso(end), kind]
    if ref:
        where = " AND (kind='gap' OR object_ref=?)"
        params.append(ref)
    elif kind == 'transport' and config.get('object_type'):
        where = " AND (kind='gap' OR object_ref LIKE ?)"
        params.append(config['object_type']+':%')
    rows = [decode_observation(row) for row in db.execute('''SELECT * FROM workspace_observations
        WHERE observed_at>=? AND observed_at<? AND kind IN (?, 'gap')'''+where+
        ' ORDER BY observed_at,id LIMIT 10001', params)]
    limited = len(rows) > 10000
    rows = rows[:10000]
    source = []
    if kind == 'measurement':
        for row in db.execute('''SELECT * FROM station_measurements WHERE object_ref=? AND sensor_id=? AND metric=?
            AND observed_at>=? AND observed_at<? AND is_current=1 ORDER BY observed_at LIMIT 10001''',
            (config['object_ref'], config['sensor_id'], config['metric'], iso(start), iso(end))):
            source.append({'kind': kind, 'object_ref': row['object_ref'], 'source_id': 'gios' if row['sensor_id'] else 'imgw',
                           'observed_at': row['observed_at'], 'trusted': row['quality'] == 'valid',
                           'payload': dict(row), 'key': f'history:measurement:{row["id"]}'})
        gios = config['object_ref'].startswith('air_quality_station:gios:')
        resources = (['gios:stations', 'gios:sensors:'+config['object_ref'].rsplit(':', 1)[-1],
                      'gios:data:'+config['sensor_id']] if gios else ['hydro:stations'])
        for row in db.execute('''SELECT * FROM workspace_source_runs
            WHERE fetched_at>=? AND fetched_at<? AND resource IN ('''+','.join('?' for _ in resources)+''')
            AND (status NOT IN ('ready','empty') OR complete=0) ORDER BY fetched_at,id LIMIT 10001''',
            [iso(start), iso(end), *resources]):
            source.append({'kind': 'gap', 'object_ref': '*', 'source_id': 'gios' if gios else 'imgw',
                           'observed_at': row['fetched_at'], 'trusted': False,
                           'payload': {'resource': row['resource'], 'reason': row['message'] or row['status']},
                           'key': f'history:source:gap:{row["id"]}'})
    elif kind == 'transport':
        where, params = '', [iso(start), iso(end)]
        if config.get('object_ref'):
            _, prefix, identity = config['object_ref'].split(':')
            where = ' AND t.kind=? AND t.object_id=?'
            params.extend(['aircraft' if prefix == 'icao' else 'ship', identity])
        elif config.get('object_type'):
            where = ' AND t.kind=?'
            params.append(config['object_type'])
        for row in db.execute('''SELECT p.*,t.kind,t.object_id FROM object_track_points p JOIN object_tracks t ON t.id=p.track_id
            WHERE p.position_at>=? AND p.position_at<?'''+where+' ORDER BY p.position_at LIMIT 10001', params):
            prefix = 'aircraft:icao:' if row['kind'] == 'aircraft' else 'ship:mmsi:'
            if row['break_before']:
                source.append({'kind': 'gap', 'object_ref': prefix+row['object_id'], 'source_id': 'aircraft' if row['kind'] == 'aircraft' else 'ships',
                               'observed_at': row['position_at'], 'trusted': False, 'payload': {'reason': 'Przerwa zapisanej trasy'},
                               'key': f'history:position:gap:{row["track_id"]}:{row["position_at"]}'})
            source.append({'kind': kind, 'object_ref': prefix+row['object_id'], 'source_id': 'aircraft' if row['kind'] == 'aircraft' else 'ships',
                           'observed_at': row['position_at'], 'trusted': True,
                           'payload': dict(dict(row), object_type=row['kind']), 'key': f'history:position:{row["track_id"]}:{row["position_at"]}'})
    elif kind == 'communication':
        for row in db.execute('''SELECT v.*,d.source_id FROM document_versions v JOIN documents d ON d.id=v.document_id
            WHERE v.created_at>=? AND v.created_at<? ORDER BY v.created_at,v.id LIMIT 10001''', (iso(start), iso(end))):
            payload = dict(row)
            fields = json.loads(row['fields_json'])
            if fields.get('contract_validated') is not True or fields.get('access_allowed') is not True:
                continue
            # Areas are versioned publisher metadata, never a current projection.
            payload['areas'] = fields.get('event', {}).get('locations', [])
            if not payload['areas']:
                payload['areas'] = fields.get('areas', [])
            source.append({'kind': kind, 'object_ref': f'communication:{row["document_id"]}', 'source_id': row['source_id'],
                           'observed_at': row['created_at'], 'trusted': True, 'payload': payload,
                           'key': f'history:document:{row["id"]}'})
    elif kind == 'ukraine':
        for row in db.execute('''SELECT * FROM workspace_ukraine_observations WHERE region_ref=?
            AND observed_at>=? AND observed_at<? ORDER BY observed_at,id LIMIT 10001''',
            (config['region_ref'], iso(start), iso(end))):
            source.append({'kind': kind, 'object_ref': row['region_ref'], 'source_id': 'ukraine_alerts',
                           'observed_at': row['observed_at'], 'trusted': True, 'payload': dict(row),
                           'key': f'history:ukraine:{row["id"]}'})
        for row in db.execute('''SELECT * FROM workspace_ukraine_runs
            WHERE observed_at>=? AND observed_at<? AND status!='ready'
            ORDER BY observed_at,id LIMIT 10001''', (iso(start), iso(end))):
            source.append({'kind': 'gap', 'object_ref': '*', 'source_id': 'ukraine_alerts',
                           'observed_at': row['observed_at'], 'trusted': False,
                           'payload': {'reason': row['reason'] or row['status']},
                           'key': f'history:ukraine:gap:{row["id"]}'})
    def identity(row):
        return (row['kind'], row['object_ref'], row['observed_at'], row['source_id'],
                row['payload'].get('resource') if row['kind'] == 'gap' else None)
    keys = {identity(row) for row in rows}
    rows.extend(row for row in source if identity(row) not in keys)
    rows.sort(key=lambda row: (row['observed_at'], row['kind'] != 'gap', row.get('id', 0)))
    return rows[:10000], limited or len(source) > 10000 or len(rows) > 10000


class WorkspaceMonitor:
    def __init__(self, workspace):
        self.workspace, self.repo, self.db = workspace, workspace.repo, workspace.db
        self.sources = None
        self.worker = None
        self.closed = False
        self.error = None
        self.last_cycle = None
        self.last_poll = {}
        self.last_maintenance = None
        self.source_errors = {}
        with self.repo.lock, self.db:
            # A server restart is a coverage break, even if the next source
            # report arrives quickly. Preserve checkpoints, not continuity.
            self.db.execute('DELETE FROM workspace_rule_states')
            self.db.execute("UPDATE workspace_rules SET condition_state='unknown',error='Restart WICI; oczekiwanie na nową obserwację.' WHERE enabled=1")

    def bind(self, sources):
        self.sources = sources
        return self

    def start(self):
        if self.worker is None and not self.closed:
            self.worker = asyncio.create_task(self._run(), name='wici-workspace-monitor')
        return self

    def status(self):
        with self.repo.lock:
            count = self.db.execute('SELECT count(*) FROM workspace_observations').fetchone()[0]
            checkpoint = self.db.execute('SELECT min(checkpoint_id) FROM workspace_rules WHERE enabled=1').fetchone()[0]
            pending = self.db.execute('SELECT count(*) FROM workspace_observations WHERE id>?', (checkpoint,)).fetchone()[0] if checkpoint is not None else 0
            overload = self.db.execute("SELECT value FROM workspace_monitor_meta WHERE key='overload'").fetchone()
            moving = getattr(self.sources, 'moving_ingestion', None)
            persistence = moving.status() if moving is not None else {}
            raw_errors = persistence.get('monitor_errors', {})
            return {'running': bool(self.worker and not self.worker.done()),
                    'error': self.error or next(iter(self.source_errors.values()), None) or next(iter(raw_errors.values()), None),
                    'source_errors': dict(self.source_errors),
                    'last_cycle_at': self.last_cycle, 'retained_observations': count,
                    'pending_observations': pending, 'transport_pending': persistence.get('monitor_pending', 0),
                    'transport_errors': raw_errors,
                    'max_observations': MAX_STREAM, 'overload_at': overload[0] if overload else None,
                    'active_rules': self.db.execute('SELECT count(*) FROM workspace_rules WHERE enabled=1').fetchone()[0],
                    'background_rules': self.db.execute("SELECT count(*) FROM workspace_rules WHERE enabled=1 AND mode='background'").fetchone()[0],
                    'notice': 'Wymaga działającego serwera. Restart i awaria źródła nie uzupełniają brakujących odczytów.'}

    def process(self):
        processed = 0
        with self.repo.lock, self.db:
            overload = self.db.execute("SELECT value FROM workspace_monitor_meta WHERE key='overload'").fetchone()
            boundary = self.db.execute("SELECT value FROM workspace_monitor_meta WHERE key='overload_after_id'").fetchone()
            rules = [self.workspace.rules.decode(row) for row in self.db.execute('SELECT * FROM workspace_rules WHERE enabled=1')]
            for rule in rules:
                area = None
                if rule['template'] == 'transport':
                    try:
                        area = self.workspace.areas.detail(rule['config']['area_id'])
                    except KeyError:
                        pass
                area_revision = area['revision'] if area else 0
                self._expire_states(rule, area_revision)
                observations = self.db.execute('SELECT * FROM workspace_observations WHERE id>? ORDER BY id LIMIT ?',
                                               (rule['checkpoint_id'], BATCH)).fetchall()
                for row in observations:
                    self._apply_overload_gap(rule, row['id']-1, overload, boundary)
                    observation = decode_observation(row)
                    ref = observation['object_ref']
                    if observation['kind'] == 'gap' and _matches(rule, observation):
                        # Source failures break all identities; a track/session
                        # break belongs only to that object, never its peers.
                        if ref == '*':
                            self.db.execute('DELETE FROM workspace_rule_states WHERE rule_id=?', (rule['id'],))
                        else:
                            self.db.execute('INSERT OR REPLACE INTO workspace_rule_states VALUES(?,?,?,?,?)',
                                            (rule['id'], rule['revision'], area_revision, ref,
                                             encode({'condition_state': 'unknown', 'observed_at': observation['observed_at']})))
                        self.db.execute("UPDATE workspace_rules SET condition_state='unknown',last_evaluated_at=?,error=? WHERE id=?",
                                        (iso(self.repo.clock()), 'Luka źródła; brak wiarygodnej obserwacji.', rule['id']))
                        self.db.execute('UPDATE workspace_rules SET checkpoint_id=? WHERE id=?', (row['id'], rule['id']))
                        processed += 1
                        continue
                    previous = self.db.execute('''SELECT state_json FROM workspace_rule_states
                        WHERE rule_id=? AND rule_revision=? AND area_revision=? AND object_ref=?''',
                        (rule['id'], rule['revision'], area_revision, ref)).fetchone()
                    state, event = evaluate(rule, observation, json.loads(previous[0]) if previous else None, area)
                    if state is not None:
                        self.db.execute('INSERT OR REPLACE INTO workspace_rule_states VALUES(?,?,?,?,?)',
                                        (rule['id'], rule['revision'], area_revision, ref, encode(state)))
                        now = iso(self.repo.clock())
                        self.db.execute('''UPDATE workspace_rules SET last_evaluated_at=?,condition_state=?,
                            last_successful_at=CASE WHEN ? THEN ? ELSE last_successful_at END,error=? WHERE id=?''',
                            (now, state['condition_state'], int(state['condition_state'] != 'unknown'), observation['observed_at'],
                             None if state['condition_state'] != 'unknown' else 'Brak wiarygodnej obserwacji lub luka źródła.', rule['id']))
                        if event:
                            observation['trigger'] = event['trigger']
                            self.workspace.events.emit(rule, observation, event['condition_state'], event['description'], area)
                    self.db.execute('UPDATE workspace_rules SET checkpoint_id=? WHERE id=?', (row['id'], rule['id']))
                    processed += 1
                    self._apply_overload_gap(rule, row['id'], overload, boundary)
                if not observations:
                    self._apply_overload_gap(rule, rule['checkpoint_id'], overload, boundary)
                states = [json.loads(row[0])['condition_state'] for row in self.db.execute('''SELECT state_json
                    FROM workspace_rule_states WHERE rule_id=? AND rule_revision=? AND area_revision=?''',
                    (rule['id'], rule['revision'], area_revision))]
                aggregate = 'met' if 'met' in states else 'unknown' if not states or 'unknown' in states else 'unmet'
                self.db.execute('UPDATE workspace_rules SET condition_state=? WHERE id=?', (aggregate, rule['id']))
            self.last_cycle = iso(self.repo.clock())
        return processed

    def _apply_overload_gap(self, rule, checkpoint, overload, boundary):
        if not overload or not boundary or checkpoint < int(boundary[0]):
            return
        key = 'overload_handled:'+rule['id']
        handled = self.db.execute('SELECT value FROM workspace_monitor_meta WHERE key=?', (key,)).fetchone()
        if handled and handled[0] == overload[0]:
            return
        self.db.execute('DELETE FROM workspace_rule_states WHERE rule_id=?', (rule['id'],))
        self.db.execute("UPDATE workspace_rules SET condition_state='unknown',error='Przepełnienie strumienia; luka monitorowania.' WHERE id=?", (rule['id'],))
        self.db.execute('INSERT INTO workspace_monitor_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        (key, overload[0]))

    def _expire_states(self, rule, area_revision):
        if rule['template'] == 'communication':
            return
        now = self.repo.clock().astimezone(UTC)
        for row in self.db.execute('''SELECT object_ref,state_json FROM workspace_rule_states
            WHERE rule_id=? AND rule_revision=? AND area_revision=?''',
            (rule['id'], rule['revision'], area_revision)).fetchall():
            state = json.loads(row['state_json'])
            maximum = (MAX_AGE[row['object_ref'].split(':')[0]] if rule['template'] == 'transport'
                       and row['object_ref'] != '*' else 60 if rule['template'] == 'ukraine' else 7200)
            observed = timestamp(state.get('observed_at'))
            if observed and (now-observed).total_seconds() > maximum and state['condition_state'] != 'unknown':
                state['condition_state'] = 'unknown'
                self.db.execute('''UPDATE workspace_rule_states SET state_json=? WHERE rule_id=?
                    AND rule_revision=? AND area_revision=? AND object_ref=?''',
                    (encode(state), rule['id'], rule['revision'], area_revision, row['object_ref']))
                self.db.execute('UPDATE workspace_rules SET error=? WHERE id=?',
                                ('Brak świeżej obserwacji; stan warunku jest nieznany.', rule['id']))

    async def _background(self):
        sources = self.sources
        if sources is None:
            return
        rules = [r for r in self.workspace.rules.list()['items'] if r['enabled'] and r['mode'] == 'background']
        resources = set()
        for rule in rules:
            config = rule['config']
            if rule['template'] == 'transport':
                kind = config.get('object_type') or config['object_ref'].split(':')[0]
                resources.add((kind, ''))
            elif rule['template'] == 'measurement':
                if config['object_ref'].startswith('air_quality_station:'):
                    resources.add(('gios_sensors', config['object_ref'].rsplit(':', 1)[-1]))
                    resources.add(('gios_data', config['sensor_id']))
                else:
                    resources.add(('hydro', ''))
            elif rule['template'] == 'ukraine':
                resources.add(('ukraine', ''))
            # Communication sources already have an always-on shared scheduler.
        now = asyncio.get_running_loop().time()
        self.source_errors = {key: message for key, message in self.source_errors.items()
                              if tuple(key.split('|', 1)) in resources}
        for resource, identity in sorted(resources, key=lambda item: (item[0] == 'gios_data', item)):
            key = resource, identity
            interval = 10 if resource in ('aircraft', 'ship') else 15 if resource == 'ukraine' else 60
            if now-self.last_poll.get(key, -interval) < interval:
                continue
            self.last_poll[key] = now
            try:
                response = None
                if resource in ('aircraft', 'ship'):
                    service = getattr(sources, 'aircraft' if resource == 'aircraft' else 'ships')
                    response = await service.fetch()
                elif resource == 'hydro':
                    response = await sources.hydro.fetch()
                elif resource.startswith('gios_'):
                    response = await sources.gios.fetch('sensors' if resource == 'gios_sensors' else 'data', int(identity))
                else:
                    await sources.ukraine.geometry()
                    response = await sources.ukraine.fetch_alerts()
                if response is not None and (response.get('status') not in ('ready', 'empty') or response.get('stale')):
                    message = f'Źródło {resource}: {response.get("status", "unknown")}; brak świeżych obserwacji.'
                    self.source_errors[resource+'|'+identity] = message
                    await asyncio.to_thread(self._source_gap, resource, identity, message)
                else:
                    self.source_errors.pop(resource+'|'+identity, None)
            except (ValueError, RuntimeError, OSError, KeyError):
                message = f'Odczyt źródła {resource} nie powiódł się; brakujące dane pozostają luką.'
                self.source_errors[resource+'|'+identity] = message
                await asyncio.to_thread(self._source_gap, resource, identity, message)

    def _source_gap(self, resource, identity, message):
        source = {'aircraft': 'aircraft', 'ship': 'ships', 'hydro': 'imgw',
                  'gios_sensors': 'gios', 'gios_data': 'gios', 'ukraine': 'ukraine_alerts'}[resource]
        name = ('gios:sensors:' if resource == 'gios_sensors' else
                'gios:data:' if resource == 'gios_data' else '')+identity
        with self.repo.lock, self.db:
            now = iso(self.repo.clock())
            append_observation(self.repo, 'gap', '*', source, now, [resource, identity, now],
                               {'resource': name, 'reason': message}, False)

    def prune(self):
        with self.repo.lock, self.db:
            cutoff = iso(self.repo.clock()-timedelta(days=RETENTION_DAYS))
            self.db.execute('DELETE FROM workspace_observations WHERE recorded_at<?', (cutoff,))
            self.repo._monitor_stream_count = self.db.execute('SELECT count(*) FROM workspace_observations').fetchone()[0]
            self.workspace.events.prune()

    async def _run(self):
        while not self.closed:
            try:
                self.error = None
                await self._background()
                await asyncio.to_thread(self.process)
                now = self.repo.clock()
                if self.last_maintenance is None or (now-self.last_maintenance).total_seconds() >= 3600:
                    await asyncio.to_thread(self.prune)
                    self.last_maintenance = now
            except (sqlite3.Error, ValueError, RuntimeError, OSError, KeyError, TypeError):
                self.error = 'Nie udało się zapisać oceny reguł. Trwały checkpoint zostanie ponowiony.'
                LOG.exception('Local monitoring evaluation failed')
            await asyncio.sleep(1)

    async def close(self):
        self.closed = True
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            self.worker = None
        # A shielded final drain avoids losing already persisted observations.
        for _ in range(32):
            if not await asyncio.to_thread(self.process):
                break
