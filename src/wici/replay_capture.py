"""Prepare and import time-matched ADS-B and weather-radar recordings."""
import asyncio
import json
import re
import warnings
from bisect import bisect_right
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from wici.aircraft import AircraftService, in_poland
from wici.flight_replay import MAX_MANIFEST, Episode, FlightReplay
from wici.radar import MAX_ZOOM, RadarService, RadarUnavailable, tile_allowed

SOURCE = 'https://adsb.lol'
Z = MAX_ZOOM
TILES = [(x, y) for x in range(2**Z) for y in range(2**Z) if tile_allowed(Z, x, y)]
MAX_AGE = 600  # RainViewer composite cadence (seconds).
MAX_GAP = 120
MIN_DURATION = 300
CAPTURE_TIMEOUT = 150
MAX_IMPORT_BYTES = 64 * 1024 * 1024


class NoReplayHistory(ValueError):
    """No matching track has enough observed positions and overlapping radar."""


def clock():
    return datetime.now(UTC)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def frame_at(times, time):
    index = bisect_right(times, time) - 1
    if index >= 0 and time - times[index] < MAX_AGE:
        return times[index]
    return None


def trace_legs(trace):
    """Separate physical legs before clipping to Poland or the radar time window."""
    if (not isinstance(trace, dict) or not numeric(trace.get('timestamp'))
            or not isinstance(trace.get('trace'), list)):
        raise ValueError('Nieprawidłowy ślad adsb.lol.')
    epoch = trace['timestamp']
    previous = None
    name = ''
    rows = []
    for row in trace['trace']:
        if not isinstance(row, list) or len(row) < 9 or type(row[6]) is not int:
            raise ValueError('Nieprawidłowy raport adsb.lol.')
        if not numeric(row[0]):
            raise ValueError('Nieprawidłowy czas raportu.')
        time = round(epoch + row[0])
        if previous is not None and time < previous:
            raise ValueError('Nieuporządkowane czasy raportów adsb.lol.')
        details = {} if row[8] is None else row[8]
        if not isinstance(details, dict) or not isinstance(details.get('flight', ''), str):
            raise TypeError('Nieprawidłowa identyfikacja lotu.')
        reported = details.get('flight', '').strip().upper()
        if len(reported) > 32 or any(ord(c) < 32 for c in reported):
            raise ValueError('Nieprawidłowy znak lotu.')
        ground = row[3] == 'ground'
        split = ground or bool(row[6] & 2) or (previous is not None and time - previous > MAX_GAP)
        if split or (reported and reported != name):
            if rows:
                yield name, rows
                rows = []
            name = ''
        previous = time
        if not ground:
            name = reported or name
            rows.append((time, row))
    if rows:
        yield name, rows


def latest_segment(rows, times):
    points = []
    selected = None
    for time, row in rows:
        lat, lon, altitude, _, course, flags = row[1:7]
        frame = frame_at(times, time)
        if frame is None or not numeric(lat) or not numeric(lon) or not in_poland(lat, lon):
            points = []
            continue
        # readsb field 10 is geometric altitude in feet. Bit 8 designates
        # field 3 as geometric for aircraft with no barometric altitude.
        geometric = altitude if flags & 8 else (row[10] if len(row) > 10 else None)
        if not numeric(geometric):
            continue
        if points and time - points[-1]['time'] > MAX_GAP:
            points = []
        sample = {'time': time, 'lat': lat, 'lon': lon, 'alt_m': round(geometric * 0.3048, 3)}
        if numeric(course) and 0 <= course <= 360:
            sample['heading'] = course
        if points and time == points[-1]['time']:
            points[-1] = sample
        else:
            points.append(sample)
        first = points[0]['time']
        if time - first >= MIN_DURATION and frame != frame_at(times, first):
            selected = points
    if selected:
        start = frame_at(times, selected[0]['time'])
        return selected, [t for t in times if start <= t <= selected[-1]['time']]
    return None


def select_leg(trace, times, requested='', *, current=False):
    """Select the last eligible leg, or require the currently selected callsign."""
    selected = None
    for name, rows in trace_legs(trace):
        if requested:
            # In the UI a later flight (even a different callsign) supersedes
            # the selected aircraft's historical flight. An explicit CLI filter
            # can select an older named flight, but never its previous occurrence.
            if current or name == requested:
                selected = None
            if name != requested:
                continue
        if rows[-1][0] < times[0] or rows[0][0] >= times[-1] + MAX_AGE:
            continue
        segment = latest_segment(rows, times)
        if segment:
            selected = (name, *segment)
    return selected


async def download_trace(client, icao):
    url = f'{SOURCE}/data/traces/{icao[-2:]}/trace_full_{icao}.json'
    async with client.stream('GET', url, timeout=15, follow_redirects=False) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(data) + len(chunk) > 8 * 1024 * 1024:
                raise ValueError('Ślad przekracza limit rozmiaru.')
            data.extend(chunk)
        trace = await asyncio.to_thread(json.loads, data)
    if not isinstance(trace, dict) or trace.get('icao') != icao:
        raise ValueError('Źródło zwróciło inny identyfikator samolotu.')
    return trace


