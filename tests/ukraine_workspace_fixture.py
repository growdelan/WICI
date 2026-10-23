"""Isolated, explicitly synthetic server for Ukraine Analysis browser regressions."""
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

from wici.app import create_app
from wici.config import Config


def feature(key, name, x, y, scope='oblasts'):
    return {'type': 'Feature', 'properties': {'key': key, 'region' if scope == 'oblasts' else 'rayon': name},
            'geometry': {'type': 'Polygon', 'coordinates': [
                [[x, y], [x+1, y], [x+1, y+1], [x, y+1], [x, y]]]}}


def geometry(scope):
    features = [feature('obwod-a', 'TEST Obwód A', 26, 49), feature('obwod-b', 'TEST Obwód B', 30, 49)]
    if scope == 'raions':
        features = [feature('rejon-a', 'TEST Rejon A', 26.1, 49.1, scope)]
    return {'type': 'FeatureCollection', 'features': features}


def alert(key, name, since, level='red', oblast=None):
    return {'key': key, 'name': name, 'since': since.isoformat(), 'level': level,
            'oblast': oblast, 'reasons': ['Syntetyczne dane testu interfejsu']}


def network(request):
    if request.url.host != 'neptun.in.ua':
        raise AssertionError('External network forbidden: '+str(request.url))
    if request.url.path.endswith('.geojson'):
        return httpx.Response(200, json=geometry(request.url.path[1:-8]))
    if request.url.path == '/api/v1/alerts':
        now = datetime.now(UTC)
        return httpx.Response(200, json={'version': 1, 'updatedAt': now.isoformat(), 'raions': [],
            'oblasts': [alert('obwod-a', 'TEST Obwód A', now)]})
    raise AssertionError('Unrequested provider endpoint: '+str(request.url))


def make_app(directory, port, seeded=True):
    client = httpx.AsyncClient(transport=httpx.MockTransport(network))
    app = create_app(demo=True, root=Path(directory), config=Config(port=port), client=client)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def fixture_lifespan(app):
        async with original(app):
            history = app.state.workspace.ukraine
            end = datetime.now(UTC).replace(second=0, microsecond=0)
            clock = [end-timedelta(hours=1)]
            app.state.repo.clock = lambda: clock[0]
            if seeded:
                history.register_geometry({'status': 'ready', 'fetched_at': clock[0].isoformat(),
                                           'oblasts': geometry('oblasts'), 'raions': geometry('raions')})
                history.set_recording(True)
            for index in range(240 if seeded else 0):
                clock[0] = end-timedelta(hours=1)+timedelta(seconds=index*15)
                if 60 <= index < 80:
                    if index == 60:
                        history.mark_gap('synthetic_network_failure')
                    continue
                items = []
                if index < 120:
                    items.append(dict(alert('obwod-a', 'TEST Obwód A', end-timedelta(hours=1)), scope='oblast'))
                if index >= 100:
                    items.append(dict(alert('obwod-b', 'TEST Obwód B', end-timedelta(minutes=35), 'yellow'), scope='oblast'))
                if index < 120:
                    items.append(dict(alert('rejon-a', 'TEST Rejon A', end-timedelta(hours=1),
                                            oblast='TEST Obwód A'), scope='raion'))
                history.ingest({'status': 'ready', 'stale': False, 'fetched_at': clock[0].isoformat(),
                    'updated_at': clock[0].isoformat(), 'source_version': index, 'items': items})
            clock[0] = end
            history.set_recording(False)
            app.state.repo.clock = lambda: datetime.now(UTC)
            app.state.ukraine.demo = False
            app.state.ukraine_collector.available = True
            app.state.workspace.source_enabled['ukraine_alerts'] = True
            yield
        await client.aclose()

    app.router.lifespan_context = fixture_lifespan
    return app


if __name__ == '__main__':
    port = int(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='wici-ukraine-workspace-') as directory:
        uvicorn.run(make_app(directory, port, seeded='--empty' not in sys.argv),
                    host='127.0.0.1', port=port, log_level='error')
