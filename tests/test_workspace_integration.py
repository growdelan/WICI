"""Full local app checks: workspace, legacy APIs, source persistence and security."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.demo import DEMO_NOW

ORIGIN = 'http://127.0.0.1:8765'
FIXTURES = Path(__file__).parent / 'fixtures'


def headers(client):
    return {'Origin': ORIGIN, 'X-CSRF-Token': client.get('/api/health').json()['csrf_token']}


def query(client, body=None):
    response = client.post('/api/workspace/query', json=body or {}, headers=headers(client))
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(repo):
    with repo.lock:
        return {table: [tuple(row) for row in repo.db.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('documents', 'document_versions', 'catalog_objects', 'station_sensors',
                              'station_measurements', 'station_index_observations', 'workspace_source_runs')}


def test_demo_catalogue_cards_timeline_and_restart_are_idempotent(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get('/api/health').json()['mode'] == 'demo'
        assert len(client.get('/api/communications').json()['items']) == 5
        result = query(client, {'page_size': 200, 'query_revision': 7})
        assert result['query_revision'] == 7
        assert result['total'] >= 400
        assert result['map']['located_total'] + result['map']['unlocated_total'] == result['total']
        assert result['timeline_summary']['timeless_total'] > 0
        stations = query(client, {'types': ['hydro_station', 'air_quality_station']})
        assert stations['total'] == 3
        assert stations['map']['unlocated_total'] == 1
        params = {'as_of': stations['as_of'], 'data_revision': stations['data_revision']}
        for row in stations['items']:
            detail = client.get(f'/api/workspace/objects/{row["ref"]}', params=params)
            assert detail.status_code == 200, detail.text
            assert detail.json()['object']['ref'] == row['ref']
            timeline = client.get(f'/api/workspace/objects/{row["ref"]}/timeline', params=params)
            assert timeline.status_code == 200, timeline.text
        details = client.get('/api/workspace/objects/air_quality_station:gios:9000001').json()
        assert len(details['sensors']) == 2
        assert details['object']['official_index']['value'] == 1
        assert client.get('/api/hydro').json()['status'] == 'disabled'
        assert client.get('/api/gios').json()['status'] == 'disabled'
        status = client.get('/api/workspace/status').json()
        assert status['status'] == 'ready' and status['persistence']['errors'] == {}
        before = snapshot(app.state.repo)
    reopened = create_app(demo=True, root=tmp_path)
    with TestClient(reopened, base_url=ORIGIN) as client:
        assert snapshot(reopened.state.repo) == before
        assert query(client, {'types': ['hydro_station', 'air_quality_station']})['total'] == 3
        assert len(client.get('/api/communications').json()['items']) == 5


def test_legacy_source_endpoints_commit_before_workspace_read_and_cache_never_duplicates(tmp_path):
    calls, now = [], [datetime(2026, 10, 17, 6, 30, tzinfo=UTC)]
    fixtures = {kind: json.loads((FIXTURES / f'gios/{kind}.json').read_text())
                for kind in ('stations', 'sensors', 'data', 'index')}
    hydro = json.loads((FIXTURES / 'imgw_hydro/hydro.json').read_text())

    def handler(request):
        calls.append(str(request.url))
        if '/hydro/' in request.url.path:
            return httpx.Response(503) if now[0].minute >= 36 else httpx.Response(200, json=hydro)
        kind = next(kind for part, kind in (('findAll', 'stations'), ('sensors', 'sensors'),
                                           ('getData', 'data'), ('getIndex', 'index')) if part in request.url.path)
        return httpx.Response(200, json=fixtures[kind])

    network = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        app = create_app(demo=True, root=tmp_path, client=network)
        with TestClient(app, base_url=ORIGIN) as client:
            app.state.repo.clock = lambda: now[0]
            for service in (app.state.hydro, app.state.gios):
                service.demo = False
                service.clock = app.state.repo.clock
            hydro_result = client.get('/api/hydro').json()
            assert hydro_result['status'] == 'ready'
            stations = client.get('/api/gios').json()
            station_id = stations['items'][0]['id']
            sensors = client.get('/api/gios', params={'kind': 'sensors', 'id': station_id}).json()
            sensor_id = sensors['items'][0]['id']
            assert client.get('/api/gios', params={'kind': 'data', 'id': sensor_id}).json()['status'] == 'ready'
            assert client.get('/api/gios', params={'kind': 'index', 'id': station_id}).json()['status'] == 'ready'
            assert len(calls) == 5
            before = snapshot(app.state.repo)
            for path, params in [('/api/hydro', {}), ('/api/gios', {}), ('/api/gios', {'kind': 'sensors', 'id': station_id}),
                                 ('/api/gios', {'kind': 'data', 'id': sensor_id}), ('/api/gios', {'kind': 'index', 'id': station_id})]:
                assert client.get(path, params=params).status_code == 200
            assert len(calls) == 5 and snapshot(app.state.repo) == before
            result = query(client, {'types': ['hydro_station', 'air_quality_station'], 'include_without_samples': False})
            native_refs = {f'hydro_station:imgw:{hydro_result["items"][0]["id"]}',
                           f'air_quality_station:gios:{station_id}'}
            assert native_refs.issubset({row['ref'] for row in result['items']})
            detail = client.get(f'/api/workspace/objects/air_quality_station:gios:{station_id}',
                                params={'sensor_id': sensor_id}).json()
            assert detail['selected_measurement']['sensor_id'] == str(sensor_id)
            assert detail['object']['official_index']['value'] == 1
            assert len(calls) == 5  # Query and cards are entirely local.
            now[0] += timedelta(minutes=6)
            assert client.get('/api/hydro').json()['status'] == 'error'
            failed = client.get('/api/workspace/status').json()
            assert next(row for row in failed['sources'] if row['resource'] == 'hydro:stations')['status'] == 'error'
            assert len(snapshot(app.state.repo)['station_measurements']) == len(before['station_measurements'])
    finally:
        asyncio.run(network.aclose())


def test_workspace_security_validation_and_saved_views_survive_restart(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    body = {'name': 'Mój widok', 'config': {'query': {'types': ['hydro_station'], 'province': '14'},
                                          'camera': {'lat': 52.2, 'lng': 21, 'zoom': 8}}}
    with TestClient(app, base_url=ORIGIN) as client:
        trusted = headers(client)
        assert client.get('/api/workspace/status', headers={'Host': 'attacker.invalid'}).status_code == 400
        for path, value in [('/api/workspace/query', {}), ('/api/workspace/views', body)]:
            assert client.post(path, json=value).status_code == 403
            assert client.post(path, json=value, headers={**trusted, 'Origin': 'https://attacker.invalid'}).status_code == 403
            assert client.post(path, json=value, headers={**trusted, 'X-CSRF-Token': 'wrong'}).status_code == 403
        assert client.post('/api/workspace/query', content=' ' * 65537, headers=trusted).status_code == 413
        for invalid in ({'province': '00'}, {'q': 'a' * 201}, {'sort': {'field': 'label;DROP TABLE documents'}},
                        {'upstream_url': 'https://attacker.invalid'}, {'page_size': 201}):
            assert client.post('/api/workspace/query', json=invalid, headers=trusted).status_code == 422
        assert client.post('/api/workspace/views', json={**body, 'config': {'api_key': 'secret'}}, headers=trusted).status_code == 422
        saved = client.post('/api/workspace/views', json=body, headers=trusted)
        assert saved.status_code == 201
        view = saved.json()
        assert view['revision'] == 1
        stale = client.put(f'/api/workspace/views/{view["id"]}', json={**body, 'revision': 2}, headers=trusted)
        assert stale.status_code == 409
        updated = client.put(f'/api/workspace/views/{view["id"]}',
                             json={**body, 'name': 'Zmieniony widok', 'revision': 1}, headers=trusted)
        assert updated.status_code == 200 and updated.json()['revision'] == 2
    with TestClient(create_app(demo=True, root=tmp_path), base_url=ORIGIN) as client:
        assert client.get('/api/workspace/views').json()['items'][0]['name'] == 'Zmieniony widok'
        assert client.delete(f'/api/workspace/views/{view["id"]}', headers=trusted).status_code == 403
        assert client.delete(f'/api/workspace/views/{view["id"]}', headers=headers(client)).status_code == 200
        assert client.get('/api/workspace/views').json()['items'] == []


def test_analysis_queries_and_filters_do_not_stop_active_recording(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        now = [DEMO_NOW]
        app.state.repo.clock = lambda: now[0]
        tracking = app.state.tracking

        class AircraftSource:
            async def fetch(self):
                return {'status': 'ready', 'items': [{'hex': '48abcd', 'id': 'DEMO123', 'latitude': 52,
                                                      'longitude': 20, 'position_at': now[0].isoformat()}]}

        tracking.demo = False
        tracking.services['aircraft'] = AircraftSource()
        created = client.post('/api/tracks', json={'kind': 'aircraft', 'object_id': '48abcd'}, headers=headers(client))
        assert created.status_code == 200
        track_id = created.json()['track']['id']
        for body in ({}, {'province': '14'}, {'types': ['hydro_station']}, {'q': 'nieistniejący obiekt'}):
            query(client, body)
        assert client.get(f'/api/tracks/{track_id}').json()['track']['active'] is True
        now[0] += timedelta(seconds=15)
        client.portal.call(tracking.collect_once)
        result = client.get(f'/api/tracks/{track_id}').json()
        assert result['track']['active'] is True and result['track']['point_count'] == 2
        assert client.get('/api/communications').status_code == 200
