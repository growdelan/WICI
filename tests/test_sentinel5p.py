"""Scientific masks, selected-product provenance and bounded offline provider contracts."""
import asyncio
import base64
import copy
import io
import json
import tarfile
import time
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from wici.config import Config
from wici.sentinel5p import (
    BBOX,
    CATALOG,
    COLLECTION,
    MAX_BYTES,
    PARAMETERS,
    PROCESS,
    TOKEN,
    Sentinel5PError,
    Sentinel5PService,
    catalog_item,
    decode,
    evalscript,
    grid,
    images,
    process_payload,
    selection,
)

DAY = '2026-10-15'
ID = 'S5P_NRTI_L2__NO2____20261015T124254_20261015T124754_46664_03_020901_20261015T132437.nc'
SHAPE = {'type': 'Polygon', 'coordinates': [[[12, 48], [26, 48], [26, 56], [12, 56], [12, 48]]]}
FEATURE = {'id': ID, 'properties': {'datetime': '2026-10-15T12:42:54Z',
                                  's5p:type': 'NO2', 's5p:timeliness': 'NRTI'}, 'geometry': SHAPE}
ITEM = catalog_item(FEATURE, PARAMETERS['no2'], DAY)


def configured():
    return Config(sources={'sentinel5p': {'enabled': True, 'client_id': 'private-client',
                                        'client_secret': 'private-secret'}})


def raster_data(raster_grid=None):
    raster_grid = raster_grid or grid()
    data = np.ones((3, raster_grid['height'], raster_grid['width']), dtype='float32')
    data[0] = .00015
    return data


def archive(data=None, tiles=None, bbox=None, dtype='float32', duplicate=False, nested=False):
    raster_grid = grid()
    data = raster_data() if data is None else data
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=raster_grid['width'], height=raster_grid['height'], count=3,
                         dtype=dtype, crs='EPSG:3857', transform=from_bounds(
                             *(bbox or raster_grid['bbox']), raster_grid['width'], raster_grid['height'])) as raster:
            raster.write(data.astype(dtype))
        tiff = memory.read()
    tiles = tiles if tiles is not None else [{'date': ITEM['observed_at'], 'sentinel5pProductId': ID}]
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as tar:
        metadata = {'tiles': [], 'orbits': [{'tiles': tiles}]} if nested else {'tiles': tiles}
        files = [('raster.tif', tiff), ('userdata.json', json.dumps(metadata).encode())]
        if duplicate:
            files.append(files[-1])
        for name, body in files:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return output.getvalue()


def handler(calls, status=200):
    def respond(request):
        calls.append(request)
        if str(request.url) == TOKEN:
            return httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
        if status != 200:
            return httpx.Response(status, text='private-token private-secret', headers={'Retry-After': '3500'})
        if str(request.url) == CATALOG:
            return httpx.Response(200, json={'features': [FEATURE], 'context': {'next': 50}})
        payload = json.loads(request.content)
        assert payload['input']['data'][0]['type'] == COLLECTION
        assert payload['input']['data'][0]['dataFilter']['timeliness'] == 'NRTI'
        assert payload['input']['data'][0]['processing']['minQa'] in (0, 76)
        assert request.headers['accept'] == 'application/tar'
        return httpx.Response(200, content=archive())
    return respond


def test_product_units_quality_thresholds_and_no_cloud_band():
    assert [(p['unit'], p['min_qa']) for p in PARAMETERS.values()] == [
        ('mol/m²', 76), ('mol/m²', 51), ('indeks bezwymiarowy', 81)]
    assert 'troposferyczna' in PARAMETERS['no2']['label']
    assert 'nie jest udokumentowany' in PARAMETERS['so2']['description']
    assert '2.09.01' in PARAMETERS['aer_ai']['description']
    for parameter in PARAMETERS.values():
        script = evalscript(parameter, ID)
        assert parameter['band'] in script and parameter['input_unit'] in script
        assert "mosaicking:'ORBIT'" in script and 'FLOAT32' in script
        assert 'CLOUD_FRACTION' not in script and 'qa_value' not in script
    payload = process_payload(PARAMETERS['no2'], ITEM, 76)
    assert payload['input']['data'][0]['processing'] == {'upsampling': 'NEAREST', 'minQa': 76}
    assert payload['input']['data'][0]['dataFilter']['timeRange'] == {
        'from': ITEM['observation_start'], 'to': '2026-10-15T12:47:53.999+00:00'}


