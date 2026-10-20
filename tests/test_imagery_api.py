"""Local imagery routes, offline mode and preview error handling."""
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.imagery import ImageryUnavailable


def test_imagery_demo_stays_offline_and_has_ui(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        response = client.get('/api/imagery?lat=50.43&lon=16.65')
        assert response.status_code == 200
        data = response.json()
        assert data['enabled'] is False and data['items'] == []
        assert client.get('/api/imagery?lat=50&lon=16',
                          headers={'sec-fetch-site':'cross-site'}).status_code == 403
        assert client.get('/api/imagery/preview/unknown',
                          headers={'sec-fetch-site':'cross-site'}).status_code == 403
        assert client.get('/api/imagery?lat=oops&lon=16').status_code == 422
        assert client.get('/api/imagery?lat=50').status_code == 422
        html = client.get('/').text
        assert 'id="imagery-enabled"' in html and '/static/js/imagery.js' in html


def test_imagery_routes_preview_errors_and_coordinates(tmp_path):
    app = create_app(demo=True, root=tmp_path,
                     config=Config(sources={'imagery':{'enabled':False}}))
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/imagery?lat=52&lon=19').json()['enabled'] is False

        class FakeService:
            async def search(self, lat, lon):
                return {'point':[lat, lon], 'items':[]}

            async def preview(self, image_id):
                if image_id == 'missing':
                    raise KeyError(image_id)
                if image_id == 'unavailable':
                    raise ImageryUnavailable('Podgląd niedostępny')
                return b'preview', 'image/png'

        app.state.imagery = FakeService()
        assert client.get('/api/imagery?lat=50.5&lon=16.2').json()['point'] == [50.5, 16.2]
        image = client.get('/api/imagery/preview/example')
        assert image.content == b'preview' and image.headers['content-type'] == 'image/png'
        assert "img-src 'self'" in image.headers['content-security-policy']
        assert client.get('/api/imagery/preview/missing').status_code == 404
        assert client.get('/api/imagery/preview/unavailable').status_code == 503


def test_imagery_ui_lifecycle():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for browser lifecycle regression')
    subprocess.run([node, 'tests/imagery_ui.cjs'], cwd=Path(__file__).resolve().parents[1],
                   check=True, capture_output=True, text=True, timeout=15)
