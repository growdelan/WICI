"""Verified catalogue shapes, location filtering, honest dates, bounded/safe thumbnail fetches."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wici.imagery import (
    CEMS_CATALOG,
    CEMS_DETAIL,
    CEMS_IMAGES,
    JSON_LIMIT,
    PREVIEW_LIMIT,
    ImageryService,
    ImageryUnavailable,
    _safe_preview,
)

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
CATALOG = {'count': 1, 'next': None, 'results': [
    {'code': 'EMSR756', 'centroid': 'POINT (16.667259 50.603763)'}]}
PRODUCT = {'id': 1027, 'type': 'DEL', 'feasible': True, 'mapsCount': 2,
    'images': [{'acquisitionTime': '2024-09-14T16:54:00', 'new': True}],
    'downloadPath': 'https://rapidmapping.emergency.copernicus.eu/backend/EMSR756/AOI01/DEL_PRODUCT/EMSR756_AOI01_DEL_PRODUCT_v1.zip',
    'version': {'statusCode': 'F', 'deliveryTime': '2024-09-15T06:17:22.026478'}}
DETAIL = {'results': [{'code': 'EMSR756', 'aois': [{'name': 'Klodzko',
    'extent': 'POLYGON ((16.5 50.3, 16.8 50.3, 16.8 50.6, 16.5 50.6, 16.5 50.3))',
    'products': [PRODUCT]}]}]}


def handler(calls, detail=None, preview=None):
    def respond(request):
        calls.append(request)
        url = str(request.url).split('?')[0]
        if url == CEMS_CATALOG:
            return httpx.Response(200, json=CATALOG)
        if url == CEMS_DETAIL:
            return httpx.Response(200, json=DETAIL if detail is None else detail)
        if preview:
            return preview(request)
        return httpx.Response(200, content=b'\xff\xd8\xff' + b'example jpeg')
    return respond


@pytest.mark.asyncio
async def test_real_catalogue_shapes_location_dates_attribution_and_local_preview():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls))) as client:
        service = ImageryService(client, lambda: NOW)
        result = await service.search(50.43, 16.65)
        assert len(result['items']) == 1 and result['status'] == 'partial'
        cems = result['items'][0]
        assert cems['source'] == 'Copernicus EMS'
        assert [provider['source'] for provider in result['providers']] == ['Copernicus EMS']
        assert cems['attribution'] == '© European Union, Copernicus EMS'
        assert cems['acquired_at'] == '2024-09-14'
        assert cems['product_at'] == '2024-09-15'
        assert cems['kind'] == 'mapping' and cems['bounds'] == [[50.3, 16.5], [50.6, 16.8]]
        for item in result['items']:
            assert item['preview_url'] == '/api/imagery/preview/' + item['id']
            body, mime = await service.preview(item['id'])
            assert body and mime in {'image/png', 'image/jpeg'}
        assert str(calls[-1].url) == CEMS_IMAGES + '/EMSR756/AOI01/DEL_PRODUCT/thumbnails/thumbnail.jpg'
        count = len(calls)
        assert await service.search(50.43, 16.65) == result
        await service.preview(cems['id'])
        assert len(calls) == count
        assert calls[0].url.params['limit'] == '500'


@pytest.mark.asyncio
async def test_product_date_is_not_acquisition_and_outside_area_ignored():
    detail = deepcopy(DETAIL)
    detail['results'][0]['aois'][0]['products'][0]['images'] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler([], detail))) as client:
        result = await ImageryService(client, lambda: NOW).search(50.43, 16.65)
        assert len(result['items']) == 1
        assert result['items'][0]['acquired_at'] is None
        assert result['items'][0]['product_at'].startswith('2024-09-15')

@pytest.mark.asyncio
async def test_outside_aoi_is_ignored():
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler([]))) as client:
        result = await ImageryService(client, lambda: NOW).search(51.0, 16.65)
        assert result['items'] == []


@pytest.mark.parametrize('url', ['http://127.0.0.1/a.png', 'https://attacker.test/a.png',
    'https://rapidmapping-viewer.s3.eu-west-1.amazonaws.com.evil.test/a.png',
    'https://rapidmapping-viewer.s3.eu-west-1.amazonaws.com/a.png?secret=1',
    'https://user:pass@rapidmapping-viewer.s3.eu-west-1.amazonaws.com/a.png',
    'https://rapidmapping-viewer.s3.eu-west-1.amazonaws.com:8443/a.png'])
def test_untrusted_thumbnail_url_is_rejected(url):
    assert not _safe_preview(url)



@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(302, headers={'location': 'http://127.0.0.1/'}),
    httpx.Response(200, content=b'<html>not a raster</html>'),
    httpx.Response(200, content=b'\x89PNG\r\n\x1a\n' + b'x' * PREVIEW_LIMIT)])
async def test_preview_rejects_redirect_non_raster_and_oversize(response):
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls, preview=lambda r: response)),
                                 follow_redirects=True) as client:
        service = ImageryService(client, lambda: NOW)
        result = await service.search(50.43, 16.65)
        with pytest.raises(ImageryUnavailable):
            await service.preview(result['items'][0]['id'])
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_catalog_failure_and_failure_cache():
    calls, now = [], [NOW]
    def respond(request):
        calls.append(request)
        assert request.url.host == 'rapidmapping.emergency.copernicus.eu'
        return httpx.Response(200, content=b'x' * (JSON_LIMIT+1))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = ImageryService(client, lambda: now[0])
        result = await service.search(50.43, 16.65)
        assert result['status'] == 'error' and result['items'] == []
        assert result['providers'][0]['status'] == 'error'
        assert len(calls) == 1
        await service.search(50.43, 16.65)
        assert len(calls) == 1
        now[0] += timedelta(minutes=3)
        await service.search(50.43, 16.65)
        assert len(calls) == 2



@pytest.mark.asyncio
async def test_demo_disabled_invalid_coordinates_zero_network():
    def forbidden(request):
        pytest.fail('No network for disabled/demo imagery')
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        for options in ({'demo': True}, {'enabled': False}):
            service = ImageryService(client, lambda: NOW, **options)
            result = await service.search(50.43, 16.65)
            assert result['status'] == 'disabled' and result['items'] == []
            with pytest.raises(ImageryUnavailable):
                await service.preview('anything')
            for lat, lon in [(float('nan'), 0), (0, float('inf')), (91, 0), (0, -181)]:
                with pytest.raises(ValueError):
                    await service.search(lat, lon)


@pytest.mark.asyncio
async def test_cache_expiry_and_bounded_coordinate_cache():
    calls, now = [], [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls))) as client:
        service = ImageryService(client, lambda: now[0])
        result = await service.search(50.43, 16.65)
        identifier = result['items'][0]['id']
        now[0] += timedelta(minutes=16)
        await service.search(50.43, 16.65)
        assert len(calls) == 2  # CEMS catalogue and details remain cached
        for offset in range(40):
            await service.search(50.43+offset/10000, 16.65)
        assert len(service.searches) == 32
        now[0] += timedelta(hours=2)
        with pytest.raises(KeyError):
            await service.preview(identifier)


@pytest.mark.asyncio
async def test_cems_detail_calls_limited_and_empty_archive_honest():
    calls = []
    catalog = {'results': [{'code': f'EMSR{n}', 'centroid': 'POINT (16.66 50.43)'} for n in range(20)]}
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=catalog if request.url.path.endswith('public-activations-info/')
                              else {'results': [], 'meta': {'found': 0}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await ImageryService(client, lambda: NOW).search(50.43, 16.65)
        assert len(calls) == 5 and result['items'] == []
        assert result['status'] == 'partial'
        assert 'części katalogów' in result['message']
        assert 'do 4' in result['providers'][0]['message']


@pytest.mark.asyncio
async def test_slow_catalog_reports_timeout_without_results():
    import asyncio
    async def respond(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json=CATALOG)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = ImageryService(client, lambda: NOW)
        service.provider_deadline = 0.03
        result = await asyncio.wait_for(service.search(50.43, 16.65), 0.2)
        assert result['status'] == 'error' and result['items'] == []
        assert result['providers'][0]['source'] == 'Copernicus EMS'



@pytest.mark.asyncio
async def test_cems_details_parallel_and_single_detail_timeout_isolated():
    import asyncio
    catalog = {'results': [{'code': f'EMSR{n}', 'centroid': 'POINT (16.66 50.43)'} for n in range(4)]}
    active, peak = [0], [0]
    async def respond(request):
        if request.url.path.endswith('public-activations-info/'):
            return httpx.Response(200, json=catalog)
        if request.url.path.endswith('public-activations/'):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            try:
                await asyncio.sleep(5 if request.url.params['code'] == 'EMSR0' else 0.005)
                return httpx.Response(200, json={'results': []})
            finally:
                active[0] -= 1
        pytest.fail(f'Unexpected upstream request: {request.url}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = ImageryService(client, lambda: NOW)
        service.detail_deadline = 0.03
        result = await asyncio.wait_for(service.search(50.43, 16.65), 0.2)
        assert peak[0] == 4
        assert result['providers'][0]['status'] == 'partial'
        assert 'Część aktywacji' in result['providers'][0]['message']


@pytest.mark.asyncio
async def test_preview_timeout_uses_declared_exception():
    import asyncio
    normal = handler([])
    async def respond(request):
        if request.url.host == 'rapidmapping-viewer.s3.eu-west-1.amazonaws.com':
            await asyncio.sleep(5)
        return normal(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = ImageryService(client, lambda: NOW)
        result = await service.search(50.43, 16.65)
        service.provider_deadline = 0.03
        with pytest.raises(ImageryUnavailable):
            await service.preview(result['items'][0]['id'])
