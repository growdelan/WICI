"""Conservative evidence, shared transport, persistence and offline lifecycle."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.aircraft import AircraftService
from wici.app import create_app
from wici.position_quality import PositionQuality
from wici.repository import Repository

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def record(i=1, **values):
    return {'hex': f'{i:06x}', 'type': 'adsb_icao', 'version': 2, 'lat': 52.2, 'lon': 21.1,
            'seen_pos': 1, 'nac_p': 9, 'nic': 8, 'rc': 186, **values}


def payload(at, ac):
    return {'now': at.timestamp()*1000, 'ac': ac, 'msg': 'No error'}


@pytest.fixture
def quality(tmp_path):
    repo = Repository(tmp_path/'quality.sqlite3', clock=lambda: NOW)
    q = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True)
    yield q
    repo.close()


def history(q):
    return q.history(NOW.date())


def collector_for(repo, endpoint):
    aircraft = AircraftService(None, repo.clock)
    aircraft.source_endpoint = endpoint
    return PositionQuality(repo, aircraft, enabled=True)


def collect_minutes(q, start, minutes, bad=0):
    for minute in range(minutes):
        at = start+timedelta(minutes=minute)
        q.ingest(payload(at, [record(i+1, nac_p=3 if i < bad else 9) for i in range(6)]), at)


def test_provider_change_cannot_use_previous_background_and_rewarms(tmp_path):
    repo = Repository(tmp_path/'epochs.sqlite3', clock=lambda: NOW)
    try:
        old = collector_for(repo, 'https://previous-provider.invalid/snapshot')
        collect_minutes(old, NOW-timedelta(minutes=90), 75)
        current = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True)
        assert current.epoch != old.epoch
        assert current.source_state['success'] is None
        collect_minutes(current, NOW-timedelta(minutes=15), 15, bad=4)
        result = history(current)
        recent = [i for i in result['items'] if i['epoch'] == current.epoch]
        assert recent and all(i['state'] == 'insufficient' and i['baseline'] is None for i in recent)
        assert any(i['state'] == 'normal' for i in result['items'] if i['epoch'] == old.epoch)
        # Genuine deterioration is still detected once the new source has its own healthy background.
        collect_minutes(current, NOW, 60)
        collect_minutes(current, NOW+timedelta(minutes=60), 15, bad=4)
        repo.clock = lambda: NOW+timedelta(minutes=75)
        recent = [i for i in history(current)['items'] if i['epoch'] == current.epoch]
        assert any(i['state'] == 'normal' for i in recent)
        assert any(i['state'] == 'anomaly' for i in recent)
    finally:
        repo.close()


def test_returning_provider_starts_new_epoch_but_restart_preserves_it(tmp_path):
    file = tmp_path/'epochs.sqlite3'
    repo = Repository(file, clock=lambda: NOW)
    first = collector_for(repo, 'https://first.invalid/snapshot')
    collect_minutes(first, NOW-timedelta(minutes=90), 60)
    second = collector_for(repo, 'https://second.invalid/snapshot')
    collect_minutes(second, NOW-timedelta(minutes=30), 15)
    returned = collector_for(repo, 'https://first.invalid/snapshot')
    collect_minutes(returned, NOW-timedelta(minutes=15), 15, bad=4)
    assert len({first.epoch, second.epoch, returned.epoch}) == 3
    expected = history(returned)
    assert all(i['state'] == 'insufficient' for i in expected['items'] if i['epoch'] == returned.epoch)
    epoch, state = returned.epoch, dict(returned.source_state)
    repo.close()
    repo = Repository(file, clock=lambda: NOW)
    try:
        reopened = collector_for(repo, 'https://first.invalid/snapshot')
        assert reopened.epoch == epoch and reopened.source_state == state
        assert history(reopened) == expected
    finally:
        repo.close()


def test_mixed_window_and_duplicate_aircraft_are_isolated_by_epoch(tmp_path):
    repo = Repository(tmp_path/'epochs.sqlite3', clock=lambda: NOW)
    try:
        old = collector_for(repo, 'https://previous-provider.invalid/snapshot')
        at = NOW-timedelta(minutes=4)
        collect_minutes(old, at, 1)
        current = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True)
        collect_minutes(current, at, 1, bad=4)
        collect_minutes(current, at, 1, bad=4)  # Duplicate only within the same epoch.
        result = history(current)
        item = result['items'][0]
        assert item['reports'] == 12 and item['aircraft'] == 6
        assert item['epoch'] is None and item['provenance'] == 'mixed'
        assert item['state'] == 'insufficient' and item['baseline'] is None
        assert repo.db.execute('SELECT count(*) FROM position_quality_samples').fetchone()[0] == 12
    finally:
        repo.close()


def test_delayed_previous_epoch_write_cannot_replace_current_source_or_freshness(tmp_path):
    repo = Repository(tmp_path/'epochs.sqlite3', clock=lambda: NOW)
    try:
        old = collector_for(repo, 'https://previous-provider.invalid/snapshot')
        captured = old.note_source('ready', NOW.timestamp(), success=True)
        current = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True)
        current.source('error', (NOW-timedelta(seconds=1)).timestamp())
        assert old.ingest(payload(NOW, [record()]), NOW, source_state=captured)
        saved = repo.db.execute('SELECT * FROM position_quality_source').fetchone()
        assert saved['epoch'] == current.epoch and saved['status'] == 'error' and saved['success'] is None
        assert history(current)['observation_age_seconds'] is None
        current.source('ready', NOW.timestamp(), success=True)  # Success without qualifying observations.
        assert history(current)['status'] == 'insufficient'
    finally:
        repo.close()


def test_migrate_unattributed_history_without_guessing_provider_or_detecting_anomalies(tmp_path):
    import sqlite3
    file = tmp_path/'legacy.sqlite3'
    db = sqlite3.connect(file)
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    for migration in migrations[:10]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=10')
    for ago in range(60, 0, -1):
        at = NOW-timedelta(minutes=ago)
        db.executemany('INSERT INTO position_quality_samples VALUES(?,?,?,?,?,?,?,?,?)',
                      [(int(at.timestamp()//60), f'{i+1:06x}', at.timestamp(), '52.0,21', '14', 1,
                        int(ago <= 15 and i < 4), 0, '{}') for i in range(6)])
    db.execute("INSERT INTO position_quality_source VALUES(1,?,?,?,'ready')", (NOW.timestamp(),)*3)
    db.commit()
    db.close()
    for _ in range(2):
        repo = Repository(file, clock=lambda: NOW)
        try:
            q = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True)
            result = history(q)
            assert result['coverage']['stored_reports'] == 360
            assert result['coverage']['unknown_provenance_reports'] == 360
            assert all(i['provenance'] == 'unknown' and i['state'] == 'insufficient'
                       and i['baseline'] is None for i in result['items'])
            assert result['source']['success'] is None and result['status'] == 'insufficient'
            assert repo.db.execute('PRAGMA foreign_key_check').fetchall() == []
        finally:
            repo.close()


def scenario(q, bad=4, count=6):
    for minute in range(60, 0, -1):
        at = NOW-timedelta(minutes=minute)
        q.ingest(payload(at, [record(i+1, nac_p=3 if minute <= 15 and i < bad else 9)
                              for i in range(count)]), at)


def test_cluster_persistence_baseline_and_distinct_aircraft(quality):
    scenario(quality)
    items = history(quality)['items']
    anomalies = [x for x in items if x['state'] == 'anomaly']
    assert anomalies and all(x['aircraft'] == 6 and x['degraded_aircraft'] == 4 for x in anomalies)
    assert any(x['state'] == 'normal' for x in items)
    assert all(x['background_windows'] >= 6 and x['share']-x['baseline'] >= .3 for x in anomalies)
    assert items[0]['state'] == 'insufficient'  # No invented background.


def test_single_transponder_and_low_traffic_never_alarm(quality):
    scenario(quality, bad=1)
    assert not any(x['state'] == 'anomaly' for x in history(quality)['items'])
    with quality.repo.lock, quality.repo.db:
        quality.repo.db.execute('DELETE FROM position_quality_samples')
    scenario(quality, bad=2, count=2)
    assert all(x['state'] == 'insufficient' for x in history(quality)['items'])


def test_dedup_missing_zero_sources_and_uncertain_location(quality):
    missing = record(2)
    for k in ['nac_p', 'nic', 'rc']:
        missing.pop(k)
    records = [record(1, nac_p=0), missing, record(3, type='mlat'),
               record(4, type='tisb_icao'), record(5, mlat=['lat', 'lon']),
               record(6, seen_pos=90, lastPosition={'lat': 52.2, 'lon': 21.1, 'seen_pos': 90}),
               record(7, lat=None, lon=None), record(8, version=0),
               record(9, type='other'), record(10, tisb=['lat']),
               record(11, version=1), record(12, version=True)]
    # Same exact source timestamp and duplicate entries cannot inflate any count.
    for _ in range(3):
        quality.ingest(payload(NOW, records+records), NOW)
    result = history(quality)
    item = result['items'][0]
    assert item['reports'] == 11 and item['aircraft'] == 2 and item['degraded_aircraft'] == 1
    assert item['context_reports'] == 1
    assert result['coverage']['unlocated_reports'] == 1
    row = quality.repo.db.execute("SELECT fields FROM position_quality_samples WHERE aircraft='000002'").fetchone()
    assert 'nac_p' not in json.loads(row[0])
    row = quality.repo.db.execute("SELECT fields FROM position_quality_samples WHERE aircraft='000001'").fetchone()
    assert json.loads(row[0])['nac_p'] == 0


def test_restart_retention_source_failure_and_stale(tmp_path):
    now = [NOW]
    file = tmp_path/'quality.sqlite3'
    repo = Repository(file, clock=lambda: now[0])
    q = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True, retention=50)
    scenario(q)
    count = repo.db.execute('SELECT count(*) FROM position_quality_samples').fetchone()[0]
    q.source('error', NOW.timestamp())
    assert history(q)['status'] == 'error'
    assert any(x['state'] == 'anomaly' for x in history(q)['items'])  # API failure doesn't create/delete evidence.
    repo.close()
    repo = Repository(file, clock=lambda: now[0])
    q = PositionQuality(repo, AircraftService(None, repo.clock), enabled=True, retention=50)
    assert repo.db.execute('SELECT count(*) FROM position_quality_samples').fetchone()[0] == count
    assert history(q)['status'] == 'error'
    q.source('ready', NOW.timestamp())
    now[0] += timedelta(minutes=10)
    assert history(q)['status'] == 'stale'
    now[0] += timedelta(hours=51)
    q.prune()
    assert repo.db.execute('SELECT count(*) FROM position_quality_samples').fetchone()[0] == 0
    repo.close()


@pytest.mark.asyncio
async def test_shared_collector_fetch_cache_retry_and_stop(tmp_path):
    now, calls = [NOW], []
    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(429, headers={'Retry-After': '180'})
        return httpx.Response(200, json=payload(now[0], [record()]))
    repo = Repository(tmp_path/'test.sqlite3', clock=lambda: now[0])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        aircraft = AircraftService(client, repo.clock)
        q = PositionQuality(repo, aircraft, enabled=True)
        q.start()
        await asyncio.sleep(.01)  # Collector works without any viewer or map.
        await asyncio.gather(aircraft.fetch(), aircraft.fetch())
        assert len(calls) == 1
        await q.flush()
        assert history(q)['items'][0]['reports'] == 1
        now[0] += timedelta(seconds=61)
        await aircraft.fetch()
        assert history(q)['status'] == 'error'
        now[0] += timedelta(seconds=179)
        await aircraft.fetch()
        assert len(calls) == 2
        now[0] += timedelta(seconds=1)
        await aircraft.fetch()
        await q.flush()
        assert len(calls) == 3 and history(q)['status'] == 'ready'
        await q.stop()
        assert q.task.done()
    repo.close()


@pytest.mark.asyncio
async def test_disabled_collector_and_demo_no_network(tmp_path):
    def handler(request):
        raise AssertionError('Network forbidden')
    repo = Repository(tmp_path/'test.sqlite3', clock=lambda: NOW)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for enabled, demo in [(False, False), (True, True)]:
            q = PositionQuality(repo, AircraftService(client, repo.clock, demo=demo), enabled=enabled, demo=demo)
            q.start()
            assert q.task is None
            result = history(q)
            assert result['status'] == ('ready' if demo else 'disabled')
            if demo:
                assert result['synthetic'] and any(x['state'] == 'anomaly' for x in result['items'])
            await q.stop()
    repo.close()


def test_demo_api_day_province_validation_and_loopback(tmp_path):
    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        data = client.get('/api/position-quality?hours=48').json()
        assert data['synthetic'] and data['items']
        assert any(i['state'] == 'anomaly' for i in data['items'])
        assert client.get('/api/position-quality?voivodeship=32').json()['items'] == []
        assert client.get('/api/position-quality?date=2020-01-01').json()['items'] == []
        assert client.get('/api/position-quality?hours=25').status_code == 422
        assert client.get('/api/position-quality?date=bad').status_code == 422
        assert client.get('/api/position-quality', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.get('/api/position-quality', headers={'host': 'example.com'}).status_code == 400
        html = client.get('/').text
        assert 'id="quality-enabled" type="checkbox">' in html


def test_synthetic_source_fixture_is_ingestible_without_claiming_history(quality):
    sample = json.loads((Path(__file__).parent/'fixtures/aircraft/synthetic.json').read_text())
    observed = datetime.fromtimestamp(sample['now']/1000, UTC)
    quality.ingest(sample, observed)
    rows = quality.repo.db.execute('SELECT fields FROM position_quality_samples').fetchall()
    assert rows and any('nac_p' in json.loads(r[0]) for r in rows)


def test_empty_response_and_experimental_marker_alone_cannot_alarm(quality):
    quality.ingest(payload(NOW, [record(1, gpsOkBefore=NOW.timestamp()-600)]), NOW)
    assert history(quality)['items'][0]['degraded_aircraft'] == 0
    quality.ingest(payload(NOW+timedelta(minutes=1), []), NOW+timedelta(minutes=1))
    assert not any(i['state'] == 'anomaly' for i in history(quality)['items'])
    # A fresh successful source read cannot mask old aircraft evidence.
    quality.repo.clock = lambda: NOW+timedelta(minutes=10)
    quality.ingest(payload(quality.repo.clock(), []), quality.repo.clock())
    result = quality.history(NOW.date())
    assert result['status'] == 'stale' and result['age_seconds'] == 0
    assert result['observation_age_seconds'] == 600


def test_rc_zero_alone_is_unknown_and_fields_are_validated(quality):
    a = record(rc=0, nac_p=None, nic=None, sil=0, sil_type='unknown')
    quality.ingest(payload(NOW, [a]), NOW)
    item = history(quality)['items'][0]
    assert item['aircraft'] == 0 and item['state'] == 'insufficient'
    assert item['availability']['rc'] == 1 and item['availability']['nac_p'] == 0
    assert item['availability']['sil'] == 1


def test_warsaw_historical_day_uses_civil_midnight_including_dst(quality):
    # Europe/Warsaw DST transition is 25 Oct 2026: following midnight is 23:00 UTC.
    from datetime import date
    quality.repo.clock = lambda: datetime(2026, 10, 27, tzinfo=UTC)
    end = quality.history(date(2026, 10, 25), 48)['window_end']
    assert datetime.fromtimestamp(end, UTC) == datetime(2026, 10, 25, 23, tzinfo=UTC)


def test_configuration_bounds():
    from pydantic import ValidationError

    from wici.config import Config
    for values in [{'interval_seconds': 1}, {'retention_hours': 49}, {'retention_hours': 169}]:
        with pytest.raises(ValidationError):
            Config(position_quality=values)
    assert not Config().position_quality.enabled


@pytest.mark.asyncio
async def test_read_only_storage_preserves_aircraft_cache_task_and_recovers(tmp_path, monkeypatch):
    from contextlib import contextmanager

    now, calls = [NOW], []
    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json=payload(now[0], [record()]))
    repo = Repository(tmp_path/'readonly.sqlite3', clock=lambda: now[0])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        aircraft = AircraftService(client, repo.clock)
        q = PositionQuality(repo, aircraft, enabled=True)
        readonly = [True]
        writer = q.writer_connection
        @contextmanager
        def readonly_writer():
            with writer() as db:
                if readonly[0]:
                    db.execute('PRAGMA query_only=ON')
                yield db
        monkeypatch.setattr(q, 'writer_connection', readonly_writer)
        q.start()
        try:
            async def failed():
                while q.storage_error is None:
                    await asyncio.sleep(.005)
            await asyncio.wait_for(failed(), timeout=2)
            assert not q.task.done() and not q.writer_task.done()
            result = await aircraft.fetch()
            assert result['status'] == 'ready' and len(result['items']) == 1 and len(calls) == 1
            status = history(q)
            assert status['status'] == 'error' and status['storage_error']
            assert status['status_label'] == 'Błąd zapisu kolektora'
            assert status['source']['attempt'] == NOW.timestamp()
            now[0] += timedelta(seconds=11)
            result = await aircraft.fetch()
            assert result['status'] == 'error' and result['stale'] and len(result['items']) == 1
            assert history(q)['source']['status'] == 'error'
            assert len(calls) == 2 and not q.task.done()
            readonly[0] = False
            # The writer retries the queued snapshot without another HTTP request.
            await asyncio.wait_for(q.flush(), timeout=3)
            assert len(calls) == 2 and not history(q)['storage_error']
            assert history(q)['source']['status'] == 'error'
            now[0] += timedelta(seconds=60)
            result = await aircraft.fetch()
            await q.flush()
            assert result['status'] == 'ready' and len(calls) == 3
            status = history(q)
            assert status['status'] == 'ready' and not status['storage_error']
            assert status['coverage']['stored_reports'] == 2
        finally:
            readonly[0] = False
            await q.stop()
            repo.close()
        assert q.task.done() and q.task.cancelled()
        assert q.writer_task.done()


@pytest.mark.asyncio
async def test_writer_contains_unexpected_collector_sqlite_failure(quality, monkeypatch):
    import sqlite3
    ingest, attempts = quality.ingest, []
    def failed_ingest(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise sqlite3.OperationalError('database is locked')
        return ingest(*args, **kwargs)
    monkeypatch.setattr(quality, 'ingest', failed_ingest)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload(NOW, [record()]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quality.aircraft.client = client
        try:
            result = await quality.aircraft.fetch()
            assert result['status'] == 'ready' and len(result['items']) == 1
            assert (await quality.aircraft.fetch()) == result and len(calls) == 1
            async def failed():
                while quality.storage_error is None:
                    await asyncio.sleep(.005)
            await asyncio.wait_for(failed(), timeout=2)
            assert history(quality)['storage_error']
            await asyncio.wait_for(quality.flush(), timeout=3)
            assert not history(quality)['storage_error'] and len(attempts) == 2
            assert not quality.writer_task.done()
        finally:
            await quality.stop()


@pytest.mark.parametrize('interval', [60, 300])
def test_all_supported_sampling_extremes_can_detect_persistence(quality, interval):
    from wici.config import Config
    assert Config(position_quality={'interval_seconds': interval}).position_quality.interval_seconds == interval
    for ago in range(7200, -1, -interval):
        at = NOW-timedelta(seconds=ago)
        ac = [record(i+1, nac_p=3 if ago <= 900 and i < 4 else 9) for i in range(6)]
        quality.ingest(payload(at, ac), at)
    result = history(quality)
    assert any(i['state'] == 'normal' for i in result['items'])
    assert any(i['state'] == 'anomaly' for i in result['items'])


def test_ten_minute_interval_is_rejected_before_starting_collector(quality):
    from pydantic import ValidationError

    from wici.config import Config
    for interval in [301, 600]:
        with pytest.raises(ValidationError):
            Config(position_quality={'interval_seconds': interval})
        with pytest.raises(ValueError, match='60–300'):
            PositionQuality(quality.repo, quality.aircraft, enabled=True, interval=interval)


def test_full_history_api_does_not_block_health_or_collector(tmp_path, monkeypatch):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    connect = sqlite3.connect
    class PausedReader(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith('SELECT * FROM position_quality_samples'):
                entered.set()
                assert release.wait(10), 'History reader never released'
            return super().execute(sql, *args, **kwargs)
    with TestClient(create_app(demo=True, root=tmp_path), base_url='http://127.0.0.1:8765') as client:
        q = client.app.state.position_quality
        repo = q.repo
        end = int(repo.clock().timestamp())
        fields = json.dumps({'nac_p': 9, 'nic': 8, 'version': 2, 'type': 'adsb_icao'})
        with repo.lock, repo.db:
            repo.db.execute('DELETE FROM position_quality_samples')
            repo.db.executemany('INSERT INTO position_quality_samples VALUES(?,?,?,?,?,?,?,?,?,?)',
                ((int((end-m*60)//60), f'{i:06x}', end-m*60, '52.0,21', '14', 1, 0, 0, fields, q.epoch)
                 for m in range(3000) for i in range(100)))
        monkeypatch.setattr('wici.position_quality.sqlite3.connect',
                            lambda *a, **kw: connect(*a, **kw, factory=PausedReader))
        with ThreadPoolExecutor(max_workers=3) as pool:
            request = pool.submit(client.get, '/api/position-quality?hours=48')
            try:
                assert entered.wait(5), 'History did not open an independent reader'
                health = pool.submit(client.get, '/api/health').result(timeout=2)
                assert health.status_code == 200
                # A paused worker read must not own repo.lock or the application's writer connection.
                collected = pool.submit(q.ingest, payload(repo.clock(), [record(999)]), repo.clock())
                collected.result(timeout=2)
            finally:
                release.set()
            result = request.result(timeout=15)
        assert result.status_code == 200
        data = result.json()
        assert data['coverage']['stored_reports'] == 300001
        assert len(data['items']) >= 576
        assert any(i['state'] == 'normal' for i in data['items'])
        assert data['status'] == 'ready'


def test_position_quality_ui_lifecycle_regressions():
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed for the UI lifecycle regressions')
    subprocess.run([node, 'tests/position_quality_ui.cjs'], cwd=Path(__file__).resolve().parents[1],
                   check=True, capture_output=True, text=True, timeout=10)


def test_begin_immediate_does_not_block_cache_api_queue_or_shutdown(tmp_path, monkeypatch):
    import sqlite3
    import time
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event, get_ident

    now, calls, timings = [NOW], [], {}
    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json=payload(now[0], [record()]))
    # Keep all unrelated sources in offline DEMO; replace only the aircraft/quality pair.
    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        repo = app.state.repo
        repo.clock = lambda: now[0]
        network = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        aircraft = AircraftService(network, repo.clock)
        q = PositionQuality(repo, aircraft, enabled=True)
        entered, release, writer_threads = Event(), Event(), []
        writer = q.writer_connection
        @contextmanager
        def paused_writer():
            with writer() as db:
                writer_threads.append(get_ident())
                entered.set()
                assert release.wait(5), 'Writer was never released'
                yield db
        monkeypatch.setattr(q, 'writer_connection', paused_writer)
        app.state.aircraft, app.state.position_quality = aircraft, q
        path = repo.db.execute('PRAGMA database_list').fetchone()[2]
        locker = sqlite3.connect(path)
        locker.execute('BEGIN IMMEDIATE')
        def wait_until(predicate):
            deadline = time.monotonic()+2
            while not predicate():
                assert time.monotonic() < deadline, 'Writer did not attempt the locked database'
                time.sleep(.005)
        with ThreadPoolExecutor(max_workers=4) as pool:
            def get(url):
                start = time.monotonic()
                result = pool.submit(client.get, url).result(timeout=1)
                timings[url] = max(timings.get(url, 0), time.monotonic()-start)
                assert result.status_code == 200
                return result.json()
            try:
                data = get('/api/aircraft')
                assert data['status'] == 'ready' and len(data['items']) == 1
                assert aircraft.cache[0] > repo.clock()
                # Neither publishing the cache nor its readers waits for the worker to write.
                assert get('/api/aircraft') == data and len(calls) == 1
                assert entered.wait(1)
                assert writer_threads[0] != client.portal.call(get_ident)
                get('/api/health')
                get('/api/communications')
                client.portal.start_task_soon(asyncio.sleep, .02).result(timeout=1)
                # The completed cache and both API readers are usable while the writer is paused.
                release.set()
                wait_until(lambda: q.storage_error is not None)
                assert not q.writer_task.done()
                client.portal.call(q.start)
                assert not q.task.done()
                get('/api/health')
                get('/api/communications')  # This endpoint reads through the shared repo.lock.
                client.portal.start_task_soon(asyncio.sleep, .02).result(timeout=1)
                status = get('/api/position-quality')
                assert status['storage_error'] and status['pending_writes'] == 1
                assert status['source']['status'] == 'ready'
                # Upstream failures must publish their status immediately, even behind a stalled write.
                now[0] += timedelta(seconds=11)
                failed = get('/api/aircraft')
                assert failed['status'] == 'error' and failed['stale'] and len(failed['items']) == 1
                assert get('/api/position-quality')['source']['status'] == 'error'
                get('/api/aircraft')
                assert len(calls) == 2  # Source backoff is independent of write retries.
                now[0] += timedelta(seconds=60)
                assert get('/api/aircraft')['status'] == 'ready' and len(calls) == 3
                # A prolonged lock may discard older pending snapshots, never grow an unbounded queue.
                for _ in range(5):
                    now[0] += timedelta(seconds=11)
                    assert get('/api/aircraft')['status'] == 'ready'
                status = get('/api/position-quality')
                assert status['pending_writes'] <= 3 and status['dropped_snapshots'] > 0
                assert q.pending.qsize() <= 2 and not q.task.done()
                last_attempt = now[0].timestamp()
                calls_before_unlock = len(calls)
                locker.rollback()
                client.portal.start_task_soon(q.flush).result(timeout=4)
                status = get('/api/position-quality')
                assert not status['storage_error'] and status['pending_writes'] == 0
                assert status['source']['attempt'] == last_attempt
                persisted = repo.db.execute('SELECT attempt,status FROM position_quality_source').fetchone()
                assert persisted['attempt'] == last_attempt and persisted['status'] == 'ready'
                assert len(calls) == calls_before_unlock  # Recovery retries SQLite, not the aircraft API.
                assert repo.db.execute('SELECT count(*) FROM position_quality_samples WHERE aircraft=?',
                                       ('000001',)).fetchone()[0] >= 2
                first = repo.db.execute('SELECT observed,eligible FROM position_quality_samples WHERE aircraft=? '
                                        'ORDER BY observed LIMIT 1', ('000001',)).fetchone()
                assert first['observed'] == NOW.timestamp() and first['eligible'] == 1
                # Closing also stays bounded when the writer is waiting on another real lock.
                locker.execute('BEGIN IMMEDIATE')
                now[0] += timedelta(seconds=11)
                assert get('/api/aircraft')['status'] == 'ready'
                wait_until(lambda: q.storage_error is not None)
                start = time.monotonic()
                client.portal.start_task_soon(q.stop).result(timeout=2)
                timings['shutdown'] = time.monotonic()-start
                assert q.writer_task.done() and q.task.done() and aircraft.quality is None
                assert q.pending.qsize() == 0 and not q.active_write
                get('/api/health')
                get('/api/communications')
            finally:
                release.set()
                locker.rollback()
                locker.close()
                client.portal.call(q.stop)
                client.portal.call(network.aclose)
        print('BEGIN IMMEDIATE response times (seconds):', {k: round(v, 3) for k, v in timings.items()})


@pytest.mark.asyncio
async def test_retention_maintenance_during_retry_after_is_async_and_does_not_invent_attempts(tmp_path):
    def forbidden(request):
        raise AssertionError('Retry-After must prevent upstream requests')
    repo = Repository(tmp_path/'backoff.sqlite3', clock=lambda: NOW)
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        aircraft = AircraftService(client, repo.clock)
        q = PositionQuality(repo, aircraft, enabled=True)
        previous = (NOW-timedelta(hours=1)).timestamp()
        q.note_source('error', previous)
        aircraft.retry_at = NOW+timedelta(days=1)
        expired = NOW-timedelta(hours=73)
        with repo.db:
            repo.db.execute('INSERT INTO position_quality_samples VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (int(expired.timestamp()//60), '000001', expired.timestamp(),
                             '52.0,21', '14', 1, 0, 0, '{}', q.epoch))
        q.start()
        try:
            async def maintenance_started():
                while q.writer_task is None:
                    await asyncio.sleep(.005)
            await asyncio.wait_for(maintenance_started(), timeout=2)
            await asyncio.wait_for(q.flush(), timeout=2)
            assert repo.db.execute('SELECT count(*) FROM position_quality_samples').fetchone()[0] == 0
            assert q.source_state['attempt'] == previous
            assert repo.db.execute('SELECT attempt FROM position_quality_source').fetchone()[0] == previous
            assert not q.task.done()
        finally:
            await q.stop()
            repo.close()
