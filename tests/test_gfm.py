"""Offline STAC, masks, security, resource, time and real GDAL reprojection regressions."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from wici.app import create_app
from wici.gfm import (
    LAYERS,
    GFMService,
    GFMUnavailable,
    RangeReader,
    area,
    classify,
    instant,
    render_product,
    retry_seconds,
    safe_asset,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)
BOX = (16.55, 50.35, 16.75, 50.55)
URL = 'https://data.eodc.eu/collections/GFM_LAYERS/test.tif'


def product():
    return {'id': 'ENSEMBLE_TEST', 'collection': 'GFM', 'properties': {
        'datetime': '2024-09-15T05:01:49Z', 'created': '2024-11-06T14:23:19Z',
        'processing:datetime': '2024-09-15T08:15:00Z', 'processing:version': 'GFM v3.1.0'},
        'assets': {name: {'href': URL.replace('test', name)} for name in LAYERS}}


def service(handler, clock=lambda: NOW):
    return GFMService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), clock)


async def test_contract_time_cache_dedupe_and_no_pagination():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.params['collections'] == 'GFM'
        assert request.url.params['limit'] == '24'
        return httpx.Response(200, json={'type': 'FeatureCollection', 'features': [product()],
                                      'links': [{'rel': 'next', 'href': 'http://127.0.0.1/evil'}]})
    svc = service(handler)
    results = await asyncio.gather(*(svc.search(BOX, '2024-09-14', '2024-09-17') for _ in range(4)))
    assert len(calls) == 1
    item = results[0]['items'][0]
    assert results[0]['truncated']
    assert item['observed_at'].startswith('2024-09-15')
    assert item['processed_at'].startswith('2024-09-15')
    assert item['catalog_created_at'].startswith('2024-11-06')
    assert item['fetched_at'] == NOW.isoformat() and item['stale']
    assert item['version'] == 'GFM v3.1.0'
    assert '[2024]' in item['attribution']
    assert 'assets' not in item


@pytest.mark.parametrize('url', ['http://data.eodc.eu/collections/GFM_a/a.tif',
    'https://data.eodc.eu.evil/collections/GFM_a/a.tif', 'https://data.eodc.eu:443/collections/GFM_a/a.tif',
    'https://user@data.eodc.eu/collections/GFM_a/a.tif', 'https://data.eodc.eu/collections/GFM_a/../a.tif',
    URL+'?x=1', 'file:///etc/passwd', None])
def test_asset_restrictions(url):
    assert not safe_asset(url)
    assert safe_asset(URL)


@pytest.mark.parametrize('box', [(0, 0, 1, 1), (16, 50, 17, 51), (16, 50, 15, 50),
                                 (16, 50, float('nan'), 51), (16, 50)])
def test_area_limits(box):
    with pytest.raises(ValueError):
        area(box)


def test_masks_and_nodata():
    flood = np.array([0, 1, 0, 1, 0, 255, 0, 0, 9], dtype='uint8')
    ref = np.array([0, 0, 1, 2, 0, 0, 255, 0, 0], dtype='uint8')
    exc = np.array([0, 0, 0, 0, 1, 0, 0, 255, 0], dtype='uint8')
    assert classify(flood, ref, exc).tolist() == [0, 1, 2, 2, 3, 4, 4, 4, 4]
    assert instant('2024-09-15T07:01:49+02:00') == '2024-09-15T05:01:49+00:00'
    with pytest.raises(ValueError):
        instant('2024-09-15T05:01:49')


async def test_demo_disabled_validation_and_missing():
    def forbidden(request):
        raise AssertionError('network in demo')
    svc = service(forbidden)
    svc.demo = True
    assert (await svc.search(BOX, '2024-09-14', '2024-09-17'))['status'] == 'demo_no_data'
    with pytest.raises(GFMUnavailable):
        await svc.render('missing', BOX)
    svc.demo = False
    with pytest.raises(KeyError):
        await svc.render('missing', BOX)
    for start, end in [('2024-09-17', '2024-09-14'), ('2024-09-01', '2024-10-01')]:
        with pytest.raises(ValueError):
            await svc.search(BOX, start, end)


async def test_errors_retry_after_and_expiry():
    now = NOW
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '120'})
    svc = service(handler, lambda: now)
    for _ in range(2):
        with pytest.raises(GFMUnavailable):
            await svc.search(BOX, '2024-09-14', '2024-09-17')
    assert len(calls) == 1
    now += timedelta(seconds=121)
    with pytest.raises(GFMUnavailable):
        await svc.search(BOX, '2024-09-14', '2024-09-17')
    assert len(calls) == 2
    assert retry_seconds('Sat, 17 Oct 2026 00:02:00 GMT', NOW) == 120
    assert retry_seconds('999999', NOW) == 3600


@pytest.mark.parametrize('response', [httpx.Response(302, headers={'Location': 'http://localhost'}),
    httpx.Response(200, content=b'x'), httpx.Response(206, headers={'Content-Range': 'bytes 0-9/100'}, content=b'x')])
def test_range_requires_exact_partial_and_no_redirect(response):
    with (httpx.Client(transport=httpx.MockTransport(lambda r, response=response: response)) as client,
          pytest.raises(GFMUnavailable)):
        RangeReader(URL, client, {'bytes': 0, 'requests': 0, 'deadline': float('inf')})


def test_range_cache_seek_and_budget():
    calls = []
    body = bytes(range(256))*512
    def handler(request):
        calls.append(request)
        start, end = map(int, request.headers['range'][6:].split('-'))
        return httpx.Response(206, headers={'Content-Range': f'bytes {start}-{end}/{len(body)}'},
                              content=body[start:end+1])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        budget = {'bytes': 0, 'requests': 0, 'deadline': float('inf')}
        reader = RangeReader(URL, client, budget)
        assert reader.read(10) == body[:10]
        reader.seek(65530)
        assert reader.read(20) == body[65530:65550]
        reader.seek(-10, 2)
        assert reader.read(20) == body[-10:]
        assert len(calls) == 2
        with pytest.raises(GFMUnavailable):
            reader.read()
        budget['deadline'] = 0
        with pytest.raises(GFMUnavailable):
            reader._block(2)


def test_real_gdal_nearest_reprojection(tmp_path, monkeypatch):
    # Equi7 EU, same CRS as the verified 2024 provider product.
    crs = '+proj=aeqd +lat_0=53 +lon_0=24 +x_0=5837287.81977 +y_0=2121415.69617 +datum=WGS84 +units=m'
    from rasterio.warp import transform_bounds
    bounds = transform_bounds('EPSG:4326', crs, *BOX)
    w = int((bounds[2]-bounds[0])/20)+1
    h = int((bounds[3]-bounds[1])/20)+1
    item = product()
    for name in LAYERS:
        data = np.zeros((h, w), dtype='uint8')
        if name == 'ensemble_flood_extent':
            data[:, w//2:] = 1
        if name == 'ensemble_likelihood':
            data[:, w//2:] = 80
        path = tmp_path / (name+'.tif')
        with rasterio.open(path, 'w', driver='GTiff', count=1, width=w, height=h,
                           dtype='uint8', crs=crs, transform=from_origin(bounds[0],bounds[3],20,20), nodata=255) as dst:
            dst.write(data, 1)
    def opener(url, mode='rb'):
        return open(tmp_path / url.rsplit('/', 1)[1], mode)
    result = render_product(item, BOX, opener=opener)
    assert result['counts']['flood'] > 100000 and result['counts']['assessed_clear'] > 100000
    assert set(result['quality']['ensemble_likelihood']) <= {'0', '80', '255'}
    assert result['bounds'] == [[50.35,16.55], [50.55,16.75]]
    assert result['status'] == 'flood'
    monkeypatch.setattr('wici.gfm.MAX_PIXELS', 1)
    with pytest.raises(GFMUnavailable, match='4 mln'):
        render_product(item, BOX, opener=opener)


async def test_render_cache_and_worker_shared(monkeypatch):
    calls = []
    svc = service(lambda r: httpx.Response(200, json={'type': 'FeatureCollection', 'features': [product()]}))
    await svc.search(BOX, '2024-09-14', '2024-09-17')
    def render(item, box, **kwargs):
        calls.append(item)
        return {'transfer': {}, 'counts': {}}
    monkeypatch.setattr('wici.gfm.render_product', render)
    await asyncio.gather(*(svc.render('ENSEMBLE_TEST', BOX) for _ in range(4)))
    assert len(calls) == 1
    for i in range(20):
        svc.put(svc.cache, i, (NOW, i), 12)
    assert len(svc.cache) == 12


async def test_stac_response_limit_and_contract():
    for response in [httpx.Response(200, content=b'x'*(3*1024*1024+1)), httpx.Response(200,json={})]:
        svc = service(lambda r, response=response: response)
        with pytest.raises(GFMUnavailable):
            await svc.search(BOX, '2024-09-14', '2024-09-17')


def test_api_offline_and_security(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        query = 'bbox=16.55,50.35,16.75,50.55&start=2024-09-14&end=2024-09-17'
        assert client.get('/api/gfm?'+query).json()['status'] == 'demo_no_data'
        assert client.get('/api/gfm?'+query, headers={'sec-fetch-site': 'cross-site'}).status_code == 403
        assert client.get('/api/gfm/render/test?bbox=16.55,50.35,16.75,50.55',
                          headers={'origin': 'https://evil.test'}).status_code == 403
        assert client.get('/api/gfm?'+query.replace('16.55','0')).status_code == 422
        html = client.get('/').text
        assert 'id="gfm-enabled"' in html and '/static/js/gfm.js' in html


async def test_incomplete_current_products_remain_visible_but_cannot_render():
    incomplete = product()
    del incomplete['assets']['exclusion_mask']
    svc = service(lambda r: httpx.Response(200, json={'type': 'FeatureCollection', 'features': [incomplete]}))
    result = await svc.search(BOX, '2024-09-14', '2024-09-17')
    assert result['items'][0]['renderable'] is False
    assert result['items'][0]['missing_assets'] == ['exclusion_mask']
    with pytest.raises(GFMUnavailable, match='exclusion_mask'):
        await svc.render(incomplete['id'], BOX)


async def test_cache_expiry_empty_products_and_malformed_json():
    now = NOW
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'type': 'FeatureCollection', 'features': []})
    svc = service(handler, lambda: now)
    assert (await svc.search(BOX, '2024-09-14', '2024-09-17'))['status'] == 'no_products'
    now += timedelta(seconds=601)
    await svc.search(BOX, '2024-09-14', '2024-09-17')
    assert len(calls) == 2
    svc = service(lambda r: httpx.Response(200, content=b'broken'))
    with pytest.raises(GFMUnavailable, match='JSON'):
        await svc.search(BOX, '2024-09-14', '2024-09-17')


async def test_render_failure_backoff_preserves_retry_after(monkeypatch):
    svc = service(lambda r: httpx.Response(200, json={'type': 'FeatureCollection', 'features': [product()]}))
    await svc.search(BOX, '2024-09-14', '2024-09-17')
    def broken(item, box, budget):
        budget['retry'] = 180
        raise OSError('provider failure')
    monkeypatch.setattr('wici.gfm.render_product', broken)
    with pytest.raises(GFMUnavailable):
        await svc.render('ENSEMBLE_TEST', BOX)
    assert svc.retry_at == NOW+timedelta(seconds=180)


async def test_synthetic_contract_old_and_current():
    from pathlib import Path
    payload = json.loads((Path(__file__).parent/'fixtures/gfm/stac.json').read_text())
    svc = service(lambda r: httpx.Response(200, json=payload))
    result = await svc.search(BOX, '2026-10-03', '2026-10-17')
    items = result['items']
    assert len(items) == 3
    assert items[0]['version'] == 'GFM v3.1.0'
    assert items[1]['version'] == 'v4.1.1' and items[1]['renderable'] is False
    assert items[2]['renderable'] is True
    assert items[2]['observed_at'] != items[2]['processed_at']


async def test_cancellation_keeps_provider_slot_until_work_finishes():
    svc = service(lambda r: httpx.Response(200))
    entered, finish = asyncio.Event(), asyncio.Event()
    async def work():
        entered.set()
        await finish.wait()
        return {'ok': True}
    task = asyncio.create_task(svc._cached('test', work, 60))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert svc.lock.locked()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not svc.lock.locked()


async def test_malformed_features_and_provider_timeout():
    svc = service(lambda r: httpx.Response(200, json={'type': 'FeatureCollection', 'features': [None]}))
    with pytest.raises(GFMUnavailable, match='kontraktu'):
        await svc.search(BOX, '2024-09-14', '2024-09-17')
    def timeout(request):
        raise httpx.ReadTimeout('provider timed out')
    svc = service(timeout)
    with pytest.raises(httpx.ReadTimeout):
        await svc.search(BOX, '2024-09-14', '2024-09-17')
    assert svc.retry_at > NOW


@pytest.fixture
def native_gfm_window(tmp_path):
    """Native Equi7 window larger than the preview; [592,409] is skipped by nearest sampling."""
    from rasterio.warp import transform_bounds
    crs = '+proj=aeqd +lat_0=53 +lon_0=24 +x_0=5837287.81977 +y_0=2121415.69617 +datum=WGS84 +units=m'
    bounds = transform_bounds('EPSG:4326', crs, *BOX)
    width = int((bounds[2]-bounds[0])/20)+1
    height = int((bounds[3]-bounds[1])/20)+1
    affine = from_origin(bounds[0], bounds[3], 20, 20)
    item = product()
    item['assets'] = {name: item['assets'][name] for name in LAYERS[:3]}
    def write(name, data):
        with rasterio.open(tmp_path/(name+'.tif'), 'w', driver='GTiff', count=1, width=width, height=height,
                           dtype='uint8', crs=crs, transform=affine, nodata=255) as dst:
            dst.write(data, 1)
    def opener(url, mode='rb'):
        return open(tmp_path/url.rsplit('/', 1)[1], mode)
    return item, opener, write, (height, width), crs, affine


@pytest.mark.parametrize('background', [0, 255])
def test_native_flood_pixel_cannot_be_lost_from_status(native_gfm_window, background):
    item, opener, write, shape, _, _ = native_gfm_window
    for name in LAYERS[:3]:
        data = np.full(shape, background, dtype='uint8')
        data[592, 409] = 1 if name == 'ensemble_flood_extent' else 0
        write(name, data)
    result = render_product(item, BOX, opener=opener)
    assert result['counts']['flood'] == 0, 'The regression specifically needs a detection omitted by the preview'
    assert result['source_counts']['flood'] == 1
    assert result['status'] == 'flood'


@pytest.mark.parametrize(('reference', 'exclusion', 'expected_class'), [
    (1, 0, 'reference_water'), (0, 1, 'excluded'), (255, 0, 'no_observation')])
def test_native_detection_summary_still_applies_all_masks(native_gfm_window, reference, exclusion, expected_class):
    item, opener, write, shape, _, _ = native_gfm_window
    for name, value in zip(LAYERS[:3], [1, reference, exclusion]):
        data = np.zeros(shape, dtype='uint8')
        data[592, 409] = value
        write(name, data)
    result = render_product(item, BOX, opener=opener)
    assert result['source_counts']['flood'] == 0
    assert result['source_counts'][expected_class] >= 1
    assert result['status'] == 'no_detection'


def test_native_summary_does_not_count_flood_outside_the_aoi(native_gfm_window):
    from rasterio.warp import transform
    item, opener, write, shape, crs, affine = native_gfm_window
    corners = [affine @ pair for pair in [(0, 0), (1, 0), (1, 1), (0, 1)]]
    lon, lat = transform(crs, 'EPSG:4326', *zip(*corners))
    assert (max(lon) < BOX[0] or min(lon) > BOX[2]
            or max(lat) < BOX[1] or min(lat) > BOX[3])
    for name in LAYERS[:3]:
        data = np.zeros(shape, dtype='uint8')
        if name == 'ensemble_flood_extent':
            data[0, 0] = 1
        write(name, data)
    result = render_product(item, BOX, opener=opener)
    assert result['source_counts']['flood'] == 0
    assert result['status'] == 'no_detection'


@pytest.mark.parametrize(('values', 'expected_class', 'expected_status'), [
    ((1, 0, 0), 'flood', 'flood'),
    ((0, 0, 0), 'assessed_clear', 'no_detection'),
    ((1, 1, 0), 'reference_water', 'reference_water'),
    ((1, 0, 1), 'excluded', 'excluded'),
    ((255, 0, 0), 'no_observation', 'no_coverage'),
])
def test_subpixel_aoi_uses_intersecting_native_pixel(native_gfm_window, values, expected_class, expected_status):
    from rasterio.warp import transform, transform_bounds
    item, opener, write, shape, crs, affine = native_gfm_window
    # A roughly 1 m AOI inside the top-left corner of the cell, away from its centre.
    row, col = 592, 409
    x, y = affine @ (col+.1, row+.1)
    lon, lat = transform(crs, 'EPSG:4326', [x], [y])
    box = area((lon[0], lat[0], lon[0]+.00001, lat[0]+.00001))
    west, south, east, north = transform_bounds('EPSG:4326', crs, *box)
    left, top = affine @ (col, row)
    assert left < west < east < left+20 and top-20 < south < north < top
    centre_lon, centre_lat = transform(crs, 'EPSG:4326', [left+10], [top-10])
    assert not (box[0] <= centre_lon[0] <= box[2] and box[1] <= centre_lat[0] <= box[3])
    for name, value in zip(LAYERS[:3], values):
        data = np.full(shape, 255, dtype='uint8')
        data[row, col] = value
        write(name, data)
    result = render_product(item, box, opener=opener)
    assert result['counts'][expected_class] > 0
    assert result['source_counts'][expected_class] == 1
    assert sum(result['source_counts'].values()) == 1
    assert result['status'] == expected_status
    if expected_status == 'flood':
        assert result['counts']['flood'] == sum(result['counts'].values())
        assert result['status'] != 'no_coverage'


def test_subpixel_aoi_crossing_a_cell_edge_counts_both_pixels(native_gfm_window):
    from rasterio.warp import transform_bounds
    item, opener, write, shape, crs, affine = native_gfm_window
    row, col = 592, 409
    edge_x, edge_y = affine @ (col+1, row+.25)
    box = area(transform_bounds(crs, 'EPSG:4326', edge_x-1, edge_y-.5, edge_x+1, edge_y+.5))
    for name in LAYERS[:3]:
        data = np.full(shape, 255, dtype='uint8')
        data[row, col] = 1 if name == 'ensemble_flood_extent' else 0
        data[row, col+1] = 0
        write(name, data)
    result = render_product(item, box, opener=opener)
    assert result['counts']['flood'] > 0 and result['counts']['assessed_clear'] > 0
    assert result['source_counts']['flood'] == result['source_counts']['assessed_clear'] == 1
    assert sum(result['source_counts'].values()) == 2
    assert result['status'] == 'flood'
