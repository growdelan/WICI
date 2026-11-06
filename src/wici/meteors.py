"""Read CC BY 4.0 Global Meteor Network trajectories for a local Polish night."""
import asyncio
import json
import math
import re
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from wici.aircraft import in_poland
from wici.ioda import retry_after

SOURCE = 'https://globalmeteornetwork.org/data/'
DAILY = SOURCE + 'traj_summary_data/daily/'
MIN_NIGHT = date(2018, 12, 9)
FEATURED_NIGHT = date(2026, 11, 4)
BUNDLED = Path(__file__).with_name('data') / 'meteor-night-2026-11-04.json'
WARSAW = ZoneInfo('Europe/Warsaw')
DAY = timedelta(days=1)
FILE_LINK = re.compile(r'href="(traj_summary_(\d{8})_solrange_(\d{3})\.0-(\d{3})\.0\.txt)"')
ID = re.compile(r'\d{14}_[A-Za-z0-9]{5}')
MAX_FILE = 32 * 1024 * 1024
MAX_EVENTS = 10000


class MeteorUnavailable(Exception):
    """Archive unavailable, incomplete, or beyond safe retrieval limits."""


def night_bounds(day):
    """Unix timestamps for consecutive local noons, including DST transitions."""
    return tuple(int(datetime.combine(d, time(12), WARSAW).timestamp()) for d in (day, day + DAY))


def result(day, start, end, events, *, bundled=False):
    return {'date': day.isoformat(), 'start': start, 'end': end, 'events': events,
            'source_url': SOURCE, 'bundled': bundled}


@dataclass
class SolarBin:
    first: float
    last: float
    events: list


def _number(value):
    if value.lower() in ('none', 'nan', '', '...'):
        return None
    n = float(value)
    if not math.isfinite(n):
        raise ValueError('Nieprawidłowa liczba GMN.')
    return n


# GMN table headers span two lines. Pair them to disambiguate UTC from Julian date,
# absolute magnitude from peak height and the many repeated +/- sigma fields.
COLUMNS = {'id': ('Unique trajectory', 'identifier'), 'start': ('Beginning', 'UTC Time'),
           'duration': ('Duration', 'sec'), 'speed': ('Vinit', 'km/s'), 'mag': ('Peak', 'AbsMag'),
           'lat1': ('LatBeg', '+N deg'), 'lon1': ('LonBeg', '+E deg'), 'ht1': ('HtBeg', 'km'),
           'lat2': ('LatEnd', '+N deg'), 'lon2': ('LonEnd', '+E deg'), 'ht2': ('HtEnd', 'km')}


def parse_table(body):
    """Keep only Polish events, but retain the actual time coverage of the whole file."""
    names = columns = None
    first = math.inf
    last = -math.inf
    events = []
    try:
        for raw in body.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(b'#'):
                header = [s.strip() for s in line[1:].decode('utf-8').split(';')]
                if header[0] == 'Unique trajectory':
                    names = header
                elif names and header[0] == 'identifier':
                    pairs = list(zip(names, header, strict=True))
                    columns = {k: pairs.index(v) for k, v in COLUMNS.items()}
                continue
            if columns is None:
                raise ValueError('Brak nazw kolumn GMN.')
            row = [s.strip() for s in line.decode('ascii').split(';')]
            if len(row) != len(names):
                raise ValueError('Niepełny wiersz GMN.')
            utc_text = row[columns['start']]
            observed = datetime.fromisoformat(utc_text)
            if observed.tzinfo is not None or len(utc_text) < 19 or utc_text[10] != ' ':
                raise ValueError('Nieoczekiwany format czasu GMN.')
            stamp = observed.replace(tzinfo=UTC).timestamp()
            first, last = min(first, stamp), max(last, stamp)
            latitude, longitude = float(row[columns['lat1']]), float(row[columns['lon1']])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError('Nieprawidłowa pozycja GMN.')
            if not (48 <= latitude <= 56 and 14 <= longitude <= 25 and in_poland(latitude, longitude)):
                continue
            identifier = row[columns['id']]
            alt = float(row[columns['ht1']])
            end_lat, end_lon, end_alt = (float(row[columns[k]]) for k in ('lat2', 'lon2', 'ht2'))
            duration = float(row[columns['duration']])
            if (not ID.fullmatch(identifier) or not 0 < duration < 3600
                    or not -90 <= end_lat <= 90 or not -180 <= end_lon <= 180
                    or not 0 <= alt <= 1000 or not 0 <= end_alt <= 1000):
                raise ValueError('Nieprawidłowa trajektoria GMN.')
            events.append({'id': identifier, 'start': stamp, 'duration': duration,
                           'begin': {'lat': latitude, 'lon': longitude, 'alt_km': alt},
                           'end': {'lat': end_lat, 'lon': end_lon, 'alt_km': end_alt},
                           'speed_kms': _number(row[columns['speed']]), 'magnitude': _number(row[columns['mag']])})
            if len(events) > MAX_EVENTS:
                raise ValueError('Limit trajektorii GMN.')
        if columns is None:
            raise ValueError('Brak tabeli GMN.')
    except (ValueError, OverflowError, OSError) as exc:
        raise MeteorUnavailable('Nie można odczytać formatu tabeli trajektorii GMN.') from exc
    return SolarBin(first, last, events)


