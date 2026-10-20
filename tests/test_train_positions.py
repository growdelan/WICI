"""Estimates follow GTFS curves with explicit realtime brackets; stale feeds never move trains."""
import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from test_trains import archive, update

from wici.train_positions import PositionEstimator, interval
from wici.trains import STATIC_URL, TrainService

NOW = datetime(2026, 10, 15, 22, 5, tzinfo=UTC)
DAY = date(2026, 10, 15)


def curved_archive(**overrides):
    files = {
        'stops.txt': [['stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'location_type', 'parent_station', 'country'],
                      ['A', 'West', '52', '20', '1', '', 'PL'],
                      ['B', 'East', '52', '20.02', '1', '', 'PL']],
        'stop_times.txt': [['trip_id', 'stop_sequence', 'stop_id', 'arrival_time', 'departure_time',
                            'pickup_type', 'shape_dist_traveled'],
                           ['T', '7', 'A', '24:00:00', '24:00:00', '0', '0'],
                           ['T', '9', 'B', '24:10:00', '24:10:00', '1', '3000']],
        'shapes.txt': [['shape_id', 'shape_pt_sequence', 'shape_pt_lat', 'shape_pt_lon', 'shape_dist_traveled'],
                       ['shape', '0', '52', '20', '0'], ['shape', '1', '52.01', '20', '1000'],
                       ['shape', '2', '52.01', '20.02', '2000'], ['shape', '3', '52', '20.02', '3000']],
    }
    files.update(overrides)
    return archive(**files)


def live(**overrides):
    return update(now=NOW, stop_times=[{'stop_sequence': 7, 'departure': '2026-10-16T00:00:00+02:00'},
                                      {'stop_sequence': 9, 'arrival': '2026-10-16T00:10:00+02:00'}], **overrides)


def service_for(client, clock):
    return TrainService(client, clock)


@pytest.mark.asyncio
async def test_curved_track_beyond_midnight_realtime_only_shared_cache_and_expiry():
    now, calls = [NOW], []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=curved_archive() if str(request.url) == STATIC_URL else json.dumps(live()))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = service_for(client, lambda: now[0])
        results = await asyncio.gather(*(service.positions() for _ in range(4)))
        assert len(calls) == 2 and results[0] == results[1]
        result = results[0]
        item = result['items'][0]
        assert item['latitude'] == 52.01 and item['longitude'] == pytest.approx(20.01)
        assert item['id'] == 'T|2026-10-15' and item['estimated'] is True
        assert item['start_date'] == '2026-10-15'
        assert item['from_station'] == 'West' and item['to_station'] == 'East'
        assert item['estimated_at'] == NOW.isoformat()
        assert item['valid_until'] == (NOW + timedelta(seconds=30)).isoformat()
        item['latitude'] = 0
        assert (await service.positions())['items'][0]['latitude'] == 52.01
        now[0] += timedelta(seconds=16)
        new = await service.positions()
        assert new['estimated_at'] == now[0].isoformat()
        assert new['items'][0]['longitude'] > 20.01
        assert len(calls) == 2  # positions tick; source still shared for120s
        now[0] = NOW.replace(minute=10)
        assert (await service.positions())['items'] == []  # interval ends, no extrapolation


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'cancelled': True}, {'detour': True}, {'stop_times': []},
                                    {'stop_times': [{'stop_sequence': 7, 'departure': '2026-10-16T00:00:00+02:00',
                                                     'cancelled': True},
                                                    {'stop_sequence': 9, 'arrival': '2026-10-16T00:10:00+02:00'}]}])
async def test_cancelled_detour_missing_realtime_and_skipped_stops_have_no_positions(changes):
    payload = live()
    payload['trip_updates'][0].update(changes)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        assert (await service_for(client, lambda: NOW).positions())['items'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['missing', 'off_route', 'nonmonotonic_shape', 'missing_distance'])
async def test_unreliable_geometry_never_falls_back_to_straight_line(mode):
    files = {}
    if mode == 'missing':
        files['shapes.txt'] = [['shape_id', 'shape_pt_sequence', 'shape_pt_lat', 'shape_pt_lon',
                                'shape_dist_traveled']]
    elif mode == 'off_route':
        files['shapes.txt'] = [['shape_id', 'shape_pt_sequence', 'shape_pt_lat', 'shape_pt_lon',
                                'shape_dist_traveled'], ['shape', '0', '53', '21', '0'],
                               ['shape', '1', '53', '21.02', '3000']]
    elif mode == 'nonmonotonic_shape':
        files['shapes.txt'] = [['shape_id', 'shape_pt_sequence', 'shape_pt_lat', 'shape_pt_lon',
                                'shape_dist_traveled'], ['shape', '0', '52', '20', '3000'],
                               ['shape', '1', '52', '20.02', '0']]
    elif mode == 'missing_distance':
        files['stop_times.txt'] = [['trip_id', 'stop_sequence', 'stop_id', 'arrival_time', 'departure_time',
                                    'pickup_type'], ['T', '7', 'A', '24:00:00', '24:00:00', '0'],
                                   ['T', '9', 'B', '24:10:00', '24:10:00', '1']]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive(**files) if str(r.url) == STATIC_URL else json.dumps(live())))) as client:
        assert (await service_for(client, lambda: NOW).positions())['items'] == []


