"""On-demand CDSE RGB comparison; bounded jobs, exact product selection, no remote URLs from UI."""
import asyncio
import base64
import io
import json
import math
import re
import tarfile
import time
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta

import httpx
import numpy as np
from rasterio.errors import RasterioError
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform, transform_geom

from wici.aircraft import in_poland
from wici.gfm import png, retry_seconds

TOKEN = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
CATALOG = 'https://sh.dataspace.copernicus.eu/catalog/v1/search'
PROCESS = 'https://sh.dataspace.copernicus.eu/process/v1'
SETUP = ('Brak konfiguracji Sentinel-2. Załóż bezpłatne konto na dataspace.copernicus.eu, '
         'w Sentinel Hub Dashboard → User Settings → OAuth clients utwórz klienta backendowego '
         '(bez SPA). W config.local.toml ustaw [sources.sentinel2]: enabled=true, client_id i client_secret.')
MAX_BYTES = 8 * 1024 * 1024


class SentinelError(Exception):
    def __init__(self, message, code=503, retry=None):
        super().__init__(message)
        self.code, self.retry = code, retry


def geometry(lat, lon, size=4):
    if not all(math.isfinite(v) for v in (lat, lon, size)) or not (49 <= lat <= 55 and 14 <= lon <= 24.3):
        raise ValueError('Wskaż punkt w Polsce.')
    if not in_poland(lat, lon):
        raise ValueError('Wskaż punkt wewnątrz granic Polski.')
    if size not in (2, 4, 6):
        raise ValueError('Zasięg musi wynosić 2, 4 lub 6 km.')
    x, y = transform('EPSG:4326', 'EPSG:3857', [lon], [lat])
    half = size * 500 / math.cos(math.radians(lat))
    box = [x[0]-half, y[0]-half, x[0]+half, y[0]+half]
    xs, ys = transform('EPSG:3857', 'EPSG:4326', [box[0], box[2]], [box[1], box[3]])
    return {'bbox': box, 'bounds': [[ys[0], xs[0]], [ys[1], xs[1]]],
            'catalog_bbox': [xs[0], ys[0], xs[1], ys[1]], 'width': int(size*100),
            'height': int(size*100), 'crs': 'EPSG:3857', 'size_km': size}


def footprint_coverage(shape, grid):
    """Footprint coverage at output pixel centres; actual NoData is checked after rendering."""
    if not shape:
        return None
    try:
        projected = transform_geom('EPSG:4326', grid['crs'], shape)
        covered = geometry_mask([projected], out_shape=(grid['height'], grid['width']),
                                transform=from_bounds(*grid['bbox'], grid['width'], grid['height']), invert=True)
        return 100.0 if covered.all() else min(99.99, round(float(covered.mean()*100), 2))
    except (ValueError, TypeError, KeyError):
        return None


def evalscript(identifier):
    target = json.dumps(identifier.removesuffix('.SAFE'))
    return r'''//VERSION=3
function setup(){return {input:[{bands:['B04','B03','B02','dataMask','SCL']}],
output:{id:'raster',bands:5,sampleType:'UINT8'},mosaicking:'TILE'};}
const target=TARGET;
function match(t){return (t.sentinel2ProductId||'').replace(/\.SAFE$/,'')===target ||
 (t.dataPath||'').split('/').some(p=>p===target+'.SAFE'||p===target);}
function preProcessScenes(c){c.scenes.tiles=c.scenes.tiles.filter(match);return c;}
function evaluatePixel(s){if(!s.length)return [0,0,0,0,0];let p=s[0];
return [255*Math.min(1,2.5*p.B04),255*Math.min(1,2.5*p.B03),
255*Math.min(1,2.5*p.B02),255*p.dataMask,p.SCL];}
function updateOutputMetadata(s,i,o){o.userData={tiles:s.tiles};}
'''.replace('TARGET', target)


