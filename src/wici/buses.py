"""On-demand ZDiTM Szczecin bus positions, shared across viewers without history."""
import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from wici.weather import number

BUSES_URL = 'https://www.zditm.szczecin.pl/api/v2/vehicles'
REFRESH_SECONDS = 10
MAX_POSITION_AGE = 120
MAX_BYTES = 4 * 1024 * 1024


def label(value, maximum=160):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= maximum and not any(ord(c) < 32 for c in value) else None


def mapping(value):
    return value if isinstance(value, dict) else {}


class BusService:
    def __init__(self, client, clock, timeout=10, demo=False, enabled=True):
        self.client, self.clock = client, clock
        self.timeout = min(timeout, 10)
        self.demo, self.enabled = demo, enabled
        self.lock = asyncio.Lock()
        self.cache = None
        self.retry_at = None
        self.etag = None

    def base(self):
        return {'items': [], 'status': 'ready', 'stale': False, 'fetched_at': None,
                'refresh_seconds': REFRESH_SECONDS, 'message': '', 'enabled': bool(self.enabled),
                'demo': self.demo, 'source_name': 'ZDiTM Szczecin',
                'source_url': 'https://www.zditm.szczecin.pl/pl/zditm/dla-programistow/api-pojazdy'}

    def snapshot(self, now, error=False):
        result = dict(self.cache[1]) if self.cache else self.base()
        result['items'] = [dict(item) for item in result['items'] if
                           0 <= (now-datetime.fromisoformat(item['position_at'])).total_seconds()
                           <= MAX_POSITION_AGE]
        if error:
            result.update(status='error', stale=bool(self.cache),
                          message='ZDiTM Szczecin chwilowo niedostępne; pozycje mogą być nieaktualne.')
        return result

    async def fetch(self):
        async with self.lock:
            now = self.clock().astimezone(UTC)
            if not self.enabled:
                return {**self.base(), 'status': 'disabled',
                        'message': 'Warstwa autobusów wyłączona w konfiguracji.'}
            if self.demo:
                return {**self.base(), 'message': 'Pozycje autobusów niedostępne w trybie demonstracyjnym.'}
            if self.cache and now < self.cache[0]:
                return self.snapshot(now)
            if self.retry_at and now < self.retry_at:
                return self.snapshot(now, error=True)
            try:
                payload, headers = await self.download(now)
                now = self.clock().astimezone(UTC)
                if payload is None:
                    if not self.cache:
                        raise ValueError('Unexpected bus source 304')
                    result = dict(self.cache[1])
                    result['fetched_at'] = now.isoformat()
                else:
                    result = {**self.base(), 'items': self.normalize(payload, now),
                              'fetched_at': now.isoformat()}
                control = headers.get('cache-control', '').lower()
                max_age = re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)', control)
                age = number(headers.get('age'), 0, 86400) or 0
                lifetime = max(REFRESH_SECONDS, min(int(max_age[1]), 86400)-age) if max_age else REFRESH_SECONDS
                if 'no-store' in control:
                    self.cache, self.etag, self.retry_at = None, None, None
                    return result
                if 'no-cache' in control:
                    lifetime = 0
                self.etag = headers.get('etag', self.etag if payload is None else None)
                self.cache = (now+timedelta(seconds=lifetime), result)
                self.retry_at = None
                return self.snapshot(now)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
                self.retry_at = max(self.retry_at or now, now+timedelta(seconds=60))
                return self.snapshot(now, error=True)

    def rate_limit(self, headers, now):
        delays = [60]
        retry = headers.get('retry-after', '')
        seconds = number(retry, 0, 86400)
        if seconds is not None:
            delays.append(seconds)
        else:
            try:
                delays.append((parsedate_to_datetime(retry).astimezone(UTC)-now).total_seconds())
            except (ValueError, TypeError, OverflowError, AttributeError):
                pass
        reset = number(headers.get('x-ratelimit-reset'), 0, 1e12)
        if reset is not None:
            delays.append(reset-now.timestamp())
        self.retry_at = now+timedelta(seconds=min(max(delays), 86400))

    async def download(self, now):
        headers = {'Accept': 'application/json'}
        if self.etag:
            headers['If-None-Match'] = self.etag
        async with self.client.stream('GET', BUSES_URL, timeout=self.timeout,
                                      follow_redirects=False, headers=headers) as response:
            if response.status_code == 304:
                return None, response.headers
            if response.status_code != 200:
                if response.status_code == 429:
                    self.rate_limit(response.headers, now)
                raise ValueError('Bus source unavailable')
            if response.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                raise ValueError('Bus response is not JSON')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body)+len(chunk) > MAX_BYTES:
                    raise ValueError('Bus response too large')
                body.extend(chunk)
            return json.loads(body), response.headers

    def normalize(self, payload, now):
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list) or len(payload['data']) > 10000:
            raise ValueError('Invalid bus snapshot')
        items, seen = [], set()
        for row in payload['data']:
            if not isinstance(row, dict):
                continue
            vehicle, position = mapping(row.get('vehicle')), mapping(row.get('position'))
            identity = vehicle.get('id')
            if (vehicle.get('type') != 'BUS' or not isinstance(identity, int)
                    or isinstance(identity, bool) or identity <= 0 or identity in seen):
                continue
            lat, lon = number(position.get('latitude'), 49, 55), number(position.get('longitude'), 14, 24.3)
            try:
                observed = datetime.fromisoformat(row['updated_at'])
                if observed.tzinfo is None:
                    continue
                observed = observed.astimezone(UTC)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                continue
            if lat is None or lon is None or not 0 <= (now-observed).total_seconds() <= MAX_POSITION_AGE:
                continue
            seen.add(identity)
            items.append({'id': f'szczecin:{identity}',
                          'line': label(mapping(row.get('line')).get('number'), 16),
                          'vehicle_number': label(vehicle.get('number'), 32),
                          'model': label(vehicle.get('model')), 'operator': label(vehicle.get('operator')),
                          'headsign': label(mapping(row.get('trip')).get('headsign')),
                          'latitude': lat, 'longitude': lon,
                          'speed_kmh': number(position.get('velocity'), 0, 200),
                          'bearing': number(position.get('bearing'), 0, 360),
                          'delay_seconds': number(mapping(row.get('delay')).get('seconds'), -86400, 86400),
                          'previous_stop': label(mapping(row.get('previous_stop')).get('name')),
                          'next_stop': label(mapping(row.get('next_stop')).get('name')),
                          'position_at': observed.isoformat(),
                          'low_floor': vehicle.get('low_floor') if isinstance(vehicle.get('low_floor'), bool) else None})
        return items


class CityBusService:
    """Independent on-demand providers: a failed city never blocks another city."""

    def __init__(self, client, clock, config, demo=False):
        from wici.buses_gtfs import GtfsBusService
        from wici.buses_warsaw import WarsawBusService

        enabled = config.enabled('buses')
        self.providers = {
            'szczecin': BusService(client, clock, config.timeout_seconds, demo=demo,
                                  enabled=enabled and config.enabled('buses_szczecin')),
            'krakow': GtfsBusService(client, clock, 'krakow', timeout=config.timeout_seconds, demo=demo,
                                    enabled=enabled and config.enabled('buses_krakow')),
            'poznan': GtfsBusService(client, clock, 'poznan', timeout=config.timeout_seconds, demo=demo,
                                    enabled=enabled and config.enabled('buses_poznan')),
            'warszawa': WarsawBusService(client, clock, key=config.warsaw_key(),
                                        timeout=config.timeout_seconds, demo=demo,
                                        enabled=enabled and config.enabled('buses_warsaw')),
        }

    async def fetch(self, city='szczecin'):
        if city not in self.providers:
            raise ValueError('Nieobsługiwane miasto')
        return {**await self.providers[city].fetch(), 'city': city}
