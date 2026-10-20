"""On-demand adsb.fi snapshots, shared across viewers and clipped to Poland."""
import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from wici.weather import inside_ring, number

AIRCRAFT_URL = 'https://opendata.adsb.fi/api/v3/lat/52.05/lon/19.2/dist/250'
REFRESH_SECONDS = 10
MAX_POSITION_AGE = 120
MAX_BYTES = 4 * 1024 * 1024


def poland_polygons():
    features = json.loads((Path(__file__).parent/'static/geo/provinces.geojson').read_text())['features']
    polygons = []
    for feature in features:
        geometry = feature['geometry']
        for rings in ([geometry['coordinates']] if geometry['type'] == 'Polygon'
                      else geometry['coordinates']):
            outer = rings[0]
            bounds = (min(p[0] for p in outer), min(p[1] for p in outer),
                      max(p[0] for p in outer), max(p[1] for p in outer))
            polygons.append((bounds, rings))
    return polygons


POLYGONS = poland_polygons()


def in_poland(lat, lon):
    return any(left <= lon <= right and bottom <= lat <= top
               and inside_ring(lat, lon, rings[0])
               and not any(inside_ring(lat, lon, hole) for hole in rings[1:])
               for (left, bottom, right, top), rings in POLYGONS)


def label(value, maximum=32):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= maximum and not any(ord(c) < 32 for c in value) else None


