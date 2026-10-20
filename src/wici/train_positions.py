"""Conservative estimates along provider GTFS shapes, using explicit realtime times.

The feed supplies no GPS observations. Missing times/distances and detours never
fall back to straight-line movement or to scheduled vehicle positions.
"""
import bisect
import csv
import io
import math
import time
import zlib
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from wici.aircraft import in_poland

CACHE_SECONDS = 15
VALID_SECONDS = 30
MAX_ITEMS = 1500
MAX_PROFILES = 8
MAX_LEGS = 1024
MAX_RETAINED_POINTS = 100000
MAX_PROFILE_POINTS = 100000
MAX_CANDIDATES = 2500
MAX_COMPUTE_SECONDS = 10
MAX_STOP_OFFSET_METRES = 500


def metres(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742000 * math.asin(min(1, math.sqrt(value)))


def distance(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def interval(entries, update, epoch):
    """Return one explicit dwell or consecutive-stop live interval containing now."""
    live = update.get('stops', {})
    sequences = [entry[1] for entry in entries]
    sequence_set = set(sequences)
    if len(sequence_set) != len(sequences) or any(s not in sequence_set for s in live):
        return None
    previous, candidates = None, []
    for index, entry in enumerate(entries):
        stop = live.get(entry[1])
        if not stop:
            continue
        arrival, departure = stop[1:3]
        values = [value for value in (arrival, departure) if value is not None]
        if values and previous is not None and min(values) < previous:
            return None
        if arrival is not None and departure is not None and arrival > departure:
            return None
        if values:
            previous = max(values)
        if stop[3]:
            continue
        if arrival is not None and departure is not None and arrival <= epoch < departure:
            candidates.append((entry, entry, arrival, departure))
        if departure is not None and index + 1 < len(entries):
            following = entries[index + 1]
            next_live = live.get(following[1])
            if next_live and not next_live[3] and next_live[1] is not None:
                end = next_live[1]
                if departure > end:
                    return None
                if departure <= epoch < end:
                    candidates.append((entry, following, departure, end))
    return candidates[0] if len(candidates) == 1 else None


def point_at(points, distances, target):
    if not distances or target < distances[0] or target > distances[-1]:
        return None
    index = bisect.bisect_right(distances, target) - 1
    if index == len(points) - 1:
        return list(points[index])
    span = distances[index + 1] - distances[index]
    if span <= 0:
        return None
    fraction = (target - distances[index]) / span
    return [points[index][axis] + fraction * (points[index + 1][axis] - points[index][axis])
            for axis in (0, 1)]


class PositionEstimator:
    def __init__(self, timetable):
        self.timetable = timetable
        self.profiles = OrderedDict()
        self.legs = OrderedDict()
        self.profile_points = self.leg_points = 0

    def profile(self, shape_id):
        if shape_id in self.profiles:
            self.profiles.move_to_end(shape_id)
            return self.profiles[shape_id]
        result = self.read_profile(shape_id)
        self.profiles[shape_id] = result
        self.profile_points += len(result[0]) if result else 0
        while len(self.profiles) > MAX_PROFILES or self.profile_points > MAX_RETAINED_POINTS:
            _, removed = self.profiles.popitem(last=False)
            self.profile_points -= len(removed[0]) if removed else 0
        return result

    def read_profile(self, shape_id):
        rows = []
        for block in self.timetable.shapes.get(shape_id, []):
            for row in csv.DictReader(io.StringIO(zlib.decompress(block).decode('utf-8')),
                                      fieldnames=self.timetable.shape_columns):
                value = distance(row.get('shape_dist_traveled'))
                lat, lon = float(row['shape_pt_lat']), float(row['shape_pt_lon'])
                if value is None or not math.isfinite(lat) or not math.isfinite(lon):
                    return None
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    return None
                rows.append((int(row['shape_pt_sequence']), [lon, lat], value))
                if len(rows) > MAX_PROFILE_POINTS:
                    return None
        rows.sort(key=lambda row: row[0])
        if len(rows) < 2 or len({r[0] for r in rows}) != len(rows):
            return None
        points, distances = [], []
        for _, point, value in rows:
            if distances and value <= distances[-1]:
                if value == distances[-1] and metres(point, points[-1]) <= 1:
                    continue  # Identical shape vertices at a shared track node are harmless.
                return None
            points.append(point)
            distances.append(value)
        return (points, distances) if len(points) > 1 else None

    def leg(self, shape_id, start, end):
        if len(start) < 6 or len(end) < 6 or start[5] is None or end[5] is None:
            return None
        lower, upper = start[5], end[5]
        if lower > upper or (start[1] != end[1] and lower == upper):
            return None
        key = (shape_id, start[0], end[0], lower, upper)
        if key in self.legs:
            self.legs.move_to_end(key)
            return self.legs[key]
        profile = self.profile(shape_id)
        if profile is None:
            return None
        points, distances = profile
        first, last = point_at(points, distances, lower), point_at(points, distances, upper)
        if first is None or last is None:
            return None
        for entry, point in ((start, first), (end, last)):
            station = self.timetable.stops[entry[0]]
            if metres(point, (station['longitude'], station['latitude'])) > MAX_STOP_OFFSET_METRES:
                return None
        left, right = bisect.bisect_right(distances, lower), bisect.bisect_left(distances, upper)
        result = ([first, *points[left:right], last], [lower, *distances[left:right], upper])
        if lower == upper:
            result = ([first], [lower])
        self.legs[key] = result
        self.leg_points += len(result[0])
        while len(self.legs) > MAX_LEGS or self.leg_points > MAX_RETAINED_POINTS:
            _, removed = self.legs.popitem(last=False)
            self.leg_points -= len(removed[0])
        return result

    def estimate(self, updates, now, source_at, stale_seconds):
        epoch, items, considered = now.timestamp(), [], 0
        started = time.monotonic()
        source_end = source_at + timedelta(seconds=stale_seconds)
        if now >= source_end:
            return items
        for (trip_id, day), update in updates.items():
            if time.monotonic() - started > MAX_COMPUTE_SECONDS:
                break
            info = self.timetable.trips.get(trip_id)
            if (not info or update.get('cancelled') or update.get('detour') or
                    not self.timetable.active(info['service'], day)):
                continue
            entries = self.timetable.times.get(trip_id, [])
            bracket = interval(entries, update, epoch)
            if bracket is None:
                continue
            considered += 1
            if considered > MAX_CANDIDATES:
                break
            start, end, start_time, end_time = bracket
            leg = self.leg(info['shape'], start, end)
            if leg is None:
                continue
            points, distances = leg
            fraction = (epoch - start_time) / (end_time - start_time)
            target = distances[0] + fraction * (distances[-1] - distances[0])
            point = points[0] if len(points) == 1 else point_at(points, distances, target)
            if point is None or not in_poland(point[1], point[0]):
                continue
            valid_until = min(source_end, now + timedelta(seconds=VALID_SECONDS),
                              datetime.fromtimestamp(end_time, UTC))
            items.append({'id': f'{trip_id}|{day.isoformat()}', 'trip_id': trip_id,
                          'start_date': day.isoformat(),
                          **{key: info[key] for key in ('number', 'headsign', 'operator')},
                          'latitude': point[1], 'longitude': point[0], 'estimated': True,
                          'estimated_at': now.isoformat(), 'source_updated_at': source_at.isoformat(),
                          'from_station': self.timetable.stops[start[0]]['name'],
                          'to_station': self.timetable.stops[end[0]]['name'],
                          'valid_until': valid_until.isoformat()})
            if len(items) >= MAX_ITEMS:
                break
        return items
