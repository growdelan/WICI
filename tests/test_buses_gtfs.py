"""Synthetic GTFS fixtures verify city joins, freshness, resource bounds and failures."""
import asyncio
import io
import struct
import zipfile
import zlib
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as gtfs

from wici.buses_gtfs import (
    FEEDS,
    STATIC_SECONDS,
    GtfsBusService,
    read_realtime,
    read_static,
)

NOW = datetime(2026, 10, 15, 15, tzinfo=UTC)


def archive(**overrides):
    tables = {
        'agency.txt': 'agency_id,agency_name\na,Operator miejski\n',
        'routes.txt': 'route_id,route_short_name,route_type,agency_id\nb,101,3,a\nt,1,0,a\n',
        'trips.txt': 'trip_id,route_id,trip_headsign\ntrip,b,Pętla\ntram,t,Centrum\n',
        'stops.txt': 'stop_id,stop_name\ns1,Pierwszy\ns2,Drugi\n',
        # These expensive tables must never be decoded/indexed.
        'stop_times.txt': 'invalid unused file', 'shapes.txt': 'invalid unused file',
        **overrides,
    }
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, value in tables.items():
            output.writestr(name, value)
    return result.getvalue()


def feed(timestamp=NOW, **changes):
    result = gtfs.FeedMessage()
    result.header.gtfs_realtime_version = '2.0'
    result.header.timestamp = int(timestamp.timestamp())
    entity = result.entity.add(id='entity1')
    vehicle = entity.vehicle
    vehicle.trip.trip_id = 'trip'
    vehicle.trip.route_id = 'b'
    vehicle.vehicle.id = '1050'
    vehicle.vehicle.label = '101/1'
    vehicle.position.latitude = 52.4
    vehicle.position.longitude = 16.9
    vehicle.position.speed = 10
    vehicle.position.bearing = 90
    vehicle.timestamp = int(timestamp.timestamp())
    vehicle.current_stop_sequence = 1
    vehicle.stop_id = 's1'
    for name, value in changes.items():
        setattr(vehicle, name, value)
    return result


def updates(timestamp=NOW):
    result = gtfs.FeedMessage()
    result.header.gtfs_realtime_version = '2.0'
    result.header.timestamp = int(timestamp.timestamp())
    update = result.entity.add(id='update1').trip_update
    update.trip.trip_id = 'trip'
    update.vehicle.id = '1050'
    stop = update.stop_time_update.add(stop_sequence=1, stop_id='s1')
    stop.arrival.delay = -20
    stop = update.stop_time_update.add(stop_sequence=2, stop_id='s2')
    stop.arrival.delay = 200
    return result


def transport(handler=None, city='poznan'):
    urls = {url: kind for _, *urls in FEEDS[city] for url, kind in zip(urls, ('positions', 'updates', 'static'))}
    calls = Counter()
    async def respond(request):
        url = str(request.url)
        calls[url] += 1
        kind = urls[url]
        if handler:
            response = handler(url, kind, calls[url])
            if response is not None:
                return response
        content = archive() if kind == 'static' else (feed() if kind == 'positions' else updates()).SerializeToString()
        return httpx.Response(200, content=content)
    return httpx.MockTransport(respond), calls


@pytest.mark.asyncio
async def test_lazy_shared_cache_static_index_and_city_contract():
    mock, calls = transport()
    now = [NOW]
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'poznan')
        assert not calls
        snapshots = await asyncio.gather(*(service.fetch() for _ in range(6)))
        assert sum(calls.values()) == 3
        assert all(snapshot == snapshots[0] for snapshot in snapshots)
        snapshot = snapshots[0]
        assert snapshot['status'] == 'ready' and not snapshot['stale']
        item = snapshot['items'][0]
        assert item == {'id': 'poznan:ztm:1050', 'line': '101', 'vehicle_number': '1050',
                        'model': None, 'operator': 'Operator miejski', 'headsign': 'Pętla',
                        'latitude': pytest.approx(52.4), 'longitude': pytest.approx(16.9),
                        'speed_kmh': 36, 'bearing': 90, 'delay_seconds': -20,
                        'previous_stop': None, 'next_stop': 'Pierwszy',
                        'position_at': NOW.isoformat(), 'low_floor': None}
        item['line'] = 'changed'
        assert (await service.fetch())['items'][0]['line'] == '101'
        now[0] += timedelta(seconds=10)
        await service.fetch()
        assert sum(calls.values()) == 5  # The large archive remains cached.
        assert calls[FEEDS['poznan'][0][3]] == 1


