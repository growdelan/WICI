"""Offline service-day, route, freshness and shared download checks for rail data."""
import asyncio
import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from wici.trains import STALE_SECONDS, STATIC_URL, UPDATES_URL, Timetable, TrainService, service_time

NOW = datetime(2026, 10, 15, 22, 5, tzinfo=UTC)  # 00:05 Warsaw, service started yesterday


def archive(**overrides):
    files = {
        'agency.txt': [['agency_id', 'agency_name'], ['IC', 'PKP Intercity']],
        'stops.txt': [['stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'location_type', 'parent_station', 'country'],
                      ['A', 'Warszawa', '52.23', '21.01', '1', '', 'PL'],
                      ['A_1', 'Warszawa peron 1', '52.231', '21.011', '0', 'A', 'PL'],
                      ['B', 'Kraków', '50.06', '19.94', '1', '', 'PL'],
                      ['C', 'Berlin', '52.5', '13.4', '1', '', 'DE']],
        'routes.txt': [['route_id', 'agency_id', 'route_short_name'], ['R', 'IC', 'IC']],
        'trips.txt': [['trip_id', 'route_id', 'service_id', 'shape_id', 'trip_short_name', 'trip_headsign'],
                      ['T', 'R', 'S', 'shape', '123', 'Kraków'],
                      ['T2', 'R', 'S2', '', '456', 'Kraków']],
        'calendar_dates.txt': [['date', 'service_id', 'exception_type'], ['20261015', 'S', '1'],
                               ['20261015', 'S2', '1']],
        'stop_times.txt': [['trip_id', 'stop_sequence', 'stop_id', 'arrival_time', 'departure_time', 'pickup_type'],
                           ['T', '7', 'A_1', '24:00:00', '24:10:00', '0'],
                           ['T', '9', 'B', '26:00:00', '', '1'],
                           ['T2', '0', 'A_1', '24:20:00', '24:20:00', '0']],
        'shapes.txt': [['shape_id', 'shape_pt_sequence', 'shape_pt_lat', 'shape_pt_lon'],
                       ['shape', '1', '52.23', '21.01'], ['shape', '2', '50.06', '19.94']],
        'feed_info.txt': [['feed_end_date'], ['20261231']],
    }
    files.update(overrides)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, rows in files.items():
            data = io.StringIO()
            csv.writer(data).writerows(rows)
            z.writestr(name, data.getvalue())
    return output.getvalue()


def update(now=NOW, **overrides):
    row = {'trip_id': 'T', 'start_date': '2026-10-15', 'stop_times': [
        {'stop_sequence': 7, 'departure': '2026-10-16T00:17:00+02:00'},
        {'stop_sequence': 9, 'arrival': '2026-10-16T02:05:00+02:00'}], **overrides}
    return {'timestamp': now.isoformat(), 'trip_updates': [row]}


@pytest.mark.asyncio
async def test_lazy_shared_cache_station_parent_and_beyond_midnight_route():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        assert request.headers['user-agent'].startswith('WICI/')
        return httpx.Response(200, content=archive() if str(request.url) == STATIC_URL else json.dumps(update()))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrainService(client, lambda: NOW)
        assert calls == []
        results = await asyncio.gather(*(service.stations() for _ in range(5)))
        assert calls == [STATIC_URL, UPDATES_URL]
        assert {s['id'] for s in results[0]['items']} == {'A', 'B'}
        board = await service.station('A')
        first, second = board['departures']
        assert first['trip_id'] == 'T' and first['start_date'] == '2026-10-15'
        assert first['scheduled_at'] == '2026-10-15T22:10:00+00:00'
        assert first['expected_at'] == '2026-10-15T22:17:00+00:00'
        assert first['delay_seconds'] == 420 and first['realtime'] is True
        assert second['delay_seconds'] is None and second['expected_at'] is None
        route = (await service.trip('T', first['start_date']))['trip']
        assert [s['sequence'] for s in route['stops']] == [7, 9]
        assert route['stops'][1]['delay_seconds'] == 300
        assert route['geometry']['coordinates'] == [[21.01, 52.23], [19.94, 50.06]]
        assert (await service.station('unknown'))['status'] == 'not_found'
        assert (await service.trip('T', '2026-10-16'))['status'] == 'not_found'
        assert (await service.trip('T', 'invalid'))['status'] == 'not_found'
        results[0]['items'][0]['name'] = 'changed'
        assert all(s['name'] != 'changed' for s in (await service.stations())['items'])


@pytest.mark.asyncio
async def test_source_timestamp_staleness_and_failure_retains_cache_with_backoff():
    now, calls = [NOW], []
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == STATIC_URL:
            return httpx.Response(200, content=archive())
        if len(calls) > 2:
            return httpx.Response(429, headers={'retry-after': '1000'})
        return httpx.Response(200, json=update(NOW - timedelta(seconds=STALE_SECONDS + 1)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrainService(client, lambda: now[0])
        initial = await service.stations()
        assert initial['stale'] and initial['status'] == 'stale'
        assert initial['fetched_at'] == NOW.isoformat()
        now[0] += timedelta(seconds=120)
        failed = await service.station('A')
        assert failed['stale'] and failed['departures']
        assert failed['source_updated_at'] == initial['source_updated_at']
        now[0] += timedelta(seconds=120)
        await service.stations()
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_missing_rt_is_planned_and_detour_does_not_attach_wrong_sequence_or_geometry():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=archive() if str(r.url) == STATIC_URL else json.dumps(update(detour=True))))) as client:
        service = TrainService(client, lambda: NOW)
        route = (await service.trip('T', '2026-10-15'))['trip']
        assert route['detour'] and route['geometry'] is None
        assert route['stops'][0]['expected_departure'] is None
        assert route['stops'][0]['delay_seconds'] is None
        assert (await service.station('A'))['departures'][0]['realtime'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('whole_trip', [True, False])
async def test_cancelled_and_skipped_are_explicit(whole_trip):
    payload = update(cancelled=whole_trip)
    if not whole_trip:
        payload['trip_updates'][0]['stop_times'][0]['cancelled'] = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        service = TrainService(client, lambda: NOW)
        departure = (await service.station('A'))['departures'][0]
        assert departure['cancelled']
        assert departure['trip_cancelled'] is whole_trip
        assert (await service.trip('T', '2026-10-15'))['trip']['cancelled'] is whole_trip


@pytest.mark.asyncio
@pytest.mark.parametrize('demo,enabled', [(True, True), (False, False)])
async def test_demo_disabled_never_download(demo, enabled):
    def handler(request):
        pytest.fail('unexpected network request')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrainService(client, lambda: NOW, demo=demo, enabled=enabled)
        assert (await service.stations())['items'] == []
        assert (await service.station('A'))['departures'] == []
        assert (await service.trip('T', '2026-10-15'))['trip'] is None


def test_calendar_exceptions_override_regular_and_gtfs_dst_noon_anchor():
    table = Timetable(archive(**{
        'calendar.txt': [['service_id', 'start_date', 'end_date', 'monday', 'tuesday', 'wednesday',
                          'thursday', 'friday', 'saturday', 'sunday'],
                         ['S', '20260101', '20261231', '1', '1', '1', '1', '1', '1', '1']],
        'calendar_dates.txt': [['date', 'service_id', 'exception_type'], ['20261015', 'S', '2']],
    }))
    assert not table.active('S', date(2026, 10, 15))
    assert table.active('S', date(2026, 10, 16))
    assert service_time(date(2026, 10, 25), 24 * 3600).isoformat() == '2026-10-25T23:00:00+00:00'


def test_invalid_timestamp_archive_and_size_bounds(monkeypatch):
    with pytest.raises(ValueError):
        TrainService.parse_updates(json.dumps(update(NOW + timedelta(hours=1))), NOW)
    with pytest.raises(ValueError):
        TrainService.parse_updates('{"timestamp":"2026-10-15T22:05:00"}', NOW)
    monkeypatch.setattr('wici.trains.MAX_UNPACKED', 10)
    with pytest.raises(ValueError, match='too large'):
        Timetable(archive())


@pytest.mark.asyncio
async def test_bad_download_keeps_static_unavailable_and_retries_bounded_body(monkeypatch):
    monkeypatch.setattr('wici.trains.MAX_BYTES', 10)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=archive())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrainService(client, lambda: NOW)
        assert (await service.stations())['status'] == 'error'
        assert (await service.stations())['items'] == []
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_backup_agency_number_match_and_ambiguous_match_is_ignored():
    payload = update(trip_id='old-T', agency_id='IC', numbers=['123'])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        service = TrainService(client, lambda: NOW)
        board = await service.station('A')
        assert board['departures'][0]['delay_seconds'] == 420
        service.timetable.by_number[('IC', '123')].append('T2')
        updates, _ = service.parse_updates(json.dumps(payload), NOW)
        service.match_updates(updates)
        assert ('T', date(2026, 10, 15)) not in updates


