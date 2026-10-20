"""Aircraft endpoint integration remains local-only and demo stays offline."""
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from wici.app import create_app


def test_aircraft_demo_endpoint_and_cross_origin(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        response = client.get('/api/aircraft')
        assert response.status_code == 200
        data = response.json()
        assert data['items'] == [] and data['demo']
        assert data['refresh_seconds'] == 10
        assert data['source_name'] == 'adsb.fi' and data['source_url'] == 'https://adsb.fi/'
        assert client.get('/api/aircraft', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        html = client.get('/').text
        assert 'id="aircraft-enabled"' in html and '/static/js/aircraft.js' in html
        aircraft_panel = html.split('aria-label="Samoloty nad Polską"')[1].split('<hr>')[0]
        assert 'https://adsb.fi/' in aircraft_panel and 'ADSB.lol' not in aircraft_panel
        assert 'użytek osobisty, niekomercyjny' in aircraft_panel
        assert client.get('/static/js/aircraft.js').status_code == 200


def test_aircraft_ui_lifecycle():
    import pytest
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the browser lifecycle regression')
    subprocess.run([node, 'tests/aircraft_ui.cjs'], cwd=Path(__file__).resolve().parents[1],
                   check=True, capture_output=True, text=True, timeout=10)
