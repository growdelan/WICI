"""Offline GIOŚ v1 contracts; original synthetic samples, no network."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.gios import MAX_BYTES, GiosService, normalize, source_time

NOW = datetime(2026, 10, 17, 6, 30, tzinfo=UTC)
FIXTURES = Path(__file__).parent/'fixtures/gios'


def sample(kind):
    return json.loads((FIXTURES/f'{kind}.json').read_text())


def response(kind):
    return httpx.Response(200, json=sample(kind), headers={'Content-Type': 'application/ld+json'})


def test_synthetic_schema_units_local_time_and_index_separate():
    for kind, field in [('stations', 'Lista stacji pomiarowych'),
                        ('sensors', 'Lista stanowisk pomiarowych dla podanej stacji'),
                        ('data', 'Lista danych pomiarowych')]:
        items, rejected = normalize(kind, sample(kind)[field])
        assert items and rejected == 0
        if kind == 'data':
            assert items[0]['unit'] == 'µg/m³'
            assert items[0]['observed_at'] == '2026-10-17T06:00:00+00:00'
        if kind == 'sensors':
            assert all(i['unit'] == 'µg/m³' for i in items)
            assert len([i for i in items if i['parameter'] == 'PM10']) == 2
    index = normalize('index', [sample('index')['AqIndex']])[0][0]
    assert index['value'] == 1 and index['name'] == 'Dobry'
    assert index['calculated']['source_time'] != index['source_time']


def test_dst_raw_source_no_guessing_and_invalid_location_retained():
    for raw in ('2026-10-25 02:00:00', '2026-03-29 02:00:00', 'bad'):
        assert source_time(raw) == {'source_time': raw, 'observed_at': None,
                                    'time_status': 'ambiguous_or_invalid'}
    assert source_time('2026-10-25T02:00:00+02:00')['observed_at'] == '2026-10-25T00:00:00+00:00'
    assert source_time('2026-01-17 08:00:00')['observed_at'] == '2026-01-17T07:00:00+00:00'
    row = sample('stations')['Lista stacji pomiarowych'][0]
    items, rejected = normalize('stations', [{**row, 'WGS84 φ N': 'nan'}, {}, None])
    assert items[0]['latitude'] is None and rejected == 2
    index = sample('index')['AqIndex']
    assert normalize('index', [{**index, 'Wartość indeksu': None}])[0][0]['name'] == 'Brak indeksu'
    assert normalize('index', [{**index, 'Wartość indeksu': 0}])[0][0]['value'] == 0


@pytest.mark.asyncio
async def test_cache_concurrency_latest_zero_null_order_and_aging():
    now, calls = [NOW], []
    payload = sample('data')
    payload['Lista danych pomiarowych'] = [
        {'Data': '2026-10-17 08:10:00', 'Wartość': None},
        {'Data': '2026-10-17 07:00:00', 'Wartość': 11},
        {'Data': '2026-10-17 08:00:00', 'Wartość': 0},
        {'Data': '2026-10-25 02:00:00', 'Wartość': 90}]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        results = await asyncio.gather(*(service.fetch('data', 9101) for _ in range(10)))
        assert len(calls) == 1
        assert results[0]['latest']['value'] == 0
        assert results[0]['latest']['age_seconds'] == 1800
        assert results[0]['unresolved_value_count'] == 1
        # Age recomputed from original observation, including within cache TTL.
        now[0] += timedelta(hours=2, minutes=29)
        await service.fetch('data', 9101)
        now[0] += timedelta(minutes=2)
        assert (await service.fetch('data', 9101))['latest']['freshness'] == 'stale'
        assert len(calls) == 2
        assert all('/v1/' in r.url.path for r in calls)


@pytest.mark.asyncio
async def test_pagination_uses_total_not_broken_next_links_and_partial_records():
    calls = []
    payload = sample('sensors')
    rows = payload['Lista stanowisk pomiarowych dla podanej stacji']
    def handler(request):
        calls.append(request)
        page = int(request.url.params['page'])
        return httpx.Response(200, json={**payload, 'totalPages': 2,
            'Lista stanowisk pomiarowych dla podanej stacji': rows[:1] if page == 0 else rows[1:]+[{}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: NOW)
        result = await service.fetch('sensors', 9001)
        assert result['status'] == 'partial' and result['rejected_count'] == 1
        assert len(result['items']) == len(rows) and len(calls) == 2
        assert [r.url.params['page'] for r in calls] == ['0', '1']
        assert all(r.url.params['size'] == '500' for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', '429', 'html', 'bad_json', 'schema', 'oversize', 'redirect', 'page'])
async def test_failure_preserves_original_snapshot_and_backoff(failure):
    now, calls = [NOW], []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response('data')
        if failure == 'timeout':
            raise httpx.ReadTimeout('private')
        return {
            '429': lambda: httpx.Response(429, headers={'Retry-After': '1200'}),
            'html': lambda: httpx.Response(200, text='private'),
            'bad_json': lambda: httpx.Response(200, content='{', headers={'Content-Type': 'application/json'}),
            'schema': lambda: httpx.Response(200, json={'values': []}),
            'oversize': lambda: httpx.Response(200, content=' '*(MAX_BYTES+1),
                                              headers={'Content-Type': 'application/json'}),
            'redirect': lambda: httpx.Response(302, headers={'Location': 'https://bad.test'}),
            'page': lambda: httpx.Response(200, json={**sample('data'), 'totalPages': 10000}),
        }[failure]()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        first = await service.fetch('data', 9101)
        now[0] += timedelta(seconds=1801)
        result = await service.fetch('data', 9101)
        assert result['status'] == 'error' and result['stale']
        assert result['fetched_at'] == first['fetched_at'] and result['items']
        assert 'private' not in str(result)
        await service.fetch('data', 9101)
        assert len(calls) == 2
        now[0] += timedelta(seconds=301)
        await service.fetch('data', 9101)
        assert len(calls) == (2 if failure == '429' else 3)


@pytest.mark.asyncio
async def test_manual_empty_missing_demo_and_source_disable():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(400, json=sample('manual'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for settings in ({'demo': True}, {'enabled': False}):
            service = GiosService(client, lambda: NOW, **settings)
            assert (await service.fetch())['status'] == 'disabled'
        assert not calls
        service = GiosService(client, lambda: NOW)
        assert (await service.fetch('data', 9100))['status'] == 'manual'
        assert (await service.fetch('data', 9100))['latest'] is None
        assert len(calls) == 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            **sample('data'), 'Lista danych pomiarowych': []}))) as client:
        assert (await GiosService(client, lambda: NOW).fetch('data', 1))['status'] == 'empty'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            **sample('data'), 'Lista danych pomiarowych': [{'Data': '2026-10-17 08:00:00', 'Wartość': None}]}))) as client:
        assert (await GiosService(client, lambda: NOW).fetch('data', 1))['status'] == 'missing'


@pytest.mark.asyncio
async def test_service_limits_shared_backoff_and_bounded_concurrency():
    in_flight, peak, calls = 0, 0, []
    async def handler(request):
        nonlocal in_flight, peak
        calls.append(request)
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(.01)
        in_flight -= 1
        return response('sensors')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: NOW)
        await asyncio.gather(*(service.fetch('sensors', i) for i in range(1, 25)))
        assert 1 < peak <= 4
        for _ in range(2):
            await service.reserve('stations')
        with pytest.raises(ValueError):
            await service.reserve('stations')
        assert len(service.requests['stations']) == 2
        service.requests['data'].extend([NOW]*120)
        with pytest.raises(ValueError):
            await service.reserve('data')


def test_local_api_guard_validation_demo_and_html(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path, config=Config()),
                    base_url='http://127.0.0.1:8765') as client:
        for kind in ('stations', 'sensors', 'data', 'index'):
            result = client.get('/api/gios', params={'kind': kind, 'id': 9001})
            assert result.status_code == 200
            assert result.json()['status'] == 'disabled'
        for query in ('kind=nope', 'kind=data', 'kind=data&id=-1', 'kind=index&id=9999999999999999999999'):
            assert client.get('/api/gios?'+query).status_code == 422
        for headers in ({'Origin': 'https://bad.test'}, {'Sec-Fetch-Site': 'cross-site'}):
            assert client.get('/api/gios', headers=headers).status_code == 403
        html = client.get('/').text
        assert 'id="gios-enabled"' in html and '/static/js/gios.js' in html
        assert 'id="gios-enabled" checked' not in html


@pytest.mark.asyncio
async def test_interrupted_pagination_partial_and_last_complete_cache_preserved():
    calls, now, fail = [], [NOW], [True]
    payload = sample('sensors')
    def handler(request):
        calls.append(request)
        if fail[0] and request.url.params['page'] == '1':
            return httpx.Response(503)
        return httpx.Response(200, json={**payload, 'totalPages': 2 if fail[0] else 1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        result = await service.fetch('sensors', 9001)
        assert result['status'] == 'partial' and result['stale'] and result['items']
        fail[0] = False
        now[0] += timedelta(minutes=6)
        complete = await service.fetch('sensors', 9001)
        assert complete['status'] == 'ready'
        fail[0] = True
        now[0] += timedelta(hours=7)
        result = await service.fetch('sensors', 9001)
        assert result['status'] == 'partial' and result['fetched_at'] == complete['fetched_at']
        assert result['items'] == complete['items'] and result['stale']


@pytest.mark.asyncio
async def test_retry_after_http_date_shared_between_sensors_and_cached_results():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response('data')
        return httpx.Response(429, headers={'Retry-After': 'Sat, 17 Oct 2026 09:30:00 GMT'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        first = await service.fetch('data', 1)
        now[0] += timedelta(minutes=31)
        assert (await service.fetch('data', 2))['status'] == 'error'
        retained = await service.fetch('data', 1)
        assert retained['status'] == 'error' and retained['fetched_at'] == first['fetched_at']
        now[0] += timedelta(hours=1)
        await service.fetch('data', 3)
        assert len(calls) == 2


def test_real_local_api_with_fixture_client_separate_resources(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        path = request.url.path
        kind = ('stations' if 'findAll' in path else 'sensors' if '/sensors/' in path
                else 'index' if '/getIndex/' in path else 'data')
        return response(kind)
    with TestClient(create_app(demo=True, root=tmp_path, config=Config()),
                    base_url='http://127.0.0.1:8765') as client:
        # Only GIOŚ is fixture-backed; demo scheduler and all other feeds remain offline.
        app = client.app
        app.state.gios = GiosService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), lambda: NOW)
        for kind, identity in [('stations', None), ('sensors', 9001), ('index', 9001), ('data', 9101)]:
            result = client.get('/api/gios', params={'kind': kind, **({'id': identity} if identity else {})})
            assert result.status_code == 200 and result.json()['status'] == 'ready'
        assert len(calls) == 4


@pytest.mark.asyncio
async def test_partial_records_cannot_replace_last_complete_snapshot():
    now, broken = [NOW], [False]
    def handler(request):
        payload = sample('data')
        if broken[0]:
            payload['Lista danych pomiarowych'].append({'Data': 'bad', 'Wartość': 'bad'})
        return httpx.Response(200, json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        first = await service.fetch('data', 9101)
        broken[0] = True
        now[0] += timedelta(minutes=31)
        result = await service.fetch('data', 9101)
        assert result['status'] == 'partial' and result['stale']
        assert result['fetched_at'] == first['fetched_at']
        assert result['latest']['value'] == first['latest']['value']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['data', 'sensors', 'index'])
@pytest.mark.parametrize('status', [400, 403, 404])
async def test_missing_resource_does_not_block_other_resources(kind, status):
    now, calls = [NOW], []
    valid_id = 9101 if kind == 'data' else 9001
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/999999'):
            return httpx.Response(status, json={'error_code': 'API-ERR-100001'})
        return response(kind)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        assert (await service.fetch(kind, 999999))['status'] == 'error'
        assert (await service.fetch(kind, valid_id))['status'] == 'ready'
        assert len(calls) == 2
        # Suppress repeated reads of only the missing resource; keep other cached data healthy.
        assert (await service.fetch(kind, 999999))['status'] == 'error'
        assert (await service.fetch(kind, valid_id))['status'] == 'ready'
        assert len(calls) == 2
        now[0] += timedelta(seconds=301)
        assert (await service.fetch(kind, 999999))['status'] == 'error'
        assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('delays', [(1200, 300), (300, 1200)])
async def test_concurrent_429_preserves_longest_retry_after(delays):
    now, calls = [NOW], []
    started = asyncio.Event()
    # Use different lock stripes so both upstream requests are genuinely in flight.
    identities = [1, next(i for i in range(2, 100) if hash(('data', i)) % 32 != hash(('data', 1)) % 32)]
    releases = {identity: asyncio.Event() for identity in identities}
    async def handler(request):
        calls.append(request)
        identity = int(request.url.path.rsplit('/', 1)[1])
        if len(calls) == 2:
            started.set()
        await releases[identity].wait()
        return httpx.Response(429, json={}, headers={'Retry-After': str(delays[identities.index(identity)])})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        tasks = [asyncio.create_task(service.fetch('data', identity)) for identity in identities]
        try:
            await asyncio.wait_for(started.wait(), 1)
            releases[identities[0]].set()
            await tasks[0]
            releases[identities[1]].set()
            await tasks[1]
        finally:
            for release in releases.values():
                release.set()
            await asyncio.gather(*tasks)
        assert service.retry_at['data'] == NOW+timedelta(seconds=1200)
        now[0] += timedelta(seconds=601)
        assert (await service.fetch('data', 999))['status'] == 'error'
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_index_shared_cache_and_service_backoff_for_viewport_clients():
    now, calls, failed = [NOW], [], [False]
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '1200'}) if failed[0] else response('index')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GiosService(client, lambda: now[0])
        results = await asyncio.gather(*(service.fetch('index', 9001) for _ in range(8)))
        assert len(calls) == 1 and all(r['items'][0]['value'] == 1 for r in results)
        now[0] += timedelta(minutes=29)
        assert (await service.fetch('index', 9001))['fetched_at'] == results[0]['fetched_at']
        assert len(calls) == 1
        now[0] += timedelta(minutes=2)
        failed[0] = True
        result = await service.fetch('index', 9001)
        assert result['stale'] and result['status'] == 'error'
        assert result['service_retry_after_seconds'] == 1200
        assert (await service.fetch('index', 53))['service_retry_after_seconds'] == 1200
        assert len(calls) == 2
