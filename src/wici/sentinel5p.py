"""Bounded, on-demand Sentinel-5P regional columns; never surface concentrations.

CDSE S5P has ORBIT mosaicking and server-side minQa, not S2 TILE/SCL.
Each image is one explicitly selected product, checked against Process metadata.
"""
import asyncio
import base64
import copy
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

from wici.gfm import png, retry_seconds

TOKEN = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
CATALOG = 'https://sh.dataspace.copernicus.eu/catalog/v1/search'
PROCESS = 'https://sh.dataspace.copernicus.eu/process/v1'
COLLECTION = 'sentinel-5p-l2'
MAX_BYTES = 8 * 1024 * 1024
MIN_DAY = '2018-04-30'
BBOX = [12, 48, 26, 56]
WARNING = ('Obserwacja satelitarna atmosfery w skali regionalnej. Nie opisuje jakości powietrza '
           'przy konkretnej ulicy i nie dowodzi emisji z pojedynczego zakładu')
SETUP = ('Sentinel-5P wymaga sources.sentinel5p.enabled=true oraz backendowego klienta OAuth CDSE '
         '(client_id, client_secret). Można użyć istniejącego klienta sources.sentinel2, '
         'pozostawiając oba pola Sentinel-5P puste. Konfiguracja w config.local.toml.')
MASK_LEGEND = [
    {'label': 'Brak pokrycia (przybliżony footprint)', 'color': '#677586'},
    {'label': 'Odrzucone przez filtr jakości', 'color': '#a65cdb'},
    {'label': 'NoData w obszarze pokrycia', 'color': '#edbd4c'},
]
PARAMETERS = {
    'no2': {'id': 'no2', 'label': 'NO₂ — kolumna troposferyczna', 'band': 'NO2', 'product_type': 'NO2',
            'unit': 'mol/m²', 'input_unit': 'MOL_M2', 'min_qa': 76,
            'description': 'Troposferyczna kolumna NO₂. Nominalny piksel około 3,5 × 5,5 km; '
                           'wymiary zależą od daty produktu i geometrii pomiaru.',
            'quality_filter': 'qa_value ≥ 0,76 (CDSE minQa=76; konserwatywnie >0,75); jakość produktu uwzględnia chmury. '
                              'Bez dodatkowego filtra CLOUD i bez interpolacji luk.',
            'legend': {'min': -0.0001, 'max': 0.0003, 'stops': [
                {'value': -0.0001, 'color': '#3768b0'}, {'value': 0, 'color': '#d6e8ef'},
                {'value': 0.0001, 'color': '#efca55'}, {'value': 0.0003, 'color': '#aa2959'}]}},
    'so2': {'id': 'so2', 'label': 'SO₂ — kolumna całkowita', 'band': 'SO2', 'product_type': 'SO2',
            'unit': 'mol/m²', 'input_unit': 'MOL_M2', 'min_qa': 51,
            'description': 'Całkowita kolumna SO₂ z pasma CDSE SO2. Wariant wysokościowy tego pasma '
                           'nie jest udokumentowany przez kanał CDSE; nie zakładamy warstwy 1, 3, 7 ani 15 km. '
                           'Główny produkt L2 używa profilu a priori TM5; kanał nie potwierdza mapowania pola.',
            'quality_filter': 'qa_value ≥ 0,51 (CDSE minQa=51; konserwatywnie >0,50); jakość produktu uwzględnia chmury. '
                              'Bez dodatkowego filtra CLOUD i bez interpolacji luk.',
            'legend': {'min': -0.001, 'max': 0.005, 'stops': [
                {'value': -0.001, 'color': '#3768b0'}, {'value': 0, 'color': '#d6e8ef'},
                {'value': 0.001, 'color': '#efca55'}, {'value': 0.005, 'color': '#aa2959'}]}},
    'aer_ai': {'id': 'aer_ai', 'label': 'Aerozole — UVAI 354/388 nm', 'band': 'AER_AI_354_388',
               'product_type': 'AER_AI', 'unit': 'indeks bezwymiarowy', 'input_unit': 'INDEX', 'min_qa': 81,
               'description': 'Indeks aerozolowy UV (354/388 nm), nie stężenie PM10 ani PM2,5. '
                              'Chmury i geometria wpływają na sygnał; ujemne wartości są zachowane. '
                              'Advisory 23.01.2026: procesor 2.09.01 ma przesunięcie około +0,2 UVAI 354/388, '
                              'którego QA nie usuwa; WICI nie koryguje go samodzielnie.',
               'quality_filter': 'qa_value ≥ 0,81 (CDSE minQa=81; konserwatywnie >0,80). Bez maskowania wszystkich chmur; '
                                 'UVAI może obserwować aerozole nad chmurami. Bez interpolacji luk.',
               'legend': {'min': -2, 'max': 5, 'stops': [
                   {'value': -2, 'color': '#3768b0'}, {'value': 0, 'color': '#d6e8ef'},
                   {'value': 2, 'color': '#efca55'}, {'value': 5, 'color': '#aa2959'}]}},
}
PRODUCT = re.compile(r'S5P_(NRTI|OFFL|RPRO)_L2__(NO2___|SO2___|AER_AI)_'
                     r'(\d{8}T\d{6})_(\d{8}T\d{6})_(\d{5})_(\d{2})_(\d{6})_(\d{8}T\d{6})(?:\.nc)?')


