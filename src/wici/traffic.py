"""On-demand TomTom raster flow proxy; private key and persistent local free-tier cap."""
import asyncio
import json
import math
import re
import struct
import zlib
from collections import OrderedDict
from datetime import UTC, timedelta
from email.utils import parsedate_to_datetime

import httpx

ENDPOINT = 'https://api.tomtom.com/maps/orbis/traffic/flow/raster/tile'
ROAD_ENDPOINT = 'https://api.tomtom.com/maps/orbis/places/reverseGeocode'
BOUNDS = [[49, 14], [55, 24.2]]
MONTHLY_LIMIT = 190_000  # Headroom below the published 200k raster-tile free allowance.
REFRESH_SECONDS = 300
MAX_BYTES = 1024 * 1024
SIGNATURE = b'\x89PNG\r\n\x1a\n'


class TrafficUnavailable(Exception):
    """Only safe local messages may reach API responses."""


def tile_in_poland(z, x, y):
    if not 6 <= z <= 18 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise ValueError('Nieprawidłowe współrzędne kafelka ruchu')
    n = 2**z
    west, east = x/n*360-180, (x+1)/n*360-180
    north = math.degrees(math.atan(math.sinh(math.pi*(1-2*y/n))))
    south = math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+1)/n))))
    return west < 24.2 and east > 14 and south < 55 and north > 49


def validate_tile(body):
    """Check PNG framing, CRCs and dimensions; provider may use indexed PNG colors."""
    if not body.startswith(SIGNATURE):
        raise ValueError('Nieprawidłowy obraz ruchu')
    pos, header, data = 8, False, False
    while pos+12 <= len(body):
        size = struct.unpack('>I', body[pos:pos+4])[0]
        kind = body[pos+4:pos+8]
        end = pos+8+size
        if end+4 > len(body) or zlib.crc32(body[pos+4:end]) != struct.unpack('>I', body[end:end+4])[0]:
            break
        if kind == b'IHDR':
            if header or pos != 8 or size != 13 or struct.unpack('>II', body[pos+8:pos+16]) != (256, 256):
                break
            header = True
        elif kind == b'IDAT':
            data = data or size > 0
        elif kind == b'IEND':
            if header and data and size == 0 and end+4 == len(body):
                return body
            break
        pos = end+4
    raise ValueError('Niepełny obraz ruchu')


class TrafficService:
    def __init__(self, client, clock, usage_path, key='', enabled=False, demo=False, timeout=20,
                 monthly_limit=MONTHLY_LIMIT):
        self.client, self.clock, self.usage_path = client, clock, usage_path
        self.key, self.enabled, self.demo, self.timeout = key, enabled, demo, timeout
        self.monthly_limit = monthly_limit
        self.lock = asyncio.Lock()
        self.cache = OrderedDict()
        self.month = self.clock().astimezone(UTC).strftime('%Y-%m')
        self.used, self.counter_error = 0, False
        self.last_fetch_at, self.retry_at, self.failure = None, None, ''
        try:
            if usage_path.exists():
                usage = json.loads(usage_path.read_text())
                if (not isinstance(usage, dict) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', usage.get('month', ''))
                        or type(usage.get('requests_used')) is not int or usage['requests_used'] < 0):
                    raise ValueError('Invalid quota file')
                self.month, self.used = usage['month'], usage['requests_used']
        except (OSError, ValueError, TypeError):
            self.counter_error = True

    def roll_month(self):
        month = self.clock().astimezone(UTC).strftime('%Y-%m')
        if month > self.month:
            self.month, self.used = month, 0

    def metadata(self):
        self.roll_month()
        enabled = bool(self.enabled and self.key and not self.demo)
        status, message = 'ready', ''
        if not enabled:
            status = 'disabled'
            message = ('TomTom wyłączony w demonstracji (bez sieci).' if self.demo else
                       'TomTom wyłączony lub brak klucza w lokalnej konfiguracji.')
        elif self.counter_error:
            status, message = 'error', 'Nie można odczytać lub zapisać licznika TomTom; pobieranie zatrzymane.'
        elif self.used >= self.monthly_limit:
            status, message = 'limit', 'Osiągnięto lokalny limit miesięczny TomTom; pobieranie zatrzymane.'
        elif self.retry_at and self.clock() < self.retry_at:
            status, message = 'error', self.failure
        return {'enabled': enabled, 'status': status, 'message': message, 'month': self.month,
                'requests_used': self.used, 'monthly_limit': self.monthly_limit,
                'refresh_seconds': REFRESH_SECONDS, 'tile_url': '/api/traffic/tiles/{z}/{x}/{y}.png',
                'bounds': BOUNDS, 'last_fetch_at': self.last_fetch_at}

    def reserve_request(self):
        # Persist before contacting provider: errors and interrupted downloads count too.
        self.used += 1
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.usage_path.with_suffix('.tmp')
            with temporary.open('w') as stream:
                json.dump({'month': self.month, 'requests_used': self.used}, stream)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            temporary.replace(self.usage_path)
        except OSError:
            self.counter_error = True
            raise TrafficUnavailable('Nie można zapisać licznika TomTom; pobieranie zatrzymane.') from None

    async def tile(self, z, x, y):
        if not tile_in_poland(z, x, y):
            raise ValueError('Kafelek poza obszarem Polski')
        async with self.lock:
            metadata = self.metadata()
            if metadata['status'] != 'ready':
                raise TrafficUnavailable(metadata['message'])
            now = self.clock()
            self.cache = OrderedDict((k, v) for k, v in self.cache.items() if v[0] > now)
            cached = self.cache.get((z, x, y))
            if cached:
                return cached[1]
            self.reserve_request()
            retry_seconds, failure = REFRESH_SECONDS, 'Ruch TomTom niedostępny; kolejna próba za kilka minut.'
            try:
                async with self.client.stream('GET', f'{ENDPOINT}/{z}/{x}/{y}',
                        params={'apiVersion': '2', 'style': 'light', 'tileSize': '256'},
                        headers={'TomTom-Api-Key': self.key, 'Accept': 'image/png'},
                        timeout=self.timeout, follow_redirects=False) as response:
                    if response.status_code != 200:
                        if response.status_code in (401, 403):
                            failure = 'TomTom odrzucił klucz lub dostęp do API; sprawdź konto TomTom.'
                        elif response.status_code == 429:
                            failure = 'Limit zapytań TomTom; pobieranie chwilowo wstrzymane.'
                            retry = response.headers.get('retry-after', '')
                            try:
                                seconds = float(retry)
                            except ValueError:
                                try:
                                    seconds = (parsedate_to_datetime(retry)-now).total_seconds()
                                except (ValueError, TypeError):
                                    seconds = REFRESH_SECONDS
                            if math.isfinite(seconds):
                                retry_seconds = max(REFRESH_SECONDS, min(seconds, 31*86400))
                        raise ValueError('Provider unavailable')
                    if response.headers.get('content-type', '').split(';')[0] != 'image/png':
                        raise ValueError('Provider did not return PNG')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError('Tile too large')
                    body = validate_tile(bytes(body))
                    # Respect the provider cache lifetime and never store traffic history.
                    cache_control = response.headers.get('cache-control', '').lower()
                    age = re.search(r'(?:^|,)\s*max-age=(\d+)', cache_control)
                    ttl = min(REFRESH_SECONDS, int(age[1])) if age and 'no-store' not in cache_control else 0
                self.last_fetch_at = self.clock().isoformat()
                self.retry_at, self.failure = None, ''
                if ttl:
                    self.cache[(z, x, y)] = (self.clock()+timedelta(seconds=ttl), body)
                    while len(self.cache) > 256:
                        self.cache.popitem(last=False)
                return body
            except (httpx.HTTPError, ValueError, struct.error):
                self.retry_at = self.clock()+timedelta(seconds=retry_seconds)
                self.failure = failure
                raise TrafficUnavailable(failure) from None


