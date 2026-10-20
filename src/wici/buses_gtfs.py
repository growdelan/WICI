"""On-demand city bus snapshots from bounded GTFS and GTFS-Realtime feeds.

Static data is indexed in memory, never persisted; stop_times and shapes are not read.
Feed namespaces keep Kraków's independent operator identifiers separate.
"""
import asyncio
import csv
import io
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as gtfs

from wici.weather import number

REFRESH_SECONDS = 10
MAX_POSITION_AGE = 120
MAX_REALTIME_BYTES = 8 * 1024 * 1024
MAX_STATIC_BYTES = 64 * 1024 * 1024
MAX_TABLE_BYTES = 64 * 1024 * 1024
MAX_TABLE_ROWS = 500_000
STATIC_SECONDS = 6 * 60 * 60

KRAKOW_ROOT = 'https://gtfs.ztp.krakow.pl/'
POZNAN_ROOT = 'https://www.ztm.poznan.pl/pl/dla-deweloperow/'
FEEDS = {
    'krakow': [
        ('A', KRAKOW_ROOT+'VehiclePositions_A.pb', KRAKOW_ROOT+'TripUpdates_A.pb',
         KRAKOW_ROOT+'GTFS_KRK_A.zip'),
        ('M', KRAKOW_ROOT+'VehiclePositions_M.pb', KRAKOW_ROOT+'TripUpdates_M.pb',
         KRAKOW_ROOT+'GTFS_KRK_M.zip'),
    ],
    'poznan': [
        ('ztm', POZNAN_ROOT+'getGtfsRtFile?file=vehicle_positions.pb',
         POZNAN_ROOT+'getGtfsRtFile?file=trip_updates.pb', POZNAN_ROOT+'getGTFSFile'),
    ],
}
SOURCES = {
    'krakow': ('ZTP Kraków — MPK i Mobilis', 'https://gtfs.ztp.krakow.pl/'),
    'poznan': ('ZTM Poznań', 'https://www.ztm.poznan.pl/otwarte-dane/dla-deweloperow/'),
}


def text(value, maximum=160):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= maximum and not any(ord(c) < 32 for c in value) else None


def observed_at(timestamp, now):
    try:
        result = datetime.fromtimestamp(timestamp, UTC)
        return result if 0 <= (now-result).total_seconds() <= MAX_POSITION_AGE else None
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def read_realtime(body):
    feed = gtfs.FeedMessage()
    feed.ParseFromString(body)
    if (not feed.IsInitialized() or feed.header.incrementality == gtfs.FeedHeader.DIFFERENTIAL
            or len(feed.entity) > 20_000):
        raise ValueError('Invalid or differential GTFS-RT snapshot')
    return feed


