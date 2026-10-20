"""Controlled FIRMS transport, geometry, persistence and API contracts."""
import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.firms import PRODUCTS, fetch_fires, in_ring, parse_csv, province_at
from wici.repository import Repository
from wici.runtime import redact_firms_logs
from wici.scheduler import Scheduler

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
HEADER = 'latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp\n'
ROW = '52.23,21.01,2026-10-13,28,NOAA-20,VIIRS,n,12.5\n'
KEY = 'test-secret-never-print'


def test_httpx_log_redacts_secret_in_url(caplog):
    import logging
    redact_firms_logs(KEY)
    with caplog.at_level(logging.INFO, logger='httpx'):
        logging.getLogger('httpx').info('HTTP Request: GET %s', f'https://example.test/{KEY}/csv')
    assert KEY not in caplog.text
    assert '[REDACTED]' in caplog.text


def config():
    return Config(sources={'firms': {'map_key': KEY}})


def records():
    return parse_csv(HEADER + ROW, PRODUCTS[0])[0]


def test_csv_geometry_time_and_invalid():
    items, invalid = parse_csv(HEADER + ROW + '52,13,2026-10-13,0010,NOAA-20,VIIRS,h,1\n'
                               + 'nan,21,2026-10-13,1200,NOAA-20,VIIRS,h,1\n', PRODUCTS[0])
    assert len(items) == 1 and invalid == 1
    assert items[0]['observed_at'] == '2026-10-13T00:28:00+00:00'
    assert items[0]['voivodeship'] == '14'
    assert province_at(13,52) is None
    assert province_at(21.01,52.23)['name'] == 'mazowieckie'
    with pytest.raises(ValueError):
        parse_csv('Invalid MAP_KEY', PRODUCTS[0])
    for bad_time in ('', ' ', '１２', '12345'):
        bad_records, bad_count = parse_csv(HEADER+ROW.replace(',28,',f',{bad_time},'),PRODUCTS[0])
        assert bad_records == [] and bad_count == 1
    assert in_ring(1,1,[[0,0],[2,0],[2,2],[0,2],[0,0]])
    assert not in_ring(3,1,[[0,0],[2,0],[2,2],[0,2],[0,0]])


def test_persistent_dedupe_window_limit_and_dst(tmp_path):
    path = tmp_path/'db.sqlite3'
    repo = Repository(path,clock=lambda:NOW)
    assert repo.ingest_fires(records()) == 1
    assert repo.ingest_fires(records()) == 0
    item = records()[0]
    later = {**item,'id':'later','observed_at':'2026-10-13T10:00:00+00:00'}
    repo.ingest_fires([later])
    result = repo.list_fires(24,limit=1)
    assert result['total'] == 2 and result['limited']
    assert result['items'][0]['id'] == 'later'
    assert repo.list_fires(48,voivodeship='02')['total'] == 0
    assert repo.list_fires(24,selected_date='2026-10-12')['total'] == 0
    with pytest.raises(ValueError):
        repo.list_fires(12)
    with pytest.raises(ValueError):
        repo.list_fires(24,selected_date='2026-10-14')
    repo.close()
    repo = Repository(path,clock=lambda:datetime(2026,11,1,tzinfo=UTC))
    assert repo.db.execute('SELECT COUNT(*) FROM fire_observations').fetchone()[0] == 2
    dst = repo.list_fires(24,selected_date='2026-10-25')
    assert dst['window_end'] == '2026-10-25T23:00:00+00:00'
    assert dst['window_start'] == '2026-10-24T23:00:00+00:00'
    repo.close()


@pytest.mark.asyncio
async def test_partial_failure_keeps_data_redacts_and_recovers(tmp_path):
    calls = []
    failing = True
    def handler(request):
        calls.append(request)
        if PRODUCTS[1] in str(request.url) and failing:
            raise httpx.ConnectError(str(request.url),request=request)
        return httpx.Response(200,text=HEADER+ROW)
    repo = Repository(tmp_path/'db',clock=lambda:NOW)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scheduler = Scheduler(repo,config(),client)
        await scheduler.fetch('firms')
        assert len(calls) == 3
        assert all('/3/2026-10-11' in str(request.url) for request in calls)
        assert repo.list_fires()['total'] == 2
        state = next(x for x in scheduler.sources() if x['id']=='firms')
        assert state['last_result'] == 'partial'
        assert KEY not in json.dumps(state)
        assert not state['last_successful_check']
        failing = False
        await scheduler.fetch('firms')
        assert repo.list_fires()['total'] == 3
        assert next(x for x in scheduler.sources() if x['id']=='firms')['last_result'] == 'success'
    repo.close()


@pytest.mark.asyncio
async def test_denied_retry_and_missing_key(tmp_path):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(403,text=KEY)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await fetch_fires(client,config(),NOW)
        assert response.availability == 'blocked_access'
        assert KEY not in repr(response)
        retry = await fetch_fires(httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r:httpx.Response(429,headers={'retry-after':'7200'}))),config(),NOW)
        assert retry.retry_after == 7200
        repo = Repository(tmp_path/'db')
        scheduler = Scheduler(repo,Config(),client)
        await scheduler.fetch('firms')
        assert count == 3
        with pytest.raises(ValueError):
            scheduler.refresh('firms')
        assert next(x for x in scheduler.sources() if x['id']=='firms')['access_state'] == 'disabled_by_user'
        repo.close()
    assert KEY not in repr(config()) and KEY not in config().model_dump_json()


def test_demo_no_network_api_separation(tmp_path):
    def handler(request):
        raise AssertionError('Demo must never fetch FIRMS')
    with TestClient(create_app(demo=True,root=tmp_path,config=config(),
                    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
                    base_url='http://127.0.0.1:8765') as client:
        data = client.get('/api/fires?hours=48').json()
        assert data['items'] == [] and data['hours'] == 48
        assert client.get('/api/fires?hours=12').status_code == 422
        assert client.get('/api/fires?date=broken').status_code == 422
        assert all(row['source_id'] != 'firms' for row in client.get('/api/communications').json()['items'])
        status = client.get('/api/sources').json()
        assert KEY not in json.dumps(status)


@pytest.mark.asyncio
async def test_persistence_failure_does_not_mark_success(tmp_path,monkeypatch):
    repo = Repository(tmp_path/'db',clock=lambda:NOW)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=HEADER+ROW))) as client:
        scheduler = Scheduler(repo,config(),client)
        def fail(records):
            raise RuntimeError(KEY)
        monkeypatch.setattr(repo,'ingest_fires',fail)
        await scheduler.fetch('firms')
        status = next(x for x in scheduler.sources() if x['id']=='firms')
        assert status['last_result'] == 'error' and status['last_successful_check'] is None
        assert KEY not in json.dumps(status)
    repo.close()
