"""Incremental, layer-driven national GFM monitoring; native pixels, bounded COG reads."""
import asyncio
import hashlib
import json
import math
import time
import zlib
from collections import OrderedDict
from contextlib import ExitStack
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import bounds as geometry_bounds
from rasterio.features import geometry_mask, shapes
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as transform_coordinates
from rasterio.warp import transform_bounds, transform_geom
from rasterio.windows import Window

from wici.gfm import (
    LAYERS,
    REQUIRED,
    STAC,
    GDALRangeReader,
    GFMUnavailable,
    classify,
    cog_errors,
    instant,
    safe_asset,
)

POLAND = (14, 49, 24.3, 55)
BLOCK = 512
MAX_PRODUCTS = 96
MAX_POINTS = 250_000
MAX_CACHE_BYTES = 64*1024*1024
MAX_RESPONSE_BYTES = 4*1024*1024


def view_bbox(value):
    if value is None:
        return None
    try:
        w, s, e, n = (float(v) for v in value.split(','))
        if not all(math.isfinite(v) for v in (w, s, e, n)) or not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Nieprawidłowy obszar mapy GFM.') from None
    if not overlaps((w, s, e, n), POLAND):
        return None
    return max(w, POLAND[0]), max(s, POLAND[1]), min(e, POLAND[2]), min(n, POLAND[3])


