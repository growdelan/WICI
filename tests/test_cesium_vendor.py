"""Pinned runtime integrity and same-origin delivery for the offline 3D viewer."""
import runpy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wici.app import create_app

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'src/wici/static/vendor/cesium'
VENDOR_SCRIPT = runpy.run_path(str(ROOT / 'scripts/vendor_cesium.py'))


def test_cesium_runtime_matches_pinned_manifest_offline():
    files = VENDOR_SCRIPT['check_vendor'](VENDOR)
    assert 'Cesium.js' in files and 'LICENSE.md' in files and 'ThirdParty.json' in files
    assert not any(name.endswith('.map') or name in {'index.js', 'index.cjs'} for name in files)
    assert all(not name.startswith(('Source/', 'node_modules/')) for name in files)
    assert b'Version 1.146.0' in files['Cesium.js'][:150]
    assert VENDOR_SCRIPT['GLOBAL_LOOKUP'] not in files['Cesium.js']
    assert VENDOR_SCRIPT['SAFE_GLOBAL_LOOKUP'] in files['Cesium.js']


def test_cesium_vendoring_rejects_unpinned_archive():
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        VENDOR_SCRIPT['runtime_files'](b'not the pinned Cesium npm package')


@pytest.mark.parametrize(('asset', 'media_type'), [
    ('Cesium.js', 'javascript'),
    ('Workers/createGeometry.js', 'javascript'),
    ('Widgets/widgets.css', 'text/css'),
    ('ThirdParty/draco_decoder.wasm', 'application/wasm'),
    ('Assets/approximateTerrainHeights.json', 'application/json'),
])
def test_cesium_static_resources_delivered_locally_with_csp(tmp_path, asset, media_type):
    client = TestClient(create_app(root=tmp_path, demo=True), base_url='http://127.0.0.1:8765')
    response = client.get('/static/vendor/cesium/' + asset)
    assert response.status_code == 200
    assert media_type in response.headers['content-type']
    csp = response.headers['content-security-policy']
    assert "script-src 'self' 'wasm-unsafe-eval';" in csp and "worker-src 'self' blob:;" in csp
    assert "connect-src 'self';" in csp and "img-src 'self' data: blob:;" in csp
    assert 'https:' not in csp and "'unsafe-eval'" not in csp
    assert response.headers['x-content-type-options'] == 'nosniff'
