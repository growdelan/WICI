"""Non-blocking, bounded projection of shared transport snapshots into Analysis.

This is a latest-state projection, not the observation recorder. Coalescing pending
snapshots keeps at most one per source; TrackingService still owns durable tracks.
"""
import asyncio
import copy
import logging
import sqlite3
from collections import deque

LOG = logging.getLogger(__name__)


class MovingIngestion:
    def __init__(self, moving):
        self.moving = moving
        self.pending = {}
        self.wake = asyncio.Event()
        self.idle = asyncio.Event()
        self.idle.set()
        self.worker = None
        self.accepting = True
        self.errors = {}
        self.writing = False
        self.coalesced = 0
        # Keep every raw observation before the latest-state catalogue projection.
        # The queue is bounded independently and its overload remains explicit.
        self.observations = deque()
        self.observation_errors = {}
        self.observation_overflow = 0
        self.observation_gap_after = set()

    def enqueue(self, kind, snapshot):
        if not self.accepting or kind not in ('aircraft', 'ship'):
            return False
        if kind in self.pending:
            self.coalesced += 1
        if getattr(self.moving, 'repo', None) is not None:
            if len(self.observations) < 128:
                self.observations.append((kind, copy.deepcopy(snapshot)))
            else:
                self.observation_overflow += 1
                self.observation_gap_after.add(kind)
                self.observation_errors[kind] = 'Przepełnienie kolejki obserwacji; ciągłość monitorowania niepotwierdzona.'
        self.pending[kind] = copy.deepcopy(snapshot)
        self.idle.clear()
        self.wake.set()
        if self.worker is None:
            self.worker = asyncio.create_task(self._run(), name='wici-moving-projection')
        return True

    def status(self):
        return {'pending': len(self.pending) + int(self.writing),
                'errors': dict(self.errors), 'coalesced_snapshots': self.coalesced,
                'monitor_pending': len(self.observations), 'monitor_errors': dict(self.observation_errors),
                'monitor_overflow': self.observation_overflow}

    def _observe(self, kind, snapshot):
        from wici.workspace_monitor import append_observation, moving_observations
        repo = self.moving.repo
        with repo.lock:
            timeout = int(repo.db.execute('PRAGMA busy_timeout').fetchone()[0])
            try:
                repo.db.execute('PRAGMA busy_timeout=0')
                repo.db.execute('BEGIN IMMEDIATE')
                if kind in self.observation_errors:
                    from wici.workspace_repository import iso
                    now = iso(repo.clock())
                    append_observation(repo, 'gap', '*', 'aircraft' if kind == 'aircraft' else 'ships',
                                       now, ['projection_gap', now], {'reason': self.observation_errors[kind]}, False)
                moving_observations(repo, kind, snapshot)
                repo.db.commit()
            except Exception:
                repo.db.rollback()
                raise
            finally:
                repo.db.execute(f'PRAGMA busy_timeout={timeout}')

    def _overflow_gap(self, kind):
        from wici.workspace_monitor import append_observation
        from wici.workspace_repository import iso
        repo = self.moving.repo
        with repo.lock, repo.db:
            now = iso(repo.clock())
            append_observation(repo, 'gap', '*', 'aircraft' if kind == 'aircraft' else 'ships', now,
                               ['overflow', now, self.observation_overflow],
                               {'reason': 'Przepełnienie kolejki obserwacji transportu.'}, False)

    async def flush(self, timeout=None):
        try:
            async with asyncio.timeout(timeout):
                await self.idle.wait()
            return True
        except TimeoutError:
            return False

    def _write(self, kind, snapshot):
        repo = getattr(self.moving, 'repo', None)
        if repo is None:
            return self.moving.ingest(kind, snapshot)
        # An external SQLite writer must not hold up the shared repository's
        # readers while the connection waits its usual five-second busy timeout.
        # Acquire the transaction immediately or report the failed projection.
        with repo.lock:
            timeout = int(repo.db.execute('PRAGMA busy_timeout').fetchone()[0])
            try:
                repo.db.execute('PRAGMA busy_timeout=0')
                repo.db.execute('BEGIN IMMEDIATE')
                self.moving.ingest(kind, snapshot)
            except Exception:
                repo.db.rollback()
                raise
            finally:
                repo.db.execute(f'PRAGMA busy_timeout={timeout}')

    async def close(self):
        self.accepting = False
        self.wake.set()
        if self.worker is not None:
            await self.worker
            self.worker = None

    async def _run(self):
        while self.accepting or self.pending or self.observations:
            if self.observations:
                kind, snapshot = self.observations.popleft()
                self.writing = True
                try:
                    await asyncio.to_thread(self._observe, kind, snapshot)
                    self.observation_errors.pop(kind, None)
                except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RuntimeError):
                    self.observation_errors[kind] = 'Nie zapisano obserwacji; ciągłość monitorowania niepotwierdzona.'
                    LOG.error('Moving monitoring observation write failed for %s', kind)
                finally:
                    self.writing = False
                if not self.observations:
                    for gap_kind in tuple(self.observation_gap_after):
                        try:
                            await asyncio.to_thread(self._overflow_gap, gap_kind)
                            self.observation_gap_after.discard(gap_kind)
                        except (sqlite3.Error, OSError, RuntimeError):
                            self.observation_errors[gap_kind] = 'Nie zapisano luki przeciążenia; ciągłość niepotwierdzona.'
                continue
            if not self.pending:
                self.idle.set()
                self.wake.clear()
                await self.wake.wait()
                continue
            kind = next(iter(self.pending))
            snapshot = self.pending.pop(kind)
            self.writing = True
            try:
                await asyncio.to_thread(self._write, kind, snapshot)
                self.errors.pop(kind, None)
            except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, RuntimeError):
                self.errors[kind] = 'Nie udało się zapisać odczytu transportu w katalogu Analizy.'
                LOG.error('Moving object projection failed for %s', kind)
            finally:
                self.writing = False
                if not self.pending:
                    self.idle.set()
        self.idle.set()