class UnsupportedProduct(ValueError):
    """An older retrieval requires quality inputs unavailable through this channel."""


class Sentinel5PError(Exception):
    def __init__(self, message, code=503, retry=None, status='provider_error'):
        super().__init__(message)
        self.code, self.retry, self.status = code, retry, status


def grid():
    xs, ys = transform('EPSG:4326', 'EPSG:3857', [BBOX[0], BBOX[2]], [BBOX[1], BBOX[3]])
    return {'bbox': [xs[0], ys[0], xs[1], ys[1]], 'catalog_bbox': BBOX.copy(),
            'bounds': [[BBOX[1], BBOX[0]], [BBOX[3], BBOX[2]]], 'width': 200, 'height': 190,
            'crs': 'EPSG:3857', 'resampling': 'NEAREST', 'approximate_grid_km': 5}


def selection(parameter, day):
    if parameter not in PARAMETERS:
        raise ValueError('Parametr Sentinel-5P: no2, so2 albo aer_ai.')
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('Wybierz dzień w formacie RRRR-MM-DD (UTC).')
    chosen = date.fromisoformat(day)
    if not date.fromisoformat(MIN_DAY) <= chosen <= datetime.now(UTC).date():
        raise ValueError('Wybierz jeden dzień UTC od 30.04.2018 do dziś.')
    return PARAMETERS[parameter], chosen


def utc(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Missing timezone')
    return result.astimezone(UTC)


def catalog_item(feature, parameter, day):
    identifier, props = feature['id'], feature['properties']
    matched = PRODUCT.fullmatch(identifier)
    if not matched:
        raise ValueError('Product identifier')
    mode, product, start, end, orbit, _, version, generated = matched.groups()
    parse = lambda value: datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=UTC)
    start, end, generated = map(parse, (start, end, generated))
    if (product.rstrip('_') != parameter['product_type'] or props['s5p:type'] != parameter['product_type']
            or props['s5p:timeliness'] != mode or abs((utc(props['datetime'])-start).total_seconds()) > 2
            or start.date().isoformat() != day or not start < end <= start+timedelta(hours=3)):
        raise ValueError('Product metadata mismatch')
    if parameter['id'] == 'so2' and int(version) < 20000:
        raise UnsupportedProduct('SO₂ V1 wymaga dodatkowych filtrów niedostępnych w tym kanale.')
    shape = feature['geometry']
    if shape.get('type') not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Footprint')
    # Validate geometry before adding a product to the selection allowlist.
    footprint(shape, grid())
    return {'id': identifier, 'product_ids': [identifier], 'observed_at': start.isoformat(),
            'observation_start': start.isoformat(), 'observation_end': end.isoformat(), 'mode': mode,
            'orbit': int(orbit), 'processor_version': version, 'product_generated_at': generated.isoformat(),
            'product_generation_delay_hours': round((generated-end).total_seconds()/3600, 2),
            'time_basis': 'UTC; przedział produktu, nie dokładny czas każdego piksela',
            'attribution': f'Contains modified Copernicus Sentinel data [{start.year}]',
            'geometry': shape}


