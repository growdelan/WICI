"""A replay is a single revision of private local material, including after a new capture."""
import base64
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wici.flight_replay import create_replay_router


@pytest.fixture
def archive(tmp_path):
    directory = tmp_path / 'var/live/flight-replay'
    directory.mkdir(parents=True)
    episode = {
        'label': 'Próba', 'flight_source': 'synthetic', 'radar_source': 'synthetic',
        'points': [{'time': t, 'lat': 52, 'lon': 20, 'alt_m': 1000} for t in (1200, 1300)],
        'frames': [{'time': 1200, 'tiles': [{'x': 0, 'y': 0, 'z': 0, 'file': 'image.png'}]}],
    }
    def publish():
        pending = directory / 'pending.json'
        pending.write_text(json.dumps(episode))
        pending.replace(directory / 'episode.json')
    app = FastAPI()
    app.include_router(create_replay_router(tmp_path, False))
    return directory, episode, publish, TestClient(app)


def test_manifest_switch_invalidates_previous_tiles(archive):
    directory, episode, publish, client = archive
    assert client.get('/api/flight-replay').status_code == 404
    publish()
    first = client.get('/api/flight-replay').json()
    url = first['frames'][0]['tiles'][0]['url']
    assert 'file' not in first['frames'][0]['tiles'][0]
    assert client.get(url).status_code == 503
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+cplkAAAAASUVORK5CYII=')
    (directory / 'image.png').write_bytes(png)
    assert client.get(url).content == png
    assert client.get(url, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    episode['label'] = 'Następny lot'
    publish()
    assert client.get(url).status_code == 404
    assert client.get('/api/flight-replay').json()['label'] == 'Następny lot'


def test_demo_never_serves_private_recording(archive):
    directory, _, publish, _ = archive
    publish()
    app = FastAPI()
    app.include_router(create_replay_router(directory.parents[2], True))
    assert TestClient(app).get('/api/flight-replay').status_code == 404


def test_rejects_outside_files_and_duplicate_time(archive):
    directory, episode, publish, client = archive
    tile = episode['frames'][0]['tiles'][0]
    tile['file'] = '../outside.png'
    publish()
    assert client.get('/api/flight-replay').status_code == 503

    tile['file'] = 'image.png'
    outside = directory.parent / 'outside.png'
    outside.write_bytes(b'\x89PNG\r\n\x1a\nprivate')
    (directory / 'image.png').symlink_to(outside)
    publish()
    url = client.get('/api/flight-replay').json()['frames'][0]['tiles'][0]['url']
    assert client.get(url).status_code == 503
    episode['points'][1]['time'] = episode['points'][0]['time']
    publish()
    assert client.get('/api/flight-replay').status_code == 503


def test_requires_radar_near_an_actual_report(archive):
    _, episode, publish, client = archive
    episode['points'][1]['time'] = 10000
    # This frame lies inside the overall range, but long after the first point
    # and long before the second. There is no usable position for this image.
    episode['frames'][0]['time'] = 5000
    publish()
    assert client.get('/api/flight-replay').status_code == 503
    episode['frames'][0]['time'] = 9500
    publish()
    assert client.get('/api/flight-replay').status_code == 200
