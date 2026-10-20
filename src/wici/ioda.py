"""IODA v2 contract, bounded polling and neutral connectivity semantics.

Contract documentation: docs/ioda.md; synthetic regression cases: tests/fixtures/ioda. Never create events from
alerts, missing samples or transport failures. All remote strings are data.
"""
import asyncio
import hashlib
import json
import math
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import partial

import httpx

BASE = 'https://api.ioda.inetintel.cc.gatech.edu/v2/'
SITE = 'https://ioda.inetintel.cc.gatech.edu'
SIGNALS = {'bgp': 'Visible /24s', 'ping-slash24': 'Up /24s', 'merit-nt': 'Unique Source IPs'}
SIGNAL_MEANINGS = {
    'bgp': 'Liczba widocznych bloków IPv4 /24 w pomiarach BGP.',
    'ping-slash24': 'Liczba bloków IPv4 /24 uznanych za dostępne przez aktywne sondy IODA.',
    'merit-nt': 'Liczba unikalnych źródłowych adresów IP widzianych w teleskopie sieciowym.',
}
SCORE_UNIT = 'punkt IODA (spadek sygnału w % × minuty); nie odsetek użytkowników'
COPYRIGHT = 'This data is Copyright (c) 2021-2025 Georgia Tech Research Corporation. All Rights Reserved.'
# Reviewed against IODA country/PL metadata and local PRG province names.
REGIONS = {
 '3288': ('Warmian-Masurian', '28'), '3289': ('Pomeranian', '22'),
 '3290': ('Lower Silesian', '02'), '3291': ('West Pomeranian', '32'),
 '3292': ('Lubusz', '08'), '3293': ('Greater Poland', '30'),
 '3294': ('Kuyavian-Pomeranian', '04'), '3295': ('Silesian', '24'),
 '3296': ('Łódź', '10'), '3297': ('Masovian', '14'),
 '3298': ('Świętokrzyskie', '26'), '3299': ('Podlachian', '20'),
 '3300': ('Lublin', '06'), '3301': ('Subcarpathian', '18'),
 '3302': ('Opole', '16'), '3303': ('Lesser Poland', '12'),
}


class ContractError(ValueError):
    pass


class RateLimited(Exception):
    def __init__(self, delay):
        self.delay = delay


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ContractError('Nieprawidłowa liczba IODA')
    return value