def read_static(body):
    """Keep only bus route/trip metadata and stop/agency names, with bounded tables."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        if len(archive.infolist()) > 100:
            raise ValueError('Too many GTFS archive entries')
        names = ('agency.txt', 'routes.txt', 'trips.txt', 'stops.txt')
        if sum(archive.getinfo(name).file_size for name in names) > 2 * MAX_TABLE_BYTES:
            raise ValueError('GTFS metadata too large')

        def rows(name, required):
            info = archive.getinfo(name)
            if info.file_size > MAX_TABLE_BYTES:
                raise ValueError('GTFS table too large')
            with archive.open(info) as binary:
                # read() is bounded even if a malformed ZIP lies about its entry size.
                body = binary.read(MAX_TABLE_BYTES+1)
            if len(body) > MAX_TABLE_BYTES:
                raise ValueError('GTFS table too large')
            reader = csv.DictReader(io.StringIO(body.decode('utf-8-sig'), newline=''))
            if not required.issubset(reader.fieldnames or []):
                raise ValueError('Missing GTFS columns')
            for index, row in enumerate(reader):
                if index >= MAX_TABLE_ROWS:
                    raise ValueError('Too many GTFS rows')
                yield row

        agencies = {row.get('agency_id', ''): text(row['agency_name'])
                    for row in rows('agency.txt', {'agency_name'})}
        routes = {}
        for row in rows('routes.txt', {'route_id', 'route_type', 'route_short_name'}):
            route_type = number(row['route_type'], 0, 2000)
            if route_type == 3 or route_type is not None and 700 <= route_type < 800:
                operator = agencies.get(row.get('agency_id', ''))
                if operator is None and len(agencies) == 1:
                    operator = next(iter(agencies.values()))
                routes[row['route_id']] = (text(row['route_short_name'], 16), operator)
        trips = {row['trip_id']: (row['route_id'], text(row.get('trip_headsign')))
                 for row in rows('trips.txt', {'trip_id', 'route_id'}) if row['route_id'] in routes}
        stops = {row['stop_id']: text(row['stop_name'])
                 for row in rows('stops.txt', {'stop_id', 'stop_name'})}
        return {'routes': routes, 'trips': trips, 'stops': stops}


@dataclass
class FeedState:
    metadata: dict | None = None
    static_until: datetime | None = None
    static_retry: datetime | None = None
    items: list = field(default_factory=list)
    fetched_at: str | None = None
    next_fetch: datetime | None = None
    updates_retry: datetime | None = None
    error: bool = False


class SourceError(ValueError):
    def __init__(self, retry_seconds=60):
        super().__init__('Bus source unavailable')
        self.retry_seconds = retry_seconds


class GtfsBusService:
    def __init__(self, client, clock, city, timeout=20, demo=False, enabled=True):
        if city not in FEEDS:
            raise ValueError('Unsupported GTFS bus city')
        self.client, self.clock, self.city = client, clock, city
        self.timeout, self.demo, self.enabled = min(timeout, 30), demo, enabled
        self.lock = asyncio.Lock()
        self.feeds = {config[0]: FeedState() for config in FEEDS[city]}

    def base(self):
        name, url = SOURCES[self.city]
        return {'items': [], 'status': 'ready', 'stale': False, 'fetched_at': None,
                'refresh_seconds': REFRESH_SECONDS, 'message': '', 'enabled': bool(self.enabled),
                'demo': self.demo, 'source_name': name, 'source_url': url}

    def snapshot(self, now):
        result = self.base()
        for state in self.feeds.values():
            result['items'].extend(dict(item) for item in state.items
                                   if observed_at(datetime.fromisoformat(item['position_at']).timestamp(), now))
        fetched = [state.fetched_at for state in self.feeds.values() if state.fetched_at]
        result['fetched_at'] = max(fetched) if fetched else None
        if any(state.error for state in self.feeds.values()):
            result.update(status='error', stale=bool(result['items']),
                          message=f'{result["source_name"]}: część danych chwilowo niedostępna; '
                                  'sprawdź czas pozycji. Niektórych szczegółów może brakować.')
        return result

    async def fetch(self):
        async with self.lock:
            if not self.enabled:
                return {**self.base(), 'status': 'disabled',
                        'message': 'Warstwa autobusów wyłączona w konfiguracji.'}
            if self.demo:
                return {**self.base(), 'message': 'Pozycje autobusów niedostępne w trybie demonstracyjnym.'}
            now = self.clock().astimezone(UTC)
            await asyncio.gather(*(self.refresh(config, now) for config in FEEDS[self.city]))
            return self.snapshot(self.clock().astimezone(UTC))

    async def download(self, url, maximum, now):
        async with self.client.stream('GET', url, timeout=self.timeout, follow_redirects=True) as response:
            if response.status_code != 200:
                retry = 60
                if response.status_code == 429:
                    raw = response.headers.get('retry-after', '')
                    seconds = number(raw, 0, 86400)
                    if seconds is None:
                        try:
                            seconds = (parsedate_to_datetime(raw).astimezone(UTC)-now).total_seconds()
                        except (ValueError, TypeError, OverflowError, AttributeError):
                            seconds = None
                    retry = min(max(60, seconds or 0), 86400)
                raise SourceError(retry)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body)+len(chunk) > maximum:
                    raise ValueError('Bus source response too large')
                body.extend(chunk)
            return bytes(body)

    async def metadata(self, state, url, now):
        if state.metadata is not None and now < state.static_until:
            return state.metadata
        if state.static_retry and now < state.static_retry:
            if state.metadata is None:
                raise SourceError((state.static_retry-now).total_seconds())
            return state.metadata
        try:
            body = await self.download(url, MAX_STATIC_BYTES, now)
            metadata = await asyncio.to_thread(read_static, body)
            state.metadata, state.static_until = metadata, now+timedelta(seconds=STATIC_SECONDS)
            state.static_retry = None
        except (httpx.HTTPError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile, zlib.error,
                RuntimeError, csv.Error, EOFError, NotImplementedError) as error:
            state.static_retry = now+timedelta(seconds=getattr(error, 'retry_seconds', 60))
            if state.metadata is None:
                raise
        return state.metadata

    async def refresh(self, config, now):
        namespace, position_url, update_url, static_url = config
        state = self.feeds[namespace]
        if state.next_fetch and now < state.next_fetch:
            return
        try:
            # Static tables are loaded once per six hours. The independent operators
            # refresh concurrently, but each is committed only after valid positions.
            metadata = await self.metadata(state, static_url, now)
            positions = read_realtime(await self.download(position_url, MAX_REALTIME_BYTES, now))
            updates, update_error = None, bool(state.updates_retry and now < state.updates_retry)
            if not update_error:
                try:
                    updates = read_realtime(await self.download(update_url, MAX_REALTIME_BYTES, now))
                    state.updates_retry = None
                except (httpx.HTTPError, ValueError, DecodeError) as error:
                    state.updates_retry = now+timedelta(seconds=getattr(error, 'retry_seconds', 60))
                    update_error = True
            observed_now = self.clock().astimezone(UTC)
            state.items = self.normalize(positions, updates, metadata, namespace, observed_now)
            state.fetched_at = observed_now.isoformat()
            state.error = update_error or state.static_retry is not None
            state.next_fetch = observed_now+timedelta(seconds=REFRESH_SECONDS)
        except (httpx.HTTPError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile, zlib.error,
                RuntimeError, csv.Error, EOFError, NotImplementedError, DecodeError) as error:
            state.error = True
            state.next_fetch = now+timedelta(seconds=getattr(error, 'retry_seconds', 60))

    def normalize(self, positions, updates, metadata, namespace, now):
        update_index = {}
        if updates is not None:
            for entity in updates.entity:
                if entity.is_deleted or not entity.HasField('trip_update'):
                    continue
                update = entity.trip_update
                timestamp = update.timestamp if update.HasField('timestamp') else updates.header.timestamp
                if observed_at(timestamp, now):
                    update_index[(update.trip.trip_id, update.vehicle.id)] = update
        items, seen = [], set()
        for entity in positions.entity:
            if entity.is_deleted or not entity.HasField('vehicle'):
                continue
            vehicle = entity.vehicle
            if not vehicle.HasField('position'):
                continue
            trip_id = vehicle.trip.trip_id
            trip = metadata['trips'].get(trip_id)
            route_id = vehicle.trip.route_id or (trip[0] if trip else '')
            route = metadata['routes'].get(route_id)
            identity = text(vehicle.vehicle.id, 100) or text(vehicle.vehicle.label, 100) or text(entity.id, 100)
            lat = number(vehicle.position.latitude, 49, 55)
            lon = number(vehicle.position.longitude, 14, 24.3)
            timestamp = vehicle.timestamp if vehicle.HasField('timestamp') else positions.header.timestamp
            observed = observed_at(timestamp, now)
            if not route or not identity or identity in seen or lat is None or lon is None or observed is None:
                continue
            seen.add(identity)
            update = update_index.get((trip_id, vehicle.vehicle.id)) or update_index.get((trip_id, ''))
            next_stop, delay = self.stop_details(vehicle, update, metadata['stops'])
            speed = number(vehicle.position.speed*3.6, 0, 200) if vehicle.position.HasField('speed') else None
            bearing = number(vehicle.position.bearing, 0, 360) if vehicle.position.HasField('bearing') else None
            items.append({'id': f'{self.city}:{namespace}:{identity}', 'line': route[0],
                          'vehicle_number': text(vehicle.vehicle.id, 32) or text(vehicle.vehicle.label, 32),
                          'model': None, 'operator': route[1], 'headsign': trip[1] if trip else None,
                          'latitude': lat, 'longitude': lon, 'speed_kmh': speed, 'bearing': bearing,
                          'delay_seconds': delay, 'previous_stop': None, 'next_stop': next_stop,
                          'position_at': observed.isoformat(), 'low_floor': None})
        return items

    @staticmethod
    def stop_details(vehicle, update, stops):
        # IN_TRANSIT_TO/INCOMING_AT refer to the upcoming stop. STOPPED_AT refers
        # to the present stop, which must not be mislabeled as the next stop.
        if vehicle.current_status == gtfs.VehiclePosition.STOPPED_AT:
            return None, None
        next_stop = stops.get(vehicle.stop_id)
        if update is None:
            return next_stop, None
        for stop in update.stop_time_update:
            if vehicle.HasField('current_stop_sequence') and stop.HasField('stop_sequence'):
                match = vehicle.current_stop_sequence == stop.stop_sequence
            else:
                match = bool(vehicle.stop_id and stop.stop_id == vehicle.stop_id)
            if not match or stop.schedule_relationship != gtfs.TripUpdate.StopTimeUpdate.SCHEDULED:
                continue
            next_stop = next_stop or stops.get(stop.stop_id)
            for event in (stop.arrival, stop.departure):
                if event.HasField('delay'):
                    return next_stop, number(event.delay, -86400, 86400)
            break
        return next_stop, None
