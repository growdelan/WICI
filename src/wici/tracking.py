"""Explicit, durable observation tracks, independent of browser/layer visibility."""
import asyncio
import logging
import math
import re
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

REFRESH_SECONDS = 10
RETENTION_DAYS = 7
MAX_ACTIVE = 20
MAX_AGE = {'aircraft': 120, 'ship': 900}
# Conservative plausibility ceilings, not estimated speeds or route reconstruction.
MAX_SPEED = {'aircraft': 1800, 'ship': 160}


class TrackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['aircraft', 'ship']
    object_id: str = Field(min_length=1, max_length=16)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def finite(value, low, high):
    return (value if isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high else None)


def distance_km(a, b):
    lat1, lat2 = math.radians(a['latitude']), math.radians(b['latitude'])
    dlat, dlon = lat2-lat1, math.radians(b['longitude']-a['longitude'])
    hav = math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 12742*math.asin(math.sqrt(min(1, max(0, hav))))


class TrackingService:
    def __init__(self, repo, aircraft, ships, *, demo=False, interval_seconds=REFRESH_SECONDS):
        self.repo, self.demo = repo, demo
        self.services = {'aircraft': aircraft, 'ship': ships}
        self.interval_seconds = interval_seconds
        self.task = None
        self.workers = set()
        self.storage_error = False
        self.operations = asyncio.Lock()
        self.wake = asyncio.Event()
        self.prune()
        # A new process cannot claim continuous observation over its downtime.
        with repo.lock, repo.db:
            repo.db.execute("""UPDATE object_tracks SET pending_break=1, status='waiting',
                message='Wznowiono zapis. Oczekiwanie na nową pozycję.' WHERE active=1""")

    def start(self):
        if not self.demo and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self.run(), name='wici-object-tracks')

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        # Cancelling asyncio.to_thread does not cancel its database work. Drain it
        # before the application closes the shared repository connection.
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)

    async def storage(self, operation, *args):
        worker = asyncio.create_task(asyncio.to_thread(operation, *args))
        self.workers.add(worker)
        worker.add_done_callback(self.workers.discard)
        return await asyncio.shield(worker)

    def prune(self):
        cutoff = (self.repo.clock().astimezone(UTC)-timedelta(days=RETENTION_DAYS)).isoformat()
        with self.repo.lock, self.repo.db:
            self.repo.db.execute('DELETE FROM object_track_points WHERE recorded_at < ?', (cutoff,))
            self.repo.db.execute('DELETE FROM object_tracks WHERE active=0 AND stopped_at < ?', (cutoff,))

    def active(self):
        with self.repo.lock:
            return [dict(row) for row in self.repo.db.execute('SELECT * FROM object_tracks WHERE active=1')]

    def _summary(self, row):
        value = dict(row)
        value['active'] = bool(value['active'])
        value['military'] = (bool(value['military'])
                             if value['kind'] == 'aircraft' and value['military'] is not None else None)
        value['ship_type_code'] = value['ship_type_code'] if value['kind'] == 'ship' else None
        value.pop('pending_break', None)
        last = timestamp(value['last_position_at'])
        if (value['active'] and last and value['status'] == 'live'
                and (self.repo.clock().astimezone(UTC)-last).total_seconds() > MAX_AGE[value['kind']]):
            value.update(status='stale', message='Brak świeżej pozycji. Zapis nadal czeka na dane.')
        if value['active'] and self.storage_error:
            value.update(status='stale', message='Nie udało się zapisać pozycji. Ponawianie zapisu.')
        return value

    @staticmethod
    def _summary_query():
        return """SELECT t.*, COUNT(p.position_at) AS point_count, MAX(p.position_at) AS last_position_at
            FROM object_tracks t LEFT JOIN object_track_points p ON p.track_id=t.id"""

    def listing(self):
        self.prune()
        with self.repo.lock:
            rows = self.repo.db.execute(self._summary_query()+"""
                GROUP BY t.id ORDER BY t.active DESC, t.started_at DESC, t.id""")
            return {'items': [self._summary(row) for row in rows], 'retention_days': RETENTION_DAYS,
                    'refresh_seconds': REFRESH_SECONDS, 'max_active': MAX_ACTIVE}

    def detail(self, track_id):
        self.prune()
        with self.repo.lock:
            row = self.repo.db.execute(self._summary_query()+' WHERE t.id=? GROUP BY t.id',
                                       (track_id,)).fetchone()
            if row is None:
                raise KeyError(track_id)
            points = [dict(point) for point in self.repo.db.execute("""SELECT position_at, latitude,
                longitude, altitude_m, speed_kmh, heading, break_before FROM object_track_points
                WHERE track_id=? ORDER BY position_at""", (track_id,))]
            for point in points:
                point['break_before'] = bool(point['break_before'])
            if points:
                points[0]['break_before'] = True
            return {'track': self._summary(row), 'points': points, 'retention_days': RETENTION_DAYS,
                    'refresh_seconds': REFRESH_SECONDS}

    def point(self, kind, item, now):
        at = timestamp(item.get('position_at'))
        lat, lon = finite(item.get('latitude'), -90, 90), finite(item.get('longitude'), -180, 180)
        if at is None or lat is None or lon is None or not 0 <= (now-at).total_seconds() <= MAX_AGE[kind]:
            return None
        speed = item.get('speed_kmh')
        if kind == 'ship':
            knots = finite(item.get('speed_knots'), 0, 102.2)
            speed = knots*1.852 if knots is not None else None
        heading = item.get('track') if kind == 'aircraft' else item.get('heading')
        if finite(heading, 0, 360) is None and kind == 'ship':
            heading = item.get('course')
        return {'position_at': at.isoformat(), 'latitude': lat, 'longitude': lon,
                'altitude_m': finite(item.get('altitude_m'), -1000, 40000) if kind == 'aircraft' else None,
                'speed_kmh': finite(speed, 0, 6000), 'heading': finite(heading, 0, 360)}

    @staticmethod
    def label(kind, item, object_id):
        value = (item.get('id') or item.get('registration')) if kind == 'aircraft' else item.get('name')
        return value[:128] if isinstance(value, str) and value.strip() else object_id

    @staticmethod
    def military(kind, item):
        value = item.get('military')
        return value if kind == 'aircraft' and isinstance(value, bool) else None

    @staticmethod
    def ship_type_code(kind, item):
        value = item.get('type_code')
        if (kind == 'ship' and isinstance(value, (int, float)) and not isinstance(value, bool)
                and 1 <= value <= 99 and int(value) == value):
            return int(value)
        return None

    def ingest(self, kind, snapshot):
        now = self.repo.clock().astimezone(UTC)
        field = 'hex' if kind == 'aircraft' else 'mmsi'
        items = {str(item.get(field)): item for item in snapshot.get('items', []) if isinstance(item, dict)}
        with self.repo.lock, self.repo.db:
            tracks = self.repo.db.execute('SELECT * FROM object_tracks WHERE kind=? AND active=1', (kind,)).fetchall()
            for track in tracks:
                item = items.get(track['object_id'])
                point = self.point(kind, item, now) if item else None
                unavailable = snapshot.get('status') == 'disabled' or snapshot.get('demo')
                stale = snapshot.get('stale') or snapshot.get('status') == 'error'
                if unavailable or stale or point is None:
                    status = 'disabled' if unavailable else 'stale' if stale else 'waiting'
                    message = ('Źródło wyłączone lub nieskonfigurowane. Zapis czeka na dane.' if unavailable
                               else 'Źródło chwilowo niedostępne. Zapis czeka na świeże dane.' if stale
                               else 'Brak obiektu w bieżących danych. Zapis czeka na kolejną pozycję.')
                    self.repo.db.execute("""UPDATE object_tracks SET status=?, message=?, pending_break=1
                        WHERE id=?""", (status, message, track['id']))
                    continue
                previous = self.repo.db.execute("""SELECT * FROM object_track_points WHERE track_id=?
                    ORDER BY position_at DESC LIMIT 1""", (track['id'],)).fetchone()
                # Classification can arrive independently of a new position, including
                # for sessions created before the classification field existed.
                self.repo.db.execute("""UPDATE object_tracks SET status='live', message='', label=?,
                    military=COALESCE(?, military), ship_type_code=COALESCE(?, ship_type_code) WHERE id=?""",
                    (self.label(kind, item, track['object_id']), self.military(kind, item),
                     self.ship_type_code(kind, item), track['id']))
                if previous:
                    elapsed = (timestamp(point['position_at'])-timestamp(previous['position_at'])).total_seconds()
                    # Duplicate/out-of-order reports and sub-interval sampling never grow the archive.
                    if elapsed <= 0 or (now-timestamp(previous['recorded_at'])).total_seconds() < REFRESH_SECONDS:
                        continue
                    gap = (track['pending_break'] or elapsed > MAX_AGE[kind]
                           or distance_km(previous, point) > MAX_SPEED[kind]*elapsed/3600 + .5)
                else:
                    gap = True
                self.repo.db.execute("""INSERT OR IGNORE INTO object_track_points VALUES(?,?,?,?,?,?,?,?,?)""",
                    (track['id'], point['position_at'], point['latitude'], point['longitude'], point['altitude_m'],
                     point['speed_kmh'], point['heading'], int(bool(gap)), now.isoformat()))
                self.repo.db.execute('UPDATE object_tracks SET pending_break=0 WHERE id=?', (track['id'],))

    async def begin(self, kind, object_id):
        if self.demo:
            raise ValueError('Zapis tras jest niedostępny w demonstracji.')
        if kind not in self.services:
            raise ValueError('Nieprawidłowy rodzaj obiektu.')
        object_id = object_id.lower()
        pattern = r'~?[0-9a-f]{6}' if kind == 'aircraft' else r'[1-9][0-9]{8}'
        if not re.fullmatch(pattern, object_id):
            raise ValueError('Nieprawidłowy identyfikator obiektu.')
        async with self.operations:
            with self.repo.lock:
                existing = self.repo.db.execute("""SELECT id FROM object_tracks
                    WHERE kind=? AND object_id=? AND active=1""", (kind, object_id)).fetchone()
                count = self.repo.db.execute('SELECT COUNT(*) FROM object_tracks WHERE active=1').fetchone()[0]
                if not existing and count >= MAX_ACTIVE:
                    raise ValueError('Można zapisywać jednocześnie maksymalnie 20 obiektów. Zatrzymaj jeden z zapisów.')
            if existing:
                return await self.storage(self.detail, existing['id'])
            snapshot = await self.services[kind].fetch()
            if snapshot.get('status') == 'disabled' or snapshot.get('demo'):
                raise ValueError('Źródło danych jest wyłączone lub nieskonfigurowane.')
            field = 'hex' if kind == 'aircraft' else 'mmsi'
            item = next((item for item in snapshot.get('items', []) if str(item.get(field)) == object_id), None)
            if item is None or self.point(kind, item, self.repo.clock().astimezone(UTC)) is None:
                raise ValueError('Obiekt nie ma aktualnej pozycji. Odśwież mapę i wybierz go ponownie.')
            track_id = uuid4().hex
            with self.repo.lock, self.repo.db:
                self.repo.db.execute("""INSERT INTO object_tracks
                    (id,kind,object_id,label,active,started_at,status,military,ship_type_code)
                    VALUES(?,?,?,?,1,?,'waiting',?,?)""",
                    (track_id, kind, object_id, self.label(kind, item, object_id),
                     self.repo.clock().astimezone(UTC).isoformat(), self.military(kind, item),
                     self.ship_type_code(kind, item)))
            await self.storage(self.ingest, kind, snapshot)
            self.wake.set()
            return await self.storage(self.detail, track_id)

    async def stop(self, track_id):
        async with self.operations:
            with self.repo.lock, self.repo.db:
                row = self.repo.db.execute('SELECT active FROM object_tracks WHERE id=?', (track_id,)).fetchone()
                if row is None:
                    raise KeyError(track_id)
                if row['active']:
                    self.repo.db.execute("""UPDATE object_tracks SET active=0, stopped_at=?, status='stopped',
                        message='Zapis zatrzymany. Dostępne są pozycje z ostatnich 7 dni.' WHERE id=?""",
                        (self.repo.clock().astimezone(UTC).isoformat(), track_id))
            return await self.storage(self.detail, track_id)

    async def collect_once(self):
        if self.demo:
            return
        async with self.operations:
            await self.storage(self.prune)
            kinds = {track['kind'] for track in await self.storage(self.active)}

            async def collect(kind):
                try:
                    snapshot = await self.services[kind].fetch()
                except Exception:
                    logging.getLogger('wici').exception('Track source fetch failed: %s', kind)
                    snapshot = {'items': [], 'status': 'error', 'stale': True}
                await self.storage(self.ingest, kind, snapshot)

            await asyncio.gather(*(collect(kind) for kind in kinds))

    async def run(self):
        while True:
            self.wake.clear()
            try:
                await self.collect_once()
            except Exception:
                self.storage_error = True
                logging.getLogger('wici').exception('Track collection failed; retrying')
            else:
                self.storage_error = False
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=self.interval_seconds)