def footprint(shape, raster_grid):
    projected = transform_geom('EPSG:4326', 'EPSG:3857', shape)
    return geometry_mask([projected], out_shape=(raster_grid['height'], raster_grid['width']),
                         transform=from_bounds(*raster_grid['bbox'], raster_grid['width'], raster_grid['height']),
                         invert=True)


def evalscript(parameter, identifier):
    """Filter when scene metadata permits; always require a single selected product on decode."""
    return r'''//VERSION=3
const target=TARGET;
function setup(){return {input:[{bands:[BAND,'dataMask'],units:[UNIT,'DN']}],
 output:{id:'raster',bands:3,sampleType:'FLOAT32'},mosaicking:'ORBIT'};}
function match(t){return (t.sentinel5pProductId||'').replace(/\.nc$/,'')===target.replace(/\.nc$/,'');}
function preProcessScenes(c){
 if(c.scenes.tiles && c.scenes.tiles.length)c.scenes.tiles=c.scenes.tiles.filter(match);
 if(c.scenes.orbits && c.scenes.orbits.every(o=>Array.isArray(o.tiles)&&o.tiles.length))
   c.scenes.orbits=c.scenes.orbits.map(o=>{o.tiles=o.tiles.filter(match);return o;}).filter(o=>o.tiles.length);
 return c;
}
function evaluatePixel(samples){
 if(!samples.length)return [0,0,0];
 let p=samples[0],v=p[BAND];
 return [Number.isFinite(v)&&Math.abs(v)<1e30?v:0,p.dataMask,
         Number.isFinite(v)&&Math.abs(v)<1e30?1:0];
}
function updateOutputMetadata(s,i,o){o.userData={tiles:s.tiles||[],orbits:s.orbits||[]};}
'''.replace('TARGET', json.dumps(identifier)).replace('BAND', json.dumps(parameter['band'])).replace(
        'UNIT', json.dumps(parameter['input_unit']))


def process_payload(parameter, item, min_qa):
    raster_grid = grid()
    # Process includes both endpoints; exclude the next granule starting at this end.
    # Keep the original observation interval in provenance, changing only the query.
    query_end = (utc(item['observation_end'])-timedelta(milliseconds=1)).isoformat(timespec='milliseconds')
    return {'input': {'bounds': {'bbox': raster_grid['bbox'], 'properties': {
        'crs': 'http://www.opengis.net/def/crs/EPSG/0/3857'}}, 'data': [{
        'type': COLLECTION, 'dataFilter': {'timeRange': {
            'from': item['observation_start'], 'to': query_end},
            'timeliness': item['mode'], 'mosaickingOrder': 'mostRecent'},
        'processing': {'upsampling': 'NEAREST', 'minQa': min_qa}}]},
        'output': {'width': raster_grid['width'], 'height': raster_grid['height'], 'responses': [
            {'identifier': 'raster', 'format': {'type': 'image/tiff'}},
            {'identifier': 'userdata', 'format': {'type': 'application/json'}}]},
        'evalscript': evalscript(parameter, item['id'])}


