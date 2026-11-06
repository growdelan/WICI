"""Durably record a selected aircraft and its matching real radar frames."""
import asyncio
import json
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx

from wici.aircraft import MAX_POSITION_AGE
from wici.flight_replay import Position
from wici.radar import RadarUnavailable
from wici.replay_capture import MAX_GAP, MIN_DURATION, TILES, Z, describe, frame_at, numeric, publish

MAX_ACTIVE = 4
MAX_TERMINAL = 32
MAX_LIFETIME = 30 * 60
UNSEEN_LIFETIME = 10 * 60
POLL = 15
BACKOFF = 60
ACTIVE = {'collecting', 'publishing'}
STORE_ERROR = 'Nie można odczytać lub zapisać lokalnego postępu nagrania.'
log = logging.getLogger('wici')


def utc(epoch):
    return datetime.fromtimestamp(epoch, UTC).isoformat()


@dataclass
class Session:
    icao: str
    requested: str
    started: float
    updated: float
    callsign: str = ''
    state: str = 'collecting'
    message: str = 'Czekam na nowe pozycje wybranego samolotu.'
    high_water: float = 0
    seen: bool = False
    points: list = field(default_factory=list)
    frames: list = field(default_factory=list)

    def public(self):
        result = {'icao': self.icao, 'callsign': self.requested or self.callsign,
                  'status': 'collecting' if self.state in ACTIVE else self.state, 'message': self.message,
                  'points': len(self.points), 'frames': len(self.frames),
                  'started_at': utc(self.started), 'updated_at': utc(self.updated)}
        if self.state not in ACTIVE:
            result['ended_at'] = utc(self.updated)
        return result


