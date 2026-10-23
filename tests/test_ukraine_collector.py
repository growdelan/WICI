"""Shared transport and recorder lifecycle without live network or user databases."""
import asyncio
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wici.repository import Repository
from wici.ukraine import ALERTS_URL, OBLASTS_URL, RAIONS_URL, THREATS_URL, UkraineService
from wici.ukraine_collector import UkraineCollector
from wici.ukraine_history import UkraineHistory

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def alert_payload(now, *, active=True):
    return {'version': 1, 'updatedAt': NOW.isoformat(), 'raions': [], 'oblasts': [
        {'key': 'test', 'name': 'Obwód testowy', 'level': 'red', 'since': NOW.isoformat(),
         'reasons': []}] if active else []}


@pytest.mark.asyncio
async def test_alarm_only_transport_shares_cache_and_hooks_only_actual_fetches():
    now, calls, observed = [NOW], [], []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=alert_payload(now[0]) if str(request.url) == ALERTS_URL else {
            'epoch': 'test', 'seq': 1, 'serverTime': now[0].isoformat(), 'threats': []})

    async def capture(component):
        observed.append(component)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        service.on_alerts = capture
        await asyncio.gather(service.fetch_alerts(), service.fetch(), service.fetch_alerts())
        assert calls.count(ALERTS_URL) == calls.count(THREATS_URL) == 1
        assert len(observed) == 1 and observed[0]['source_version'] == 1
        now[0] += timedelta(seconds=15)
        await service.fetch_alerts()
        assert len(observed) == 2 and calls.count(THREATS_URL) == 1
        assert observed[0]['updated_at'] == observed[1]['updated_at']
        assert observed[0]['fetched_at'] != observed[1]['fetched_at']


@pytest.mark.asyncio
async def test_recorder_preserves_transitions_off_state_and_failed_fetch_gap(tmp_path):
    now, fail, active = [NOW], [False], [True]

    def handler(request):
        if fail[0]:
            raise httpx.ReadTimeout('offline')
        return httpx.Response(200, json=alert_payload(now[0], active=active[0]))

    repo = Repository(tmp_path/'alarms.sqlite3', clock=lambda: now[0])
    history = UkraineHistory(repo)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        collector = UkraineCollector(service, history)
        assert not collector.status()['enabled']
        await service.fetch_alerts()
        assert repo.db.execute('SELECT count(*) FROM workspace_ukraine_runs').fetchone()[0] == 0
        assert history.status()['regions'] == 1
        # Exercise the same persisted setting without starting a timer in this
        # deterministic transport test.
        history.set_recording(True)
        now[0] += timedelta(seconds=15)
        await service.fetch_alerts()
        now[0] += timedelta(seconds=15)
        active[0] = False
        await service.fetch_alerts()
        now[0] += timedelta(seconds=15)
        active[0] = True
        await service.fetch_alerts()
        episodes = list(repo.db.execute('SELECT active FROM workspace_ukraine_episodes'))
        assert sorted(row[0] for row in episodes) == [0, 1]
        fail[0] = True
        now[0] += timedelta(seconds=15)
        await service.fetch_alerts()
        runs = list(repo.db.execute('SELECT status FROM workspace_ukraine_runs ORDER BY id'))
        assert [row[0] for row in runs] == ['ready', 'ready', 'ready', 'unknown']
        assert collector.status()['last_error']
        # A retry-cache hit creates no additional coverage or gap row.
        await service.fetch_alerts()
        assert len(list(repo.db.execute('SELECT id FROM workspace_ukraine_runs'))) == len(runs)
        await collector.close()
        assert history.status()['enabled']  # preserved across app restarts
    repo.close()


@pytest.mark.asyncio
async def test_sqlite_contention_is_reported_and_recovery_keeps_a_gap(tmp_path):
    now = [NOW]
    path = tmp_path/'alarms.sqlite3'
    repo = Repository(path, clock=lambda: now[0])
    history = UkraineHistory(repo)
    history.set_recording(True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=alert_payload(now[0])))) as client:
        service = UkraineService(client, lambda: now[0])
        collector = UkraineCollector(service, history)
        await service.fetch_alerts()
        other = sqlite3.connect(path)
        other.execute('BEGIN IMMEDIATE')
        now[0] += timedelta(seconds=15)
        await asyncio.wait_for(service.fetch_alerts(), timeout=1)
        assert collector.status()['error'] and collector.failed_at == now[0]
        other.rollback()
        other.close()
        now[0] += timedelta(seconds=15)
        await service.fetch_alerts()
        assert collector.status()['error'] is None
        runs = list(repo.db.execute('SELECT status,reason FROM workspace_ukraine_runs ORDER BY id'))
        assert [(r[0], r[1]) for r in runs] == [('ready', None), ('unknown', 'storage_error'), ('ready', None)]
        assert repo.db.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
        await collector.close()
    repo.close()