class RoadService(TrafficService):
    """Street identity near a clicked point; independent 19k reverse-geocoding cap."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('monthly_limit', 19_000)
        super().__init__(*args, **kwargs)

    async def lookup(self, lat, lon):
        if not (math.isfinite(lat) and math.isfinite(lon) and 49 <= lat <= 55 and 14 <= lon <= 24.2):
            raise ValueError('Kliknij drogę na mapie Polski')
        async with self.lock:
            metadata = self.metadata()
            if metadata['status'] != 'ready':
                raise TrafficUnavailable(metadata['message'])
            self.reserve_request()
            delay = REFRESH_SECONDS
            try:
                async with self.client.stream('GET', ROAD_ENDPOINT,
                        params={'position':f'{lon:.6f},{lat:.6f}', 'radiusInMeters':'250'},
                        headers={'TomTom-Api-Key':self.key, 'TomTom-Api-Version':'2',
                                 'Attributes':'results', 'Accept':'application/json'},
                        timeout=self.timeout, follow_redirects=False) as response:
                    if response.status_code != 200:
                        if response.status_code == 429:
                            retry = response.headers.get('retry-after', '')
                            try:
                                seconds = float(retry)
                            except ValueError:
                                try:
                                    seconds = (parsedate_to_datetime(retry)-self.clock()).total_seconds()
                                except (ValueError, TypeError):
                                    seconds = REFRESH_SECONDS
                            if math.isfinite(seconds):
                                delay = max(REFRESH_SECONDS, min(seconds, 31*86400))
                        raise ValueError('Road lookup unavailable')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ValueError('Road response too large')
                    payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                    raise TypeError('Invalid road response')
                # Keep only public road identity, never house numbers or full addresses.
                for result in payload['results']:
                    if not isinstance(result, dict) or result.get('type') not in ('street', 'address'):
                        continue
                    address = result.get('address', {})
                    if not isinstance(address, dict) or address.get('countryCodeIso2') != 'PL':
                        continue
                    name, numbers = address.get('street'), address.get('routeNumbers', [])
                    if name is not None and (not isinstance(name, str) or len(name) > 300):
                        raise ValueError('Invalid street name')
                    if not isinstance(numbers, list) or len(numbers) > 20 or any(
                            not isinstance(n, str) or len(n) > 40 for n in numbers):
                        raise ValueError('Invalid road numbers')
                    if name or numbers:
                        return {'found':True, 'name':name or None,
                                'symbols':list(dict.fromkeys(n for n in numbers if n)),
                                'source':'TomTom', 'radius_m':250}
                return {'found':False, 'name':None, 'symbols':[], 'source':'TomTom', 'radius_m':250}
            except (httpx.HTTPError, ValueError, TypeError):
                self.retry_at = self.clock()+timedelta(seconds=delay)
                self.failure = 'Nie udało się odczytać nazwy drogi z TomTom. Spróbuj za kilka minut.'
                raise TrafficUnavailable(self.failure) from None
