"""National automation: native pixels, temporal replacement, bounds, progress and offline lifecycle."""
import asyncio
import threading
import zlib
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform, transform_bounds

from wici.app import create_app
from wici.gfm import LAYERS, GFMService, GFMUnavailable
from wici.gfm_monitor import BLOCK, GFMMonitor, latest_pixels, monitor_item, scan_product, view_bbox

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def feature(identifier='test', observed='2026-10-17T05:08:27Z'):
    return {'id': identifier, 'collection': 'GFM', 'properties': {'datetime': observed,
        'created': '2026-10-17T06:39:47Z', 'processing:datetime': '2026-10-17T06:38:57Z',
        'processing:version': 'v4.1.1'}, 'assets': {name: {
            'href': 'https://data.eodc.eu/collections/GFM_LAYERS/'+name+'.tif'} for name in LAYERS}}


def record(identifier='old', observed='2026-10-17T05:00:00+00:00', points=((10, 20, 0, 90),), covered=((10, 20),)):
    valid = np.zeros((BLOCK, BLOCK), dtype='uint8')
    for row, col in covered:
        valid[row, col] = 1
    item = monitor_item(feature(identifier, observed), NOW)
    return {'item': item, 'points': np.asarray(points, dtype='uint16').reshape((-1, 4)),
            'coverage': {(0, 0): zlib.compress(np.packbits(valid).tobytes())}, 'grid_key': 'same-grid',
            'grid': {'crs': 'EPSG:3857', 'transform': [20, 0, 1800000, 0, -20, 6500000],
                     'width': 512, 'height': 512}, 'size': 100, 'truncated': False}


def service(handler=lambda r: httpx.Response(200, json={'type': 'FeatureCollection', 'features': []})):
    return GFMService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), lambda: NOW)


