"""Local API boundary, isolated demo and credential handling for Sentinel-5P."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.sentinel5p import Sentinel5PError


@pytest.fixture
def api(tmp_path):
    def reject_network(request):
        pytest.fail(f'Offline demo attempted network access: {request.url.host}')

    client = httpx.AsyncClient(transport=httpx.MockTransport(reject_network))
    app = create_app(demo=True, root=tmp_path, config=Config(), client=client)
    with TestClient(app, base_url='http://127.0.0.1:8765') as session:
        yield session, app


def test_demo_api_is_offline_with_separate_parameter_date_and_selection(api):
    session, _ = api
    assert session.get('/api/sentinel5p/status').json()['status'] == 'demo'
    for parameter in ('no2', 'so2', 'aer_ai'):
        query = {'parameter': parameter, 'day': '2026-10-15'}
        result = session.get('/api/sentinel5p/search', params=query)
        assert result.status_code == 200
        item = result.json()['items'][0]
        rendered = session.get('/api/sentinel5p/render', params={**query, 'identifier': item['id']})
        assert rendered.status_code == 200
        data = rendered.json()
        assert data['image'] and data['item']['id'] == item['id']
        assert '2026-10-15' in json.dumps(data['item'])
        assert session.get('/api/sentinel5p/render', params={**query, 'identifier': 'unknown'}).status_code == 404
    assert session.get('/api/gios').json()['demo'] is True


@pytest.mark.parametrize('path', ['status', 'search', 'render'])
def test_cross_origin_satellite_requests_are_rejected(api, path):
    session, _ = api
    for headers in ({'origin': 'https://external.invalid'}, {'sec-fetch-site': 'cross-site'}):
        assert session.get(f'/api/sentinel5p/{path}', headers=headers).status_code == 403


@pytest.mark.parametrize('query', [
    {'parameter': 'PM10', 'day': '2026-10-15'},
    {'parameter': 'no2', 'day': 'not-a-date'},
    {'parameter': 'no2', 'day': '2010-01-01'},
    {'parameter': 'no2', 'day': '2100-01-01'},
])
def test_api_validates_parameter_and_day(api, query):
    session, _ = api
    assert session.get('/api/sentinel5p/search', params=query).status_code == 422


def test_provider_errors_keep_retry_after_and_status(api):
    session, app = api

    class Limited:
        async def search(self, parameter, day):
            raise Sentinel5PError('CDSE: limit konta.', 429, 7, 'rate_limited')

        async def close(self):
            pass

    app.state.sentinel5p = Limited()
    response = session.get('/api/sentinel5p/search', params={'parameter': 'no2', 'day': '2026-10-15'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '7'
    assert response.json() == {'detail': 'CDSE: limit konta.', 'status': 'rate_limited'}


def test_satellite_credentials_are_masked_in_configuration():
    config = Config(sources={'sentinel5p': {'client_id': 'unique-client-id', 'client_secret': 'unique-secret'}})
    assert config.sources['sentinel5p']['client_secret'].get_secret_value() == 'unique-secret'
    for serialized in (str(config), config.model_dump_json()):
        assert 'unique-secret' not in serialized
        assert 'unique-client-id' not in serialized