@pytest.mark.parametrize('parameter,day', [('o3', DAY), ('NO2', DAY), ('no2', '2018-04-29'),
    ('no2', '9999-01-01'), ('no2', '2026-10-1'), ('no2', '2026-02-30'), ('no2', '')])
def test_invalid_selection(parameter, day):
    with pytest.raises(ValueError):
        selection(parameter, day)


def test_grid_georeferencing_and_footprint():
    raster_grid = grid()
    assert raster_grid['catalog_bbox'] == BBOX
    assert raster_grid['bounds'] == [[48, 12], [56, 26]]
    assert raster_grid['width']*raster_grid['height'] == 38000
    np.testing.assert_array_equal(decode(archive(), ITEM, raster_grid), raster_data())
    result = images(raster_data(), raster_data(), ITEM, PARAMETERS['no2'], DAY)
    assert result['quality']['valid_percent'] == 100
    assert result['mosaic'] is False
    assert 'geometry' not in result['item']
    assert base64.b64decode(result['image']).startswith(b'\x89PNG')


@pytest.mark.parametrize('mutation', ['mode', 'type', 'time', 'bad_id', 'naive_time', 'shape'])
def test_catalog_rejects_mismatched_provenance(mutation):
    feature = copy.deepcopy(FEATURE)
    if mutation == 'mode':
        feature['properties']['s5p:timeliness'] = 'OFFL'
    elif mutation == 'type':
        feature['properties']['s5p:type'] = 'SO2'
    elif mutation == 'time':
        feature['properties']['datetime'] = '2026-10-14T12:42:54Z'
    elif mutation == 'naive_time':
        feature['properties']['datetime'] = '2026-10-15T12:42:54'
    elif mutation == 'shape':
        feature['geometry'] = {'type': 'Point', 'coordinates': [20, 52]}
    else:
        feature['id'] = 'https://untrusted.test/product'
    with pytest.raises((ValueError, KeyError)):
        catalog_item(feature, PARAMETERS['no2'], DAY)


def test_product_interval_timeliness_and_generation_are_distinct():
    assert ITEM['observed_at'] == '2026-10-15T12:42:54+00:00'
    assert ITEM['observation_end'] == '2026-10-15T12:47:54+00:00'
    assert ITEM['product_generated_at'] == '2026-10-15T13:24:37+00:00'
    assert ITEM['processor_version'] == '020901' and ITEM['mode'] == 'NRTI'
    assert ITEM['product_generation_delay_hours'] == .61


@pytest.mark.parametrize('tiles', [[], [{'sentinel5pProductId': 'wrong', 'date': ITEM['observed_at']}],
    [{'sentinel5pProductId': ID, 'date': '2026-10-14T12:42:54Z'}],
    [{'sentinel5pProductId': ID, 'date': ITEM['observed_at']}]*2])
def test_decode_fails_closed_on_missing_product_mosaic_or_wrong_time(tiles):
    with pytest.raises(Sentinel5PError):
        decode(archive(tiles=tiles), ITEM, grid())


def test_corrupt_duplicate_wrong_grid_dtype_and_masks_rejected():
    wrong_mask = raster_data()
    wrong_mask[1, 0, 0] = .5
    for body in [b'not tar', archive(duplicate=True), archive(bbox=[n+20 for n in grid()['bbox']]),
                 archive(dtype='uint8'), archive(wrong_mask)]:
        with pytest.raises(Sentinel5PError):
            decode(body, ITEM, grid())


