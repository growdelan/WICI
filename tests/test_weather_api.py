"""Weather endpoint stays local and respects explicit provider configuration."""
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config


def test_weather_demo_contract_and_no_foreign_origin(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        for mode in ['measurement', 'forecast']:
            response = client.get('/api/weather', params={'mode': mode})
            assert response.status_code == 200
            data = response.json()
            assert data['mode'] == mode and data['times'] and data['points']
            assert all(len(point['samples']) == len(data['times']) for point in data['points'])
        assert client.get('/api/weather?mode=other').status_code == 422
        assert client.get('/api/weather', headers={'sec-fetch-site':'cross-site'}).status_code == 403


def test_weather_explicitly_disabled_has_no_points(tmp_path):
    config = Config(sources={'weather_imgw':{'enabled':False}, 'weather_forecast':{'enabled':False}})
    with TestClient(create_app(demo=True, root=tmp_path, config=config), base_url='http://127.0.0.1:8765') as client:
        for mode in ['measurement', 'forecast']:
            data = client.get('/api/weather', params={'mode':mode}).json()
            assert data['enabled'] is False and not data['points']


def test_demo_regional_forecast_and_strict_region_validation(tmp_path):
    from wici.weather import GRID, REGION_GRIDS, in_region

    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        for code, grid in REGION_GRIDS.items():
            response = client.get('/api/weather', params={'mode': 'forecast', 'voivodeship': code})
            assert response.status_code == 200
            points = response.json()['points']
            assert len(points) == len(grid)
            assert all(in_region(p['latitude'], p['longitude'], code) for p in points)
        assert len(client.get('/api/weather?mode=forecast').json()['points']) == len(GRID)
        for code in ['99', '2']:
            assert client.get('/api/weather', params={'voivodeship': code}).status_code == 422
