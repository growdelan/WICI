"""Local, conservative aircraft position-quality observations; never a GNSS measurement."""
import asyncio
import json
import logging
import math
import re
import sqlite3
from collections import defaultdict
from contextlib import closing, contextmanager, suppress
from datetime import UTC, datetime, time, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

from wici.aircraft import in_poland, label
from wici.weather import inside_ring, number

WARSAW = ZoneInfo('Europe/Warsaw')
WRITE_TIMEOUT = .05
WRITE_RETRY_SECONDS = 1
WRITE_QUEUE_SIZE = 2
FIELDS = ('nac_p', 'nic', 'rc', 'sil', 'sil_type', 'version', 'type', 'gpsOkBefore', 'lastPosition')
STATES = {'anomaly': 'Anomalia jakości pozycji', 'normal': 'Brak wykrytej anomalii przy wystarczającej próbie',
          'insufficient': 'Za mało danych', 'stale': 'Dane nieaktualne', 'error': 'Błąd źródła',
          'disabled': 'Kolektor wyłączony'}
METHOD = ('Komórki 0,5° × 1°; okna 5 min. ≥5 różnych samolotów w każdym z dwóch kolejnych okien; '
          '≥60% samolotów z pogorszeniem w obu oknach (≥połowa ich raportów). '
          'Tło: ≥6 wystarczających okien z poprzednich 2 h, bez dwóch ocenianych okien; wzrost ≥30 p.p. '
          'Tło i sąsiednie okna wyłącznie z tego samego okresu jednego źródła. '
          'Zmiana dostawcy rozpoczyna nową rozgrzewkę; historia bez pochodzenia nie podlega ocenie. '
          'Pogorszenie: NACp <7 lub NIC <6 lub RC >1852 m, tylko bezpośredni ADS-B v1/v2, świeża pozycja ≤60 s. '
          'SIL i eksperymentalne gpsOkBefore są kontekstem. Minimum rozgrzewki 40 min; progi heurystyczne, bez kalibracji GNSS.')


def cell_for(lat, lon):
    return f'{math.floor(lat*2)/2:.1f},{math.floor(lon):.0f}'


def geometry(cell):
    lat, lon = map(float, cell.split(','))
    return {'type': 'Polygon', 'coordinates': [[[lon, lat], [lon+1, lat], [lon+1, lat+.5],
                                                [lon, lat+.5], [lon, lat]]]}


