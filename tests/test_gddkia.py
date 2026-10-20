"""Synthetic XML contract, plan vs actuality, bounded fetch and honest stale fallbacks."""
import asyncio
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.gddkia import ENDPOINT, GddkiaService, parse_feed

NOW = datetime(2026,10,14,13,10,tzinfo=UTC)
FIXTURE = Path(__file__).parent/'fixtures/gddkia_synthetic.xml'


def record(**fields):
    base = {'typ':'U', 'nr_drogi':'A1', 'woj':'pomorskie', 'nazwa_odcinka':'Odcinek',
            'geo_lat':'53.5', 'geo_long':'18.6', 'data_powstania':'2026-10-01T08:00:00+0200',
            'data_likwidacji':'2026-10-14T12:00:00+0200', 'rodzaj':'<poz>U33</poz>',
            'objazd':'Opis zamknięcia pasa', 'skutki':'S07'}
    base.update(fields)
    return '<utr>'+''.join(f'<{k}>{v}</{k}>' for k,v in base.items())+'</utr>'


def feed(rows=None,generated='2026-10-14T15:08:02+0200'):
    return f'<utrudnienia gen="{generated}">{record() if rows is None else rows}</utrudnienia>'.encode()


def test_synthetic_fixture_mapping_effects_planned_end_and_missing_coords():
    data = parse_feed(FIXTURE.read_bytes())
    assert data['total'] == 5 and data['unmapped_count'] == 1 and data['invalid_count'] == 0
    assert data['source_generated_at'] == '2026-10-14T13:00:00+00:00'
    assert len(data['items']) == 4
    first, second, accident = data['items'][:3]
    assert first['cause'] == second['cause'] == 'Roboty drogowe'
    assert first['latitude'] == second['latitude'] and first['id'] != second['id']
    assert first['planned_end_at'] != second['planned_end_at']
    assert second['effects'] == ['Ruch dwukierunkowy','Ograniczenie prędkości: 80 km/h']
    assert accident['cause'] == 'Najechanie na urządzenie drogowe'
    assert accident['effects'] == ['Zablokowany pas ruchu']
    assert all(i['source_url'] == ENDPOINT for i in data['items'])


def test_missing_dates_invalid_dates_and_unknown_cause_are_never_invented():
    data = parse_feed(feed(record(data_powstania='',data_likwidacji='',rodzaj='<poz>NEW</poz>',
                                  skutki='',objazd='')))
    item = data['items'][0]
    assert item['planned_end_at'] is item['start_at'] is None
    assert item['cause'] == 'Roboty drogowe (kod NEW)' and item['effects'] == []
    bad = parse_feed(feed(record(data_likwidacji='2026-10-01',ogr_predkosc='nan',ogr_nosnosc='bad')))
    assert bad['items'][0]['planned_end_at'] is None and bad['invalid_count'] == 1
    bad = parse_feed(feed(record(data_likwidacji='9999-12-31T00:00:00Z')))
    assert bad['items'][0]['planned_end_at'] is None
    bad = parse_feed(feed(record(data_likwidacji='2025-10-01T00:00:00Z')))
    assert bad['items'][0]['planned_end_at'] is None and bad['invalid_count'] == 1


@pytest.mark.parametrize('lat,lon',[('',''),('nan','19'),('52','inf'),('0','0'),('48','19')])
def test_missing_and_bad_coordinates_never_create_fallback_point(lat,lon):
    data = parse_feed(feed(record(geo_lat=lat,geo_long=lon)))
    assert not data['items'] and data['unmapped_count'] == 1


@pytest.mark.parametrize('body',[b'<html/>',b'<utrudnienia><unknown/></utrudnienia>',
                                b'<!DOCTYPE x [<!ENTITY evil "x">]><utrudnienia/>',
                                b'<utrudnienia>',feed(record(nr_drogi='')),
                                feed('<utr/>'*5001)])
def test_wrong_truncated_or_hostile_xml_is_not_empty_success(body):
    with pytest.raises((ValueError,ET.ParseError)):
        parse_feed(body)