def test_scientific_masks_zero_negative_nodata_and_qa_rejection_are_disjoint():
    small_grid = {**grid(), 'width': 4, 'height': 2}
    half_item = {**ITEM, 'geometry': {'type': 'Polygon', 'coordinates': [
        [[12, 48], [22.5, 48], [22.5, 56], [12, 56], [12, 48]]]}}
    raw = np.ones((3, 2, 4), dtype='float32')
    raw[0] = [[0, -.00002, .0002, 0], [.0001, 0, .0001, 0]]
    raw[1, :, 3] = 0  # Outside footprint, no coverage.
    raw[1, 1, 1] = 0  # Inside footprint, no source data.
    filtered = raw.copy()
    filtered[1, 1, 2] = 0  # Source value exists, but failed QA.
    result = images(raw, filtered, half_item, PARAMETERS['no2'], DAY, small_grid)
    quality = result['quality']
    assert {k: quality[k] for k in ('valid_percent', 'no_coverage_percent', 'rejected_percent', 'nodata_percent',
                                    'zero_percent', 'negative_percent')} == {
        'valid_percent': 50, 'no_coverage_percent': 25, 'rejected_percent': 12.5, 'nodata_percent': 12.5,
        'zero_percent': 12.5, 'negative_percent': 12.5}
    assert quality['minimum'] < 0
    with MemoryFile(base64.b64decode(result['image'])) as memory, memory.open() as raster:
        alpha = raster.read(4)
        assert alpha[0, 0] > 0 and alpha[0, 1] > 0  # Genuine zero and negative are visible.
        assert alpha[0, 3] == alpha[1, 1] == alpha[1, 2] == 0  # No interpolation into gaps.


@pytest.mark.parametrize('kind,expected', [('raw_missing', 'nodata'), ('qa_rejected', 'quality_rejected'),
                                          ('outside', 'no_coverage')])
def test_empty_image_states(kind, expected):
    raw = raster_data()
    filtered = raw.copy()
    item = ITEM
    filtered[1] = 0
    if kind != 'qa_rejected':
        raw[1] = 0
    if kind == 'outside':
        item = {**ITEM, 'geometry': {'type': 'Polygon', 'coordinates': [
            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}
    assert images(raw, filtered, item, PARAMETERS['no2'], DAY)['status'] == expected


def test_nonfinite_retrieval_and_inconsistent_filters():
    raw = raster_data()
    raw[0, :3, :3] = np.nan
    filtered = raw.copy()
    assert images(raw, filtered, ITEM, PARAMETERS['no2'], DAY)['quality']['nodata_percent'] > 0
    raw[1, 10, 10] = 0
    with pytest.raises(Sentinel5PError, match='niespójne'):
        images(raw, filtered, ITEM, PARAMETERS['no2'], DAY)


async def test_search_render_singleflight_cache_and_secret_isolation():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls))) as client:
        service = Sentinel5PService(client, configured())
        searches = await asyncio.gather(*(service.search('no2', DAY) for _ in range(5)))
        assert len(calls) == 2 and searches[0]['truncated']
        assert searches[0]['day'] == DAY and searches[0]['items'][0]['id'] == ID
        rendered = await asyncio.gather(*(service.render('no2', DAY, ID) for _ in range(5)))
        assert len(calls) == 4 and rendered[0]['status'] == 'ready'
        assert rendered[0]['age_hours'] is not None
        assert rendered[0]['fetched_at']
        body = json.dumps(searches+rendered)
        assert not any(secret in body for secret in ('private-client', 'private-secret', 'private-token'))
        service.items.clear()
        await service.search('no2', DAY)
        await service.render('no2', DAY, ID)
        assert len(calls) == 4
        searches[0]['items'].clear()
        assert len((await service.search('no2', DAY))['items']) == 1  # Cache insulated from response mutation.
        await service.close()


