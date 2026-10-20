"""Exercise real GDAL callbacks, rather than mocking the raster operation that fails."""
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import from_origin
from rasterio.windows import Window

from wici.gfm import GDALRangeReader, GFMUnavailable, cog_errors

URL = 'https://data.eodc.eu/collections/GFM_LAYERS/io-test.tif'


@pytest.fixture
def cog_bytes():
    with rasterio.io.MemoryFile() as memory:
        with memory.open(driver='GTiff', width=1024, height=1024, count=1, dtype='uint8',
                         crs='EPSG:3857', transform=from_origin(1800000, 6500000, 20, 20),
                         nodata=255, tiled=True, blockxsize=256, blockysize=256) as dst:
            dst.write(np.ones((1024, 1024), dtype='uint8'), 1)
        return memory.read()


@pytest.mark.parametrize('failure', ['bytes', 'deadline', 'requests', 'network'])
def test_gdal_callback_reports_failure_without_unraisable_exception(cog_bytes, monkeypatch, capsys, failure):
    import sys

    from wici import gfm
    unraisable = []
    monkeypatch.setattr(sys, 'unraisablehook', unraisable.append)
    calls = []
    broken = False
    def handler(request):
        calls.append(request)
        if broken and failure == 'network':
            raise httpx.ReadTimeout('Synthetic read timeout')
        start, end = map(int, request.headers['range'][6:].split('-'))
        end = min(end, len(cog_bytes)-1)
        return httpx.Response(206, headers={'Content-Range': f'bytes {start}-{end}/{len(cog_bytes)}'},
                              content=cog_bytes[start:end+1])
    budget = {'bytes': 0, 'requests': 0, 'deadline': time.monotonic()+40}
    message = {'bytes': 'limit transferu', 'deadline': 'czas odczytu',
               'requests': 'limit żądań', 'network': 'Błąd połączenia'}[failure]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def opener(path, mode='rb'):
            if path != URL:
                raise FileNotFoundError(path)
            return GDALRangeReader(path, client, budget)
        with (pytest.raises(GFMUnavailable, match=message), cog_errors(budget),
              rasterio.open(URL, opener=opener, driver='GTiff') as src):
            # Fail only after GDAL has successfully opened a real georeferenced TIFF.
            if failure == 'bytes':
                monkeypatch.setattr(gfm, 'MAX_BYTES', budget['bytes']+128)
            elif failure == 'deadline':
                budget['deadline'] = 0
            elif failure == 'requests':
                budget['max_requests'] = budget['requests']
            broken = True
            src.read(1, window=Window(768, 768, 256, 256))
    assert message in budget['error']
    assert unraisable == []
    output = capsys.readouterr()
    assert 'Exception ignored' not in output.err and 'Traceback' not in output.err
    assert len(calls) <= 4, 'Failure must latch instead of letting GDAL retry remote reads'


def test_swallowed_native_failure_cannot_publish_a_successful_result():
    budget = {'error': 'Upłynął czas odczytu COG.'}
    with pytest.raises(GFMUnavailable, match='czas odczytu'), cog_errors(budget):
        pass  # Even if GDAL returns normally, a failed source is never accepted.


@pytest.mark.parametrize('failure', ['deadline', 'network'])
def test_gdal_open_failure_is_controlled_and_does_not_retry(monkeypatch, capsys, failure):
    import sys
    unraisable, calls = [], []
    monkeypatch.setattr(sys, 'unraisablehook', unraisable.append)
    def handler(request):
        calls.append(request)
        raise httpx.ConnectError('Synthetic connection failure')
    budget = {'bytes': 0, 'requests': 0, 'deadline': 0 if failure == 'deadline' else time.monotonic()+40}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def opener(path, mode='rb'):
            if path != URL:
                raise FileNotFoundError(path)
            return GDALRangeReader(path, client, budget)
        with pytest.raises(GFMUnavailable), cog_errors(budget), rasterio.open(URL, opener=opener):
            pytest.fail('A failed source must not open')
    assert len(calls) <= 1 and not unraisable
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('worker', ['archive', 'monitor'])
def test_real_raster_workers_report_callback_limit_as_gfm_failure(cog_bytes, monkeypatch, worker):
    import sys
    from datetime import UTC, datetime

    from wici import gfm
    from wici.gfm_monitor import monitor_item, scan_product

    unraisable = []
    monkeypatch.setattr(sys, 'unraisablehook', unraisable.append)
    original_client = httpx.Client
    def handler(request):
        start, end = map(int, request.headers['range'][6:].split('-'))
        end = min(end, len(cog_bytes)-1)
        return httpx.Response(206, headers={'Content-Range': f'bytes {start}-{end}/{len(cog_bytes)}'},
                              content=cog_bytes[start:end+1])
    monkeypatch.setattr(gfm.httpx, 'Client', lambda: original_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(gfm, 'MAX_BYTES', 3*65536+128)
    raw = {'id': 'native-io-test', 'collection': 'GFM', 'properties': {'datetime': '2026-10-17T05:00:00Z'},
           'assets': {name: {'href': URL.replace('io-test', name)} for name in gfm.REQUIRED}}
    item = monitor_item(raw, datetime(2026,10,17,12,tzinfo=UTC))
    box = rasterio.warp.transform_bounds('EPSG:3857', 'EPSG:4326', 1800000,6479520,1820480,6500000)
    w,s,e,n = box
    country = [{'type': 'Polygon', 'coordinates': [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}]
    with pytest.raises(GFMUnavailable, match='limit transferu'):
        if worker == 'archive':
            gfm.render_product(item, box)
        else:
            scan_product(item, country)
    assert unraisable == []


def test_georeferenced_polygonization_in_parallel_has_no_warning():
    # Reuse the synthetic native record used by the monitor tests, with no network.
    from test_gfm_monitor import record, service

    from wici.gfm_monitor import GFMMonitor

    mon = GFMMonitor(service(), geometries=[])
    r = record()
    mon.records[r['item']['key']] = r
    with warnings.catch_warnings():
        warnings.simplefilter('error', NotGeoreferencedWarning)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(mon._snapshot, [(14,49,24.3,55)]*8))
    for result in results:
        geom = result['features'][0]['geometry']
        x, y = rasterio.warp.transform('EPSG:4326', 'EPSG:3857',
                                      *zip(*geom['coordinates'][0][0]))
        assert min(x) == pytest.approx(1800400)
        assert max(x)-min(x) == pytest.approx(20)
        assert min(y) == pytest.approx(6499780)
        assert max(y)-min(y) == pytest.approx(20)
