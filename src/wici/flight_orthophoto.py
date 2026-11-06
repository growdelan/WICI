"""On-demand GUGiK WMTS tiles for flight replay, including transparent border tiles."""
import asyncio
import math
import warnings
from collections import OrderedDict, deque

import httpx
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.io import MemoryFile

from wici.gfm import retry_seconds
from wici.traffic import validate_tile as validate_png

WMTS = 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution'
# WGS84BoundingBox advertised by the ORTOFOTOMAPA layer.
BOUNDS = (13.8, 48.8, 24.4, 55.0)
MAX_BYTES = 256 * 1024
MAX_CACHE = 128
MAX_CALLS_PER_MINUTE = 240
MAX_PENDING = 24


class OrthophotoUnavailable(Exception):
    def __init__(self, retry_in):
        self.retry_in = max(1, math.ceil(retry_in))
        super().__init__('Ortofotomapa chwilowo niedostępna.')


def within_coverage(z, x, y):
    if not 11 <= z <= 19 or not (0 <= x < 2**z and 0 <= y < 2**z):
        return False
    west, south, east, north = BOUNDS
    n = 2**z

    def row(lat):
        return n * (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2

    return (x < n*(east+180)/360 and x+1 > n*(west+180)/360
            and y < row(south) and y+1 > row(north))


def image_type(body):
    # GUGiK also returns RGBA PNGs labelled image/jpeg at the edge of coverage.
    if body.startswith(b'\xff\xd8\xff') and body.endswith(b'\xff\xd9'):
        driver, mime = 'JPEG', 'image/jpeg'
    elif body.startswith(b'\x89PNG\r\n\x1a\n'):
        validate_png(body)
        driver, mime = 'PNG', 'image/png'
    else:
        raise ValueError('Nieprawidłowy format ortofotomapy.')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', NotGeoreferencedWarning)
        with MemoryFile(body) as memory, memory.open(driver=driver) as image:
            if ((image.width, image.height) != (256, 256) or image.count not in (1, 2, 3, 4)
                    or any(dtype != 'uint8' for dtype in image.dtypes)):
                raise ValueError('Nieprawidłowy obraz ortofotomapy.')
            image.read()
    return mime


class FlightOrthophoto:
    def __init__(self, client, clock, timeout=12):
        self.client, self.clock, self.timeout = client, clock, min(12, timeout)
        self.cache = OrderedDict()
        self.pending = {}
        self.slots = asyncio.Semaphore(4)
        self.calls = deque()
        self.retry_at = 0.

    async def tile(self, z, x, y):
        if not within_coverage(z, x, y):
            return None
        key = (z, x, y)
        # A cancelled download wakes its waiters as well: one may retry the tile.
        while (pending := self.pending.get(key)) is not None:
            await pending.wait()
        cached = self.cache.get(key)
        if cached and cached[0] > self.clock().timestamp():
            self.cache.move_to_end(key)
            return cached[1]
        if len(self.pending) >= MAX_PENDING:
            raise OrthophotoUnavailable(2)
        self.pending[key] = asyncio.Event()
        try:
            async with self.slots:
                result = await self.download(z, x, y)
                self.cache[key] = (self.clock().timestamp() + (21600 if result else 600), result)
                self.cache.move_to_end(key)
                if len(self.cache) > MAX_CACHE:
                    self.cache.popitem(last=False)
                return result
        finally:
            self.pending.pop(key).set()

    async def download(self, z, x, y):
        now = self.clock().timestamp()
        if now < self.retry_at:
            raise OrthophotoUnavailable(self.retry_at-now)
        while self.calls and self.calls[0] <= now-60:
            self.calls.popleft()
        if len(self.calls) >= MAX_CALLS_PER_MINUTE:
            raise OrthophotoUnavailable(self.calls[0]+60-now)
        self.calls.append(now)
        params = {'SERVICE': 'WMTS', 'VERSION': '1.0.0', 'REQUEST': 'GetTile',
                  'LAYER': 'ORTOFOTOMAPA', 'STYLE': 'default', 'FORMAT': 'image/jpeg',
                  'TILEMATRIXSET': 'EPSG:3857', 'TILEMATRIX': f'EPSG:3857:{z}', 'TILECOL': x, 'TILEROW': y}
        delay = 30
        try:
            async with asyncio.timeout(self.timeout), self.client.stream(
                    'GET', WMTS, params=params, timeout=self.timeout, follow_redirects=False,
                    headers={'Accept-Encoding': 'identity'}) as response:
                if response.status_code in (204, 404):
                    return None
                if response.status_code in (429, 503):
                    delay = max(delay, retry_seconds(response.headers.get('retry-after'), self.clock()))
                response.raise_for_status()
                if (response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity'
                        or response.headers.get('content-type', '').split(';')[0].lower() not in ('image/jpeg', 'image/png')
                        or int(response.headers.get('content-length', 0)) > MAX_BYTES):
                    raise ValueError('Nieprawidłowa odpowiedź WMTS.')
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16*1024):
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise ValueError('Zbyt duży kafel.')
                    body.extend(chunk)
            image = bytes(body)
            return image, await asyncio.to_thread(image_type, image)
        except (httpx.HTTPError, ValueError, RasterioError, TimeoutError):
            self.retry_at = max(self.retry_at, self.clock().timestamp()+delay)
            raise OrthophotoUnavailable(delay) from None