@pytest.mark.asyncio
async def test_enabled_recorder_restarts_and_shutdown_waits_for_pending_writes(tmp_path):
    repo = Repository(tmp_path/'alarms.sqlite3', clock=lambda: NOW)
    history = UkraineHistory(repo)
    seen = asyncio.Event()

    async def handler(request):
        if str(request.url) == ALERTS_URL:
            seen.set()
            return httpx.Response(200, json=alert_payload(NOW))
        return httpx.Response(200, json={'type': 'FeatureCollection', 'features': []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: NOW)
        collector = UkraineCollector(service, history)
        collector.start()
        assert collector.worker is None
        await collector.set_enabled(True)
        await asyncio.wait_for(seen.wait(), 2)
        await collector.close()
        assert collector.worker is None and history.status()['enabled']
        assert repo.db.execute('SELECT count(*) FROM workspace_ukraine_runs').fetchone()[0] >= 1
        restarted = UkraineCollector(UkraineService(client, lambda: NOW), UkraineHistory(repo))
        restarted.start()
        assert restarted.status()['running']
        await restarted.set_enabled(False)
        assert not restarted.status()['enabled'] and not restarted.status()['running']
        await restarted.close()
    repo.close()


@pytest.mark.asyncio
async def test_retention_runs_with_recording_disabled_without_provider_requests(tmp_path, monkeypatch):
    repo = Repository(tmp_path/'alarms.sqlite3', clock=lambda: NOW)
    history = UkraineHistory(repo)
    maintained = asyncio.Event()
    loop = asyncio.get_running_loop()
    original = history.prune

    def prune():
        result = original()
        loop.call_soon_threadsafe(maintained.set)
        return result

    monkeypatch.setattr(history, 'prune', prune)
    monkeypatch.setattr('wici.ukraine_collector.MAINTENANCE_SECONDS', 0.01)

    def forbidden(request):
        raise AssertionError('Disabled recording must not fetch any provider')

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        collector = UkraineCollector(UkraineService(client, lambda: NOW), history)
        collector.start()
        await asyncio.wait_for(maintained.wait(), 2)
        assert collector.worker is None and not collector.status()['enabled']
        await collector.close()
        assert collector.maintenance is None
    repo.close()


@pytest.mark.asyncio
async def test_queued_capture_observes_recording_disabled_before_its_write(tmp_path):
    repo = Repository(tmp_path/'recording-race.sqlite3', clock=lambda: NOW)
    history = UkraineHistory(repo)
    history.set_recording(True)
    async with httpx.AsyncClient() as client:
        collector = UkraineCollector(UkraineService(client, lambda: NOW), history)
        # A stop operation owns the writer slot before the source callback arrives.
        # It changes the persisted setting before the queued capture may proceed.
        await collector.write_lock.acquire()
        capture = asyncio.create_task(collector.capture({'status': 'ready', 'items': [],
            'fetched_at': NOW.isoformat(), 'updated_at': NOW.isoformat()}))
        await asyncio.sleep(0)
        assert not capture.done()
        history.set_recording(False)
        collector.write_lock.release()
        await capture
        assert history.status()['fetched_at'] == NOW.isoformat()
        assert not history.status()['recording']
        assert repo.db.execute('SELECT count(*) FROM workspace_ukraine_runs').fetchone()[0] == 0
        await collector.close()
    repo.close()


def geometry_payload(at=NOW, label='Obwód testowy'):
    return {'status': 'ready', 'fetched_at': at.isoformat(), 'oblasts': {
        'type': 'FeatureCollection', 'features': [{'type': 'Feature',
            'properties': {'key': 'test', 'region': label, 'rayon': 'Rejon testowy'},
            'geometry': {'type': 'Polygon', 'coordinates': [
                [[30, 50], [31, 50], [31, 51], [30, 50]]]}}]}}


@pytest.mark.asyncio
async def test_geometry_write_retries_with_recording_off_after_successful_alert_read(tmp_path, monkeypatch):
    path = tmp_path/'geometry.sqlite3'
    repo = Repository(path, clock=lambda: NOW)
    history = UkraineHistory(repo)
    calls = []
    monkeypatch.setattr('wici.ukraine_collector.GEOMETRY_RETRY_SECONDS', 0.01)

    def handler(request):
        calls.append(str(request.url))
        payload = alert_payload(NOW) if str(request.url) == ALERTS_URL else geometry_payload()['oblasts']
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: NOW)
        collector = UkraineCollector(service, history)
        collector.start()
        other = sqlite3.connect(path)
        other.execute('BEGIN IMMEDIATE')
        try:
            result = await asyncio.wait_for(service.geometry(), timeout=1)
            assert result['status'] == 'ready'
            assert not history.regions()
            error = collector.status()['geometry_error']
            assert error and collector.status()['last_error'] == error
            retry = collector.geometry_retry
            assert retry is not None
            # Delay only the local retry while the next alert snapshot succeeds.
            # Its success must not hide the independent geometry write failure.
            async with collector.geometry_lock:
                other.rollback()
                await service.fetch_alerts()
                assert collector.status()['last_error'] == error
                assert history.regions()[0]['geometry'] is None
            await asyncio.wait_for(asyncio.shield(retry), timeout=2)
            assert collector.status()['geometry_error'] is None
            assert collector.status()['last_error'] is None
            assert all(region['geometry'] for region in history.regions())
            assert calls.count(OBLASTS_URL) == calls.count(RAIONS_URL) == calls.count(ALERTS_URL) == 1
            assert len(calls) == 3
            assert not collector.status()['enabled'] and collector.worker is None
            assert repo.db.execute('SELECT count(*) FROM workspace_ukraine_runs').fetchone()[0] == 0
        finally:
            other.rollback()
            other.close()
            await collector.close()
    repo.close()


