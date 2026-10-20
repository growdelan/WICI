"""On-demand, bounded catalogue lookup and thumbnail proxy for Copernicus EMS.

CEMS endpoints and thumbnail paths match the official Rapid Mapping viewer.
A CEMS thumbnail is a cartographic product, not a georeferenced satellite raster.
"""
import asyncio
import hashlib
import json
import math
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx

CEMS_ROOT = 'https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/'
CEMS_CATALOG = CEMS_ROOT + 'public-activations-info/'
CEMS_DETAIL = CEMS_ROOT + 'public-activations/'
CEMS_IMAGES = 'https://rapidmapping-viewer.s3.eu-west-1.amazonaws.com'
RADIUS_KM = 10
JSON_LIMIT = 4 * 1024 * 1024
PREVIEW_LIMIT = 4 * 1024 * 1024
MAX_ITEMS = 12
MAX_ACTIVATIONS = 4
PREVIEW_HOSTS = frozenset({
    'rapidmapping-viewer.s3.eu-west-1.amazonaws.com',
})


class ImageryUnavailable(Exception):
    """A known catalogue thumbnail cannot currently be retrieved."""


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        # Dashboard timestamps omit timezone. Preserve a calendar date rather than invent UTC.
        return parsed.isoformat() if parsed.tzinfo else parsed.date().isoformat()
    except ValueError:
        return None


def _bounds(value):
    try:
        west, south, east, north = map(float, value)
        if all(math.isfinite(x) for x in (west, south, east, north)) and (
                -180 <= west < east <= 180 and -90 <= south < north <= 90):
            return [[south, west], [north, east]]
    except (TypeError, ValueError):
        pass
    return None


def _wkt_bounds(value):
    if not isinstance(value, str) or not value.startswith(('POLYGON', 'MULTIPOLYGON')):
        return None
    pairs = re.findall(r'(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)', value)
    if not pairs:
        return None
    xs, ys = zip(*((float(x), float(y)) for x, y in pairs))
    return _bounds([min(xs), min(ys), max(xs), max(ys)])


def _intersects(a, b):
    return a and b and a[0][0] <= b[1][0] and a[1][0] >= b[0][0] and (
        a[0][1] <= b[1][1] and a[1][1] >= b[0][1])


def _distance(lat, lon, other_lat, other_lon):
    p1, p2 = math.radians(lat), math.radians(other_lat)
    dlon = math.radians(other_lon-lon)
    a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def _safe_preview(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in PREVIEW_HOSTS and
                parsed.port in (None, 443) and not parsed.username and not parsed.password and
                not parsed.query and not parsed.fragment and
                re.fullmatch(r'/[A-Za-z0-9_./-]+\.(?:png|jpg|jpeg)', parsed.path, re.IGNORECASE) is not None and
                '..' not in parsed.path)
    except ValueError:
        return False