def test_normalization_filters_trams_unknown_routes_invalid_positions_and_age():
    positions = feed()
    for index, route in enumerate(('t', 'unknown')):
        entity = positions.entity.add(id=f'e{index}')
        entity.CopyFrom(positions.entity[0])
        entity.vehicle.vehicle.id = f'invalid{index}'
        entity.vehicle.trip.route_id = route
    for index, timestamp in enumerate((NOW+timedelta(seconds=1), NOW-timedelta(seconds=121))):
        entity = positions.entity.add(id=f'old{index}')
        entity.CopyFrom(positions.entity[0])
        entity.vehicle.vehicle.id = f'old{index}'
        entity.vehicle.timestamp = int(timestamp.timestamp())
    invalid = positions.entity.add(id='coordinates')
    invalid.CopyFrom(positions.entity[0])
    invalid.vehicle.vehicle.id = 'badco'
    invalid.vehicle.position.latitude = float('nan')
    service = GtfsBusService(None, lambda: NOW, 'poznan')
    items = service.normalize(positions, None, read_static(archive()), 'ztm', NOW)
    assert len(items) == 1 and items[0]['vehicle_number'] == '1050'


def test_source_timestamp_fallback_optional_fields_and_trip_route_join():
    positions = feed()
    vehicle = positions.entity[0].vehicle
    vehicle.ClearField('timestamp')
    vehicle.trip.ClearField('route_id')
    vehicle.position.ClearField('speed')
    vehicle.position.ClearField('bearing')
    service = GtfsBusService(None, lambda: NOW, 'poznan')
    item = service.normalize(positions, None, read_static(archive()), 'ztm', NOW)[0]
    assert item['position_at'] == NOW.isoformat()
    assert item['line'] == '101' and item['bearing'] is None and item['speed_kmh'] is None
    positions.header.ClearField('timestamp')
    assert service.normalize(positions, None, read_static(archive()), 'ztm', NOW) == []


def test_delay_matches_next_stop_not_arbitrary_future_and_ignores_stale_updates():
    service = GtfsBusService(None, lambda: NOW, 'poznan')
    metadata = read_static(archive())
    positions, update_feed = feed(), updates()
    vehicle = positions.entity[0].vehicle
    update_feed.entity[0].trip_update.stop_time_update[0].stop_sequence = 3
    assert service.normalize(positions, update_feed, metadata, 'ztm', NOW)[0]['delay_seconds'] is None
    vehicle.current_stop_sequence = 2
    vehicle.stop_id = 's2'
    assert service.normalize(positions, update_feed, metadata, 'ztm', NOW)[0]['delay_seconds'] == 200
    stale_updates = updates(NOW-timedelta(seconds=121))
    assert service.normalize(positions, stale_updates, metadata, 'ztm', NOW)[0]['delay_seconds'] is None
    vehicle.current_status = gtfs.VehiclePosition.STOPPED_AT
    item = service.normalize(positions, update_feed, metadata, 'ztm', NOW)[0]
    assert item['next_stop'] is None and item['delay_seconds'] is None


@pytest.mark.asyncio
async def test_krakow_namespaces_and_partial_failure_preserve_then_expire():
    now = [NOW]
    def fail_one(url, kind, count):
        if url == FEEDS['krakow'][1][1] and count > 1:
            return httpx.Response(503)
    mock, calls = transport(fail_one, 'krakow')
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'krakow')
        result = await service.fetch()
        assert {item['id'] for item in result['items']} == {'krakow:A:1050', 'krakow:M:1050'}
        now[0] += timedelta(seconds=10)
        result = await service.fetch()
        assert result['status'] == 'error' and result['stale'] and len(result['items']) == 2
        now[0] += timedelta(seconds=10)
        await service.fetch()
        assert calls[FEEDS['krakow'][1][1]] == 2  # Failed feed has its own backoff.
        assert calls[FEEDS['krakow'][0][1]] == 3
        now[0] += timedelta(seconds=111)
        assert (await service.fetch())['items'] == []  # Download never rejuvenates source timestamps.


