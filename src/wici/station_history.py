"""Bounded persistence of normalized, on-demand station responses.

The source services own networking and caches. This writer only receives a new
response, never a cache hit, and uses the repository's existing connection/lock.
"""
import asyncio
import copy
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from wici.monitor_epochs import RECEIPT_KEY, receipt, stamp_payload

LOG = logging.getLogger(__name__)
RETENTION = timedelta(days=14)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class StationHistory:
    def __init__(self, repo, queue_size=32):
        self.repo = repo
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.worker = None
        self.accepting = True
        self.last_written_at = None
        self.errors = {}
        self.error_generations = {}
        self.generation = 0
        self.rejected_submissions = 0
        self.last_pruned_at = None

    def start(self):
        if self.worker is None and self.accepting:
            self.worker = asyncio.create_task(self._run(), name='wici-station-history')
        return self

    def submit(self, resource, response):
        """Do not block the source response when disk persistence is delayed."""
        if not self.accepting:
            return False
        self.start()
        self.generation += 1
        received = receipt(self.repo)
        try:
            # The legacy UI may subsequently change freshness/selection fields.
            self.queue.put_nowait((resource, stamp_payload(self.repo, copy.deepcopy(response), received), self.generation))
            return True
        except asyncio.QueueFull:
            self.rejected_submissions += 1
            self.errors[resource] = 'Kolejka historii jest pełna; odczyt nie został zapisany.'
            self.error_generations[resource] = self.generation
            return False

    def report_failure(self, resource, response):
        return self.submit(resource, {
            'status': response.get('status', 'error'), 'items': [],
            'fetched_at': self.repo.clock().astimezone(UTC).isoformat(),
            'message': response.get('message', 'Źródło chwilowo niedostępne.'),
            'rejected_count': response.get('rejected_count', 0),
            '_failure': True,
        })

    def status(self):
        return {'pending': self.queue.qsize(), 'last_written_at': self.last_written_at,
                'errors': dict(self.errors), 'rejected_submissions': self.rejected_submissions}

    async def flush(self):
        await self.queue.join()

    async def close(self):
        self.accepting = False
        if self.worker is not None:
            await self.flush()
            await self.queue.put(None)
            await self.worker
            self.worker = None

    async def _run(self):
        while True:
            now = self.repo.clock().astimezone(UTC)
            if self.last_pruned_at is None or now - self.last_pruned_at >= timedelta(hours=1):
                try:
                    await asyncio.to_thread(self.prune)
                    self.last_pruned_at = now
                    self.errors.pop('retention', None)
                except (sqlite3.Error, OSError, ValueError, RuntimeError):
                    self.errors['retention'] = 'Nie udało się usunąć przeterminowanych pomiarów z lokalnej historii.'
                    LOG.error('Station history retention maintenance failed')
            try:
                entry = await asyncio.wait_for(self.queue.get(), timeout=60)
            except TimeoutError:
                # Local retention maintenance only: this worker never fetches a source.
                continue
            try:
                if entry is None:
                    return
                resource, response, generation = entry
                try:
                    await asyncio.to_thread(self.write, resource, response, generation)
                    self.last_written_at = self.repo.clock().astimezone(UTC).isoformat()
                    # A queued older response succeeding cannot clear the loss of
                    # a newer response that did not fit into the queue.
                    if generation > self.error_generations.get(resource, 0):
                        self.errors.pop(resource, None)
                        self.error_generations.pop(resource, None)
                except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RuntimeError):
                    # Do not expose database paths or upstream response contents.
                    self.errors[resource] = 'Nie udało się zapisać odczytu w lokalnej historii.'
                    self.error_generations[resource] = generation
                    LOG.error('Station history persistence failed for %s', resource)
            finally:
                self.queue.task_done()

    def write(self, resource, response, generation=None):
        """Persist one response atomically; public for isolated fixture import."""
        from wici.workspace_repository import WorkspaceRepository

        response = stamp_payload(self.repo, response)
        fetched = date(response.get('fetched_at')) or self.repo.clock().astimezone(UTC)
        provider, kind, *identity_parts = resource.split(':')
        identity = identity_parts[0] if identity_parts else None
        if provider not in ('hydro', 'gios') or kind not in ('stations', 'sensors', 'data', 'index'):
            raise ValueError('Unsupported station history resource')
        status = response.get('status', 'error')
        items = response.get('items', [])
        complete = status in ('ready', 'empty') and not response.get('rejected_count', 0)
        with self.repo.lock, self.repo.db:
            if generation is not None and resource in self.errors and generation > self.error_generations.get(resource, 0):
                from wici.workspace_monitor import append_observation
                append_observation(self.repo, 'gap', '*', 'gios' if provider == 'gios' else 'imgw',
                                   fetched, ['storage_recovery', resource, generation],
                                   {'resource': resource, 'reason': 'Przerwa zapisu lub przepełnienie kolejki historii.'},
                                   False, receipt=response[RECEIPT_KEY])
            self.repo.db.execute('''INSERT INTO workspace_source_runs
                (resource,fetched_at,status,item_count,rejected_count,complete,message) VALUES(?,?,?,?,?,?,?)''',
                (resource, fetched.isoformat(), status, len(items), response.get('rejected_count', 0),
                 int(complete), str(response.get('message', ''))[:500]))
            self._prune(fetched)
            if response.get('_failure') or status in ('error', 'disabled'):
                from wici.workspace_monitor import append_observation
                append_observation(self.repo, 'gap', '*', 'gios' if provider == 'gios' else 'imgw',
                                   fetched, [resource, fetched.isoformat(), status],
                                   {'resource': resource, 'reason': status}, False, receipt=response[RECEIPT_KEY])
                return
            catalogue = WorkspaceRepository(self.repo)
            changed = {}
            if kind == 'stations':
                source_id = 'imgw' if provider == 'hydro' else 'gios'
                prefix = 'hydro_station:imgw:' if provider == 'hydro' else 'air_quality_station:gios:'
                seen = set()
                for item in items:
                    ref = prefix + str(item['id'])
                    seen.add(ref)
                    metadata = {k: v for k, v in item.items()
                                if k not in ('measurements', 'threshold_status')}
                    metadata['catalogue_present'] = True
                    previous = self.repo.db.execute('SELECT metadata_json FROM catalog_objects WHERE ref=?',
                                                    (ref,)).fetchone()
                    # Sensors are subordinate station data; catalogue refreshes
                    # must not discard a sensor list acquired independently.
                    if previous:
                        old = json.loads(previous['metadata_json'])
                        if 'sensors' in old:
                            metadata['sensors'] = old['sensors']
                    catalogue.upsert_station(ref, source_id, str(item['id']), item['name'],
                                             item.get('latitude'), item.get('longitude'), metadata)
                    if provider == 'hydro':
                        thresholds = {k: item.get(k) for k in ('warning_level_cm', 'alarm_level_cm')}
                        for metric, sample in item.get('measurements', {}).items():
                            observation = self._measurement(ref, '', metric, sample, fetched,
                                                            response, thresholds if metric == 'water_level' else {})
                            if observation:
                                changed.setdefault(ref, []).append(observation)
                if complete:
                    self._mark_absent(prefix, seen)
            elif provider == 'gios' and kind == 'sensors':
                for item in items:
                    ref = 'air_quality_station:gios:' + str(item['station_id'])
                    self._ensure_gios_station(catalogue, ref, item['station_id'])
                    self.repo.db.execute('''INSERT INTO station_sensors
                        (sensor_id,object_ref,parameter,name,unit,metadata_json,fetched_at)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(sensor_id) DO UPDATE SET
                        object_ref=excluded.object_ref,parameter=excluded.parameter,name=excluded.name,
                        unit=excluded.unit,metadata_json=excluded.metadata_json,fetched_at=excluded.fetched_at''',
                        (str(item['id']), ref, item['parameter'], str(item.get('name', item['parameter'])),
                         item.get('unit'), encode(item), fetched.isoformat()))
                if identity:
                    ref = 'air_quality_station:gios:' + identity
                    station = self.repo.db.execute('SELECT * FROM catalog_objects WHERE ref=?', (ref,)).fetchone()
                    if station:
                        metadata = json.loads(station['metadata_json'])
                        metadata['sensors'] = [json.loads(row[0]) for row in self.repo.db.execute(
                            'SELECT metadata_json FROM station_sensors WHERE object_ref=? ORDER BY sensor_id', (ref,))]
                        catalogue.upsert_station(ref, 'gios', identity, station['label'], station['latitude'],
                                                 station['longitude'], metadata)
            elif provider == 'gios' and kind == 'data':
                sensor = self.repo.db.execute('SELECT * FROM station_sensors WHERE sensor_id=?',
                                             (identity,)).fetchone()
                if sensor is None:
                    # An unassociated sensor must not be assigned to a guessed station.
                    raise ValueError('Station metadata must precede sensor observations')
                for sample in items:
                    observation = self._measurement(sensor['object_ref'], identity, sensor['parameter'],
                                                    sample, fetched, response, {})
                    if observation:
                        changed.setdefault(sensor['object_ref'], []).append(observation)
            elif provider == 'gios' and kind == 'index':
                ref = 'air_quality_station:gios:' + identity
                self._ensure_gios_station(catalogue, ref, identity)
                for sample in items:
                    observation = self._index(ref, sample, fetched, response)
                    if observation:
                        changed.setdefault(ref, []).append(observation)
            for ref, observations in changed.items():
                latest = max((v for v in observations if isinstance(v, str)), default=None)
                self.repo.db.execute('''UPDATE catalog_objects SET revision=revision+1,
                    updated_at=CASE WHEN ? IS NOT NULL AND (updated_at IS NULL OR updated_at<?)
                    THEN ? ELSE updated_at END WHERE ref=?''', (latest, latest, latest, ref))

    def _ensure_gios_station(self, catalogue, ref, identity):
        if not self.repo.db.execute('SELECT 1 FROM catalog_objects WHERE ref=?', (ref,)).fetchone():
            catalogue.upsert_station(ref, 'gios', str(identity), f'Stacja GIOŚ {identity}', None, None,
                                     {'catalogue_present': None, 'metadata_incomplete': True})

    def _mark_absent(self, prefix, seen):
        rows = self.repo.db.execute('SELECT ref,metadata_json FROM catalog_objects WHERE ref LIKE ?',
                                    (prefix + '%',)).fetchall()
        for row in rows:
            if row['ref'] in seen:
                continue
            metadata = json.loads(row['metadata_json'])
            if metadata.get('catalogue_present') is not False:
                metadata['catalogue_present'] = False
                self.repo.db.execute('UPDATE catalog_objects SET metadata_json=?,revision=revision+1 WHERE ref=?',
                                     (encode(metadata), row['ref']))

    def _identity(self, ref, sensor, metric, sample, fetched):
        observed = date(sample.get('observed_at'))
        quality = ('unknown_time' if observed is None else 'future'
                   if observed > fetched else 'valid')
        key = observed.isoformat() if observed else 'unknown:' + digest(sample.get('source_time'))
        first = fetched.isoformat()
        if quality == 'valid':
            if observed < fetched - RETENTION:
                return None
        else:
            key_hash = digest([ref, sensor, metric, key])
            self.repo.db.execute('INSERT OR IGNORE INTO station_observation_keys VALUES(?,?)', (key_hash, first))
            first = self.repo.db.execute('SELECT first_fetched_at FROM station_observation_keys WHERE key_hash=?',
                                        (key_hash,)).fetchone()[0]
            if date(first) < fetched - RETENTION:
                return None
        return key, observed.isoformat() if observed else None, quality, first

    def _measurement(self, ref, sensor, metric, sample, fetched, response, thresholds):
        identity = self._identity(ref, sensor, metric, sample, fetched)
        if identity is None:
            return False
        key, observed, quality, first = identity
        content = {'value': sample.get('value'), 'unit': sample.get('unit'), 'source_time': sample.get('source_time'),
                   'quality': quality, 'thresholds': thresholds}
        content_hash = digest(content)
        previous = self.repo.db.execute('''SELECT content_hash,revision,first_fetched_at FROM station_measurements
            WHERE object_ref=? AND sensor_id=? AND metric=? AND observed_key=? ORDER BY revision DESC LIMIT 1''',
            (ref, sensor, metric, key)).fetchone()
        if previous and previous['content_hash'] == content_hash:
            return False
        self.repo.db.execute('''UPDATE station_measurements SET is_current=0 WHERE
            object_ref=? AND sensor_id=? AND metric=? AND observed_key=? AND is_current=1''',
            (ref, sensor, metric, key))
        self.repo.db.execute('''INSERT INTO station_measurements
            (object_ref,sensor_id,metric,observed_key,observed_at,source_time,value,unit,fetched_at,
             first_fetched_at,revision,quality,content_hash,provenance_json,thresholds_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ref, sensor, metric, key, observed, sample.get('source_time'), sample.get('value'), sample.get('unit'),
             fetched.isoformat(), previous['first_fetched_at'] if previous else first,
             previous['revision'] + 1 if previous else 1, quality, content_hash,
             self._provenance(response), encode(thresholds)))
        from wici.workspace_monitor import append_observation
        revision = previous['revision'] + 1 if previous else 1
        station = self.repo.db.execute('SELECT label,latitude,longitude FROM catalog_objects WHERE ref=?', (ref,)).fetchone()
        append_observation(self.repo, 'measurement', ref, 'gios' if sensor else 'imgw', observed,
                           [sensor, metric, key, revision],
                           {'sensor_id': str(sensor), 'metric': metric, 'unit': sample.get('unit'),
                            'value': sample.get('value'), 'source_time': sample.get('source_time'),
                            'quality': quality, 'revision': revision, 'fetched_at': fetched.isoformat(),
                            'label': station['label'] if station else ref,
                            'latitude': station['latitude'] if station else None,
                            'longitude': station['longitude'] if station else None,
                            'source_url': response.get('source_url'),
                            'provenance': json.loads(self._provenance(response))},
                           quality == 'valid' and not sample.get('stale')
                           and sample.get('freshness', 'fresh') == 'fresh'
                           and sample.get('status', 'value' if sensor else 'fresh') == ('value' if sensor else 'fresh'),
                           receipt=response[RECEIPT_KEY])
        return observed if quality == 'valid' else True

    def _index(self, ref, sample, fetched, response):
        identity = self._identity(ref, '', 'official_index', sample, fetched)
        if identity is None:
            return False
        key, observed, quality, first = identity
        calculated = sample.get('calculated', {})
        calculated_at = date(calculated.get('observed_at'))
        content = {'value': sample.get('value'), 'name': sample.get('name'), 'quality': quality,
                   'source_time': sample.get('source_time'), 'calculated': calculated}
        content_hash = digest(content)
        previous = self.repo.db.execute('''SELECT content_hash,revision,first_fetched_at
            FROM station_index_observations WHERE object_ref=? AND observed_key=?
            ORDER BY revision DESC LIMIT 1''', (ref, key)).fetchone()
        if previous and previous['content_hash'] == content_hash:
            return False
        self.repo.db.execute('''UPDATE station_index_observations SET is_current=0 WHERE
            object_ref=? AND observed_key=? AND is_current=1''', (ref, key))
        self.repo.db.execute('''INSERT INTO station_index_observations
            (object_ref,observed_key,observed_at,source_time,calculated_at,source_calculated_time,
             value,name,fetched_at,first_fetched_at,revision,quality,content_hash,provenance_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ref, key, observed, sample.get('source_time'), calculated_at.isoformat() if calculated_at else None,
             calculated.get('source_time'), sample.get('value'), sample.get('name'), fetched.isoformat(),
             previous['first_fetched_at'] if previous else first, previous['revision'] + 1 if previous else 1,
             quality, content_hash, self._provenance(response)))
        return observed if quality == 'valid' else True

    @staticmethod
    def _provenance(response):
        return encode({key: response.get(key) for key in ('source_url', 'attribution', 'time_basis')
                       if response.get(key)})

    def prune(self):
        with self.repo.lock, self.repo.db:
            self._prune(self.repo.clock().astimezone(UTC))

    def _prune(self, now):
        cutoff = (now - RETENTION).isoformat()
        for table in ('station_measurements', 'station_index_observations'):
            expired = set()
            # Separate indexed predicates avoid scanning the entire retained
            # history for the OR between observed and first-fetch clocks.
            for condition in ("quality='valid' AND observed_at<?", "quality!='valid' AND first_fetched_at<?"):
                expired.update(row[0] for row in self.repo.db.execute(
                    f'SELECT DISTINCT object_ref FROM {table} WHERE {condition}', (cutoff,)))
                self.repo.db.execute(f'DELETE FROM {table} WHERE {condition}', (cutoff,))
            self.repo.db.executemany('UPDATE catalog_objects SET revision=revision+1 WHERE ref=?',
                                    [(ref,) for ref in expired])
        self.repo.db.execute('DELETE FROM workspace_source_runs WHERE fetched_at<?', (cutoff,))