def decode(body, item, grid):
    try:
        with tarfile.open(fileobj=io.BytesIO(body)) as archive:
            files = {}
            for member in archive:
                if (not member.isfile() or member.size > MAX_BYTES or len(files) >= 4
                        or sum(len(v) for v in files.values())+member.size > MAX_BYTES):
                    raise ValueError('archive')
                files[member.name] = archive.extractfile(member).read()
        meta = json.loads(files['userdata.json'])
        tiles = meta['tiles']
        target = item['id'].removesuffix('.SAFE')
        if len(tiles) != 1 or not (str(tiles[0].get('sentinel2ProductId', '')).removesuffix('.SAFE') == target or
                target+'.SAFE' in tiles[0].get('dataPath', '').split('/')):
            raise ValueError('product')
        observed = datetime.fromisoformat(item['observed_at'])
        actual = datetime.fromisoformat(tiles[0]['date'])
        if abs((actual-observed).total_seconds()) > 2:
            raise ValueError('date')
        with MemoryFile(files['raster.tif']) as memory, memory.open() as raster:
            if (raster.dtypes != ('uint8',)*5 or raster.count != 5 or raster.width != grid['width'] or raster.height != grid['height']
                    or raster.crs.to_epsg() != 3857
                    or not np.allclose(tuple(raster.bounds), grid['bbox'], atol=.01, rtol=0)):
                raise ValueError('grid')
            data = raster.read()
        return images(data, item, grid)
    except (ValueError, KeyError, TypeError, tarfile.TarError, OSError, RasterioError, AttributeError, OverflowError) as exc:
        raise SentinelError('Odrzucono render: niezgodna obserwacja, siatka lub metadane CDSE.') from exc


