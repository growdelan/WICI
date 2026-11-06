"""Exercise the map/manual API through the real application, with offline providers."""
import asyncio
import struct
import time
import zlib
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.scheduler import INTERVALS

ORIGIN = 'http://127.0.0.1:8765'
AIRCRAFT = '/api/flight-replay/aircraft'


def radar_png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    header = struct.pack('!IIBBBBB', 256, 256, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(bytes(256 * 1025))) + chunk(b'IEND', b''))


@pytest.fixture
def backend(tmp_path):
    last_scan = int(datetime.now(UTC).timestamp()) // 600 * 600 - 600
    png = radar_png()
    feed = {'trace': 200, 'requests': 0}

    async def provider(request):
        if request.url.host == 'adsb.lol':
            feed['requests'] += 1
            await asyncio.sleep(.08)
            identity = request.url.path.split('_')[-1][:6]
            rows = [[i, 52, 21, 5000, 220, 10, 0, 0, {'flight': feed.get('callsign', 'TST42')}, None, 5100]
                    for i in range(0, 601, 60)]
            return httpx.Response(feed['trace'], json={'icao': identity, 'timestamp': last_scan - 600, 'trace': rows})
        if request.url.host == 'api.rainviewer.com':
            return httpx.Response(200, json={'host': 'https://tilecache.rainviewer.com', 'radar': {
                'past': [{'time': t, 'path': f'/v2/radar/{t}'} for t in [last_scan - 600, last_scan]]}})
        if request.url.host == 'tilecache.rainviewer.com':
            return httpx.Response(200, content=png, headers={'Content-Type': 'image/png'})
        return httpx.Response(404)

    cfg = Config(sources={key: {'enabled': False} for key in INTERVALS if key not in ('aircraft', 'radar')})
    network = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app = create_app(root=tmp_path, config=cfg, client=network)
    with TestClient(app, base_url=ORIGIN) as client:
        client.headers.update({'Origin': ORIGIN, 'X-CSRF-Token': client.get('/api/health').json()['csrf_token']})
        yield app, client, feed
    asyncio.run(network.aclose())


def finish(client, icao, callsign=''):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f'{AIRCRAFT}/{icao}/status', params={'callsign': callsign}).json()
        if state['status'] != 'preparing':
            return state
        time.sleep(.01)
    pytest.fail('Timed out waiting for local capture')


def test_selected_lookup_deduplicates_and_serves_only_its_aircraft(backend, tmp_path):
    _, client, feed = backend
    base = f'{AIRCRAFT}/ABCDEF'
    legacy = tmp_path / 'var/live/flight-replay/episode.json'
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b'legacy episode')
    for _ in range(2):
        assert client.post(base + '/prepare', json={'callsign': 'tst42'}).json()['status'] == 'preparing'
    assert client.post(base + '/collect', json={'callsign': 'TST42'}).json()['status'] == 'preparing'
    assert client.post(base + '/prepare', json={'callsign': 'OTHER'}).json()['status'] == 'unavailable'
    ready = finish(client, 'abcdef', 'TST42')
    assert ready['status'] == 'ready' and ready['frames'] == 2 and ready['points'] == 11
    assert feed['requests'] == 1
    episode = client.get(ready['episode_url']).json()
    assert episode['icao'] == 'abcdef' and episode['callsign'] == 'TST42'
    tile = episode['frames'][0]['tiles'][0]['url']
    assert client.get(tile).content == radar_png()
    assert client.get(tile.replace('/abcdef/', '/ffffff/')).status_code == 404
    assert legacy.read_bytes() == b'legacy episode'
    # A manual lookup without a callsign still opens the specified airframe.
    assert client.post(f'{AIRCRAFT}/123def/prepare', json={}).json()['status'] == 'preparing'
    other = finish(client, '123def')
    assert client.get(other['episode_url']).json()['icao'] == '123def'
    assert client.get(tile).content == radar_png()
    # A subsequent flight by the same airframe cannot silently change an already open viewer.
    feed['callsign'] = 'NEXT42'
    client.post(base + '/prepare', json={'callsign': 'NEXT42'})
    following = finish(client, 'abcdef', 'NEXT42')
    assert client.get(following['episode_url']).json()['callsign'] == 'NEXT42'
    assert client.get(ready['episode_url']).json()['callsign'] == 'TST42'
    assert client.get(tile).status_code == 200


def test_missing_history_outage_and_saved_fallback_are_distinct(backend, monkeypatch):
    _, client, feed = backend
    monkeypatch.setattr('wici.replay_requests.RETRY_WINDOW', 0)
    path = f'{AIRCRAFT}/abcdef/prepare'
    client.post(path, json={})
    saved = finish(client, 'abcdef')['episode_url']
    feed['trace'] = 503
    client.post(path, json={})
    unavailable = finish(client, 'abcdef')
    assert unavailable['status'] == 'unavailable' and unavailable['saved_episode_url'] == saved
    feed['trace'] = 404
    client.post(path, json={'callsign': 'NEW1'})
    missing = finish(client, 'abcdef', 'NEW1')
    assert missing['status'] == 'no_history' and 'saved_episode_url' not in missing
    for _ in range(2):
        collecting = client.post(f'{AIRCRAFT}/abcdef/collect', json={'callsign': 'NEW1'}).json()
        assert collecting['status'] == 'collecting'
    assert client.post(path, json={}).json()['status'] == 'collecting'
    assert client.get(saved).status_code == 200


def test_lookup_validation_source_configuration_and_demo_isolation(backend, tmp_path):
    app, client, feed = backend
    path = f'{AIRCRAFT}/abcdef/prepare'
    assert client.post(path, json={}, headers={'X-CSRF-Token': 'invalid'}).status_code == 403
    assert client.get(f'{AIRCRAFT}/abcdef/status', headers={'Origin': 'https://other.invalid'}).status_code == 403
    assert client.post(f'{AIRCRAFT}/ABC12G/prepare', json={}).status_code == 422
    assert client.post(path, json={'source_url': 'https://other.invalid'}).status_code == 422
    app.state.radar.enabled = False
    assert client.post(path, json={}).json()['status'] == 'unavailable'
    assert client.get(f'{AIRCRAFT}/abcdef/status').json()['status'] == 'unavailable'
    assert client.post(f'{AIRCRAFT}/abcdef/collect', json={}).json()['status'] == 'unavailable'
    assert feed['requests'] == 0
    with TestClient(create_app(demo=True, root=tmp_path), base_url=ORIGIN) as demo:
        auth = {'Origin': ORIGIN, 'X-CSRF-Token': demo.get('/api/health').json()['csrf_token']}
        for action in ('prepare', 'collect'):
            assert demo.post(f'{AIRCRAFT}/abcdef/{action}', json={}, headers=auth).status_code == 404
        assert demo.get(f'{AIRCRAFT}/abcdef/status').status_code == 404
