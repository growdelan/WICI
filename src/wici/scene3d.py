"""Small on-demand terrain, building and tree tiles. No credentials, collectors or new services."""
import asyncio
import json
import math
import re
import time
from collections import OrderedDict
from datetime import UTC, datetime

import httpx
import numpy as np
from rasterio.errors import RasterioError
from rasterio.io import MemoryFile

from wici.buildings3d import decode_buildings, tile_bounds

BUILDINGS_URL = 'https://tiles.openfreemap.org/planet'
NMT_URL = 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF'
TREES_URL = 'https://mapa.um.warszawa.pl/mapviewer/dataserver/DANE_WAWA'
SIZE = 65
MAX_LEVEL = 14
MAX_TREES = 1200


def bounds(x, y, level):
    if not 0 <= level <= MAX_LEVEL or not 0 <= x < 2**(level+1) or not 0 <= y < 2**level:
        raise ValueError('Nieprawidłowy kafel 3D.')
    step = 180 / 2**level
    return (-180+x*step, 90-(y+1)*step, -180+(x+1)*step, 90-y*step)


def intersects(box, area):
    w, s, e, n = box
    return e > area[0] and n > area[1] and w < area[2] and s < area[3]


def decode_terrain(body):
    with MemoryFile(body) as memory, memory.open() as raster:
        if raster.width != SIZE or raster.height != SIZE or raster.count != 1:
            raise ValueError('Nieprawidłowy rozmiar NMT.')
        heights = raster.read(1, masked=True).filled(0)
        if not np.isfinite(heights).all() or (heights < -500).any() or (heights > 9000).any():
            raise ValueError('Nieprawidłowe wysokości NMT.')
        return np.round(heights, 2).ravel().tolist()


def trees_from_geojson(data, box):
    if data.get('type') != 'FeatureCollection' or data.get('srs') != 4326:
        raise ValueError('Nieprawidłowy zbiór drzew.')
    result, seen, dates = [], set(), set()
    for feature in data.get('features', []):
        geometry, props = feature.get('geometry') or {}, feature.get('properties') or {}
        coordinates = geometry.get('coordinates', [])
        if geometry.get('type') != 'Point' or len(coordinates) < 2:
            continue
        lon, lat = coordinates[:2]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lon, lat)):
            continue
        if not (box[0] <= lon < box[2] and box[1] <= lat < box[3]):
            continue
        identifier = str(feature.get('_id', f'{lon},{lat}'))
        if identifier in seen:
            continue
        seen.add(identifier)
        label = str(props.get('_label_', ''))[:4000]
        match = re.search(r'Wysokość w m:[ \t]*([0-9]+(?:[.,][0-9]+)?)', label)
        height = float(match[1].replace(',', '.')) if match else None
        measured = height is not None and 1 <= height <= 65
        diameter = props.get('SREDNICA_KORONY')
        crown_measured = isinstance(diameter, (int, float)) and math.isfinite(diameter) and 0.5 <= diameter <= 40
        date = re.search(r'Aktualność danych na dzień:[ \t]*([0-9.]+)', label)
        if date:
            dates.add(date[1])
        result.append({'id': identifier, 'longitude': lon, 'latitude': lat,
                       'height': height if measured else 8, 'diameter': diameter if crown_measured else 4,
                       'estimated': not measured or not crown_measured})
        if len(result) > MAX_TREES:
            break
    return result[:MAX_TREES], len(result) > MAX_TREES, sorted(dates)


