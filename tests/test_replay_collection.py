"""Deterministic collection from live-service shaped snapshots with no external IO."""
import asyncio
import sqlite3
from base64 import b64decode
from datetime import UTC, datetime

import pytest

from wici.flight_replay import FlightReplay
from wici.radar import RadarUnavailable
from wici.replay_capture import TILES
from wici.replay_collection import BACKOFF, MAX_ACTIVE, MAX_LIFETIME, UNSEEN_LIFETIME, ReplayCollection

START = 1740000000 + 480
ICAO = 'abcdef'
PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAaX2RUAAAAAASUVORK5CYII=')


class Clock:
    epoch = START

    def __call__(self):
        return datetime.fromtimestamp(self.epoch, UTC)


class Aircraft:
    def __init__(self, clock):
        self.clock = clock
        self.epoch = None
        self.name = 'TEST1'
        self.target = ICAO
        self.altitude = 1800
        self.stale = False
        self.fetches = 0

    async def fetch(self):
        self.fetches += 1
        epoch = self.clock.epoch if self.epoch is None else self.epoch
        item = {'hex': self.target, 'id': self.name, 'position_at': datetime.fromtimestamp(epoch, UTC).isoformat(),
                'latitude': 52.1, 'longitude': 20.9, 'altitude_m': self.altitude, 'track': 210}
        return {'status': 'ready', 'stale': self.stale, 'items': [item]}


class Radar:
    def __init__(self, clock):
        self.clock = clock
        self.stamps = [START - 480, START + 120]
        self.requests = []
        self.broken = False

    async def metadata(self):
        return {'status': 'success', 'frames': [{'timestamp': t} for t in self.stamps if t <= self.clock.epoch]}

    async def tile(self, stamp, z, x, y):
        self.requests.append((stamp, z, x, y))
        if self.broken and (x, y) == TILES[-1]:
            raise RadarUnavailable('test interruption')
        return PNG


class SteppedCollection(ReplayCollection):
    # Advance the same worker operation as the scheduler, without sleeping in tests.
    def _launch(self, icao):
        pass


def setup(directory, cls=SteppedCollection):
    clock = Clock()
    aircraft, radar = Aircraft(clock), Radar(clock)
    return cls(directory, aircraft, radar, clock), aircraft, radar, clock


async def test_resume_with_initial_scan_saved_even_after_provider_removes_it(tmp_path):
    collect, aircraft, radar, clock = setup(tmp_path)
    initial = await collect.start(ICAO.upper(), 'test1')
    assert await collect.start(ICAO) == initial
    for offset in (0, 60):
        clock.epoch = START + offset
        await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == 2
    assert collect.status(ICAO)['frames'] == 1
    await collect.close()
    radar.stamps = [START + 120]
    resumed = SteppedCollection(tmp_path, aircraft, radar, clock)
    await resumed.resume()
    assert resumed.status(ICAO)['started_at'] == initial['started_at']
    for offset in (120, 180, 240, 300):
        clock.epoch = START + offset
        await resumed._poll(ICAO)
    done = resumed.status(ICAO)
    assert done['status'] == 'ready' and done['points'] == 6 and done['frames'] == 2
    assert done['ended_at'] == done['updated_at'] == clock().isoformat()
    assert done['callsign'] == 'TEST1'
    saved = FlightReplay(tmp_path / 'aircraft' / ICAO, ICAO).load()
    assert saved.public['icao'] == ICAO and saved.public['callsign'] == 'TEST1'
    assert [p['time'] for p in saved.public['points']] == list(range(START, START + 301, 60))
    assert all(p['alt_m'] == 1800 for p in saved.public['points'])
    assert 'barometryczna' in saved.public['note'] and saved.public['flight_source'] == 'adsb.fi'
    assert [f['time'] for f in saved.public['frames']] == [START - 480, START + 120]
    assert len(radar.requests) == len(set(radar.requests)) == 2 * len(TILES)
    await resumed.close()
    checked = SteppedCollection(tmp_path, aircraft, radar, clock)
    await checked.resume()
    assert checked.status(ICAO) == done
    clock.epoch += 20
    fresh = await checked.start(ICAO, 'NEXT')
    assert fresh['started_at'] != done['started_at'] and fresh['points'] == 0
    assert FlightReplay(tmp_path / 'aircraft' / ICAO, ICAO).load().revision == saved.revision
    await checked.close()


