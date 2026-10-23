"""The real aircraft adapter projects into Analysis using its existing request."""
import httpx
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.demo import DEMO_NOW


def test_existing_aircraft_fetch_updates_catalog_without_second_upstream_call(tmp_path):
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(200, json={'now': DEMO_NOW.timestamp() * 1000, 'ac': [{
            'hex': '48abcd', 'flight': 'TEST123', 'r': 'SP-TST', 't': 'TEST',
            'type': 'adsb_icao', 'category': 'A3', 'lat': 52.23, 'lon': 21.01,
            'alt_baro': 10000, 'gs': 250, 'track': 120, 'seen_pos': 0,
        }]})

    network = httpx.AsyncClient(transport=httpx.MockTransport(response))
    app = create_app(demo=True, root=tmp_path, client=network)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        # Scheduler remains offline; enable only the actual aircraft adapter.
        app.state.aircraft.demo = False
        app.state.workspace.source_enabled['aircraft'] = True
        fetched = client.get('/api/aircraft')
        assert fetched.status_code == 200
        assert client.get('/api/workspace/status').json()['moving_persistence']['errors'] == {}
        object_url = '/api/workspace/objects/aircraft:icao:48abcd'
        projected = client.get(object_url)
        assert projected.status_code == 200
        assert projected.json()['object']['position']['latitude'] == 52.23
        assert projected.json()['object']['label'] == 'TEST123'
        assert projected.json()['object']['provenance']['source_url'] == 'https://adsb.fi/'
        assert projected.json()['object']['fetched_at'] == DEMO_NOW.isoformat()
        assert len(calls) == 1
        # Pure local catalogue reads do not acquire or extend transport demand.
        client.get(object_url)
        client.get('/api/workspace/status')
        assert len(calls) == 1
        app.state.aircraft.enabled = False
        client.get('/api/aircraft')
        hidden = client.get(object_url).json()['object']
        assert hidden['position'] is None
        assert hidden['last_known_position']['latitude'] == 52.23
        assert len(calls) == 1
