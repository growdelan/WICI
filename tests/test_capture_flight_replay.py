"""Validate acquisition boundaries and the atomic switch of local episodes."""
import struct
import zlib

import httpx
import pytest

from wici import replay_capture as capture


def fix(time, *, flight=None, course=180, alt_geom=5000, flag=0, alt_baro=4900):
    fields = {'flight': flight} if flight else None
    return [time, 52.1, 20.9, alt_baro, 210, course, flag, 500, fields, 'adsb_icao', alt_geom]


def test_trace_uses_identified_leg_with_overlapping_radar_and_geometric_altitude():
    # A longer leg with only one radar frame must not hide a shorter,
    # properly bracketed leg. Duplicate integer seconds keep the last fix.
    rows = [fix(t, flight='AAA1' if t == 0 else None) for t in range(0, 481, 60)]
    rows += [fix(482, alt_baro='ground'), fix(500, flight='BBB2'), fix(560, alt_geom=5100),
             fix(560.1, alt_geom=5200), fix(650), fix(750), fix(810, alt_geom=None, alt_baro=4600, flag=8)]
    name, points, stamps = capture.select_leg({'timestamp': 1200, 'trace': rows}, [1200, 1800])
    assert name == 'BBB2'
    assert [p['time'] for p in points] == [1700, 1760, 1850, 1950, 2010]
    assert [p['alt_m'] for p in points] == pytest.approx([1524, 1584.96, 1524, 1524, 1402.08])
    assert stamps == [1200, 1800]


def test_gap_and_ground_split_the_track_even_when_callsign_matches():
    rows = [fix(20, flight='BBB2'), fix(150), fix(300), fix(410), fix(500, alt_baro='ground'),
            fix(600), fix(690), fix(800), fix(900)]
    assert capture.select_leg({'timestamp': 1200, 'trace': rows}, [1200, 1800], 'BBB2') is None


def png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    header = struct.pack('!IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(b'\x00'*5)) + chunk(b'IEND', b''))


def test_failed_import_or_bad_tile_preserves_previously_published_material(tmp_path, monkeypatch):
    points = [{'time': time, 'lat': 52, 'lon': 20, 'alt_m': 1500} for time in [1200, 1250]]
    metadata = capture.describe('TEST1', 'abcdef', points)
    body = png()
    images = {(1200, 6, 35, 21): body}
    capture.publish(tmp_path, metadata, images)
    assert capture.read_saved(tmp_path) == (metadata, images)
    original = (tmp_path / 'episode.json').read_bytes()
    with pytest.raises(ValueError, match='PNG'):
        capture.publish(tmp_path, {**metadata, 'label': 'Test 2'}, {(1200, 6, 35, 21): body[:-10]})
    monkeypatch.setattr(capture, 'MAX_IMPORT_BYTES', len(body) - 1)
    with pytest.raises(ValueError, match='64 MiB'):
        capture.read_saved(tmp_path)
    assert (tmp_path / 'episode.json').read_bytes() == original


def trace_of(rows):
    return {'timestamp': 1200, 'icao': 'abcdef', 'trace': rows}


def test_newest_matching_flight_supersedes_longer_leg_even_with_same_callsign():
    older = [fix(t, flight='TEST1' if t == 0 else None) for t in range(0, 851, 100)]
    newer = [fix(900, flag=2, flight='TEST1'), *(fix(t) for t in range(1000, 1301, 100))]
    times = [1200, 1800, 2400]
    _, points, frames = capture.select_leg(trace_of(older + newer), times, 'TEST1', current=True)
    assert points[0]['time'] == 2100
    assert frames == [1800, 2400]

    for latest in (fix(1400, flag=2, flight='TEST1'), fix(1400, flight='DIFF2')):
        history = trace_of(older + newer + [latest])
        assert capture.select_leg(history, times, 'TEST1', current=True) is None
    # Anonymous manual ICAO selection can choose the latest qualifying segment.
    _, points, _ = capture.select_leg(history, times, current=True)
    assert points[0]['time'] == 2100
    # Explicit historic CLI callsign still works after another flight takes off.
    _, points, _ = capture.select_leg(history, times, 'TEST1')
    assert points[0]['time'] == 2100


def test_trace_without_callsign_is_addressed_by_icao_and_never_attached_to_named_leg():
    anonymous = [fix(t) for t in range(200, 701, 100)]
    rows = anonymous + [fix(800, flight='TEST2')]
    times = [1200, 1800]
    name, points, _ = capture.select_leg(trace_of(rows), times)
    assert name == '' and points[-1]['time'] == 1900
    assert capture.select_leg(trace_of(rows), times, 'TEST2', current=True) is None
    meta = capture.describe(name, 'ABCDEF', points)
    assert meta['label'] == 'ABCDEF' and meta['icao'] == 'abcdef' and 'callsign' not in meta


class SharedRadar:
    def __init__(self, status='success'):
        self.status = status
        self.requests = []

    async def metadata(self):
        return {'status': self.status, 'frames': [{'timestamp': t} for t in (1200, 1800)]}

    async def tile(self, stamp, z, x, y):
        self.requests.append((stamp, z, x, y))
        return b'tile'


async def test_manual_capture_uses_one_aircraft_and_only_matching_shared_radar_frames():
    requests = []
    history = trace_of([fix(t, flight='TEST1' if t == 300 else None) for t in range(300, 701, 100)])
    def handle(request):
        requests.append(str(request.url))
        return httpx.Response(200, json=history)
    radar = SharedRadar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        meta, images = await capture.capture_recent(client, radar, 'ABCDEF', 'test1')
    assert requests == ['https://adsb.lol/data/traces/ef/trace_full_abcdef.json']
    assert meta['icao'] == 'abcdef' and meta['callsign'] == 'TEST1'
    assert set(images) == set(radar.requests)
    assert len(images) == 2 * len(capture.TILES)


@pytest.mark.parametrize(('http_status', 'radar_status', 'rows', 'expected'), [
    (404, 'success', [], capture.NoReplayHistory),
    (200, 'success', [], capture.NoReplayHistory),
    (200, 'error', [], capture.RadarUnavailable),
    (503, 'success', [], httpx.HTTPStatusError),
    (200, 'success', [None], ValueError),
])
async def test_only_absent_history_offers_observation(http_status, radar_status, rows, expected):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(http_status, json=trace_of(rows))
    )) as client:
        with pytest.raises(expected) as caught:
            await capture.capture_recent(client, SharedRadar(radar_status), 'abcdef')
    assert type(caught.value) is expected