async def test_adjacent_granules_excluded_from_inclusive_process_time_range():
    identifiers = [
        'S5P_NRTI_L2__NO2____20261015T105754_20261015T110254_46663_03_020901_20261015T113634.nc',
        'S5P_NRTI_L2__NO2____20261015T110254_20261015T110754_46663_03_020901_20261015T130501.nc',
    ]
    starts = ['2026-10-15T10:57:54+00:00', '2026-10-15T11:02:54+00:00']
    features = [{**copy.deepcopy(FEATURE), 'id': identifier, 'properties': {
        **FEATURE['properties'], 'datetime': start}} for identifier, start in zip(identifiers, starts)]
    process_calls = []

    def respond(request):
        if str(request.url) == TOKEN:
            return httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
        if str(request.url) == CATALOG:
            return httpx.Response(200, json={'features': features})
        assert str(request.url) == PROCESS
        source = json.loads(request.content)['input']['data'][0]
        interval = source['dataFilter']['timeRange']
        start, end = (datetime.fromisoformat(interval[key]) for key in ('from', 'to'))
        # CDSE includes a granule starting exactly at `to`. ORBIT tile metadata is
        # only populated after preProcessScenes, so that hook cannot remove it.
        tiles = [{'date': feature['properties']['datetime'], 'sentinel5pProductId': feature['id']}
                 for feature in features
                 if start <= datetime.fromisoformat(feature['properties']['datetime']) <= end]
        process_calls.append((source['processing']['minQa'], interval, tiles))
        return httpx.Response(200, content=archive(tiles=tiles, nested=True))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = Sentinel5PService(client, configured())
        try:
            found = await service.search('no2', DAY)
            assert {item['id'] for item in found['items']} == set(identifiers)
            selected = next(item for item in found['items'] if item['id'] == identifiers[0])
            rendered = await service.render('no2', DAY, selected['id'])
            assert rendered['status'] == 'ready' and rendered['mosaic'] is False
            assert rendered['item']['product_ids'] == [identifiers[0]]
            for item in (selected, rendered['item']):
                assert item['observed_at'] == item['observation_start'] == starts[0]
                assert item['observation_end'] == starts[1]
                assert item['product_generated_at'] == '2026-10-15T11:36:34+00:00'
            assert [qa for qa, _, _ in process_calls] == [0, 76]
            for _, interval, tiles in process_calls:
                assert datetime.fromisoformat(interval['from']) == datetime.fromisoformat(starts[0])
                assert datetime.fromisoformat(interval['to']) == (
                    datetime.fromisoformat(starts[1])-timedelta(milliseconds=1))
                assert [tile['sentinel5pProductId'] for tile in tiles] == [identifiers[0]]
        finally:
            await service.close()


@pytest.mark.parametrize('code,expected', [(401, 'auth_error'), (403, 'account_limit'),
    (429, 'rate_limited'), (500, 'provider_error'), (503, 'provider_error')])
async def test_provider_failure_sanitization_and_millisecond_backoff(code, expected):
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls, code))) as client:
        service = Sentinel5PService(client, configured())
        with pytest.raises(Sentinel5PError) as error:
            await service.search('no2', DAY)
        assert error.value.status == expected and 'private' not in str(error.value)
        assert len(calls) == 2 and not service.jobs
        if code in (429, 503):
            assert error.value.retry == 4
            with pytest.raises(Sentinel5PError):
                await service.search('no2', DAY)
            assert len(calls) == 2
        if code == 401:
            assert service.expires == 0
        await service.close()