def epoch(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value < 4102444800:
        raise ContractError('Nieprawidłowy czas IODA')
    return value


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def entity(item):
    if not isinstance(item, dict) or item.get('type') not in ('country', 'region', 'asn'):
        raise ContractError('Nieprawidłowa jednostka IODA')
    code, name = item.get('code'), item.get('name')
    if not isinstance(code, str) or not code or not isinstance(name, str) or not name:
        raise ContractError('Brak metadanych jednostki IODA')
    if item['type'] in ('region','asn') and not code.isdigit():
        raise ContractError('Nieprawidłowy kod jednostki IODA')
    if not isinstance(item.get('attrs'), dict):
        raise ContractError('Brak atrybutów jednostki IODA')
    return item['type'], code


def geometry_ref(item):
    kind, code = entity(item)
    if kind == 'country' and code == 'PL':
        return 'PL'
    mapping = REGIONS.get(code)
    if (kind == 'region' and mapping and item['name'] == mapping[0]
            and item['attrs'].get('country_code') == 'PL'):
        return mapping[1]
    return None


def envelope(payload, expected):
    if (not isinstance(payload, dict) or payload.get('type') != expected
            or payload.get('error') is not None or not isinstance(payload.get('data'), list)
            or not isinstance(payload.get('metadata'), dict)):
        raise ContractError('Niezgodna odpowiedź IODA')
    return payload['data']


def parse_alert(raw):
    kind, code = entity(raw['entity'])
    signal, method = raw['datasource'], raw['method']
    if not isinstance(signal, str) or not isinstance(method, str) or not isinstance(raw['level'], str):
        raise ContractError('Nieprawidłowy alert IODA')
    at = epoch(raw['time'])
    for field in ('value', 'historyValue'):
        number(raw[field])
    return {'id': identity(kind, code, signal, method, at), 'entity_type': kind,
            'entity_code': code, 'datasource': signal, 'method': method, 'measured_at': at, 'raw': raw}


def parse_event(raw):
    kind, code = entity(raw['entity'])
    start, until = epoch(raw['from']), epoch(raw['until'])
    if until < start:
        raise ContractError('Odwrócony czas zdarzenia IODA')
    signal, method = raw['datasource'], raw['method']
    if not isinstance(signal, str) or not isinstance(method, str) or not raw.get('alerts'):
        raise ContractError('Brak sygnału lub alertów IODA')
    alerts = [parse_alert(a) for a in raw['alerts']]
    if any((a['entity_type'], a['entity_code'], a['datasource'], a['method']) !=
           (kind, code, signal, method) or not start <= a['measured_at'] <= until for a in alerts):
        raise ContractError('Niezgodne alerty zdarzenia IODA')
    # API may synthesize `until` at the query boundary. Only a normal alert
    # at that time confirms a source-reported end; absence is never recovery.
    ended = until if any(a['measured_at'] == until and a['raw']['level'] == 'normal' for a in alerts) else None
    return {'id': identity(kind, code, signal, method, start), 'entity_type': kind, 'entity_code': code,
            'name': raw['entity']['name'], 'datasource': signal, 'method': method,
            'started_at': start, 'source_until': until, 'ended_at': ended,
            'score': number(raw['score']), 'measured_at': max(a['measured_at'] for a in alerts), 'raw': raw}


def parse_signals(payload):
    series = []
    for group in envelope(payload, 'signals'):
        if not isinstance(group, list):
            raise ContractError('Niezgodne grupy sygnałów IODA')
        for raw in group:
            kind, code, signal = raw['entityType'], raw['entityCode'], raw['datasource']
            if kind not in ('country', 'region', 'asn') or not isinstance(code, str) or signal not in SIGNALS:
                raise ContractError('Nieznany sygnał IODA')
            start, until = epoch(raw['from']), epoch(raw['until'])
            step, native = raw['step'], raw['nativeStep']
            if (not isinstance(step, int) or not isinstance(native, int) or not 0 < native <= step
                    or until < start or not isinstance(raw['values'], list) or len(raw['values']) > 600):
                raise ContractError('Nieprawidłowa siatka czasowa IODA')
            for i, value in enumerate(raw['values']):
                if value is not None:
                    number(value)
                at = start + step*i
                if at > until:
                    raise ContractError('Próbka poza zakresem serii')
                series.append({'entity_type': kind, 'entity_code': code, 'datasource': signal,
                                   'measured_at': at, 'step': step, 'native_step': native, 'value': value})
    return series


def retry_after(value, now):
    try:
        return max(0, min(86400, int(value)))
    except (ValueError, TypeError):
        try:
            return max(0, min(86400, int((parsedate_to_datetime(value)-now).total_seconds())))
        except (ValueError, TypeError, OverflowError):
            return 600


class Collector:
    """One sequential run, <=60 requests, <=3 pages per dataset, 48h overlap.

    Metadata is cached durably for 24h. No world enumeration. 429 stops the
    run immediately. Successful pages are committed before later failures.
    """
    def __init__(self, repo, client, config):
        self.repo, self.client, self.config = repo, client, config
        self.errors, self.requests, self.changed, self.retry = [], 0, 0, 0
        self.now = repo.clock()
        self.start = int((self.now-timedelta(hours=48)).timestamp())
        self.end = int(self.now.timestamp())
        self.allowed = set()
        self.coverage = []
        self.valid_signals = set()
        self.signal_checks = {}

    async def get(self, path, params, expected):
        if self.requests >= 60:
            raise ContractError('Limit 60 zapytań IODA')
        self.requests += 1
        async with self.client.stream('GET', BASE+path, params=params,
                                      timeout=self.config.timeout_seconds) as response:
            if response.status_code == 429:
                raise RateLimited(retry_after(response.headers.get('Retry-After'), self.now))
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > min(self.config.max_response_bytes, 4_000_000):
                    raise ContractError('Przekroczono limit rozmiaru IODA')
            payload = json.loads(content)
        data = envelope(payload, expected)
        return data, {'url': str(response.url), 'metadata': payload['metadata'],
                      'copyright': payload.get('copyright'), 'requestParameters': payload.get('requestParameters')}

    def failed(self, label, exc):
        reason = str(exc) if isinstance(exc, ContractError) else type(exc).__name__
        self.errors.append(f'{label}: {reason}')

    async def pages(self, path, params, expected, consume, limit=100):
        for page in range(3):
            data, provenance = await self.get(path, dict(params, limit=limit, page=page), expected)
            consume(data, provenance)
            if len(data) < limit:
                return
        raise ContractError('Osiągnięto limit 3 stron IODA; zakres niepełny')

    async def metadata(self):
        cached = self.repo.ioda_metadata()
        groups = [('country', 'PL', None), ('region', None, None)]
        groups += [('asn', None, str(code)) for code in self.config.ioda_asns()]
        selected = []
        for kind, code, search in groups:
            old = [r for r in cached if r['type'] == kind and (not code or r['code'] == code)
                   and (not search or r['code'] == search)]
            fresh = old and all((self.now-datetime.fromisoformat(r['_verified_at'])).total_seconds() < 86400
                                for r in old)
            if fresh:
                selected.extend(old)
                continue
            found = []
            params = {'entityType': kind}
            if code:
                params['entityCode'] = code
            else:
                params['relatedTo'] = 'country/PL'
            if search:
                params['search'] = search
            def consume(rows, provenance, kind=kind, code=code, search=search, found=found):
                for r in rows:
                    t, c = entity(r)
                    if t != kind or (code and c != code):
                        raise ContractError('Jednostka poza zakresem metadanych')
                    if kind == 'region' and r['attrs'].get('country_code') != 'PL':
                        raise ContractError('Region poza Polską')
                    if search and c != search:
                        continue
                    found.append(r)
            try:
                await self.pages('entities/query', params, 'entities.lookup', consume)
                if not found:
                    raise ContractError('Brak potwierdzenia jednostki country/PL')
                self.repo.save_ioda_metadata(found)
                selected.extend(found)
            except RateLimited:
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                self.failed(f'metadata/{kind}/{search or code or "PL"}', exc)
                selected.extend(found or old)
        self.allowed = {entity(r) for r in selected}
        return selected

    def consume_events(self, rows, provenance, scope=None):
        for raw in rows:
            try:
                item = parse_event(raw)
                if (item['entity_type'], item['entity_code']) not in (scope or self.allowed):
                    raise ContractError('Zdarzenie poza wybranym zakresem')
                self.changed += self.repo.save_ioda_events([item], provenance)
            except (KeyError, ValueError, TypeError) as exc:
                self.failed('event', exc)

    def consume_alerts(self, rows, provenance, scope=None):
        for raw in rows:
            try:
                item = parse_alert(raw)
                if (item['entity_type'], item['entity_code']) not in (scope or self.allowed):
                    raise ContractError('Alert poza wybranym zakresem')
                self.repo.save_ioda_alerts([item], provenance)
            except (KeyError, ValueError, TypeError) as exc:
                self.failed('alert', exc)

    async def run(self):
        try:
            try:
                rows, _ = await self.get('datasources/', {}, 'datasources')
                available = {r['datasource']: r['units'] for r in rows}
                self.valid_signals = {k for k,v in SIGNALS.items() if available.get(k)==v}
                if self.valid_signals != set(SIGNALS):
                    raise ContractError('Zmiana jednostek sygnałów IODA')
            except RateLimited:
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                self.failed('datasources', exc)
            entities = await self.metadata()
            for kind in ('country', 'region', 'asn'):
                codes = sorted({r['code'] for r in entities if r['type'] == kind})
                if not codes:
                    continue
                params = {'entityType': kind, 'entityCode': ','.join(codes),
                          'from': self.start, 'until': self.end, 'extendWindow': 1209600}
                for path, consume in [('events', self.consume_events), ('alerts', self.consume_alerts)]:
                    extra = {'format': 'ioda', 'includeAlerts': 'true', 'overall': 'false',
                             'orderBy': 'time/asc'} if path == 'events' else {}
                    try:
                        await self.pages('outages/'+path, dict(params, **extra), 'outages.'+path,
                                         partial(consume, scope={(kind,c) for c in codes}))
                        self.coverage.append(f'{kind}/{path}')
                    except RateLimited:
                        raise
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        self.failed(f'{kind}/{path}', exc)
                for signal in SIGNALS:
                    if signal not in self.valid_signals:
                        for code in codes:
                            self.signal_checks[f'{kind}/{code}/{signal}'] = {'result':'error','measurement_at':None}
                        continue
                    try:
                        path = f'signals/raw/{kind}/{",".join(codes)}'
                        rows, provenance = await self.get(path, {'from': self.start, 'until': self.end,
                                                                 'datasource': signal, 'maxPoints': 288}, 'signals')
                        samples = parse_signals({'type': 'signals', 'error': None, 'metadata': {}, 'data': rows})
                        if any(s['entity_type'] != kind or s['entity_code'] not in codes
                               or s['datasource'] != signal for s in samples):
                            raise ContractError('Sygnały poza zakresem')
                        for code in codes:
                            latest = max((s['measured_at'] for s in samples if s['entity_code']==code
                                          and s['value'] is not None and s['measured_at']<=self.end),default=None)
                            self.signal_checks[f'{kind}/{code}/{signal}'] = {'result':'success','measurement_at':latest}
                        self.repo.save_ioda_samples([s for s in samples if s['measured_at'] <= self.end], provenance)
                        self.coverage.append(f'{kind}/{signal}')
                    except RateLimited:
                        raise
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        self.failed(f'{kind}/{signal}', exc)
                        for code in codes:
                            self.signal_checks[f'{kind}/{code}/{signal}'] = {'result':'error','measurement_at':None}
        except asyncio.CancelledError:
            self.errors.append('Odczyt IODA przerwany podczas zatrzymania')
            raise
        except RateLimited as exc:
            self.retry = exc.delay
            self.failed('HTTP429 Retry-After', exc)
        finally:
            result = 'partial' if self.errors and self.coverage else 'error' if self.errors else 'success'
            summary = {'result': result, 'errors': self.errors, 'coverage': self.coverage,
                       'retry_after_seconds': self.retry, 'signal_checks': self.signal_checks, 'requests': self.requests, 'window_start': self.start, 'window_end': self.end,
                       'entities': sorted('/'.join(v) for v in self.allowed), 'at': self.now.isoformat()}
            self.repo.save_ioda_run(summary)
        return summary
