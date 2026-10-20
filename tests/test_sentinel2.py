"""Offline provider contracts, georeferencing, resource limits and local API security."""
import asyncio
import base64
import io
import json
import tarfile
import time
from datetime import datetime

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from wici.app import create_app
from wici.config import Config
from wici.sentinel2 import (
    CATALOG,
    MAX_BYTES,
    PROCESS,
    TOKEN,
    SentinelError,
    SentinelService,
    decode,
    evalscript,
    geometry,
    images,
)

ID = 'S2B_TEST.SAFE'
WHEN = '2026-10-13T10:06:12.589+00:00'
ARGS = (52.02, 19.12, 2)
ITEM = {'id': ID, 'observed_at': WHEN}


def configured():
    return Config(sources={'sentinel2': {'enabled': True, 'client_id': 'private-client',
                                        'client_secret': 'private-secret'}})


def archive(grid, tiles=None, bbox=None):
    data = np.zeros((5, grid['height'], grid['width']), dtype='uint8')
    data[:4] = 255
    data[4] = 4
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=grid['width'], height=grid['height'], count=5,
                         dtype='uint8', crs='EPSG:3857', transform=from_bounds(
                             *(bbox or grid['bbox']), grid['width'], grid['height'])) as raster:
            raster.write(data)
        tiff = memory.read()
    tiles = tiles if tiles is not None else [{'date': WHEN, 'sentinel2ProductId': ID[:-5]}]
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as tar:
        for name, body in [('raster.tif', tiff), ('userdata.json', json.dumps({'tiles': tiles}).encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return output.getvalue()


def full_footprint(fraction=1):
    w, s, e, n = geometry(*ARGS)['catalog_bbox']
    e = w+(e-w)*fraction
    return {'type': 'Polygon', 'coordinates': [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def handler(calls, status=200):
    def respond(request):
        calls.append(request)
        if str(request.url) == TOKEN:
            return httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
        if status != 200:
            return httpx.Response(status, text='private-secret private-token', headers={'Retry-After': '3500'})
        if str(request.url) == CATALOG:
            return httpx.Response(200, json={'features': [{'id': ID, 'properties': {
                'datetime': WHEN, 'eo:cloud_cover': 12}, 'geometry': full_footprint()}], 'context': {'next': 50}})
        payload = json.loads(request.content)
        assert payload['output']['width'] == 200
        assert request.headers['accept'] == 'application/tar'
        assert 'S2B_TEST' in payload['evalscript'] and 'mosaicking' in payload['evalscript']
        return httpx.Response(200, content=archive(geometry(*ARGS)))
    return respond


@pytest.mark.parametrize('args', [(0, 0, 4), (52, 15, 99), (float('nan'), 19, 4),
                                 (50, 14.1, 4), (55, 24, 4), (52, 19, float('inf'))])
def test_geometry_rejects_outside_poland_and_unbounded_area(args):
    with pytest.raises(ValueError):
        geometry(*args)


def test_geometry_mercator_matches_leaflet_and_ground_resolution():
    grid = geometry(*ARGS)
    assert grid['width'] == grid['height'] == 200
    assert grid['bounds'][0][0] < ARGS[0] < grid['bounds'][1][0]
    assert grid['bounds'][0][1] < ARGS[1] < grid['bounds'][1][1]
    assert (grid['bbox'][2]-grid['bbox'][0])/200 > 10  # Mercator scale, not native UTM.
    result = decode(archive(grid), ITEM, grid)
    assert result['quality'] == {'coverage': 100, 'missing_percent': 0, 'missing_pixels': 0, 'total_pixels': 40000,
                                  'cloud': 0, 'shadow': 0, 'snow': 0}
    assert base64.b64decode(result['image']).startswith(b'\x89PNG')


@pytest.mark.parametrize('tiles', [[], [{'sentinel2ProductId': 'wrong', 'date': WHEN}],
    [{'sentinel2ProductId': ID[:-5], 'date': '2026-10-14T10:06:12Z'}],
    [{'sentinel2ProductId': ID[:-5], 'date': WHEN}]*2])
def test_rejects_wrong_product_date_and_mosaics(tiles):
    grid = geometry(*ARGS)
    with pytest.raises(SentinelError):
        decode(archive(grid, tiles), ITEM, grid)


def test_rejects_shifted_grid_corrupt_and_oversized_archive():
    grid = geometry(*ARGS)
    box = [v+20 for v in grid['bbox']]
    for body in [archive(grid, bbox=box), b'not an image']:
        with pytest.raises(SentinelError):
            decode(body, ITEM, grid)


def test_quality_cloud_shadow_snow_and_opaque_nodata():
    data = np.zeros((5, 2, 2), dtype='uint8')
    data[3] = 255
    data[3, 0, 0] = 0
    data[4] = [[0, 9], [3, 11]]
    result = images(data, ITEM, geometry(*ARGS))
    assert result['quality']['coverage'] == 75
    assert result['quality']['cloud'] == 33.33
    assert result['quality']['shadow'] == 33.33
    assert result['quality']['snow'] == 33.33
    data[3] = 0
    assert images(data, ITEM, geometry(*ARGS))['status'] == 'no_coverage'


async def test_search_render_cache_and_parallel_jobs():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls))) as client:
        svc = SentinelService(client, configured())
        results = await asyncio.gather(*(svc.search(*ARGS, '2026-10-01', '2026-10-16', 80) for _ in range(5)))
        assert len(calls) == 2
        assert results[0]['truncated']
        assert datetime.fromisoformat(results[0]['items'][0]['observed_at']) == datetime.fromisoformat(WHEN)
        rendered = await asyncio.gather(*(svc.render(*ARGS, ID) for _ in range(5)))
        assert len(calls) == 3 and rendered[0] == rendered[4]
        # Re-searching from cache restores the allowlist after selection eviction.
        svc.items.clear()
        await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)
        assert (await svc.render(*ARGS, ID))['item']['id'] == ID
        assert len(calls) == 3
        assert str(calls[-1].url) == PROCESS
        assert not any(secret in json.dumps(results+rendered) for secret in
                       ['private-secret', 'private-client', 'private-token'])
        with pytest.raises(SentinelError, match='Wyszukaj'):
            await svc.render(*ARGS, 'https://evil.test/')
        await svc.close()