class PositionQuality:
    def __init__(self, repo, aircraft, *, enabled=False, interval=60, retention=72, demo=False):
        self.repo, self.aircraft = repo, aircraft
        self.enabled, self.demo = enabled, demo
        self.interval, self.retention = interval, retention
        if not 60 <= interval <= 300:
            raise ValueError('Interwał jakości pozycji musi wynosić 60–300 s (okna detekcji: 300 s).')
        self.task = None
        self.state_lock = Lock()
        self.storage_error = None
        self.storage_revision = 0
        self.pending = asyncio.Queue(maxsize=WRITE_QUEUE_SIZE)
        self.writer_task = None
        self.active_write = False
        self.dropped_snapshots = 0
        self.closing = False
        self.stopping = asyncio.Event()
        from pathlib import Path
        self.provinces = json.loads((Path(__file__).parent/'static/geo/provinces.geojson').read_text())['features']
        with repo.lock, repo.db:
            repo.db.execute("INSERT OR IGNORE INTO position_quality_source(id,started,status) VALUES(1,NULL,'insufficient')")
            self.db_path = repo.db.execute('PRAGMA database_list').fetchone()[2]
            provider = 'DEMO (syntetyczne)' if demo else aircraft.base()['source_name']
            endpoint = 'demo' if demo else aircraft.source_endpoint
            previous = repo.db.execute('SELECT * FROM position_quality_epochs ORDER BY epoch DESC LIMIT 1').fetchone()
            if previous['provider'] != provider or previous['endpoint'] != endpoint:
                self.epoch = repo.db.execute('INSERT INTO position_quality_epochs(provider,endpoint) VALUES(?,?)',
                                             (provider, endpoint)).lastrowid
                repo.db.execute("UPDATE position_quality_source SET epoch=?, started=NULL, attempt=NULL, "
                                "success=NULL, status='insufficient' WHERE id=1", (self.epoch,))
            else:
                self.epoch = previous['epoch']
            self.source_state = dict(repo.db.execute('SELECT * FROM position_quality_source WHERE id=1').fetchone())
            self.source_state.update(provider=provider, endpoint=endpoint)
        self.prune()
        if enabled and not demo:
            aircraft.quality = self
        if demo:
            self.seed_demo()

    def storage_failed(self, error):
        with self.state_lock:
            changed = self.storage_error != str(error)
            self.storage_error = str(error)
            self.storage_revision += 1
        if changed:
            logging.getLogger('wici').warning('Position quality storage unavailable: %s', error)

    @contextmanager
    def writer_connection(self):
        # Runtime writes use their own connection, never the application's repository lock.
        if self.db_path:
            with closing(sqlite3.connect(self.db_path, timeout=WRITE_TIMEOUT)) as db:
                yield db
        else:  # Standalone, in-memory fixtures cannot be reopened by filename.
            with self.repo.lock:
                yield self.repo.db

    def prune(self):
        try:
            with self.writer_connection() as db, db:
                db.execute('DELETE FROM position_quality_samples WHERE observed < ?',
                           (self.repo.clock().timestamp()-self.retention*3600,))
            return True
        except sqlite3.Error as error:
            self.storage_failed(error)
            return False

    def note_source(self, status, at, success=False):
        # Source health is immediate; an older queued write must never roll it back.
        with self.state_lock:
            if self.source_state['started'] is None:
                self.source_state['started'] = at
            self.source_state.update(attempt=at, status=status)
            if success:
                self.source_state['success'] = at
            return dict(self.source_state)

    def persist(self, state, rows=()):
        with self.state_lock:
            revision = self.storage_revision
        try:
            with self.writer_connection() as db, db:
                db.executemany('INSERT OR IGNORE INTO position_quality_samples VALUES(?,?,?,?,?,?,?,?,?,?)', rows)
                db.execute('DELETE FROM position_quality_samples WHERE observed < ?',
                           (self.repo.clock().timestamp()-self.retention*3600,))
                db.execute('UPDATE position_quality_source SET started=COALESCE(started,?),attempt=?,success=?,status=? '
                           'WHERE id=1 AND epoch=? AND (attempt IS NULL OR attempt<=?)',
                           (state['started'], state['attempt'], state['success'], state['status'],
                            state['epoch'], state['attempt']))
            with self.state_lock:
                if self.storage_revision == revision:
                    self.storage_error = None
            return True
        except sqlite3.Error as error:
            self.storage_failed(error)
            return False

    def source(self, status, at, success=False):
        # Synchronous entry point for fixtures and offline seeding; live callers only enqueue.
        return self.persist(self.note_source(status, at, success))

    def enqueue(self, payload, now):
        if not self.enabled or self.demo or self.closing:
            return
        state = self.note_source('ready', now.timestamp(), success=True)
        self.submit((payload, now, state))

    def notify_error(self, now):
        if not self.enabled or self.demo or self.closing:
            return
        self.submit((None, now, self.note_source('error', now.timestamp())))

    def submit(self, job):
        # The source owns the raw payload; nobody exposes or mutates it after enqueueing.
        if self.writer_task is None:
            self.writer_task = asyncio.create_task(self.write_loop(), name='wici-position-quality-writer')
        if self.pending.full():
            discarded = self.pending.get_nowait()
            self.pending.task_done()
            if discarded[0] is not None:
                with self.state_lock:
                    self.dropped_snapshots += 1
        self.pending.put_nowait(job)

    def process_job(self, job):
        payload, now, state = job
        if payload is None:
            return self.persist(state)
        return self.ingest(payload, now, source_state=state)

    async def write_loop(self):
        while True:
            job = await self.pending.get()
            with self.state_lock:
                self.active_write = True
            try:
                while True:
                    try:
                        saved = await asyncio.to_thread(self.process_job, job)
                    except sqlite3.Error as error:
                        self.storage_failed(error)
                        saved = False
                    except (ValueError, TypeError, KeyError, OverflowError) as error:
                        self.storage_failed(error)
                        # Malformed input is not a transient lock; do not retry it forever.
                        saved = False
                        break
                    if saved or self.closing:
                        break
                    try:
                        await asyncio.wait_for(self.stopping.wait(), timeout=WRITE_RETRY_SECONDS)
                    except TimeoutError:
                        pass
                if not saved and job[0] is not None:
                    with self.state_lock:
                        self.dropped_snapshots += 1
            finally:
                with self.state_lock:
                    self.active_write = False
                self.pending.task_done()

    async def flush(self):
        """Wait for queued writes, without making a source request (also useful in tests)."""
        await self.pending.join()

    def province(self, lat, lon):
        for f in self.provinces:
            g = f['geometry']
            for rings in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
                if inside_ring(lat, lon, rings[0]) and not any(inside_ring(lat, lon, h) for h in rings[1:]):
                    return str(f['properties']['admin_code'])
        return None

    def ingest(self, payload, now, *, source_state=None):
        # Called on the shared, validated raw snapshot BEFORE the aircraft display's freshness filter.
        state = source_state or self.note_source('ready', now.timestamp(), success=True)
        observed = float(payload['now'])/1000
        rows = []
        for a in payload['ac']:
            if not isinstance(a, dict):
                continue
            identity = label(a.get('hex'), 7)
            if not identity or not re.fullmatch(r'~?[0-9a-fA-F]{6}', identity):
                continue
            fields = {k: a[k] for k in FIELDS if k in a}
            for k in ('type', 'sil_type'):
                if k in fields:
                    fields[k] = label(fields[k])
            if 'gpsOkBefore' in fields:
                fields['gpsOkBefore'] = number(fields['gpsOkBefore'], 0, observed+30)
            if 'lastPosition' in fields:
                last = fields['lastPosition']
                fields['lastPosition'] = ({k: number(last.get(k), lo, hi)
                    for k, lo, hi in [('lat', -90, 90), ('lon', -180, 180), ('nic', 0, 11),
                                     ('rc', 0, 10000000), ('seen_pos', 0, 86400)]}
                    if isinstance(last, dict) else None)
            for k, hi in [('nac_p', 11), ('nic', 11), ('rc', 10000000), ('sil', 3), ('version', 2)]:
                v = number(a.get(k), 0, hi)
                if k in a:
                    fields[k] = v if k == 'rc' or v is None or v.is_integer() else None
            for k in ('mlat', 'tisb'):
                fields[k] = [f for f in ('lat', 'lon') if f in a[k]] if isinstance(a.get(k), list) else []
            lat, lon = number(a.get('lat'), -90, 90), number(a.get('lon'), -180, 180)
            age = number(a.get('seen_pos'), 0, 86400)
            fresh = (lat is not None and lon is not None and age is not None
                     and 0 <= now.timestamp()-observed+age <= 60)
            context = not fresh
            if not fresh:
                last = a.get('lastPosition')
                if isinstance(last, dict):
                    lat, lon = number(last.get('lat'), -90, 90), number(last.get('lon'), -180, 180)
                # Stale regular position or lastPosition: only context, never evidence.
            located = lat is not None and lon is not None and in_poland(lat, lon)
            if lat is not None and lon is not None and not located:
                continue  # The spatial endpoint also covers neighbouring countries.
            direct = (a.get('type') in ('adsb_icao', 'adsb_other') and
                      not any(k in fields[s] for s in ('mlat', 'tisb') for k in ('lat', 'lon')))
            eligible = (located and fresh and direct and fields.get('version') in (1, 2)
                        and a.get('alt_baro') != 'ground'
                        and not str(a.get('category', '')).startswith(('B', 'C'))
                        and (any(fields.get(k) is not None for k in ('nac_p', 'nic'))
                             or (fields.get('rc') is not None and fields['rc'] > 0)))
            bad = None
            if eligible:
                bad = int(any(fields.get(k) is not None and fields[k] < threshold
                              for k, threshold in [('nac_p', 7), ('nic', 6)])
                          or (fields.get('rc') is not None and fields['rc'] > 1852))
            rows.append((int(observed//60), identity.lower(), observed,
                         cell_for(lat, lon) if located else None, self.province(lat, lon) if located else None,
                         int(eligible), bad, int(context), json.dumps(fields), state['epoch']))
        return self.persist(state, rows)

    async def run(self):
        while True:
            await self.aircraft.fetch()
            # Cache hits and long Retry-After periods still need retention maintenance.
            # Reuse the last source state; maintenance is not a new upstream attempt.
            if self.pending.empty() and not self.active_write and not self.closing:
                with self.state_lock:
                    state = dict(self.source_state)
                self.submit((None, self.repo.clock(), state))
            await asyncio.sleep(self.interval)

    def start(self):
        if self.enabled and not self.demo and self.aircraft.enabled:
            self.task = asyncio.create_task(self.run(), name='wici-position-quality')

    async def stop(self):
        self.closing = True
        self.stopping.set()
        if self.aircraft.quality is self:
            self.aircraft.quality = None
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.writer_task:
            # Finish an in-flight bounded attempt before closing the repository. During
            # shutdown failed jobs are dropped, rather than waiting for an external lock.
            await self.flush()
            self.writer_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.writer_task

    def history_rows(self, start, until, province):
        query = ('SELECT * FROM position_quality_samples JOIN position_quality_epochs USING(epoch) '
                 'WHERE observed>=? AND observed<=?'
                 + (' AND province=?' if province else ''))
        lower = max(start-7200, self.repo.clock().timestamp()-self.retention*3600)
        params = (lower, until, province) if province else (lower, until)
        if not self.db_path:  # In-memory repositories cannot be reopened by filename.
            self.prune()
            with self.repo.lock:
                return self.repo.db.execute(query, params).fetchall()
        # A worker must not hold the application's shared repository lock during a large read.
        with closing(sqlite3.connect(self.db_path, timeout=WRITE_TIMEOUT)) as db:
            db.row_factory = sqlite3.Row
            try:
                with db:
                    db.execute('DELETE FROM position_quality_samples WHERE observed < ?',
                               (self.repo.clock().timestamp()-self.retention*3600,))
            except sqlite3.Error as error:
                self.storage_failed(error)
            return db.execute(query, params).fetchall()

    def history(self, day, hours=24, province=None):
        now = self.repo.clock()
        end = min(now, datetime.combine(day+timedelta(days=1), time.min, WARSAW).astimezone(UTC))
        until = end.timestamp()
        start = until-hours*3600
        rows = self.history_rows(start, until, province)
        with self.state_lock:
            source = dict(self.source_state)
            storage_error = self.storage_error
            pending_writes = self.pending.qsize()+int(self.active_write)
            dropped_snapshots = self.dropped_snapshots
        windows = defaultdict(list)
        for row in rows:
            if row['cell']:
                windows[(row['cell'], int(row['observed']//300)*300)].append(row)
        metrics = {}
        for key, samples in windows.items():
            epochs = {r['epoch'] for r in samples}
            epoch = next(iter(epochs)) if len(epochs) == 1 else None
            planes = defaultdict(list)
            availability = {f: 0 for f in FIELDS}
            for r in samples:
                for f, v in json.loads(r['fields']).items():
                    if f in availability and v is not None:
                        availability[f] += 1
                if r['eligible']:
                    planes[r['aircraft']].append(r['degraded'])
            n = len(planes)
            bad = sum(sum(v)/len(v) >= .5 for v in planes.values())
            metrics[key] = {'epoch': epoch, 'provenance': 'mixed' if epoch is None else 'unknown' if epoch == 0 else 'known',
                            'provider': samples[0]['provider'] if epoch is not None else 'Różne okresy źródła',
                            'aircraft': n, 'degraded_aircraft': bad, 'share': bad/n if n else None,
                            'reports': len(samples), 'eligible_reports': sum(len(v) for v in planes.values()),
                            'degraded_report_share': (sum(sum(v) for v in planes.values()) /
                                                      sum(len(v) for v in planes.values())) if n else None,
                            'context_reports': sum(r['context'] for r in samples), 'availability': availability,
                            'last_observed': max(r['observed'] for r in samples)}
        items = []
        for (cell, t), m in sorted(metrics.items()):
            if t+300 <= start:
                continue
            previous = metrics.get((cell, t-300), {})
            epoch = m['epoch']
            background = [metrics[(cell, b)]['share'] for b in range(t-7200, t-300, 300)
                          if epoch and (cell, b) in metrics and metrics[(cell, b)]['aircraft'] >= 5
                          and metrics[(cell, b)]['epoch'] == epoch]
            baseline = sum(background)/len(background) if len(background) >= 6 else None
            enough = (bool(epoch) and previous.get('epoch') == epoch
                      and m['aircraft'] >= 5 and previous.get('aircraft', 0) >= 5 and baseline is not None
                      and t+300 <= until)
            anomaly = (enough and m['share'] >= .6 and previous['share'] >= .6 and m['share']-baseline >= .3)
            state = 'anomaly' if anomaly else 'normal' if enough else 'insufficient'
            items.append({'cell': cell, 'window_start': t, 'window_end': t+300,
                          'geometry': geometry(cell), 'state': state, 'label': STATES[state],
                          'baseline': baseline, 'background_windows': len(background), **m})
        age = max(0, now.timestamp()-source['success']) if source['success'] is not None else None
        latest_eligible = max((r['observed'] for r in rows if r['eligible'] and r['epoch'] == self.epoch), default=None)
        observation_age = until-latest_eligible if latest_eligible is not None else None
        status = ('disabled' if not (self.enabled or self.demo) or (not self.aircraft.enabled and not self.demo) else
                  'error' if storage_error or source['status'] == 'error' else
                  'stale' if age is not None and age > max(180, self.interval*3) else
                  'stale' if observation_age is not None and observation_age > max(180, self.interval*3) else
                  'ready' if source['success'] and observation_age is not None else 'insufficient')
        return {'items': items, 'status': status, 'status_label': ('Błąd zapisu kolektora' if storage_error else
                                 STATES.get(status, 'Odczyt źródła poprawny')),
                'storage_error': bool(storage_error), 'pending_writes': pending_writes,
                'dropped_snapshots': dropped_snapshots,
                'coverage': {'stored_reports': len(rows), 'unlocated_reports': sum(r['cell'] is None for r in rows),
                             'eligible_reports': sum(r['eligible'] for r in rows),
                             'unknown_provenance_reports': sum(r['epoch'] == 0 for r in rows),
                             'context_reports': sum(r['context'] for r in rows)},
                'observation_age_seconds': observation_age, 'source': source, 'age_seconds': age, 'synthetic': self.demo,
                'window_start': start, 'window_end': until, 'method': METHOD,
                'note': 'Pośrednia obserwacja jakości pozycji. Nie potwierdza jammingu ani spoofingu i nie jest '
                        'oficjalnym ostrzeżeniem. Komórka to obszar obserwacji, nie lokalizacja nadajnika. '
                        'Brak pozycji, mały ruch i błąd API nie tworzą anomalii. Historia tylko od uruchomienia kolektora.'}

    def seed_demo(self):
        now = self.repo.clock()
        # Entirely synthetic, same ingestion and aggregation path; no upstream calls or invented live history.
        for offset in range(90, 0, -1):
            at = now-timedelta(minutes=offset)
            ac = [{'hex': f'{i+1:06x}', 'type': 'adsb_icao', 'version': 2, 'lat': 52.7, 'lon': 20.1,
                   'seen_pos': 1, 'nic': 8, 'nac_p': 3 if offset <= 15 and i < 4 else 9}
                  for i in range(6)]
            self.ingest({'now': at.timestamp()*1000, 'ac': ac}, at)
