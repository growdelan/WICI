"""On-demand IMGW hydrology snapshots, independently cached for each public JSON feed."""
import asyncio
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

from wici.weather import number, timestamp

URLS = {kind: f'https://danepubliczne.imgw.pl/api/data/{feed}/'
        for kind, feed in [('stations', 'hydro'), ('warnings', 'warningshydro')]}
REFRESH = 300
MAX_BYTES = 4 * 1024 * 1024
STALE_AFTER = 3 * 3600
WARSAW = ZoneInfo('Europe/Warsaw')
ATTRIBUTION = ('Źródło: IMGW-PIB. Dane Instytutu Meteorologii i Gospodarki Wodnej – '
               'Państwowego Instytutu Badawczego zostały przetworzone.')


def text(value, limit=20000):
    return value.strip()[:limit] if isinstance(value, str) else ''


def warning_time(value):
    """Warning JSON uses Polish civil time (confirmed against the publisher's TXT)."""
    value = text(value, 40)
    if not value or value.startswith('9999-'):
        return None
    try:
        date = datetime.fromisoformat(value)
        if date.tzinfo is not None:
            return date.astimezone(UTC)
        candidates = {date.replace(tzinfo=WARSAW, fold=fold).astimezone(UTC) for fold in (0, 1)
                      if date.replace(tzinfo=WARSAW, fold=fold).astimezone(UTC).astimezone(WARSAW)
                      .replace(tzinfo=None) == date}
        return candidates.pop() if len(candidates) == 1 else None
    except (ValueError, OverflowError):
        return None


def freshness(date, now):
    if date is None:
        return 'missing_time'
    age = (now-date).total_seconds()
    return 'future' if age < -900 else 'stale' if age > STALE_AFTER else 'fresh'


def stations(payload, now):
    items, seen, rejected = [], set(), 0
    for row in payload:
        if not isinstance(row, dict):
            rejected += 1
            continue
        identity, name = text(row.get('id_stacji'), 40), text(row.get('stacja'), 200)
        if not identity or not name or identity in seen:
            rejected += 1
            continue
        seen.add(identity)
        lat, lon = number(row.get('lat'), 48, 56), number(row.get('lon'), 13, 25)
        if lat is None or lon is None:
            lat = lon = None
        measurements = {}
        for key, field, time_field, unit, low, high in [
            ('water_level', 'stan_wody', 'stan_wody_data_pomiaru', 'cm', -1000, 10000),
            ('discharge', 'przeplyw', 'przeplyw_data', 'm³/s', 0, 100000),
            ('temperature', 'temperatura_wody', 'temperatura_wody_data_pomiaru', '°C', -5, 50),
        ]:
            value, date = number(row.get(field), low, high), timestamp(row.get(time_field))
            state = 'missing' if value is None else freshness(date, now)
            measurements[key] = {'value': value, 'unit': unit, 'observed_at': date.isoformat() if date else None,
                                 'source_time': text(row.get(time_field), 40) or None,
                                 'status': state, 'stale': state != 'fresh'}
        warning, alarm = (number(row.get(key), -1000, 10000) for key in ('stan_ostrzegawczy', 'stan_alarmowy'))
        level = measurements['water_level']
        threshold = 'unknown'
        if level['status'] == 'fresh':
            if alarm is not None and level['value'] >= alarm:
                threshold = 'alarm'
            elif warning is not None and level['value'] >= warning:
                threshold = 'warning'
            elif warning is not None:
                threshold = 'below_warning'
        items.append({'id': identity, 'name': name, 'river': text(row.get('rzeka'), 200),
                      'province': text(row.get('wojewodztwo'), 100), 'latitude': lat, 'longitude': lon,
                      'measurements': measurements, 'warning_level_cm': warning, 'alarm_level_cm': alarm,
                      'threshold_status': threshold})
    return items, rejected


def warnings(payload, now):
    items, seen, rejected = [], set(), 0
    for row in payload:
        if not isinstance(row, dict) or not text(row.get('zdarzenie')) or not text(row.get('przebieg')):
            rejected += 1
            continue
        identity = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        if identity in seen:
            continue
        seen.add(identity)
        start, end, published = (warning_time(row.get(k)) for k in ('data_od', 'data_do', 'opublikowano'))
        open_ended = text(row.get('data_do')).startswith('9999-')
        state = 'unknown'
        if start and (end or open_ended) and (end is None or end >= start):
            state = 'expired' if end and end <= now else 'upcoming' if start > now else 'active'
        areas = []
        for area in row.get('obszary', []) if isinstance(row.get('obszary'), list) else []:
            if isinstance(area, dict):
                codes = area.get('kod_zlewni', [])
                areas.append({'province': text(area.get('wojewodztwo'), 100), 'description': text(area.get('opis')),
                              'basin_codes': [text(c, 100) for c in codes if isinstance(c, str)]
                              if isinstance(codes, list) else []})
        severity = str(row.get('stopień', ''))
        items.append({'id': identity, 'number': text(row.get('numer'), 100), 'event': text(row.get('zdarzenie')),
                      'severity': int(severity) if severity in ('1', '2', '3') else None,
                      'severity_code': severity, 'description': text(row.get('przebieg')),
                      'comment': text(row.get('komentarz')), 'office': text(row.get('biuro')),
                      'probability_percent': number(row.get('prawdopodobienstwo'), 0, 100), 'areas': areas,
                      'published_at': published.isoformat() if published else None,
                      'valid_from': start.isoformat() if start else None, 'valid_until': end.isoformat() if end else None,
                      'source_valid_from': text(row.get('data_od'), 40),
                      'source_valid_until': text(row.get('data_do'), 40), 'open_ended': open_ended, 'status': state})
    return sorted(items, key=lambda item: (
        {'active': 0, 'upcoming': 1, 'unknown': 2, 'expired': 3}[item['status']],
        -(item['severity'] or 0), item['event'])), rejected


