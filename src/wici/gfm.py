"""Bounded on-demand GFM STAC and COG windows. No user-supplied remote URLs."""
import asyncio
import base64
import io
import json
import math
import re
import struct
import time
import zlib
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as transform_coordinates
from rasterio.warp import transform_bounds
from rasterio.windows import Window

STAC = 'https://stac.eodc.eu/api/v1'
LAYERS = ('ensemble_flood_extent', 'reference_water_mask', 'exclusion_mask',
          'advisory_flags', 'ensemble_likelihood')
REQUIRED = LAYERS[:3]
MAX_BYTES = 24 * 1024 * 1024
MAX_PIXELS = 4_000_000
COLORS = np.array([[180, 210, 185, 35], [225, 30, 105, 230], [25, 125, 225, 190],
                   [110, 100, 90, 145], [160, 160, 160, 65]], dtype='uint8')


class GFMUnavailable(Exception):
    """A provider, contract or bounded-resource failure."""


def safe_asset(url):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.netloc == 'data.eodc.eu' and not p.query and not p.fragment
                and '..' not in p.path and re.fullmatch(r'/collections/GFM_[A-Za-z0-9_./-]+\.tif', p.path))
    except (ValueError, TypeError):
        return False


def area(value):
    try:
        box = tuple(float(x) for x in value)
        w, s, e, n = box
        if (all(math.isfinite(x) for x in box) and 14 <= w < e <= 24.3 and 49 <= s < n <= 55
                and e-w <= .5 and n-s <= .5):
            return box
    except (ValueError, TypeError):
        pass
    raise ValueError('Wybierz obszar w Polsce: maksymalnie 0,5° × 0,5° (przybliż mapę).')


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Czas bez strefy')
    return parsed.astimezone(UTC).isoformat()


def retry_seconds(value, now):
    try:
        return max(1, min(3600, int(value)))
    except (ValueError, TypeError):
        try:
            return max(1, min(3600, int((parsedate_to_datetime(value)-now).total_seconds())))
        except (ValueError, TypeError, OverflowError):
            return 60


