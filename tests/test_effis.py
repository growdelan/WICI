"""Forecast dates, fixed WMS proxy, honest availability and bounded cache contracts."""
import struct
import zlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.effis import ENDPOINT, HEIGHT, LAYER, WIDTH, EffisService, decode_png, parse_capabilities

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
CAPABILITIES = b'''<WMT_MS_Capabilities><Capability><Layer><Layer><Name>ecmwf.fwi</Name>
<Extent name="time">2018-01-01/2099-12-31</Extent></Layer></Layer></Capability></WMT_MS_Capabilities>'''


def png(width=WIDTH, height=HEIGHT, alpha=255, filtering=0):
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    pixel = bytes([25,100,10,alpha])
    if filtering == 0:
        row = b'\x00'+pixel*width
    else:  # Sub filter: same pixels after the first are all zero deltas.
        row = b'\x01'+pixel+b'\x00'*(4*(width-1))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))
            +chunk(b'IDAT',zlib.compress(row*height))+chunk(b'IEND',b''))


def responses(calls, map_body=None):
    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(ENDPOINT+'?')
        kind = request.url.params['REQUEST']
        if kind == 'GetCapabilities':
            return httpx.Response(200,content=CAPABILITIES)
        if kind == 'GetLegendGraphic':
            return httpx.Response(200,content=png(146,95))
        return httpx.Response(200,content=map_body if map_body is not None else png())
    return handler


@pytest.mark.asyncio
async def test_fixed_wms_params_local_metadata_cache_and_expiry():
    calls, now = [], [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(responses(calls))) as client:
        service = EffisService(client,lambda:now[0])
        for offset in range(3):
            day = NOW.date()+timedelta(days=offset)
            metadata = await service.metadata(day)
            assert metadata['available'] and metadata['issued_at'] is None
            assert metadata['forecast_date'] == day.isoformat()
            assert metadata['image_url'] == f'/api/effis/map?day={day}'
            assert metadata['legend_url'] == f'/api/effis/legend?day={day}'
            assert metadata['fetched_at'] == NOW.isoformat()
            assert await service.map_image(day) == png()
        assert len(calls) == 5  # shared capabilities and legend; one image per date.
        maps = [r for r in calls if r.url.params['REQUEST'] == 'GetMap']
        assert all(r.url.params['SRS'] == 'EPSG:3857' and r.url.params['LAYERS'] == LAYER for r in maps)
        assert float(maps[0].url.params['BBOX'].split(',')[1]) > 6_000_000
        assert await service.legend_image() == png(146,95)
        now[0] += timedelta(hours=1,seconds=1)
        assert (await service.metadata())['fetched_at'] == now[0].isoformat()
        assert len(calls) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_body',[b'<ServiceException>missing time</ServiceException>',
                                      png(alpha=0), png()[:-8], png(2,2)])
async def test_invalid_or_blank_forecast_never_available_and_failure_cooldown(bad_body):
    calls, now = [], [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(responses(calls,bad_body))) as client:
        service = EffisService(client,lambda:now[0])
        result = await service.metadata()
        assert not result['available'] and result['status'] == 'error'
        assert result['image_url'] is None and result['fetched_at'] is None
        assert await service.map_image() is None
        assert len(calls) == 2
        now[0] += timedelta(minutes=6)
        await service.metadata()
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_provider_time_not_advertised_no_map_request():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200,content=CAPABILITIES.replace(b'2018-01-01/2099-12-31',b'2026-10-12'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = EffisService(client,lambda:NOW)
        assert not (await service.metadata())['available']
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_transport_retry_bounded_and_redirect_refused():
    calls = []
    def reject(request):
        calls.append(request)
        raise httpx.RemoteProtocolError('Truncated response')
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        service = EffisService(client,lambda:NOW)
        assert not (await service.metadata())['available']
        assert len(calls) == 2
    calls.clear()
    def redirect(request):
        calls.append(request)
        return httpx.Response(302,headers={'Location':'https://attacker.test/'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect),follow_redirects=True) as client:
        assert not (await EffisService(client,lambda:NOW).metadata())['available']
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_response_size_bounded():
    def oversized(request):
        return httpx.Response(200,content=b'x'*(1024*1024+1))
    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        assert not (await EffisService(client,lambda:NOW).metadata())['available']


def test_decode_crc_and_filter_and_entity_guard():
    assert decode_png(png(2,2,filtering=1))[3] == [bytes([25,100,10,255])*2]*2
    corrupt = bytearray(png(2,2)); corrupt[20] ^= 1
    with pytest.raises(ValueError):
        decode_png(bytes(corrupt))
    with pytest.raises(ValueError):
        parse_capabilities(b'<!DOCTYPE x [<!ENTITY x "bomb">]><x>&x;</x>')


@pytest.mark.asyncio
async def test_warsaw_midnight_date_validation_and_demo_zero_network():
    def forbidden(request):
        pytest.fail('Demo must never access network')
    now = datetime(2026,10,13,23,30,tzinfo=UTC)  # 14 October in Warsaw.
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        service = EffisService(client,lambda:now,demo=True)
        assert (await service.metadata())['forecast_date'] == '2026-10-14'
        assert (await service.metadata())['status'] == 'disabled'
        for day in ('2026-10-13','2026-10-17'):
            with pytest.raises(ValueError):
                await service.metadata(datetime.fromisoformat(day).date())
        assert await service.map_image() is None
        assert await service.legend_image() is None


def test_api_demo_and_invalid_dates(tmp_path):
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        data = client.get('/api/effis').json()
        assert data['status'] == 'disabled' and not data['available']
        assert client.get('/api/effis/map').status_code == 503
        assert client.get('/api/effis/legend').status_code == 503
        assert client.get('/api/effis?day=1999-01-01').status_code == 422
        assert client.get('/api/effis?day=https://evil.test').status_code == 422


@pytest.mark.asyncio
async def test_map_bundle_keeps_legend_when_shared_cache_expires():
    calls, now = [], [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(responses(calls))) as client:
        service = EffisService(client,lambda:now[0])
        await service.metadata()
        now[0] += timedelta(minutes=30)
        tomorrow = NOW.date()+timedelta(days=1)
        metadata = await service.metadata(tomorrow)
        now[0] += timedelta(minutes=31)
        assert await service.legend_image(tomorrow) == png(146,95)
        assert (await service.metadata(tomorrow)) == metadata
        assert len(calls) == 4