@pytest.mark.asyncio
async def test_dwell_uses_projected_station_and_bounds_validity_to_departure():
    payload = live()
    payload['trip_updates'][0]['stop_times'][0] = {
        'stop_sequence': 7, 'arrival': '2026-10-16T00:00:00+02:00', 'departure': '2026-10-16T00:05:10+02:00'}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        item = (await service_for(client, lambda: NOW).positions())['items'][0]
        assert (item['latitude'], item['longitude']) == (52, 20)
        assert item['from_station'] == item['to_station'] == 'West'
        assert item['valid_until'] == (NOW + timedelta(seconds=10)).isoformat()


@pytest.mark.asyncio
async def test_feed_failure_and_stale_source_remove_positions_even_if_cache_exists():
    now = [NOW]
    def handler(request):
        if str(request.url) == STATIC_URL:
            return httpx.Response(200, content=curved_archive())
        return httpx.Response(200, json=live()) if now[0] == NOW else httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = service_for(client, lambda: now[0])
        assert (await service.positions())['items']
        now[0] += timedelta(seconds=120)
        result = await service.positions()
        assert result['stale'] and result['items'] == []
        service.update_error = False
        service.source_at = NOW - timedelta(seconds=601)
        assert (await service.positions())['items'] == []


@pytest.mark.asyncio
async def test_freshness_checked_again_after_worker_and_snapshot_changes_never_escape(monkeypatch):
    now = [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(live())))) as client:
        service = service_for(client, lambda: now[0])
        original = PositionEstimator.estimate
        def estimate(estimator, *args):
            result = original(estimator, *args)
            now[0] += timedelta(seconds=601)
            return result
        monkeypatch.setattr(PositionEstimator, 'estimate', estimate)
        response = await service.positions()
        assert response['stale'] and response['items'] == []


def test_nonmonotonic_and_zero_duration_movement_is_rejected():
    entries = [('A', 7, 0, 0, True, 0), ('B', 9, 0, 0, False, 3000)]
    assert interval(entries, {'stops': {7: (7, None, 200, False), 9: (9, 100, None, False)}}, 150) is None
    assert interval(entries, {'stops': {7: (7, None, 100, False), 9: (9, 100, None, False)}}, 100) is None
    assert interval(entries, {'stops': {7: (7, 200, 100, False), 9: (9, 300, None, False)}}, 150) is None


@pytest.mark.asyncio
async def test_invalid_service_date_and_disabled_demo_have_no_positions():
    payload = live()
    payload['trip_updates'][0]['start_date'] = '2026-10-14'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        assert (await service_for(client, lambda: NOW).positions())['items'] == []
    for kwargs in ({'demo': True}, {'enabled': False}):
        service = TrainService(None, lambda: NOW, **kwargs)
        assert (await service.positions())['items'] == []


@pytest.mark.asyncio
async def test_source_replacement_during_estimation_discards_worker_result(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(live())))) as client:
        service = service_for(client, lambda: NOW)
        original = PositionEstimator.estimate
        def estimate(estimator, *args):
            result = original(estimator, *args)
            service.updates = dict(service.updates)
            return result
        monkeypatch.setattr(PositionEstimator, 'estimate', estimate)
        assert (await service.positions())['items'] == []


@pytest.mark.asyncio
async def test_position_cache_continues_with_unchanged_source_until_source_freshness_boundary():
    now = [NOW]
    payload = live()
    payload['timestamp'] = (NOW - timedelta(seconds=580)).isoformat()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        service = service_for(client, lambda: now[0])
        result = await service.positions()
        assert result['items'][0]['valid_until'] == (NOW + timedelta(seconds=20)).isoformat()
        now[0] += timedelta(seconds=16)
        newer = await service.positions()
        assert newer['items'] and newer['estimated_at'] == now[0].isoformat()
        now[0] += timedelta(seconds=5)
        assert (await service.positions())['items'] == []


def test_invalid_profiles_are_cached_and_leg_memory_is_bounded(monkeypatch):
    import wici.train_positions as positions
    from wici.trains import Timetable
    estimator = PositionEstimator(Timetable(curved_archive()))
    assert estimator.profile('missing') is None
    assert 'missing' in estimator.profiles
    monkeypatch.setattr(positions, 'MAX_RETAINED_POINTS', 3)
    entries = estimator.timetable.times['T']
    assert estimator.leg('shape', entries[0], entries[1]) is not None
    assert estimator.leg_points <= 3 and estimator.profile_points <= 3


@pytest.mark.asyncio
async def test_estimates_outside_poland_are_omitted(monkeypatch):
    monkeypatch.setattr('wici.train_positions.in_poland', lambda lat, lon: False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=curved_archive() if str(r.url) == STATIC_URL else json.dumps(live())))) as client:
        assert (await service_for(client, lambda: NOW).positions())['items'] == []