async def test_watermark_boundaries_and_partial_frames(tmp_path):
    collect, aircraft, radar, clock = setup(tmp_path)
    await collect.start(ICAO, 'TEST1')
    radar.broken = True
    for offset in (-1, 1, 0, 0):  # pre-consent, future, accepted, duplicate
        aircraft.epoch = START + offset
        await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == 1 and collect.status(ICAO)['frames'] == 0
    assert collect.db.execute('SELECT count(*) FROM tiles').fetchone()[0] == 0
    radar.broken = False
    clock.epoch += BACKOFF
    aircraft.epoch = START + 30
    await collect._poll(ICAO)
    assert collect.status(ICAO)['frames'] == 1
    aircraft.epoch -= 10
    await collect._poll(ICAO)
    aircraft.epoch = clock.epoch
    aircraft.stale = True
    await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == 2
    aircraft.stale = False
    aircraft.name = 'OTHER'
    await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == collect.status(ICAO)['frames'] == 0
    aircraft.name = 'TEST1'
    aircraft.epoch -= 1
    await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == 0
    aircraft.epoch = None
    clock.epoch += 1
    await collect._poll(ICAO)
    clock.epoch += 120
    await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == 2
    clock.epoch += 121
    await collect._poll(ICAO)
    assert collect.status(ICAO)['points'] == 1
    assert collect.sessions[ICAO].points[0]['time'] == clock.epoch
    await collect.close()


async def test_unseen_targets_expire_offline_capacity_is_bounded_and_slots_reusable(tmp_path):
    collect, aircraft, radar, clock = setup(tmp_path)
    ids = [f'{i:06x}' for i in range(MAX_ACTIVE + 1)]
    for icao in ids[:-1]:
        assert (await collect.start(icao))['status'] == 'collecting'
    assert (await collect.start(ids[-1]))['status'] == 'error'
    await collect._poll(ids[0])
    assert collect.status(ids[0])['points'] == 0 and radar.requests == []
    assert 'nie ma' in collect.status(ids[0])['message']
    clock.epoch += UNSEEN_LIFETIME
    await collect._poll(ids[0])
    assert collect.status(ids[0])['status'] == 'expired' and aircraft.fetches == 1
    assert (await collect.start(ids[-1]))['status'] == 'collecting'
    await collect.close()


async def test_one_scan_cannot_publish_even_with_five_minutes_of_positions(tmp_path):
    collect, _, radar, clock = setup(tmp_path)
    radar.stamps = [START]
    await collect.start(ICAO)
    for offset in range(0, 301, 60):
        clock.epoch = START + offset
        await collect._poll(ICAO)
    assert collect.status(ICAO)['status'] == 'collecting' and collect.status(ICAO)['frames'] == 1
    clock.epoch = START + MAX_LIFETIME
    await collect._poll(ICAO)
    assert collect.status(ICAO)['status'] == 'expired'
    assert not (tmp_path / 'aircraft' / ICAO / 'episode.json').exists()
    await collect.close()


async def test_start_launches_background_worker_and_close_allows_resume(tmp_path):
    collect, aircraft, radar, clock = setup(tmp_path, ReplayCollection)
    await collect.start(ICAO)
    await asyncio.sleep(0)
    assert collect.status(ICAO)['points'] == 1
    await collect.close()
    assert not collect.tasks
    clock.epoch += 15
    restarted = ReplayCollection(tmp_path, aircraft, radar, clock)
    await restarted.resume()
    await asyncio.sleep(0)
    assert restarted.status(ICAO)['points'] == 2
    await restarted.close()


async def test_corrupt_progress_cannot_prevent_startup_or_hide_healthy_sessions(tmp_path):
    collect, aircraft, radar, clock = setup(tmp_path)
    await collect.start(ICAO)
    await collect.start('000000')
    await collect.close()
    database = tmp_path / 'collection.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute("UPDATE sessions SET data='{' WHERE icao=?", (ICAO,))
    resumed = SteppedCollection(tmp_path, aircraft, radar, clock)
    await resumed.resume()
    assert resumed.status(ICAO)['status'] == 'error'
    assert resumed.status('000000')['status'] == 'collecting'
    assert (await resumed.start(ICAO))['status'] == 'collecting'
    await resumed.close()
    database.write_bytes(b'corrupt')
    broken = ReplayCollection(tmp_path, aircraft, radar, clock)
    await broken.resume()
    assert not broken.tasks and (await broken.start(ICAO))['status'] == 'error'
    assert database.read_bytes() == b'corrupt'
    await broken.close()


async def test_publication_replays_idempotently_after_manifest_switch(tmp_path, monkeypatch):
    collect, aircraft, radar, clock = setup(tmp_path)
    await collect.start(ICAO)
    for offset in range(0, 300, 60):
        clock.epoch = START + offset
        await collect._poll(ICAO)

    def interrupted(*_args, **_kwargs):
        raise OSError('simulated interruption before terminal acknowledgement')

    monkeypatch.setattr(collect, '_finish', interrupted)
    clock.epoch += 60
    with pytest.raises(OSError, match='interruption'):
        await collect._poll(ICAO)
    assert collect.sessions[ICAO].state == 'publishing'
    store = FlightReplay(tmp_path / 'aircraft' / ICAO, ICAO)
    revision = store.load().revision
    await collect.close()
    fetches, requests = aircraft.fetches, len(radar.requests)
    clock.epoch += MAX_LIFETIME
    restarted = SteppedCollection(tmp_path, aircraft, radar, clock)
    await restarted.resume()
    await restarted._poll(ICAO)
    assert restarted.status(ICAO)['status'] == 'ready'
    assert revision == store.load().revision
    assert fetches == aircraft.fetches and requests == len(radar.requests)
    await restarted.close()
