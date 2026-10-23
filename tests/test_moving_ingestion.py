"""Projection backpressure cannot block the shared transport collectors."""
import asyncio
import sqlite3
import threading
from datetime import UTC, datetime

import httpx
import pytest

from wici.aircraft import AircraftService
from wici.moving_ingestion import MovingIngestion
from wici.ships import ShipService


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
