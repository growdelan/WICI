"""Isolated browser fixture: real tracking API/SQLite, synthetic feeds, no network."""
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import httpx
import uvicorn

from wici.app import create_app
from wici.config import Config
from wici.tracking import TrackingService


def forbidden(request):
    raise AssertionError(f'External network forbidden: {request.url}')


class Feed:
    vessels: ClassVar = {
        '261000001': {'name': 'TEST STATEK', 'type_code': 70, 'offset': 0},
        '261000002': {'name': 'TEST WOJSKOWY', 'type_code': 35, 'offset': .25},
        '261000003': {'name': 'TEST NIEUSTALONY', 'type_code': None, 'offset': .5},
    }

    def __init__(self, kind, repo):
        self.kind, self.repo = kind, repo
        self.started = datetime.now(UTC)

    def item(self, at, step=0, object_id=None):
        common = {'position_at': at.isoformat(), 'latitude': 52.1+step*.001,
                  'longitude': 19.1+step*.002}
        if self.kind == 'aircraft':
            return {**common, 'hex': '48abcd', 'id': 'TEST LOT', 'registration': 'SP-TEST',
                    'altitude_m': 8200, 'speed_kmh': 700, 'track': 80, 'type_code': 'TEST',
                    'military': True}
        mmsi = object_id or '261000001'
        vessel = self.vessels[mmsi]
        direction = 50 if vessel['type_code'] is not None else None
        return {**common, 'latitude': 55.1+vessel['offset']+step*.0001,
                'longitude': 18.1+vessel['offset']+step*.0001,
                'mmsi': mmsi, 'name': vessel['name'], 'speed_knots': 12,
                'course': direction, 'heading': direction, 'type_code': vessel['type_code']}

    async def fetch(self):
        now = self.repo.clock()
        step = max(0, int((now-self.started).total_seconds()/10))
        items = ([self.item(now, step, mmsi) for mmsi in self.vessels] if self.kind == 'ship'
                 else [self.item(now, step)])
        return {'items': items, 'status': 'ready', 'stale': False,
                'message': 'Syntetyczny test historii', 'enabled': True, 'configured': True,
                'refresh_seconds': 10, 'fetched_at': now.isoformat()}


def serve(port):
    with tempfile.TemporaryDirectory(prefix='wici-tracking-browser-') as directory:
        client = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
        app = create_app(demo=True, root=Path(directory), config=Config(port=port), client=client)
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            async with original(application):
                repo = application.state.repo
                repo.clock = lambda: datetime.now(UTC)
                aircraft, ships = Feed('aircraft', repo), Feed('ship', repo)
                tracker = TrackingService(repo, aircraft, ships, interval_seconds=.25)
                application.state.aircraft = aircraft
                application.state.ships = ships
                application.state.tracking = tracker
                tracker.start()
                try:
                    yield
                finally:
                    await tracker.close()
                    await client.aclose()

        app.router.lifespan_context = lifespan

        @app.post('/_test/history/{track_id}')
        async def history(track_id: str):
            tracker, repo = app.state.tracking, app.state.repo
            track = tracker.detail(track_id)['track']
            feed = tracker.services[track['kind']]
            now = datetime.now(UTC)
            start = now-timedelta(hours=3)
            clock = repo.clock
            with repo.lock, repo.db:
                repo.db.execute('DELETE FROM object_track_points WHERE track_id=?', (track_id,))
                repo.db.execute('UPDATE object_tracks SET started_at=? WHERE id=?',
                                (start.isoformat(), track_id))
            try:
                for sample in range(1081):
                    minute = sample/6
                    if 70 < minute < 110:
                        continue
                    at = start+timedelta(seconds=sample*10)
                    repo.clock = lambda at=at: at
                    tracker.ingest(track['kind'], {'items': [feed.item(at, minute, track['object_id'])],
                                                   'status': 'ready', 'stale': False})
            finally:
                repo.clock = clock
            return tracker.detail(track_id)

        uvicorn.run(app, host='127.0.0.1', port=port, log_level='error')


if __name__ == '__main__':
    serve(int(sys.argv[1]))
