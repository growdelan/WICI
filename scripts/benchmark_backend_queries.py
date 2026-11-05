"""Offline backend query benchmark using an isolated synthetic SQLite database.

uv run --locked python scripts/benchmark_backend_queries.py --runs 15 --profile
"""
import argparse
import cProfile
import io
import json
import platform
import pstats
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wici.repository import Repository
from wici.sources.normalize import document, location
from wici.workspace_service import WorkspaceService

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def populate(repo, workspace, stations, samples, communications):
    with repo.lock, repo.db:
        for number in range(stations):
            ref = f'hydro_station:imgw:benchmark-{number}'
            workspace.catalog.upsert_station(ref, 'imgw', str(number), f'Stacja {number:04}',
                                             52.2, 21.0, {'province': '14'})
        repo.db.executemany('''INSERT INTO station_measurements
            (object_ref,metric,observed_key,observed_at,value,unit,fetched_at,first_fetched_at,
             revision,quality,content_hash) VALUES(?,'water_level',?,?,?,'cm',?,?,1,'valid','synthetic')''',
            ((f'hydro_station:imgw:benchmark-{number}', at, at, number % 400, NOW.isoformat(), NOW.isoformat())
             for number in range(stations)
             for at in ((NOW-timedelta(minutes=20*(sample+1))).isoformat() for sample in range(samples))))
    for number in range(communications):
        repo.ingest(document('rso', f'benchmark-{number}', 'https://example.org/synthetic',
                             f'Komunikat {number:05}', 'Syntetyczny komunikat na potrzeby pomiaru.',
                             {'locations': [location('14', 'notification_area', 'synthetic')]}, [],
                             source_published_at=(NOW-timedelta(days=number % 30)).isoformat()))
    with repo.lock, repo.db:
        for number in range(100):
            dossier = f'benchmark-{number}'
            repo.db.execute('INSERT INTO workspace_dossiers VALUES(?,?,?,1,?,?)',
                            (dossier, f'Teczka {number:03}', 'Syntetyczna teczka', NOW.isoformat(), NOW.isoformat()))
            repo.db.executemany('INSERT INTO workspace_dossier_pins VALUES(?,?,?,?,?,?)',
                [(dossier, f'hydro_station:imgw:benchmark-{index}', f'Stacja {index:04}', 'hydro_station',
                  'imgw', NOW.isoformat()) for index in range(min(stations, 50))])
            repo.db.executemany('INSERT INTO workspace_dossier_notes VALUES(?,?,?,1,?,?)',
                [(f'{dossier}-{index}', dossier, 'Syntetyczna notatka', NOW.isoformat(), NOW.isoformat())
                 for index in range(5)])
    return workspace.areas.save({'name': 'Obszar benchmarku', 'shape': 'circle',
                                 'center': [21, 52.2], 'radius_m': 10000})['ref']


def measure(repo, operation, runs, profile):
    start = time.perf_counter()
    result = operation()
    cold = (time.perf_counter()-start)*1000
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        result = operation()
        timings.append((time.perf_counter()-start)*1000)
    statements = []
    repo.db.set_trace_callback(statements.append)
    try:
        operation()
    finally:
        repo.db.set_trace_callback(None)
    report = {'cold_ms': round(cold, 3), 'median_ms': round(statistics.median(timings), 3),
              'p95_ms': round(sorted(timings)[min(len(timings)-1, int(len(timings)*.95))], 3),
              'sql_statements': len(statements),
              'result_count': result.get('total', len(result.get('items', result.get('nodes', [])))),
              'payload_bytes': len(json.dumps(result, ensure_ascii=False).encode())}
    if 'neighbor_counts' in result:
        report['neighbors'] = sum(value['total'] for value in result['neighbor_counts'].values())
    if profile:
        profiler = cProfile.Profile()
        profiler.runcall(operation)
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats('cumulative').print_stats(12)
        report['profile'] = output.getvalue()
    return report


def run(stations=800, samples=80, communications=5000, runs=15, profile=False):
    with tempfile.TemporaryDirectory(prefix='wici-backend-benchmark-') as directory:
        repo = Repository(Path(directory)/'benchmark.sqlite3', clock=lambda: NOW)
        try:
            workspace = WorkspaceService(repo)
            area_ref = populate(repo, workspace, stations, samples, communications)
            operations = {
                'station_map': lambda: workspace.query({'types': ['hydro_station'], 'page_size': 100}),
                'communications_today': lambda: repo.list_communications({'date': NOW.date().isoformat()}),
                'communications_all': lambda: repo.list_communications(),
                'dossiers': workspace.dossiers.list,
                'custom_area_graph': lambda: workspace.relations.query({
                    'seed_refs': [area_ref], 'relation_types': ['custom_area_member']}),
            }
            return {'python': platform.python_version(), 'platform': platform.platform(),
                    'stations': stations, 'measurements': stations*samples,
                    'communications': communications, 'runs': runs,
                    'scenarios': {name: measure(repo, operation, runs, profile)
                                  for name, operation in operations.items()}}
        finally:
            repo.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stations', type=int, default=800)
    parser.add_argument('--samples', type=int, default=80)
    parser.add_argument('--communications', type=int, default=5000)
    parser.add_argument('--runs', type=int, default=15)
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    if min(args.stations, args.samples, args.runs) < 1 or args.communications < 0:
        parser.error('Stations, samples and runs must be positive; communications cannot be negative.')
    print(json.dumps(run(**vars(args)), ensure_ascii=False, indent=2))
