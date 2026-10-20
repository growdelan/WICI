"""Durable opt-in trajectories, measured gaps, bounded sampling and collection lifecycle."""
import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from wici.repository import Repository
from wici.tracking import MAX_ACTIVE, TrackingService

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


class Clock:
    now = NOW

    def __call__(self):
        return self.now

    def advance(self, seconds=10):
        self.now += timedelta(seconds=seconds)


def plane(clock, identity='48abcd', **extra):
    return {'hex': identity, 'id': 'LOT123', 'latitude': 52.0, 'longitude': 20.0,
            'position_at': clock().isoformat(), 'speed_kmh': 700, 'altitude_m': 10000,
            'track': 90, **extra}


def ship(clock, **extra):
    return {'mmsi': '261123456', 'name': 'BALTIC', 'latitude': 55.0, 'longitude': 19.0,
            'position_at': clock().isoformat(), 'speed_knots': 10, 'heading': 45, **extra}


class Source:
    def __init__(self, items=()):
        self.items, self.calls = list(items), 0
        self.status, self.stale = 'ready', False
        self.error = None

    async def fetch(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.snapshot()

    def snapshot(self):
        return {'items': self.items, 'status': self.status, 'stale': self.stale}


@pytest.fixture
def service(tmp_path):
    clock = Clock()
    repo = Repository(tmp_path/'app.sqlite3', clock=clock)
    aircraft, ships = Source([plane(clock)]), Source([ship(clock)])
    tracking = TrackingService(repo, aircraft, ships)
    yield tracking, clock, aircraft, ships
    repo.close()


async def start(tracking, kind='aircraft', identity='48abcd'):
    return (await tracking.begin(kind, identity))['track']['id']


async def test_only_explicit_objects_recorded_and_shared_source_once_per_poll(service):
    tracking, clock, aircraft, ships = service
    await tracking.collect_once()
    assert aircraft.calls == ships.calls == 0
    aircraft.items.append(plane(clock, identity='48abce'))
    first = await start(tracking)
    second = await start(tracking, identity='48abce')
    vessel = await start(tracking, 'ship', '261123456')
    aircraft.calls = ships.calls = 0
    clock.advance()
    aircraft.items = [plane(clock, identity='48abcd', longitude=20.01),
                      plane(clock, identity='48abce', longitude=20.01),
                      plane(clock, identity='48abcf')]
    ships.items = [ship(clock, longitude=19.001)]
    await tracking.collect_once()
    assert aircraft.calls == ships.calls == 1
    assert len(tracking.listing()['items']) == 3
    for track_id in (first, second, vessel):
        assert tracking.detail(track_id)['track']['point_count'] == 2
    assert tracking.detail(vessel)['points'][-1]['speed_kmh'] == 18.52


async def test_idempotent_start_stop_and_same_object_can_start_new_session(service):
    tracking, clock, aircraft, _ = service
    track_id = await start(tracking)
    again = await asyncio.wait_for(tracking.begin('aircraft', '48ABCD'), timeout=1)
    assert again['track']['id'] == track_id and aircraft.calls == 1
    stopped = await tracking.stop(track_id)
    assert stopped['track']['active'] is False and stopped['track']['status'] == 'stopped'
    assert stopped == await tracking.stop(track_id)
    clock.advance()
    aircraft.items = [plane(clock, longitude=20.01)]
    await tracking.collect_once()
    assert aircraft.calls == 1 and tracking.detail(track_id)['track']['point_count'] == 1
    new_id = await start(tracking)
    assert new_id != track_id and len(tracking.listing()['items']) == 2


async def test_no_duplicate_out_of_order_or_sub_interval_points(service):
    tracking, clock, aircraft, _ = service
    track_id = await start(tracking)
    clock.advance()
    await tracking.collect_once()  # Cached report.
    aircraft.items = [plane(clock, position_at=(NOW-timedelta(seconds=1)).isoformat())]
    await tracking.collect_once()
    assert tracking.detail(track_id)['track']['point_count'] == 1
    aircraft.items = [plane(clock, longitude=20.01)]
    await tracking.collect_once()
    clock.advance(1)
    aircraft.items = [plane(clock, longitude=20.02)]
    await tracking.collect_once()
    history = tracking.detail(track_id)
    assert history['track']['point_count'] == 2
    assert history['points'][-1]['longitude'] == 20.01
    assert history['points'][-1]['break_before'] is False


async def test_gaps_missing_source_error_and_implausible_jump_preserve_history(service):
    tracking, clock, aircraft, _ = service
    track_id = await start(tracking)
    for event in ('missing', 'error', 'jump', 'long_gap'):
        clock.advance()
        if event in ('missing', 'error'):
            aircraft.items = []
            aircraft.error = RuntimeError('synthetic source outage') if event == 'error' else None
            await tracking.collect_once()
            before = tracking.detail(track_id)
            assert before['track']['status'] in ('waiting', 'stale')
            aircraft.error = None
            clock.advance()
        elif event == 'long_gap':
            clock.advance(130)
        aircraft.items = [plane(clock, longitude=23 if event == 'jump' else 20)]
        await tracking.collect_once()
        assert tracking.detail(track_id)['points'][-1]['break_before'] is True
    assert tracking.detail(track_id)['track']['point_count'] == 5


async def test_slow_but_regular_ais_reports_still_form_route(service):
    tracking, clock, _, ships = service
    track_id = await start(tracking, 'ship', '261123456')
    for _ in range(18):
        clock.advance()
        await tracking.collect_once()
    ships.items = [ship(clock, longitude=19.002)]
    await tracking.collect_once()
    points = tracking.detail(track_id)['points']
    assert len(points) == 2 and points[-1]['break_before'] is False


async def test_aircraft_classification_updates_without_new_position_and_survives_missing_metadata(service):
    tracking, clock, aircraft, ships = service
    track_id = await start(tracking)
    initial = tracking.detail(track_id)
    assert initial['track']['military'] is None
    for military in (True, False, True):
        aircraft.items = [plane(clock, military=military)]
        await tracking.collect_once()
        detail = tracking.detail(track_id)
        assert detail['track']['military'] is military
        assert detail['points'] == initial['points'], 'Classification must not need a new position'
        assert tracking.listing()['items'][0]['military'] is military
    for extra in ({}, {'military': None}, {'military': 'false'}, {'military': 0}):
        aircraft.items = [plane(clock, **extra)]
        await tracking.collect_once()
        assert tracking.detail(track_id)['track']['military'] is True
    ships.items = [ship(clock, military=True)]
    vessel = await start(tracking, 'ship', '261123456')
    assert tracking.detail(vessel)['track']['military'] is None
    stopped = await tracking.stop(track_id)
    assert stopped['track']['military'] is True
    aircraft.items = [plane(clock, military=False)]
    await tracking.collect_once()
    assert tracking.detail(track_id)['track']['military'] is True


@pytest.mark.parametrize('military', [True, False, None])
async def test_aircraft_classification_persists_across_restart_and_stop(tmp_path, military):
    clock, path = Clock(), tmp_path/'classification.sqlite3'
    aircraft, ships = Source([plane(clock, military=military)]), Source()
    repo = Repository(path, clock=clock)
    tracking = TrackingService(repo, aircraft, ships)
    try:
        track_id = await start(tracking)
        expected = tracking.detail(track_id)
        assert expected['track']['military'] is military
    finally:
        repo.close()
    repo = Repository(path, clock=clock)
    resumed = TrackingService(repo, aircraft, ships)
    try:
        assert resumed.detail(track_id)['track']['military'] is military
        assert resumed.detail(track_id)['points'] == expected['points']
        aircraft.items = [plane(clock)]  # Missing metadata after restart must not clear a known flag.
        await resumed.collect_once()
        assert resumed.detail(track_id)['track']['military'] is military
        stopped = await resumed.stop(track_id)
        assert stopped['track']['military'] is military
    finally:
        repo.close()
    repo = Repository(path, clock=clock)
    try:
        history = TrackingService(repo, aircraft, ships).detail(track_id)
        assert history['track']['military'] is military
        assert history['track']['active'] is False
        assert history['points'] == expected['points']
    finally:
        repo.close()


async def test_ship_type_updates_without_new_position_and_survives_missing_metadata(service):
    tracking, clock, aircraft, ships = service
    track_id = await start(tracking, 'ship', '261123456')
    initial = tracking.detail(track_id)
    assert initial['track']['ship_type_code'] is None
    for type_code in (35, 70, 1, 99, 35.0):
        ships.items = [ship(clock, type_code=type_code)]
        await tracking.collect_once()
        detail = tracking.detail(track_id)
        assert detail['track']['ship_type_code'] == type_code
        assert type(detail['track']['ship_type_code']) is int
        assert detail['points'] == initial['points'], 'Static AIS data must not need a new position'
        assert tracking.listing()['items'][0]['ship_type_code'] == type_code
    for extra in ({}, {'type_code': None}, {'type_code': 0}, {'type_code': 100},
                  {'type_code': True}, {'type_code': '70'}, {'type_code': 35.5},
                  {'type_code': float('nan')}, {'type_code': float('inf')}):
        ships.items = [ship(clock, **extra)]
        await tracking.collect_once()
        assert tracking.detail(track_id)['track']['ship_type_code'] == 35
    aircraft.items = [plane(clock, type_code=35)]
    aircraft_id = await start(tracking)
    assert tracking.detail(aircraft_id)['track']['ship_type_code'] is None
    stopped = await tracking.stop(track_id)
    assert stopped['track']['ship_type_code'] == 35
    ships.items = [ship(clock, type_code=70)]
    await tracking.collect_once()
    assert tracking.detail(track_id)['track']['ship_type_code'] == 35


@pytest.mark.parametrize('type_code', [None, True, False, 0, -1, 100, 35.5, '35',
                                     float('nan'), float('inf'), float('-inf'), 10**400])
async def test_invalid_initial_ship_type_is_unknown(service, type_code):
    tracking, clock, _, ships = service
    ships.items = [ship(clock, type_code=type_code)]
    result = await tracking.begin('ship', '261123456')
    assert result['track']['ship_type_code'] is None
    assert result['track']['point_count'] == 1


@pytest.mark.parametrize(('type_code', 'expected_code'), [(35, 35), (70, 70), (35.0, 35),
                                                       (1, 1), (99, 99), (None, None)])
async def test_ship_type_persists_across_restart_and_stop(tmp_path, type_code, expected_code):
    clock, path = Clock(), tmp_path/'ship-type.sqlite3'
    aircraft, ships = Source(), Source([ship(clock, type_code=type_code)])
    repo = Repository(path, clock=clock)
    tracking = TrackingService(repo, aircraft, ships)
    try:
        track_id = await start(tracking, 'ship', '261123456')
        expected = tracking.detail(track_id)
        assert expected['track']['ship_type_code'] == expected_code
        assert expected['track']['military'] is None
    finally:
        repo.close()
    repo = Repository(path, clock=clock)
    resumed = TrackingService(repo, aircraft, ships)
    try:
        assert resumed.detail(track_id)['track']['ship_type_code'] == expected_code
        assert resumed.detail(track_id)['points'] == expected['points']
        ships.items = [ship(clock)]
        await resumed.collect_once()
        assert resumed.detail(track_id)['track']['ship_type_code'] == expected_code
        stopped = await resumed.stop(track_id)
        assert stopped['track']['ship_type_code'] == expected_code
    finally:
        repo.close()
    repo = Repository(path, clock=clock)
    try:
        history = TrackingService(repo, aircraft, ships).detail(track_id)
        assert history['track']['ship_type_code'] == expected_code
        assert history['track']['active'] is False
        assert history['points'] == expected['points']
    finally:
        repo.close()


async def test_invalid_coordinates_time_unknown_id_and_disabled_source_rejected(service):
    tracking, clock, aircraft, _ = service
    for identity in ('bad', '../../48abcd', '48abcd123'):
        with pytest.raises(ValueError):
            await start(tracking, identity=identity)
    with pytest.raises(ValueError):
        await start(tracking, identity='48abce')
    for item in (plane(clock, latitude=float('nan')), plane(clock, longitude=181),
                 plane(clock, position_at=(NOW+timedelta(seconds=1)).isoformat()),
                 plane(clock, position_at=(NOW-timedelta(seconds=121)).isoformat())):
        aircraft.items = [item]
        with pytest.raises(ValueError):
            await start(tracking)
    aircraft.items = [plane(clock)]
    aircraft.status = 'disabled'
    with pytest.raises(ValueError):
        await start(tracking)
    assert not tracking.listing()['items']


async def test_active_limit_and_demo_never_fetch(service):
    tracking, clock, aircraft, _ = service
    tracking.demo = True
    tracking.start()
    await tracking.collect_once()
    with pytest.raises(ValueError):
        await start(tracking)
    assert tracking.task is None and aircraft.calls == 0
    tracking.demo = False
    aircraft.items = [plane(clock, identity=f'{i:06x}') for i in range(MAX_ACTIVE+1)]
    for i in range(MAX_ACTIVE):
        await start(tracking, identity=f'{i:06x}')
    with pytest.raises(ValueError, match='20'):
        await start(tracking, identity=f'{MAX_ACTIVE:06x}')


async def test_background_continues_without_browser_then_restart_and_stop(tmp_path):
    clock, filename = Clock(), tmp_path/'tracks.sqlite3'
    aircraft, ships = Source([plane(clock)]), Source()
    repo = Repository(filename, clock=clock)
    tracking = TrackingService(repo, aircraft, ships, interval_seconds=.01)
    track_id = await start(tracking)
    clock.advance()
    aircraft.items = [plane(clock, longitude=20.01)]
    tracking.start()
    try:
        for _ in range(100):
            if tracking.detail(track_id)['track']['point_count'] == 2:
                break
            await asyncio.sleep(.01)
        assert tracking.detail(track_id)['track']['point_count'] == 2
    finally:
        await tracking.close()
        repo.close()
    repo = Repository(filename, clock=clock)
    resumed = TrackingService(repo, aircraft, ships)
    try:
        assert resumed.listing()['items'][0]['active']
        clock.advance()
        aircraft.items = [plane(clock, longitude=20.02)]
        await resumed.collect_once()
        detail = resumed.detail(track_id)
        assert len(detail['points']) == 3 and detail['points'][-1]['break_before']
        await resumed.stop(track_id)
        count = aircraft.calls
        await resumed.collect_once()
        assert aircraft.calls == count
    finally:
        repo.close()


async def test_retention_removes_old_points_and_stopped_sessions_but_keeps_active(service):
    tracking, clock, aircraft, _ = service
    stopped = await start(tracking)
    await tracking.stop(stopped)
    active = await start(tracking)
    clock.advance(7*86400+1)
    aircraft.items = [plane(clock)]
    await tracking.collect_once()
    listing = tracking.listing()
    assert [row['id'] for row in listing['items']] == [active]
    assert tracking.detail(active)['track']['point_count'] == 1
    with pytest.raises(KeyError):
        tracking.detail(stopped)


async def test_stop_while_fetching_never_appends_after_stop_returns(service):
    tracking, clock, aircraft, _ = service
    track_id = await start(tracking)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed():
        entered.set()
        await release.wait()
        return aircraft.snapshot()

    aircraft.fetch = delayed
    clock.advance()
    aircraft.items = [plane(clock, longitude=20.01)]
    collector = asyncio.create_task(tracking.collect_once())
    await entered.wait()
    stopping = asyncio.create_task(tracking.stop(track_id))
    release.set()
    await collector
    result = await stopping
    await tracking.collect_once()
    assert tracking.detail(track_id) == result


async def test_shutdown_drains_in_progress_database_worker(service):
    tracking, clock, aircraft, _ = service
    track_id = await start(tracking)
    entered, release = Event(), Event()
    original = tracking.ingest

    def delayed(kind, snapshot):
        entered.set()
        assert release.wait(timeout=3)
        return original(kind, snapshot)

    tracking.ingest = delayed
    clock.advance()
    aircraft.items = [plane(clock, longitude=20.01)]
    tracking.start()
    closing = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        closing = asyncio.create_task(tracking.close())
        await asyncio.sleep(.01)
        assert not closing.done(), 'Shutdown must wait for the SQLite worker before repo.close()'
    finally:
        release.set()
        if closing:
            await closing
        else:
            await tracking.close()
    assert tracking.detail(track_id)['track']['point_count'] == 2
    assert not tracking.workers
