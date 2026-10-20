"""Shared PolishTrainsGTFS data and explicitly estimated positions, without GPS."""
import asyncio
import csv
import io
import json
import math
import zipfile
import zlib
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from wici.train_positions import CACHE_SECONDS, VALID_SECONDS, PositionEstimator, distance

STATIC_URL = 'https://mkuran.pl/gtfs/polish_trains.zip'
UPDATES_URL = 'https://mkuran.pl/gtfs/polish_trains/updates.json'
REFRESH_SECONDS = 120
STATIC_SECONDS = 21600
STALE_SECONDS = 600
MAX_BYTES = 48 * 1024 * 1024
MAX_UNPACKED = 240 * 1024 * 1024
WARSAW = ZoneInfo('Europe/Warsaw')


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except ValueError:
        return None


def seconds(value):
    if not value:
        return None
    hour, minute, second = map(int, value.split(':'))
    if not (0 <= hour <= 71 and 0 <= minute < 60 and 0 <= second < 60):
        raise ValueError('Invalid GTFS time')
    return hour * 3600 + minute * 60 + second


def service_time(day, value):
    """GTFS service day is noon minus 12h, including local DST transition days."""
    if value is None:
        return None
    noon = datetime.combine(day, datetime.min.time().replace(hour=12), WARSAW).astimezone(UTC)
    return noon + timedelta(seconds=value - 43200)


def iso(value):
    return value.isoformat() if value is not None else None


