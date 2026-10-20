"""Warsaw bus positions from the authenticated, current city open-data portal."""
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from wici.buses import MAX_BYTES, MAX_POSITION_AGE, BusService, label
from wici.weather import number

BUSES_URL = 'https://dane.um.warszawa.pl/api/action/get_ztm_lokalizacja_pojazdow'
SOURCE_URL = 'https://dane.um.warszawa.pl/pl/datasets/f319f602-7292-4e8c-b3d1-f5898aa9a638'
WARSAW = ZoneInfo('Europe/Warsaw')


def position_time(value):
    """Convert local GPS time; never guess through an ambiguous DST hour."""
    if not isinstance(value, str) or len(value) != 19:
        raise ValueError('Invalid Warsaw GPS time')
    local = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    first, second = local.replace(tzinfo=WARSAW, fold=0), local.replace(tzinfo=WARSAW, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError('Ambiguous or nonexistent Warsaw GPS time')
    return first.astimezone(UTC)


class WarsawBusService(BusService):
    """Reuse shared cache, locking, conditional responses and backoff semantics."""

    def __init__(self, client, clock, key='', timeout=20, demo=False, enabled=True):
        super().__init__(client, clock, timeout=timeout, demo=demo, enabled=enabled)
        self.key = key.strip() if isinstance(key, str) else ''

    def base(self):
        return {**super().base(), 'source_name': 'ZTM Warszawa — dane.um.warszawa.pl',
                'source_url': SOURCE_URL}

    def snapshot(self, now, error=False):
        result = super().snapshot(now, error=error)
        if error:
            result['message'] = 'Dane ZTM Warszawa chwilowo niedostępne; pozycje mogą być nieaktualne.'
        return result

    async def fetch(self):
        if self.enabled and not self.demo and not self.key:
            return {**self.base(), 'enabled': False, 'status': 'unconfigured',
                    'message': 'Warszawa wymaga klucza API w sources.buses_warsaw.api_key.'}
        return await super().fetch()

    async def download(self, now):
        # The official API uses a raw token header and a POST for this read-only operation.
        # Credentials never enter request URLs, cache snapshots, or error messages.
        headers = {'Accept': 'application/json', 'Authorization': self.key}
        if self.etag:
            headers['If-None-Match'] = self.etag
        async with self.client.stream('POST', BUSES_URL, json={'type': 1}, headers=headers,
                                      timeout=self.timeout, follow_redirects=False) as response:
            if response.status_code == 304:
                return None, response.headers
            if response.status_code != 200:
                if response.status_code == 429:
                    self.rate_limit(response.headers, now)
                raise ValueError('Warsaw bus source unavailable')
            if response.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                raise ValueError('Warsaw bus response is not JSON')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body)+len(chunk) > MAX_BYTES:
                    raise ValueError('Warsaw bus response too large')
                body.extend(chunk)
            return json.loads(body), response.headers

    def normalize(self, payload, now):
        # The deployed service returns an array, while its documentation shows a result wrapper.
        rows = payload.get('result') if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError('Invalid Warsaw bus snapshot')
        items = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            vehicle = label(row.get('VehicleNumber'), 32)
            lat, lon = number(row.get('Lat'), 49, 55), number(row.get('Lon'), 14, 24.3)
            try:
                observed = position_time(row.get('Time'))
            except (ValueError, TypeError, OverflowError):
                continue
            if (not vehicle or lat is None or lon is None
                    or not 0 <= (now-observed).total_seconds() <= MAX_POSITION_AGE):
                continue
            identity = f'warszawa:{vehicle}'
            if identity in items and items[identity]['position_at'] >= observed.isoformat():
                continue
            items[identity] = {
                'id': identity, 'line': label(row.get('Lines'), 16), 'vehicle_number': vehicle,
                'model': None, 'operator': None, 'headsign': None,
                'latitude': lat, 'longitude': lon, 'speed_kmh': None, 'bearing': None,
                'delay_seconds': None, 'previous_stop': None, 'next_stop': None,
                'position_at': observed.isoformat(), 'low_floor': None,
            }
        return list(items.values())
