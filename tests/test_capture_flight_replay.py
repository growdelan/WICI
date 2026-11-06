"""Validate acquisition boundaries and the atomic switch of local episodes."""
import importlib.util
import struct
import zlib
from pathlib import Path

import pytest


def load_script():
    path = Path(__file__).resolve().parents[1] / 'scripts/capture_flight_replay.py'
    spec = importlib.util.spec_from_file_location('capture_flight_replay', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = load_script()


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
