"""Offline PRG/transport benchmarks with pre-optimization algorithms as references.

Run: uv run --locked --offline python scripts/benchmark_services.py --runs 7
Only bundled geometry and deterministic synthetic positions are used. No database,
network, configuration, downsampling, provider timing or wall-clock time is used.
"""
import argparse
import copy
import json
import random
import statistics
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from wici import aircraft, firms, geo, weather
from wici.monitor_epochs import receipt, stamp_payload
from wici.moving_ingestion import MovingIngestion


def raw_provinces():
    result = []
    for feature in geo.features():
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        result.append((feature['properties'], geometry, polygons,
                       geo.province_bounds()[feature['properties']['admin_code']]))
    return result


RAW = raw_provinces()
AIRCRAFT_RINGS = tuple(((min(p[0] for p in rings[0]), min(p[1] for p in rings[0]),
                        max(p[0] for p in rings[0]), max(p[1] for p in rings[0])), rings)
                       for _, _, polygons, _ in RAW for rings in polygons)


def reference_provinces(lon, lat):
    return sorted(properties['admin_code'] for properties, geometry, _, (w, s, e, n) in RAW
                  if w <= lon <= e and s <= lat <= n and geo.contains(geometry, lon, lat))


def reference_aircraft(lat, lon):
    return any(w <= lon <= e and s <= lat <= n and weather.inside_ring(lat, lon, rings[0])
               and not any(weather.inside_ring(lat, lon, hole) for hole in rings[1:])
               for (w, s, e, n), rings in AIRCRAFT_RINGS)


def reference_firms(lon, lat):
    for properties, _, polygons, (w, s, e, n) in RAW:
        if w <= lon <= e and s <= lat <= n and any(
                firms.in_ring(lon, lat, rings[0]) and not any(firms.in_ring(lon, lat, hole)
                                                           for hole in rings[1:]) for rings in polygons):
            return properties
    return None


def measure(function, runs):
    result = function()
    durations = []
    for _ in range(runs):
        started = time.perf_counter()
        current = function()
        durations.append((time.perf_counter()-started)*1000)
        assert current == result, 'Benchmark changed its output between runs'
    return result, {'median_ms': round(statistics.median(durations), 3),
                    'min_ms': round(min(durations), 3), 'max_ms': round(max(durations), 3)}


def compare(before, after, runs):
    reference, original_time = measure(before, runs)
    result, optimized_time = measure(after, runs)
    assert result == reference, 'Optimized output differs from the original algorithm'
    return {'reference': original_time, 'optimized': optimized_time, 'identical_output': True,
            'median_speedup': round(original_time['median_ms']/optimized_time['median_ms'], 2)}


def transport_payload(points, now):
    return {'now': now.timestamp()*1000, 'msg': 'No error', 'ac': [
        {'hex': f'{index:06x}', 'flight': f'TEST{index}', 'r': 'SP-TST', 't': 'E75S',
         'type': 'adsb_icao', 'category': 'A3', 'lat': lat, 'lon': lon, 'alt_baro': 10000,
         'gs': 250, 'track': 120, 'seen_pos': 3.5} for index, (lon, lat) in enumerate(points)]}


def reference_enqueue(writer, snapshot):
    """Original two-copy path, with the benchmark's empty queues and live repo."""
    received = receipt(writer.moving.repo)
    writer.observations.append(('aircraft', stamp_payload(writer.moving.repo, copy.deepcopy(snapshot), received)))
    writer.pending['aircraft'] = copy.deepcopy(snapshot)
    writer.idle.clear()
    writer.wake.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--points', type=int, default=1000)
    parser.add_argument('--runs', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.points <= 10000 or not 1 <= args.runs <= 100:
        parser.error('points must be 1..10000 and runs 1..100')
    rng = random.Random(20261105)
    points = [(rng.uniform(14, 24.3), rng.uniform(49, 55)) for _ in range(args.points)]
    report = {'points': len(points), 'runs': args.runs, 'seed': 20261105, 'mode': 'offline synthetic', 'cases': {}}
    cases = report['cases']
    cases['province_assignment'] = compare(lambda: [reference_provinces(lon, lat) for lon, lat in points],
                                           lambda: [geo.provinces_for_point(lon, lat) for lon, lat in points], args.runs)
    cases['aircraft_poland_filter'] = compare(lambda: [reference_aircraft(lat, lon) for lon, lat in points],
                                            lambda: [aircraft.in_poland(lat, lon) for lon, lat in points], args.runs)
    cases['firms_province_filter'] = compare(lambda: [reference_firms(lon, lat) for lon, lat in points],
                                           lambda: [firms.province_at(lon, lat) for lon, lat in points], args.runs)
    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    payload = transport_payload(points, now)
    service = aircraft.AircraftService(None, lambda: now)

    def original_normalize():
        with patch.object(aircraft, 'in_poland', reference_aircraft):
            return service.normalize(payload, now)

    cases['aircraft_normalize'] = compare(original_normalize, lambda: service.normalize(payload, now), args.runs)
    snapshot = {'status': 'ready', 'items': [dict(item, hex=f'{i:06x}') for i, item in
                                          enumerate(service.normalize(transport_payload([(21.01, 52.23)], now), now)
                                                    *args.points)]}
    writer = MovingIngestion(SimpleNamespace(repo=SimpleNamespace()))
    # Measure synchronous admission only; no worker, database or provider runs.
    writer.worker = object()

    def enqueue(reference=False):
        writer.observations.clear()
        writer.pending.clear()
        if reference:
            reference_enqueue(writer, snapshot)
        else:
            writer.enqueue('aircraft', snapshot)
        return dict(writer.pending), list(writer.observations)

    cases['transport_enqueue'] = compare(lambda: enqueue(True), enqueue, args.runs)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