@pytest.mark.parametrize('code', [401, 403, 429, 500, 503])
async def test_errors_are_sanitized_no_automatic_retry_and_cooldown(code):
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls, code))) as client:
        svc = SentinelService(client, configured())
        with pytest.raises(SentinelError) as error:
            await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)
        assert 'private' not in str(error.value) and len(calls) == 2
        if code in (429, 503):
            assert error.value.retry == 4
            with pytest.raises(SentinelError):
                await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)
            assert len(calls) == 2
        if code == 401:
            assert svc.expires == 0
        await svc.close()


async def test_timeout_response_limit_and_expired_token():
    def oversized(request):
        return httpx.Response(200, content=b'x'*(MAX_BYTES+1))
    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        svc = SentinelService(client, configured())
        with pytest.raises(SentinelError, match='8 MiB'):
            await svc.request(CATALOG)
    def timeout(request):
        raise httpx.ReadTimeout('private-secret')
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        svc = SentinelService(client, configured())
        with pytest.raises(SentinelError, match='timeout'):
            await svc.request(CATALOG)
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls))) as client:
        svc = SentinelService(client, configured())
        await svc.authorized(CATALOG, {})
        svc.expires = 0
        await svc.authorized(CATALOG, {})
        assert sum(str(r.url) == TOKEN for r in calls) == 2
        await svc.close()


async def test_cache_lru_expiry_concurrency_and_caller_cancellation():
    svc = SentinelService(None, Config(), demo=True)
    count, peak, running = 0, 0, 0
    async def work():
        nonlocal count, peak, running
        count += 1
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(.01)
        running -= 1
        return count
    await asyncio.gather(*(svc.cached(i, work) for i in range(8)))
    assert peak == 2
    for i in range(8, 15):
        await svc.cached(i, work)
    assert len(svc.cache) == 12 and 0 not in svc.cache
    svc.cache[14] = (time.monotonic()-1, 0)
    assert await svc.cached(14, work) != 0
    started, release = asyncio.Event(), asyncio.Event()
    async def held():
        started.set()
        await release.wait()
        return 42
    waiter = asyncio.create_task(svc.cached('held', held))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    assert await svc.cached('held', held) == 42
    await svc.close()


@pytest.mark.parametrize('start,end,cloud', [('2026-10-15', '2026-10-01', 80),
    ('2014-01-01', '2014-02-01', 80), ('2024-01-01', '2026-01-01', 80),
    ('2026-10-01', '2026-10-16', -1), ('2026-10-01', '2026-10-16', float('nan'))])
async def test_invalid_search_dates_and_cloud(start, end, cloud):
    with pytest.raises(ValueError):
        await SentinelService(None, Config()).search(*ARGS, start, end, cloud)