class RangeReader(io.RawIOBase):
    """GDAL custom opener: strict 206, no redirects, bounded bytes/requests/deadline."""
    def __init__(self, url, client, budget):
        if not safe_asset(url):
            raise GFMUnavailable('Niedozwolony host lub ścieżka zasobu GFM.')
        self.url, self.client, self.budget = url, client, budget
        self.position, self.size = 0, None
        self.blocks = {}
        self._block(0)

    def _block(self, index):
        if index in self.blocks:
            return self.blocks[index]
        b = self.budget
        if time.monotonic() > b['deadline']:
            raise GFMUnavailable('Upłynął czas odczytu COG.')
        if b['requests'] >= b.get('max_requests', 160):
            raise GFMUnavailable('Przekroczono limit żądań COG.')
        if b['bytes'] >= MAX_BYTES:
            raise GFMUnavailable('Przekroczono limit transferu COG.')
        start = index*65536
        b['requests'] += 1
        with self.client.stream('GET', self.url, headers={'Range': f'bytes={start}-{start+65535}'},
                                follow_redirects=False, timeout=8) as response:
            if response.status_code in (429, 503):
                b['retry'] = retry_seconds(response.headers.get('Retry-After'), datetime.now(UTC))
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if response.status_code != 206 or not match or int(match[1]) != start:
                raise GFMUnavailable('Zasób nie udostępnia poprawnego HTTP Range (206).')
            self.size = int(match[3])
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                b['bytes'] += len(chunk)
                if len(body) > 65536:
                    raise GFMUnavailable('Odpowiedź COG przekracza zakres 64 KiB.')
                if b['bytes'] > MAX_BYTES:
                    raise GFMUnavailable('Przekroczono limit transferu COG.')
                if time.monotonic() > b['deadline']:
                    raise GFMUnavailable('Upłynął czas odczytu COG.')
            if len(body) != int(match[2])-start+1:
                raise GFMUnavailable('Niepełny fragment COG.')
        self.blocks[index] = bytes(body)
        return self.blocks[index]

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if self.position < 0:
            raise ValueError('Negative seek')
        return self.position

    def read(self, size=-1):
        if size < 0 or size > MAX_BYTES:
            raise GFMUnavailable('Niedozwolony pełny odczyt rastra.')
        stop = min(self.size, self.position+size)
        chunks = []
        while self.position < stop:
            block = self._block(self.position//65536)
            part = block[self.position % 65536: min(65536, self.position % 65536+stop-self.position)]
            if not part:
                raise GFMUnavailable('Pusty fragment COG.')
            chunks.append(part)
            self.position += len(part)
        return b''.join(chunks)


class GDALRangeReader(RangeReader):
    """Do not let Python exceptions escape GDAL's native read callback.

    A short read tells GDAL that I/O failed. Keep the actual failure in the
    job-local budget and raise it at the Python boundary in cog_errors().
    """
    def __init__(self, url, client, budget):
        if budget.get('error'):
            raise GFMUnavailable(budget['error'])
        try:
            super().__init__(url, client, budget)
        except Exception as exc:
            self._failure(exc, budget)
            raise

    @staticmethod
    def _failure(exc, budget):
        budget.setdefault('error', str(exc) if isinstance(exc, GFMUnavailable) else 'Błąd połączenia podczas odczytu COG.')

    def read(self, size=-1):
        if self.budget.get('error'):
            return b''
        try:
            return super().read(size)
        except Exception as exc:  # noqa: BLE001 -- native callbacks must never leak Python exceptions
            self._failure(exc, self.budget)
            return b''


@contextmanager
def cog_errors(budget):
    """Surface even a swallowed GDAL I/O failure; never publish its partial raster."""
    try:
        yield
    except Exception as exc:
        if budget.get('error'):
            raise GFMUnavailable(budget['error']) from exc
        raise
    if budget.get('error'):
        raise GFMUnavailable(budget['error'])


def classify(flood, reference, exclusion):
    """0 assessed/no detection, 1 flood, 2 reference, 3 excluded, 4 unknown."""
    classes = np.full(flood.shape, 4, dtype='uint8')
    valid = np.isin(flood, [0, 1]) & np.isin(reference, [0, 1, 2]) & np.isin(exclusion, [0, 1])
    classes[valid] = 0
    classes[valid & (flood == 1)] = 1
    classes[valid & (reference > 0)] = 2
    classes[valid & (exclusion == 1)] = 3
    return classes


def class_counts(classes):
    return {name: int(np.count_nonzero(classes == i)) for i, name in enumerate(
        ('assessed_clear', 'flood', 'reference_water', 'excluded', 'no_observation'))}


def source_grid(src, box, window):
    """Cover every native flood pixel whose footprint intersects the WGS84 AOI."""
    left, top = math.floor(window.col_off), math.floor(window.row_off)
    right, bottom = math.ceil(window.col_off+window.width), math.ceil(window.row_off+window.height)
    width, height = right-left, bottom-top
    if width*height > MAX_PIXELS:
        raise GFMUnavailable('Obszar przekracza 4 mln pikseli źródłowych; przybliż mapę.')
    transform = src.window_transform(Window(left, top, width, height))
    west, south, east, north = box
    # Densify geographic edges before projecting: Equi7 bounding boxes include pixels outside the AOI.
    ring = [(x, south) for x in np.linspace(west, east, 65)]
    ring += [(east, y) for y in np.linspace(south, north, 65)[1:]]
    ring += [(x, north) for x in np.linspace(east, west, 65)[1:]]
    ring += [(west, y) for y in np.linspace(north, south, 65)[1:]]
    xs, ys = transform_coordinates('EPSG:4326', src.crs, *zip(*ring))
    inside = geometry_mask([{'type': 'Polygon', 'coordinates': [list(zip(xs, ys))]}],
                           out_shape=(height, width), transform=transform, invert=True, all_touched=True)
    return {'crs': src.crs, 'transform': transform, 'width': width, 'height': height}, inside


def png(rgba):
    def chunk(kind, body):
        return struct.pack('!I', len(body))+kind+body+struct.pack('!I', zlib.crc32(kind+body))
    h, w, _ = rgba.shape
    pixels = b''.join(b'\0'+row.tobytes() for row in rgba)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B', w, h, 8, 6, 0, 0, 0))
            +chunk(b'IDAT', zlib.compress(pixels))+chunk(b'IEND', b''))


