"""Frozen evidence, crash replay dedup and handling isolated from condition state."""
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.repository import Repository
from wici.workspace_events import WorkspaceEvents
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
RULE = {'id': 'rule-1', 'revision': 1, 'name': 'Mój próg', 'priority': 'high',
        'template': 'measurement', 'config': {'threshold': 60, 'unit': 'µg/m³'}}
OBS = {'id': 12, 'key': 'measurement:12', 'object_ref': 'air_quality_station:gios:123',
       'observed_at': NOW.isoformat(), 'payload': {'value': 65, 'unit': 'µg/m³', 'sensor_id': 'pm-1'}}


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'events.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    service.events = WorkspaceEvents(service)
    yield service
    repo.close()


def emit(workspace, rule=None, obs=None, area=None):
    with workspace.repo.lock, workspace.db:
        return workspace.events.emit(rule or RULE, obs or OBS, 'met', 'Przekroczono własny próg', area)


def test_emit_dedup_restart_and_revision_preserve_evidence(workspace):
    area = {'id': 'a', 'revision': 1, 'name': 'Pierwotny obszar', 'geometry': {'coordinates': [[[1, 1]]]}}
    first = emit(workspace, area=area)
    assert emit(workspace, area=area)['id'] == first['id']
    workspace.events = WorkspaceEvents(workspace)
    assert emit(workspace, area=area)['id'] == first['id']
    second = emit(workspace, dict(RULE, revision=2), area=dict(area, revision=2, name='Nowa granica'))
    assert second['id'] != first['id']
    assert workspace.events.detail(first['id'])['evidence']['area'] == area
    assert workspace.events.detail(first['id'])['rule_revision'] == 1
    assert workspace.events.list()['total'] == 2
    with workspace.repo.lock, workspace.db, pytest.raises(sqlite3.IntegrityError, match='immutable'):
        workspace.db.execute('UPDATE workspace_events SET evidence_json=? WHERE id=?', ('{}', first['id']))


def test_crash_rollback_does_not_commit_event_before_checkpoint(workspace):
    with pytest.raises(RuntimeError), workspace.repo.lock, workspace.db:
        workspace.events.emit(RULE, OBS, 'met', 'Warunek')
        raise RuntimeError('failure after emission, before checkpoint')
    assert workspace.events.list()['total'] == 0
    assert emit(workspace)['status'] == 'new'


def test_handling_audit_conflicts_and_comments_do_not_retrigger(workspace):
    event = emit(workspace)
    eid = event['id']
    with pytest.raises(ValueError):
        workspace.events.handle(eid, {'status': 'closed', 'revision': 1})
    accepted = workspace.events.handle(eid, {'status': 'accepted', 'revision': 1})
    assert accepted['condition_state'] == 'met'
    with pytest.raises(QueryChanged):
        workspace.events.comment(eid, {'body': 'Stary szkic', 'revision': 1})
    comment = workspace.events.comment(eid, {'body': '<script>tekst</script>', 'revision': 2})
    closed = workspace.events.handle(eid, {'status': 'closed', 'revision': 3})
    assert closed['condition_state'] == 'met' and len(closed['history']) == 4
    assert comment['comments'][0]['body'] == '<script>tekst</script>'
    assert emit(workspace)['id'] == eid
    assert workspace.events.list()['total'] == 1


def test_capture_survives_retention_of_event_and_rule(workspace):
    event = emit(workspace)
    did = workspace.dossiers.save({'name': 'Zachowana podstawa'})['id']
    saved = workspace.events.capture(event['id'], {'dossier_id': did})
    assert saved['kind'] == 'event' and saved['snapshot']['schema_version'] == 3
    assert saved['snapshot']['event']['evidence']['observation'] == OBS
    payload = workspace.db.execute('SELECT snapshot_json FROM workspace_dossier_materials WHERE id=?', (saved['id'],)).fetchone()[0]
    assert hashlib.sha256(payload.encode()).hexdigest() == saved['sha256']
    workspace.repo.clock = lambda: NOW+timedelta(days=91)
    assert workspace.events.prune() == 1
    assert workspace.events.list()['total'] == 0
    assert workspace.dossiers.material(did, saved['id'])['snapshot'] == saved['snapshot']
    with workspace.repo.lock, workspace.db, pytest.raises(sqlite3.IntegrityError):
        workspace.db.execute('UPDATE workspace_dossier_materials SET snapshot_json=? WHERE id=?', ('{}', saved['id']))


def test_filters_time_and_pagination(workspace):
    first = emit(workspace)
    emit(workspace, dict(RULE, id='r2', priority='low'), dict(OBS, id=13, key='measurement:13',
        observed_at=(NOW-timedelta(hours=1)).isoformat()))
    assert workspace.events.list(priority='high')['items'][0]['id'] == first['id']
    assert workspace.events.list(rule_id='r2')['total'] == 1
    assert workspace.events.list(object_type='ship')['total'] == 0
    assert workspace.events.list(start=NOW.isoformat())['total'] == 1
    assert workspace.events.list(end=NOW.isoformat())['total'] == 1
    assert len(workspace.events.list(limit=1)['items']) == 1
    assert workspace.events.list(offset=2)['items'] == []
    for kwargs in ({'start': '2026-10-25T12:00:00'}, {'status': 'fake'}, {'priority': 'fake'},
                   {'condition_state': 'fake'}, {'start': NOW.isoformat(), 'end': NOW.isoformat()}):
        with pytest.raises(ValueError):
            workspace.events.list(**kwargs)


def test_api_security_revisions_capture_and_no_evaluation_on_reads(tmp_path):
    app = create_app(demo=True, root=tmp_path, config=Config())
    origin = 'http://127.0.0.1:8765'
    with TestClient(app, base_url=origin) as client:
        ws = app.state.workspace
        ws.events = WorkspaceEvents(ws)
        event = emit(ws)
        base = '/api/workspace/events/'+event['id']
        headers = {'Origin': origin, 'X-CSRF-Token': client.get('/api/health').json()['csrf_token']}
        assert client.patch(base, json={'revision': 1, 'status': 'accepted'}).status_code == 403
        assert client.get(base).json()['evidence']['rule']['name'] == RULE['name']
        response = client.patch(base, headers=headers, json={'revision': 1, 'status': 'accepted'})
        assert response.status_code == 200 and response.json()['revision'] == 2
        assert client.patch(base, headers=headers, json={'revision': 1, 'status': 'accepted'}).status_code == 409
        assert client.post(base+'/comments', headers=headers, json={'revision': 2, 'body': 'Odczytano'}).status_code == 201
        did = ws.dossiers.save({'name': 'Teczka'})['id']
        saved = client.post(base+'/capture', headers=headers, json={'dossier_id': did})
        assert saved.status_code == 201 and saved.json()['snapshot']['event']['revision'] == 3
        for _ in range(3):
            assert client.get('/api/workspace/events').json()['total'] == 1
        assert client.get(base).json()['revision'] == 3
