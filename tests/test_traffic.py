"""Quota survives restarts; raster proxy never exposes credentials or follows redirects."""
import asyncio
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.traffic import (
    ENDPOINT,
    MONTHLY_LIMIT,
    ROAD_ENDPOINT,
    RoadService,
    TrafficService,
    TrafficUnavailable,
    tile_in_poland,
)

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
KEY = 'test-secret-do-not-expose'
TILE = (10, 571, 337)  # Warsaw.


def png():
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',256,256,8,6,0,0,0))
            +chunk(b'IDAT',zlib.compress((b'\x00'+bytes([42,229,123,255])*256)*256))+chunk(b'IEND',b''))


@pytest.mark.asyncio
async def test_proxy_header_auth_cache_concurrency_and_persistent_quota(tmp_path):
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(ENDPOINT+'/10/571/337?')
        assert KEY not in str(request.url)
        assert request.headers['TomTom-Api-Key'] == KEY
        assert dict(request.url.params) == {'apiVersion':'2','style':'light','tileSize':'256'}
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png','Cache-Control':'max-age=60'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path = tmp_path/'usage.json'
        service = TrafficService(client,lambda:now[0],path,key=KEY,enabled=True)
        assert service.metadata()['requests_used'] == 0 and len(calls) == 0
        bodies = await asyncio.gather(*(service.tile(*TILE) for _ in range(4)))
        assert bodies == [png()]*4 and len(calls) == 1
        assert service.metadata()['requests_used'] == 1
        assert service.metadata()['last_fetch_at'] == NOW.isoformat()
        now[0] += timedelta(seconds=61)
        await service.tile(*TILE)
        assert len(calls) == 2
        restarted = TrafficService(client,lambda:now[0],path,key=KEY,enabled=True)
        assert restarted.metadata()['requests_used'] == 2
        assert KEY not in path.read_text() and KEY not in str(service.metadata())


@pytest.mark.asyncio
async def test_limit_restart_and_new_month(tmp_path):
    path, calls, now = tmp_path/'usage.json', [], [NOW]
    path.write_text(json.dumps({'month':'2026-10','requests_used':MONTHLY_LIMIT-1}))
    def handler(request):
        calls.append(request)
        return httpx.Response(200,content=png(),headers={'Content-Type':'image/png'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = TrafficService(client,lambda:now[0],path,key=KEY,enabled=True)
        await service.tile(*TILE)
        with pytest.raises(TrafficUnavailable,match='limit miesięczny'):
            await service.tile(*TILE)
        restarted = TrafficService(client,lambda:now[0],path,key=KEY,enabled=True)
        assert restarted.metadata()['status'] == 'limit' and len(calls) == 1
        now[0] = datetime(2026,11,1,tzinfo=UTC)
        await restarted.tile(*TILE)
        assert restarted.metadata()['requests_used'] == 1 and len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,headers',[
    (302,b'',{'Location':'https://evil.test'}),
    (403,KEY.encode(),{}),
    (429,b'',{'Retry-After':'600'}),
    (200,b'<html>not a tile</html>',{'Content-Type':'image/png'}),
    (200,png()[:-8],{'Content-Type':'image/png'}),
    (200,b'x'*(1024*1024+1),{'Content-Type':'image/png'}),
])
async def test_errors_redacted_counted_and_cooldown(tmp_path,status,body,headers):
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,content=body,headers=headers)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
        service = TrafficService(client,lambda:now[0],tmp_path/'usage.json',key=KEY,enabled=True)
        for _ in range(2):
            with pytest.raises(TrafficUnavailable) as exc:
                await service.tile(*TILE)
            assert KEY not in str(exc.value)
        assert len(calls) == 1 and service.used == 1
        assert service.metadata()['status'] == 'error'
        now[0] += timedelta(seconds=301)
        if status == 429:
            assert service.metadata()['status'] == 'error'
        else:
            assert service.metadata()['status'] == 'ready'


@pytest.mark.asyncio
async def test_no_network_for_demo_disabled_corrupt_quota_and_invalid_tiles(tmp_path):
    def forbidden(request):
        pytest.fail('Unexpected network')
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        for options in ({'demo':True,'enabled':True,'key':KEY},{'enabled':False,'key':KEY},{'enabled':True}):
            service = TrafficService(client,lambda:NOW,tmp_path/'usage.json',**options)
            assert service.metadata()['status'] == 'disabled'
            with pytest.raises(TrafficUnavailable):
                await service.tile(*TILE)
        path = tmp_path/'corrupt.json'
        path.write_text('{broken')
        service = TrafficService(client,lambda:NOW,path,key=KEY,enabled=True)
        assert service.metadata()['status'] == 'error'
        with pytest.raises(TrafficUnavailable):
            await service.tile(*TILE)
        for coords in [(5,1,1),(19,1,1),(10,-1,1),(10,1024,1),(10,0,0)]:
            with pytest.raises(ValueError):
                await service.tile(*coords)
        assert tile_in_poland(*TILE)


