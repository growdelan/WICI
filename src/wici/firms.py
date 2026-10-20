"""NASA FIRMS VIIRS observations, separate from official communications."""
import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

PRODUCTS = ('VIIRS_NOAA20_NRT', 'VIIRS_NOAA21_NRT', 'VIIRS_SNPP_NRT')
PUBLIC_URL = 'https://firms.modaps.eosdis.nasa.gov/'
BBOX = '14,49,24.2,55'
REQUIRED = {'latitude', 'longitude', 'acq_date', 'acq_time', 'satellite', 'instrument', 'confidence', 'frp'}


@lru_cache(maxsize=1)
def provinces():
    features = json.loads((Path(__file__).with_name('static') / 'geo/provinces.geojson').read_text())['features']
    prepared = []
    for feature in features:
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        points = [p for polygon in polygons for ring in polygon for p in ring]
        bounds = (min(p[0] for p in points), min(p[1] for p in points),
                  max(p[0] for p in points), max(p[1] for p in points))
        prepared.append((feature['properties'], polygons, bounds))
    return prepared


def in_ring(x, y, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a
        bx, by = b
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        if abs(cross) < 1e-10 and min(ax, bx)-1e-10 <= x <= max(ax, bx)+1e-10 and min(ay, by)-1e-10 <= y <= max(ay, by)+1e-10:
            return True
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
    return inside


def province_at(longitude, latitude):
    for properties, polygons, (west, south, east, north) in provinces():
        if not west <= longitude <= east or not south <= latitude <= north:
            continue
        if any(in_ring(longitude, latitude, polygon[0])
               and not any(in_ring(longitude, latitude, hole) for hole in polygon[1:]) for polygon in polygons):
            return properties
    return None


def parse_csv(text, product):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
        raise ValueError('Nieprawidłowy nagłówek CSV FIRMS')
    observations, invalid = [], 0
    for row in reader:
        try:
            latitude, longitude, frp = float(row['latitude']), float(row['longitude']), float(row['frp'])
            if not all(math.isfinite(v) for v in (latitude, longitude, frp)) or frp < 0 or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError('Nieprawidłowa liczba')
            raw_clock = row['acq_time'].strip()
            if not 1 <= len(raw_clock) <= 4 or not raw_clock.isascii() or not raw_clock.isdigit():
                raise ValueError('Nieprawidłowy czas')
            clock = raw_clock.zfill(4)
            observed = datetime.strptime(row['acq_date'] + clock, '%Y-%m-%d%H%M').replace(tzinfo=UTC)
            satellite, instrument = row['satellite'].strip(), row['instrument'].strip()
            confidence = row['confidence'].strip().lower()
            if not satellite or instrument.upper() != 'VIIRS' or confidence not in ('l', 'n', 'h', 'low', 'nominal', 'high'):
                raise ValueError('Nieprawidłowe pola VIIRS')
            province = province_at(longitude, latitude)
            if province is None:
                continue
            observed_at = observed.isoformat()
            identity = f'{product}|{satellite}|{observed_at}|{latitude:.6f}|{longitude:.6f}'
            observations.append({'id': hashlib.sha256(identity.encode()).hexdigest(), 'product': product,
                'satellite': satellite, 'instrument': instrument, 'latitude': latitude, 'longitude': longitude,
                'observed_at': observed_at, 'confidence': confidence, 'frp': frp,
                'voivodeship': province['admin_code'], 'voivodeship_name': province['name']})
        except (TypeError, ValueError, KeyError, AttributeError):
            invalid += 1
    return observations, invalid


@dataclass
class FireResult:
    observations: list[dict] = field(default_factory=list)
    status: str = 'success'
    coverage: str = ''
    message: str = ''
    invalid: int = 0
    availability: str = 'enabled'
    retry_after: int = 0


async def fetch_fires(client, config, now):
    key = config.firms_key()
    if not key or not config.enabled('firms'):
        return FireResult(status='disabled', coverage='Pobieranie wyłączone; brak klucza lub źródło wyłączone')
    result = FireResult()
    succeeded, failed = [], []
    # UTC API dates are explicit: three civil days cover a rolling 48-hour view.
    start = (now.astimezone(UTC).date()-timedelta(days=2)).isoformat()
    denied = 0
    for product in PRODUCTS:
        url = f'{PUBLIC_URL}api/area/csv/{key}/{product}/{BBOX}/3/{start}'
        try:
            async with client.stream('GET', url, timeout=config.timeout_seconds, follow_redirects=False) as response:
                if response.status_code != 200:
                    if response.status_code in (401,403):
                        denied += 1
                    if response.status_code in (429,503):
                        try:
                            result.retry_after = max(result.retry_after, min(86400,int(response.headers.get('retry-after','3600'))))
                        except ValueError:
                            result.retry_after = max(result.retry_after,3600)
                    failed.append(f'{product} (HTTP {response.status_code})')
                    continue
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > config.max_response_bytes:
                        raise ValueError('Zbyt duża odpowiedź FIRMS')
            records, invalid = parse_csv(body.decode('utf-8'), product)
            result.observations.extend(records)
            result.invalid += invalid
            succeeded.append(product)
        except Exception:  # noqa: BLE001 — remote messages and secret-bearing URLs must never escape.
            failed.append(product)
    result.status = 'partial' if failed or result.invalid else 'success'
    if not succeeded:
        result.status = 'error'
        if denied == len(PRODUCTS):
            result.availability = 'blocked_access'
    result.coverage = f'Polska / lokalne granice PRG; {len(succeeded)}/{len(PRODUCTS)} produktów VIIRS; ostatnie 3 dni UTC'
    if failed:
        result.message = 'Nie udało się pobrać: ' + ', '.join(failed) + '; zachowano zapisane obserwacje'
    if result.invalid:
        result.message += f'; pominięto {result.invalid} błędnych rekordów'
    return result
