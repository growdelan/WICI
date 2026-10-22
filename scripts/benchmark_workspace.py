"""Reproducible local workspace query benchmark; synthetic temporary database only.

uv run python scripts/benchmark_workspace.py --samples 1000000 --runs 30
"""
import argparse
import json
import platform
import resource
import statistics
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from wici.demo import DEMO_NOW
from wici.repository import Repository
from wici.workspace_service import WorkspaceService


def run(samples=1000000, runs=30, communications=10000, stations=1500):
    with tempfile.TemporaryDirectory(prefix='wici-workspace-benchmark-') as directory:
        repo = Repository(Path(directory)/'app.sqlite3', clock=lambda: DEMO_NOW)
        service = WorkspaceService(repo)
        now = DEMO_NOW.isoformat()
        with repo.lock, repo.db:
            repo.db.executemany('''INSERT INTO catalog_objects
                (ref,type,source_id,native_id,label,search_text,published_at) VALUES(?,?,?,?,?,?,?)''',
                [(f'communication:benchmark-{n}', 'communication', 'rso', str(n), f'Komunikat {n:05}',
                  f'komunikat {n:05}', now) for n in range(communications)])
            repo.db.executemany('''INSERT INTO catalog_objects
                (ref,type,source_id,native_id,label,search_text,latitude,longitude) VALUES(?,?,?,?,?,?,?,?)''',
                [(f'hydro_station:imgw:benchmark-{n}', 'hydro_station', 'imgw', str(n), f'Stacja {n:04}',
                  f'stacja {n:04}', 52.2+n/100000, 21.0) for n in range(stations)])
            repo.db.execute('''INSERT INTO catalog_object_areas SELECT ref,'14','station_location',
                'synthetic benchmark' FROM catalog_objects WHERE ref LIKE '%benchmark-%' ''')
            timestamps = [(DEMO_NOW-timedelta(minutes=20*(n+1))).isoformat()
                          for n in range((samples+stations-1)//stations)]
            for offset in range(0, samples, 10000):
                repo.db.executemany('''INSERT INTO station_measurements
                    (object_ref,metric,observed_key,observed_at,value,unit,fetched_at,first_fetched_at,
                     revision,quality,content_hash) VALUES(?,'water_level',?,?,?,'cm',?,?,1,'valid','synthetic')''',
                    [(f'hydro_station:imgw:benchmark-{n%stations}', timestamps[n//stations],
                      timestamps[n//stations], n%400, now, now) for n in range(offset, min(samples, offset+10000))])
        query = {'types': ['communication', 'hydro_station'], 'page_size': 100,
                     'time': {'mode':'range', 'filter_range':{'from':(DEMO_NOW-timedelta(days=14)).isoformat(),
                                                         'to':(DEMO_NOW+timedelta(seconds=1)).isoformat()}}}
        # Exact fourteen-day window, including the current source timestamp.
        query['time']['filter_range']['from'] = (DEMO_NOW-timedelta(days=14)+timedelta(seconds=1)).isoformat()
        start = time.perf_counter(); result = service.query(query); cold = (time.perf_counter()-start)*1000
        timings = []
        for _ in range(runs):
            start = time.perf_counter(); result = service.query(query); timings.append((time.perf_counter()-start)*1000)
        card_times = []
        for _ in range(runs):
            start = time.perf_counter()
            service.detail('hydro_station:imgw:benchmark-0', result['as_of'], result['data_revision'])
            card_times.append((time.perf_counter()-start)*1000)
        def p95(values):
            return round(sorted(values)[min(len(values)-1, int(len(values)*.95))], 2)
        report = {'machine': platform.platform(), 'python': platform.python_version(), 'communications': communications,
                      'stations': stations, 'measurements': samples, 'runs': runs, 'cold_query_ms': round(cold, 2),
                      'warm_query_median_ms': round(statistics.median(timings), 2), 'warm_query_p95_ms': p95(timings),
                      'warm_card_p95_ms': p95(card_times), 'payload_bytes': len(json.dumps(result, ensure_ascii=False).encode()),
                      'max_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      'result_count': result['total'], 'map_mode': result['map']['mode'],
                      'histogram_events': result['timeline_summary']['event_total'],
                      'query_target_met': p95(timings)<500, 'card_target_met': p95(card_times)<300}
        repo.close()
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=1000000)
    parser.add_argument('--runs', type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(run(args.samples, args.runs), ensure_ascii=False, indent=2))
