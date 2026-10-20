"""LI AFA times, validated imagery, caching and honest empty/delayed observations."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from test_effis import png

from wici.app import create_app
from wici.lightning import ENDPOINT, LightningService, LightningUnavailable, parse_times

NOW = datetime(2026,10,14,15,25,tzinfo=UTC)


def capabilities(dimension='2025-05-30T15:00:00Z/2026-10-14T15:20:00Z/PT5M'):
    return f'<WMS_Capabilities xmlns="http://www.opengis.net/wms"><Layer><Name>mtg_fd:li_afa</Name><Dimension name="time">{dimension}</Dimension></Layer></WMS_Capabilities>'.encode()


@pytest.mark.parametrize('dimension',[
    '2026-10-14T15:20:00', '2026-10-14T18:00:00Z', '2026-10-14T10:00:00Z',
    '2026-10-14T15:00:00Z/2026-10-14T15:20:00Z/PT10M', '',
])
def test_invalid_times_rejected(dimension):
    with pytest.raises(ValueError):parse_times(capabilities(dimension),NOW)


def test_periods_are_source_start_times_and_entities_rejected():
    times=parse_times(capabilities(),NOW)
    assert len(times)==13 and times[-1]==NOW-timedelta(minutes=5)
    assert times[-1]-times[0]==timedelta(hours=1)
    with pytest.raises(ValueError):parse_times(b'<!DOCTYPE x>'+capabilities(),NOW)
    with pytest.raises(ValueError):parse_times(capabilities().replace(b'mtg_fd:li_afa',b'other'),NOW)


@pytest.mark.parametrize('alpha',[0,255])
async def test_fixed_no_key_images_and_click_share_validated_cache(alpha):
    calls=[]
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(ENDPOINT+'?')
        assert 'authorization' not in request.headers
        return httpx.Response(200,content=capabilities() if request.url.params['REQUEST']=='GetCapabilities' else png(alpha=alpha))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=LightningService(client,lambda:NOW)
        data=await service.metadata();stamp=data['frames'][-1]['timestamp']
        assert data['delay_minutes']==0 and not data['stale']
        assert data['latest_end']==NOW.isoformat()
        await asyncio.gather(*(service.image(stamp) for _ in range(3)))
        point=await service.point(stamp,52,19)
        assert point['visible_activity']==bool(alpha) and len(calls)==2
        assert 'count' not in point and 'strike' not in point
        params=calls[-1].url.params
        assert params['CRS']=='EPSG:3857' and params['TIME']==data['frames'][-1]['time'].replace('+00:00','Z')
        assert params['TRANSPARENT']=='true'
        await service.legend_image();await service.legend_image();assert len(calls)==3
        with pytest.raises(ValueError):await service.point(stamp,float('nan'),19)
        with pytest.raises(ValueError):await service.image(stamp+1)


async def test_delayed_and_failed_refresh_retains_last_image_with_retry_after():
    now,calls=[NOW],[]
    def handler(request):
        calls.append(request)
        if len(calls)>2:return httpx.Response(429,headers={'retry-after':'900'})
        return httpx.Response(200,content=capabilities() if len(calls)==1 else png())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=LightningService(client,lambda:now[0]);first=await service.metadata()
        stamp=first['frames'][-1]['timestamp'];image=await service.image(stamp)
        now[0]+=timedelta(minutes=25);failed=await service.metadata()
        assert failed['frames']==first['frames'] and failed['stale'] and failed['delay_minutes']==25
        assert await service.image(stamp)==image
        assert service.blocked_until==now[0]+timedelta(minutes=15)
        with pytest.raises(LightningUnavailable):await service.image(first['frames'][0]['timestamp'])
        assert len(calls)==3


@pytest.mark.parametrize('body',[b'<html/>',png()[:-1],png(10,10),b'x'*(4*1024*1024+1)])
async def test_invalid_image_not_cached(body):
    def handler(request):
        return httpx.Response(200,content=capabilities() if request.url.params['REQUEST']=='GetCapabilities' else body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=LightningService(client,lambda:NOW);data=await service.metadata()
        with pytest.raises(LightningUnavailable):await service.image(data['frames'][-1]['timestamp'])
        assert not service.images


def test_demo_and_cross_origin(tmp_path):
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        assert not client.get('/api/lightning').json()['enabled']
        assert client.get('/api/lightning',headers={'sec-fetch-site':'cross-site'}).status_code==403
        assert client.get('/api/lightning/map?time=1').status_code==503
        assert client.get('/api/lightning/legend').status_code==503