@pytest.mark.asyncio
@pytest.mark.parametrize('warm_cache', [False, True])
async def test_corrupt_operator_archive_keeps_krakow_available_and_recovers(warm_cache):
    broken = bytearray(archive())
    with zipfile.ZipFile(io.BytesIO(broken)) as zipped:
        entry = zipped.getinfo('trips.txt')
    name_length, extra_length = struct.unpack_from('<HH', broken, entry.header_offset+26)
    offset = entry.header_offset+30+name_length+extra_length
    # Preserve the ZIP directory but give the DEFLATE stream a reserved block type.
    broken[offset] = (broken[offset] & ~6) | 6
    with pytest.raises(zlib.error):
        read_static(bytes(broken))

    now = [NOW]
    failed_attempt = 2 if warm_cache else 1
    static_url = FEEDS['krakow'][0][3]

    def respond(url, kind, count):
        if url == static_url and count == failed_attempt:
            return httpx.Response(200, content=bytes(broken))
        if kind in ('positions', 'updates'):
            message = feed(now[0]) if kind == 'positions' else updates(now[0])
            return httpx.Response(200, content=message.SerializeToString())

    mock, calls = transport(respond, 'krakow')
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'krakow')
        if warm_cache:
            assert len((await service.fetch())['items']) == 2
            now[0] += timedelta(seconds=STATIC_SECONDS)

        result = await service.fetch()
        expected = {'krakow:A:1050', 'krakow:M:1050'} if warm_cache else {'krakow:M:1050'}
        assert {item['id'] for item in result['items']} == expected
        assert result['status'] == 'error' and result['stale'] and result['message']
        assert service.feeds['A'].static_retry == now[0]+timedelta(seconds=60)

        now[0] += timedelta(seconds=10)
        assert {item['id'] for item in (await service.fetch())['items']} == expected
        assert calls[static_url] == failed_attempt  # No immediate archive retry.
        assert calls[FEEDS['krakow'][1][1]] >= 2  # Healthy operator still refreshes.

        now[0] += timedelta(seconds=50)
        recovered = await service.fetch()
        assert recovered['status'] == 'ready' and not recovered['stale']
        assert {item['id'] for item in recovered['items']} == {'krakow:A:1050', 'krakow:M:1050'}
        assert calls[static_url] == failed_attempt+1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['static', 'positions'])
async def test_initial_failure_is_contained_and_backed_off(kind):
    def fail(url, requested_kind, count):
        if requested_kind == kind:
            return httpx.Response(429, headers={'Retry-After': '180'})
    mock, calls = transport(fail)
    now = [NOW]
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'poznan')
        result = await service.fetch()
        assert result['status'] == 'error' and result['items'] == []
        count = sum(calls.values())
        now[0] += timedelta(seconds=179)
        await service.fetch()
        assert sum(calls.values()) == count
        now[0] += timedelta(seconds=1)
        await service.fetch()
        assert sum(calls.values()) > count


@pytest.mark.asyncio
async def test_optional_updates_failure_keeps_positions_without_old_delay_and_honors_retry():
    def fail(url, kind, count):
        if kind == 'updates':
            return httpx.Response(429, headers={'Retry-After': '180'})
    mock, calls = transport(fail)
    now = [NOW]
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'poznan')
        result = await service.fetch()
        assert result['status'] == 'error' and len(result['items']) == 1
        assert result['items'][0]['delay_seconds'] is None
        now[0] += timedelta(seconds=10)
        await service.fetch()
        assert calls[FEEDS['poznan'][0][2]] == 1
        assert calls[FEEDS['poznan'][0][1]] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('config', [{'demo': True}, {'enabled': False}])
async def test_disabled_and_demo_do_not_connect(config):
    mock, calls = transport()
    async with httpx.AsyncClient(transport=mock) as client:
        result = await GtfsBusService(client, lambda: NOW, 'poznan', **config).fetch()
        assert not calls and result['items'] == []


