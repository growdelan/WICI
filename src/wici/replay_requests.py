"""Coordinate UI lookups and explicit recordings for each selected aircraft."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from time import monotonic

import httpx
from fastapi import HTTPException

from wici.flight_replay import FlightReplay
from wici.radar import RadarUnavailable
from wici.replay_capture import NoReplayHistory, capture_recent, publish
from wici.replay_collection import ReplayCollection

log = logging.getLogger('wici')
RETRY_WINDOW = 30
MAX_LOOKUPS = 2
MAX_RESULTS = 64


@dataclass
class Lookup:
    callsign: str
    task: asyncio.Task | None = None
    result: dict | None = None
    completed: float = 0


def response(icao, status, message, **fields):
    return {'icao': icao, 'status': status, 'message': message, **fields}


class ReplayRequests:
    def __init__(self, directory, client, aircraft, radar, clock):
        self.directory, self.client, self.aircraft, self.radar = directory, client, aircraft, radar
        self.clock = clock
        self.collection = ReplayCollection(directory, aircraft, radar, clock)
        self.store = lru_cache(maxsize=16)(self._store)
        self.jobs = {}
        self.gate = asyncio.Lock()

    def _store(self, icao):
        return FlightReplay(self.directory / 'aircraft' / icao, icao)

    async def resume(self):
        if self.aircraft.enabled and self.radar.enabled:
            await self.collection.resume()

    async def close(self):
        tasks = [job.task for job in self.jobs.values() if job.task and not job.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.collection.close()

    def _saved(self, icao, callsign):
        try:
            snapshot = self.store(icao).load()
        except HTTPException:
            return None
        return snapshot if not callsign or snapshot.public.get('callsign') == callsign else None

    @staticmethod
    def _url(icao, snapshot):
        return f'/api/flight-replay/aircraft/{icao}/episode?revision={snapshot.revision}'

    def _with_saved(self, icao, callsign, result):
        snapshot = self._saved(icao, callsign)
        if snapshot:
            return {**result, 'saved_episode_url': self._url(icao, snapshot),
                    'saved_label': snapshot.public['label'], 'saved_end': snapshot.public['points'][-1]['time']}
        return result

    def _ready(self, icao, snapshot):
        data = snapshot.public
        return response(icao, 'ready', 'Odcinek lotu z radarem jest gotowy.',
                        callsign=data.get('callsign', ''), points=len(data['points']), frames=len(data['frames']),
                        start=data['points'][0]['time'], end=data['points'][-1]['time'], episode_url=self._url(icao, snapshot))

    def _collection_result(self, icao, callsign, result):
        if callsign and result.get('callsign') and callsign != result['callsign']:
            return response(icao, 'unavailable', 'Na tej maszynie wybrano już inny znak wywoławczy.')
        if result['status'] == 'ready':
            snapshot = self._saved(icao, callsign or result.get('callsign'))
            if snapshot:
                return {**result, **self._ready(icao, snapshot)}
            return response(icao, 'unavailable', 'Zapisany odcinek jest już niedostępny. Wyszukaj go ponownie.')
        return result

    def _in_progress(self, icao, callsign):
        current = self.collection.status(icao)
        if current and current['status'] == 'collecting':
            return self._collection_result(icao, callsign, current)
        job = self.jobs.get(icao)
        if job and job.result is None:
            if callsign and callsign != job.callsign:
                return response(icao, 'unavailable', 'Trwa sprawdzanie innego wyboru dla tej maszyny. Spróbuj ponownie za chwilę.')
            return response(icao, 'preparing', 'Sprawdzam pozycje samolotu i odpowiadające im klatki radaru.', callsign=job.callsign)
        return None

    def _disabled(self, icao, callsign):
        if self.aircraft.enabled and self.radar.enabled:
            return None
        return self._with_saved(icao, callsign, response(icao, 'unavailable',
            'Przygotowanie odcinka wymaga włączenia źródeł Samoloty i Radar w konfiguracji WICI.'))

    async def prepare(self, icao, callsign):
        async with self.gate:
            state = self._disabled(icao, callsign) or self._in_progress(icao, callsign)
            if state:
                return state
            job = self.jobs.get(icao)
            if (job and job.callsign == callsign and job.result['status'] == 'ready'
                    and monotonic() - job.completed < RETRY_WINDOW):
                return job.result
            if sum(j.result is None for j in self.jobs.values()) >= MAX_LOOKUPS:
                return response(icao, 'unavailable', 'Trwają dwa wyszukiwania. Spróbuj ponownie za chwilę.')
            if len(self.jobs) >= MAX_RESULTS:
                oldest = min((k for k, j in self.jobs.items() if j.result), key=lambda k: self.jobs[k].completed)
                del self.jobs[oldest]
            job = self.jobs[icao] = Lookup(callsign)
            job.task = asyncio.create_task(self._lookup(icao, job))
            return response(icao, 'preparing', 'Sprawdzam historię samolotu i czas radaru.', callsign=callsign)

    async def _lookup(self, icao, job):
        try:
            metadata, images = await capture_recent(self.client, self.radar, icao, job.callsign)
            store = self.store(icao)
            saved = self._saved(icao, job.callsign)
            if not saved or metadata['points'][-1]['time'] > saved.public['points'][-1]['time']:
                # Publishing is atomic. Finish a running disk write before releasing the instance lock.
                write = asyncio.create_task(asyncio.to_thread(publish, store.directory, metadata, images))
                try:
                    await asyncio.shield(write)
                except asyncio.CancelledError:
                    await write
                    raise
                saved = store.load()
            result = self._ready(icao, saved)
        except NoReplayHistory as exc:
            result = self._with_saved(icao, job.callsign, response(icao, 'no_history', str(exc)))
        except (RadarUnavailable, TimeoutError, httpx.HTTPError, ValueError, OSError, HTTPException) as exc:
            log.warning('Replay lookup failed for %s (%s)', icao, type(exc).__name__)
            result = self._with_saved(icao, job.callsign, response(icao, 'unavailable',
                'Nie udało się pobrać lub zapisać danych lotu i radaru. Spróbuj ponownie.'))
        except Exception:
            # A failed background operation must always release its slot and end polling.
            log.exception('Unexpected replay lookup failure for %s', icao)
            result = response(icao, 'error', 'Przygotowanie odcinka zostało przerwane. Spróbuj ponownie.')
        job.result, job.completed = result, monotonic()

    async def collect(self, icao, callsign):
        async with self.gate:
            state = self._disabled(icao, callsign) or self._in_progress(icao, callsign)
            if state:
                return state
            last = self.collection.status(icao)
            if last and last['status'] == 'ready' and (not callsign or callsign == last.get('callsign')):
                ended = datetime.fromisoformat(last['ended_at'])
                if 0 <= (self.clock() - ended).total_seconds() < RETRY_WINDOW:
                    return self._collection_result(icao, callsign, last)
            result = await self.collection.start(icao, callsign)
            if result['status'] == 'collecting':
                self.jobs.pop(icao, None)
            return self._collection_result(icao, callsign, result)

    def status(self, icao, callsign):
        active = self._disabled(icao, callsign) or self._in_progress(icao, callsign)
        if active:
            return active
        job = self.jobs.get(icao)
        if job and (not callsign or job.callsign == callsign):
            return job.result
        current = self.collection.status(icao)
        if current and (not callsign or callsign == current.get('callsign')):
            return self._collection_result(icao, callsign, current)
        return self._with_saved(icao, callsign, response(icao, 'no_history',
            'Brak aktywnego wyszukiwania lub zbierania. Możesz ponownie sprawdzić historię.'))
