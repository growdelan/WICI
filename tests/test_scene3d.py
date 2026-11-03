"""Synthetic terrain and municipal records; no external services in tests."""
import asyncio

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from wici.app import create_app
from wici.config import Config
from wici.scene3d import (
    MAX_LEVEL,
    NMT_URL,
    SIZE,
    Scene3DService,
    bounds,
    decode_terrain,
    trees_from_geojson,
)


def tiff(value=125):
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=SIZE, height=SIZE, count=1, dtype='float32',
                         crs='EPSG:4326', transform=from_bounds(21, 52.2, 21.01, 52.21, SIZE, SIZE)) as raster:
            raster.write(np.full((SIZE, SIZE), value, dtype='float32'), 1)
        return memory.read()


def tile(lon=21.006, lat=52.225):
    step = 180/2**MAX_LEVEL
    return int((lon+180)//step), int((90-lat)//step)


def records(box):
    lon, lat = (box[0]+box[2])/2, (box[1]+box[3])/2
    return {'type': 'FeatureCollection', 'srs': 4326, 'features': [
        {'_id': 'synthetic/1', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
         'properties': {'SREDNICA_KORONY': 5,
                        '_label_': 'Wysokość w m: 12,5\nAktualność danych na dzień: 01.01.2026'}},
        {'_id': 'synthetic/2', 'geometry': {'type': 'Point', 'coordinates': [lon+.00001, lat]},
         'properties': {'_label_': 'Wysokość w m: \nObwód pnia w cm: 200'}},
    ]}


def test_terrain_decode_and_tile_seams():
    heights = decode_terrain(tiff())
    assert len(heights) == SIZE*SIZE and set(heights) == {125}
    x, y = tile()
    assert bounds(x, y, MAX_LEVEL)[2] == bounds(x+1, y, MAX_LEVEL)[0]
    assert bounds(x, y, MAX_LEVEL)[1] == bounds(x, y+1, MAX_LEVEL)[3]
    with pytest.raises(ValueError):
        bounds(x, y, 15)
    with pytest.raises(ValueError):
        decode_terrain(tiff(float('inf')))


def test_measured_and_estimated_trees_deduplicate_and_filter():
    box = bounds(*tile(), MAX_LEVEL)
    data = records(box)
    data['features'] += [data['features'][0], {'geometry': {'type': 'Point', 'coordinates': [0, 0]}}]
    items, truncated, dates = trees_from_geojson(data, box)
    assert len(items) == 2 and not truncated
    assert items[0]['height'] == 12.5 and items[0]['diameter'] == 5 and not items[0]['estimated']
    assert items[1]['height'] == 8 and items[1]['estimated']
    assert dates == ['01.01.2026']


@pytest.mark.asyncio
async def test_cache_coalesces_requests_and_preserves_vertex_coordinates():
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(.01)
        if str(request.url).startswith(NMT_URL):
            return httpx.Response(200, content=tiff())
        return httpx.Response(200, json=records(bounds(*tile(), MAX_LEVEL)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = Scene3DService(client)
        x, y = tile()
        first, second = await asyncio.gather(service.terrain(x, y, 14), service.terrain(x, y, 14))
        assert first == second and first['status'] == 'ready' and len(calls) == 1
        await service.terrain(x, y, 14)
        assert len(calls) == 1
        box = bounds(x, y, 14)
        actual = list(map(float, calls[0].url.params['BBOX'].split(',')))
        half = (box[2]-box[0])/(SIZE-1)/2
        assert actual[0] == pytest.approx(box[0]-half)
        assert actual[2] == pytest.approx(box[2]+half)
        trees = await service.trees(x, y)
        assert len(trees['items']) == 2 and trees['source'] == 'Urząd m.st. Warszawy'
        assert trees['source_dates'] and trees['fetched_at'] and trees['modified']
        assert len(calls) == 2
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['status', 'size', 'invalid'])
async def test_source_failure_is_bounded_cached_and_nonfatal(failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == 'status':
            return httpx.Response(503)
        return httpx.Response(200, content=b'x'*(256001 if failure == 'size' else 10))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = Scene3DService(client)
        x, y = tile()
        assert (await service.terrain(x, y, 14))['status'] == 'unavailable'
        assert (await service.terrain(x, y, 14))['status'] == 'unavailable'
        assert len(calls) == 1
        await service.close()


@pytest.mark.asyncio
async def test_demo_disabled_and_outside_coverage_do_not_fetch():
    def forbidden(request):
        raise AssertionError(f'Unexpected network: {request.url}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        for options in ({'demo': True}, {'enabled': False}):
            service = Scene3DService(client, **options)
            assert (await service.terrain(*tile(), 14))['status'] == 'empty'
            assert not (await service.trees(*tile()))['items']
        service = Scene3DService(client)
        assert (await service.terrain(0, 0, 10))['status'] == 'empty'
        assert 'Warszawy' in (await service.trees(*tile(19, 50)))['message']


def test_api_validation_origin_policy_and_demo(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path, config=Config()),
                    base_url='http://127.0.0.1:8765') as client:
        x, y = tile()
        for url in (f'/api/scene3d/terrain/14/{x}/{y}', f'/api/scene3d/trees/{x}/{y}'):
            assert client.get(url).json()['status'] == 'empty'
            assert client.get(url, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
            assert client.get(url, headers={'Origin': 'https://example.com'}).status_code == 403
        assert client.get(f'/api/scene3d/terrain/15/{x}/{y}').status_code == 422
        assert client.get('/api/scene3d/trees/-1/1').status_code == 422
        assert 'atlas3d-toggle' in client.get('/').text
        assert 'mapa.um.warszawa.pl' not in client.get('/').headers['content-security-policy']
