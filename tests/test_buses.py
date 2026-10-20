"""Offline checks for shared bus snapshots, provider caching and source freshness."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wici.buses import BUSES_URL, MAX_BYTES, BusService

NOW = datetime(2026, 10, 15, 15, tzinfo=UTC)


def bus(**updates):
    return {'vehicle': {'id': 3, 'type': 'BUS', 'number': '1050', 'model': 'Solaris Urbino 18',
                        'operator': 'SPA Klonowica', 'low_floor': True},
            'position': {'latitude': 53.4, 'longitude': 14.5, 'velocity': 30, 'bearing': 90},
            'line': {'number': '60'}, 'trip': {'headsign': 'Stocznia Szczecińska'},
            'delay': {'seconds': -30}, 'previous_stop': {'name': 'Cukrowa'}, 'next_stop': None,
            'updated_at': (NOW-timedelta(seconds=15)).isoformat(), **updates}


def payload(*rows):
    return {'data': list(rows)}


@pytest.mark.asyncio
async def test_shared_lazy_concurrent_cache_and_source_schema():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        assert str(request.url) == BUSES_URL
        assert request.extensions['timeout']['read'] == 10
        return httpx.Response(200, json=payload(bus()), headers={'Cache-Control': 'max-age=30'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = BusService(client, lambda: now[0], timeout=20)
        assert not calls
        results = await asyncio.gather(*(service.fetch() for _ in range(6)))
        assert len(calls) == 1 and all(result == results[0] for result in results)
        item = results[0]['items'][0]
        assert item == {'id': 'szczecin:3', 'line': '60', 'vehicle_number': '1050',
                        'model': 'Solaris Urbino 18', 'operator': 'SPA Klonowica',
                        'headsign': 'Stocznia Szczecińska', 'latitude': 53.4, 'longitude': 14.5,
                        'speed_kmh': 30, 'bearing': 90, 'delay_seconds': -30,
                        'previous_stop': 'Cukrowa', 'next_stop': None,
                        'position_at': (NOW-timedelta(seconds=15)).isoformat(), 'low_floor': True}
        item['line'] = 'mutated'
        assert (await service.fetch())['items'][0]['line'] == '60'
        now[0] += timedelta(seconds=29)
        await service.fetch()
        assert len(calls) == 1
        now[0] += timedelta(seconds=1)
        await service.fetch()
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_conditional_304_does_not_rejuvenate_positions():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=payload(bus()), headers={'ETag': '"abc"', 'Cache-Control': 'max-age=5'})
        assert request.headers['If-None-Match'] == '"abc"'
        return httpx.Response(304, headers={'Cache-Control': 'max-age=10'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = BusService(client, lambda: now[0])
        initial = await service.fetch()
        now[0] += timedelta(seconds=10)
        result = await service.fetch()
        assert len(calls) == 2 and result['items'] == initial['items']
        assert result['fetched_at'] == now[0].isoformat()
        now[0] += timedelta(seconds=100)
        result = await service.fetch()
        assert result['items'] == [] and result['status'] == 'ready'


def test_invalid_rows_nullable_fields_and_source_age():
    service = BusService(None, lambda: NOW)
    malformed = [None, {}, bus(vehicle={'type': 'TRAM', 'id': 4}), bus(vehicle={'type': 'BUS', 'id': True}),
                 bus(position={'latitude': 'NaN', 'longitude': 14.5}),
                 bus(position={'latitude': True, 'longitude': 14.5}), bus(updated_at='invalid'),
                 bus(updated_at=NOW.replace(tzinfo=None).isoformat()),
                 bus(updated_at=(NOW+timedelta(seconds=1)).isoformat()),
                 bus(updated_at=(NOW-timedelta(seconds=121)).isoformat())]
    assert service.normalize(payload(*malformed, bus(), bus()), NOW) == service.normalize(payload(bus()), NOW)
    record = bus(line=None, trip=None, delay=None, previous_stop=None,
                 vehicle={'id': 3, 'type': 'BUS', 'number': None, 'low_floor': 'true'},
                 position={'latitude': 53.4, 'longitude': 14.5, 'velocity': None, 'bearing': 361})
    item = service.normalize(payload(record), NOW)[0]
    assert all(item[key] is None for key in ('line', 'model', 'vehicle_number', 'operator', 'headsign',
                                           'speed_kmh', 'bearing', 'delay_seconds', 'previous_stop',
                                           'next_stop', 'low_floor'))


@pytest.mark.asyncio
async def test_failure_preserves_then_expires_last_positions():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=payload(bus()))
        raise httpx.ReadTimeout('unavailable')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = BusService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=10)
        result = await service.fetch()
        assert result['stale'] and result['status'] == 'error' and len(result['items']) == 1
        assert result['fetched_at'] == NOW.isoformat()
        now[0] += timedelta(seconds=30)
        await service.fetch()
        assert len(calls) == 2
        now[0] += timedelta(seconds=90)
        result = await service.fetch()
        assert result['stale'] and result['items'] == [] and len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [{'Retry-After': '180'},
    {'Retry-After': 'Thu, 15 Oct 2026 15:03:00 GMT'},
    {'X-RateLimit-Reset': str(int(NOW.timestamp()+180))}])
async def test_rate_limit_retry_headers(headers):
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return (httpx.Response(429, headers=headers) if len(calls) == 1
                else httpx.Response(200, json=payload()))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = BusService(client, lambda: now[0])
        assert (await service.fetch())['status'] == 'error'
        now[0] += timedelta(seconds=179)
        await service.fetch()
        assert len(calls) == 1
        now[0] += timedelta(seconds=1)
        assert (await service.fetch())['status'] == 'ready'
        assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, json={'data': {}}),
    httpx.Response(200, json=[]), httpx.Response(304), httpx.Response(302),
    httpx.Response(200, content='invalid', headers={'Content-Type': 'application/json'}),
    httpx.Response(200, content='{}', headers={'Content-Type': 'text/html'}),
    httpx.Response(200, content=b' '*(MAX_BYTES+1), headers={'Content-Type': 'application/json'})])
async def test_invalid_response_is_explicit_error(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        result = await BusService(client, lambda: NOW).fetch()
        assert result['status'] == 'error' and not result['stale'] and result['items'] == []


@pytest.mark.asyncio
async def test_demo_disabled_no_network():
    def handler(request):
        raise AssertionError('Network should not be used')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        demo = await BusService(client, lambda: NOW, demo=True).fetch()
        disabled = await BusService(client, lambda: NOW, enabled=False).fetch()
        assert demo['demo'] and demo['items'] == [] and demo['message']
        assert disabled['status'] == 'disabled' and disabled['items'] == []


@pytest.mark.asyncio
async def test_no_store_discards_positions_and_etag():
    calls = []
    def handler(request):
        calls.append(request)
        assert 'If-None-Match' not in request.headers
        return httpx.Response(200, json=payload(bus()),
                              headers={'Cache-Control': 'no-store', 'ETag': '"private"'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = BusService(client, lambda: NOW)
        assert len((await service.fetch())['items']) == 1
        assert service.cache is None and service.etag is None
        assert len((await service.fetch())['items']) == 1
        assert len(calls) == 2
