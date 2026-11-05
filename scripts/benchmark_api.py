"""Offline HTTP serialization benchmark with synthetic, already-normalized payloads.

Actual WICI routes are compared with FastAPI's default dictionary response in
the same process. No lifespan, database, sockets or upstream calls are started.
The comparison includes ASGI routing/security and verifies identical bytes.
"""
import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import time
from types import SimpleNamespace

import httpx

from wici.app import create_app
from wici.config import Config
from wici.demo import DEMO_NOW


def payloads(count):
    items = [{'ref': f'hydro_station:imgw:synthetic-{n}', 'label': f'Stacja Łódź {n}',
                  'latitude': 51.7+n/100000, 'longitude': 19.4, 'source_id': 'imgw',
                  'measurement': {'value': None if n % 7 == 0 else n / 3, 'unit': 'cm',
                               'observed_at': DEMO_NOW.isoformat(), 'stale': False},
                  'metadata': {'synthetic': True, 'source_url': 'https://example.invalid/source'},
                  'areas': [{'admin_code': '10', 'role': 'station_location'}]} for n in range(count)]
    return {
        'workspace': {'items': items[:100], 'total': count, 'map': {'points': items, 'areas': []},
                      'as_of': DEMO_NOW.isoformat(), 'data_revision': 'synthetic'},
        'layer': {'status': 'ready', 'items': items, 'fetched_at': DEMO_NOW.isoformat(), 'stale': False},
        'history': {'items': [{'id': n, 'value': None if n % 7 == 0 else n / 3,
                                 'observed_at': DEMO_NOW.isoformat(), 'quality': 'valid', 'unit': 'cm',
                                 'provenance': {'synthetic': True}} for n in range(count * 2)],
                    'has_more': False},
    }


async def run(count=1000, runs=20):
    values = payloads(count)
    app = create_app(demo=True, config=Config())
    app.state.repo = SimpleNamespace(clock=lambda: DEMO_NOW)
    app.state.scheduler = SimpleNamespace(gap_seconds=0)
    app.state.workspace = SimpleNamespace(query=lambda _: values['workspace'], timeline=lambda *args: values['history'])

    async def fetch(city):
        return values['layer']

    app.state.buses = SimpleNamespace(fetch=fetch)

    @app.post('/_benchmark/workspace')
    def reference_workspace():
        return values['workspace']

    @app.get('/_benchmark/layer')
    async def reference_layer():
        return values['layer']

    @app.get('/_benchmark/history')
    def reference_history():
        return values['history']

    origin = 'http://127.0.0.1:8765'
    report = {'python': platform.python_version(), 'platform': platform.platform(),
              'items': count, 'runs': runs, 'scope': __doc__, 'scenarios': {}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
        token = (await client.get('/api/health')).json()['csrf_token']
        headers = {'Origin': origin, 'X-CSRF-Token': token}
        cases = [('workspace', 'POST', '/api/workspace/query', '/_benchmark/workspace'),
                 ('layer', 'GET', '/api/buses', '/_benchmark/layer'),
                 ('history', 'GET', '/api/workspace/objects/hydro_station:imgw:synthetic-0/timeline',
                  '/_benchmark/history')]
        for name, method, endpoint, reference in cases:
            durations = {endpoint: [], reference: []}
            expected = None
            # Alternate ordering to avoid systematically favoring the second route.
            for iteration in range(runs+2):
                for path in ([reference, endpoint] if iteration % 2 else [endpoint, reference]):
                    start = time.perf_counter()
                    response = await client.request(method, path, headers=headers,
                                                    **({'json': {}} if method == 'POST' else {}))
                    elapsed = (time.perf_counter()-start)*1000
                    assert response.status_code == 200, response.text
                    if expected is None:
                        expected = response.content
                    assert response.content == expected, f'{name}: serialization changed the response'
                    if iteration >= 2:
                        durations[path].append(elapsed)
            actual = statistics.median(durations[endpoint])
            default = statistics.median(durations[reference])
            report['scenarios'][name] = {
                'default_median_ms': round(default, 3), 'wici_median_ms': round(actual, 3),
                'speedup': round(default/actual, 2), 'response_bytes': len(expected),
                'sha256': hashlib.sha256(expected).hexdigest(),
            }
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--items', type=int, default=1000)
    parser.add_argument('--runs', type=int, default=20)
    args = parser.parse_args()
    if args.items < 1 or args.runs < 1:
        parser.error('Items and runs must be positive.')
    print(json.dumps(asyncio.run(run(args.items, args.runs)), indent=2, ensure_ascii=False))
