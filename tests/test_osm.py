"""OSM raster fetches are the only external map permission; demo stays local-only."""
from fastapi.testclient import TestClient

from wici.app import create_app


def test_live_only_osm_raster_origin_no_external_scripts(tmp_path):
    # The response middleware is independent of lifespan: no collectors/network start.
    client = TestClient(create_app(root=tmp_path),base_url='http://127.0.0.1:8765')
    response = client.get('/')
    assert response.status_code == 200
    csp = response.headers['content-security-policy']
    assert "img-src 'self' data: blob: https://tile.openstreetmap.org;" in csp
    assert "connect-src 'self' https://tile.openstreetmap.org;" in csp
    assert "script-src 'self' 'wasm-unsafe-eval';" in csp
    assert "worker-src 'self' blob:;" in csp
    assert "'unsafe-eval'" not in csp
    assert response.headers['referrer-policy'] == 'strict-origin-when-cross-origin'


def test_demo_does_not_authorize_external_map_images(tmp_path):
    client = TestClient(create_app(root=tmp_path,demo=True),base_url='http://127.0.0.1:8765')
    response = client.get('/')
    csp = response.headers['content-security-policy']
    assert "img-src 'self' data: blob:;" in csp
    assert "connect-src 'self';" in csp
    assert "script-src 'self' 'wasm-unsafe-eval';" in csp
    assert "worker-src 'self' blob:;" in csp
    assert "'unsafe-eval'" not in csp
    assert 'tile.openstreetmap.org' not in csp
    assert response.headers['referrer-policy'] == 'no-referrer'