async def candidates(client, requested):
    service = AircraftService(client, clock)
    data = await service.fetch()
    if data['status'] == 'error':
        raise ValueError(data['message'])
    items = [item for item in data['items'] if item['id'] and not item['military']
             and not item['hex'].startswith('~') and (not requested or item['id'] == requested)]
    items.sort(key=lambda item: (not item['id'].startswith('LOT'), item['hex']))
    return [item['hex'] for item in items[:3]]


async def _capture_one(client, radar, icao, callsign, *, current):
    if not re.fullmatch('[0-9a-f]{6}', icao):
        raise ValueError('Nieprawidłowy identyfikator ICAO.')
    async with asyncio.timeout(CAPTURE_TIMEOUT):
        trace = await download_trace(client, icao)
        if trace is None:
            raise NoReplayHistory('Brak śladu wybranego samolotu w adsb.lol.')
        metadata = await radar.metadata()
        if metadata.get('status') != 'success' or not metadata.get('frames'):
            raise RadarUnavailable(metadata.get('message') or 'Brak odczytu RainViewer.')
        times = [frame['timestamp'] for frame in metadata['frames']]
        selected = await asyncio.to_thread(select_leg, trace, times, callsign, current=current)
        if not selected:
            raise NoReplayHistory('Brak ciągłego odcinka nad Polską z co najmniej dwiema klatkami radaru.')
        name, points, stamps = selected
        episode = describe(name, icao, points)
        images = {}
        # RadarService limits the manifest to 13 frames and enforces its shared
        # tile cache, request budget and provider backoff across all consumers.
        for time in stamps:
            for x, y in TILES:
                images[time, Z, x, y] = await radar.tile(time, Z, x, y)
        return episode, images


async def capture_recent(client, radar, icao, callsign=''):
    """Manual UI capture. NoReplayHistory alone means recording can be offered."""
    return await _capture_one(client, radar, icao.strip().lower(), (callsign or '').strip().upper(), current=True)


async def capture(client, icao, callsign):
    """CLI discovery can select a named earlier leg of the chosen aircraft."""
    radar = RadarService(client, clock)
    identities = [icao] if icao else await candidates(client, callsign)
    for identity in identities:
        try:
            return await _capture_one(client, radar, identity, callsign, current=False)
        except NoReplayHistory:
            if icao:
                raise
    raise NoReplayHistory('Brak odpowiedniego śladu z pokryciem radaru. '
                          'Podaj --icao i opcjonalnie --callsign albo zaimportuj wcześniejszy zapis.')


def describe(name, identity, points):
    identity = identity.strip().lower()
    name = (name or '').strip().upper()
    metadata = {
        'icao': identity,
        'label': f'{name} · {identity.upper()}' if name else identity.upper(),
        'flight_source': 'adsb.lol (ODbL 1.0)',
        'flight_source_url': 'https://www.adsb.lol/about',
        'radar_source': 'Weather data by RainViewer',
        'radar_source_url': 'https://www.rainviewer.com/',
        'points': points,
        'note': 'Raporty ADS-B nad Polską. Wysokość geometryczna w metrach, kurs nad ziemią. '
                'Czas radaru oznacza utworzenie kompozytu. Przezroczystość oznacza brak echa '
                'lub brak pokrycia; radar nie określa wysokości opadów.',
    }
    if name:
        metadata['callsign'] = name
    return metadata


def read_saved(source: Path):
    replay = FlightReplay(source)
    snapshot = replay.load()
    images = {}
    total = 0
    for key in snapshot.files:
        body = replay.read_tile(snapshot.revision, key)
        total += len(body)
        if total > MAX_IMPORT_BYTES:
            raise ValueError('Rozmiar kafli przekracza limit importu 64 MiB.')
        images[key] = body
    metadata = {k: v for k, v in snapshot.public.items() if k in Episode.model_fields and k != 'frames'}
    return metadata, images


def check_png(body):
    if (not body.startswith(b'\x89PNG\r\n\x1a\n') or body[12:16] != b'IHDR'
            or not body.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82')):
        raise ValueError('Niepełny plik PNG radaru.')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', NotGeoreferencedWarning)
        with MemoryFile(body) as buf, buf.open() as image:
            if image.driver != 'PNG' or not 1 <= image.width == image.height <= 512:
                raise ValueError('Nieprawidłowy rozmiar PNG radaru.')
            image.read()


def publish(destination, episode, images):
    """A validated generation becomes visible only after all its PNGs exist."""
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination) as temp:
        work = Path(temp)
        frames = {}
        for (time, z, x, y), body in sorted(images.items()):
            digest = sha256(body).hexdigest()
            file = f'tiles/{digest}.png'
            staged = work / (digest + '.png')
            if not staged.exists():
                check_png(body)
                staged.write_bytes(body)
            frames.setdefault(time, []).append({'x': x, 'y': y, 'z': z, 'file': file})
        manifest = Episode(**episode, frames=[{'time': t, 'tiles': v} for t, v in frames.items()])
        raw = manifest.model_dump_json(exclude_none=True).encode()
        if len(raw) > MAX_MANIFEST:
            raise ValueError('Manifest przekracza limit rozmiaru.')
        (work / 'episode.json').write_bytes(raw)
        tiles = destination / 'tiles'
        tiles.mkdir(exist_ok=True)
        for png in work.glob('*.png'):
            png.replace(tiles / png.name)
        (work / 'episode.json').replace(destination / 'episode.json')
    return manifest