async def test_timeout_size_limit_http_date_and_oauth_retry_seconds():
    def oversized(request):
        return httpx.Response(200, content=b'x'*(MAX_BYTES+1))
    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        with pytest.raises(Sentinel5PError, match='8 MiB'):
            await Sentinel5PService(client, configured()).request(CATALOG)
    def timeout(request):
        raise httpx.ReadTimeout('private-token')
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(Sentinel5PError, match='timeout'):
            await Sentinel5PService(client, configured()).request(CATALOG)
    for url, header, minimum in [(TOKEN, '15', 15), (PROCESS, '15000', 15),
        (PROCESS, (datetime.now(UTC)+timedelta(seconds=120)).strftime('%a, %d %b %Y %H:%M:%S GMT'), 118)]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request, header=header:
                httpx.Response(429, headers={'Retry-After': header}))) as client:
            with pytest.raises(Sentinel5PError) as error:
                await Sentinel5PService(client, configured()).request(url)
            assert error.value.retry >= minimum


async def test_cache_bounds_expiry_concurrency_cancel_and_close():
    service = Sentinel5PService(None, Config(), demo=True)
    count, active, peak = 0, 0, 0
    async def work():
        nonlocal count, active, peak
        count += 1
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.005)
        active -= 1
        return count
    await asyncio.gather(*(service.cached(i, work) for i in range(8)))
    assert peak == 2
    for key in range(8, 15):
        await service.cached(key, work)
    assert len(service.cache) == 12 and 0 not in service.cache
    service.cache[14] = (time.monotonic()-1, 'expired')
    assert await service.cached(14, work) != 'expired'
    started, release = asyncio.Event(), asyncio.Event()
    async def held():
        started.set()
        await release.wait()
        return 42
    waiter = asyncio.create_task(service.cached('shared', held))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    assert await service.cached('shared', held) == 42
    await service.close()
    assert not service.jobs and not service.credentials and not service.token and not service.cache
    with pytest.raises(Sentinel5PError):
        await service.cached('closed', work)


async def test_queue_limit_and_shutdown_cancels_owned_work():
    service = Sentinel5PService(None, Config(), demo=True)
    release = asyncio.Event()
    callers = [asyncio.create_task(service.cached(i, release.wait)) for i in range(8)]
    await asyncio.sleep(.005)
    with pytest.raises(Sentinel5PError) as error:
        await service.cached(9, release.wait)
    assert error.value.code == 429
    await service.close()
    await asyncio.gather(*callers, return_exceptions=True)
    assert not service.jobs


async def test_offline_demo_parameter_day_and_expired_selection():
    def no_network(request):
        pytest.fail('Synthetic demo called provider')
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as client:
        service = Sentinel5PService(client, configured(), demo=True)
        assert service.status()['status'] == 'demo'
        images_by_parameter = []
        for parameter in PARAMETERS:
            found = await service.search(parameter, DAY)
            assert all(item['mode'] == 'SYNTHETIC' and 'syntetyczne' in item['attribution'] for item in found['items'])
            rendered = [await service.render(parameter, DAY, item['id']) for item in found['items']]
            assert rendered[0]['image'] != rendered[1]['image']
            images_by_parameter.append(rendered[0]['parameter']['id'])
            with pytest.raises(Sentinel5PError):
                await service.render(parameter, '2026-10-14', found['items'][0]['id'])
            key = (parameter, DAY, found['items'][0]['id'])
            service.items[key] = (time.monotonic()-1, found['items'][0])
            with pytest.raises(Sentinel5PError):
                await service.render(*key)
        assert images_by_parameter == ['no2', 'so2', 'aer_ai']
        await service.close()


async def test_unconfigured_no_requests_and_explicit_s2_fallback():
    service = Sentinel5PService(None, Config())
    assert service.status()['status'] == 'unconfigured'
    assert (await service.search('no2', DAY))['items'] == []
    cfg = Config(sources={'sentinel2': {'enabled': True, 'client_id': 'a', 'client_secret': 'b'}})
    assert not Sentinel5PService(None, cfg).enabled
    cfg.sources['sentinel5p'] = {'enabled': True}
    assert Sentinel5PService(None, cfg).enabled
    cfg.sources['sentinel5p']['client_id'] = 'partial'
    assert not Sentinel5PService(None, cfg).enabled