def render_product(item, box, opener=None, budget=None):
    """Run only in worker thread. Read native pixels then nearest-neighbour warp."""
    if budget is None:
        budget = {}
    budget.update(bytes=0, requests=0, deadline=time.monotonic()+40)
    arrays, details, source_arrays = {}, {}, {}
    grid, inside = None, None
    destination = transform_bounds('EPSG:4326', 'EPSG:3857', *box)
    width = 768
    height = max(1, min(768, round(width*(destination[3]-destination[1])/(destination[2]-destination[0]))))
    transform = from_bounds(*destination, width, height)
    with cog_errors(budget), httpx.Client() as client, rasterio.Env(GDAL_CACHEMAX=16, GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'):
        for name in LAYERS:
            asset = item['assets'].get(name)
            if not asset:
                continue
            url = asset['href']
            def remote_open(path, mode='rb', url=url):
                if path != url:
                    raise FileNotFoundError(path)
                return GDALRangeReader(url, client, budget)
            with rasterio.open(url, opener=opener or remote_open, driver='GTiff', sharing=False) as src:
                if (src.count != 1 or src.dtypes[0] != 'uint8' or src.nodata != 255 or not src.crs
                        or any(abs(r-20) > .01 for r in src.res)
                        or any(block[0]*block[1] > 1_048_576 for block in src.block_shapes)):
                    raise GFMUnavailable('Nieobsługiwany kontrakt rastra GFM.')
                native = transform_bounds('EPSG:4326', src.crs, *box, densify_pts=21)
                window = rasterio.windows.from_bounds(*native, transform=src.transform)
                if window.width*window.height > MAX_PIXELS:
                    raise GFMUnavailable('Obszar przekracza 4 mln pikseli źródłowych; przybliż mapę.')
                details[name] = {'crs': src.crs.to_wkt(), 'resolution': list(src.res), 'nodata': src.nodata}
                if name in REQUIRED:
                    if grid is None:
                        grid, inside = source_grid(src, box, window)
                    # Same resolution and alignment as the native flood raster, including all its pixels.
                    # Other masks may use a different grid; align them with nearest neighbour.
                    with WarpedVRT(src, **grid, resampling=Resampling.nearest,
                                   nodata=255, warp_mem_limit=16) as vrt:
                        source_arrays[name] = vrt.read(1)
                with WarpedVRT(src, crs='EPSG:3857', transform=transform, width=width, height=height,
                               resampling=Resampling.nearest, nodata=255, warp_mem_limit=16) as vrt:
                    arrays[name] = vrt.read(1)
    classes = classify(*(arrays[name] for name in REQUIRED))
    counts = class_counts(classes)
    source_counts = class_counts(classify(*(source_arrays[name] for name in REQUIRED))[inside])
    quality = {}
    for name in LAYERS[3:]:
        if name in arrays:
            values, frequencies = np.unique(arrays[name], return_counts=True)
            quality[name] = {str(int(k)): int(v) for k, v in zip(values, frequencies)}
    rgba = COLORS[classes]
    result = {'image': base64.b64encode(png(rgba)).decode(), 'bounds': [[box[1], box[0]], [box[3], box[2]]],
              'counts': counts, 'source_counts': source_counts,
              'quality': quality, 'rasters': details, 'transfer': budget,
              'status': 'flood' if source_counts['flood'] else 'no_detection' if source_counts['assessed_clear'] else
                        'excluded' if source_counts['excluded'] else
                        'reference_water' if source_counts['reference_water'] else 'no_coverage'}
    budget.pop('deadline')
    return result


class GFMService:
    def __init__(self, client, clock, enabled=True, demo=False):
        self.client, self.clock, self.enabled, self.demo = client, clock, enabled, demo
        self.cache, self.products = OrderedDict(), OrderedDict()
        self.lock = asyncio.Lock()
        self.retry_at = clock()
        self.failures = 0

    def put(self, cache, key, value, limit):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    async def _json(self, url, params):
        if self.clock() < self.retry_at:
            raise GFMUnavailable('Źródło w okresie backoff; spróbuj później.')
        async with self.client.stream('GET', url, params=params, timeout=12, follow_redirects=False) as r:
            if r.status_code != 200:
                self.retry_at = self.clock()+timedelta(seconds=retry_seconds(r.headers.get('Retry-After'), self.clock()))
                raise GFMUnavailable(f'STAC HTTP {r.status_code}; spróbuj później.')
            body = bytearray()
            async for part in r.aiter_bytes():
                body.extend(part)
                if len(body) > 3*1024*1024:
                    raise GFMUnavailable('Przekroczono 3 MiB odpowiedzi STAC.')
            try:
                return json.loads(body)
            except (ValueError, UnicodeError) as exc:
                raise GFMUnavailable('Nieprawidłowy JSON STAC.') from exc

    async def _cached(self, key, work, ttl):
        # A single provider job also bounds queueing; shield keeps worker ownership after caller cancellation.
        async with asyncio.timeout(55):
            async with self.lock:
                cached = self.cache.get(key)
                if cached and cached[0] > self.clock():
                    return cached[1]
                if self.clock() < self.retry_at:
                    raise GFMUnavailable('Źródło w okresie backoff; spróbuj później.')
                task = asyncio.create_task(work())
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                except Exception:
                    self.failures = min(6, self.failures+1)
                    self.retry_at = max(self.retry_at, self.clock()+timedelta(seconds=10*2**self.failures))
                    raise
                self.failures = 0
                self.put(self.cache, key, (self.clock()+timedelta(seconds=ttl), result), 12)
                return result

    async def search(self, box, start, end):
        box = area(box)
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if not 0 <= (last-first).days <= 14:
            raise ValueError('Zakres dat: maksymalnie 15 dni kalendarzowych.')
        if self.demo or not self.enabled:
            return {'status': 'demo_no_data' if self.demo else 'disabled', 'items': [], 'enabled': False,
                    'message': 'Demo offline: brak danych GFM.' if self.demo else 'GFM wyłączone w konfiguracji.'}
        async def work():
            async with asyncio.timeout(15):
                data = await self._json(STAC+'/search', {'collections': 'GFM', 'bbox': ','.join(map(str, box)),
                'datetime': f'{start}T00:00:00Z/{end}T23:59:59Z', 'limit': 24})
            if data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
                raise GFMUnavailable('Nieprawidłowy kontrakt STAC.')
            items, rejected = [], 0
            for feature in data['features'][:24]:
                if (not isinstance(feature, dict) or not isinstance(feature.get('assets'), dict)
                        or not isinstance(feature.get('properties'), dict)
                        or not isinstance(feature.get('id'), str)):
                    rejected += 1
                    continue
                assets, p = feature['assets'], feature['properties']
                assets = {name: value for name, value in assets.items() if isinstance(value, dict)}
                if feature.get('collection') != 'GFM' or not re.fullmatch(r'[A-Za-z0-9_-]{1,180}', feature['id']):
                    continue
                filtered = {name: assets[name] for name in LAYERS if safe_asset(assets.get(name, {}).get('href'))}
                identifier = feature['id']
                try:
                    observed = instant(p['datetime'])
                except (ValueError, TypeError, AttributeError, KeyError):
                    rejected += 1
                    continue
                item = {'id': identifier, 'observed_at': observed, 'processed_at': p.get('processing:datetime'),
                        'catalog_created_at': p.get('created'), 'version': p.get('processing:version'),
                        'lineage': p.get('processing:lineage'), 'facility': p.get('processing:facility'),
                        'derived_from': [link['href'] for link in feature.get('links', [])
                                         if isinstance(link, dict) and link.get('rel') == 'derived_from'
                                         and isinstance(link.get('href'), str)],
                        'fetched_at': self.clock().isoformat(), 'bbox': feature.get('bbox'),
                        'source_url': STAC+'/collections/GFM/items/'+identifier,
                        'attribution': f'Contains modified Copernicus Emergency Management Service information [{observed[:4]}]',
                        'stale': self.clock()-datetime.fromisoformat(observed) > timedelta(hours=24),
                        'available_quality': [name for name in LAYERS[3:] if name in filtered],
                        'missing_assets': [name for name in REQUIRED if name not in filtered],
                        'renderable': all(name in filtered for name in REQUIRED)}
                self.put(self.products, identifier, (self.clock()+timedelta(hours=1), {**item, 'assets': filtered}), 288)
                items.append(item)
            if rejected and not items:
                raise GFMUnavailable('STAC zwrócił produkty bez poprawnego kontraktu lub czasu obserwacji.')
            return {'status': 'ready' if items else 'no_products', 'rejected': rejected, 'enabled': True, 'items': items,
                    'truncated': len(data['features']) > 24 or any(
                        isinstance(link, dict) and link.get('rel') == 'next' for link in data.get('links', [])),
                    'fetched_at': self.clock().isoformat(), 'bbox': box}
        return await self._cached(('search', box, start, end), work, 600)

    async def render(self, identifier, box):
        box = area(box)
        if self.demo or not self.enabled:
            raise GFMUnavailable('Brak danych GFM w demo / źródło wyłączone.')
        product = self.products.get(identifier)
        if not product or product[0] <= self.clock():
            raise KeyError(identifier)
        if not product[1].get('renderable', True):
            raise GFMUnavailable('Produkt nie udostępnia wymaganych masek: '+', '.join(product[1]['missing_assets']))
        async def work():
            budget = {}
            try:
                result = await asyncio.to_thread(render_product, product[1], box, budget=budget)
            except Exception as exc:
                if budget.get('retry'):
                    self.retry_at = self.clock()+timedelta(seconds=budget['retry'])
                raise GFMUnavailable('Odczyt GFM nie powiódł się lub przekroczył limity. Spróbuj później / zmniejsz obszar.') from exc
            if result['transfer'].get('retry'):
                self.retry_at = self.clock()+timedelta(seconds=result['transfer']['retry'])
            return {**result, 'product': {k: v for k, v in product[1].items() if k != 'assets'},
                    'rendered_at': self.clock().isoformat()}
        return await self._cached(('render', identifier, box), work, 1800)
