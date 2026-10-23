"""Opt-in local alarm recorder, sharing the on-demand NEPTUN transport.

Every actual fetch is awaited and persisted in order. Cached reads never create
observations, and no pending alarm transition is coalesced away.
"""
import asyncio
import logging
import sqlite3

from wici.ukraine import REFRESH_SECONDS

LOG = logging.getLogger(__name__)
STORAGE_ERRORS = (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RuntimeError)
MAINTENANCE_SECONDS = 3600
GEOMETRY_RETRY_SECONDS = 1
GEOMETRY_RETRY_MAX_SECONDS = 60


class UkraineCollector:
    def __init__(self, service, history):
        self.service, self.history = service, history
        self.available = service.enabled and not service.demo
        self.worker = None
        self.maintenance = None
        self.maintenance_error = None
        self.write_lock = asyncio.Lock()
        self.error = None
        self.failed_at = None
        self.geometry_revision = None
        self.geometry_error = None
        self.geometry_pending = None
        self.geometry_retry = None
        self.geometry_lock = asyncio.Lock()
        self.closed = False
        service.on_alerts = self.capture
        service.on_geometry = self.geometry

    def status(self):
        status = self.history.status()
        source_error = self.service.states['alerts']['error']
        if status['status'] == 'partial' and not source_error:
            source_error = 'Odczyt alarmów jest częściowy; ten okres nie potwierdza ciągłości historii.'
        error = self.error or self.geometry_error or self.maintenance_error or source_error
        return {**status, 'last_success_at': status.get('last_successful_at'),
                'last_error': error, 'available': self.available,
                'running': bool(self.worker and not self.worker.done()),
                'error': error, 'geometry_error': self.geometry_error,
                'refresh_seconds': REFRESH_SECONDS}

    def start(self):
        if not self.closed and (self.maintenance is None or self.maintenance.done()):
            self.maintenance = asyncio.create_task(self._maintain(), name='wici-ukraine-retention')
        if (not self.closed and self.available and self.history.status()['enabled']
                and (self.worker is None or self.worker.done())):
            self.worker = asyncio.create_task(self._run(), name='wici-ukraine-recorder')

    def _write_sync(self, method, *args, **kwargs):
        repo = self.history.repo
        with repo.lock:
            timeout = int(repo.db.execute('PRAGMA busy_timeout').fetchone()[0])
            try:
                # Do not keep the shared repository locked while an external
                # writer holds SQLite: report an explicit collection gap instead.
                repo.db.execute('PRAGMA busy_timeout=0')
                return method(*args, **kwargs)
            except Exception:
                repo.db.rollback()
                raise
            finally:
                repo.db.execute(f'PRAGMA busy_timeout={timeout}')

    async def _write(self, method, *args, **kwargs):
        async with self.write_lock:
            task = asyncio.create_task(asyncio.to_thread(self._write_sync, method, *args, **kwargs))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # SQLite work cannot be cancelled. Finish it before shutdown
                # releases the connection, or before another snapshot is written.
                await task
                raise

    async def capture(self, component):
        if self.closed:
            return
        try:
            if self.failed_at is not None:
                await self._write(self.history.mark_gap, 'storage_error', at=self.failed_at)
            await self._write(self.history.ingest, component,
                              record=None if self.available else False)
            self.error = None
            self.failed_at = None
        except STORAGE_ERRORS:
            self.failed_at = self.failed_at or self.history.repo.clock()
            self.error = 'Nie udało się zapisać odczytu alarmów. Ten okres będzie oznaczony jako luka.'
            LOG.error('Ukraine alarm history write failed')

    async def geometry(self, payload):
        if self.closed:
            return
        revision = (payload.get('fetched_at'), tuple(
            (payload.get('sources', {}).get(key) or {}).get('fetched_at')
            for key in ('oblasts', 'raions')))
        if revision == self.geometry_revision:
            return
        # Keep just the latest source snapshot. Retrying its local projection must
        # not depend on another HTTP request or on enabling alarm recording.
        self.geometry_pending = (revision, payload)
        try:
            await self._store_geometry()
        finally:
            if (not self.closed and self.geometry_pending is not None
                    and (self.geometry_retry is None or self.geometry_retry.done())):
                self.geometry_retry = asyncio.create_task(
                    self._retry_geometry(), name='wici-ukraine-geometry-retry')

    async def _store_geometry(self):
        async with self.geometry_lock:
            pending = self.geometry_pending
            if self.closed or pending is None:
                return
            revision, payload = pending
            try:
                await self._write(self.history.register_geometry, payload)
                self.geometry_revision = revision
                if self.geometry_pending is pending:
                    self.geometry_pending = None
                self.geometry_error = None
            except STORAGE_ERRORS:
                self.geometry_error = 'Nie udało się zapisać granic regionów Ukrainy. Zapis zostanie ponowiony.'
                LOG.error('Ukraine region cache write failed')

    async def _retry_geometry(self):
        delay = GEOMETRY_RETRY_SECONDS
        try:
            while not self.closed and self.geometry_pending is not None:
                await asyncio.sleep(delay)
                await self._store_geometry()
                delay = min(delay * 2, GEOMETRY_RETRY_MAX_SECONDS)
        finally:
            self.geometry_retry = None

    async def set_enabled(self, enabled):
        if enabled and not self.available:
            raise ValueError('Rejestracja alarmów wymaga trybu LIVE i włączonego źródła Ukrainy.')
        await self._write(self.history.set_recording, enabled)
        if enabled:
            self.start()
        else:
            await self._stop_worker()
        return self.status()

    async def _run(self):
        while not self.closed:
            # Geometry refresh uses the same 24-hour cache as Situation. Source
            # failures have their own backoff and never block fetching alarms.
            await self.service.geometry()
            snapshot = await self.service.fetch_alerts()
            delay = max(REFRESH_SECONDS, snapshot.get('retry_after_seconds', REFRESH_SECONDS))
            await asyncio.sleep(delay)

    async def _maintain(self):
        while not self.closed:
            await asyncio.sleep(MAINTENANCE_SECONDS)
            try:
                await self._write(self.history.prune)
                self.maintenance_error = None
            except STORAGE_ERRORS:
                self.maintenance_error = 'Nie udało się usunąć przeterminowanej historii alarmów.'
                LOG.error('Ukraine alarm retention failed')

    async def _stop_worker(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    async def close(self):
        self.closed = True
        await self._stop_worker()
        if self.geometry_retry is not None:
            retry = self.geometry_retry
            retry.cancel()
            try:
                await retry
            except asyncio.CancelledError:
                pass
            self.geometry_retry = None
        self.geometry_pending = None
        if self.maintenance is not None:
            self.maintenance.cancel()
            try:
                await self.maintenance
            except asyncio.CancelledError:
                pass
            self.maintenance = None
        if self.available and self.history.status()['enabled']:
            try:
                await self._write(self.history.mark_gap, 'shutdown')
            except STORAGE_ERRORS:
                LOG.error('Ukraine recorder shutdown gap write failed')
        self.service.on_alerts = self.service.on_geometry = None
