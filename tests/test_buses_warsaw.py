"""Offline coverage of the current Warsaw API protocol, freshness and failures."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wici.buses import MAX_BYTES
from wici.buses_warsaw import BUSES_URL, WarsawBusService, position_time

NOW = datetime(2026, 10, 15, 15, tzinfo=UTC)


def row(**updates):
    return {'Brigade': '03', 'Lines': '219', 'VehicleNumber': '1000',
            'Lat': 52.21, 'Lon': 21.12, 'Time': '2026-10-15 16:59:45', **updates}


@pytest.mark.asyncio
async def test_current_api_header_post_and_shared_cache():
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == BUSES_URL
        assert request.method == 'POST'
        assert request.headers['Authorization'] == 'test-secret'
        assert json.loads(request.content) == {'type': 1}
        return httpx.Response(200, json=[row()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WarsawBusService(client, lambda: NOW, key='test-secret')
        results = await asyncio.gather(*(service.fetch() for _ in range(5)))
        assert len(calls) == 1 and all(r == results[0] for r in results)
        result = results[0]
        assert 'test-secret' not in json.dumps(result)
        item = result['items'][0]
        assert item['id'] == 'warszawa:1000' and item['line'] == '219'
        assert item['position_at'] == (NOW-timedelta(seconds=15)).isoformat()
        assert all(item[key] is None for key in ('model', 'operator', 'headsign', 'speed_kmh',
                                               'bearing', 'delay_seconds', 'low_floor'))
        item['line'] = 'changed'
        assert (await service.fetch())['items'][0]['line'] == '219'


@pytest.mark.asyncio
@pytest.mark.parametrize('options,status', [({}, 'unconfigured'), ({'enabled': False}, 'disabled'),
                                           ({'demo': True}, 'ready')])
async def test_no_network_without_key_when_disabled_or_demo(options, status):
    def handler(request):
        pytest.fail('No network permitted')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WarsawBusService(client, lambda: NOW, **options).fetch()
        assert result['status'] == status and result['items'] == []
        if status == 'unconfigured':
            assert result['enabled'] is False


def test_normalization_rejects_invalid_rows_and_keeps_newest_duplicate():
    service = WarsawBusService(None, lambda: NOW)
    rows = [None, {}, row(VehicleNumber=True), row(Lat='nan'), row(Lon=True),
            row(Time='2026-10-15 17:00:01'), row(Time='2026-10-15 16:57:59'),
            row(Time='2024-05-28 14:42:05'), row(Time='invalid'), row(),
            row(Time='2026-10-15 16:59:30')]
    items = service.normalize(rows, NOW)
    assert len(items) == 1 and items[0]['position_at'] == (NOW-timedelta(seconds=15)).isoformat()
    assert service.normalize({'result': rows}, NOW) == items
    for invalid in ({'result': 'denied'}, 'denied', None, [None]*10001):
        with pytest.raises(ValueError):
            service.normalize(invalid, NOW)


def test_local_time_dst_and_ambiguous_hour():
    assert position_time('2026-01-15 17:00:00') == datetime(2026, 1, 15, 16, tzinfo=UTC)
    assert position_time('2026-07-15 17:00:00') == datetime(2026, 7, 15, 15, tzinfo=UTC)
    for value in ('2026-10-25 02:30:00', '2026-03-29 02:30:00', '2026-10-15T17:00:00Z'):
        with pytest.raises(ValueError):
            position_time(value)


@pytest.mark.asyncio
async def test_304_and_failure_never_rejuvenate_positions():
    calls, now = [], [NOW]

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=[row()], headers={'ETag': '"v1"'})
        assert request.headers['If-None-Match'] == '"v1"'
        if len(calls) == 2:
            return httpx.Response(304)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WarsawBusService(client, lambda: now[0], key='test-secret')
        first = await service.fetch()
        now[0] += timedelta(seconds=10)
        assert (await service.fetch())['items'] == first['items']
        now[0] += timedelta(seconds=10)
        failed = await service.fetch()
        assert failed['items'] == first['items'] and failed['stale'] and failed['status'] == 'error'
        assert 'Warszawa' in failed['message'] and 'Szczecin' not in failed['message']
        now[0] += timedelta(seconds=90)
        assert (await service.fetch())['items'] == []


@pytest.mark.asyncio
async def test_retry_after_and_safe_auth_error():
    calls, now = [], [NOW]

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '300'}, text='test-secret')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WarsawBusService(client, lambda: now[0], key='test-secret')
        result = await service.fetch()
        assert result['status'] == 'error' and 'test-secret' not in json.dumps(result)
        now[0] += timedelta(seconds=299)
        await service.fetch()
        assert len(calls) == 1
        now[0] += timedelta(seconds=1)
        await service.fetch()
        assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>'),
                                     httpx.Response(200, json={'error': 'unauthorized'}),
                                     httpx.Response(401, json={'secret': 'test-secret'}),
                                     httpx.Response(200, content=b'['+b' '*MAX_BYTES,
                                                    headers={'Content-Type': 'application/json'})])
async def test_invalid_or_oversize_source_responses_are_safe(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        result = await WarsawBusService(client, lambda: NOW, key='test-secret').fetch()
        assert result['status'] == 'error' and result['items'] == []
        assert 'test-secret' not in json.dumps(result)
