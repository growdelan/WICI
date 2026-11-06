"""Prepare one offline flight replay in var/live/flight-replay (personal/educational use).

With no arguments, use one adsb.fi snapshot to identify civil aircraft over Poland,
then try at most three individual adsb.lol traces in RainViewer's last two hours.
--icao skips discovery. --import-episode installs an existing local episode folder.
"""
import argparse
import asyncio
import json
import re
import sys
import warnings
from bisect import bisect_right
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastapi import HTTPException
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from wici.aircraft import AircraftService, in_poland
from wici.flight_replay import MAX_MANIFEST, Episode, FlightReplay
from wici.radar import MAX_ZOOM, RadarService, RadarUnavailable, tile_allowed

DEST = Path(__file__).resolve().parents[1] / 'var/live/flight-replay'
SOURCE = 'https://adsb.lol'
Z = MAX_ZOOM
TILES = [(x, y) for x in range(2**Z) for y in range(2**Z) if tile_allowed(Z, x, y)]
MAX_AGE = 600  # RainViewer composite cadence (seconds).
MIN_DURATION = 300
MAX_IMPORT_BYTES = 64 * 1024 * 1024


def clock():
    return datetime.now(UTC)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def frame_at(times, time):
    index = bisect_right(times, time) - 1
    if index >= 0 and time - times[index] < MAX_AGE:
        return times[index]
    return None


def select_leg(trace, times, requested=''):
    """Keep real, contiguous airborne fixes of a single callsign over Poland."""
    best = []
    best_callsign = ''
    points = []
    callsign = ''
    if not isinstance(trace, dict) or not numeric(trace.get('timestamp')) or not isinstance(trace.get('trace'), list):
        raise ValueError('Nieprawidłowy ślad adsb.lol.')
    epoch = trace['timestamp']
    for row in trace['trace']:
        if not isinstance(row, list) or len(row) < 9 or not isinstance(row[6], int):
            raise ValueError('Nieprawidłowy raport adsb.lol.')
        offset, lat, lon, altitude, _, course, flags = row[:7]
        if not numeric(offset):
            raise ValueError('Nieprawidłowy czas raportu.')
        details = {} if row[8] is None else row[8]
        if not isinstance(details, dict) or not isinstance(details.get('flight', ''), str):
            raise TypeError('Nieprawidłowa identyfikacja lotu.')
        before = callsign
        if flags & 2 or altitude == 'ground':
            callsign = ''
        if details.get('flight'):
            callsign = details['flight'].strip()
        time = round(epoch + offset)
        if callsign != before or flags & 2 or (points and time - points[-1]['time'] > 120):
            points = []
        if (not callsign or (requested and callsign != requested) or frame_at(times, time) is None
                or altitude == 'ground' or not numeric(lat) or not numeric(lon) or not in_poland(lat, lon)):
            points = []
            continue
        # readsb trace field 10 is geometric altitude in feet. Bit 8 designates
        # field 3 as geometric for aircraft with no barometric altitude.
        geometric = altitude if flags & 8 else (row[10] if len(row) > 10 else None)
        if not numeric(geometric):
            continue
        sample = {'time': time, 'lat': lat, 'lon': lon, 'alt_m': round(geometric * 0.3048, 3)}
        if numeric(course) and 0 <= course <= 360:
            sample['heading'] = course
        if points and time == points[-1]['time']:
            points[-1] = sample
        elif not points or time > points[-1]['time']:
            points.append(sample)
        else:
            raise ValueError('Nieuporządkowane czasy raportów adsb.lol.')
        # Commit the list reference, not a deep copy on each sample.
        duration = time - points[0]['time']
        if (duration >= MIN_DURATION and frame_at(times, points[0]['time']) != frame_at(times, time)
                and (not best or duration > best[-1]['time'] - best[0]['time'])):
            best = points
            best_callsign = callsign
    if not best:
        return None
    frames = [t for t in times if frame_at(times, best[0]['time']) <= t <= best[-1]['time']]
    return best_callsign, best, frames


async def download_trace(client, icao):
    url = f'{SOURCE}/data/traces/{icao[-2:]}/trace_full_{icao}.json'
    async with client.stream('GET', url) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(data) + len(chunk) > 8 * 1024 * 1024:
                raise ValueError('Ślad przekracza limit rozmiaru.')
            data.extend(chunk)
        trace = json.loads(data)
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


async def capture(client, icao, callsign):
    radar = RadarService(client, clock)
    metadata = await radar.metadata()
    times = [frame['timestamp'] for frame in metadata['frames']]
    if not times:
        raise ValueError(metadata['message'] or 'Brak rzeczywistych klatek RainViewer.')
    for identity in ([icao] if icao else await candidates(client, callsign)):
        trace = await download_trace(client, identity)
        selected = select_leg(trace, times, callsign) if trace else None
        if selected:
            name, points, stamps = selected
            episode = describe(name, identity, points)
            images = {}
            for time in stamps:
                for x, y in TILES:
                    images[time, Z, x, y] = await radar.tile(time, Z, x, y)
            return episode, images
    raise ValueError('Brak ciągłego odcinka nad Polską z co najmniej dwiema klatkami radaru. '
                     'Podaj --icao i opcjonalnie --callsign albo zaimportuj wcześniejszy zapis.')


def describe(name, identity, points):
    return {'label': f'{name} · {identity.upper()}', 'flight_source': 'adsb.lol (ODbL 1.0)',
                'flight_source_url': 'https://www.adsb.lol/about', 'radar_source': 'Weather data by RainViewer',
                'radar_source_url': 'https://www.rainviewer.com/', 'points': points,
                'note': 'Raporty ADS-B nad Polską. Wysokość geometryczna w metrach, kurs nad ziemią. '
                     'Czas radaru oznacza utworzenie kompozytu. Przezroczystość oznacza brak echa '
                     'lub brak pokrycia; radar nie określa wysokości opadów.'}


def read_saved(source):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--icao', help='6 cyfr szesnastkowych ICAO wybranego samolotu')
    group.add_argument('--import-episode', type=Path, metavar='KATALOG', help='wczytaj zapis offline')
    parser.add_argument('--callsign', default='', help='wybierz konkretny znak lotu')
    args = parser.parse_args()
    if args.icao and not re.fullmatch('[a-fA-F0-9]{6}', args.icao):
        parser.error('--icao wymaga 6 cyfr szesnastkowych')
    if args.import_episode and args.callsign:
        parser.error('--callsign dotyczy wyłącznie pobierania')

    async def run():
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            return await capture(client, args.icao.lower() if args.icao else None, args.callsign.upper())
    try:
        episode, images = read_saved(args.import_episode) if args.import_episode else asyncio.run(run())
        result = publish(DEST, episode, images)
    except (KeyError, TypeError, ValueError, HTTPException, OSError, httpx.HTTPError, RadarUnavailable) as exc:
        sys.exit(f'Nie zapisano lotu: {exc}')
    start = datetime.fromtimestamp(result.points[0].time, UTC).isoformat()
    end = datetime.fromtimestamp(result.points[-1].time, UTC).isoformat()
    print(f'{result.label}: {start} – {end}; {len(result.points)} pozycji, {len(result.frames)} klatek. '
          f'{DEST / "episode.json"}')


if __name__ == '__main__':
    main()