def overlaps(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def country_shapes():
    path = Path(__file__).with_name('static')/'geo'/'provinces.geojson'
    return [f['geometry'] for f in json.loads(path.read_text())['features']]


def monitor_item(feature, now):
    """Metadata remains attached to each observation; no invented asset paths."""
    if not isinstance(feature, dict) or feature.get('collection') != 'GFM':
        raise ValueError('Nieprawidłowy produkt GFM')
    props, assets = feature['properties'], feature['assets']
    observed = instant(props['datetime'])
    if not now-timedelta(hours=48) <= datetime.fromisoformat(observed) <= now+timedelta(minutes=15):
        return None
    filtered = {name: assets[name] for name in LAYERS
                if isinstance(assets.get(name), dict) and safe_asset(assets[name].get('href'))}
    identifier = feature['id']
    if not isinstance(identifier, str) or len(identifier) > 180 or not identifier.replace('_', '').replace('-', '').isalnum():
        raise ValueError('Nieprawidłowy identyfikator GFM')
    fingerprint = hashlib.sha256(json.dumps([identifier, props.get('processing:datetime'), filtered],
                                            sort_keys=True).encode()).hexdigest()
    return {'id': identifier, 'key': fingerprint, 'assets': filtered, 'observed_at': observed,
            'processed_at': instant(props['processing:datetime']) if props.get('processing:datetime') else None,
            'catalog_created_at': instant(props['created']) if props.get('created') else None,
            'version': str(props.get('processing:version') or '')[:512],
            'lineage': str(props.get('processing:lineage') or '')[:512],
            'facility': str(props.get('processing:facility') or '')[:512], 'fetched_at': now.isoformat(),
            'source_url': STAC+'/collections/GFM/items/'+identifier,
            'derived_from': [link['href'][:2048] for link in feature.get('links', [])
                             if isinstance(link, dict) and link.get('rel') == 'derived_from'
                             and isinstance(link.get('href'), str)][:8],
            'attribution': f'Contains modified Copernicus Emergency Management Service information [{observed[:4]}]',
            'missing_assets': [name for name in REQUIRED if name not in filtered]}


def scan_product(item, geometries, budget=None, opener=None):
    """Stream logical 512² windows; never allocate the complete 15000² source raster."""
    budget = {} if budget is None else budget
    budget.update(bytes=0, requests=0, deadline=time.monotonic()+40, max_requests=512)
    coverage, chunks, total = {}, [], 0
    retained = 0
    with cog_errors(budget), ExitStack() as stack:
        client = stack.enter_context(httpx.Client())
        stack.enter_context(rasterio.Env(GDAL_CACHEMAX=64*1024*1024, GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'))
        datasets = {}
        for name in LAYERS:
            asset = item['assets'].get(name)
            if not asset:
                continue
            url = asset['href']
            def remote(path, mode='rb', url=url):
                if path != url:
                    raise FileNotFoundError(path)
                return GDALRangeReader(url, client, budget)
            src = stack.enter_context(rasterio.open(url, opener=opener or remote, driver='GTiff', sharing=False))
            if (src.count != 1 or src.dtypes[0] != 'uint8' or src.nodata != 255 or not src.crs
                    or any(abs(res-20) > .01 for res in src.res)
                    or src.transform.b != 0 or src.transform.d != 0
                    or src.transform.a <= 0 or src.transform.e >= 0
                    or max(src.width, src.height) > 15_000
                    or any(block[0]*block[1] > 1_048_576 for block in src.block_shapes)):
                raise GFMUnavailable('Nieobsługiwany raster GFM.')
            datasets[name] = src
        primary = datasets['ensemble_flood_extent']
        if primary.width*primary.height > 225_000_000:
            raise GFMUnavailable('Kafel GFM przekracza 225 mln pikseli.')
        for name in list(datasets):
            src = datasets[name]
            if src.crs != primary.crs or src.transform != primary.transform or src.shape != primary.shape:
                datasets[name] = stack.enter_context(WarpedVRT(src, crs=primary.crs, transform=primary.transform,
                    width=primary.width, height=primary.height, nodata=255, resampling=Resampling.nearest,
                    warp_mem_limit=16))
        projected = [transform_geom('EPSG:4326', primary.crs, geom) for geom in geometries]
        projected = [(geom, geometry_bounds(geom)) for geom in projected]
        for row in range(0, primary.height, BLOCK):
            for col in range(0, primary.width, BLOCK):
                if time.monotonic() > budget['deadline']:
                    raise GFMUnavailable('Upłynął czas analizy kafla GFM.')
                window = Window(col, row, min(BLOCK, primary.width-col), min(BLOCK, primary.height-row))
                bounds = rasterio.windows.bounds(window, primary.transform)
                local = [geom for geom, bbox in projected if overlaps(bbox, bounds)]
                if not local:
                    continue
                flood = primary.read(1, window=window)
                if not np.any(np.isin(flood, [0, 1])):
                    continue
                inside = geometry_mask(local, flood.shape, primary.window_transform(window), invert=True)
                if not np.any(inside):
                    continue
                classes = classify(flood, *(datasets[name].read(1, window=window) for name in REQUIRED[1:]))
                valid = inside & (classes != 4)
                padded = np.zeros((BLOCK, BLOCK), dtype='uint8')
                padded[:flood.shape[0], :flood.shape[1]] = valid
                coverage[(row//BLOCK, col//BLOCK)] = zlib.compress(np.packbits(padded).tobytes())
                ys, xs = np.where(inside & (classes == 1))
                total += len(ys)
                keep = min(len(ys), MAX_POINTS-retained)
                if keep <= 0:
                    continue
                ys, xs = ys[:keep], xs[:keep]
                points = np.full((keep, 4), 255, dtype='uint16')
                points[:, 0], points[:, 1] = ys+row, xs+col
                for column, name in enumerate(LAYERS[3:], 2):
                    if name in datasets:
                        points[:, column] = datasets[name].read(1, window=window)[ys, xs]
                chunks.append(points)
                retained += keep
        points = np.concatenate(chunks) if chunks else np.empty((0, 4), dtype='uint16')
        grid = {'crs': primary.crs.to_wkt(), 'transform': list(primary.transform)[:6],
                'width': primary.width, 'height': primary.height}
    budget.pop('deadline')
    return {'item': {k: v for k, v in item.items() if k != 'assets'}, 'grid': grid,
            'grid_key': hashlib.sha256(json.dumps(grid, sort_keys=True).encode()).hexdigest(),
            'coverage': coverage, 'points': points, 'total': total, 'truncated': total > retained,
            'transfer': budget, 'size': points.nbytes+sum(len(v) for v in coverage.values())}


def point_groups(points):
    if not len(points):
        return
    block_ids = (points[:, 0].astype('int32')//BLOCK)*64+points[:, 1]//BLOCK
    order = np.argsort(block_ids, kind='stable')
    cuts = np.r_[0, np.flatnonzero(np.diff(block_ids[order]))+1, len(order)]
    for start, end in pairwise(cuts):
        key = int(block_ids[order[start]])
        yield (key//64, key % 64), order[start:end]


def latest_pixels(records):
    """A newer assessed pixel (including clear/reference/excluded) supersedes an older flood."""
    newer, result = {}, []
    for record in sorted(records, key=lambda r: r['item']['observed_at'], reverse=True):
        points = record['points']
        keep = np.ones(len(points), dtype=bool)
        for block, indexes in point_groups(points):
            positions = (points[indexes, 0].astype('int64') % BLOCK)*BLOCK+points[indexes, 1] % BLOCK
            for previous in newer.get(record['grid_key'], []):
                packed = previous['coverage'].get(block)
                if packed:
                    covered = np.unpackbits(np.frombuffer(zlib.decompress(packed), dtype='uint8'))
                    keep[indexes] &= ~covered[positions].astype(bool)
        if np.any(keep):
            result.append((record, points[keep]))
        newer.setdefault(record['grid_key'], []).append(record)
    return result


class GFMMonitor:
    def __init__(self, service, geometries=None):
        self.service = service
        self.geometries = country_shapes() if geometries is None else geometries
        self.catalog = []
        self.records = OrderedDict()
        self.failed = {}
        self.task = None
        self.checked_at = None
        self.catalog_due = service.clock()
        self.error = None
        self.revision = 0
        self.snapshot_lock = asyncio.Lock()
        self.snapshots = OrderedDict()
        self.limited = False

    async def close(self):
        if self.task:
            await asyncio.shield(self.task)

    async def _catalog(self):
        now = self.service.clock()
        params = {'collections': 'GFM', 'bbox': ','.join(map(str, POLAND)),
                  'datetime': f'{(now-timedelta(hours=48)).isoformat()}/{now.isoformat()}', 'limit': 24}
        found, seen = {}, set()
        more = False
        oversized = False
        async with asyncio.timeout(45):
            for _ in range(4):
                data = await self.service._json(STAC+'/search', params)
                if not isinstance(data, dict) or not isinstance(data.get('features'), list):
                    raise GFMUnavailable('Nieprawidłowy katalog GFM.')
                oversized |= len(data['features']) > 24
                for feature in data['features'][:24]:
                    try:
                        item = monitor_item(feature, now)
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        raise GFMUnavailable('Nieprawidłowy kontrakt produktu GFM.') from exc
                    if item:
                        found[item['id']] = item
                next_link = next((link for link in data.get('links', [])
                                  if isinstance(link, dict) and link.get('rel') == 'next'), None)
                more = next_link is not None
                if not more:
                    break
                url = urlsplit(next_link.get('href', ''))
                token = parse_qs(url.query).get('token', [''])[0]
                if (url.scheme != 'https' or url.netloc != 'stac.eodc.eu' or url.path != '/api/v1/search'
                        or not token or len(token) > 1024 or token in seen):
                    raise GFMUnavailable('Nieobsługiwana paginacja GFM.')
                seen.add(token)
                params = {**params, 'token': token}
        self.catalog = sorted(found.values(), key=lambda item: item['observed_at'], reverse=True)[:MAX_PRODUCTS]
        keys = {item['key'] for item in self.catalog}
        identifiers = {item['id'] for item in self.catalog}
        # A metadata revision is not an assessment: keep the last successful
        # version (including its clear coverage) until its replacement is read.
        self.records = OrderedDict((key, value) for key, value in self.records.items()
                                   if value['item']['id'] in identifiers)
        self.failed = {key: value for key, value in self.failed.items() if key in keys}
        self.checked_at = now.isoformat()
        self.catalog_due = now+timedelta(minutes=10)
        self.limited = more or oversized
        self.revision += 1

    def _pending(self):
        return next((item for item in self.catalog if not item['missing_assets']
                     and item['key'] not in self.records
                     and (item['key'] not in self.failed or self.failed[item['key']][0] <= self.service.clock())), None)

    async def _step(self):
        svc = self.service
        budget = {}
        try:
            async with svc.lock:
                if svc.clock() < svc.retry_at:
                    return
                if svc.clock() >= self.catalog_due:
                    await self._catalog()
                item = self._pending()
                if item:
                    try:
                        record = await asyncio.to_thread(scan_product, item, self.geometries, budget)
                    except Exception as exc:
                        detail = str(exc) if isinstance(exc, GFMUnavailable) else 'Nie udało się odczytać rastrów.'
                        self.failed[item['key']] = (svc.clock()+timedelta(minutes=10), detail)
                        raise GFMUnavailable(f'Część rastrów GFM jest niedostępna. {detail} Zachowano pozostałe odczyty.') from exc
                    self.failed.pop(item['key'], None)
                    self.records = OrderedDict((key, value) for key, value in self.records.items()
                                               if value['item']['id'] != item['id'])
                    self.records[item['key']] = record
                    while sum(record['size'] for record in self.records.values()) > MAX_CACHE_BYTES:
                        key = min(self.records, key=lambda key: self.records[key]['item']['observed_at'])
                        del self.records[key]
                        self.failed[key] = (svc.clock()+timedelta(minutes=10), 'Przekroczono limit cache.')
                        self.limited = True
                    self.revision += 1
                self.error = None
        except (GFMUnavailable, httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, OSError) as exc:
            self.error = str(exc) if isinstance(exc, GFMUnavailable) else 'Źródło GFM jest chwilowo niedostępne.'
            svc.retry_at = max(svc.retry_at, svc.clock()+timedelta(seconds=budget.get('retry', 60)))
            if svc.clock() >= self.catalog_due:
                self.catalog_due = svc.clock()+timedelta(minutes=1)

    async def snapshot(self, bbox=None):
        svc = self.service
        if svc.demo or not svc.enabled:
            return {'enabled': False, 'status': 'demo_no_data' if svc.demo else 'disabled', 'clusters': [],
                    'features': [], 'message': 'Demo offline: brak danych GFM.' if svc.demo else 'GFM wyłączone.'}
        if ((self.task is None or self.task.done()) and svc.clock() >= svc.retry_at
                and (svc.clock() >= self.catalog_due or self._pending() is not None)):
            self.task = asyncio.create_task(self._step())
        # Coordinate processing and compositing are CPU work; keep them off the API event loop.
        async with self.snapshot_lock:
            state = self._state()
            key = (state['revision'], tuple(bbox) if bbox else None, int(svc.clock().timestamp())//30)
            if key not in self.snapshots:
                self.snapshots[key] = await asyncio.to_thread(self._snapshot, bbox, state)
                while len(self.snapshots) > 2:
                    self.snapshots.popitem(last=False)
            return {**self.snapshots[key], 'busy': self.task is not None and not self.task.done(),
                    'poll_after_seconds': 3 if self.task is not None and not self.task.done() else 30}

    def _state(self):
        return {'records': list(self.records.values()), 'catalog': list(self.catalog), 'failed': dict(self.failed),
                'revision': self.revision, 'error': self.error, 'limited': self.limited, 'checked_at': self.checked_at}

    def _snapshot(self, bbox, state=None):
        state = self._state() if state is None else state
        now = self.service.clock()
        records = [record for record in state['records']
                   if datetime.fromisoformat(record['item']['observed_at']) >= now-timedelta(hours=48)]
        assessed_keys = {record['item']['key'] for record in records}
        processed = sum(item['key'] in assessed_keys for item in state['catalog'])
        selected = latest_pixels(records)
        clusters, features, pixels = [], [], 0
        clipped = False
        for record, points in selected:
            affine = rasterio.Affine(*record['grid']['transform'])
            view_bounds = transform_bounds('EPSG:4326', record['grid']['crs'], *bbox) if bbox else None
            for (row, col), indexes in point_groups(points):
                block_points = points[indexes]
                xs = affine.c+(block_points[:, 1]+.5)*affine.a
                ys = affine.f+(block_points[:, 0]+.5)*affine.e
                lon, lat = transform_coordinates(record['grid']['crs'], 'EPSG:4326', xs, ys)
                lon, lat = np.asarray(lon), np.asarray(lat)
                properties = {'product': record['item'], 'pixels': len(indexes),
                              'flags': sorted(set(map(int, block_points[:, 2]))),
                              'likelihood': sorted(set(map(int, block_points[:, 3])))}
                clusters.append({'type': 'Feature', 'geometry': {'type': 'Point',
                    'coordinates': [float(lon.mean()), float(lat.mean())]}, 'properties': properties})
                if view_bounds is None:
                    continue
                visible = ((xs+10 >= view_bounds[0]) & (xs-10 <= view_bounds[2])
                           & (ys+10 >= view_bounds[1]) & (ys-10 <= view_bounds[3]))
                local = block_points[visible]
                if not len(local):
                    continue
                if pixels+len(local) > 20_000:
                    clipped = True
                    continue
                pixels += len(local)
                mask = np.zeros((BLOCK, BLOCK), dtype='uint8')
                mask[local[:, 0] % BLOCK, local[:, 1] % BLOCK] = 1
                origin = affine @ rasterio.Affine.translation(col*BLOCK, row*BLOCK)
                # Give polygonization a georeferenced dataset, not temporary
                # ndarray datasets whose creation can warn in worker threads.
                with rasterio.io.MemoryFile() as memory, memory.open(
                        driver='GTiff', width=BLOCK, height=BLOCK, count=1, dtype='uint8',
                        transform=origin, crs=record['grid']['crs']) as raster:
                    raster.write(mask, 1)
                    polygons = [geom['coordinates'] for geom, value in shapes(rasterio.band(raster, 1))
                                if value == 1]
                geom = transform_geom(record['grid']['crs'], 'EPSG:4326', {'type': 'MultiPolygon', 'coordinates': polygons})
                features.append({'type': 'Feature', 'geometry': geom,
                                 'properties': {**properties, 'pixels': len(local),
                                     'flags': sorted(set(map(int, local[:, 2]))),
                                     'likelihood': sorted(set(map(int, local[:, 3])))}})
        result = {'enabled': True, 'status': 'partial' if processed < len(state['catalog']) or not state['checked_at']
                or state['error'] or state['limited'] or state['failed']
                or any(item['missing_assets'] for item in state['catalog']) else 'ready',
                'busy': self.task is not None and not self.task.done(), 'checked_at': state['checked_at'],
                'products': len(state['catalog']), 'processed': processed,
                'unavailable': sum(bool(item['missing_assets']) for item in state['catalog']),
                'failed': len(state['failed']), 'truncated': state['limited'] or clipped or len(clusters) > 2000 or any(r['truncated'] for r in records),
                'revision': str(state['revision'])+':'+hashlib.sha256(
                    ','.join(r['item']['key'] for r in records).encode()).hexdigest()[:12],
                'clusters': clusters[:2000], 'features': features, 'pixels': sum(len(points) for _, points in selected),
                'message': state['error'], 'window_hours': 48,
                'poll_after_seconds': 3 if self.task is not None and not self.task.done() else 30}

        while len(json.dumps(result, separators=(',', ':')).encode()) > MAX_RESPONSE_BYTES:
            target = result['features'] or result['clusters']
            if not target:
                break
            del target[len(target)//2:]
            result['truncated'] = True
        if result['truncated']:
            result['status'] = 'partial'
        return result
