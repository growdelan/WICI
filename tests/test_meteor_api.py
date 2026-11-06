"""Public entry points must serve the real example without contacting GMN."""
import asyncio

import httpx
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config


def test_example_and_origin_controls_offline(tmp_path):
    def offline(request):
        raise AssertionError(f'Unexpected external request to {request.url.host}')

    network = httpx.AsyncClient(transport=httpx.MockTransport(offline))
    cfg = Config(sources={'meteors': {'enabled': False}})
    app = create_app(demo=True, root=tmp_path, config=cfg, client=network)
    try:
        with TestClient(app, base_url='http://127.0.0.1:8765') as client:
            endpoint = '/api/meteors/night'
            reply = client.get(endpoint)
            assert reply.status_code == 200
            night = reply.json()
            assert night['bundled'] and night['date'] == '2026-11-04'
            events = {event['id']: event for event in night['events']}
            assert len(events) == len(night['events']) > 1
            nysa = events['20261104215730_pYgTq']
            assert nysa['duration'] == 4.08
            assert round(nysa['begin']['alt_km'], 2) == 82.67
            assert round(nysa['end']['alt_km'], 2) == 60.59
            assert client.get(endpoint, params={'date': '2026-11-04'}).json() == night
            assert client.get(endpoint, params={'date': '2026-11-03'}).status_code == 503
            assert client.get(endpoint, params={'date': '2026-02-30'}).status_code == 422
            assert client.get(endpoint, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    finally:
        asyncio.run(network.aclose())