@pytest.fixture
def native(tmp_path):
    crs = '+proj=aeqd +lat_0=53 +lon_0=24 +x_0=5837287.81977 +y_0=2121415.69617 +datum=WGS84 +units=m'
    x, y = transform('EPSG:4326', crs, [16.65], [50.44])
    affine = from_origin(x[0], y[0]+20480, 20, 20)
    bbox = transform_bounds(crs, 'EPSG:4326', x[0]-1, y[0]-1, x[0]+20481, y[0]+20481)
    w, s, e, n = bbox
    country = [{'type': 'Polygon', 'coordinates': [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}]
    def write(name, data):
        with rasterio.open(tmp_path/(name+'.tif'), 'w', driver='GTiff', width=1024, height=1024,
                           count=1, crs=crs, transform=affine, dtype='uint8', nodata=255,
                           tiled=True, blockxsize=512, blockysize=512) as dst:
            dst.write(data, 1)
    def opener(url, mode='rb'):
        return open(tmp_path/url.rsplit('/',1)[1], mode)
    return write, opener, country


def test_scan_native_pixels_and_quality_without_preview_downsampling(native):
    write, opener, country = native
    for name in LAYERS:
        data = np.zeros((1024,1024), dtype='uint8')
        if name == 'ensemble_flood_extent':
            for row,col in [(10,20),(11,21),(12,22),(600,700)]:
                data[row,col] = 1
        if name == 'reference_water_mask':
            data[11,21] = 1
        if name == 'exclusion_mask':
            data[12,22] = 1
        if name == 'advisory_flags':
            data[10,20] = 2
        if name == 'ensemble_likelihood':
            data[10,20] = 90
        write(name, data)
    result = scan_product(monitor_item(feature(), NOW), country, opener=opener)
    assert result['points'].tolist() == [[10,20,2,90],[600,700,0,0]]
    assert result['total'] == 2 and not result['truncated']
    bits = np.unpackbits(np.frombuffer(zlib.decompress(result['coverage'][(0,0)]), dtype='uint8'))
    assert bits[11*BLOCK+21] == bits[12*BLOCK+22] == 1


def test_scan_limits_points_but_keeps_coverage_for_temporal_replacement(native, monkeypatch):
    write, opener, country = native
    monkeypatch.setattr('wici.gfm_monitor.MAX_POINTS', 1)
    for name in LAYERS:
        data = np.zeros((1024,1024), dtype='uint8')
        if name == 'ensemble_flood_extent':
            data[10,20:23] = 1
        write(name, data)
    result = scan_product(monitor_item(feature(), NOW), country, opener=opener)
    assert len(result['points']) == 1 and result['total'] == 3 and result['truncated']
    bits = np.unpackbits(np.frombuffer(zlib.decompress(result['coverage'][(0,0)]), dtype='uint8'))
    assert bits[10*BLOCK+22] == 1


@pytest.mark.parametrize('newer_points', [(), ((10,20,1,85),)])
def test_latest_assessed_pixel_replaces_older_flood(newer_points):
    old = record()
    new = record('new', '2026-10-17T06:00:00+00:00', points=newer_points)
    result = latest_pixels([old,new])
    assert [r['item']['id'] for r,p in result] == (['new'] if newer_points else [])


def test_nodata_and_different_grids_do_not_erase_an_older_valid_detection():
    old = record()
    new = record('new','2026-10-17T06:00:00+00:00',points=(),covered=())
    assert latest_pixels([old,new])[0][0]['item']['id'] == 'old'
    new = record('new','2026-10-17T06:00:00+00:00',points=())
    new['grid_key'] = 'different-tile'
    assert latest_pixels([old,new])[0][0]['item']['id'] == 'old'


def test_snapshot_overview_and_actual_twenty_metre_geometry():
    mon = GFMMonitor(service(), geometries=[])
    r = record();mon.records[r['item']['key']] = r;mon.catalog = [r['item']]
    result = mon._snapshot((14,49,24.3,55))
    assert result['pixels'] == 1 and len(result['clusters']) == len(result['features']) == 1
    geom = result['features'][0]['geometry']
    assert geom['type'] == 'MultiPolygon'
    corners = geom['coordinates'][0][0]
    x,y = transform('EPSG:4326','EPSG:3857',*[list(values) for values in zip(*corners)])
    assert max(x)-min(x) == pytest.approx(20)
    assert max(y)-min(y) == pytest.approx(20)
    assert result['features'][0]['properties']['product']['observed_at'] == r['item']['observed_at']


def test_monitor_metadata_preserves_times_and_exposes_missing_masks():
    raw = feature();del raw['assets']['exclusion_mask']
    item = monitor_item(raw,NOW)
    assert item['observed_at'] != item['catalog_created_at'] != item['processed_at']
    assert item['missing_assets'] == ['exclusion_mask']
    assert monitor_item(feature(observed='2024-09-15T05:01:49Z'),NOW) is None
    raw = feature();raw['assets']['exclusion_mask']['href'] = 'https://localhost/evil.tif'
    assert monitor_item(raw,NOW)['missing_assets'] == ['exclusion_mask']


async def test_catalog_paginates_only_with_validated_token_and_fixed_poland_query():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.params['bbox'] == '14,49,24.3,55'
        if len(calls)==1:
            return httpx.Response(200,json={'features':[feature('a')], 'links':[{'rel':'next',
                'href':'https://stac.eodc.eu/api/v1/search?token=next:test&bbox=0,0,1,1'}]})
        assert request.url.params['token'] == 'next:test'
        return httpx.Response(200,json={'features':[feature('b')]})
    mon=GFMMonitor(service(handler),geometries=[])
    await mon._catalog()
    assert len(mon.catalog)==2 and len(calls)==2
    assert mon.catalog_due == NOW+timedelta(minutes=10)


async def test_catalog_rejects_untrusted_pagination_without_replacing_previous_data():
    mon=GFMMonitor(service(lambda r:httpx.Response(200,json={'features':[], 'links':[
        {'rel':'next','href':'http://127.0.0.1/evil?token=x'}]})),geometries=[])
    mon.catalog=[monitor_item(feature('old'),NOW)]
    with pytest.raises(GFMUnavailable):
        await mon._catalog()
    assert mon.catalog[0]['id']=='old'


async def test_only_active_poll_advances_work_and_concurrent_polls_share_a_scan(monkeypatch):
    mon=GFMMonitor(service(),geometries=[])
    mon.catalog=[monitor_item(feature('a'),NOW),monitor_item(feature('b'),NOW)]
    mon.catalog_due=NOW+timedelta(minutes=10)
    entered,finish=threading.Event(),threading.Event();calls=[]
    def scan(item,geometries,budget):
        calls.append(item['id']);entered.set();assert finish.wait(3)
        r=record(item['id']);r['item']=item;return r
    monkeypatch.setattr('wici.gfm_monitor.scan_product',scan)
    try:
        await mon.snapshot()
        for _ in range(100):
            if entered.is_set():break
            await asyncio.sleep(.01)
        await mon.snapshot()
        assert calls==['a']
    finally:
        finish.set();await mon.close()
    await asyncio.sleep(.02)
    assert calls==['a'], 'No next scan without another active-layer request'
    await mon.snapshot();await mon.close()
    assert calls==['a','b']


async def test_failure_honours_retry_after_and_retains_previous_results(monkeypatch):
    mon=GFMMonitor(service(),geometries=[])
    old=record();mon.records[old['item']['key']]=old
    mon.catalog=[monitor_item(feature('new'),NOW),old['item']];mon.catalog_due=NOW+timedelta(minutes=10)
    def scan(item,geometries,budget):
        budget['retry']=120
        raise GFMUnavailable('rate limited')
    monkeypatch.setattr('wici.gfm_monitor.scan_product',scan)
    await mon._step()
    assert mon.service.retry_at==NOW+timedelta(seconds=120)
    result=mon._snapshot(None)
    assert result['pixels']==1 and result['status']=='partial' and result['message']
    assert 'rate limited' in result['message'], 'The UI must receive the actual source failure reason'


def test_view_bounds_allow_country_and_clip_large_viewports():
    assert view_bbox('-180,-80,180,80')==(14,49,24.3,55)
    assert view_bbox('0,0,1,1') is None
    for invalid in ['nan,49,24,55','14,49,13,55','bad','14,49,24']:
        with pytest.raises(ValueError):view_bbox(invalid)


def test_monitor_api_is_offline_in_demo_and_rejects_cross_origin(tmp_path):
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/gfm/monitor').json()['status']=='demo_no_data'
        assert client.get('/api/gfm/monitor',headers={'sec-fetch-site':'cross-site'}).status_code==403
        assert client.get('/api/gfm/monitor?bbox=nan,49,24,55').status_code==422


def test_monitor_response_limit_is_explicit_and_does_not_claim_zero_detections(monkeypatch):
    monkeypatch.setattr('wici.gfm_monitor.MAX_RESPONSE_BYTES', 1000)
    mon=GFMMonitor(service(),geometries=[])
    r=record();mon.records[r['item']['key']]=r
    result=mon._snapshot((14,49,24.3,55))
    assert result['truncated'] and result['status']=='partial' and result['pixels']==1
    assert result['features']==[] and result['clusters']==[]


def test_expired_records_disappear_and_change_map_revision():
    svc=service();mon=GFMMonitor(svc,geometries=[])
    r=record();mon.records[r['item']['key']]=r
    before=mon._snapshot(None)
    svc.clock=lambda:NOW+timedelta(days=3)
    after=mon._snapshot(None)
    assert after['pixels']==0 and after['clusters']==[] and after['revision']!=before['revision']


def test_subpixel_view_keeps_intersecting_native_flood_geometry():
    mon=GFMMonitor(service(),geometries=[])
    r=record();mon.records[r['item']['key']]=r
    x=1800000+20*20+1;y=6500000-10*20-1
    w,s,e,n=transform_bounds('EPSG:3857','EPSG:4326',x,y-1,x+1,y)
    result=mon._snapshot((w,s,e,n))
    assert result['features'][0]['properties']['pixels']==1


async def test_national_catalog_has_a_hard_pagination_limit():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'features':[feature(str(len(calls)))], 'links':[
            {'rel':'next','href':f'https://stac.eodc.eu/api/v1/search?token={len(calls)}'}]})
    mon=GFMMonitor(service(handler),geometries=[])
    await mon._catalog()
    assert len(calls)==4 and mon.limited