@pytest.mark.asyncio
async def test_geometry_retry_keeps_only_latest_snapshot_and_close_cancels_it(tmp_path, monkeypatch):
    path = tmp_path/'geometry-latest.sqlite3'
    repo = Repository(path, clock=lambda: NOW)
    history = UkraineHistory(repo)
    monkeypatch.setattr('wici.ukraine_collector.GEOMETRY_RETRY_SECONDS', 0.01)
    async with httpx.AsyncClient() as client:
        collector = UkraineCollector(UkraineService(client, lambda: NOW), history)
        other = sqlite3.connect(path)
        other.execute('BEGIN IMMEDIATE')
        try:
            await collector.geometry(geometry_payload())
            retry = collector.geometry_retry
            latest = geometry_payload(NOW+timedelta(seconds=1), 'Nowsza nazwa')
            await collector.geometry(latest)
            assert collector.geometry_retry is retry
            assert collector.geometry_pending[1] == latest
            other.rollback()
            await asyncio.wait_for(asyncio.shield(retry), timeout=2)
            assert history.regions()[0]['label'] == 'Nowsza nazwa'
            assert collector.geometry_pending is None

            # A pending write must not outlive the collector or use a closed DB.
            other.execute('BEGIN IMMEDIATE')
            await collector.geometry(geometry_payload(NOW+timedelta(seconds=2)))
            retry = collector.geometry_retry
            await collector.close()
            assert retry.done() and collector.geometry_retry is None
            assert collector.geometry_pending is None
            assert collector.service.on_geometry is None
        finally:
            other.rollback()
            other.close()
            await collector.close()
    repo.close()


@pytest.mark.asyncio
async def test_geometry_retry_shutdown_waits_for_inflight_sqlite_write(tmp_path, monkeypatch):
    repo = Repository(tmp_path/'geometry-shutdown.sqlite3', clock=lambda: NOW)
    history = UkraineHistory(repo)
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    register = history.register_geometry
    attempts = 0

    def delayed_register(payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError('database is locked')
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=3):
            raise AssertionError('Test did not release the in-flight geometry write')
        return register(payload)

    monkeypatch.setattr(history, 'register_geometry', delayed_register)
    monkeypatch.setattr('wici.ukraine_collector.GEOMETRY_RETRY_SECONDS', 0.01)
    async with httpx.AsyncClient() as client:
        collector = UkraineCollector(UkraineService(client, lambda: NOW), history)
        try:
            await collector.geometry(geometry_payload())
            retry = collector.geometry_retry
            await asyncio.wait_for(entered.wait(), timeout=2)
            closing = asyncio.create_task(collector.close())
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            await asyncio.wait_for(closing, timeout=2)
            assert retry.done() and collector.geometry_retry is None
            assert collector.geometry_pending is None
            assert history.regions()[0]['geometry']
        finally:
            release.set()
            await collector.close()
    repo.close()
