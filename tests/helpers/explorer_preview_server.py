"""Offline Explorer visual fixture: temporary SQLite and invented Odra measurements.

Run: .venv/bin/python tests/helpers/explorer_preview_server.py PORT
This never changes the production demo or reads real provider data. Geographic
locations provide a recognizable context; every label and payload marks the
measurements as synthetic. The HTTP client rejects all upstream requests.
"""
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn

from wici.app import create_app
from wici.config import Config

NOW = datetime(2026, 11, 5, 8, 50, tzinfo=UTC)
LAST_SAMPLE = NOW - timedelta(minutes=10)
SELECTED_REF = 'hydro_station:imgw:explorer-trestno'
STATIONS = [
    ('trestno', 'Wrocław — Trestno', 51.0712, 17.1028, 412, 400, 450),
    ('olawa', 'Oława', 50.9475, 17.2957, 338, 380, 450),
    ('brzeg-dolny', 'Brzeg Dolny', 51.2704, 16.7096, 286, 350, 400),
    ('glogow', 'Głogów', 51.6663, 16.0943, 401, 390, 450),
    ('redzin', 'Wrocław — Rędzin', 51.1670, 16.9315, 268, 330, 400),
]


def forbidden(request):
    raise AssertionError(f'External network forbidden in Explorer preview: {request.url}')


def seed_preview(history):
    for hours in range(24, -1, -1):
        fetched = LAST_SAMPLE - timedelta(hours=hours)
        items = []
        for key, name, latitude, longitude, latest, warning, alarm in STATIONS:
            # Głogów deliberately has no new measurements for four hours.
            age = max(hours, 4) if key == 'glogow' else hours
            observed = LAST_SAMPLE - timedelta(hours=age)
            slope = -0.18 if key == 'brzeg-dolny' else 1.75 if key == 'trestno' else .3
            value = round(latest - age * slope)
            # A null correction is an explicit break, never a zero measurement.
            if key == 'redzin' and hours in (11, 12):
                value = None
            items.append({
                'id': f'explorer-{key}', 'name': f'DEMO: {name}', 'river': 'Odra',
                'province': 'dolnośląskie', 'latitude': latitude, 'longitude': longitude,
                'warning_level_cm': warning, 'alarm_level_cm': alarm, 'synthetic': True,
                'measurements': {'water_level': {
                    'value': value, 'unit': 'cm', 'observed_at': observed.isoformat(),
                    'source_time': observed.isoformat(),
                }},
            })
        history.write('hydro:stations', {
            'status': 'ready', 'items': items, 'fetched_at': fetched.isoformat(),
            'synthetic': True, 'source_url': 'https://example.invalid/wici/explorer-preview/hydro',
            'message': 'DEMO: wymyślone pomiary Doliny Odry do porównania interfejsu z makietą.',
        })


def make_app(directory, port):
    client = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    app = create_app(demo=True, root=Path(directory), config=Config(port=port), client=client)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            application.state.repo.clock = lambda: NOW
            seed_preview(application.state.station_history)
            yield
        await client.aclose()

    app.router.lifespan_context = lifespan

    @app.get('/_test/explorer-preview')
    def preview():
        return {'synthetic': True, 'scenario': 'DEMO: Dolina Odry', 'now': NOW.isoformat(),
                'selected_ref': SELECTED_REF, 'province': '02', 'value': 412, 'unit': 'cm',
                'observed_at': LAST_SAMPLE.isoformat(), 'station_count': len(STATIONS),
                'range': {'from': (NOW - timedelta(hours=24)).isoformat(), 'to': NOW.isoformat()}}

    return app


def serve(port):
    with tempfile.TemporaryDirectory(prefix='wici-explorer-preview-') as directory:
        uvicorn.run(make_app(directory, port), host='127.0.0.1', port=port, log_level='error')


if __name__ == '__main__':
    serve(int(sys.argv[1]))
