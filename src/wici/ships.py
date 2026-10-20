"""Demand-driven, shared AISStream connection; bounded volatile Baltic positions."""
import asyncio
import json
import logging
import math
import random
from contextlib import suppress
from datetime import UTC, datetime

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from wici.marine_area import in_baltic

STREAM_URL = 'wss://stream.aisstream.io/v0/stream'
BOUNDING_BOXES = [[[53, 9], [66, 31]]]
MAX_POSITION_AGE = 900
MAX_VESSELS = 10000
POSITION_TYPES = ('PositionReport', 'StandardClassBPositionReport', 'ExtendedClassBPositionReport')
MESSAGE_TYPES = [*POSITION_TYPES, 'ShipStaticData', 'StaticDataReport']

# WebSocket debug frame logging can include the subscription secret. Never propagate it.
STREAM_LOGGER = logging.getLogger('wici.ais.transport')
STREAM_LOGGER.setLevel(logging.CRITICAL + 1)
STREAM_LOGGER.addHandler(logging.NullHandler())
STREAM_LOGGER.propagate = False


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if low <= value <= high and math.isfinite(value) else None


def text(value, maximum=128):
    if not isinstance(value, str):
        return None
    value = value.strip().strip('@').strip()
    return value if value and len(value) <= maximum and all(ord(c) >= 32 for c in value) else None


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        # AISStream Go timestamps append a redundant UTC zone name after the offset.
        parsed = datetime.fromisoformat(value.removesuffix(' UTC'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


class ShipService:
    def __init__(self, clock, key='', enabled=True, demo=False, connector=connect, idle_seconds=45):
        self.clock, self._key = clock, key
        self.enabled, self.demo = enabled, demo
        self.connector, self.idle_seconds = connector, idle_seconds
        self.items = {}
        self.task = None
        self.deadline = 0
        self.status = 'connecting'
        self.last_received = None

    def prune(self):
        now = self.clock().astimezone(UTC)
        for mmsi, item in list(self.items.items()):
            at = timestamp(item.get('position_at')) or timestamp(item.get('_metadata_at'))
            if at is None or not 0 <= (now-at).total_seconds() <= MAX_POSITION_AGE:
                del self.items[mmsi]

    def snapshot(self):
        self.prune()
        items = [{k: v for k, v in item.items() if not k.startswith('_')}
                 for item in self.items.values() if item.get('position_at')]
        status, message = self.status, ''
        if not self.enabled:
            status, message = 'disabled', 'Warstwa statków wyłączona w konfiguracji.'
        elif self.demo:
            status, message = 'disabled', 'Statki AIS niedostępne w trybie demonstracyjnym.'
        elif not self._key:
            status, message = 'disabled', 'Brak klucza AISStream w konfiguracji lokalnej.'
        elif status == 'error':
            message = 'AISStream chwilowo niedostępny. Automatyczne ponawianie połączenia.'
        elif status == 'connecting':
            message = 'Łączenie z AISStream; mapa uzupełnia się po odebraniu wiadomości.'
        elif not items:
            message = 'Oczekiwanie na pozycje AIS z Bałtyku; pokrycie może być niepełne.'
        return {'items': items, 'status': status, 'message': message,
                'stale': bool(items) and status != 'ready', 'enabled': self.enabled, 'demo': self.demo,
                'configured': bool(self._key), 'refresh_seconds': 10, 'source_name': 'AISStream',
                'source_url': 'https://aisstream.io/', 'fetched_at': self.last_received}

    async def fetch(self):
        if self.enabled and not self.demo and self._key:
            self.deadline = asyncio.get_running_loop().time() + self.idle_seconds
            if self.task is None or self.task.done():
                self.status = 'connecting'
                self.task = asyncio.create_task(self.run(), name='wici-aisstream')
        return self.snapshot()

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    def ingest(self, payload):
        if not isinstance(payload, dict):
            return False
        kind = payload.get('MessageType')
        if kind not in MESSAGE_TYPES:
            return False
        meta, messages = payload.get('MetaData'), payload.get('Message')
        if not isinstance(meta, dict) or not isinstance(messages, dict):
            return False
        report = messages.get(kind)
        if not isinstance(report, dict) or report.get('Valid') is False:
            return False
        mmsi_value = number(meta.get('MMSI'), 100000000, 999999999)
        if mmsi_value is None or int(mmsi_value) != mmsi_value:
            return False
        mmsi = str(int(mmsi_value))
        at = timestamp(meta.get('time_utc'))
        now = self.clock().astimezone(UTC)
        if at is None or not 0 <= (now-at).total_seconds() <= MAX_POSITION_AGE:
            return False
        old = self.items.get(mmsi, {})
        item = dict(old) if old else dict.fromkeys(('name', 'imo', 'type_code', 'destination',
            'latitude', 'longitude', 'speed_knots', 'course', 'heading', 'position_at'))
        item['mmsi'] = mmsi
        if kind in POSITION_TYPES:
            lat, lon = number(report.get('Latitude'), -90, 90), number(report.get('Longitude'), -180, 180)
            if lat is None or lon is None or (old.get('position_at') and at < timestamp(old['position_at'])):
                return False
            if not in_baltic(lat, lon):
                # A newer outside-area report must also remove the previous visible position.
                self.items.pop(mmsi, None)
                return False
            item.update(latitude=lat, longitude=lon, position_at=at.isoformat(),
                        speed_knots=number(report.get('Sog'), 0, 102.2),
                        course=number(report.get('Cog'), 0, 359.9),
                        heading=number(report.get('TrueHeading'), 0, 359))
            if kind == 'ExtendedClassBPositionReport':
                item['type_code'] = number(report.get('Type'), 1, 99) or item['type_code']
        else:
            if old.get('_metadata_at') and at < timestamp(old['_metadata_at']):
                return False
            if kind == 'ShipStaticData':
                item.update(imo=number(report.get('ImoNumber'), 1000000, 9999999),
                            type_code=number(report.get('Type'), 1, 99),
                            destination=text(report.get('Destination')))
                item['name'] = text(report.get('Name')) or item['name']
            else:
                part_a, part_b = report.get('ReportA'), report.get('ReportB')
                if isinstance(part_a, dict) and report.get('PartNumber') == 0:
                    item['name'] = text(part_a.get('Name')) or item['name']
                if isinstance(part_b, dict) and report.get('PartNumber') == 1:
                    item['type_code'] = number(part_b.get('ShipType'), 1, 99)
            item['_metadata_at'] = at.isoformat()
        item['name'] = item['name'] or text(report.get('Name')) or text(meta.get('ShipName'))
        if mmsi not in self.items and len(self.items) >= MAX_VESSELS:
            self.prune()
            if len(self.items) >= MAX_VESSELS:
                self.items.pop(next(iter(self.items)))
        self.items[mmsi] = item
        self.last_received = now.isoformat()
        return True

    async def run(self):
        loop = asyncio.get_running_loop()
        delay = 2
        while loop.time() < self.deadline:
            try:
                async with self.connector(STREAM_URL, compression='deflate', open_timeout=10,
                        close_timeout=2, ping_interval=20, ping_timeout=20,
                        max_size=65536, max_queue=32, logger=STREAM_LOGGER) as socket:
                    await asyncio.wait_for(socket.send(json.dumps({'APIKey': self._key,
                        'BoundingBoxes': BOUNDING_BOXES, 'FilterMessageTypes': MESSAGE_TYPES})), timeout=2)
                    last_event = loop.time()
                    while loop.time() < self.deadline:
                        if loop.time()-last_event >= 60:
                            raise TimeoutError('AIS stream silent')
                        try:
                            raw = await asyncio.wait_for(socket.recv(),
                                timeout=min(20, max(.01, self.deadline-loop.time())))
                        except TimeoutError:
                            if loop.time()-last_event >= 60:
                                raise TimeoutError('AIS stream silent') from None
                            continue
                        try:
                            payload = json.loads(raw)
                        except (ValueError, UnicodeError, TypeError):
                            continue
                        if not isinstance(payload, dict):
                            continue
                        if 'error' in payload or 'Error' in payload:
                            raise ValueError('AIS subscription rejected')
                        if payload.get('MessageType') == 'SubscriptionConfirmation' or self.ingest(payload):
                            self.status = 'ready'
                            last_event = loop.time()
                            delay = 2
            except (OSError, TimeoutError, WebSocketException, ValueError):
                # Never log exception text or raw frames: providers may echo credentials.
                self.status = 'error'
                remaining = self.deadline-loop.time()
                if remaining > 0:
                    await asyncio.sleep(min(remaining, delay + random.uniform(0, 1)))
                    delay = min(delay*2, 60)
        self.status = 'connecting'