class ReplayCollection:
    def __init__(self, directory, aircraft, radar, clock):
        self.directory, self.aircraft, self.radar, self.clock = Path(directory), aircraft, radar, clock
        self.database = self.directory / 'collection.sqlite3'
        self.db = None
        self.sessions = {}
        self.tasks = {}
        self.radar_retry = {}

    def _open(self):
        if self.db is not None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=1)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (icao TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS tiles (
                icao TEXT, time INTEGER, x INTEGER, y INTEGER, png BLOB NOT NULL, PRIMARY KEY (icao,time,x,y))''')
            sessions = {}
            for icao, raw in db.execute('SELECT icao,data FROM sessions'):
                if not isinstance(icao, str) or not re.fullmatch('[a-f0-9]{6}', icao):
                    continue
                try:
                    job = Session(**json.loads(raw))
                    if job.icao != icao or job.state not in ACTIVE | {'ready', 'expired', 'error'}:
                        raise ValueError('Nieprawidłowy stan sesji.')
                    if not isinstance(job.points, list) or not isinstance(job.frames, list):
                        raise TypeError('Nieprawidłowy postęp sesji.')
                    for p in job.points:
                        Position.model_validate(p)
                    if not all(type(t) is int and t > 0 for t in job.frames):
                        raise ValueError('Nieprawidłowe czasy radaru.')
                    job.public()  # Also validate the persisted dates before exposing the job.
                except (TypeError, ValueError, OverflowError, OSError):
                    log.warning('Invalid flight replay collection record for %s', icao)
                    now = self.clock().timestamp()
                    job = Session(icao, '', now, now, state='error', message=STORE_ERROR)
                sessions[icao] = job
        except sqlite3.Error:
            db.close()
            raise
        self.db, self.sessions = db, sessions

    def _save(self, session, *, clear=False, tiles=()):
        # A frame is visible in progress only once all its tiles survive a restart.
        with self.db:
            if clear:
                self.db.execute('DELETE FROM tiles WHERE icao=?', (session.icao,))
            self.db.executemany('INSERT INTO tiles VALUES (?,?,?,?,?)', tiles)
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)',
                            (session.icao, json.dumps(asdict(session), ensure_ascii=False)))
        self.sessions[session.icao] = session
        return session

    def _finish(self, session, state, message):
        result = self._save(replace(session, state=state, message=message,
                                    updated=self.clock().timestamp()), clear=True)
        self.radar_retry.pop(session.icao, None)
        terminal = sorted((s for s in self.sessions.values() if s.state not in ACTIVE), key=lambda s: s.updated)
        for old in terminal[:-MAX_TERMINAL]:
            with self.db:
                self.db.execute('DELETE FROM sessions WHERE icao=?', (old.icao,))
            del self.sessions[old.icao]
        return result

    def status(self, icao):
        session = self.sessions.get(icao.lower())
        return session.public() if session else None

    def _launch(self, icao):
        if icao not in self.tasks or self.tasks[icao].done():
            self.tasks[icao] = asyncio.create_task(self._run(icao))

    async def resume(self):
        if self.database.is_file():
            try:
                self._open()
            except (sqlite3.Error, OSError):
                log.exception('Cannot resume local flight replay collection')
                return
            for session in list(self.sessions.values()):
                if session.state in ACTIVE:
                    self._launch(session.icao)

    async def start(self, icao, callsign=''):
        icao, callsign = icao.lower(), callsign.strip().upper()
        if not re.fullmatch(r'[a-f0-9]{6}', icao) or len(callsign) > 32 or any(ord(c) < 32 for c in callsign):
            raise ValueError('Nieprawidłowy identyfikator lotu.')
        now = self.clock().timestamp()
        job = Session(icao, callsign, now, now)
        try:
            self._open()
        except (sqlite3.Error, OSError):
            return replace(job, state='error', message=STORE_ERROR).public()
        current = self.sessions.get(icao)
        if current and current.state in ACTIVE:
            return current.public()
        if sum(s.state in ACTIVE for s in self.sessions.values()) >= MAX_ACTIVE:
            return replace(job, state='error', message='Trwa już zbieranie czterech samolotów.').public()
        try:
            self._save(job, clear=True)
        except (sqlite3.Error, OSError):
            return replace(job, state='error', message=STORE_ERROR).public()
        self._launch(icao)
        return job.public()

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        if self.db is not None:
            self.db.close()
            self.db = None

    async def _run(self, icao):
        try:
            while self.sessions[icao].state in ACTIVE:
                delay = await self._poll(icao)
                if self.sessions[icao].state in ACTIVE:
                    await asyncio.sleep(delay)
        except Exception:
            log.exception('Flight replay collection failed for %s', icao)
            session = self.sessions[icao]
            try:
                self._finish(session, 'error', 'Nie udało się zapisać odcinka. Możesz rozpocząć ponownie.')
            except (sqlite3.Error, OSError):
                self.sessions[icao] = replace(session, state='error', message=STORE_ERROR,
                                              updated=self.clock().timestamp())
        finally:
            self.tasks.pop(icao, None)

    def _observe(self, session, item, now):
        observed = datetime.fromisoformat(item['position_at'])
        if observed.tzinfo is None:
            return session
        exact = observed.timestamp()
        if (exact < session.started or exact <= session.high_water or not 0 <= now - exact <= MAX_POSITION_AGE):
            return session
        # Advance the watermark even across callsign boundaries and unusable altitude reports.
        name = (item.get('id') or '').strip().upper()
        updated = replace(session, updated=now, high_water=exact)
        points = session.points
        epoch = int(exact)
        matches = (not session.requested or name == session.requested)
        boundary = (not matches or name != session.callsign or
                    bool(points and epoch - points[-1]['time'] > MAX_GAP))
        if boundary:
            updated = replace(updated, callsign=name, points=[], frames=[])
            points = []
        altitude = item.get('altitude_m')
        if (matches and numeric(altitude) and -500 <= altitude <= 30000
                and (not points or epoch > points[-1]['time'])):
            point = {'time': epoch, 'lat': item['latitude'], 'lon': item['longitude'], 'alt_m': altitude}
            if item.get('track') is not None:
                point['heading'] = item['track']
            updated = replace(updated, points=[*points, point], seen=True)
        return self._save(updated, clear=boundary)

    async def _radar(self, session):
        manifest = await self.radar.metadata()
        if manifest['status'] != 'success' or manifest.get('stale'):
            raise RadarUnavailable('Brak aktualnego manifestu radaru.')
        available = sorted(f['timestamp'] for f in manifest['frames'])
        needed = {frame_at(available, p['time']) for p in session.points} - {None, *session.frames}
        for stamp in sorted(needed):
            tiles = [(session.icao, stamp, x, y, await self.radar.tile(stamp, Z, x, y)) for x, y in TILES]
            session = self._save(replace(session, frames=sorted([*session.frames, stamp]),
                                         updated=self.clock().timestamp()), tiles=tiles)
        return session

    @staticmethod
    def _covered(session):
        start = 0
        for i, point in enumerate(session.points):
            stamp = frame_at(session.frames, point['time'])
            if stamp is None:
                start = i + 1
                continue
            first = session.points[start]['time']
            if point['time'] - first >= MIN_DURATION and stamp != frame_at(session.frames, first):
                points = session.points[start:i + 1]
                return points, sorted({frame_at(session.frames, p['time']) for p in points})
        return None

    async def _publish(self, session, points, frames):
        # Persist the exact selection before the atomic manifest switch. A crash can
        # repeat publication from the same durable bytes without contacting sources.
        session = self._save(replace(session, state='publishing', points=points, frames=frames,
                                     updated=self.clock().timestamp()))
        metadata = describe(session.callsign, session.icao, points)
        metadata.update(callsign=session.callsign, flight_source='adsb.fi', flight_source_url='https://adsb.fi/',
                        note='Wysokość barometryczna ADS-B w metrach, kurs nad ziemią. '
                             'Czas radaru oznacza utworzenie kompozytu. Przezroczystość oznacza brak '
                             'echa lub brak pokrycia. Radar nie określa wysokości opadów.')
        rows = self.db.execute('SELECT time,x,y,png FROM tiles WHERE icao=?', (session.icao,))
        images = {(t, Z, x, y): png for t, x, y, png in rows if t in frames}
        if set(images) != {(t, Z, x, y) for t in frames for x, y in TILES}:
            raise ValueError('Brak kompletu zapisanych kafli radaru.')
        destination = self.directory / 'aircraft' / session.icao
        write = asyncio.create_task(asyncio.to_thread(publish, destination, metadata, images))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            await write
            self._finish(session, 'ready', 'Zapisano odcinek lotu z radarem.')
            raise
        self._finish(session, 'ready', 'Zapisano odcinek lotu z radarem.')

    async def _poll(self, icao):
        session = self.sessions[icao]
        if session.state not in ACTIVE:
            return POLL
        covered = self._covered(session)
        if covered:
            await self._publish(session, *covered)
            return POLL
        now = self.clock().timestamp()
        age = now - session.started
        if age >= MAX_LIFETIME or (not session.seen and age >= UNSEEN_LIFETIME):
            message = ('Przez 10 minut nie otrzymano pozycji wybranego lotu z wysokością.' if not session.seen
                       else 'Upłynęło 30 minut. Brak ciągłego odcinka z dwiema klatkami radaru.')
            self._finish(session, 'expired', message)
            return POLL
        delay = POLL
        message = ''
        try:
            aircraft = await self.aircraft.fetch()
            if aircraft['status'] != 'ready' or aircraft.get('stale') or aircraft.get('demo'):
                delay = BACKOFF
            else:
                item = next((i for i in aircraft['items'] if i['hex'] == icao), None)
                if item:
                    previous_points = session.points
                    session = self._observe(session, item, self.clock().timestamp())
                    if not session.points or session.points is previous_points:
                        message = 'Czekam na nowy raport wybranego lotu z pozycją i wysokością.'
                else:
                    message = 'Samolotu nie ma w ostatnim raporcie nad Polską. Czekam na jego pozycję.'
        except (httpx.HTTPError, TimeoutError):
            delay = BACKOFF
        if delay == BACKOFF:
            message = 'Źródło ADS-B jest chwilowo niedostępne. Ponowię sprawdzenie.'
        if session.points and now >= self.radar_retry.get(icao, 0):
            try:
                async with asyncio.timeout(30):
                    await self._radar(session)
            except (httpx.HTTPError, RadarUnavailable, ValueError, TimeoutError):
                self.radar_retry[icao] = now + BACKOFF
        session = self.sessions[icao]
        covered = self._covered(session)
        if covered:
            await self._publish(session, *covered)
        else:
            if not message and session.points:
                message = ('Czekam na odpowiadającą pozycjom klatkę radaru.' if
                           now < self.radar_retry.get(icao, 0) or not session.frames
                           else 'Zbieram pozycje samolotu i odpowiadające im klatki radaru.')
            if message and message != session.message:
                self._save(replace(session, message=message, updated=self.clock().timestamp()))
        return delay
