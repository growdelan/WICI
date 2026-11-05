"""Projection backpressure cannot block the shared transport collectors."""
import asyncio
import sqlite3
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from wici.aircraft import AircraftService
from wici.moving_ingestion import MovingIngestion
from wici.ships import ShipService


@pytest.mark.asyncio
async def test_raw_observations_and_latest_projection_share_owned_data_without_losing_receipts():
    observed, projected = [], []
    repo = SimpleNamespace()

    class Reader(MovingIngestion):
        def _observe(self, kind, snapshot):
            observed.append((kind, snapshot))

        def _write(self, kind, snapshot):
            projected.append((kind, snapshot))

    writer = Reader(SimpleNamespace(repo=repo))
    first = {'status': 'ready', 'items': [{'hex': '48abcd', 'metadata': {'label': 'original'}}]}
    second = {'status': 'ready', 'items': [{'hex': '48abcd', 'metadata': {'label': 'new'}}]}
    try:
        writer.enqueue('aircraft', first)
        raw_first = writer.observations[0][1]
        latest_first = writer.pending['aircraft']
        assert raw_first is not latest_first
        assert raw_first['items'] is latest_first['items']
        assert '_monitor_receipt' not in latest_first
        first['items'][0]['metadata']['label'] = 'caller mutation'
        # The same source data received on each side of an epoch boundary must
        # still be retained separately; copying less must never deduplicate it.
        repo._monitor_receipt_state['generation'] += 1
        writer.enqueue('aircraft', second)
        second['items'].clear()
        assert writer.status()['monitor_pending'] == 2
        assert writer.status()['coalesced_snapshots'] == 1
        await asyncio.wait_for(writer.flush(), 3)
        assert [snapshot['items'][0]['metadata']['label'] for _, snapshot in observed] == ['original', 'new']
        assert observed[0][1]['_monitor_receipt'][1] == 0
        assert observed[1][1]['_monitor_receipt'][1] == 1
        assert len(projected) == 1 and projected[0][1]['items'][0]['metadata']['label'] == 'new'
        assert '_monitor_receipt' not in projected[0][1]
        assert writer.status()['monitor_overflow'] == 0
    finally:
        await writer.close()


@pytest.mark.asyncio
async def test_coalesces_latest_snapshot_without_blocking_and_drains_on_close():
    entered, release = threading.Event(), threading.Event()
    written = []

    class SlowProjection:
        def ingest(self, kind, snapshot):
            if not written:
                entered.set()
                assert release.wait(5)
            written.append((kind, snapshot['value']))

    writer = MovingIngestion(SlowProjection())
    try:
        writer.enqueue('aircraft', {'value': 0})
        assert await asyncio.to_thread(entered.wait, 3)
        # Runs while SQLite worker is blocked; the producer stays bounded.
        snapshot = {'value': 1}
        writer.enqueue('ship', snapshot)
        snapshot['value'] = 999
        for i in range(1, 100):
            writer.enqueue('aircraft', {'value': i})
        assert writer.status()['pending'] == 3  # Two queued, one being written.
        assert writer.status()['coalesced_snapshots'] == 98
        closing = asyncio.create_task(writer.close())
        await asyncio.sleep(0)
        assert not closing.done()
        assert writer.enqueue('ship', {'value': 2}) is False
        release.set()
        await asyncio.wait_for(closing, 3)
        assert written == [('aircraft', 0), ('ship', 1), ('aircraft', 99)]
        assert writer.status()['pending'] == 0
    finally:
        release.set()
        await writer.close()


@pytest.mark.asyncio
async def test_storage_failure_is_visible_and_next_snapshot_recovers():
    class FailingProjection:
        def ingest(self, kind, snapshot):
            if snapshot['fail']:
                raise sqlite3.OperationalError('private database details')

    writer = MovingIngestion(FailingProjection())
    try:
        writer.enqueue('ship', {'fail': True})
        await asyncio.wait_for(writer.flush(), 3)
        assert 'ship' in writer.status()['errors']
        assert 'private' not in str(writer.status())
        writer.enqueue('ship', {'fail': False})
        await asyncio.wait_for(writer.flush(), 3)
        assert writer.status()['errors'] == {}
    finally:
        await writer.close()


@pytest.mark.asyncio
async def test_snapshot_hooks_share_existing_cache_and_never_open_demo_sources():
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    calls, received = [], []

    def response(request):
        calls.append(request)
        return httpx.Response(200, json={'now': now.timestamp() * 1000, 'ac': []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        aircraft = AircraftService(client, lambda: now)
        aircraft.on_snapshot = lambda kind, snapshot: received.append((kind, snapshot))
        await aircraft.fetch()
        await aircraft.fetch()
        assert len(calls) == 1
        assert len(received) == 2
        aircraft.enabled = False
        assert (await aircraft.fetch())['status'] == 'disabled'
        assert received[-1][1]['status'] == 'disabled'
        ship = ShipService(lambda: now, demo=True)
        ship.on_snapshot = aircraft.on_snapshot
        await ship.fetch()
        assert received[-1][0] == 'ship'
        assert received[-1][1]['demo'] is True
        assert ship.task is None