@pytest.mark.asyncio
async def test_source_rollback_keeps_last_good_update_and_mutating_route_does_not_poison_cache():
    now = [NOW]
    def handler(request):
        if str(request.url) == STATIC_URL:
            return httpx.Response(200, content=archive())
        return httpx.Response(200, json=update(NOW if now[0] == NOW else NOW - timedelta(seconds=10)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrainService(client, lambda: now[0])
        trip = await service.trip('T', '2026-10-15')
        trip['trip']['geometry']['coordinates'][0][0] = 99
        assert (await service.trip('T', '2026-10-15'))['trip']['geometry']['coordinates'][0][0] == 21.01
        now[0] += timedelta(seconds=120)
        result = await service.stations()
        assert result['stale'] and result['source_updated_at'] == NOW.isoformat()


def test_invalid_json_root_is_rejected():
    with pytest.raises(TypeError):
        TrainService.parse_updates('[]', NOW)


@pytest.mark.asyncio
async def test_skipped_stop_and_negative_delay_remain_distinct():
    payload = update(stop_times=[{'stop_sequence': 7, 'departure': '2026-10-16T00:08:00+02:00',
                                 'cancelled': True}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=archive() if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        service = TrainService(client, lambda: NOW)
        departure = (await service.station('A'))['departures'][0]
        assert departure['delay_seconds'] == -120 and departure['cancelled']
        trip = (await service.trip('T', '2026-10-15'))['trip']
        assert not trip['cancelled'] and trip['stops'][0]['skipped']


@pytest.mark.asyncio
async def test_failed_static_refresh_retains_previous_stations_and_marks_stale():
    now = [NOW]
    def handler(request):
        if str(request.url) == STATIC_URL:
            return httpx.Response(200, content=archive()) if now[0] == NOW else httpx.Response(503)
        return httpx.Response(200, json=update(now[0]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrainService(client, lambda: now[0])
        initial = await service.stations()
        now[0] += timedelta(hours=6)
        refreshed = await service.stations()
        assert refreshed['items'] == initial['items']
        assert refreshed['stale'] and refreshed['static_fetched_at'] == NOW.isoformat()


@pytest.mark.asyncio
async def test_arrival_only_update_at_stop_with_planned_departure_does_not_infer_departure_delay():
    payload = update(stop_times=[{'stop_sequence': 7, 'arrival': '2026-10-16T00:10:00+02:00'},
                                 {'stop_sequence': 9, 'arrival': '2026-10-16T02:10:00+02:00'}])
    timetable = archive(**{
        'stop_times.txt': [['trip_id', 'stop_sequence', 'stop_id', 'arrival_time', 'departure_time', 'pickup_type'],
                           ['T', '7', 'A_1', '24:00:00', '24:10:00', '0'],
                           ['T', '9', 'B', '26:00:00', '26:00:00', '1']],
    })
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, content=timetable if str(r.url) == STATIC_URL else json.dumps(payload)))) as client:
        service = TrainService(client, lambda: NOW)
        trip = (await service.trip('T', '2026-10-15'))['trip']
        assert trip['stops'][0]['delay_seconds'] == 600
        assert trip['stops'][1]['delay_seconds'] == 600
        departure = (await service.station('A'))['departures'][0]
        assert departure['expected_at'] is None and departure['delay_seconds'] is None
        assert departure['realtime'] is True
