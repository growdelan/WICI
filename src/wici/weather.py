"""On-demand, bounded weather snapshots; no polling or user-supplied upstream URLs.

IMGW timestamps are meteorological UTC, wind m/s; direction means *from*.
Open-Meteo precipitation is the preceding hour sum, not radar rainfall.
"""
import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

IMGW_URL = 'https://danepubliczne.imgw.pl/api/data/meteo/'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
VARIABLES = ('wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'precipitation')
MAX_BYTES = 4 * 1024 * 1024
REFRESH = {'measurement': 600, 'forecast': 3600}


def number(value, low, high):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def inside_ring(lat, lon, ring):
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        if (y1 > lat) != (y2 > lat) and lon < (x2-x1)*(lat-y1)/(y2-y1)+x1:
            inside = not inside
        previous = current
    return inside


def forecast_grid():
    """Approximately 70 km spacing, clipped to the bundled PRG border; no geo dependencies."""
    geometry = json.loads((Path(__file__).parent/'static/geo/poland-border.geojson').read_text())['geometry']
    if geometry['type'] == 'LineString':
        polygons = [[geometry['coordinates']]]
    elif geometry['type'] == 'Polygon':
        polygons = [geometry['coordinates']]
    elif geometry['type'] == 'MultiPolygon':
        polygons = geometry['coordinates']
    else:
        raise ValueError('Unsupported Poland border')
    return tuple((round(49.3+i*0.65, 2), round(14.5+j, 2))
                 for i in range(9) for j in range(10)
                 if any(inside_ring(49.3+i*0.65, 14.5+j, polygon[0]) and not any(
                     inside_ring(49.3+i*0.65, 14.5+j, hole) for hole in polygon[1:]) for polygon in polygons))


GRID = forecast_grid()
# A finite set of bundled PRG regions keeps cache cardinality bounded (17 scopes).
PROVINCES = {str(f['properties']['admin_code']): f['geometry'] for f in json.loads(
    (Path(__file__).parent/'static/geo/provinces.geojson').read_text())['features']}


def in_region(lat, lon, code):
    if not code:
        return True
    geometry = PROVINCES[code]
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    return any(inside_ring(lat, lon, polygon[0]) and not any(
        inside_ring(lat, lon, hole) for hole in polygon[1:]) for polygon in polygons)


REGION_GRIDS = {code: tuple(p for p in GRID if in_region(*p, code)) for code in PROVINCES}


class WeatherService:
    def __init__(self, client, clock, timeout=20, demo=False, measurement_enabled=True,
                 forecast_enabled=True):
        self.client, self.clock, self.timeout, self.demo = client, clock, timeout, demo
        self.enabled = {'measurement': measurement_enabled, 'forecast': forecast_enabled}
        self.locks = {mode: asyncio.Lock() for mode in REFRESH}
        self.cache, self.retry_at, self.failures = {}, {}, {}

    def base(self, mode):
        return {'mode': mode, 'enabled': bool(self.enabled[mode]), 'status': 'ready', 'message': '',
                'stale': False, 'fetched_at': None, 'refresh_seconds': REFRESH[mode],
                'times': [], 'points': [], 'precipitation_period_minutes': 10 if mode == 'measurement' else 60,
                'source_url': 'https://danepubliczne.imgw.pl/apiinfo' if mode == 'measurement'
                              else 'https://open-meteo.com/',
                'source_name': 'IMGW-PIB' if mode == 'measurement' else 'Open-Meteo',
                'demo': self.demo}

    async def fetch(self, mode='measurement', voivodeship=''):
        if mode not in REFRESH:
            raise ValueError('Nieprawidłowy tryb pogody')
        if voivodeship and voivodeship not in PROVINCES:
            raise ValueError('Nieprawidłowe województwo')
        # National observation files are shared; only model requests can be regional.
        key = f'{mode}:{voivodeship}' if mode == 'forecast' and voivodeship else mode
        grid = REGION_GRIDS[voivodeship] if voivodeship else GRID
        async with self.locks[mode]:
            now = self.clock().astimezone(UTC)
            result = self.base(mode)
            if not self.enabled[mode]:
                return {**result, 'status': 'disabled', 'message': 'Warstwa pogody wyłączona w konfiguracji.'}
            cached = self.cache.get(key)
            if cached and now < cached[0]:
                return dict(cached[1])
            if self.demo:
                data = self.demo_data(mode, now)
                if mode == 'forecast' and voivodeship:
                    data['points'] = [p for p in data['points'] if in_region(p['latitude'], p['longitude'], voivodeship)]
                self.cache[key] = (now+timedelta(seconds=REFRESH[mode]), data)
                return dict(data)
            if now < self.retry_at.get(mode, now):
                return self.error_result(mode, cached)
            try:
                if mode == 'measurement':
                    payload = await self.download(IMGW_URL, {}, mode, now)
                    times, points = self.measurements(payload, now)
                else:
                    start = now.replace(minute=0, second=0, microsecond=0)
                    params = {'latitude': ','.join(str(p[0]) for p in grid),
                              'longitude': ','.join(str(p[1]) for p in grid),
                              'hourly': ','.join(VARIABLES), 'wind_speed_unit': 'kmh',
                              'precipitation_unit': 'mm', 'timezone': 'GMT',
                              'start_hour': start.strftime('%Y-%m-%dT%H:%M'),
                              'end_hour': (start+timedelta(hours=47)).strftime('%Y-%m-%dT%H:%M')}
                    payload = await self.download(FORECAST_URL, params, mode, now)
                    times, points = self.forecasts(payload, start, grid)
                if not points or not times:
                    raise ValueError('No usable weather data')
                result.update(times=times, points=points, fetched_at=now.isoformat())
                self.cache[key] = (now+timedelta(seconds=REFRESH[mode]), result)
                self.retry_at.pop(mode, None)
                self.failures.pop(mode, None)
                return dict(result)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
                self.retry_at[mode] = max(self.retry_at.get(mode, now), now+timedelta(seconds=300))
                self.failures[mode] = 'Źródło pogody chwilowo niedostępne; ponowienie za kilka minut.'
                return self.error_result(mode, cached)

    def error_result(self, mode, cached):
        return {**(cached[1] if cached else self.base(mode)), 'status': 'error',
                'stale': bool(cached), 'message': self.failures[mode]}

    async def download(self, url, params, mode, now):
        async with self.client.stream('GET', url, params=params, timeout=self.timeout,
                                      follow_redirects=False, headers={'Accept': 'application/json'}) as response:
            if response.status_code != 200:
                if response.status_code == 429:
                    retry = response.headers.get('retry-after', '')
                    try:
                        delay = float(retry)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(retry).astimezone(UTC)-now).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            delay = 300
                    if math.isfinite(delay):
                        self.retry_at[mode] = now+timedelta(seconds=max(300, min(delay, 86400)))
                raise ValueError('Weather source unavailable')
            if response.headers.get('content-type', '').split(';')[0] != 'application/json':
                raise ValueError('Weather response is not JSON')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError('Weather response too large')
            return json.loads(body)

    def measurements(self, payload, now):
        if not isinstance(payload, list) or len(payload) > 5000:
            raise ValueError('Invalid IMGW snapshot')
        points, observed_times, seen = [], [], set()
        for station in payload:
            if not isinstance(station, dict):
                continue
            lat, lon = number(station.get('lat'), 49, 55), number(station.get('lon'), 14, 24.3)
            identity, name = station.get('kod_stacji'), station.get('nazwa_stacji')
            if lat is None or lon is None or not isinstance(identity, str) or not identity or len(identity) > 40:
                continue
            if identity in seen or not isinstance(name, str) or not name or len(name) > 200:
                continue
            seen.add(identity)
            sample = {'time': None}
            fields = [('wind_speed_kmh', 'wiatr_srednia_predkosc', 100, 3.6, 'wind_time'),
                      ('wind_direction_deg', 'wiatr_kierunek', 360, 1, 'wind_direction_time'),
                      ('wind_gust_kmh', 'wiatr_poryw_10min', 150, 3.6, 'wind_gust_time'),
                      ('precipitation_mm', 'opad_10min', 500, 1, 'precipitation_time')]
            for target, field, upper, factor, time_field in fields:
                value, date = number(station.get(field), 0, upper), timestamp(station.get(field+'_data'))
                sample[time_field] = date.isoformat() if date else None
                # Old sporadic gust reports must not masquerade as current gusts.
                fresh = date and timedelta(minutes=-15) <= now-date <= timedelta(hours=2)
                sample[target] = round(value*factor, 3) if value is not None and fresh else None
                if sample[target] is not None:
                    observed_times.append(date)
            if all(sample[field[0]] is None for field in fields):
                continue
            # A wind vector requires speed and direction from the same observation interval.
            speed_time, direction_time = timestamp(sample['wind_time']), timestamp(sample['wind_direction_time'])
            if speed_time and direction_time and abs(speed_time-direction_time) > timedelta(minutes=10):
                sample['wind_direction_deg'] = None
            points.append({'id': identity, 'name': name, 'latitude': lat, 'longitude': lon, 'samples': [sample]})
        times = [max(observed_times).isoformat()] if observed_times else []
        for point in points:
            point['samples'][0]['time'] = times[0]
        return times, points

    def forecasts(self, payload, start, grid=GRID):
        if len(grid) == 1 and isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list) or len(payload) != len(grid):
            raise ValueError('Invalid forecast locations')
        times = [(start+timedelta(hours=i)).isoformat() for i in range(48)]
        points = []
        for location, (lat, lon) in zip(payload, grid, strict=True):
            if not isinstance(location, dict) or location.get('utc_offset_seconds') != 0:
                raise ValueError('Invalid forecast timezone')
            hourly, units = location.get('hourly', {}), location.get('hourly_units', {})
            if not isinstance(hourly, dict) or not isinstance(units, dict):
                raise TypeError('Invalid forecast format')
            if units.get('wind_speed_10m') != 'km/h' or units.get('wind_gusts_10m') != 'km/h' or (
                    units.get('precipitation') != 'mm' or units.get('wind_direction_10m') != '°'):
                raise ValueError('Invalid forecast units')
            provider_times = hourly.get('time')
            if not isinstance(provider_times, list) or len(provider_times) != 48 or [
                    date.isoformat() if (date := timestamp(t)) else None for t in provider_times] != times:
                raise ValueError('Invalid forecast hours')
            if any(not isinstance(hourly.get(v), list) or len(hourly[v]) != 48 for v in VARIABLES):
                raise ValueError('Incomplete forecast arrays')
            samples = []
            for i, time in enumerate(times):
                samples.append({'time': time, 'wind_time': time, 'wind_direction_time': time,
                                'wind_gust_time': time, 'precipitation_time': time,
                                'wind_speed_kmh': number(hourly[VARIABLES[0]][i], 0, 360),
                                'wind_direction_deg': number(hourly[VARIABLES[1]][i], 0, 360),
                                'wind_gust_kmh': number(hourly[VARIABLES[2]][i], 0, 540),
                                'precipitation_mm': number(hourly[VARIABLES[3]][i], 0, 500)})
            if not any(any(s[k] is not None for k in ('wind_speed_kmh', 'precipitation_mm')) for s in samples):
                continue
            points.append({'id': f'forecast-{lat}-{lon}', 'name': f'Prognoza {lat:.2f}°N, {lon:.2f}°E',
                           'latitude': lat, 'longitude': lon, 'samples': samples})
        return times, points

    def demo_data(self, mode, now):
        start = now.replace(minute=0, second=0, microsecond=0)
        times = [(start+timedelta(hours=i)).isoformat() for i in range(48 if mode == 'forecast' else 1)]
        points = []
        locations = GRID if mode == 'forecast' else ((52.23, 21.01), (54.35, 18.65), (50.06, 19.94),
                                                       (51.11, 17.04), (52.41, 16.93), (53.43, 14.55))
        for j, (lat, lon) in enumerate(locations):
            samples = []
            for i, time in enumerate(times):
                speed = round(15+12*math.sin(j*.6+i*.15), 1)
                samples.append({'time': time, 'wind_time': time, 'wind_direction_time': time,
                                'wind_gust_time': time, 'precipitation_time': time,
                                'wind_speed_kmh': speed, 'wind_direction_deg': (240+j*13+i*4) % 360,
                                'wind_gust_kmh': round(speed+12, 1),
                                'precipitation_mm': round(max(0, 3*math.sin(j*.8-i*.2)), 1)})
            points.append({'id': f'demo-{j}', 'name': f'DEMO — punkt {j+1}',
                           'latitude': lat, 'longitude': lon, 'samples': samples})
        return {**self.base(mode), 'status': 'demo', 'message': 'DEMO — dane syntetyczne, bez połączeń z siecią.',
                'fetched_at': now.isoformat(), 'times': times, 'points': points,
                'source_name': 'DEMO — dane syntetyczne'}
