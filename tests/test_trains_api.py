"""Local railway API routing, validation and offline demo."""
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config


def test_trains_demo_and_origin_guards(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path, config=Config()),
                    base_url='http://127.0.0.1:8765') as client:
        for path in ('/api/trains/stations', '/api/trains/positions', '/api/trains/stations/example',
                     '/api/trains/trips/example?start_date=2026-10-15'):
            response = client.get(path)
            assert response.status_code == 200
            assert response.json()['demo']
            assert response.json()['source_url'] == 'https://mkuran.pl/gtfs/'
            assert client.get(path, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
            assert client.get(path, headers={'Origin': 'https://example.com'}).status_code == 403
        assert client.get('/api/trains/trips/example?start_date=invalid').status_code == 422
        assert client.get('/api/trains/trips/example').status_code == 422


def test_trains_routes_pass_identifiers_and_map_not_found(tmp_path):
    calls = []

    class Trains:
        async def stations(self):
            calls.append('stations')
            return {'items': [{'id': 'station_1'}]}

        async def positions(self):
            calls.append('positions')
            return {'items': [], 'estimated_at': '2026-10-15T12:00:00+00:00'}

        async def station(self, station_id):
            calls.append(station_id)
            return {'status': 'not_found', 'station': None, 'departures': []}

        async def trip(self, trip_id, start_date):
            calls.append((trip_id, start_date))
            return {'status': 'ready', 'trip': {'id': trip_id, 'start_date': start_date}}

    app = create_app(demo=True, root=tmp_path, config=Config())
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        app.state.trains = Trains()
        assert client.get('/api/trains/stations').json()['items'][0]['id'] == 'station_1'
        assert client.get('/api/trains/positions').json()['items'] == []
        assert client.get('/api/trains/stations/missing').status_code == 404
        result = client.get('/api/trains/trips/PLK_IC_2026_1?start_date=2026-10-15')
        assert result.status_code == 200
        assert calls == ['stations', 'positions', 'missing', ('PLK_IC_2026_1', '2026-10-15')]
