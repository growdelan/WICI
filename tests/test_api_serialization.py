"""Large normalized snapshots keep their wire contract without a recursive copy."""
from types import SimpleNamespace

import fastapi.routing
import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.demo import DEMO_NOW
from wici.workspace_service import QueryChanged

ORIGIN = 'http://127.0.0.1:8765'


@pytest.mark.parametrize(('path', 'method', 'body'), [
    ('/api/workspace/query', 'POST', {}),
    ('/api/workspace/objects/hydro_station:imgw:1/timeline', 'GET', None),
    ('/api/workspace/graph/query', 'POST', {'seed_refs': ['area:prg:14']}),
    ('/api/workspace/dossiers/example/materials/snapshot', 'GET', None),
    ('/api/buses', 'GET', None),
    ('/api/ukraine/geometry', 'GET', None),
    ('/api/trains/stations', 'GET', None),
    ('/api/communications', 'GET', None),
    ('/api/scene3d/buildings/1/1', 'GET', None),
    ('/api/gfm/monitor', 'GET', None),
    ('/api/sentinel2/render', 'GET', None),
    ('/api/sentinel5p/render', 'GET', None),
])
def test_large_snapshots_are_encoded_once_with_exact_json_and_security(tmp_path, monkeypatch, path, method, body):
    payload = {'items': [{'id': n, 'name': 'Łódź — Київ', 'value': None if n % 2 else 1/3,
                          'source_at': '2026-11-05T12:00:00+00:00', 'stale': False,
                          'geometry': {'type': 'Point', 'coordinates': [19.4, 51.7]},
                          'revision': 2**53+1, 'empty': [], 'zero': 0, 'negative_zero': -0.0}
                         for n in range(1000)], 'synthetic': True}
    expected = JSONResponse(payload).body
    app = create_app(demo=True, root=tmp_path, config=Config())

    def read(*args, **kwargs):
        return payload

    async def fetch(*args, **kwargs):
        return payload

    app.state.repo = SimpleNamespace(clock=lambda: DEMO_NOW, list_communications=read)
    app.state.scheduler = SimpleNamespace(gap_seconds=0)
    app.state.workspace = SimpleNamespace(query=read, timeline=read,
                                          relations=SimpleNamespace(query=read),
                                          dossiers=SimpleNamespace(material=read))
    app.state.buses = SimpleNamespace(fetch=fetch)
    app.state.ukraine = SimpleNamespace(geometry=fetch)
    app.state.trains = SimpleNamespace(stations=fetch)
    app.state.scene3d = SimpleNamespace(buildings=fetch)
    app.state.gfm_monitor = SimpleNamespace(snapshot=fetch)
    app.state.sentinel2 = SimpleNamespace(render=fetch)
    app.state.sentinel5p = SimpleNamespace(render=fetch)
    encoder = fastapi.routing.jsonable_encoder
    copies = []

    def count_snapshot_copies(value, **kwargs):
        if value is payload:
            copies.append(value)
        return encoder(value, **kwargs)

    monkeypatch.setattr(fastapi.routing, 'jsonable_encoder', count_snapshot_copies)
    # No lifespan: only the HTTP boundary is under test, with no collectors or DB.
    client = TestClient(app, base_url=ORIGIN)
    try:
        token = client.get('/api/health').json()['csrf_token']
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': token}
        response = client.request(method, path, headers=headers, **({'json': body} if body is not None else {}))
        assert response.status_code == 200
        assert response.content == expected
        assert response.headers['content-type'] == 'application/json'
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert not copies, 'Large JSON-native snapshots must not be recursively copied before encoding'
        assert client.request(method, path, headers={'Host': 'outside.invalid'}).status_code == 400
        if method == 'POST':
            assert client.post(path, json=body).status_code == 403
    finally:
        client.close()


@pytest.mark.parametrize(('error', 'status'), [(QueryChanged('Zmienione dane'), 409),
                                             (KeyError('missing'), 404), (ValueError('Błędny zakres'), 422)])
def test_direct_json_responses_keep_workspace_error_statuses(tmp_path, error, status):
    app = create_app(demo=True, root=tmp_path, config=Config())

    def read(*args):
        raise error

    app.state.workspace = SimpleNamespace(timeline=read)
    client = TestClient(app, base_url=ORIGIN)
    try:
        response = client.get('/api/workspace/objects/hydro_station:imgw:1/timeline')
        assert response.status_code == status
        assert 'detail' in response.json()
    finally:
        client.close()
