"""Isolated graph integration fixture: real app/SQLite, explicitly synthetic sources."""
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from moving_workspace_server import Feed, seed_history

from wici.app import create_app
from wici.config import Config
from wici.sources.normalize import document, location
from wici.tracking import TrackingService

STATION = 'air_quality_station:gios:9000001'
AIRCRAFT = 'aircraft:icao:48abc0'
SHIP = 'ship:mmsi:261000001'
OBLAST = 'ua_region:neptun:oblast:graph-oblast'
RAION = 'ua_region:neptun:raion:graph-raion'


def feature(key, name, *, raion=False):
    return {'type': 'Feature', 'properties': {'key': key,
        'rayon' if raion else 'region': name, 'oblast': 'graph-oblast' if raion else None},
        'geometry': {'type': 'Polygon', 'coordinates': [
            [[30, 50], [31, 50], [31, 51], [30, 51], [30, 50]]]}}


def network(request):
    if request.url.host != 'neptun.in.ua':
        raise AssertionError(f'External network forbidden: {request.url}')
    if request.url.path.endswith('.geojson'):
        raion = 'raions' in request.url.path
        return httpx.Response(200, json={'type': 'FeatureCollection', 'features': [
            feature('graph-raion' if raion else 'graph-oblast',
                    'TEST Rejon grafu' if raion else 'TEST Obwód grafu', raion=raion)]})
    if request.url.path == '/api/v1/alerts':
        now = datetime.now(UTC).isoformat()
        return httpx.Response(200, json={'version': 1, 'updatedAt': now, 'raions': [], 'oblasts': []})
    raise AssertionError(f'Unrequested provider endpoint: {request.url}')


class GraphFeed(Feed):
    def item(self, at, index=0, step=0):
        value = super().item(at, index, step)
        if self.kind == 'aircraft':
            value.update(latitude=52.2+index*.02+step*.0001,
                         longitude=21.0+index*.02+step*.0001)
        return value