async def test_fully_scanned_catalog_is_idle_until_catalog_refresh_is_due():
    mon=GFMMonitor(service(),geometries=[])
    r=record();mon.records[r['item']['key']]=r;mon.catalog=[r['item']]
    mon.catalog_due=NOW+timedelta(minutes=10)
    result=await mon.snapshot()
    assert mon.task is None and result['busy'] is False and result['poll_after_seconds']==30


@pytest.mark.parametrize('replacement_points', [(), ((10,20,1,85),)])
async def test_reprocessing_keeps_last_assessment_through_refresh_inflight_failure_and_retry(
        monkeypatch, replacement_points):
    now = NOW
    old_flood = record('flood')
    previous = record('assessment', '2026-10-17T06:00:00+00:00', points=())
    raw_flood = feature('flood', old_flood['item']['observed_at'])
    revised = feature('assessment', previous['item']['observed_at'])
    revised['properties']['processing:datetime'] = '2026-10-17T07:00:00Z'
    svc = service(lambda request: httpx.Response(200, json={'features': [revised, raw_flood]}))
    svc.clock = lambda: now
    mon = GFMMonitor(svc, geometries=[])
    mon.records = {r['item']['key']: r for r in [old_flood, previous]}
    assert mon._snapshot(None)['pixels'] == 0

    await mon._catalog()
    replacement = next(item for item in mon.catalog if item['id'] == 'assessment')
    assert replacement['key'] != previous['item']['key']
    assert mon._snapshot(None)['pixels'] == 0, 'Metadata must not resurrect the older flood'
    assert mon._snapshot(None)['processed'] == 1
    assert mon._snapshot(None)['status'] == 'partial'

    entered, finish = threading.Event(), threading.Event()
    def failed_scan(item, geometries, budget):
        assert item['key'] == replacement['key']
        entered.set()
        assert finish.wait(3)
        raise GFMUnavailable('Replacement raster offline')
    monkeypatch.setattr('wici.gfm_monitor.scan_product', failed_scan)
    task = asyncio.create_task(mon._step())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert mon._snapshot(None)['pixels'] == 0
        assert mon.records[previous['item']['key']] is previous
    finally:
        finish.set()
        await task
    failed = mon._snapshot(None)
    assert failed['pixels'] == 0 and failed['failed'] == 1 and failed['status'] == 'partial'
    assert mon.records[previous['item']['key']] is previous

    replacement_record = record('assessment', previous['item']['observed_at'], points=replacement_points)
    replacement_record['item'] = {k: v for k, v in replacement.items() if k != 'assets'}
    def successful_scan(item, geometries, budget):
        assert item['key'] == replacement['key']
        return replacement_record
    monkeypatch.setattr('wici.gfm_monitor.scan_product', successful_scan)
    now += timedelta(minutes=10)
    await mon._step()
    final = mon._snapshot(None)
    assert final['pixels'] == len(replacement_points)
    assert final['processed'] == 2 and final['status'] == 'ready' and final['failed'] == 0
    assert previous['item']['key'] not in mon.records
    assert mon.records[replacement['key']] is replacement_record
    assert len(mon.records) == 2
    await svc.client.aclose()


async def test_incomplete_replacement_keeps_previous_version_and_expired_assessment_still_expires():
    now = NOW
    previous = record()
    revised = feature(previous['item']['id'], previous['item']['observed_at'])
    del revised['assets']['exclusion_mask']
    svc = service(lambda request: httpx.Response(200, json={'features': [revised]}))
    svc.clock = lambda: now
    mon = GFMMonitor(svc, geometries=[])
    mon.records[previous['item']['key']] = previous
    await mon._catalog()
    result = mon._snapshot(None)
    assert result['pixels'] == 1 and result['unavailable'] == 1 and result['status'] == 'partial'
    assert mon._pending() is None
    now += timedelta(hours=49)
    assert mon._snapshot(None)['pixels'] == 0
    await mon._catalog()
    assert not mon.records
    await svc.client.aclose()
