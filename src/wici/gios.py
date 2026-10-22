"""On-demand GIOŚ v1 JSON-LD with an optional local observation archive."""
import asyncio
import copy
import json
import math
from collections import OrderedDict, deque
from datetime import UTC, timedelta
from email.utils import parsedate_to_datetime

import httpx

from wici.hydro import warning_time
from wici.weather import number

BASE = 'https://api.gios.gov.pl/pjp-api/v1/rest/'
SOURCE = 'https://powietrze.gios.gov.pl/pjp/content/api'
ATTRIBUTION = ('Źródło danych: GIOŚ - EKOINFONET. Państwowy Monitoring Środowiska. '
               'Wybrane stacje i stanowiska; przetworzono format i czas. '
               'Wyniki niezweryfikowane, mogą ulec zmianie.')
FIELDS = {'stations': 'Lista stacji pomiarowych', 'sensors': 'Lista stanowisk pomiarowych dla podanej stacji',
          'data': 'Lista danych pomiarowych', 'index': 'AqIndex'}
PATHS = {'stations': 'station/findAll', 'sensors': 'station/sensors/', 'data': 'data/getData/',
         'index': 'aqindex/getIndex/'}
TTL = {'stations': 86400, 'sensors': 21600, 'data': 1800, 'index': 1800}
PARAMETERS = ('PM10', 'PM2.5', 'NO2', 'SO2', 'O3', 'CO', 'C6H6')
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 20
STALE_AFTER = 3 * 3600


def source_time(raw):
    date = warning_time(raw)
    return {'source_time': raw if isinstance(raw, str) else None,
            'observed_at': date.isoformat() if date else None,
            'time_status': 'resolved' if date else 'ambiguous_or_invalid'}


def age(item, now):
    date = warning_time(item.get('observed_at'))
    seconds = (now-date).total_seconds() if date else None
    return {**item, 'age_seconds': seconds,
            'freshness': 'unknown_time' if seconds is None else 'future' if seconds < -900
            else 'stale' if seconds > STALE_AFTER else 'fresh'}


def normalize(kind, rows):
    items, rejected, seen = [], 0, set()
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise TypeError()
            if kind in ('stations', 'sensors'):
                identity = row['Identyfikator stacji' if kind == 'stations' else 'Identyfikator stanowiska']
                if type(identity) is not int or identity <= 0 or identity in seen:
                    raise ValueError()
                seen.add(identity)
                if kind == 'stations':
                    name = row['Nazwa stacji']
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError()
                    lat, lon = number(row.get('WGS84 φ N'), -90, 90), number(row.get('WGS84 λ E'), -180, 180)
                    if lat is None or lon is None:
                        lat = lon = None
                    item = {'id': identity, 'name': name[:300], 'latitude': lat, 'longitude': lon,
                            'address': ', '.join(str(row[k]) for k in ('Nazwa miasta', 'Ulica') if row.get(k)),
                            'code': row.get('Kod stacji'), 'province': row.get('Województwo')}
                else:
                    code = row['Wskaźnik - kod']
                    if not isinstance(code, str):
                        raise ValueError()
                    item = {'id': identity, 'station_id': row['Identyfikator stacji'],
                            'parameter': code.replace(',', '.'), 'name': row.get('Wskaźnik', code),
                            'measurement_type': 'unknown', 'unit': 'µg/m³'}
            elif kind == 'data':
                if 'Data' not in row or 'Wartość' not in row:
                    raise ValueError()
                value = row['Wartość']
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise ValueError()
                item = {**source_time(row['Data']), 'value': value, 'unit': 'µg/m³',
                        'station_code': row.get('Kod stanowiska'),
                        'status': 'missing' if value is None else 'value'}
            else:
                if 'Wartość indeksu' not in row or 'Identyfikator stacji pomiarowej' not in row:
                    raise ValueError()
                value = row['Wartość indeksu']
                valid = type(value) is int and 0 <= value <= 5 and row.get(
                    'Status indeksu ogólnego dla stacji pomiarowej') is True
                item = {**source_time(row.get('Data danych źródłowych, z których policzono wartość indeksu dla wskaźnika st')),
                        'value': value if valid else None,
                        'name': row.get('Nazwa kategorii indeksu') if valid else 'Brak indeksu',
                        'calculated': source_time(row.get('Data wykonania obliczeń indeksu')),
                        'status': 'value' if valid else 'missing'}
            items.append(item)
        except (KeyError, ValueError, TypeError, OverflowError):
            rejected += 1
    if rows and not items:
        raise ValueError('Unrecognized v1 schema')
    return items, rejected


class GiosUnavailable(ValueError):
    pass


class GiosResourceUnavailable(GiosUnavailable):
    """A client error for one resource must not disable unrelated resources."""


class GiosPartial(GiosUnavailable):
    def __init__(self, kind, rows):
        self.items, self.rejected = normalize(kind, rows)
        super().__init__('Incomplete pagination')