class MeteorService:
    def __init__(self, client, clock, demo=False):
        self.client, self.clock, self.demo = client, clock, demo
        self.lock = asyncio.Lock()
        self.index = []
        self.index_until = self.retry_at = 0
        self.files = OrderedDict()
        self.requests = deque()

    async def _download(self, url, limit, *, read_timeout=18):
        now = self.clock().timestamp()
        if now < self.retry_at:
            raise MeteorUnavailable('GMN chwilowo wstrzymała pobieranie. Spróbuj ponownie później.')
        while self.requests and self.requests[0] <= now - 60:
            self.requests.popleft()
        if len(self.requests) >= 16:
            raise MeteorUnavailable('Limit pobrań GMN. Spróbuj ponownie za minutę.')
        self.requests.append(now)
        timeout = httpx.Timeout(18, read=read_timeout)
        async with self.client.stream('GET', url, timeout=timeout, follow_redirects=False) as resp:
            if resp.status_code in (429, 503) and resp.headers.get('retry-after'):
                self.retry_at = now + max(60, retry_after(resp.headers['retry-after'], self.clock()))
            resp.raise_for_status()
            body = bytearray()
            async for part in resp.aiter_bytes(chunk_size=65536):
                if len(body) + len(part) > limit:
                    raise MeteorUnavailable('Plik GMN przekracza limit pobierania.')
                body.extend(part)
            return body

    async def _index(self, now):
        if self.index and now < self.index_until:
            return self.index
        # Listing thousands of files can delay the first response header even on a warm connection.
        page = await self._download(DAILY, 1024 * 1024, read_timeout=35)
        try:
            links = [(date.fromisoformat(d), int(lo), filename)
                     for filename, d, lo, hi in FILE_LINK.findall(page.decode('ascii'))
                     if int(lo) < 360 and (int(lo) + 1) % 360 == int(hi)]
        except ValueError as exc:
            raise MeteorUnavailable('Niepoprawny katalog plików GMN.') from exc
        if not links:
            raise MeteorUnavailable('Brak katalogu plików GMN.')
        # Directory order is chronological except for a possible solar 359→000
        # rollover on the same UTC date. The first bin follows the previous day's.
        links.sort()
        for i in range(1, len(links)):
            if links[i - 1][:2] == (links[i][0], 0) and links[i][1] == 359:
                links[i - 1], links[i] = links[i], links[i - 1]
        self.index, self.index_until = links, now + 3600
        return links

    async def _file(self, filename, now):
        cached = self.files.get(filename)
        if cached and now < cached[0]:
            self.files.move_to_end(filename)
            return cached[1]
        parsed = await asyncio.to_thread(parse_table, await self._download(DAILY + filename, MAX_FILE))
        self.files[filename] = (now + 3600, parsed)
        self.files.move_to_end(filename)
        if len(self.files) > 12:
            self.files.popitem(last=False)
        return parsed

    async def _archive(self, day, start, end, now):
        links = [link for link in await self._index(now) if day - DAY <= link[0] <= day + DAY]
        if not links or len(links) > 4:
            raise MeteorUnavailable('Brak opublikowanego kompletnego zakresu GMN dla tej nocy.')
        # GMN daily files span one degree of solar longitude. A file's date labels
        # the start of its bin, not midnight. The same date can have two files or none.
        pos = next((i for i, link in enumerate(links) if link[0] >= day), len(links) - 1)
        left = right = pos
        solar = await self._file(links[pos][2], now)
        first, last = solar.first, solar.last
        observed = solar.events.copy()
        while first > start or last < end:
            if first > start and left > 0 and (links[left - 1][1] + 1) % 360 == links[left][1]:
                left -= 1
                index = left
            elif last < end and right + 1 < len(links) and (links[right][1] + 1) % 360 == links[right + 1][1]:
                right += 1
                index = right
            else:
                raise MeteorUnavailable('GMN nie opublikowała pełnego zakresu dla tej nocy.')
            solar = await self._file(links[index][2], now)
            first, last = min(first, solar.first), max(last, solar.last)
            observed.extend(solar.events)
        events = {e['id']: e for e in observed if start <= e['start'] < end}
        if len(events) > MAX_EVENTS:
            raise MeteorUnavailable('Noc przekracza limit trajektorii GMN.')
        return result(day, start, end, sorted(events.values(), key=lambda e: (e['start'], e['id'])))

    async def night(self, day):
        if self.demo and day != FEATURED_NIGHT:
            raise MeteorUnavailable('Tryb demonstracyjny zawiera tylko noc z 4 na 5 listopada 2026.')
        now = self.clock()
        if not self.demo and (day < MIN_NIGHT or day > now.astimezone(WARSAW).date()):
            raise ValueError('Wybierz zakończoną noc z archiwum GMN od 9 grudnia 2018.')
        start, end = night_bounds(day)
        if not self.demo and end > now.timestamp():
            raise ValueError('Wybrana noc jeszcze się nie zakończyła.')
        if day == FEATURED_NIGHT:
            return json.loads(BUNDLED.read_bytes())
        try:
            async with asyncio.timeout(55), self.lock:
                now_s = self.clock().timestamp()
                try:
                    return await self._archive(day, start, end, now_s)
                except httpx.HTTPError:
                    self.retry_at = max(self.retry_at, now_s + 60)
                    raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise MeteorUnavailable('Archiwum trajektorii GMN jest chwilowo niedostępne.') from exc
