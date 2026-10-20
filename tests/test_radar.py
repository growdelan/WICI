"""Fixed upstream, recent frames, bounded cache and honest radar failure states."""
import asyncio
import json
import struct
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.radar import HOST, MANIFEST, RadarService, RadarUnavailable, parse_manifest, tile_allowed

NOW = datetime(2026,10,14,15,0,tzinfo=UTC)
STAMP = int(NOW.timestamp())
PNG = b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+struct.pack('>II',256,256)+b'\x08\x06\x00\x00\x00'+b'abcd'+b'\x00\x00\x00\x00IEND\xaeB`\x82'


def manifest(**updates):
    return {'host':HOST, 'radar':{'past':[{'time':STAMP-600,'path':'/v2/radar/abcdef'},
                                        {'time':STAMP,'path':'/v2/radar/hash_123'}]}, **updates}


@pytest.mark.parametrize('payload',[
    manifest(host='https://attacker.test'),manifest(radar={'past':[]}),
    manifest(radar={'past':[{'time':STAMP,'path':'/v2/radar/../../secret'}]}),
    manifest(radar={'past':[{'time':STAMP,'path':'https://attacker.test'}]}),
    manifest(radar={'past':[{'time':True,'path':'/v2/radar/x'}]}),
    manifest(radar={'past':[{'time':STAMP-4*3600,'path':'/v2/radar/x'}]}),
    manifest(radar={'past':[{'time':STAMP+3600,'path':'/v2/radar/x'}]}),
    manifest(radar={'past':[{'time':STAMP,'path':'/v2/radar/x'}]*2}),
])
def test_manifest_rejects_untrusted_or_invalid_frames(payload):
    with pytest.raises((ValueError,TypeError)):
        parse_manifest(payload,NOW)


def test_poland_native_tile_bound_limits_complete_animation():
    assert tile_allowed(5,17,10) and tile_allowed(6,34,20)
    assert not tile_allowed(7,70,42) and not tile_allowed(6,0,0)
    assert sum(tile_allowed(6,x,y) for x in range(64) for y in range(64)) == 6


async def test_cache_lock_paths_and_expiry():
    now,calls=[NOW],[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,json=manifest()) if str(request.url)==MANIFEST else httpx.Response(200,content=PNG,headers={'content-type':'image/png'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=RadarService(client,lambda:now[0])
        data=await service.metadata()
        assert data['status']=='success' and not data['stale'] and len(data['frames'])==2
        images=await asyncio.gather(*(service.tile(STAMP,5,17,10) for _ in range(3)))
        assert images==[PNG]*3 and len(calls)==2
        assert '/v2/radar/hash_123/256/5/17/10/2/1_0.png' in calls[1]
        await service.metadata();assert len(calls)==2
        with pytest.raises(ValueError):await service.tile(STAMP+1,5,17,10)
        now[0]+=timedelta(hours=4)
        with pytest.raises(ValueError):await service.tile(STAMP,5,17,10)


async def test_failed_refresh_retains_stale_and_429_delays_all_requests():
    now,calls=[NOW],[]
    def handler(request):
        calls.append(str(request.url))
        if len(calls)==1:return httpx.Response(200,json=manifest())
        return httpx.Response(429,headers={'retry-after':'900'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=RadarService(client,lambda:now[0]);first=await service.metadata()
        now[0]+=timedelta(minutes=5);failed=await service.metadata()
        assert failed['frames']==first['frames'] and failed['status']=='error' and failed['stale']
        with pytest.raises(RadarUnavailable):await service.tile(STAMP,5,17,10)
        assert len(calls)==2
        assert service.blocked_until==now[0]+timedelta(minutes=15)


async def test_local_budget_and_demo_never_fetch():
    calls=[]
    def handler(request):
        calls.append(str(request.url));return httpx.Response(200,json=manifest())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=RadarService(client,lambda:NOW,demo=True)
        assert not (await service.metadata())['enabled']
        with pytest.raises(RadarUnavailable):await service.tile(STAMP,5,17,10)
        assert not calls
        service=RadarService(client,lambda:NOW);service.calls.extend([NOW]*90)
        assert (await service.metadata())['status']=='error' and not calls


@pytest.mark.parametrize('body,type_',[(b'<html/>','text/html'),(PNG[:-1],'image/png'),(b'x'*524289,'image/png')])
async def test_bad_or_oversized_image_never_served(body,type_):
    def handler(request):
        return httpx.Response(200,json=manifest()) if str(request.url)==MANIFEST else httpx.Response(200,content=body,headers={'content-type':type_})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=RadarService(client,lambda:NOW)
        with pytest.raises(RadarUnavailable):await service.tile(STAMP,5,17,10)
        assert not service.tiles


def test_api_demo_origin_and_no_upstream_urls(tmp_path):
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        data=client.get('/api/radar').json()
        assert not data['enabled'] and not data['frames']
        assert client.get('/api/radar',headers={'sec-fetch-site':'cross-site'}).status_code==403
        assert client.get(f'/api/radar/tiles/{STAMP}/5/17/10.png').status_code==503
        assert 'tilecache' not in json.dumps(data)


async def test_transport_failure_backs_off_other_tiles():
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        if str(request.url)==MANIFEST:return httpx.Response(200,json=manifest())
        raise httpx.ReadTimeout('offline',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=RadarService(client,lambda:NOW)
        with pytest.raises(RadarUnavailable):await service.tile(STAMP,6,34,20)
        with pytest.raises(RadarUnavailable):await service.tile(STAMP,6,35,20)
        assert len(calls)==2 and service.blocked_until==NOW+timedelta(seconds=30)