class Scene3DService:
    def __init__(self, client, *, demo=False, enabled=True):
        self.client, self.demo, self.enabled = client, demo, enabled
        self.cache, self.jobs = OrderedDict(), {}
        self.semaphore = asyncio.Semaphore(2)

    async def read(self, url, params, maximum):
        async with self.client.stream('GET', url, params=params, timeout=12) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > maximum:
                    raise ValueError('Zbyt duża odpowiedź źródła 3D.')
            return bytes(body)

    async def cached(self, key, work):
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            self.cache.move_to_end(key)
            return cached[1]
        if key not in self.jobs:
            if len(self.jobs) >= 24:
                return {'status': 'unavailable', 'message': 'Ładowanie innych kafelków 3D; spróbuj ponownie.'}
            async def run():
                try:
                    async with self.semaphore:
                        result = await work()
                except (httpx.HTTPError, RasterioError, ValueError, TypeError, KeyError):
                    result = {'status': 'unavailable', 'message': 'Źródło 3D chwilowo niedostępne.'}
                ttl = 3600 if result['status'] == 'ready' else 30
                self.cache[key] = (time.monotonic()+ttl, result)
                self.cache.move_to_end(key)
                while len(self.cache) > 96:
                    self.cache.popitem(last=False)
                return result
            self.jobs[key] = asyncio.create_task(run())
            self.jobs[key].add_done_callback(lambda task: self.jobs.pop(key, None))
        return await asyncio.shield(self.jobs[key])

    async def terrain(self, x, y, level):
        box = bounds(x, y, level)
        if self.demo or not self.enabled or level < 10 or not intersects(box, (14, 49, 24.5, 55)):
            return {'status': 'empty'}

        async def work():
            # WCS pixels are centred; extend half a pixel so adjacent tile edge
            # vertices sample the same coordinate rather than forming seams.
            half = (box[2]-box[0])/(SIZE-1)/2
            coverage = (box[0]-half, box[1]-half, box[2]+half, box[3]+half)
            body = await self.read(NMT_URL, {
                'SERVICE': 'WCS', 'VERSION': '1.0.0', 'REQUEST': 'GetCoverage',
                'COVERAGE': 'DTM_PL-KRON86-NH_TIFF', 'CRS': 'EPSG:4326', 'RESPONSE_CRS': 'EPSG:4326',
                'FORMAT': 'image/tiff', 'BBOX': ','.join(map(str, coverage)), 'WIDTH': SIZE, 'HEIGHT': SIZE,
            }, 256_000)
            heights = await asyncio.to_thread(decode_terrain, body)
            return {'status': 'ready', 'heights': heights, 'size': SIZE, 'source': 'NMT / GUGiK',
                    'vertical_datum': 'PL-KRON86-NH', 'fetched_at': datetime.now(UTC).isoformat()}
        return await self.cached(('terrain', level, x, y), work)

    async def trees(self, x, y):
        box = bounds(x, y, MAX_LEVEL)
        base = {'items': [], 'source': 'Urząd m.st. Warszawy', 'modified': 'Schematyczne bryły 3D; brakujące wymiary szacowane.'}
        if self.demo or not self.enabled:
            return {**base, 'status': 'empty', 'message': 'Dane otoczenia 3D wyłączone w demonstracji lub konfiguracji.'}
        if not intersects(box, (20.75, 52.09, 21.28, 52.39)):
            return {**base, 'status': 'empty', 'message': 'Miejska baza drzew: pokrycie Warszawy.'}

        async def work():
            body = await self.read(TREES_URL, {
                't': 'BOS_ZIELEN_DRZEWA', 'bbox': ','.join(map(str, box)),
                'bbox_srid': 4326, 'to_srid': 4326, 'include_style_info': 'false', 'include_label_box': 'false',
            }, 4_000_000)
            items, truncated, dates = trees_from_geojson(json.loads(body), box)
            return {**base, 'status': 'ready', 'items': items, 'truncated': truncated,
                    'source_dates': dates, 'fetched_at': datetime.now(UTC).isoformat()}
        return await self.cached(('trees', x, y), work)

    async def buildings(self, x, y):
        box = tile_bounds(x, y)
        base = {'items': [], 'source': 'OpenFreeMap / © OpenMapTiles / © OpenStreetMap contributors',
                'license': 'ODbL 1.0'}
        if self.demo or not self.enabled:
            return {**base, 'status': 'empty', 'message': 'Budynki 3D wyłączone w demonstracji lub konfiguracji.'}
        if not intersects(box, (14, 49, 24.5, 55)):
            return {**base, 'status': 'empty', 'message': 'Budynki 3D: obszar Polski.'}

        async def source():
            data = json.loads(await self.read(BUILDINGS_URL, {}, 100_000))
            templates = data.get('tiles')
            if not isinstance(templates, list) or not templates or not isinstance(templates[0], str):
                raise ValueError('Brak adresu kafelków budynków.')
            template = templates[0]
            if not re.fullmatch(r'https://tiles\.openfreemap\.org/planet/[A-Za-z0-9_]+/\{z\}/\{x\}/\{y\}\.pbf', template):
                raise ValueError('Nieprawidłowy adres kafelków budynków.')
            return {'status': 'ready', 'template': template}
        # Resolve metadata before acquiring a tile's shared network semaphore.
        # Nested cached jobs could otherwise occupy both slots waiting on it.
        metadata = await self.cached(('building-source',), source)
        if metadata['status'] != 'ready':
            return {**base, **metadata}

        async def work():
            url = metadata['template'].format(z=14, x=x, y=y)
            body = await self.read(url, {}, 4_000_000)
            items, truncated, skipped = await asyncio.to_thread(decode_buildings, body, x, y)
            return {**base, 'status': 'ready', 'items': items, 'truncated': truncated, 'skipped': skipped,
                    'fetched_at': datetime.now(UTC).isoformat()}
        return await self.cached(('buildings', x, y), work)

    async def close(self):
        jobs = list(self.jobs.values())
        for task in jobs:
            task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
