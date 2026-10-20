"""The AIS endpoint stays local, keeps credentials private, and demos stay offline."""
import json

from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config


def test_ships_demo_api_and_origin_guard(tmp_path):
    secret = 'test-secret-never-return-to-browser'
    config = Config(sources={'ships': {'api_key': secret}})
    with TestClient(create_app(demo=True, root=tmp_path, config=config), base_url='http://127.0.0.1:8765') as client:
        response = client.get('/api/ships')
        assert response.status_code == 200
        data = response.json()
        assert data['demo'] and data['items'] == [] and data['message']
        assert data['refresh_seconds'] == 10
        assert secret not in json.dumps(data)
        assert client.get('/api/ships', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.get('/api/ships', headers={'Origin': 'https://attacker.example'}).status_code == 403
        html = client.get('/').text
        assert 'id="ships-map-legend"' in html
        assert 'Wojskowe według AIS — kod 35' in html
        assert 'Typy cywilne według AIS' in html
        assert 'Nieustalone — brak lub niejednoznaczny typ' in html
        assert 'Brak kodu 35 nie oznacza, że jednostka jest cywilna.' in html


def test_config_masks_ais_key_in_representation():
    secret = 'private-test-ais-key'
    config = Config(sources={'ships': {'api_key': f' {secret} '}})
    assert config.ships_key() == secret
    assert secret not in repr(config)
    assert secret not in config.model_dump_json()
