"""Synthetic hydrology records and offline transport/failure contracts for the map service."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.hydro import MAX_BYTES, HydroService, stations, warning_time, warnings

NOW = datetime(2026, 10, 17, 6, tzinfo=UTC)
FIXTURES = Path(__file__).parent/'fixtures/imgw_hydro'


def fixture(kind):
    return json.loads((FIXTURES/(kind+'.json')).read_text())


def test_synthetic_records_units_locations_separate_age_and_missing_values():
    items, rejected = stations(fixture('hydro'), NOW)
    assert len(items) == 5 and rejected == 0
    station = items[0]
    assert station['name'] == 'Stacja Testowa 0' and station['river'] == 'Rzeka Testowa'
    assert station['latitude'] == 52.1 and station['longitude'] == 19.2
    assert station['measurements']['water_level']['value'] == 200
    assert station['measurements']['water_level']['unit'] == 'cm'
    assert station['threshold_status'] == 'below_warning'
    assert station['measurements']['discharge']['value'] == .5
    assert station['measurements']['discharge']['status'] == 'stale'
    assert station['measurements']['temperature']['status'] == 'missing'


def test_synthetic_warning_time_matches_explicit_expected_offset_and_indefinite_drought():
    items, rejected = warnings(fixture('warningshydro'), NOW)
    assert not rejected
    drought = next(i for i in items if i['severity_code'] == '-1')
    assert drought['severity'] is None and drought['open_ended'] and drought['valid_until'] is None
    assert drought['status'] == 'active' and drought['areas'][0]['basin_codes']
    warning = next(i for i in items if i['number'] == '901')
    assert warning['valid_from'] == '2026-10-16T17:00:00+00:00'
    assert warning['valid_until'] == '2026-10-18T16:00:00+00:00'
    assert warning['published_at'] == '2026-10-16T16:00:00+00:00'
    assert warning['severity'] == 1 and warning['probability_percent'] == 60
    assert warning['description'] and warning['comment'] and warning['status'] == 'active'
    assert 'pomorskie' in [a['province'] for a in warning['areas']]
    assert warnings(fixture('warningshydro'), NOW+timedelta(days=3))[0][-1]['status'] == 'expired'


def test_station_validation_thresholds_and_no_fabricated_coordinates():
    row = fixture('hydro')[0]
    items, rejected = stations([None, {}, row, row, {**row, 'id_stacji': 'other', 'lat': 'nan',
        'stan_wody': '340', 'przeplyw': True, 'temperatura_wody': 'inf'}], NOW)
    assert rejected == 3 and len(items) == 2
    assert items[1]['latitude'] is None and items[1]['longitude'] is None
    assert items[1]['threshold_status'] == 'alarm'
    assert items[1]['measurements']['discharge']['value'] is None
    assert stations([{**row, 'stan_wody': '300'}], NOW)[0][0]['threshold_status'] == 'warning'
    assert stations([row], NOW+timedelta(hours=4))[0][0]['threshold_status'] == 'unknown'
    assert stations([row], NOW-timedelta(days=1))[0][0]['measurements']['water_level']['status'] == 'future'
    assert stations([{**row, 'stan_wody_data_pomiaru': 'invalid'}], NOW)[0][0]['measurements']['water_level']['status'] == 'missing_time'


def test_warning_unknown_dates_dst_dedup_and_future_validity():
    row = fixture('warningshydro')[-1]
    assert warning_time('2026-10-25 02:30:00') is None  # ambiguous fall hour
    assert warning_time('2026-03-29 02:30:00') is None  # missing spring hour
    assert warning_time('invalid') is None
    assert warning_time('2026-10-17T05:00:00Z').hour == 5
    items, rejected = warnings([None, {}, row, row, {**row, 'data_od': 'bad'}], NOW)
    assert rejected == 2 and len(items) == 2
    assert {i['status'] for i in items} == {'active', 'unknown'}
    assert warnings([row], NOW-timedelta(days=2))[0][0]['status'] == 'upcoming'
    assert warnings([{**row, 'data_do': '2020-01-01 00:00:00'}], NOW)[0][0]['status'] == 'unknown'


@pytest.mark.asyncio
async def test_concurrent_cache_independent_feeds_recompute_age_and_empty_lists():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=fixture('hydro') if '/hydro/' in request.url.path else [])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HydroService(client, lambda: now[0])
        assert calls == []
        results = await asyncio.gather(*(service.fetch() for _ in range(4)))
        assert len(calls) == 1 and results[0] == results[-1]
        assert (await service.fetch('warnings'))['status'] == 'empty'
        assert len(calls) == 2
        # Age is recalculated even during the five-minute cache lifetime.
        now[0] = NOW+timedelta(hours=2, minutes=19)
        await service.fetch()
        now[0] += timedelta(minutes=2)
        assert (await service.fetch())['items'][0]['measurements']['water_level']['status'] == 'stale'
        assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', '429', 'bad_json', 'wrong_schema', 'redirect', 'html', 'oversized'])
async def test_failure_retains_snapshot_and_backs_off(failure):
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=fixture('hydro'))
        if failure == 'timeout':
            raise httpx.ReadTimeout('private upstream details')
        return {'429': lambda: httpx.Response(429, headers={'Retry-After': '1200'}),
                'bad_json': lambda: httpx.Response(200, content=b'{', headers={'Content-Type': 'application/json'}),
                'wrong_schema': lambda: httpx.Response(200, json=[{'unexpected': 1}]),
                'redirect': lambda: httpx.Response(302, headers={'Location': 'https://bad.test'}),
                'html': lambda: httpx.Response(200, text='<html>private upstream details</html>'),
                'oversized': lambda: httpx.Response(200, content=b' '*(MAX_BYTES+1), headers={'Content-Type': 'application/json'})}[failure]()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        service = HydroService(client, lambda: now[0])
        first = await service.fetch()
        now[0] += timedelta(seconds=301)
        failed = await service.fetch()
        assert failed['status'] == 'error' and failed['stale']
        assert failed['fetched_at'] == first['fetched_at'] and len(failed['items']) == 5
        assert failed['items'][0]['threshold_status'] == 'unknown'
        assert 'private' not in str(failed)
        await service.fetch()
        assert len(calls) == 2
        now[0] += timedelta(seconds=301)
        await service.fetch()
        assert len(calls) == (2 if failure == '429' else 3)


@pytest.mark.asyncio
async def test_partial_empty_missing_disabled_demo_and_retry_recovery():
    now, calls = [NOW], []
    responses = [httpx.Response(503), httpx.Response(200, json=fixture('hydro')+[{}]), httpx.Response(200, json=[])]
    def handler(request):
        calls.append(request)
        return responses.pop(0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for kwargs in ({'demo': True}, {'enabled': False}):
            service = HydroService(client, lambda: now[0], **kwargs)
            assert (await service.fetch())['status'] == 'disabled'
            assert not calls
        service = HydroService(client, lambda: now[0])
        result = await service.fetch()
        assert result['status'] == 'error' and not result['items'] and not result['stale']
        now[0] += timedelta(seconds=301)
        result = await service.fetch()
        assert result['status'] == 'partial' and result['rejected_count'] == 1
        now[0] += timedelta(seconds=301)
        assert (await service.fetch())['status'] == 'empty'
        with pytest.raises(ValueError):
            await service.fetch('other')


def test_api_demo_local_guard_validation_and_static_wiring(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path, config=Config()), base_url='http://127.0.0.1:8765') as client:
        for kind in ('stations', 'warnings'):
            data = client.get('/api/hydro', params={'kind': kind}).json()
            assert data['status'] == 'disabled' and data['demo'] and not data['items']
        assert client.get('/api/hydro?kind=other').status_code == 422
        assert client.get('/api/hydro', headers={'Origin': 'https://bad.test'}).status_code == 403
        assert client.get('/api/hydro', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        html = client.get('/').text
        assert 'id="hydro-stations"' in html and 'id="hydro-warnings"' in html
        assert '/static/js/hydro.js' in html