class Timetable:
    def __init__(self, body):
        self.stations, self.stops, self.trips = {}, {}, {}
        self.times = defaultdict(list)
        self.at_station = defaultdict(list)
        self.calendar, self.exceptions = {}, {}
        self.shapes = defaultdict(list)
        self.shape_cache = OrderedDict()
        self.valid_until = None
        self.by_number = defaultdict(list)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            entries = archive.infolist()
            if len(entries) > 40 or sum(x.file_size for x in entries) > MAX_UNPACKED:
                raise ValueError('GTFS archive too large')
            names = [x.filename for x in entries]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate GTFS files')
            def rows(name):
                if name not in names:
                    return []
                return csv.DictReader(io.TextIOWrapper(archive.open(name), encoding='utf-8-sig', newline=''))
            required = {'stops.txt', 'trips.txt', 'routes.txt', 'stop_times.txt'}
            if not required.issubset(names) or not {'calendar.txt', 'calendar_dates.txt'}.intersection(names):
                raise ValueError('Incomplete GTFS archive')
            for row in rows('stops.txt'):
                lat, lon = float(row['stop_lat']), float(row['stop_lon'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                self.stops[row['stop_id']] = {
                    'id': row['stop_id'], 'name': row['stop_name'][:180], 'latitude': lat, 'longitude': lon,
                    'parent': row.get('parent_station') or row['stop_id'], 'country': row.get('country', ''),
                    'location_type': row.get('location_type', ''),
                }
            for stop in self.stops.values():
                parent = self.stops.get(stop['parent'], stop)
                if ((parent['country'] == 'PL' or (not parent['country'] and
                      49 <= parent['latitude'] <= 55 and 14 <= parent['longitude'] <= 24.3))
                        and parent['location_type'] in ('', '0', '1')):
                    self.stations[parent['id']] = {k: parent[k] for k in ('id', 'name', 'latitude', 'longitude')}
            agencies = {r['agency_id']: r['agency_name'][:180] for r in rows('agency.txt')}
            routes = {r['route_id']: r for r in rows('routes.txt')}
            for row in rows('trips.txt'):
                route = routes.get(row['route_id'], {})
                self.trips[row['trip_id']] = {
                    'id': row['trip_id'], 'service': row['service_id'], 'shape': row.get('shape_id', ''),
                    'agency_id': route.get('agency_id', ''),
                    'number': (row.get('trip_short_name') or row.get('plk_train_number') or
                               route.get('route_short_name', ''))[:100],
                    'headsign': row.get('trip_headsign', '')[:180],
                    'operator': agencies.get(route.get('agency_id'), route.get('agency_id', '')),
                }
                for number in {row.get('trip_short_name'), row.get('plk_train_number')}:
                    if number:
                        self.by_number[(route.get('agency_id', ''), number)].append(row['trip_id'])
            for row in rows('calendar.txt'):
                self.calendar[row['service_id']] = (
                    date.fromisoformat(row['start_date']), date.fromisoformat(row['end_date']),
                    tuple(row[d] == '1' for d in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday',
                                                  'saturday', 'sunday')))
            for row in rows('calendar_dates.txt'):
                self.exceptions[(row['service_id'], date.fromisoformat(row['date']))] = row['exception_type'] == '1'
            for row in rows('stop_times.txt'):
                tid, sid = row['trip_id'], row['stop_id']
                if tid not in self.trips or sid not in self.stops:
                    continue
                # Canonical identifiers are shared by ~600k records and their station index.
                tid, sid = self.trips[tid]['id'], self.stops[sid]['id']
                entry = (sid, int(row['stop_sequence']), seconds(row['arrival_time']),
                         seconds(row['departure_time']), row.get('pickup_type') != '1',
                         distance(row.get('shape_dist_traveled')))
                self.times[tid].append(entry)
                parent = self.stops[sid]['parent']
                if parent in self.stations:
                    self.at_station[parent].append((tid, entry))
            for entries in self.times.values():
                entries.sort(key=lambda r: r[1])
            for row in rows('feed_info.txt'):
                if row.get('feed_end_date'):
                    self.valid_until = date.fromisoformat(row['feed_end_date'])
            if 'shapes.txt' in names:
                # Index compressed shape blocks once; only decode the clicked route.
                shapes_text = archive.read('shapes.txt')
                header = shapes_text[:shapes_text.index(b'\n')]
                self.shape_columns = next(csv.reader([header.decode('utf-8-sig')]))
                shape_col = self.shape_columns.index('shape_id')
                offset = len(header) + 1
                previous, start = None, offset
                while offset < len(shapes_text):
                    end = shapes_text.find(b'\n', offset)
                    end = end + 1 if end >= 0 else len(shapes_text)
                    line = shapes_text[offset:end]
                    identity = line.split(b',')[shape_col].strip().decode('utf-8')
                    if identity != previous:
                        if previous is not None:
                            self.shapes[previous].append(zlib.compress(shapes_text[start:offset], level=1))
                        previous, start = identity, offset
                    offset += len(line)
                if previous is not None:
                    self.shapes[previous].append(zlib.compress(shapes_text[start:offset], level=1))
        if not self.stations or not self.trips or not self.times:
            raise ValueError('Empty GTFS timetable')

    def active(self, service, day):
        exception = self.exceptions.get((service, day))
        if exception is not None:
            return exception
        regular = self.calendar.get(service)
        return bool(regular and regular[0] <= day <= regular[1] and regular[2][day.weekday()])

    def geometry(self, shape_id):
        if not shape_id or shape_id not in self.shapes:
            return None
        if shape_id in self.shape_cache:
            self.shape_cache.move_to_end(shape_id)
            return self.shape_cache[shape_id]
        points = []
        for block in self.shapes[shape_id]:
            for row in csv.DictReader(io.StringIO(zlib.decompress(block).decode('utf-8')),
                                      fieldnames=self.shape_columns):
                lat, lon = float(row['shape_pt_lat']), float(row['shape_pt_lon'])
                if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                    points.append((int(row['shape_pt_sequence']), [lon, lat]))
        points.sort(key=lambda p: p[0])
        # Bound response size; sample existing points, never synthesize vehicle positions.
        coords = [p[1] for p in points]
        if len(coords) > 12000:
            step = math.ceil(len(coords) / 11999)
            coords = coords[::step] + [coords[-1]]
        result = {'type': 'LineString', 'coordinates': coords} if len(coords) >= 2 else None
        self.shape_cache[shape_id] = result
        if len(self.shape_cache) > 32:
            self.shape_cache.popitem(last=False)
        return result


class TrainService:
    def __init__(self, client, clock, timeout=30, demo=False, enabled=True):
        self.client, self.clock, self.timeout = client, clock, min(max(timeout, 10), 60)
        self.demo, self.enabled = demo, enabled
        self.lock = asyncio.Lock()
        self.timetable = None
        self.static_at = self.fetched_at = self.source_at = None
        self.static_retry = self.update_retry = None
        self.updates = {}
        self.static_error = self.update_error = False
        self.position_lock = asyncio.Lock()
        self.position_estimator = None
        self.position_cache = None

    def base(self):
        now = self.clock().astimezone(UTC)
        stale = bool(self.timetable and (self.static_error or self.update_error or not self.source_at or
                     now - self.source_at > timedelta(seconds=STALE_SECONDS) or
                     (self.timetable.valid_until and now.astimezone(WARSAW).date() > self.timetable.valid_until)))
        message = ''
        status = 'ready'
        if not self.enabled:
            status, message = 'disabled', 'Warstwa kolejowa wyłączona w konfiguracji.'
        elif self.demo:
            status, message = 'ready', 'Dane kolejowe niedostępne w trybie demonstracyjnym.'
        elif not self.timetable:
            status, message = 'error', 'Rozkład kolejowy chwilowo niedostępny.'
        elif stale:
            status, message = 'stale', 'Dane kolejowe mogą być nieaktualne; sprawdź czas aktualizacji źródła.'
        return {'status': status, 'stale': stale, 'source_updated_at': iso(self.source_at),
                'fetched_at': iso(self.fetched_at), 'static_fetched_at': iso(self.static_at),
                'refresh_seconds': REFRESH_SECONDS, 'stale_after_seconds': STALE_SECONDS,
                'message': message, 'enabled': bool(self.enabled), 'demo': self.demo,
                'source_name': 'PolishTrainsGTFS · PKP PLK / Koleje Mazowieckie',
                'source_url': 'https://mkuran.pl/gtfs/'}

    async def download(self, url):
        async with self.client.stream('GET', url, timeout=self.timeout, follow_redirects=False,
                                      headers={'User-Agent': 'WICI/1.0 (PolishTrainsGTFS)',
                                               'Accept': 'application/zip' if url == STATIC_URL else 'application/json'}) as response:
            if response.status_code != 200:
                delay = 120
                if response.status_code in (429, 503):
                    try:
                        delay = min(86400, max(120, int(response.headers.get('retry-after', '120'))))
                    except ValueError:
                        pass
                raise FeedError(delay)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_BYTES:
                    raise ValueError('Rail response too large')
                body.extend(chunk)
            return bytes(body)

    async def refresh(self):
        if self.demo or not self.enabled:
            return
        async with self.lock:
            now = self.clock().astimezone(UTC)
            if ((self.static_at is None or now - self.static_at >= timedelta(seconds=STATIC_SECONDS))
                    and (self.static_retry is None or now >= self.static_retry)):
                try:
                    body = await self.download(STATIC_URL)
                    timetable = await asyncio.to_thread(Timetable, body)
                    self.timetable, self.static_at, self.static_error = timetable, now, False
                    self.position_estimator = self.position_cache = None
                    self.static_retry = None
                except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError, zipfile.BadZipFile,
                        UnicodeError, csv.Error, zlib.error, RuntimeError) as error:
                    self.static_error = True
                    self.static_retry = now + timedelta(seconds=getattr(error, 'delay', 120))
            if self.timetable and ((self.fetched_at is None or
                                    now - self.fetched_at >= timedelta(seconds=REFRESH_SECONDS))
                                   and (self.update_retry is None or now >= self.update_retry)):
                try:
                    body = await self.download(UPDATES_URL)
                    updates, source_at = await asyncio.to_thread(self.parse_updates, body, now)
                    if self.source_at and source_at < self.source_at:
                        raise ValueError('Rail source timestamp moved backwards')
                    self.match_updates(updates)
                    self.updates, self.source_at, self.fetched_at = updates, source_at, now
                    self.position_cache = None
                    self.update_retry, self.update_error = None, False
                except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError) as error:
                    self.update_error = True
                    self.update_retry = now + timedelta(seconds=getattr(error, 'delay', 120))

    @staticmethod
    def parse_updates(body, now):
        def compact(row):
            # Convert each stop while JSON is parsed, avoiding hundreds of thousands
            # of large dictionaries and duplicated platform/track strings in RAM.
            if isinstance(row.get('stop_sequence'), int):
                arrival, departure = timestamp(row.get('arrival')), timestamp(row.get('departure'))
                return (row['stop_sequence'], int(arrival.timestamp()) if arrival else None,
                        int(departure.timestamp()) if departure else None, row.get('cancelled') is True)
            return row
        payload = json.loads(body, object_hook=compact)
        if not isinstance(payload, dict):
            raise TypeError('Invalid rail snapshot')
        source_at = timestamp(payload.get('timestamp'))
        entries = payload.get('trip_updates')
        if source_at is None or source_at > now + timedelta(seconds=120):
            raise ValueError('Invalid rail source timestamp')
        if entries is None:
            entries = []
        if not isinstance(entries, list) or len(entries) > 60000:
            raise ValueError('Invalid rail updates')
        updates = {}
        for row in entries:
            if not isinstance(row, dict) or not isinstance(row.get('trip_id'), str):
                continue
            day = date.fromisoformat(row['start_date'])
            stops = row.get('stop_times') or []
            if not isinstance(stops, list) or len(stops) > 2000:
                raise ValueError('Invalid rail stops')
            updates[(row['trip_id'], day)] = {
                'cancelled': row.get('cancelled') is True, 'detour': row.get('detour') is True,
                'agency_id': row.get('agency_id'), 'numbers': row.get('numbers') or [],
                'stops': {r[0]: r for r in stops if isinstance(r, tuple) and len(r) == 4},
            }
        return updates, source_at

    def match_updates(self, updates):
        # IDs can change between independent static and live publication cycles.
        # Only accept an unambiguous agency + train number + service-day fallback.
        for (tid, day), update in list(updates.items()):
            if tid in self.timetable.trips and self.timetable.active(self.timetable.trips[tid]['service'], day):
                continue
            candidates = set()
            numbers = update['numbers'] if isinstance(update['numbers'], list) else []
            for number in numbers:
                if not isinstance(number, str):
                    continue
                for candidate in self.timetable.by_number.get((update['agency_id'], number), []):
                    if self.timetable.active(self.timetable.trips[candidate]['service'], day):
                        candidates.add(candidate)
            if len(candidates) == 1:
                updates.setdefault((next(iter(candidates)), day), update)

    async def stations(self):
        await self.refresh()
        return {**self.base(), 'items': sorted((dict(s) for s in self.timetable.stations.values()),
                                             key=lambda s: s['name']) if self.timetable else []}

    def stop(self, entry, day, update, timetable=None):
        timetable = timetable or self.timetable
        sid, sequence, arrival, departure, _ = entry[:5]
        details = timetable.stops[sid]
        planned_arrival, planned_departure = service_time(day, arrival), service_time(day, departure)
        # Detour stop_sequence is explicitly not an index into the static route.
        live = update.get('stops', {}).get(sequence, {}) if not update.get('detour') else {}
        expected_arrival = datetime.fromtimestamp(live[1], UTC) if live and live[1] is not None else None
        expected_departure = datetime.fromtimestamp(live[2], UTC) if live and live[2] is not None else None
        planned, expected = ((planned_departure, expected_departure)
                             if planned_departure and expected_departure else
                             (planned_arrival, expected_arrival))
        delay = round((expected - planned).total_seconds()) if expected and planned else None
        return {'id': details['parent'], 'name': details['name'], 'latitude': details['latitude'],
                'longitude': details['longitude'], 'sequence': sequence,
                'scheduled_arrival': iso(planned_arrival), 'scheduled_departure': iso(planned_departure),
                'expected_arrival': iso(expected_arrival), 'expected_departure': iso(expected_departure),
                'delay_seconds': delay, 'skipped': bool(live and live[3]),
                'realtime': bool(live)}

    async def station(self, station_id):
        await self.refresh()
        result = {**self.base(), 'station': None, 'departures': [], 'truncated': False}
        if not self.timetable:
            return result
        if station_id not in self.timetable.stations:
            return {**result, 'status': 'not_found'}
        result['station'] = dict(self.timetable.stations[station_id])
        now = self.clock().astimezone(UTC)
        today = now.astimezone(WARSAW).date()
        departures = []
        for tid, entry in self.timetable.at_station[station_id]:
            if not entry[4] or entry[3] is None:
                continue
            info = self.timetable.trips[tid]
            # GTFS times up to 71h can belong to earlier service days.
            for offset in (-2, -1, 0, 1):
                day = today + timedelta(days=offset)
                if not self.timetable.active(info['service'], day):
                    continue
                update = self.updates.get((tid, day), {})
                stop = self.stop(entry, day, update)
                expected = timestamp(stop['expected_departure']) or timestamp(stop['scheduled_departure'])
                if not now - timedelta(minutes=30) <= expected <= now + timedelta(hours=3):
                    continue
                departures.append({'trip_id': tid, 'start_date': day.isoformat(),
                                   **{k: info[k] for k in ('number', 'headsign', 'operator')},
                                   'scheduled_at': stop['scheduled_departure'],
                                   'expected_at': stop['expected_departure'],
                                   'delay_seconds': round((timestamp(stop['expected_departure']) -
                                                          timestamp(stop['scheduled_departure'])).total_seconds())
                                   if stop['expected_departure'] else None,
                                   'cancelled': update.get('cancelled', False) or stop['skipped'],
                                   'trip_cancelled': update.get('cancelled', False),
                                   'realtime': stop['realtime'] or update.get('cancelled', False),
                                   'detour': update.get('detour', False)})
        departures.sort(key=lambda r: r['expected_at'] or r['scheduled_at'])
        result.update(departures=departures[:100], truncated=len(departures) > 100)
        return result

    async def positions(self):
        async with self.position_lock:
            await self.refresh()
            now = self.clock().astimezone(UTC)
            result = {**self.base(), 'items': [], 'estimated_at': iso(now), 'valid_until': None,
                      'refresh_seconds': CACHE_SECONDS, 'source_refresh_seconds': REFRESH_SECONDS}
            if (result['stale'] or result['status'] != 'ready' or not self.timetable or not self.source_at
                    or self.demo or not self.enabled or now >= self.source_at + timedelta(seconds=STALE_SECONDS)):
                return result
            timetable, updates, source_at = self.timetable, self.updates, self.source_at
            cache = self.position_cache
            if (cache and cache[0] is timetable and cache[1] is updates and
                    timedelta() <= now - cache[2] < timedelta(seconds=CACHE_SECONDS)):
                computed_at, items = cache[2], cache[3]
            else:
                if self.position_estimator is None or self.position_estimator.timetable is not timetable:
                    self.position_estimator = PositionEstimator(timetable)
                computed_at = now
                try:
                    items = await asyncio.to_thread(self.position_estimator.estimate, updates, now,
                                                    source_at, STALE_SECONDS)
                except (ValueError, TypeError, KeyError, OverflowError, csv.Error, zlib.error):
                    return {**result, 'status': 'error',
                            'message': 'Nie można wiarygodnie oszacować pozycji pociągów.'}
                self.position_cache = (timetable, updates, computed_at, items)
            # A refresh or source outage may have happened while the worker computed routes.
            now = self.clock().astimezone(UTC)
            current = self.base()
            if (current['stale'] or current['status'] != 'ready' or self.timetable is not timetable or
                    self.updates is not updates or self.source_at != source_at or
                    now >= source_at + timedelta(seconds=STALE_SECONDS)):
                return {**result, **current, 'refresh_seconds': CACHE_SECONDS, 'items': []}
            valid_until = min(source_at + timedelta(seconds=STALE_SECONDS),
                              computed_at + timedelta(seconds=VALID_SECONDS))
            if now >= valid_until:
                return {**result, 'message': 'Obliczanie pozycji trwało zbyt długo; ponów za chwilę.'}
            return {**result, 'items': [dict(item) for item in items if timestamp(item['valid_until']) > now],
                    'estimated_at': iso(computed_at), 'valid_until': iso(valid_until)}

    async def trip(self, trip_id, start_date):
        await self.refresh()
        result = {**self.base(), 'trip': None}
        if not self.timetable:
            return result
        try:
            day = date.fromisoformat(start_date)
        except (TypeError, ValueError):
            return {**result, 'status': 'not_found'}
        timetable = self.timetable
        info = timetable.trips.get(trip_id)
        if not info or not timetable.active(info['service'], day):
            return {**result, 'status': 'not_found'}
        update = self.updates.get((trip_id, day), {})
        geometry = None if update.get('detour') else await asyncio.to_thread(timetable.geometry, info['shape'])
        result['trip'] = {'id': trip_id, 'start_date': day.isoformat(),
                          **{k: info[k] for k in ('number', 'headsign', 'operator')},
                          'cancelled': update.get('cancelled', False), 'realtime': bool(update),
                          'detour': update.get('detour', False), 'geometry': deepcopy(geometry),
                          'stops': [self.stop(entry, day, update, timetable) for entry in timetable.times[trip_id]]}
        return result


class FeedError(ValueError):
    def __init__(self, delay):
        super().__init__('Rail source unavailable')
        self.delay = delay