@pytest.mark.asyncio
async def test_cache_concurrency_304_and_plan_end_passed_remains_published():
    now, calls = [NOW], []
    def handler(request):
        calls.append(request)
        if request.url.path == '/robots.txt':
            return httpx.Response(200,text='User-agent: *\nAllow: /')
        assert str(request.url) == ENDPOINT
        if request.headers.get('if-none-match') == 'snapshot':
            return httpx.Response(304)
        return httpx.Response(200,content=feed(),headers={'ETag':'snapshot'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = GddkiaService(client,lambda:now[0])
        results = await asyncio.gather(*(svc.fetch() for _ in range(3)))
        assert len(calls) == 2 and all(r['status'] == 'success' and not r['stale'] for r in results)
        assert results[0]['items'][0]['planned_end_passed']
        now[0] += timedelta(minutes=6)
        result = await svc.fetch()
        assert len(calls) == 3 and len(result['items']) == 1
        assert result['source_generated_at'] == results[0]['source_generated_at']
        assert result['last_success_at'] == now[0].isoformat()
        now[0] += timedelta(hours=1)
        assert (await svc.fetch())['stale']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[503,403,429,302,'html','old','future','large'])
async def test_failure_retains_last_good_snapshot_and_backs_off(failure):
    now, calls, fail = [NOW], [], [False]
    def handler(request):
        calls.append(request)
        if request.url.path == '/robots.txt':
            return httpx.Response(200,text='User-agent: *\nAllow: /')
        if not fail[0]:
            return httpx.Response(200,content=feed())
        if isinstance(failure,int):
            return httpx.Response(failure,headers={'Retry-After':'900','Location':'https://evil.test'})
        if failure == 'old':
            return httpx.Response(200,content=feed(generated='2026-10-13T15:00:00+0200'))
        if failure == 'future':
            return httpx.Response(200,content=feed(generated='2026-10-15T15:00:00+0200'))
        if failure == 'large':
            return httpx.Response(200,content=b'x'*(2*1024*1024+1))
        return httpx.Response(200,text='<html>access denied</html>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
        svc = GddkiaService(client,lambda:now[0])
        first = await svc.fetch()
        now[0] += timedelta(minutes=6)
        fail[0] = True
        last = await svc.fetch()
        assert last['status'] == 'error' and last['stale']
        assert last['items'] == first['items'] and last['last_success_at'] == first['last_success_at']
        assert len(calls) == 3
        await svc.fetch()
        assert len(calls) == 3
        if failure == 429:
            now[0] += timedelta(minutes=6)
            await svc.fetch()
            assert len(calls) == 3


@pytest.mark.asyncio
async def test_disabled_demo_and_robots_denial_zero_feed_calls():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == '/robots.txt'
        return httpx.Response(200,text='User-agent: *\nDisallow: /')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for options in ({'demo':True},{'enabled':False}):
            assert (await GddkiaService(client,lambda:NOW,**options).fetch())['status'] == 'disabled'
        assert not calls
        assert (await GddkiaService(client,lambda:NOW).fetch())['status'] == 'error'
        assert len(calls) == 1


def test_api_demo_cross_site_and_missing_snapshot(tmp_path):
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        data = client.get('/api/gddkia').json()
        assert data['status'] == 'disabled' and data['items'] == []
        assert client.get('/api/gddkia',headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403


@pytest.mark.asyncio
async def test_empty_valid_feed_clears_snapshot_and_partial_records_are_explicit():
    now, payload = [NOW], [feed()]
    def handler(request):
        return (httpx.Response(404) if request.url.path == '/robots.txt' else
                httpx.Response(200,content=payload[0]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = GddkiaService(client,lambda:now[0])
        assert len((await svc.fetch())['items']) == 1
        now[0] += timedelta(minutes=6)
        payload[0] = feed(record()+record(nr_drogi=''))
        result = await svc.fetch()
        assert result['status'] == 'partial' and result['invalid_count'] == 1 and len(result['items']) == 1
        now[0] += timedelta(minutes=6)
        payload[0] = feed('')
        result = await svc.fetch()
        assert result['status'] == 'success' and not result['items']
