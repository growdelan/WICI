"""Bounded on-demand RainViewer proxy: past composites, no forecast or archive."""
import asyncio
import json
import math
import re
import struct
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

MANIFEST = 'https://api.rainviewer.com/public/weather-maps.json'
HOST = 'https://tilecache.rainviewer.com'
BOUNDS = [[49, 14], [55, 24.2]]
REFRESH = 300
MAX_ZOOM = 6  # At most six native tiles over Poland, 78 for a 13-frame sequence.


class RadarUnavailable(Exception):
    pass


def tile_allowed(z, x, y):
    if not 3 <= z <= MAX_ZOOM or not (0 <= x < 2**z and 0 <= y < 2**z):
        return False
    west, east = x / 2**z * 360 - 180, (x+1) / 2**z * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi*(1-2*y/2**z))))
    south = math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+1)/2**z))))
    return west < 24.2 and east > 14 and south < 55 and north > 49


def parse_manifest(payload, now):
    if not isinstance(payload, dict) or payload.get('host') != HOST:
        raise ValueError('Nieznany serwer radaru')
    past = payload.get('radar', {}).get('past')
    if not isinstance(past, list) or not 1 <= len(past) <= 30:
        raise ValueError('Nieprawidłowa oś czasu radaru')
    result = {}
    for frame in past:
        if not isinstance(frame, dict):
            raise TypeError('Nieprawidłowa klatka radaru')
        time, path = frame.get('time'), frame.get('path')
        if isinstance(time, bool) or not isinstance(time, int) or not isinstance(path, str):
            raise TypeError('Nieprawidłowa klatka radaru')
        stamp = datetime.fromtimestamp(time, UTC)
        if not now-timedelta(hours=3) <= stamp <= now+timedelta(minutes=5):
            raise ValueError('Klatka poza bieżącym oknem radaru')
        if not re.fullmatch(r'/v2/radar/[a-zA-Z0-9_-]{1,64}', path) or time in result:
            raise ValueError('Nieprawidłowy adres klatki')
        result[time] = path
    return dict(sorted(result.items())[-13:])


class RadarService:
    def __init__(self, client, clock, timeout=20, enabled=True, demo=False):
        self.client, self.clock, self.timeout, self.enabled, self.demo = client, clock, timeout, enabled, demo
        self.manifest_lock, self.tile_lock = asyncio.Lock(), asyncio.Lock()
        self.snapshot, self.paths, self.tiles = None, {}, OrderedDict()
        self.calls = deque()
        self.next_due = self.blocked_until = None
        self.error = ''

    def base(self):
        return {'enabled':self.enabled and not self.demo, 'status':'disabled', 'frames':[],
                'stale':False, 'message':'Radar wyłączony w demonstracji (bez sieci).' if self.demo else
                    'Radar wyłączony w konfiguracji.', 'fetched_at':None,
                'refresh_seconds':REFRESH, 'bounds':BOUNDS, 'max_native_zoom':MAX_ZOOM,
                'source_url':'https://www.rainviewer.com/', 'source_name':'RainViewer'}

    def result(self):
        data = dict(self.snapshot or {**self.base(), 'enabled':True, 'status':'error'})
        latest = data['frames'][-1]['timestamp'] if data['frames'] else None
        data['stale'] = bool(self.error or (latest and self.clock().timestamp()-latest > 1800))
        if self.error:
            data.update(status='error', message=self.error)
        elif data['stale']:
            data['message'] = 'Ostatnia klatka ma ponad 30 minut; aktualność opadów niepotwierdzona.'
        return data

    async def request(self, url, limit):
        now = self.clock()
        if self.blocked_until and now < self.blocked_until:
            raise RadarUnavailable('Radar czeka na ponowienie po limicie dostawcy.')
        while self.calls and now-self.calls[0] >= timedelta(seconds=60):
            self.calls.popleft()
        if len(self.calls) >= 90:
            raise RadarUnavailable('Lokalny limit radaru: ponów za minutę.')
        self.calls.append(now)
        async with self.client.stream('GET', url, timeout=self.timeout, follow_redirects=False) as response:
            if response.status_code != 200:
                if response.status_code in (401, 403, 429):
                    retry = response.headers.get('retry-after', '')
                    try:
                        seconds = float(retry)
                    except ValueError:
                        try:
                            seconds = (parsedate_to_datetime(retry)-now).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            seconds = 300
                    if not math.isfinite(seconds):
                        seconds = 300
                    self.blocked_until = now+timedelta(seconds=max(300, min(seconds, 86400)))
                raise RadarUnavailable(f'Radar niedostępny (HTTP {response.status_code}).')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise RadarUnavailable('Odpowiedź radaru przekracza limit.')
            return bytes(body), response.headers.get('content-type', '').split(';')[0]

    async def metadata(self):
        if not self.enabled or self.demo:
            return self.base()
        async with self.manifest_lock:
            now = self.clock()
            if self.next_due and now < self.next_due:
                return self.result()
            self.next_due = now+timedelta(seconds=REFRESH)
            try:
                body, content_type = await self.request(MANIFEST, 65536)
                if content_type != 'application/json':
                    raise ValueError('Radar nie zwrócił JSON')
                frames = parse_manifest(json.loads(body), now)
                self.paths = {time:path for time,path in self.paths.items()
                              if now.timestamp()-time <= 3*3600}
                self.paths.update(frames)
                self.snapshot = {**self.base(), 'enabled':True, 'status':'success', 'message':'',
                                 'fetched_at':now.isoformat(), 'frames':[
                                     {'timestamp':time, 'time':datetime.fromtimestamp(time, UTC).isoformat(),
                                      'tile_url':f'/api/radar/tiles/{time}/{{z}}/{{x}}/{{y}}.png'}
                                     for time in frames]}
                self.error = ''
            except (httpx.HTTPError, RadarUnavailable, ValueError, TypeError, AttributeError, OverflowError):
                self.error = 'Nie udało się odświeżyć radaru; zachowane klatki mogą być nieaktualne.'
            return self.result()

    async def tile(self, time, z, x, y):
        if not self.enabled or self.demo:
            raise RadarUnavailable('Radar wyłączony w tym trybie.')
        if not tile_allowed(z, x, y):
            raise ValueError('Kafelek poza zakresem radaru Polski')
        await self.metadata()
        async with self.tile_lock:
            if time not in self.paths or self.clock().timestamp()-time > 3*3600:
                raise ValueError('Nieznana lub wygasła klatka radaru')
            key = (self.paths[time], z, x, y)
            if key in self.tiles:
                self.tiles.move_to_end(key)
                return self.tiles[key]
            try:
                body, content_type = await self.request(f'{HOST}{self.paths[time]}/256/{z}/{x}/{y}/2/1_0.png',
                                                        512*1024)
                if (content_type != 'image/png' or not body.startswith(b'\x89PNG\r\n\x1a\n')
                        or len(body) < 33 or body[12:16] != b'IHDR'
                        or struct.unpack('>II', body[16:24]) != (256, 256) or body[-12:] !=
                        b'\x00\x00\x00\x00IEND\xaeB`\x82'):
                    raise RadarUnavailable('Nieprawidłowy obraz radaru.')
            except httpx.HTTPError as exc:
                self.blocked_until = self.clock()+timedelta(seconds=30)
                raise RadarUnavailable('Nie udało się pobrać obrazu radaru.') from exc
            self.tiles[key] = body
            while len(self.tiles) > 128:
                self.tiles.popitem(last=False)
            return body
