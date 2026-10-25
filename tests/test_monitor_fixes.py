"""Regressions for the actual source contracts and archived-rule stop operation."""
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.gios import FIELDS, GiosService
from wici.repository import Repository
from wici.station_history import StationHistory
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize('source_time,value,threshold,expected', [
    ('2026-10-25 13:00:00', 65, 50, 1),
    ('2026-10-25 13:00:00', 0, -1, 1),
    ('2026-10-25 13:00:00', None, 50, 0),
    ('2026-10-25 09:00:00', 65, 50, 0),
    ('2026-10-25 15:00:00', 65, 50, 0),
    ('2026-10-25 02:00:00', 65, 50, 0),
])
async def test_actual_gios_fetch_history_and_rule_detection(tmp_path, source_time, value, threshold, expected):
    """No invented sample status: exercise HTTP normalization and history queue."""
    def provider(request):
        if request.url.path.endswith('station/findAll'):
            kind, rows = 'stations', [{'Identyfikator stacji': 1, 'Nazwa stacji': 'Syntetyczna stacja',
                                      'WGS84 φ N': 52, 'WGS84 λ E': 21}]
        elif request.url.path.endswith('station/sensors/1'):
            kind, rows = 'sensors', [{'Identyfikator stanowiska': 10, 'Identyfikator stacji': 1,
                                    'Wskaźnik - kod': 'PM10'}]
        elif request.url.path.endswith('data/getData/10'):
            kind, rows = 'data', [{'Data': source_time, 'Wartość': value}]
        else:
            raise AssertionError(request.url)
        return httpx.Response(200, json={FIELDS[kind]: rows, 'totalPages': 1, 'totalElements': len(rows)},
                              headers={'Content-Type': 'application/ld+json'})

    repo = Repository(tmp_path/'gios.sqlite', clock=lambda: NOW)
    workspace = WorkspaceService(repo)
    history = StationHistory(repo)
    history.start()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            source = GiosService(client, repo.clock, history=history)
            assert (await source.fetch('stations'))['status'] == 'ready'
            assert (await source.fetch('sensors', 1))['status'] == 'ready'
            await history.flush()
            rule = workspace.rules.save({'name': 'Własny próg PM10', 'template': 'measurement', 'enabled': True,
                'config': {'object_ref': 'air_quality_station:gios:1', 'sensor_id': '10', 'metric': 'PM10',
                           'unit': 'µg/m³', 'threshold': threshold}})
            response = await source.fetch('data', 10)
            assert response['status'] in ('ready', 'missing')
            assert response['items'][0]['status'] == ('missing' if value is None else 'value')
            await history.flush()
            workspace.monitor.process()
            assert workspace.events.list(rule_id=rule['id'])['total'] == expected
            row = repo.db.execute("SELECT trusted FROM workspace_observations WHERE kind='measurement'").fetchone()
            assert bool(row['trusted']) == bool(expected)
            if expected:
                event = workspace.events.detail(workspace.events.list()['items'][0]['id'])
                assert event['evidence']['observation']['payload']['value'] == value
                assert workspace.rules.detail(rule['id'])['condition_state'] == 'met'
            else:
                assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
            # A cache hit is not a new source observation and must not emit again.
            await source.fetch('data', 10)
            await history.flush()
            workspace.monitor.process()
            assert workspace.events.list(rule_id=rule['id'])['total'] == expected
    finally:
        await history.close()
        repo.close()


def test_archived_area_rule_can_stop_but_cannot_restart_or_change_to_invalid_selector(tmp_path):
    repo = Repository(tmp_path/'archived.sqlite', clock=lambda: NOW)
    try:
        workspace = WorkspaceService(repo)
        area = workspace.areas.save({'name': 'Obszar', 'shape': 'circle', 'center': [21, 52], 'radius_m': 1000})
        raw = {'name': 'Transport', 'template': 'transport', 'mode': 'background', 'enabled': True,
               'config': {'area_id': area['id'], 'object_type': 'aircraft'}}
        rule = workspace.rules.save(raw)
        workspace.areas.save({'name': area['name'], 'shape': 'circle', 'center': area['center'],
            'radius_m': area['radius_m'], 'archived': True, 'revision': area['revision']}, area['id'])
        stopped = workspace.rules.save(dict(raw, enabled=False, revision=rule['revision']), rule['id'])
        assert stopped['enabled'] is False and stopped['revision'] == 2
        assert workspace.monitor.status()['background_rules'] == 0
        assert workspace.rules.history(rule['id'])['items'][-1]['rule']['enabled'] is False
        with pytest.raises(QueryChanged):
            workspace.rules.save(dict(raw, enabled=False, revision=rule['revision']), rule['id'])
        with pytest.raises(ValueError, match='aktywny obszar'):
            workspace.rules.save(dict(raw, revision=stopped['revision']), rule['id'])
        with pytest.raises(KeyError):
            workspace.rules.save(dict(raw, enabled=False, revision=stopped['revision'],
                config={'area_id': 'missing-area', 'object_type': 'aircraft'}), rule['id'])
        assert not workspace.rules.detail(rule['id'])['enabled']
    finally:
        repo.close()


def test_api_archived_rule_disable_checks_csrf_and_revision(tmp_path):
    app = create_app(demo=True, root=tmp_path, config=Config())
    origin = 'http://127.0.0.1:8765'
    with TestClient(app, base_url=origin) as client:
        headers = {'Origin': origin, 'X-CSRF-Token': client.get('/api/health').json()['csrf_token']}
        area = client.post('/api/workspace/areas', headers=headers,
            json={'name': 'Obszar', 'shape': 'circle', 'center': [21, 52], 'radius_m': 1000}).json()
        raw = {'name': 'Reguła', 'template': 'transport', 'enabled': True, 'mode': 'background',
               'config': {'area_id': area['id'], 'object_type': 'aircraft'}}
        rule = client.post('/api/workspace/rules', headers=headers, json=raw).json()
        assert client.put('/api/workspace/areas/'+area['id'], headers=headers, json={
            'name': area['name'], 'shape': 'circle', 'center': [21, 52], 'radius_m': 1000,
            'revision': area['revision'], 'archived': True}).status_code == 200
        path = '/api/workspace/rules/'+rule['id']
        stopped = dict(raw, revision=rule['revision'], enabled=False)
        assert client.put(path, json=stopped).status_code == 403
        response = client.put(path, headers=headers, json=stopped)
        assert response.status_code == 200 and not response.json()['enabled']
        assert client.put(path, headers=headers, json=stopped).status_code == 409
        assert client.get('/api/workspace/monitor/status').json()['background_rules'] == 0