def decode(body, item, raster_grid):
    try:
        files = {}
        with tarfile.open(fileobj=io.BytesIO(body)) as archive:
            for member in archive:
                if (not member.isfile() or member.name not in ('raster.tif', 'userdata.json')
                        or member.name in files or member.size > MAX_BYTES
                        or sum(map(len, files.values()))+member.size > MAX_BYTES):
                    raise ValueError('Archive')
                files[member.name] = archive.extractfile(member).read()
        meta = json.loads(files['userdata.json'])
        tiles = meta.get('tiles') or [t for orbit in meta.get('orbits', []) for t in orbit.get('tiles', [])]
        if len(tiles) != 1 or tiles[0]['sentinel5pProductId'].removesuffix('.nc') != item['id'].removesuffix('.nc'):
            raise ValueError('Different product or mosaic')
        if abs((utc(tiles[0]['date'])-utc(item['observed_at'])).total_seconds()) > 2:
            raise ValueError('Different observation time')
        with MemoryFile(files['raster.tif']) as memory, memory.open() as raster:
            if (raster.count != 3 or raster.dtypes != ('float32',)*3 or raster.crs.to_epsg() != 3857
                    or raster.width != raster_grid['width'] or raster.height != raster_grid['height']
                    or not np.allclose(tuple(raster.bounds), raster_grid['bbox'], atol=.01, rtol=0)):
                raise ValueError('Grid')
            data = raster.read()
        if not np.isin(data[1:], [0, 1]).all():
            raise ValueError('Mask')
        return data
    except (ValueError, KeyError, TypeError, tarfile.TarError, OSError, RasterioError,
            AttributeError, OverflowError) as exc:
        raise Sentinel5PError('Odrzucono Sentinel-5P: niezgodny produkt, czas, raster lub metadane CDSE.') from exc


def images(raw, filtered, item, parameter, day, raster_grid=None):
    raster_grid = raster_grid or grid()
    raw_valid = (raw[1] == 1) & (raw[2] == 1) & np.isfinite(raw[0])
    valid = (filtered[1] == 1) & (filtered[2] == 1) & np.isfinite(filtered[0])
    if (valid & ~raw_valid).any() or not np.allclose(raw[0][valid], filtered[0][valid], equal_nan=False):
        raise Sentinel5PError('CDSE: niespójne maski jakości wybranego produktu.')
    # Catalog footprints are approximate. Actual valid samples override boundary rounding.
    covered = footprint(item['geometry'], raster_grid) | raw_valid
    rejected = raw_valid & (filtered[1] == 0)
    nodata = covered & ~valid & ~rejected
    absent = ~covered
    percentages = lambda mask: round(float(mask.mean()*100), 2)
    quality = {'valid_percent': percentages(valid), 'no_coverage_percent': percentages(absent),
               'rejected_percent': percentages(rejected), 'nodata_percent': percentages(nodata),
               'zero_percent': percentages(valid & (filtered[0] == 0)),
               'negative_percent': percentages(valid & (filtered[0] < 0)),
               'valid_of_covered_percent': round(float(valid.sum()/max(1, covered.sum())*100), 2),
               'coverage_basis': 'Przybliżony footprint katalogu; luki wewnątrz niego to NoData. '
                                 'Udziały dotyczą pikseli siatki mapy, nie powierzchni ani natywnych pikseli.',
               'filter': parameter['quality_filter'], 'min_qa': parameter['min_qa'],
               'mask_legend': MASK_LEGEND}
    values = filtered[0][valid]
    quality['minimum'] = float(values.min()) if values.size else None
    quality['maximum'] = float(values.max()) if values.size else None
    rgba = np.zeros((*valid.shape, 4), dtype='uint8')
    stops = parameter['legend']['stops']
    colors = [[int(s['color'][i:i+2], 16) for i in (1, 3, 5)] for s in stops]
    for channel in range(3):
        rgba[..., channel][valid] = np.interp(values, [s['value'] for s in stops],
                                             [c[channel] for c in colors]).astype('uint8')
    rgba[..., 3][valid] = 220
    mask = np.zeros_like(rgba)
    for condition, color in [(absent, [103, 117, 134, 100]), (rejected, [166, 92, 219, 150]),
                              (nodata, [237, 189, 76, 150])]:
        mask[condition] = color
    public_item = {k: v for k, v in item.items() if k != 'geometry'}
    return {'status': 'ready' if valid.any() else 'no_coverage' if not covered.any()
            else 'quality_rejected' if rejected.any() else 'nodata',
            'day': day, 'parameter': parameter, 'item': public_item, 'bounds': raster_grid['bounds'],
            'grid': raster_grid, 'quality': quality,
            'image': base64.b64encode(png(rgba)).decode(), 'mask': base64.b64encode(png(mask)).decode(),
            'mosaic': False, 'pixel_selection': 'Jeden wybrany produkt; najbliższy piksel (NEAREST). '
            'Brak interpolacji, uśredniania dobowego i zastępowania dnia.',
            'warning': WARNING, 'fetched_at': datetime.now(UTC).isoformat()}