@pytest.mark.asyncio
async def test_counter_write_failure_stops_before_network(tmp_path):
    def forbidden(request):
        pytest.fail('Unexpected network')
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        service = TrafficService(client,lambda:NOW,tmp_path/'usage.json',key=KEY,enabled=True)
        (tmp_path/'usage.tmp').mkdir()
        with pytest.raises(TrafficUnavailable,match='zapisać licznika'):
            await service.tile(*TILE)
        assert service.metadata()['status'] == 'error'


def test_config_secrets_and_demo_api(tmp_path):
    config = Config.model_validate({'sources':{'tomtom':{'enabled':True,'api_key':KEY}}})
    assert KEY not in repr(config) and config.tomtom_key() == KEY
    with TestClient(create_app(demo=True,root=tmp_path,config=config),base_url='http://127.0.0.1:8765') as client:
        response = client.get('/api/traffic')
        assert response.json()['status'] == 'disabled' and KEY not in response.text
        assert client.get('/api/traffic/tiles/10/571/337.png').status_code == 503
        assert client.get('/api/traffic/tiles/10/571/337.png',headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
        assert client.get('/api/traffic/tiles/5/1/1.png').status_code == 422
        assert not (tmp_path/'var/demo/tomtom-usage.json').exists()
        assert client.get('/api/traffic/road?lat=52&lon=19').status_code == 503
        assert client.get('/api/traffic/road?lat=nan&lon=19').status_code == 422
        assert client.get('/api/traffic/road?lat=52&lon=19',headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403


@pytest.mark.asyncio
async def test_road_identity_without_house_data_header_auth_and_separate_quota(tmp_path):
    calls = []
    payload = {'results':[{'type':'street','address':{'countryCodeIso2':'PL','street':'Autostrada A1',
                           'routeNumbers':['A1','E75','A1'],'houseNumber':'42','postalCode':'00-001'}}]}
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(ROAD_ENDPOINT+'?')
        assert request.url.params['position'] == '19.614600,52.072900'
        assert request.url.params['radiusInMeters'] == '250'
        assert request.headers['TomTom-Api-Key'] == KEY
        assert request.headers['TomTom-Api-Version'] == '2'
        assert KEY not in str(request.url)
        return httpx.Response(200,json=payload)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path = tmp_path/'road-usage.json'
        road = RoadService(client,lambda:NOW,path,key=KEY,enabled=True,monthly_limit=19_000)
        result = await road.lookup(52.0729,19.6146)
        assert result == {'found':True,'name':'Autostrada A1','symbols':['A1','E75'],'source':'TomTom','radius_m':250}
        assert 'houseNumber' not in str(result) and 'postalCode' not in str(result)
        assert road.used == 1 and not (tmp_path/'tomtom-usage.json').exists()
        restarted = RoadService(client,lambda:NOW,path,key=KEY,enabled=True,monthly_limit=19_000)
        assert restarted.used == 1
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[
    {'results':[]},
    {'results':[{'type':'area','address':{'street':'Not a road'}}]},
    {'results':[{'type':'street','address':{'countryCodeIso2':'DE','street':'Ausland'}}]},
])
async def test_road_not_found_without_inventing_identity(tmp_path,payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as client:
        road = RoadService(client,lambda:NOW,tmp_path/'usage.json',key=KEY,enabled=True,monthly_limit=19_000)
        assert not (await road.lookup(52,19))['found']


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[302,429])
async def test_road_errors_cooldown_limits_and_validation(tmp_path,status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status,headers={'Location':'https://evil.test/'+KEY,'Retry-After':'600'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
        road = RoadService(client,lambda:NOW,tmp_path/'road.json',key=KEY,enabled=True,monthly_limit=19_000)
        for _ in range(2):
            with pytest.raises(TrafficUnavailable) as exc:
                await road.lookup(52,19)
            assert KEY not in str(exc.value)
        assert len(calls) == 1 and road.used == 1
        assert road.retry_at == NOW+timedelta(seconds=600 if status == 429 else 300)
        for lat,lon in [(float('nan'),19),(52,float('inf')),(48,19),(52,25)]:
            with pytest.raises(ValueError):
                await road.lookup(lat,lon)
        road.retry_at = None
        road.used = 19_000
        with pytest.raises(TrafficUnavailable,match='limit miesięczny'):
            await road.lookup(52,19)
        assert len(calls) == 1