class AircraftService:
    def __init__(self, client, clock, timeout=10, demo=False, enabled=True):
        self.client, self.clock = client, clock
        self.source_endpoint = AIRCRAFT_URL
        self.timeout = min(timeout, 10)
        self.demo, self.enabled = demo, enabled
        self.lock = asyncio.Lock()
        self.cache = None
        self.retry_at = None
        self.last_error = ''
        self.quality = None

    def base(self):
        return {'items': [], 'status': 'ready', 'stale': False, 'fetched_at': None,
                'refresh_seconds': REFRESH_SECONDS, 'message': '', 'enabled': bool(self.enabled),
                'demo': self.demo, 'source_name': 'adsb.fi', 'source_url': 'https://adsb.fi/'}

    def snapshot(self, now, error=False):
        result = dict(self.cache[1]) if self.cache else self.base()
        result['items'] = [dict(item) for item in result['items'] if
                           0 <= (now-datetime.fromisoformat(item['position_at'])).total_seconds()
                           <= MAX_POSITION_AGE]
        if error:
            retry = max(0, int((self.retry_at-now).total_seconds())) if self.retry_at else 0
            result.update(status='error', stale=bool(self.cache),
                          message=f'{self.last_error or "adsb.fi chwilowo niedostępne."} '
                                  f'Ponowna próba pobrania ze źródła za około {retry} s. '
                                  'Pozycje mogą być nieaktualne.')
        return result

    async def fetch(self):
        async with self.lock:
            now = self.clock().astimezone(UTC)
            if not self.enabled:
                return {**self.base(), 'status': 'disabled',
                        'message': 'Warstwa samolotów wyłączona w konfiguracji.'}
            if self.demo:
                return {**self.base(), 'message': 'Pozycje samolotów niedostępne w trybie demonstracyjnym.'}
            if self.cache and now < self.cache[0]:
                return self.snapshot(now)
            if self.retry_at and now < self.retry_at:
                return self.snapshot(now, error=True)
            try:
                # HTTPX limits individual network phases; bound the whole download too.
                async with asyncio.timeout(self.timeout):
                    payload = await self.download(now)
                now = self.clock().astimezone(UTC)
                items = self.normalize(payload, now)
                result = {**self.base(), 'items': items, 'fetched_at': now.isoformat()}
                self.cache = (self.clock().astimezone(UTC)+timedelta(seconds=REFRESH_SECONDS), result)
                if self.quality:
                    self.quality.enqueue(payload, now)
                self.retry_at = None
                self.last_error = ''
                return self.snapshot(now)
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, OverflowError) as exc:
                now = self.clock().astimezone(UTC)
                if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
                    self.last_error = 'Przekroczono limit czasu połączenia lub odpowiedzi adsb.fi.'
                elif isinstance(exc, httpx.HTTPStatusError):
                    code = exc.response.status_code
                    self.last_error = (f'adsb.fi ogranicza liczbę zapytań (HTTP {code}).' if code == 429
                                       else f'adsb.fi zwróciło błąd HTTP {code}.')
                elif isinstance(exc, httpx.HTTPError):
                    self.last_error = 'Nie udało się połączyć z adsb.fi.'
                else:
                    self.last_error = 'adsb.fi zwróciło nieprawidłowe lub nieaktualne dane.'
                logging.getLogger('wici').warning('Aircraft fetch failed: %s (%s: %s)',
                                                 self.last_error, type(exc).__name__, exc)
                self.retry_at = max(self.retry_at or now, now+timedelta(seconds=60))
                if self.quality:
                    self.quality.notify_error(now)
                return self.snapshot(now, error=True)

    async def download(self, now):
        async with self.client.stream('GET', self.source_endpoint, timeout=self.timeout,
                                      follow_redirects=False, headers={'Accept': 'application/json'}) as response:
            if response.status_code != 200:
                if response.status_code == 429:
                    retry = response.headers.get('retry-after', '')
                    delay = number(retry, 0, 86400)
                    if delay is None:
                        try:
                            delay = (parsedate_to_datetime(retry).astimezone(UTC)-now).total_seconds()
                        except (ValueError, TypeError, OverflowError, AttributeError):
                            delay = 60
                    self.retry_at = now+timedelta(seconds=max(60, min(delay, 86400)))
                response.raise_for_status()
                raise ValueError('Aircraft source unavailable')
            if response.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                raise ValueError('Aircraft response is not JSON')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body)+len(chunk) > MAX_BYTES:
                    raise ValueError('Aircraft response too large')
                body.extend(chunk)
            return json.loads(body)

    def normalize(self, payload, now):
        if not isinstance(payload, dict) or not isinstance(payload.get('ac'), list) or len(payload['ac']) > 10000:
            raise ValueError('Invalid aircraft snapshot')
        if payload.get('msg', 'No error') != 'No error':
            raise ValueError('Aircraft provider error')
        epoch_ms = number(payload.get('now'), 0, 1e14)
        if epoch_ms is None:
            raise ValueError('Missing aircraft snapshot time')
        observed = datetime.fromtimestamp(epoch_ms/1000, UTC)
        if observed > now+timedelta(seconds=30):
            raise ValueError('Aircraft snapshot time is in the future')
        if now-observed > timedelta(seconds=MAX_POSITION_AGE):
            raise ValueError('Aircraft snapshot is stale')
        items, seen = [], set()
        for aircraft in payload['ac']:
            if not isinstance(aircraft, dict):
                continue
            identity = label(aircraft.get('hex'), 7)
            if not identity or not re.fullmatch(r'~?[0-9a-fA-F]{6}', identity) or identity.lower() in seen:
                continue
            category = label(aircraft.get('category'))
            if (aircraft.get('alt_baro') == 'ground' or aircraft.get('type') == 'adsb_icao_nt'
                    or (category and category.upper().startswith(('B', 'C')))):
                continue
            lat, lon = number(aircraft.get('lat'), 49, 55), number(aircraft.get('lon'), 14, 24.3)
            age = number(aircraft.get('seen_pos'), 0, MAX_POSITION_AGE)
            if lat is None or lon is None or age is None or not in_poland(lat, lon):
                continue
            position_at = observed-timedelta(seconds=age)
            if not 0 <= (now-position_at).total_seconds() <= MAX_POSITION_AGE:
                continue
            altitude = number(aircraft.get('alt_baro'), -2000, 100000)
            speed = number(aircraft.get('gs'), 0, 3000)
            flags = aircraft.get('dbFlags')
            seen.add(identity.lower())
            items.append({'hex': identity.lower(), 'id': label(aircraft.get('flight')),
                          'registration': label(aircraft.get('r')), 'type_code': label(aircraft.get('t')),
                          'military': isinstance(flags, int) and not isinstance(flags, bool) and bool(flags & 1),
                          'latitude': lat, 'longitude': lon,
                          'altitude_m': round(altitude*0.3048) if altitude is not None else None,
                          'speed_kmh': round(speed*1.852, 1) if speed is not None else None,
                          'track': number(aircraft.get('track'), 0, 360),
                          'position_at': position_at.isoformat()})
        return items
