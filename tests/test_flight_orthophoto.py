"""Flight replay WMTS contract, including the provider's PNG disguised as JPEG."""
import asyncio
import json
import warnings
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from wici.app import create_app
from wici.config import Config
from wici.flight_orthophoto import MAX_BYTES, WMTS, FlightOrthophoto, OrthophotoUnavailable
from wici.scheduler import INTERVALS

NOW = datetime(2026, 11, 6, tzinfo=UTC)
REPLAY = '/api/flight-replay'
TILE = REPLAY + '/orthophoto/11/1143/674.jpg'


def raster(driver='JPEG', width=256):
    count = 3 if driver == 'JPEG' else 4
    data = np.full((count, 256, width), 150, dtype='uint8')
    if count == 4:
        data[3, :, :width//2] = 0
    with warnings.catch_warnings(), MemoryFile() as memory:
        warnings.simplefilter('ignore', NotGeoreferencedWarning)
        with memory.open(driver=driver, width=width, height=256, count=count, dtype='uint8') as dataset:
            dataset.write(data)
        return memory.read()


def write_episodes(root):
    directory = root / 'var/live/flight-replay'
    episode = {
        'icao': 'abcdef', 'label': 'Test', 'flight_source': 'Test', 'radar_source': 'Test',
        'points': [{'time': t, 'lat': 52, 'lon': 21, 'alt_m': 100} for t in [1200, 1210]],
        'frames': [{'time': 1200, 'tiles': [{'x': 0, 'y': 0, 'z': 0, 'file': 'test.png'}]}],
    }
    raw = json.dumps(episode).encode()
    for path in (directory, directory / 'aircraft/abcdef'):
        path.mkdir(parents=True, exist_ok=True)
        (path / 'episode.json').write_bytes(raw)
    return sha256(raw).hexdigest()[:20]


@pytest.mark.parametrize(('demo', 'enabled'), [(False, None), (False, False), (True, True)])
def test_same_origin_config_demo_and_both_manifests(tmp_path, demo, enabled):
    requests = []
    content = raster()
    def provider(request):
        requests.append(request)
        return httpx.Response(200, content=content, headers={'content-type': 'image/jpeg'})

    sources = {key: {'enabled': False} for key in INTERVALS}
    if enabled is not None:
        sources['flight_orthophoto'] = {'enabled': enabled}
    network = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app = create_app(demo, root=tmp_path, config=Config(sources=sources), client=network)
    revision = write_episodes(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        for url in (REPLAY, f'{REPLAY}/aircraft/abcdef/episode?revision={revision}'):
            response = client.get(url)
            if demo:
                assert response.status_code == 404
            else:
                assert response.json()['orthophoto_enabled'] is (enabled is not False)
        assert client.get(TILE, headers={'Origin': 'https://example.com'}).status_code == 403
        assert client.get(TILE, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        for xyz in ('10/571/337', '20/585216/345088', '11/0/0', '11/-1/1', '11/2048/674'):
            assert client.get(f'{REPLAY}/orthophoto/{xyz}.jpg').status_code == 404
        assert not requests
        tile = client.get(TILE)
        assert 'geoportal.gov.pl' not in tile.headers['content-security-policy']
        if demo or enabled is False:
            assert tile.status_code == 404 and not requests
        else:
            assert tile.status_code == 200 and tile.content == content
            assert tile.headers['content-type'] == 'image/jpeg'
            assert client.get(TILE).content == content and len(requests) == 1
            assert str(requests[0].url).split('?')[0] == WMTS
            assert dict(requests[0].url.params) == {
                'SERVICE':'WMTS', 'VERSION':'1.0.0', 'REQUEST':'GetTile', 'LAYER':'ORTOFOTOMAPA',
                'STYLE':'default', 'FORMAT':'image/jpeg', 'TILEMATRIXSET':'EPSG:3857',
                'TILEMATRIX':'EPSG:3857:11', 'TILECOL':'1143', 'TILEROW':'674'}
    asyncio.run(network.aclose())


async def test_shared_fetch_alpha_and_cache_expiry():
    calls = []
    now = NOW
    content = raster('PNG')
    async def provider(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, content=content, headers={'content-type': 'image/jpeg'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as network:
        service = FlightOrthophoto(network, lambda: now)
        first, second = await asyncio.gather(service.tile(19, 292608, 172544), service.tile(19, 292608, 172544))
        assert first == second == (content, 'image/png')
        now += timedelta(hours=5)
        assert await service.tile(19, 292608, 172544) == first and len(calls) == 1
        now += timedelta(hours=2)
        assert await service.tile(19, 292608, 172544) == first and len(calls) == 2


@pytest.mark.parametrize('failure', ['redirect', 'jpeg', 'png_size', 'oversize', '429', 'xml'])
async def test_bad_data_and_backoff(failure):
    now = NOW
    calls = []
    def provider(request):
        calls.append(request)
        if len(calls) > 1:
            return httpx.Response(404)
        if failure == 'redirect':
            return httpx.Response(302, headers={'location': 'https://example.com'})
        if failure == '429':
            return httpx.Response(429, headers={'retry-after':'180'})
        content = {'jpeg': b'\xff\xd8\xffbad\xff\xd9', 'png_size': raster('PNG', 32),
                   'oversize': b'x'*(MAX_BYTES+1), 'xml': b'<Exception/>'}[failure]
        return httpx.Response(200, content=content, headers={'content-type':'image/jpeg'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider), follow_redirects=True) as network:
        service = FlightOrthophoto(network, lambda: now)
        with pytest.raises(OrthophotoUnavailable) as ex:
            await service.tile(11, 1143, 674)
        assert ex.value.retry_in == (180 if failure == '429' else 30)
        now += timedelta(seconds=29)
        with pytest.raises(OrthophotoUnavailable):
            await service.tile(11, 1144, 674)
        assert len(calls) == 1
        now += timedelta(seconds=151)
        assert await service.tile(11, 1144, 674) is None
        assert await service.tile(11, 1144, 674) is None
        assert len(calls) == 2


async def test_rate_cap_serves_cached_images(monkeypatch):
    monkeypatch.setattr('wici.flight_orthophoto.MAX_CALLS_PER_MINUTE', 1)
    data = raster()
    def provider(request):
        return httpx.Response(200, content=data, headers={'Content-Type': 'image/jpeg'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as network:
        now = NOW
        service = FlightOrthophoto(network, lambda: now)
        assert await service.tile(11, 1143, 674) == (data, 'image/jpeg')
        with pytest.raises(OrthophotoUnavailable) as ex:
            await service.tile(11, 1144, 674)
        assert ex.value.retry_in == 60
        assert await service.tile(11, 1143, 674) == (data, 'image/jpeg')
        now += timedelta(seconds=60)
        assert await service.tile(11, 1144, 674) == (data, 'image/jpeg')


async def test_download_stops_at_byte_cap_without_content_length():
    class TooLarge(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(MAX_BYTES//16384 + 1):
                yield b'x'*16384
            pytest.fail('The rest of the oversized response was read')

    def provider(request):
        return httpx.Response(200, stream=TooLarge(), headers={'Content-Type': 'image/jpeg'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as network:
        service = FlightOrthophoto(network, lambda: NOW)
        with pytest.raises(OrthophotoUnavailable):
            await service.tile(11, 1143, 674)
        assert not service.pending and not service.cache


async def test_cancelled_leader_releases_slot_for_waiting_duplicate(monkeypatch):
    monkeypatch.setattr('wici.flight_orthophoto.MAX_PENDING', 1)
    first_started = asyncio.Event()
    calls = 0
    data = raster()
    async def provider(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await asyncio.Future()  # Cancelled when the first viewer leaves.
        return httpx.Response(200, content=data, headers={'Content-Type': 'image/jpeg'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as network:
        service = FlightOrthophoto(network, lambda: NOW)
        leader = asyncio.create_task(service.tile(11, 1143, 674))
        await first_started.wait()
        duplicate = asyncio.create_task(service.tile(11, 1143, 674))
        await asyncio.sleep(0)
        with pytest.raises(OrthophotoUnavailable):
            await service.tile(11, 1144, 674)
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        assert await asyncio.wait_for(duplicate, timeout=2) == (data, 'image/jpeg')
        assert calls == 2 and not service.pending