class HydroService:
    def __init__(self, client, clock, timeout=20, enabled=True, demo=False, history=None):
        self.client, self.clock, self.timeout, self.enabled, self.demo = client, clock, timeout, enabled, demo
        self.history = history
        self.locks = {kind: asyncio.Lock() for kind in URLS}
        self.cache, self.retry_at = {}, {}

    def base(self, kind):
        return {'kind': kind, 'enabled': bool(self.enabled), 'demo': self.demo, 'status': 'ready',
                'message': '', 'stale': False, 'fetched_at': None, 'items': [], 'rejected_count': 0,
                'source_url': URLS[kind], 'source_name': 'IMGW-PIB', 'attribution': ATTRIBUTION,
                'refresh_seconds': REFRESH, 'stale_after_seconds': STALE_AFTER,
                'time_basis': 'UTC (przyjęta konwencja pomiarów IMGW)' if kind == 'stations' else 'Europe/Warsaw'}

    def result(self, kind, cached, now, failed=False):
        result = self.base(kind)
        if cached:
            payload, fetched_at = cached
            items, rejected = (stations if kind == 'stations' else warnings)(payload, now)
            result.update(items=items, rejected_count=rejected, fetched_at=fetched_at.isoformat(),
                          status='partial' if rejected else 'ready' if items else 'empty')
            if rejected:
                result['message'] = f'Pominięto {rejected} nieprawidłowych rekordów.'
            if not items:
                result['message'] = ('Źródło zwróciło pusty wykaz ostrzeżeń.' if kind == 'warnings'
                                     else 'Źródło zwróciło pusty wykaz stacji.')
        if failed:
            result.update(status='error', stale=bool(cached), message=(
                'Źródło IMGW chwilowo niedostępne. Zachowano ostatni odczyt; aktualność niepotwierdzona.'
                if cached else 'Źródło IMGW chwilowo niedostępne; brak danych. Ponowna próba za kilka minut.'))
            if kind == 'stations':
                for item in result['items']:
                    item['threshold_status'] = 'unknown'
        return result

    async def fetch(self, kind='stations'):
        if kind not in URLS:
            raise ValueError('Nieprawidłowy rodzaj danych hydrologicznych')
        async with self.locks[kind]:
            now = self.clock().astimezone(UTC)
            if not self.enabled or self.demo:
                return {**self.base(kind), 'enabled': False, 'status': 'disabled',
                        'message': 'Hydrologia wyłączona w demonstracji.' if self.demo
                                   else 'Hydrologia wyłączona w konfiguracji.'}
            cached = self.cache.get(kind)
            if now < self.retry_at.get(kind, now):
                return self.result(kind, cached, now, failed=True)
            if cached and (now-cached[1]).total_seconds() < REFRESH:
                return self.result(kind, cached, now)
            try:
                payload = await self.download(kind, now)
                if not isinstance(payload, list) or len(payload) > 5000:
                    raise ValueError('Invalid hydrology list')
                items, _ = (stations if kind == 'stations' else warnings)(payload, now)
                if payload and not items:
                    raise ValueError('Unrecognized hydrology records')
                cached = self.cache[kind] = (payload, now)
                self.retry_at.pop(kind, None)
                result = self.result(kind, cached, now)
                if self.history is not None and kind == 'stations':
                    queued = self.history.submit('hydro:stations', result)
                    result['history_status'] = 'pending' if queued else 'error'
                return result
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
                self.retry_at[kind] = max(self.retry_at.get(kind, now), now+timedelta(seconds=REFRESH))
                result = self.result(kind, cached, now, failed=True)
                if self.history is not None and kind == 'stations':
                    self.history.report_failure('hydro:stations', result)
                return result

    async def download(self, kind, now):
        async with self.client.stream('GET', URLS[kind], timeout=self.timeout, follow_redirects=False,
                                      headers={'Accept': 'application/json'}) as response:
            if response.status_code != 200:
                if response.status_code == 429:
                    retry = response.headers.get('retry-after', '')
                    try:
                        delay = float(retry)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(retry).astimezone(UTC)-now).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            delay = REFRESH
                    delay = max(0, min(delay, 86400)) if math.isfinite(delay) else REFRESH
                    self.retry_at[kind] = now+timedelta(seconds=max(REFRESH, delay or REFRESH))
                raise ValueError('Hydrology source unavailable')
            if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                raise ValueError('Hydrology response is not JSON')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError('Hydrology response too large')
            return json.loads(body)