def test_api_offline_demo_configuration_origin_and_secrets(tmp_path):
    def no_network(request):
        pytest.fail('Offline demo made a network request')
    client = httpx.AsyncClient(transport=httpx.MockTransport(no_network))
    with TestClient(create_app(demo=True, root=tmp_path, config=Config(), client=client),
                    base_url='http://127.0.0.1:8765') as api:
        assert api.get('/api/sentinel2/status').json()['status'] == 'demo'
        params = {'lat': 52.02, 'lon': 19.12, 'size': 2, 'start': '2026-10-01', 'end': '2026-10-16', 'cloud': 80}
        r = api.get('/api/sentinel2/search', params=params)
        assert r.status_code == 200 and len(r.json()['items']) == 2
        params['identifier'] = r.json()['items'][0]['id']
        assert api.get('/api/sentinel2/render', params=params).json()['status'] == 'partial_coverage'
        assert api.get('/api/sentinel2/status', headers={'origin': 'https://evil.test'}).status_code == 403
        assert api.get('/api/sentinel2/search', params={**params, 'lat': 0}).status_code == 422
        assert api.get('/api/sentinel2/render', params={**params, 'identifier': 'evil'}).status_code == 404
    cfg = configured()
    assert 'private-secret' not in repr(cfg) and 'private-client' not in repr(cfg)
    svc = SentinelService(None, Config())
    assert svc.status()['status'] == 'unconfigured'
    assert 'OAuth' in svc.status()['message']
    assert 'preProcessScenes' in evalscript(ID)


async def test_queue_limit_and_shutdown_clear_owned_jobs():
    svc = SentinelService(None, Config(), demo=True)
    release = asyncio.Event()
    async def held():
        await release.wait()
    callers = [asyncio.create_task(svc.cached(i, held)) for i in range(8)]
    await asyncio.sleep(.01)
    with pytest.raises(SentinelError, match='Kolejka'):
        await svc.cached(9, held)
    await svc.close()
    await asyncio.gather(*callers, return_exceptions=True)
    assert not svc.jobs and svc.token == '' and svc.credentials == {}


async def test_expired_selection_does_not_render_cached_image():
    svc = SentinelService(None, Config(), demo=True)
    result = await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)
    identifier = result['items'][0]['id']
    assert 'syntetyczne' in result['items'][0]['attribution']
    await svc.render(*ARGS, identifier)
    svc.items[(*ARGS, identifier)] = (time.monotonic()-1, result['items'][0])
    with pytest.raises(SentinelError) as error:
        await svc.render(*ARGS, identifier)
    assert error.value.code == 404
    assert not (await svc.search(*ARGS, '2026-10-01', '2026-10-16', 0))['items']
    await svc.close()


def test_footprint_and_nodata_alpha():
    from wici.sentinel2 import footprint_coverage
    grid = geometry(*ARGS)
    w, s, e, n = grid['catalog_bbox']
    half = (w+e)/2
    shape = {'type': 'Polygon', 'coordinates': [[[w, s], [half, s], [half, n], [w, n], [w, s]]]}
    assert footprint_coverage(shape, grid) == 50
    data = np.zeros((5, 2, 2), dtype='uint8')
    result = images(data, ITEM, grid)
    with MemoryFile(base64.b64decode(result['image'])) as image, image.open() as raster:
        assert np.all(raster.read(4) == 255)  # Never expose the other date under NoData.


@pytest.mark.parametrize('start,end', [('2026-10-05', '2026-10-16'),
                                      ('2026-10-01', '2026-10-16'),
                                      ('2026-10-05', '2026-10-10')])
async def test_demo_date_changes_do_not_reuse_another_observation(start, end):
    svc = SentinelService(None, Config(), demo=True)
    try:
        original = await svc.search(*ARGS, '2026-10-01', '2026-10-10', 80)
        original_renders = [await svc.render(*ARGS, item['id']) for item in original['items']]
        assert original_renders[0]['image'] != original_renders[1]['image']
        changed = await svc.search(*ARGS, start, end, 80)
        for item in changed['items']:
            rendered = await svc.render(*ARGS, item['id'])
            assert rendered['item'] == item
            assert rendered['grid'] == changed['grid']
        # Returning to the first range must retain the original observation metadata too.
        restored = await svc.search(*ARGS, '2026-10-01', '2026-10-10', 80)
        for item, expected in zip(restored['items'], original_renders, strict=True):
            assert await svc.render(*ARGS, item['id']) == expected
    finally:
        await svc.close()


async def test_full_coverage_is_default_and_opt_out_reuses_catalog_cache():
    calls = []
    def respond(request):
        calls.append(str(request.url))
        if str(request.url) == TOKEN:
            return httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
        features = [{'id': identifier, 'geometry': shape, 'properties': {
            'datetime': WHEN, 'eo:cloud_cover': 0}} for identifier, shape in [
                ('partial', full_footprint(.5)), ('unknown', None), ('full', full_footprint()),
                ('almost-full', full_footprint(.995))]]
        return httpx.Response(200, json={'features': features, 'context': {'next': 50}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        svc = SentinelService(client, configured())
        full = await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)
        assert [i['id'] for i in full['items']] == ['full']
        assert full['full_coverage_only'] and full['truncated']
        assert full['total_items'] == 4
        assert full['excluded_partial_count'] == 2 and full['excluded_unknown_count'] == 1
        all_items = await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80, full_only=False)
        assert len(all_items['items']) == 4 and all_items['items'][0]['id'] == 'full'
        assert next(i for i in all_items['items'] if i['id'] == 'almost-full')['catalog_coverage_percent'] < 100
        assert (await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)) == full
        assert calls == [TOKEN, CATALOG]
        await svc.close()