class GiosService:
    def __init__(self, client, clock, timeout=20, enabled=True, demo=False, history=None):
        self.client, self.clock = client, clock
        self.timeout, self.enabled, self.demo = min(timeout, 30), enabled, demo
        self.cache = OrderedDict()
        self.locks = [asyncio.Lock() for _ in range(32)]
        self.semaphore = asyncio.Semaphore(4)
        self.rate_lock = asyncio.Lock()
        self.requests = {k: deque() for k in FIELDS}
        self.retry_at, self.failures = {}, {}
        self.resource_failures = OrderedDict()
        self.history = history

    def archive(self, kind, identity, result, failure=False):
        if self.history is not None:
            resource = 'gios:' + kind + (':' + str(identity) if identity is not None else '')
            queued = (self.history.report_failure(resource, result) if failure
                      else self.history.submit(resource, result))
            result['history_status'] = 'pending' if queued else 'error'
        return result

    def defer(self, kind, deadline):
        self.retry_at[kind] = max(self.retry_at.get(kind, deadline), deadline)

    def defer_resource(self, key, now):
        previous, failures = self.resource_failures.get(key, (now, 0))
        failures = min(failures+1, 6)
        deadline = max(previous, now+timedelta(seconds=min(300 * 2**(failures-1), 3600)))
        self.resource_failures[key] = (deadline, failures)
        self.resource_failures.move_to_end(key)
        while len(self.resource_failures) > 1024:
            self.resource_failures.popitem(last=False)

    def result(self, kind, cached=None, failed=False):
        now = self.clock().astimezone(UTC)
        result = {'kind': kind, 'enabled': self.enabled and not self.demo, 'demo': self.demo,
                  'status': 'error' if failed else 'empty', 'stale': bool(failed and cached),
                  'items': [], 'fetched_at': None, 'message': '', 'source_url': SOURCE,
                  'attribution': ATTRIBUTION, 'refresh_seconds': TTL[kind],
                  'stale_after_seconds': STALE_AFTER, 'time_basis': 'Europe/Warsaw (czas lokalny GIOŚ)'}
        if cached:
            payload, fetched = cached
            result.update(copy.deepcopy(payload), fetched_at=fetched.isoformat())
            result['items'] = [age(item, now) if kind in ('data', 'index') else item for item in result['items']]
            result['stale'] = failed or (now-fetched).total_seconds() > TTL[kind]*2
        if kind == 'data':
            valid = [i for i in result['items'] if i['value'] is not None and i['observed_at'] is not None]
            result['latest'] = max(valid, key=lambda i: i['observed_at'], default=None)
            result['unresolved_value_count'] = sum(i['value'] is not None and i['observed_at'] is None
                                                   for i in result['items'])
            if result['items'] and not result['latest'] and result['status'] == 'ready':
                result['status'] = 'missing'
        if failed:
            result.update(status='error', message='GIOŚ chwilowo niedostępne. Zachowano ostatnie poprawne dane.'
                          if cached else 'GIOŚ chwilowo niedostępne; brak danych. Spróbuj później.')
        if not result['enabled']:
            result.update(status='disabled', message='GIOŚ wyłączone w demonstracji.' if self.demo
                          else 'GIOŚ wyłączone w konfiguracji.')
        result['service_retry_after_seconds'] = max(0, (self.retry_at.get(kind, now)-now).total_seconds())
        return result

    async def fetch(self, kind='stations', identity=None):
        if kind not in FIELDS or (kind != 'stations' and (type(identity) is not int or identity <= 0)):
            raise ValueError('Nieprawidłowy zasób GIOŚ')
        if not self.enabled or self.demo:
            return self.result(kind)
        key = (kind, identity)
        async with self.locks[hash(key) % len(self.locks)]:
            now = self.clock().astimezone(UTC)
            cached = self.cache.get(key)
            if cached:
                self.cache.move_to_end(key)
            if now < self.retry_at.get(kind, now):
                return self.result(kind, cached, True)
            if key in self.resource_failures and now < self.resource_failures[key][0]:
                return self.result(kind, cached, True)
            lifetime = 86400 if cached and cached[0]['status'] == 'manual' else TTL[kind]
            if cached and (now-cached[1]).total_seconds() < lifetime:
                return self.result(kind, cached)
            try:
                async with asyncio.timeout(60):
                    payload = await self.download(kind, identity)
                if cached and payload['status'] == 'partial':
                    self.defer_resource(key, now)
                    self.archive(kind, identity, self.result(kind, (payload, self.clock().astimezone(UTC))))
                    result = self.result(kind, cached, True)
                    result.update(status='partial', message='Nieprawidłowe rekordy GIOŚ; zachowano poprzedni odczyt.')
                    return result
                self.cache[key] = (payload, self.clock().astimezone(UTC))
                while len(self.cache) > 1024:
                    self.cache.popitem(last=False)
                self.failures[kind] = 0
                self.resource_failures.pop(key, None)
                return self.archive(kind, identity, self.result(kind, self.cache[key]))
            except GiosPartial as exc:
                self.defer_resource(key, now)
                payload = {'items': exc.items, 'status': 'partial', 'rejected_count': exc.rejected,
                           'message': 'Niepełna paginacja GIOŚ — dostępny tylko fragment odpowiedzi.'}
                partial = self.archive(kind, identity, self.result(kind, (payload, now)))
                if cached:
                    result = self.result(kind, cached, True)
                    result.update(status='partial', message='Niepełna paginacja GIOŚ; zachowano poprzedni odczyt.')
                    return result
                result = partial
                result['stale'] = True
                return result
            except GiosResourceUnavailable:
                self.defer_resource(key, now)
                return self.archive(kind, identity, self.result(kind, cached, True), failure=True)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError, TimeoutError):
                self.failures[kind] = min(self.failures.get(kind, 0)+1, 6)
                self.defer(kind, now+timedelta(seconds=min(300 * 2**(self.failures[kind]-1), 3600)))
                return self.archive(kind, identity, self.result(kind, cached, True), failure=True)

    async def reserve(self, kind):
        async with self.rate_lock:
            now = self.clock().astimezone(UTC)
            if now < self.retry_at.get(kind, now):
                raise GiosUnavailable('Backoff')
            queue = self.requests[kind]
            while queue and (now-queue[0]).total_seconds() >= 60:
                queue.popleft()
            # GIOŚ: stations 2/min; other three services 1500/min. Conservative local cap 120/min.
            if len(queue) >= (2 if kind == 'stations' else 120):
                self.defer(kind, queue[0]+timedelta(seconds=60))
                raise GiosUnavailable('Rate limit')
            queue.append(now)

    async def download(self, kind, identity):
        rows, total = [], None
        path = BASE+PATHS[kind]+('' if kind == 'stations' else str(identity))
        async with self.semaphore:
            try:
                for page in range(MAX_PAGES):
                    await self.reserve(kind)
                    async with self.client.stream('GET', path, params={'page': page, 'size': 500},
                                                  headers={'Accept': 'application/ld+json'},
                                                  timeout=self.timeout, follow_redirects=False) as response:
                        if response.status_code == 429:
                            retry = response.headers.get('retry-after', '')
                            now = self.clock().astimezone(UTC)
                            try:
                                seconds = float(retry)
                                if not math.isfinite(seconds):
                                    raise ValueError()
                            except ValueError:
                                try:
                                    seconds = (parsedate_to_datetime(retry).astimezone(UTC)-now).total_seconds()
                                except (ValueError, TypeError, OverflowError):
                                    seconds = 300
                            self.defer(kind, now+timedelta(seconds=max(300, seconds)))
                            raise GiosUnavailable('Rate limited by source')
                        failure = (GiosResourceUnavailable if 400 <= response.status_code < 500
                                   else GiosUnavailable)
                        if response.status_code not in (200, 400):
                            raise failure('Source failure')
                        content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                        if content_type not in ('application/json', 'application/ld+json'):
                            raise failure('Not JSON')
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                raise failure('Response too large')
                        try:
                            payload = json.loads(body)
                        except ValueError:
                            raise failure('Invalid JSON') from None
                        # This documented v1 error identifies manual sensors; never infer from empty/null values.
                        if (kind == 'data' and isinstance(payload, dict)
                                and payload.get('error_code') == 'API-ERR-100003'
                                and 'manualnego' in payload.get('error_reason', '')):
                            return {'status': 'manual', 'items': [], 'rejected_count': 0,
                                    'message': 'Stanowisko manualne — brak bieżących godzinowych wyników.'}
                        if response.status_code != 200 or not isinstance(payload, dict):
                            raise failure('Source failure')
                        count = payload.get('totalPages')
                        if type(count) is not int or not 0 <= count <= MAX_PAGES or (total is not None and count != total):
                            raise GiosUnavailable('Invalid pagination')
                        total = count
                        part = payload[FIELDS[kind]]
                        if kind == 'index':
                            part = [part] if isinstance(part, dict) else part
                        if not isinstance(part, list) or len(part) > 500:
                            raise GiosUnavailable('Invalid page')
                        rows.extend(part)
                        if page+1 >= total:
                            items, rejected = normalize(kind, rows)
                            return {'items': items, 'rejected_count': rejected,
                                    'status': 'partial' if rejected else 'ready' if items else 'empty',
                                    'message': f'Pominięto {rejected} nieprawidłowych rekordów.' if rejected
                                    else '' if items else 'Źródło zwróciło pusty wynik.'}
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError, TimeoutError):
                if rows:
                    raise GiosPartial(kind, rows) from None
                raise
        raise GiosUnavailable('Page limit')