class Sentinel5PService:
    def __init__(self, client, config, demo=False):
        self.client, self.demo = client, demo
        settings = config.sources.get('sentinel5p', {})
        credentials = settings if settings.get('client_id') or settings.get('client_secret') else config.sources.get(
            'sentinel2', {})
        self.credentials = {k: (credentials[k].get_secret_value() if hasattr(credentials.get(k), 'get_secret_value')
                               else str(credentials.get(k, ''))).strip() for k in ('client_id', 'client_secret')}
        self.enabled = bool(settings.get('enabled', False)) and all(self.credentials.values())
        self.cache, self.items, self.jobs = OrderedDict(), OrderedDict(), {}
        self.token, self.expires, self.backoff = '', 0, 0
        self.auth_lock, self.semaphore = asyncio.Lock(), asyncio.Semaphore(2)
        self.closed = False

    def status(self):
        return {'status': 'demo' if self.demo else 'ready' if self.enabled else 'unconfigured',
                'message': 'DEMO — wyłącznie syntetyczne dane, nie obserwacje satelitarne.' if self.demo
                else 'CDSE skonfigurowane. Dostępność danych jest sprawdzana na żądanie.' if self.enabled else SETUP,
                'demo': self.demo, 'parameters': list(PARAMETERS.values()), 'min_day': MIN_DAY,
                'max_day': datetime.now(UTC).date().isoformat(), 'bounds': grid()['bounds'],
                'warning': WARNING, 'cache_seconds': 600,
                'latency_note': 'Około 3 h to cel publikacji produktu NRT, nie gwarancja tego kanału ani WICI. '
                                'Cache aplikacji: 10 min; brak automatycznego odświeżania.'}

    async def close(self):
        self.closed = True
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.credentials.clear()
        self.token = ''
        self.cache.clear()
        self.items.clear()

    async def request(self, url, **kwargs):
        if self.closed:
            raise Sentinel5PError('Sentinel-5P zakończył pracę.')
        if time.monotonic() < self.backoff:
            raise Sentinel5PError('CDSE: przerwa po limicie; spróbuj później.', 429,
                                  max(1, math.ceil(self.backoff-time.monotonic())), 'rate_limited')
        try:
            async with self.client.stream('POST', url, timeout=25, follow_redirects=False, **kwargs) as response:
                if response.status_code != 200:
                    code = response.status_code
                    if code in (400, 401) and url == TOKEN or code == 401:
                        self.expires = 0
                        raise Sentinel5PError('CDSE: niepoprawne dane OAuth lub wygasły token.', 401,
                                              status='auth_error')
                    retry = retry_seconds(response.headers.get('Retry-After'), datetime.now(UTC))
                    if code in (429, 503):
                        raw = response.headers.get('Retry-After', '')
                        # Sentinel Hub documents milliseconds; OAuth uses standard HTTP seconds.
                        if raw.isdigit() and url != TOKEN:
                            retry = max(1, min(3600, math.ceil(int(raw)/1000)))
                        self.backoff = time.monotonic()+retry
                    if code == 403:
                        raise Sentinel5PError('CDSE: brak uprawnień lub limit konta.', 403, status='account_limit')
                    if code == 429:
                        raise Sentinel5PError('CDSE: limit żądań lub jednostek przetwarzania.', 429,
                                              retry, 'rate_limited')
                    raise Sentinel5PError('CDSE: awaria dostawcy lub odrzucony kontrakt przetwarzania.',
                                          retry=retry if code == 503 else None)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise Sentinel5PError('CDSE: odpowiedź przekracza 8 MiB.')
                return bytes(body)
        except httpx.HTTPError as exc:
            raise Sentinel5PError('CDSE: timeout lub błąd połączenia.') from exc

    async def authorized(self, url, payload):
        async with self.auth_lock:
            if time.monotonic() >= self.expires:
                raw = await self.request(TOKEN, data={'grant_type': 'client_credentials', **self.credentials})
                try:
                    token = json.loads(raw)
                    if not isinstance(token['access_token'], str) or not token['access_token']:
                        raise ValueError('Token')
                    self.token = token['access_token']
                    self.expires = time.monotonic()+max(1, min(3600, int(token['expires_in']))-30)
                except (ValueError, KeyError, TypeError, OverflowError) as exc:
                    raise Sentinel5PError('CDSE: niepoprawna odpowiedź OAuth.') from exc
        return await self.request(url, headers={'Authorization': 'Bearer '+self.token,
                                  'Accept': 'application/tar' if url == PROCESS else 'application/geo+json'},
                                  json=payload)

    async def cached(self, key, work):
        if self.closed:
            raise Sentinel5PError('Sentinel-5P zakończył pracę.')
        if key in self.cache:
            expires, result = self.cache[key]
            if expires > time.monotonic():
                self.cache.move_to_end(key)
                return copy.deepcopy(result)
            del self.cache[key]
        if key not in self.jobs:
            if len(self.jobs) >= 8:
                raise Sentinel5PError('Kolejka Sentinel-5P pełna; spróbuj później.', 429, 5, 'rate_limited')
            async def run():
                try:
                    async with asyncio.timeout(75):
                        async with self.semaphore:
                            result = await work()
                    self.cache[key] = (time.monotonic()+600, result)
                    while len(self.cache) > 12:
                        self.cache.popitem(last=False)
                    return result
                except TimeoutError as exc:
                    raise Sentinel5PError('CDSE: przekroczono 75 s na operację.') from exc
                finally:
                    self.jobs.pop(key, None)
            self.jobs[key] = asyncio.create_task(run())
            # A disconnected HTTP caller must not cancel a job shared with another tab.
            self.jobs[key].add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return copy.deepcopy(await asyncio.shield(self.jobs[key]))

    async def search(self, parameter, day):
        definition, _ = selection(parameter, day)
        if not self.enabled and not self.demo:
            return {**self.status(), 'day': day, 'parameter': definition, 'items': [], 'fetched_at': None}
        async def work():
            if self.demo:
                shape = {'type': 'Polygon', 'coordinates': [[[12, 48], [24, 48], [24, 56], [12, 56], [12, 48]]]}
                items = [{'id': f'DEMO-S5P-{parameter}-{day}-{i}', 'product_ids': [],
                          'observed_at': f'{day}T{hour}:00:00+00:00',
                          'observation_start': f'{day}T{hour}:00:00+00:00',
                          'observation_end': f'{day}T{hour}:05:00+00:00', 'mode': 'SYNTHETIC',
                          'attribution': 'WICI DEMO — dane syntetyczne, nie obserwacje Sentinel-5P.',
                          'geometry': shape} for i, hour in enumerate(('10', '12'))]
                truncated, unsupported = False, 0
            else:
                body = await self.authorized(CATALOG, {'collections': [COLLECTION], 'bbox': BBOX,
                    'datetime': day+'T00:00:00Z/'+day+'T23:59:59Z', 'limit': 50,
                    'filter-lang': 'cql2-text', 'filter': f"s5p:type = '{definition['product_type']}'"})
                try:
                    result = json.loads(body)
                    features = result['features']
                    if not isinstance(features, list) or len(features) > 50:
                        raise ValueError('Features')
                    items, unsupported = [], 0
                    for feature in features:
                        try:
                            items.append(catalog_item(feature, definition, day))
                        except UnsupportedProduct:
                            unsupported += 1
                    if len({item['id'] for item in items}) != len(items):
                        raise ValueError('Duplicate product')
                    truncated = bool(result.get('context', {}).get('next') or any(
                        link.get('rel') == 'next' for link in result.get('links', [])))
                except (ValueError, KeyError, TypeError, AttributeError, RasterioError) as exc:
                    raise Sentinel5PError('CDSE: niepoprawny katalog lub metadane produktu Sentinel-5P.') from exc
            items.sort(key=lambda item: (item['observed_at'], item['id']), reverse=True)
            return {'status': 'demo' if self.demo else 'ready' if items else 'no_data', 'demo': self.demo,
                    'day': day, 'parameter': definition, 'items': items, 'truncated': truncated,
                    'unsupported_product_count': unsupported,
                    'fetched_at': datetime.now(UTC).isoformat(), 'bounds': grid()['bounds'],
                    'message': f'Pominięto {unsupported} produktów SO₂ V1: wymagają dodatkowych filtrów '
                    'jakości niedostępnych w CDSE Process. Wybierz produkt V2+ (np. RPRO).' if unsupported
                    else 'Brak produktów dla wybranego dnia UTC.' if not items else ''}
        result = await self.cached(('search', parameter, day), work)
        for item in result['items']:
            key = (parameter, day, item['id'])
            self.items[key] = (time.monotonic()+1200, item)
            self.items.move_to_end(key)
            while len(self.items) > 300:
                self.items.popitem(last=False)
        result['items'] = [{k: v for k, v in item.items() if k != 'geometry'} for item in result['items']]
        return result

    async def render(self, parameter, day, identifier):
        definition, _ = selection(parameter, day)
        saved = self.items.get((parameter, day, identifier))
        if not saved or saved[0] < time.monotonic():
            raise Sentinel5PError('Wyszukaj obserwacje ponownie i wybierz wynik.', 404, status='selection_expired')
        item = saved[1]
        async def work():
            raster_grid = grid()
            if self.demo:
                y, x = np.indices((raster_grid['height'], raster_grid['width']))
                shift = (date.fromisoformat(day).toordinal()+int(identifier[-1])*19) % 45
                signal = np.exp(-((x-65-shift)**2/800+(y-100+(x-80)*.5)**2/130))
                raw = np.ones((3, *x.shape), dtype='float32')
                raw[0] = signal*(definition['legend']['max']*.8)+definition['legend']['min']*.2
                raw[0, 80:90, 40:50] = 0
                raw[1, :, 172:] = 0
                raw[1, 30:45, 55:75] = 0
                filtered = raw.copy()
                filtered[1, 50:80, 90:120] = 0
            else:
                raw_body = await self.authorized(PROCESS, process_payload(definition, item, 0))
                raw = await asyncio.to_thread(decode, raw_body, item, raster_grid)
                filtered_body = await self.authorized(PROCESS, process_payload(definition, item, definition['min_qa']))
                filtered = await asyncio.to_thread(decode, filtered_body, item, raster_grid)
            return await asyncio.to_thread(images, raw, filtered, item, definition, day, raster_grid)
        result = await self.cached(('render', parameter, day, identifier), work)
        result['age_hours'] = round((datetime.now(UTC)-utc(item['observation_end'])).total_seconds()/3600, 2)
        result['demo'] = self.demo
        return result
