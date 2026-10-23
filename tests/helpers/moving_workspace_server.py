"""Isolated Analysis browser fixture: real APIs/SQLite and synthetic transport feeds."""
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

from wici.app import create_app
from wici.config import Config
from wici.tracking import TrackingService


def forbidden(request):
    raise AssertionError(f'External network forbidden: {request.url}')


class Feed:
    """Reports use current timestamps while archived tracks have a fixed time range."""

    def __init__(self, kind, repo):
        self.kind, self.repo = kind, repo
        self.mode = 'fresh'
        self.revision = 0

    def item(self, at, index=0, step=0):
        common = {'position_at': at.isoformat(), 'latitude': 52.1 + index * .15 + step * .0002,
                  'longitude': 19.1 + index * .15 + step * .0003}
        if self.kind == 'aircraft':
            return {**common, 'hex': f'48abc{index}', 'id': f'ANALIZA LOT {index + 1}',
                    'registration': f'SP-TST{index}', 'altitude_m': 8000 + step * 2,
                    'speed_kmh': 600 + self.revision * 10 + index, 'track': 80,
                    'type_code': 'TEST', 'military': False}
        return {**common, 'latitude': 55.1 + index * .15 + step * .0001,
                'longitude': 18.1 + index * .15 + step * .0001,
                'mmsi': str(261000001 + index), 'imo': str(9000001 + index),
                'name': f'ANALIZA STATEK {index + 1}', 'speed_knots': 12 + self.revision,
                'course': 50, 'heading': 50, 'type_code': 70}

    async def fetch(self):
        now = self.repo.clock()
        at = now - timedelta(hours=1) if self.mode == 'stale' else now
        return {'items': [] if self.mode == 'empty' else [self.item(at, index) for index in range(3)],
                'status': 'error' if self.mode == 'stale' else 'ready',
                'stale': self.mode == 'stale', 'message': 'Syntetyczne dane testu Analizy',
                'enabled': True, 'configured': True, 'refresh_seconds': 10,
                'fetched_at': at.isoformat()}


def seed_history(repo, tracker, track_id, feed, index, start):
    """Use actual tracker ingestion, with a deliberate aircraft observation gap."""
    clock = repo.clock
    with repo.lock, repo.db:
        repo.db.execute('DELETE FROM object_track_points WHERE track_id=?', (track_id,))
        repo.db.execute('UPDATE object_tracks SET started_at=? WHERE id=?',
                        (start.isoformat(), track_id))
    try:
        for sample in range(121):
            if feed.kind == 'aircraft' and 40 < sample < 80:
                continue
            at = start + timedelta(seconds=sample * 30)
            repo.clock = lambda at=at: at
            tracker.ingest(feed.kind, {'items': [feed.item(at, index, sample)],
                                      'status': 'ready', 'stale': False})
    finally:
        repo.clock = clock


def serve(port):
    with tempfile.TemporaryDirectory(prefix='wici-moving-workspace-browser-') as directory:
        client = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
        app = create_app(demo=True, root=Path(directory), config=Config(port=port), client=client)
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            async with original(application):
                repo = application.state.repo
                repo.clock = lambda: datetime.now(UTC)
                # Keep the existing station-control regression independent of DEMO_NOW.
                observed = (repo.clock() - timedelta(hours=1)).isoformat()
                application.state.station_history.write('hydro:stations', {
                    'status': 'ready', 'fetched_at': observed, 'synthetic': True,
                    'source_url': 'https://example.invalid/test/hydro',
                    'items': [{'id': 'demo-wisla', 'name': 'DEMO: wodowskaz Wisła',
                               'latitude': 52.23, 'longitude': 21.03, 'river': 'Wisła',
                               'province': 'mazowieckie', 'synthetic': True,
                               'measurements': {'water_level': {'value': 274, 'unit': 'cm',
                                                                'observed_at': observed}}}],
                })
                aircraft, ships = Feed('aircraft', repo), Feed('ship', repo)
                tracker = TrackingService(repo, aircraft, ships)
                application.state.aircraft = aircraft
                application.state.ships = ships
                application.state.tracking = tracker
                application.state.workspace.source_enabled.update(aircraft=True, ships=True)
                start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=65)
                application.state.test_range = {'from': start.isoformat(),
                                                'to': (start + timedelta(hours=1)).isoformat()}
                application.state.test_tracks = []
                for kind, feed in [('aircraft', aircraft), ('ship', ships)]:
                    for index in range(3):
                        object_id = f'48abc{index}' if kind == 'aircraft' else str(261000001 + index)
                        detail = await tracker.begin(kind, object_id)
                        track_id = detail['track']['id']
                        seed_history(repo, tracker, track_id, feed, index, start)
                        await tracker.stop(track_id)
                        application.state.test_tracks.append(tracker.detail(track_id))
                application.state.workspace.moving.backfill_tracks()
                for kind, feed in [('aircraft', aircraft), ('ship', ships)]:
                    application.state.workspace.moving.ingest(kind, await feed.fetch())
                try:
                    yield
                finally:
                    await tracker.close()
                    await client.aclose()

        app.router.lifespan_context = lifespan

        @app.get('/_test/history')
        def history():
            return {'range': app.state.test_range, 'tracks': app.state.test_tracks}

        @app.post('/_test/feed/{mode}')
        def mode(mode: str):
            if mode not in {'fresh', 'stale', 'empty'}:
                raise ValueError(mode)
            for feed in (app.state.aircraft, app.state.ships):
                feed.mode = mode
                feed.revision += 1
            return {'mode': mode}

        uvicorn.run(app, host='127.0.0.1', port=port, log_level='error')


if __name__ == '__main__':
    serve(int(sys.argv[1]))