def test_bounded_archives_and_missing_schema(monkeypatch):
    import wici.buses_gtfs as module
    monkeypatch.setattr(module, 'MAX_TABLE_BYTES', 20)
    with pytest.raises(ValueError, match='large'):
        read_static(archive())
    monkeypatch.setattr(module, 'MAX_TABLE_BYTES', 64000)
    with pytest.raises(ValueError, match='columns'):
        read_static(archive(**{'routes.txt': 'unrelated\nbad\n'}))
    monkeypatch.setattr(module, 'MAX_TABLE_ROWS', 1)
    with pytest.raises(ValueError, match='rows'):
        read_static(archive())


def test_realtime_rejects_uninitialized_and_differential_snapshots():
    with pytest.raises(ValueError):
        read_realtime(b'')
    positions = feed()
    positions.header.incrementality = gtfs.FeedHeader.DIFFERENTIAL
    with pytest.raises(ValueError, match='differential'):
        read_realtime(positions.SerializeToString())


@pytest.mark.asyncio
async def test_runtime_response_limit(monkeypatch):
    import wici.buses_gtfs as module
    mock, _ = transport()
    monkeypatch.setattr(module, 'MAX_REALTIME_BYTES', 10)
    async with httpx.AsyncClient(transport=mock) as client:
        result = await GtfsBusService(client, lambda: NOW, 'poznan').fetch()
        assert result['status'] == 'error' and result['items'] == []


@pytest.mark.asyncio
async def test_malformed_protobuf_does_not_escape():
    def corrupt(url, kind, count):
        if kind == 'positions':
            return httpx.Response(200, content=b'invalid protobuf')
    mock, _ = transport(corrupt)
    async with httpx.AsyncClient(transport=mock) as client:
        result = await GtfsBusService(client, lambda: NOW, 'poznan').fetch()
        assert result['status'] == 'error' and result['items'] == []


@pytest.mark.asyncio
async def test_positions_failure_preserves_only_young_cache_and_original_fetch_time():
    def fail(url, kind, count):
        if kind == 'positions' and count > 1:
            raise httpx.ReadTimeout('temporary outage')
    mock, _ = transport(fail)
    now = [NOW]
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'poznan')
        initial = await service.fetch()
        now[0] += timedelta(seconds=10)
        result = await service.fetch()
        assert result['status'] == 'error' and result['stale']
        assert result['items'] == initial['items'] and result['fetched_at'] == initial['fetched_at']
        now[0] += timedelta(seconds=111)
        result = await service.fetch()
        assert result['items'] == [] and result['fetched_at'] == initial['fetched_at']


@pytest.mark.asyncio
async def test_static_refresh_failure_retains_usable_indexes_with_visible_warning():
    import wici.buses_gtfs as module
    def fail(url, kind, count):
        if kind == 'static' and count == 2:
            return httpx.Response(503)
        if kind in ('positions', 'updates'):
            message = feed(now[0]) if kind == 'positions' else updates(now[0])
            return httpx.Response(200, content=message.SerializeToString())
    mock, calls = transport(fail)
    now = [NOW]
    async with httpx.AsyncClient(transport=mock) as client:
        service = GtfsBusService(client, lambda: now[0], 'poznan')
        await service.fetch()
        now[0] += timedelta(seconds=module.STATIC_SECONDS)
        result = await service.fetch()
        assert result['status'] == 'error' and len(result['items']) == 1
        now[0] += timedelta(seconds=10)
        assert len((await service.fetch())['items']) == 1
        assert calls[FEEDS['poznan'][0][3]] == 2
        now[0] += timedelta(seconds=50)
        assert (await service.fetch())['status'] == 'ready'
        assert calls[FEEDS['poznan'][0][3]] == 3


@pytest.mark.asyncio
async def test_expiry_uses_clock_after_static_loading_not_request_start():
    now = [NOW]
    def slow_archive(url, kind, count):
        if kind == 'static':
            now[0] += timedelta(seconds=121)
    mock, _ = transport(slow_archive)
    async with httpx.AsyncClient(transport=mock) as client:
        result = await GtfsBusService(client, lambda: now[0], 'poznan').fetch()
        assert result['status'] == 'ready' and result['items'] == []
        assert result['fetched_at'] == now[0].isoformat()