class ImageryService:
    def __init__(self, client, clock, timeout=20, enabled=True, demo=False):
        self.client, self.clock, self.timeout = client, clock, timeout
        self.enabled, self.demo = enabled, demo
        self.lock = asyncio.Lock()
        self.preview_slots = asyncio.Semaphore(4)
        self.provider_deadline = 8
        self.detail_deadline = 5
        self.searches, self.details, self.assets, self.previews = (OrderedDict() for _ in range(4))
        self.catalog = None

    def _put(self, cache, key, value, maximum):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > maximum:
            cache.popitem(last=False)

    async def _fetch(self, url, params=None, limit=JSON_LIMIT):
        async with self.client.stream('GET', url, params=params, timeout=self.timeout,
                                      follow_redirects=False) as response:
            if response.status_code != 200:
                raise ImageryUnavailable('Źródło nie udostępniło danych.')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise ImageryUnavailable('Odpowiedź źródła przekracza limit.')
            return bytes(body)

    async def _json(self, url, params=None):
        value = json.loads(await self._fetch(url, params))
        if not isinstance(value, dict) or not isinstance(value.get('results'), list):
            raise ImageryUnavailable('Nieprawidłowy katalog źródła.')
        return value

    def _register(self, source, identifier, preview):
        key = source + '-' + hashlib.sha256(str(identifier).encode()).hexdigest()[:24]
        if _safe_preview(preview):
            return key, '/api/imagery/preview/' + key
        return key, None

    def _selected(self, items):
        selected = items[:MAX_ITEMS]
        for item in selected:
            remote = item.pop('_thumbnail', None)
            if item['preview_url'] and _safe_preview(remote):
                self._put(self.assets, item['id'], (self.clock()+timedelta(hours=1), remote), 1024)
        return selected

    async def _cems(self, lat, lon, box):
        now = self.clock()
        if self.catalog is None or now >= self.catalog[0]:
            data = await self._json(CEMS_CATALOG, {'limit': 500})
            self.catalog = (now+timedelta(minutes=30), data)
        data = self.catalog[1]
        candidates = []
        for row in data['results'][:500]:
            if not isinstance(row, dict) or not re.fullmatch(r'EMSR\d+', str(row.get('code', ''))):
                continue
            point = re.fullmatch(r'POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)', row.get('centroid') or '')
            if not point:
                continue
            x, y = map(float, point.groups())
            if not (-180 <= x <= 180 and -90 <= y <= 90):
                continue
            distance = _distance(lat, lon, y, x)
            if distance <= 400:
                candidates.append((distance, row['code']))
        candidates.sort()
        items, failures = [], 0
        async def load_detail(code):
            cached = self.details.get(code)
            if cached and now < cached[0]:
                return cached[1]
            detail = await asyncio.wait_for(self._json(CEMS_DETAIL, {'code': code}), self.detail_deadline)
            self._put(self.details, code, (now+timedelta(minutes=30), detail), 24)
            return detail

        codes = [code for _, code in candidates[:MAX_ACTIVATIONS]]
        details = await asyncio.gather(*(load_detail(code) for code in codes), return_exceptions=True)
        for code, detail in zip(codes, details):
            try:
                if isinstance(detail, BaseException):
                    raise ImageryUnavailable('Aktywacja jest niedostępna.')
                for activation in detail['results'][:1]:
                    for aoi in activation.get('aois', [])[:200]:
                        bounds = _wkt_bounds(aoi.get('extent'))
                        if not _intersects(bounds, box):
                            continue
                        for product in aoi.get('products', [])[:100]:
                            if (not product.get('feasible') or not product.get('mapsCount') or
                                    (product.get('version') or {}).get('statusCode') != 'F'):
                                continue
                            # This path transform is used by the official CEMS viewer.
                            path = urlsplit(str(product.get('downloadPath', ''))).path
                            pattern = rf'/backend/({code}/AOI\d+/[A-Z0-9_]+)/[A-Za-z0-9_]+\.zip'
                            match = re.fullmatch(pattern, path)
                            if not match:
                                continue
                            preview = CEMS_IMAGES + '/' + match.group(1) + '/thumbnails/thumbnail.jpg'
                            remote = preview
                            key, preview = self._register('cems', f'{code}:{product.get("id")}:{path}', preview)
                            acquisitions = sorted(filter(None, (_date(image.get('acquisitionTime'))
                                for image in product.get('images', []) if isinstance(image, dict))))
                            items.append({'id': key, 'source': 'Copernicus EMS',
                                'source_url': f'https://mapping.emergency.copernicus.eu/activations/{code}/',
                                'title': f'{code} · {aoi.get("name", "")} · {product.get("type", "")}',
                                'acquired_at': acquisitions[0] if acquisitions else None,
                                'acquisition_end': acquisitions[-1] if acquisitions else None,
                                'product_at': _date((product.get('version') or {}).get('deliveryTime')),
                                'preview_url': preview, '_thumbnail': remote, 'bounds': bounds, 'kind': 'mapping',
                                'attribution': '© European Union, Copernicus EMS',
                                'license': 'Copernicus EMS — warunki wykorzystania na stronie źródła'})
            except (ImageryUnavailable, ValueError, TypeError, KeyError, AttributeError):
                failures += 1
        items.sort(key=lambda item: item['acquired_at'] or item['product_at'] or '', reverse=True)
        message = ('Katalog Rapid Mapping: do 4 najbliższych aktywacji o środku w odległości do 400 km; '
                   'do 12 produktów przecinających okolicę. Zasięgi są prostokątami AOI. '
                   'Podglądy przedstawiają mapy skutków; archiwum może być niepełne.')
        if failures:
            message += ' Część aktywacji jest niedostępna.'
        return self._selected(items), {'source': 'Copernicus EMS',
            'status': 'error' if failures and failures == min(len(candidates), MAX_ACTIVATIONS) else 'partial',
            'message': message}

    async def search(self, lat, lon):
        lat, lon = float(lat), float(lon)
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError('Nieprawidłowe współrzędne miejsca.')
        base = {'enabled': self.enabled and not self.demo, 'items': [], 'providers': [],
                'fetched_at': None, 'radius_km': RADIUS_KM, 'location': {'lat': lat, 'lon': lon}}
        if not self.enabled or self.demo:
            return {**base, 'status': 'disabled', 'message': 'Zobrazowania wyłączone' +
                    (' w trybie demo (bez sieci).' if self.demo else ' w konfiguracji.')}
        try:
            # Include time waiting for another search, so stale UI requests cannot queue indefinitely.
            async with asyncio.timeout(self.provider_deadline + 0.5):
                return await self._search_active(lat, lon, base)
        except TimeoutError:
            return {**base, 'status': 'error', 'message': 'Wyszukiwanie trwa zbyt długo. Spróbuj ponownie.',
                    'providers': [{'source': 'Copernicus EMS', 'status': 'error',
                                   'message': 'Upłynął czas wyszukiwania.'}]}

    async def _search_active(self, lat, lon, base):
        # Cache exact coordinates: no rounding that could mix nearby search areas.
        cache_key = (lat, lon)
        async with self.lock:
            now = self.clock()
            cached = self.searches.get(cache_key)
            if cached and now < cached[0]:
                return cached[1]
            dlat = RADIUS_KM / 111.32
            dlon = min(180, dlat / max(0.001, math.cos(math.radians(lat))))
            box = [[max(-90, lat-dlat), max(-180, lon-dlon)],
                   [min(90, lat+dlat), min(180, lon+dlon)]]
            try:
                items, provider = await asyncio.wait_for(self._cems(lat, lon, box), self.provider_deadline)
            except (TimeoutError, ImageryUnavailable, ValueError, TypeError, KeyError, AttributeError, OSError, httpx.HTTPError):
                items = []
                provider = {'source': 'Copernicus EMS', 'status': 'error',
                            'message': 'Źródło jest chwilowo niedostępne. Spróbuj ponownie później.'}
            providers = [provider]
            status = provider['status']
            result = {**base, 'status': status, 'items': items, 'providers': providers,
                'fetched_at': self.clock().isoformat(), 'search_bounds': box,
                'message': 'Materiały archiwalne dla okolicy do 10 km (prostokąt wyszukiwania). ' +
                    ('Znaleziono dostępne produkty.' if items else 'Brak produktów w sprawdzonej części katalogów.')}
            ttl = timedelta(minutes=2 if status == 'error' else 15)
            self._put(self.searches, cache_key, (now+ttl, result), 32)
            return result

    async def preview(self, identifier):
        if not self.enabled or self.demo:
            raise ImageryUnavailable('Zobrazowania wyłączone.')
        try:
            async with asyncio.timeout(self.provider_deadline):
                async with self.preview_slots:
                    return await self._preview(identifier)
        except TimeoutError as exc:
            raise ImageryUnavailable("Upłynął czas pobierania podglądu.") from exc

    async def _preview(self, identifier):
        now = self.clock()
        asset = self.assets.get(identifier)
        if not asset or now >= asset[0]:
            raise KeyError(identifier)
        cached = self.previews.get(identifier)
        if cached and now < cached[0]:
            return cached[1]
        try:
            body = await self._fetch(asset[1], limit=PREVIEW_LIMIT)
            if body.startswith(b'\x89PNG\r\n\x1a\n'):
                media = 'image/png'
            elif body.startswith(b'\xff\xd8\xff'):
                media = 'image/jpeg'
            else:
                raise ImageryUnavailable('Źródło nie zwróciło podglądu obrazu.')
            self._put(self.previews, identifier, (now+timedelta(minutes=30), (body, media)), 8)
            return body, media
        except Exception as exc:
            raise ImageryUnavailable('Podgląd obrazu jest chwilowo niedostępny.') from exc