async def test_all_partial_or_unknown_results_remain_explicitly_excluded():
    def respond(request):
        if str(request.url) == TOKEN:
            return httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
        return httpx.Response(200, json={'features': [{'id': 'partial', 'geometry': full_footprint(.5),
                             'properties': {'datetime': WHEN}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        svc = SentinelService(client, configured())
        result = await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80)
        assert result['items'] == [] and result['total_items'] == 1
        assert result['excluded_partial_count'] == 1
        assert len((await svc.search(*ARGS, '2026-10-01', '2026-10-16', 80, full_only=False))['items']) == 1
        await svc.close()


@pytest.mark.parametrize('valid_pixels,status,missing', [(0, 'no_coverage', 100),
    (2, 'partial_coverage', 50), (3, 'partial_coverage', 25), (4, 'ready', 0)])
def test_render_reports_missing_data_separately_from_clouds(valid_pixels, status, missing):
    data = np.zeros((5, 2, 2), dtype='uint8')
    data[3].flat[:valid_pixels] = 255
    data[4] = 9  # Even a 100% cloudy image still has full data coverage.
    result = images(data, ITEM, geometry(*ARGS))
    assert result['status'] == status
    assert result['quality']['missing_percent'] == missing
    assert result['quality']['missing_pixels'] == 4-valid_pixels
    assert result['quality']['total_pixels'] == 4
    if valid_pixels:
        assert result['quality']['cloud'] == 100


def test_single_missing_pixel_does_not_round_to_full_coverage():
    data = np.ones((5, 600, 600), dtype='uint8')
    data[3] = 255
    data[3, 0, 0] = 0
    result = images(data, ITEM, geometry(52.02, 19.12, 6))
    assert result['status'] == 'partial_coverage'
    assert 0 < result['quality']['missing_percent'] < .01
    assert result['quality']['coverage'] < 100


def test_api_defaults_to_full_coverage_and_accepts_explicit_partial_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr('wici.sentinel2.footprint_coverage', lambda shape, grid: 50.0)
    def offline(request):
        pytest.fail('Coverage API regression must remain offline')
    with TestClient(create_app(demo=True, root=tmp_path, config=Config(),
                              client=httpx.AsyncClient(transport=httpx.MockTransport(offline))),
                    base_url='http://127.0.0.1:8765') as api:
        params = {'lat': ARGS[0], 'lon': ARGS[1], 'size': ARGS[2],
                  'start': '2026-10-01', 'end': '2026-10-16', 'cloud': 80}
        result = api.get('/api/sentinel2/search', params=params).json()
        assert result['items'] == [] and result['excluded_partial_count'] == 2
        response = api.get('/api/sentinel2/search', params={**params, 'full_only': 'false'})
        assert response.status_code == 200
        assert len(response.json()['items']) == 2 and response.json()['full_coverage_only'] is False


def test_api_separate_year_ranges_render_exact_observations_on_shared_grid(tmp_path):
    def offline(request):
        pytest.fail('Cross-year comparison regression must remain offline')
    with TestClient(create_app(demo=True, root=tmp_path, config=Config(),
                              client=httpx.AsyncClient(transport=httpx.MockTransport(offline))),
                    base_url='http://127.0.0.1:8765') as api:
        params = {'lat': ARGS[0], 'lon': ARGS[1], 'size': ARGS[2], 'cloud': 80}
        searches = []
        for year in (2020, 2026):
            response = api.get('/api/sentinel2/search', params={**params,
                               'start': f'{year}-06-01', 'end': f'{year}-06-30'})
            assert response.status_code == 200
            searches.append(response.json())
            assert len(searches[-1]['items']) == 2
            assert all(item['observed_at'].startswith(str(year)) for item in searches[-1]['items'])
        before, after = searches[0]['items'][0], searches[1]['items'][1]
        renders = []
        for item in (before, after, before):
            response = api.get('/api/sentinel2/render', params={**params, 'identifier': item['id']})
            assert response.status_code == 200
            renders.append(response.json())
            assert renders[-1]['item'] == item
        assert renders[0] == renders[2]  # Rendering another year never relabels cached pixels.
        assert renders[0]['grid'] == renders[1]['grid'] == searches[0]['grid'] == searches[1]['grid']
        assert renders[0]['image'] != renders[1]['image']
        # The limit applies to each search, not to the age difference between chosen observations.
        assert api.get('/api/sentinel2/search', params={**params, 'start': '2020-06-01',
                                                       'end': '2026-06-30'}).status_code == 422