async def test_legacy_so2_excluded_without_hiding_supported_reprocessed_product():
    old = copy.deepcopy(FEATURE)
    old['id'] = ID.replace('NO2___', 'SO2___').replace('020901', '010202')
    old['properties']['s5p:type'] = 'SO2'
    supported = copy.deepcopy(old)
    supported['id'] = old['id'].replace('NRTI', 'RPRO').replace('010202', '020901')
    supported['properties']['s5p:timeliness'] = 'RPRO'
    for features, count in [([old], 0), ([old, supported], 1)]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request, features=features:
            httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
            if str(request.url) == TOKEN else httpx.Response(200, json={'features': features}))) as client:
            service = Sentinel5PService(client, configured())
            found = await service.search('so2', DAY)
            assert len(found['items']) == count and found['unsupported_product_count'] == 1
            assert 'SO₂ V1' in found['message']
            assert found['status'] == ('ready' if count else 'no_data')
            with pytest.raises(Sentinel5PError):
                await service.render('so2', DAY, old['id'])
            await service.close()


async def test_live_probe_script_is_bounded_and_writes_only_sanitized_evidence(tmp_path):
    import re
    import runpy
    from pathlib import Path

    run_probe = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check_sentinel5p.py'))['run_probe']
    calls = []
    def respond(request):
        calls.append(request)
        if str(request.url) == TOKEN:
            return httpx.Response(200, json={'access_token': 'private-token', 'expires_in': 3600})
        payload = json.loads(request.content)
        if str(request.url) == CATALOG:
            product = payload['filter'].split("'")[1]
            feature = copy.deepcopy(FEATURE)
            feature['id'] = ID.replace('NO2___', product.ljust(6, '_'))
            feature['properties']['s5p:type'] = product
            return httpx.Response(200, json={'features': [feature]})
        identity = json.loads(re.search(r'const target=([^;]+);', payload['evalscript'])[1])
        return httpx.Response(200, content=archive(tiles=[{
            'date': ITEM['observed_at'], 'sentinel5pProductId': identity}]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        report = await run_probe(configured(), DAY, tmp_path, client)
    assert report['searches'] == report['render_attempts'] == len(report['results']) == 3
    assert report['status'] == 'checked' and len(calls) == 10
    assert len(list(tmp_path.glob('*.png'))) == 6
    assert not any(secret in json.dumps(report) for secret in ('private-token', 'private-secret', 'private-client'))
    assert report['limitations']


def test_actual_cdse_orbit_metadata_shape_and_legacy_js_compatibility():
    np.testing.assert_array_equal(decode(archive(nested=True), ITEM, grid()), raster_data())
    script = evalscript(PARAMETERS['no2'], ID)
    assert '...' not in script and '?.' not in script  # CDSE evalscript engine rejects object spread.
    assert '&&o.tiles.length' in script  # preProcessScenes exposes empty tiles; do not discard those orbits.


async def test_total_operation_deadline_cleans_up_job(monkeypatch):
    original_timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, 'timeout', lambda seconds: original_timeout(.005))
    service = Sentinel5PService(None, Config(), demo=True)
    wait = asyncio.Event()
    with pytest.raises(Sentinel5PError, match='75 s'):
        await service.cached('deadline', wait.wait)
    assert not service.jobs and not service.cache
    await service.close()


async def test_invalid_oauth_and_expired_token_are_sanitized():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(400, text='private-client private-secret'))) as client:
        service = Sentinel5PService(client, configured())
        with pytest.raises(Sentinel5PError) as error:
            await service.search('no2', DAY)
        assert error.value.status == 'auth_error' and error.value.code == 401
        assert 'private' not in str(error.value)
        await service.close()
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler(calls))) as client:
        service = Sentinel5PService(client, configured())
        await service.authorized(CATALOG, {})
        service.expires = 0
        await service.authorized(CATALOG, {})
        assert sum(str(request.url) == TOKEN for request in calls) == 2
        await service.close()
