"""NEPTUN endpoints stay same-origin and demo startup stays offline."""
import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config


def test_demo_endpoints_are_initialized_without_external_network(tmp_path):
    def forbidden(request):
        raise AssertionError('Demo must not request external NEPTUN data')

    network = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    with TestClient(create_app(demo=True, root=tmp_path, client=network),
                    base_url='http://127.0.0.1:8765') as client:
        result = client.get('/api/ukraine')
        assert result.status_code == 200 and result.headers['Cache-Control'] == 'no-store'
        data = result.json()
        assert data['status'] == 'demo_no_data' and data['demo'] and data['refresh_seconds'] == 15
        assert data['alerts']['items'] == data['threats']['items'] == []
        geometry = client.get('/api/ukraine/geometry').json()
        assert geometry['status'] == 'demo_no_data'
        assert geometry['oblasts']['features'] == geometry['raions']['features'] == []


@pytest.mark.parametrize('endpoint', ['/api/ukraine', '/api/ukraine/geometry'])
@pytest.mark.parametrize('headers', [{'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'},
                                    {'Origin': 'https://example.com'}, {'Host': 'localhost:8765'}])
def test_origin_guard_rejects_before_upstream_fetch(endpoint, headers, tmp_path):
    app = create_app(root=tmp_path)
    # No lifespan or service: rejection must happen before the endpoint accesses the provider.
    client = TestClient(app, base_url='http://127.0.0.1:8765')
    assert client.get(endpoint, headers=headers).status_code in (400, 403)


def test_config_can_disable_source_and_requests_have_no_side_effects(tmp_path):
    app = create_app(demo=True, root=tmp_path, config=Config(sources={'ukraine': {'enabled': False}}))
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/ukraine').json()['status'] == 'disabled'
        assert client.get('/api/ukraine/geometry').json()['status'] == 'disabled'
