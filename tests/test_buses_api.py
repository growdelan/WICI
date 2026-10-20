"""Local buses route, offline demo and browser lifecycle integration."""
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config


@pytest.mark.asyncio
@pytest.mark.parametrize('demo,enabled', [(True, True), (False, False)])
async def test_buses_offline_modes_and_origin_guards(tmp_path, demo, enabled):
    def handler(request):
        raise AssertionError(f'Unexpected network request: {request.url}')

    config = Config(sources={name: {'enabled': False} for name in
                            ('imgw_meteo', 'rso', 'rcb', 'sg', 'firms')})
    config.sources['buses'] = {'enabled': enabled}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as network:
        with TestClient(create_app(demo=demo, root=tmp_path, config=config, client=network),
                        base_url='http://127.0.0.1:8765') as client:
            for city in ('szczecin', 'krakow', 'poznan', 'warszawa'):
                response = client.get('/api/buses', params={'city': city})
                assert response.status_code == 200
                data = response.json()
                assert data['items'] == [] and data['demo'] == demo
                assert data['city'] == city
                if not enabled:
                    assert not data['enabled']
            assert client.get('/api/buses').json()['city'] == 'szczecin'
            assert client.get('/api/buses?city=unknown').status_code == 422
            assert client.get('/api/buses', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
            assert client.get('/api/buses', headers={'Origin': 'https://example.com'}).status_code == 403
            html = client.get('/').text
            assert 'id="buses-enabled"' in html and 'id="buses-line"' in html
            assert '/static/js/buses.js' in html
            assert client.get('/static/js/buses.js').status_code == 200


def test_buses_route_returns_service_snapshot(tmp_path):
    class Buses:
        async def fetch(self, city):
            return {'items': [{'id': f'{city}:3', 'line': '60'}], 'status': 'ready'}

    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        app.state.buses = Buses()
        assert client.get('/api/buses').json()['items'] == [{'id': 'szczecin:3', 'line': '60'}]
        assert client.get('/api/buses?city=krakow').json()['items'] == [{'id': 'krakow:3', 'line': '60'}]


def test_warsaw_key_is_protected_and_never_returned_by_api(tmp_path):
    secret = 'synthetic-warsaw-secret'
    config = Config(sources={'buses_warsaw': {'api_key': f' {secret} '}})
    assert config.warsaw_key() == secret
    assert secret not in repr(config)
    assert secret not in config.model_dump_json()
    with TestClient(create_app(demo=True, root=tmp_path, config=config),
                    base_url='http://127.0.0.1:8765') as client:
        assert secret not in client.get('/api/buses?city=warszawa').text


@pytest.mark.asyncio
async def test_provider_selection_is_lazy_and_city_failures_are_independent():
    from datetime import UTC, datetime

    from wici.buses import CityBusService

    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: calls.append(request))) as network:
        service = CityBusService(network, lambda: datetime.now(UTC), Config())
        assert not calls

        class Provider:
            def __init__(self, status):
                self.status = status
                self.calls = 0

            async def fetch(self):
                self.calls += 1
                return {'status': self.status, 'items': []}

        krakow, warsaw = Provider('ready'), Provider('error')
        service.providers.update(krakow=krakow, warszawa=warsaw)
        assert (await service.fetch('warszawa'))['status'] == 'error'
        assert krakow.calls == 0
        assert (await service.fetch('krakow'))['status'] == 'ready'
        assert krakow.calls == 1 and warsaw.calls == 1


def test_buses_ui_lifecycle():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the browser lifecycle regression')
    subprocess.run([node, 'tests/buses_ui.cjs'], cwd=Path(__file__).resolve().parents[1],
                   check=True, capture_output=True, text=True, timeout=10)