def images(data, item, grid):
    valid = data[3] > 0
    rgba = np.moveaxis(data[:4], 0, -1).copy()
    # Opaque checkerboard makes missing data visible instead of showing the other date beneath it.
    yy, xx = np.indices(valid.shape)
    grey = np.where((xx//8+yy//8) % 2, 105, 165).astype('uint8')
    rgba[~valid] = np.stack([grey, grey, grey, np.full_like(grey, 255)], -1)[~valid]
    mask = np.zeros_like(rgba)
    missing = int((~valid).sum())
    counts = {'coverage': 100.0 if not missing else min(99.99, round(float(valid.mean()*100), 2)),
              'missing_percent': missing / valid.size * 100, 'missing_pixels': missing,
              'total_pixels': int(valid.size)}
    for name, classes, color in [('cloud', [8, 9, 10], [255, 200, 0, 145]),
                                  ('shadow', [3], [170, 60, 220, 160]),
                                  ('snow', [11], [0, 220, 255, 160])]:
        found = valid & np.isin(data[4], classes)
        mask[found] = color
        counts[name] = round(float(found.sum()/max(1, valid.sum())*100), 2)
    return {'item': item, 'grid': grid, 'bounds': grid['bounds'], 'quality': counts,
            'status': 'no_coverage' if not valid.any() else 'partial_coverage' if missing else 'ready',
            'image': base64.b64encode(png(rgba)).decode(),
            'mask': base64.b64encode(png(mask)).decode()}


class SentinelService:
    def __init__(self, client, config, demo=False):
        self.client, self.demo = client, demo
        settings = config.sources.get('sentinel2', {})
        self.credentials = {k: (settings[k].get_secret_value() if hasattr(settings.get(k), 'get_secret_value')
                               else str(settings.get(k, ''))) for k in ('client_id', 'client_secret')}
        self.enabled = bool(settings.get('enabled', False)) and all(self.credentials.values())
        self.cache, self.items, self.jobs = OrderedDict(), OrderedDict(), {}
        self.token, self.expires, self.backoff = '', 0, 0
        self.auth_lock, self.semaphore = asyncio.Lock(), asyncio.Semaphore(2)

    def status(self):
        return {'status': 'demo' if self.demo else 'ready' if self.enabled else 'unconfigured',
                'message': 'DEMO — syntetyczne dane demonstracyjne, nie zdjęcia satelitarne.' if self.demo
                else 'CDSE gotowe. Wybierz punkt i wyszukaj obserwacje.' if self.enabled else SETUP}

    async def close(self):
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.credentials.clear()
        self.token = ''

    async def request(self, url, **kwargs):
        if time.monotonic() < self.backoff:
            raise SentinelError('CDSE: trwa przerwa po limicie. Spróbuj później.', 429,
                                max(1, math.ceil(self.backoff-time.monotonic())))
        try:
            async with self.client.stream('POST', url, timeout=25, follow_redirects=False, **kwargs) as r:
                if r.status_code != 200:
                    if r.status_code == 401:
                        self.expires = 0
                    retry = retry_seconds(r.headers.get('Retry-After'), datetime.now(UTC))
                    if r.status_code in (429, 503):
                        # Sentinel Hub Retry-After uses milliseconds, unlike standard HTTP seconds.
                        raw = r.headers.get('Retry-After', '')
                        if raw.isdigit() and url != TOKEN:
                            retry = max(1, min(3600, math.ceil(int(raw)/1000)))
                        self.backoff = time.monotonic()+retry
                    message = {401: 'CDSE: wygasły lub niepoprawny token; ponów ręcznie.',
                               403: 'CDSE: brak uprawnień lub wyczerpany limit konta.',
                               429: 'CDSE: limit żądań lub jednostek przetwarzania; spróbuj później.'}
                    raise SentinelError(message.get(r.status_code, 'Awaria usługi CDSE.'),
                                        r.status_code if r.status_code in (401, 403, 429) else 503,
                                        retry if r.status_code in (429, 503) else None)
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise SentinelError('CDSE: odpowiedź przekracza 8 MiB.')
                return bytes(body)
        except httpx.HTTPError as exc:
            raise SentinelError('CDSE: timeout lub błąd połączenia.') from exc

    async def authorized(self, url, payload):
        async with self.auth_lock:
            if time.monotonic() >= self.expires:
                raw = await self.request(TOKEN, data={'grant_type': 'client_credentials', **self.credentials})
                try:
                    token = json.loads(raw)
                    self.token = token['access_token']
                    self.expires = time.monotonic()+max(1, min(3600, int(token['expires_in']))-30)
                except (ValueError, KeyError, TypeError) as exc:
                    raise SentinelError('CDSE: niepoprawna odpowiedź OAuth.') from exc
        return await self.request(url, headers={'Authorization': 'Bearer '+self.token,
                                  'Accept': 'application/tar' if url == PROCESS else 'application/geo+json'},
                                  json=payload)

    async def cached(self, key, work):
        if key in self.cache:
            expires, result = self.cache[key]
            if expires > time.monotonic():
                self.cache.move_to_end(key)
                return result
            del self.cache[key]
        if key not in self.jobs:
            if len(self.jobs) >= 8:
                raise SentinelError('Kolejka Sentinel-2 pełna; spróbuj później.', 429, 5)
            async def run():
                try:
                    async with asyncio.timeout(55):
                        async with self.semaphore:
                            result = await work()
                    self.cache[key] = (time.monotonic()+600, result)
                    while len(self.cache) > 12:
                        self.cache.popitem(last=False)
                    return result
                except TimeoutError as exc:
                    raise SentinelError('CDSE: przekroczono 55 s na operację.') from exc
                finally:
                    self.jobs.pop(key, None)
            self.jobs[key] = asyncio.create_task(run())
        return await asyncio.shield(self.jobs[key])

    async def search(self, lat, lon, size, start, end, cloud, full_only=True):
        grid = geometry(lat, lon, size)
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if not (date(2015, 6, 23) <= a <= b <= datetime.now(UTC).date()) or (b-a).days > 366:
            raise ValueError('Wybierz przedział do 366 dni, od 23.06.2015 do dziś.')
        if not math.isfinite(cloud) or not 0 <= cloud <= 100:
            raise ValueError('Zachmurzenie: 0–100%.')
        if not self.enabled and not self.demo:
            return {**self.status(), 'items': []}
        key = ('search', lat, lon, size, start, end, cloud)
        async def work():
            if self.demo:
                w, south, e, north = grid['catalog_bbox']
                footprint = {'type': 'Polygon', 'coordinates': [
                    [[w, south], [e, south], [e, north], [w, north], [w, south]]]}
                features = [{'id': f'DEMO-{i}-{d}', 'geometry': footprint, 'properties': {'datetime': d+'T10:06:12Z',
                             'eo:cloud_cover': 12+i*8}} for i, d in enumerate([start, end])]
                features = [f for f in features if f['properties']['eo:cloud_cover'] <= cloud]
                result = {}
            else:
                body = await self.authorized(CATALOG, {'collections': ['sentinel-2-l2a'],
                    'bbox': grid['catalog_bbox'], 'datetime': start+'T00:00:00Z/'+end+'T23:59:59Z',
                    'limit': 50, 'filter-lang': 'cql2-text', 'filter': f'eo:cloud_cover <= {cloud}'})
                try:
                    result = json.loads(body)
                    features = result['features']
                    if not isinstance(features, list) or len(features) > 50:
                        raise ValueError('features')
                except (ValueError, KeyError, TypeError) as exc:
                    raise SentinelError('CDSE: niepoprawny katalog.') from exc
            items = []
            try:
                for f in features:
                    identifier, p = f['id'], f['properties']
                    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', identifier):
                        continue
                    observed = datetime.fromisoformat(p['datetime'])
                    if observed.tzinfo is None or not a <= observed.date() <= b:
                        continue
                    item = {'id': identifier, 'observed_at': observed.isoformat(),
                            'cloud_cover': p.get('eo:cloud_cover'),
                            'catalog_coverage_percent': footprint_coverage(f.get('geometry'), grid),
                            'attribution': ('WICI DEMO — dane syntetyczne (nie zdjęcia Sentinel-2)' if self.demo
                                            else f'Contains modified Copernicus Sentinel data [{observed.year}]')}
                    items.append(item)
            except (KeyError, TypeError, ValueError) as exc:
                raise SentinelError('CDSE: niepoprawne metadane obserwacji.') from exc
            items.sort(key=lambda i: i['observed_at'])
            return {**self.status(), 'items': items, 'grid': grid,
                    'truncated': bool(result.get('context', {}).get('next') or
                                      any(x.get('rel') == 'next' for x in result.get('links', [])))}
        result = await self.cached(key, work)
        # Filter a copy so switching coverage policy reuses Catalog metadata without mutating cache.
        all_items = result['items']
        selected = [item for item in all_items if not full_only or item['catalog_coverage_percent'] == 100]
        selected = sorted(selected, key=lambda i: (i['catalog_coverage_percent'] != 100, i['observed_at']))
        result = {**result, 'items': selected, 'full_coverage_only': full_only, 'total_items': len(all_items),
                  'excluded_partial_count': sum(i['catalog_coverage_percent'] is not None
                                                and i['catalog_coverage_percent'] < 100 for i in all_items) if full_only else 0,
                  'excluded_unknown_count': sum(i['catalog_coverage_percent'] is None for i in all_items) if full_only else 0}
        # A cached Catalog search must restore choices evicted by other tabs/areas.
        for item in result['items']:
            choice = (lat, lon, size, item['id'])
            self.items[choice] = (time.monotonic()+1200, item)
            self.items.move_to_end(choice)
            while len(self.items) > 300:
                self.items.popitem(last=False)
        return result

    async def render(self, lat, lon, size, identifier):
        grid = geometry(lat, lon, size)
        saved = self.items.get((lat, lon, size, identifier))
        if not saved or saved[0] < time.monotonic():
            raise SentinelError('Wyszukaj obserwacje ponownie i wybierz wynik.', 404)
        item = saved[1]
        async def work():
            if self.demo:
                n = grid['width']
                y, x = np.indices((n, n))
                data = np.zeros((5, n, n), dtype='uint8')
                data[0] = 45+(x//25 % 3)*15
                data[1] = 85+(y//30 % 3)*20
                data[2] = 45
                data[3] = 255
                data[4] = 4
                if identifier.startswith('DEMO-1-'):
                    data[:3, n//3:2*n//3, n//3:2*n//3] = np.array([160, 120, 70])[:, None, None]
                data[3, :n//10, :n//5] = 0
                data[4, :n//8, n//2:] = 9
                return images(data, item, grid)
            observed = datetime.fromisoformat(item['observed_at'])
            payload = {'input': {'bounds': {'bbox': grid['bbox'], 'properties': {
                'crs': 'http://www.opengis.net/def/crs/EPSG/0/3857'}}, 'data': [{
                'type': 'sentinel-2-l2a', 'dataFilter': {'timeRange': {
                    'from': (observed-timedelta(seconds=2)).isoformat(),
                    'to': (observed+timedelta(seconds=2)).isoformat()}},
                'processing': {'upsampling': 'NEAREST', 'downsampling': 'NEAREST', 'harmonizeValues': True}}]},
                'output': {'width': grid['width'], 'height': grid['height'], 'responses': [
                    {'identifier': 'raster', 'format': {'type': 'image/tiff'}},
                    {'identifier': 'userdata', 'format': {'type': 'application/json'}}]},
                'evalscript': evalscript(identifier)}
            body = await self.authorized(PROCESS, payload)
            return await asyncio.to_thread(decode, body, item, grid)
        return await self.cached(('render', lat, lon, size, identifier), work)
