"""Real track API, trusted provider positions, origin/CSRF and SQLite persistence."""
from fastapi.testclient import TestClient

from wici.app import create_app


def headers(client):
    return {'Origin': 'http://127.0.0.1:8765',
            'X-CSRF-Token': client.get('/api/health').json()['csrf_token']}


def test_tracking_api_security_and_real_archive(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        tracking = app.state.tracking
        at = app.state.repo.clock().isoformat()

        class Source:
            async def fetch(self):
                return {'status': 'ready', 'items': [{'hex': '48abcd', 'id': 'LOT123', 'latitude': 52,
                        'longitude': 20, 'position_at': at, 'military': True}]}

        tracking.demo = False
        tracking.services['aircraft'] = Source()
        body = {'kind': 'aircraft', 'object_id': '48abcd'}
        assert client.post('/api/tracks', json=body).status_code == 403
        assert client.post('/api/tracks', json=body, headers={**headers(client),
            'Origin': 'https://attacker.invalid'}).status_code == 403
        assert client.get('/api/tracks', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.get('/api/tracks', headers={'Origin': 'https://attacker.invalid'}).status_code == 403
        assert client.post('/api/tracks', json={**body, 'latitude': 1}, headers=headers(client)).status_code == 422
        assert client.post('/api/tracks', json={**body, 'military': False}, headers=headers(client)).status_code == 422
        assert client.post('/api/tracks', json={**body, 'kind': 'unknown'}, headers=headers(client)).status_code == 422
        response = client.post('/api/tracks', json=body, headers=headers(client))
        assert response.status_code == 200
        result = response.json()
        track_id = result['track']['id']
        assert result['track']['active'] and result['track']['point_count'] == 1
        assert result['track']['military'] is True
        assert result['track']['ship_type_code'] is None
        assert result['points'][0]['latitude'] == 52
        assert client.get(f'/api/tracks/{track_id}').json() == result
        assert client.post('/api/tracks', json=body, headers=headers(client)).json() == result
        assert client.get('/api/tracks').json()['items'][0] == result['track']
        assert client.get(f'/api/tracks/{track_id}', headers={'Origin': 'https://evil.invalid'}).status_code == 403
        assert client.post(f'/api/tracks/{track_id}/stop').status_code == 403
        stopped = client.post(f'/api/tracks/{track_id}/stop', headers=headers(client))
        assert stopped.status_code == 200 and not stopped.json()['track']['active']
        assert stopped.json()['track']['military'] is True
        assert stopped.json()['points'] == result['points']
        assert client.get('/api/tracks/missing').status_code == 404
        assert client.post('/api/tracks/missing/stop', headers=headers(client)).status_code == 404

    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        restored = client.get(f'/api/tracks/{track_id}').json()
        assert restored['points'] == result['points']
        assert not restored['track']['active']
        assert restored['track']['military'] is True
        assert client.post('/api/tracks', json=body, headers=headers(client)).status_code == 422


def test_ship_tracking_api_uses_trusted_type_and_preserves_archive(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    histories = {}
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        tracking = app.state.tracking
        at = app.state.repo.clock().isoformat()
        codes = [35.0, 70, 1, 99, None]
        items = [{'mmsi': str(261123456+i), 'name': f'SHIP {i}', 'latitude': 55,
                  'longitude': 19, 'position_at': at, 'type_code': code, 'military': True}
                 for i, code in enumerate(codes)]

        class Source:
            async def fetch(self):
                return {'status': 'ready', 'items': items}

        tracking.demo = False
        tracking.services['ship'] = Source()
        for item in items:
            body = {'kind': 'ship', 'object_id': item['mmsi']}
            for field in ('type_code', 'ship_type_code'):
                forged = client.post('/api/tracks', json={**body, field: 80}, headers=headers(client))
                assert forged.status_code == 422
            response = client.post('/api/tracks', json=body, headers=headers(client))
            assert response.status_code == 200
            result = response.json()
            track_id = result['track']['id']
            assert result['track']['ship_type_code'] == item['type_code']
            assert result['track']['military'] is None
            if item['type_code'] is not None:
                assert type(result['track']['ship_type_code']) is int
            assert client.get(f'/api/tracks/{track_id}').json() == result
            stopped = client.post(f'/api/tracks/{track_id}/stop', headers=headers(client))
            assert stopped.status_code == 200
            assert stopped.json()['track']['ship_type_code'] == result['track']['ship_type_code']
            assert stopped.json()['points'] == result['points']
            histories[track_id] = stopped.json()
        assert {row['id']: row['ship_type_code'] for row in client.get('/api/tracks').json()['items']} == {
            track_id: history['track']['ship_type_code'] for track_id, history in histories.items()}

    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        for track_id, history in histories.items():
            assert client.get(f'/api/tracks/{track_id}').json() == history