def make_app(directory, port):
    client = httpx.AsyncClient(transport=httpx.MockTransport(network))
    app = create_app(demo=True, root=Path(directory), config=Config(port=port), client=client)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            repo, workspace = application.state.repo, application.state.workspace
            repo.clock = lambda: datetime.now(UTC)
            end = datetime.now(UTC).replace(second=0, microsecond=0)
            start = end-timedelta(minutes=65)
            application.state.graph_range = {'from': start.isoformat(),
                                             'to': (start+timedelta(hours=1)).isoformat()}
            application.state.graph_notices = []
            for index in range(65):
                raw = document('rso', f'graph-{index}', f'https://example.invalid/graph/{index}',
                    f'TEST graf — komunikat {index:02}', 'Syntetyczna treść testu relacji.',
                    {'locations': [location('14', 'notification_area', 'RSO')]}, [],
                    source_published_at=(end-timedelta(minutes=30)).isoformat())
                result = repo.ingest(raw)
                application.state.graph_notices.append((f"communication:{result['document_id']}", raw))
            workspace.catalog.backfill()
            versioned = document('rso', 'graph-versioned', 'https://example.invalid/graph/versioned',
                'TEST graf — wersja A', 'Pierwsza treść i obszar.',
                {'locations': [location('14', 'notification_area', 'RSO')]}, [],
                source_published_at=(end-timedelta(minutes=20)).isoformat())
            first = repo.ingest(versioned)
            workspace.catalog.backfill()
            versioned_ref = f"communication:{first['document_id']}"
            old_version = workspace.detail(versioned_ref)['versions'][0]['id']
            versioned['title'] = 'TEST graf — wersja B'
            versioned['fields']['event']['locations'] = [location('12', 'notification_area', 'RSO')]
            repo.ingest(versioned)
            workspace.catalog.backfill()
            application.state.graph_versioned = {'ref': versioned_ref, 'old_version': old_version}
            observed = end-timedelta(minutes=10)
            station_history = application.state.station_history
            station_history.write('gios:stations', {'status': 'ready', 'fetched_at': end.isoformat(),
                'synthetic': True, 'source_url': 'https://example.invalid/graph/gios', 'items': [{
                    'id': 9000001, 'name': 'DEMO: jakość powietrza Warszawa',
                    'latitude': 52.21, 'longitude': 21.02, 'province': 'mazowieckie',
                    'address': 'Adres syntetyczny', 'synthetic': True}]})
            station_history.write('gios:data:9000011', {'status': 'ready', 'fetched_at': end.isoformat(),
                'synthetic': True, 'source_url': 'https://example.invalid/graph/gios',
                'items': [{'value': 23, 'unit': 'µg/m³', 'observed_at': observed.isoformat(),
                           'source_time': observed.isoformat()}]})
            aircraft, ships = GraphFeed('aircraft', repo), GraphFeed('ship', repo)
            tracker = TrackingService(repo, aircraft, ships)
            application.state.aircraft, application.state.ships = aircraft, ships
            application.state.tracking = tracker
            workspace.source_enabled.update(aircraft=True, ships=True, ukraine_alerts=True)
            for kind, feed in [('aircraft', aircraft), ('ship', ships)]:
                for index in range(3):
                    object_id = f'48abc{index}' if kind == 'aircraft' else str(261000001+index)
                    detail = await tracker.begin(kind, object_id)
                    seed_history(repo, tracker, detail['track']['id'], feed, index, start)
                    await tracker.stop(detail['track']['id'])
            workspace.moving.backfill_tracks()
            for kind, feed in [('aircraft', aircraft), ('ship', ships)]:
                workspace.moving.ingest(kind, await feed.fetch())
            history = workspace.ukraine
            repo.clock = lambda: start
            history.register_geometry({'fetched_at': end.isoformat(),
                'oblasts': {'features': [feature('graph-oblast', 'TEST Obwód grafu')]},
                'raions': {'features': [feature('graph-raion', 'TEST Rejon grafu', raion=True)]}})
            history.set_recording(True)
            try:
                for index in range(121):
                    when = start+timedelta(seconds=index*30)
                    repo.clock = lambda when=when: when
                    if 40 <= index < 60:
                        if index == 40:
                            history.mark_gap('synthetic_graph_gap')
                        continue
                    items = [] if index >= 90 else [{'scope': 'raion', 'key': 'graph-raion',
                        'name': 'TEST Rejon grafu', 'oblast': 'graph-oblast',
                        'level': 'red', 'since': start.isoformat(), 'reasons': ['Syntetyczny powód grafu']}]
                    history.ingest({'status': 'ready', 'stale': False, 'fetched_at': when.isoformat(),
                        'updated_at': when.isoformat(), 'source_version': index, 'items': items})
            finally:
                repo.clock = lambda: datetime.now(UTC)
            history.set_recording(False)
            application.state.ukraine.demo = False
            application.state.ukraine_collector.available = True
            try:
                yield
            finally:
                await tracker.close()
        await client.aclose()

    app.router.lifespan_context = lifespan

    @app.get('/_test/graph')
    def fixture():
        with app.state.repo.lock:
            alert = app.state.repo.db.execute('SELECT ref FROM workspace_ukraine_episodes ORDER BY first_seen_at LIMIT 1').fetchone()
        return {'station': STATION, 'aircraft': AIRCRAFT, 'ship': SHIP,
                'oblast': OBLAST, 'raion': RAION, 'alert': alert['ref'] if alert else None,
                'notice': app.state.graph_notices[0][0],
                'notices': [entry[0] for entry in app.state.graph_notices],
                'range': app.state.graph_range, 'versioned': app.state.graph_versioned}

    @app.post('/_test/change/{kind}')
    def change(kind: str):
        repo, workspace = app.state.repo, app.state.workspace
        if kind == 'notice':
            ref, raw = app.state.graph_notices[0]
            raw['text'] += ' Zmieniona treść źródłowa.'
            repo.ingest(raw)
            workspace.catalog.backfill()
            return {'ref': ref}
        if kind == 'station':
            with repo.lock, repo.db:
                workspace.catalog.upsert_station(STATION, 'gios', '9000001', 'Zmieniona stacja grafu',
                    52.21, 21.02, {'province': 'mazowieckie', 'synthetic': True})
            return {'ref': STATION}
        if kind == 'prune':
            with repo.lock, repo.db:
                repo.db.execute('DELETE FROM object_tracks')
                for table in ('station_measurements', 'station_sensors', 'station_index_observations'):
                    repo.db.execute(f'DELETE FROM {table} WHERE object_ref=?', (STATION,))
                repo.db.execute('DELETE FROM catalog_objects WHERE ref=?', (STATION,))
                repo.db.execute('DELETE FROM catalog_objects WHERE ref=?', (app.state.graph_notices[0][0],))
            return {'pruned': True}
        raise ValueError(kind)

    return app


if __name__ == '__main__':
    port = int(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='wici-graph-browser-') as directory:
        uvicorn.run(make_app(directory, port), host='127.0.0.1', port=port, log_level='error')
