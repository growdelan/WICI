"""Shared NEPTUN civil warning snapshots and hooks for locally observed history."""
import asyncio
import copy
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

SOURCE_URL = 'https://neptun.in.ua/'
ALERTS_URL = SOURCE_URL + 'api/v1/alerts'
THREATS_URL = SOURCE_URL + 'api/v1/threats'
OBLASTS_URL = SOURCE_URL + 'oblasts.geojson'
RAIONS_URL = SOURCE_URL + 'raions.geojson'
REFRESH_SECONDS = 15
MAX_THREAT_AGE = 420
MAX_BYTES = 2 * 1024 * 1024
MAX_GEOMETRY_BYTES = 4 * 1024 * 1024
GEOMETRY_CACHE_SECONDS = 86400
MAX_REQUEST_SECONDS = 15


def label(value, maximum=256):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= maximum and not any(ord(c) < 32 for c in value) else None


def number(value, minimum, maximum, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if minimum <= value <= maximum and (not integer or isinstance(value, int)):
        return value
    return None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64 or 'T' not in value:
        raise ValueError('Nieprawidłowy czas NEPTUN.')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Brak strefy czasowej NEPTUN.')
    return result.astimezone(UTC)


def collection():
    return {'type': 'FeatureCollection', 'features': []}


class UkraineService:
    def __init__(self, client, clock, timeout=10, demo=False, enabled=True):
        self.client, self.clock = client, clock
        self.timeout = min(timeout, 10)
        self.demo, self.enabled = demo, enabled
        self.lock = asyncio.Lock()
        self.on_alerts = None
        self.on_geometry = None
        self.states = {key: {'data': None, 'expires': None, 'retry': None, 'failures': 0, 'error': None}
                       for key in ('alerts', 'threats', 'oblasts', 'raions')}

    def inactive(self):
        if not self.enabled:
            return 'disabled', 'Warstwa Ukrainy wyłączona w konfiguracji.'
        if self.demo:
            return 'demo_no_data', 'Brak danych NEPTUN w trybie demonstracyjnym.'
        return None, ''

    def component(self, key, now):
        state = self.states[key]
        result = copy.deepcopy(state['data']) if state['data'] else {
            'status': 'error', 'items': [], 'fetched_at': None, 'stale': False,
            'invalid_count': 0, 'stale_count': 0,
            ('updated_at' if key == 'alerts' else 'server_time'): None}
        result['error'] = state['error']
        if state['error']:
            result.update(status='error', stale=bool(state['data']))
        if key == 'threats':
            current = [item for item in result['items'] if
                       -30 <= (now-timestamp(item['updated_at'])).total_seconds() <= MAX_THREAT_AGE]
            removed = len(result['items']) - len(current)
            result['items'] = current
            result['stale_count'] += removed
            if removed and result['status'] == 'ready':
                result['status'] = 'partial'
        return result

    @staticmethod
    def overall_status(parts):
        statuses = [part['status'] for part in parts]
        if all(status == 'ready' for status in statuses):
            return 'ready'
        return 'error' if all(status == 'error' for status in statuses) else 'partial'

    def next_retry(self, keys, now):
        remaining = []
        for key in keys:
            state = self.states[key]
            next_at = state['retry'] or state['expires']
            if next_at:
                remaining.append(max(REFRESH_SECONDS, math.ceil((next_at-now).total_seconds())))
        return min(remaining, default=REFRESH_SECONDS)

    async def fetch(self):
        async with self.lock:
            now = self.clock().astimezone(UTC)
            inactive, message = self.inactive()
            if not inactive:
                await asyncio.gather(
                    self.refresh('alerts', ALERTS_URL, self.normalize_alerts, now),
                    self.refresh('threats', THREATS_URL, self.normalize_threats, now))
                now = self.clock().astimezone(UTC)
            alerts, threats = (self.component(key, now) for key in ('alerts', 'threats'))
            if inactive:
                for component in (alerts, threats):
                    component.update(status=inactive, items=[], stale=False, error=None)
            status = inactive or self.overall_status((alerts, threats))
            if not inactive and status != 'ready':
                message = 'Dane NEPTUN są częściowe lub niedostępne. Brak wpisów nie oznacza braku zagrożenia.'
            return {'status': status, 'demo': self.demo, 'refresh_seconds': REFRESH_SECONDS,
                    'retry_after_seconds': self.next_retry(('alerts', 'threats'), now), 'message': message,
                    'alerts': alerts, 'threats': threats, 'source_url': SOURCE_URL}

    async def fetch_alerts(self):
        """Share the Situation cache without downloading unrelated threat reports."""
        async with self.lock:
            now = self.clock().astimezone(UTC)
            inactive, message = self.inactive()
            if not inactive:
                await self.refresh('alerts', ALERTS_URL, self.normalize_alerts, now)
                now = self.clock().astimezone(UTC)
            alerts = self.component('alerts', now)
            if inactive:
                alerts.update(status=inactive, items=[], stale=False, error=None)
            return {'status': inactive or alerts['status'], 'demo': self.demo,
                    'refresh_seconds': REFRESH_SECONDS,
                    'retry_after_seconds': self.next_retry(('alerts',), now),
                    'message': message, 'alerts': alerts, 'source_url': SOURCE_URL}

    async def geometry(self):
        async with self.lock:
            now = self.clock().astimezone(UTC)
            inactive, message = self.inactive()
            if inactive:
                return {'status': inactive, 'oblasts': collection(), 'raions': collection(),
                        'message': message, 'fetched_at': None}
            await asyncio.gather(
                self.refresh('oblasts', OBLASTS_URL,
                             lambda payload, now: self.normalize_geometry(payload, 'region'), now,
                             ttl=GEOMETRY_CACHE_SECONDS, maximum=MAX_GEOMETRY_BYTES),
                self.refresh('raions', RAIONS_URL,
                             lambda payload, now: self.normalize_geometry(payload, 'rayon'), now,
                             ttl=GEOMETRY_CACHE_SECONDS, maximum=MAX_GEOMETRY_BYTES))
            parts = {}
            diagnostics = {}
            for key in ('oblasts', 'raions'):
                state = self.states[key]
                part = copy.deepcopy(state['data']) if state['data'] else {
                    'status': 'error', 'collection': collection(), 'fetched_at': None, 'invalid_count': 0}
                if state['error']:
                    part['status'] = 'error'
                parts[key] = part
                diagnostics[key] = {field: part[field] for field in ('status', 'fetched_at', 'invalid_count')}
                diagnostics[key].update(error=state['error'], stale=bool(state['data'] and state['error']))
            status = self.overall_status(parts.values())
            if status != 'ready':
                message = 'Granice Ukrainy są częściowo niedostępne; część alertów może nie pojawić się na mapie.'
            times = [part['fetched_at'] for part in parts.values() if part['fetched_at']]
            result = {'status': status, 'oblasts': parts['oblasts']['collection'],
                    'raions': parts['raions']['collection'], 'message': message,
                    'fetched_at': min(times) if times else None, 'sources': diagnostics,
                    'retry_after_seconds': self.next_retry(('oblasts', 'raions'), now)}
            if self.on_geometry is not None:
                await self.on_geometry(copy.deepcopy(result))
            return result

    async def refresh(self, key, url, normalizer, now, ttl=REFRESH_SECONDS, maximum=MAX_BYTES):
        state = self.states[key]
        if ((state['retry'] and now < state['retry']) or
                (not state['error'] and state['expires'] and now < state['expires'])):
            return
        try:
            async with asyncio.timeout(MAX_REQUEST_SECONDS):
                payload = await self.download(url, state, now, maximum)
            published_at = self.clock().astimezone(UTC)
            result = normalizer(payload, published_at)
            time_field = {'alerts': 'updated_at', 'threats': 'server_time'}.get(key)
            if (time_field and state['data']
                    and timestamp(result[time_field]) < timestamp(state['data'][time_field])):
                raise ValueError('NEPTUN snapshot time moved backwards')
            result.update(fetched_at=published_at.isoformat(), stale=False, error=None)
            state.update(data=result, expires=published_at+timedelta(seconds=ttl),
                         retry=None, failures=0, error=None)
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            state['failures'] += 1
            delay = min(60 * 2**min(state['failures']-1, 4), 900)
            state['retry'] = max(state['retry'] or now, self.clock().astimezone(UTC)+timedelta(seconds=delay))
            state['error'] = 'Nie udało się pobrać poprawnych danych NEPTUN.'
        if key == 'alerts' and self.on_alerts is not None:
            await self.on_alerts(self.component('alerts', self.clock().astimezone(UTC)))

    async def download(self, url, state, now, maximum):
        async with self.client.stream('GET', url, timeout=self.timeout, follow_redirects=False,
                                      headers={'Accept': 'application/json, application/geo+json'}) as response:
            if response.status_code != 200:
                if response.status_code == 429:
                    retry = response.headers.get('retry-after', '')
                    try:
                        delay = int(retry)
                    except (ValueError, TypeError, OverflowError):
                        try:
                            date = parsedate_to_datetime(retry)
                            delay = (date.astimezone(UTC)-now).total_seconds() if date.tzinfo else 60
                        except (ValueError, TypeError, OverflowError, AttributeError):
                            delay = 60
                    state['retry'] = now+timedelta(seconds=max(60, min(delay, 86400)))
                raise ValueError('NEPTUN unavailable')
            mime = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if mime not in ('application/json', 'application/geo+json'):
                raise ValueError('NEPTUN response is not JSON')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body)+len(chunk) > maximum:
                    raise ValueError('NEPTUN response too large')
                body.extend(chunk)
            return json.loads(body)

    @staticmethod
    def normalize_alerts(payload, now):
        if (not isinstance(payload, dict) or number(payload.get('version'), 0, 1e15, True) is None
                or any(not isinstance(payload.get(key), list) or len(payload[key]) > 1000
                       for key in ('raions', 'oblasts'))):
            raise ValueError('Invalid NEPTUN alerts')
        updated = timestamp(payload.get('updatedAt'))
        if updated > now+timedelta(seconds=30):
            raise ValueError('Future alert snapshot')
        items, seen, invalid = [], set(), 0
        for scope, source in (('raion', 'raions'), ('oblast', 'oblasts')):
            for raw in payload[source]:
                try:
                    if not isinstance(raw, dict):
                        raise TypeError('Invalid alert')
                    key, name, oblast = (label(raw.get(field)) for field in ('key', 'name', 'oblast'))
                    if not key or not name or (scope, key) in seen:
                        raise ValueError('Invalid alert identity')
                    if not oblast and (scope != 'oblast' or raw.get('oblast') not in (None, '')):
                        invalid += 1
                    try:
                        since = timestamp(raw.get('since'))
                        if since > now+timedelta(seconds=30):
                            raise ValueError('Future alert')
                        since = since.isoformat()
                    except (ValueError, TypeError, OverflowError):
                        since = None
                        invalid += 1
                    reasons = raw.get('reasons')
                    if reasons is None:
                        reasons = []
                    if not isinstance(reasons, list) or len(reasons) > 20:
                        raise ValueError('Invalid alert reasons')
                    reasons = [label(reason, 500) for reason in reasons]
                    if any(reason is None for reason in reasons):
                        raise ValueError('Invalid alert reason')
                    level = raw.get('level')
                    if level not in ('red', 'yellow'):
                        invalid += 1
                        level = 'unknown'
                    items.append({'scope': scope, 'key': key, 'name': name, 'oblast': oblast,
                                  'level': level, 'since': since, 'reasons': reasons})
                    seen.add((scope, key))
                except (ValueError, TypeError, OverflowError):
                    invalid += 1
        return {'status': 'partial' if invalid else 'ready', 'items': items,
                'updated_at': updated.isoformat(), 'source_version': payload['version'],
                'invalid_count': invalid, 'stale_count': 0}

    @staticmethod
    def normalize_threats(payload, now):
        if (not isinstance(payload, dict) or not label(payload.get('epoch'))
                or number(payload.get('seq'), 0, 1e15, True) is None
                or not isinstance(payload.get('threats'), list) or len(payload['threats']) > 5000):
            raise ValueError('Invalid NEPTUN threats')
        observed = timestamp(payload.get('serverTime'))
        if not -30 <= (now-observed).total_seconds() <= MAX_THREAT_AGE:
            raise ValueError('NEPTUN threat snapshot is stale or future')
        items, seen, invalid, stale_count = [], set(), 0, 0
        for raw in payload['threats']:
            try:
                if not isinstance(raw, dict):
                    raise TypeError('Invalid threat')
                identity, kind = label(raw.get('id'), 128), label(raw.get('type'), 64)
                status = raw.get('status')
                if not identity or not kind or identity in seen or status not in ('active', 'stale', 'resolved'):
                    raise ValueError('Invalid threat identity or status')
                seen.add(identity)
                if status == 'resolved':
                    continue
                updated = timestamp(raw.get('updatedAt'))
                age = (now-updated).total_seconds()
                if age < -30:
                    raise ValueError('Future threat')
                if status == 'stale' or age > MAX_THREAT_AGE:
                    stale_count += 1
                    continue
                if any(field in raw and not isinstance(raw[field], bool) for field in ('areaOnly', 'advisory')):
                    raise ValueError('Invalid threat flags')
                area_only, advisory = raw.get('areaOnly', False), raw.get('advisory', False)
                lat, lon = number(raw.get('lat'), 44, 53), number(raw.get('lon'), 22, 40.5)
                bad = False
                if area_only:
                    lat, lon = None, None
                elif lat is None or lon is None:
                    lat, lon, bad = None, None, True
                item = {'id': identity, 'type': kind, 'latitude': lat, 'longitude': lon,
                        'updated_at': updated.isoformat(), 'status': status,
                        'advisory': advisory, 'area_only': area_only}
                for output, source, maximum in [('title', 'title', 256), ('region', 'region', 256),
                                                 ('district', 'district', 256), ('locality', 'locality', 256),
                                                 ('description', 'explanationShort', 1000)]:
                    item[output] = label(raw.get(source), maximum)
                    if raw.get(source) not in (None, '') and item[output] is None:
                        bad = True
                for output, source, maximum, integer in [('uncertainty_km', 'uncertaintyKm', 1000, False),
                                                        ('source_count', 'sourceCount', 10000, True),
                                                        ('count', 'count', 10000, True)]:
                    item[output] = number(raw.get(source), 0, maximum, integer)
                    if raw.get(source) is not None and item[output] is None:
                        bad = True
                for output, source, values in [('position_quality', 'positionQuality', ('confirmed', 'approx')),
                                               ('confidence', 'confidenceLevel', ('high', 'medium', 'low'))]:
                    item[output] = raw.get(source) if raw.get(source) in values else 'unknown'
                    if raw.get(source) is not None and item[output] == 'unknown':
                        bad = True
                invalid += int(bad)
                items.append(item)
            except (ValueError, TypeError, OverflowError):
                invalid += 1
        return {'status': 'partial' if invalid or stale_count else 'ready', 'items': items,
                'server_time': observed.isoformat(), 'invalid_count': invalid, 'stale_count': stale_count}

    @staticmethod
    def normalize_geometry(payload, name_property):
        if (not isinstance(payload, dict) or payload.get('type') != 'FeatureCollection'
                or not isinstance(payload.get('features'), list) or not 0 < len(payload['features']) <= 512):
            raise ValueError('Invalid NEPTUN geometry')
        keys = Counter(label(feature['properties'].get('key')) for feature in payload['features']
                       if isinstance(feature, dict) and isinstance(feature.get('properties'), dict))
        features, invalid, points = [], 0, 0
        for feature in payload['features']:
            try:
                if not isinstance(feature, dict) or feature.get('type') != 'Feature':
                    raise ValueError('Invalid feature')
                props, geometry = feature.get('properties'), feature.get('geometry')
                if not isinstance(props, dict) or not isinstance(geometry, dict):
                    raise TypeError('Missing geometry')
                key = label(props.get('key'))
                name = label(props.get(name_property)) or label(props.get('name'))
                if (not key or not name or keys[key] > 1
                        or geometry.get('type') not in ('Polygon', 'MultiPolygon')):
                    raise ValueError('Invalid geometry identity')
                coordinates = geometry.get('coordinates')
                polygons = [coordinates] if geometry['type'] == 'Polygon' else coordinates
                if not isinstance(polygons, list) or not 0 < len(polygons) <= 1000:
                    raise ValueError('Invalid polygons')
                for polygon in polygons:
                    if not isinstance(polygon, list) or not 0 < len(polygon) <= 1000:
                        raise ValueError('Invalid polygon')
                    for ring in polygon:
                        if not isinstance(ring, list) or not 4 <= len(ring) <= 50000 or ring[0] != ring[-1]:
                            raise ValueError('Invalid ring')
                        points += len(ring)
                        if points > 250000:
                            raise ValueError('Too many vertices')
                        for point in ring:
                            if (not isinstance(point, list) or len(point) != 2
                                    or number(point[0], 21, 41) is None or number(point[1], 43, 54) is None):
                                raise ValueError('Invalid coordinate')
                features.append({'type': 'Feature', 'properties': {'key': key, name_property: name},
                                 'geometry': {'type': geometry['type'], 'coordinates': coordinates}})
            except (ValueError, TypeError, KeyError):
                invalid += 1
        if not features:
            raise ValueError('No valid geometry')
        return {'status': 'partial' if invalid else 'ready', 'collection': {
            'type': 'FeatureCollection', 'features': features}, 'invalid_count': invalid}
