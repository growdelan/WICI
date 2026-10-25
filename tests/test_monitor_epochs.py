"""Receipt epochs exclude delayed source writes without comparing source clocks."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from wici.moving_ingestion import MovingIngestion
from wici.repository import Repository
from wici.station_history import StationHistory
from wici.workspace_service import WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'epochs.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def circle(workspace, center):
    return workspace.areas.save({'name': 'Area', 'shape': 'circle', 'center': center, 'radius_m': 1000})


def transport(workspace, area):
    return workspace.rules.save({'name': 'Transport', 'template': 'transport', 'enabled': True,
        'config': {'area_id': area['id'], 'object_type': 'aircraft'}})


def rule_input(rule, **changes):
    return {**{key: rule[key] for key in
        ('name', 'description', 'template', 'enabled', 'mode', 'priority', 'config', 'revision')}, **changes}


def snapshot(seconds, longitude=22):
    return {'status': 'ready', 'stale': False, 'fetched_at': NOW.isoformat(), 'items': [
        {'hex': 'abcdef', 'latitude': 53, 'longitude': longitude,
         'position_at': (NOW+timedelta(seconds=seconds)).isoformat()}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['geometry', 'rename', 'rule', 'create'])
async def test_raw_transport_queue_respects_epoch_and_unaffected_rules(workspace, mutation):
    area = circle(workspace, [21, 52] if mutation == 'geometry' else [22, 53])
    changed = None if mutation == 'create' else transport(workspace, area)
    unaffected = transport(workspace, circle(workspace, [22, 53]))
    ingestion = MovingIngestion(workspace.moving)
    try:
        # No await: the actual ingestion worker cannot persist this queue entry yet.
        ingestion.enqueue('aircraft', snapshot(-2))
        assert len(ingestion.observations) == 1
        if mutation in ('geometry', 'rename'):
            workspace.areas.save({'name': 'Edited', 'shape': 'circle', 'center': [22, 53],
                'radius_m': 1000, 'revision': area['revision']}, area['id'])
        elif mutation == 'rule':
            changed = workspace.rules.save(rule_input(changed, name='Edited'), changed['id'])
        else:
            changed = transport(workspace, area)
        await ingestion.flush(timeout=5)
        workspace.monitor.process()
        assert workspace.events.list(rule_id=changed['id'])['total'] == 0
        assert workspace.events.list(rule_id=unaffected['id'])['total'] == 1
        # The new receipt is eligible even with a source time before the edit.
        ingestion.enqueue('aircraft', snapshot(-1, 22.001))
        await ingestion.flush(timeout=5)
        workspace.monitor.process()
        assert workspace.events.list(rule_id=changed['id'])['total'] == 1
    finally:
        await ingestion.close()


def hydro_response(seconds, value):
    return {'status': 'ready', 'fetched_at': NOW.isoformat(), 'items': [
        {'id': 'epoch', 'name': 'Station', 'measurements': {'water_level': {
            'observed_at': (NOW+timedelta(seconds=seconds)).isoformat(), 'value': value,
            'unit': 'cm', 'status': 'fresh'}}}]}


@pytest.mark.asyncio
async def test_station_queue_before_rule_edit_is_not_new_epoch_data(workspace):
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station('hydro_station:imgw:epoch', 'imgw', 'epoch', 'Station')
    raw = {'name': 'Threshold', 'template': 'measurement', 'enabled': True, 'config': {
        'object_ref': 'hydro_station:imgw:epoch', 'sensor_id': '', 'metric': 'water_level',
        'unit': 'cm', 'threshold': 60}}
    changed = workspace.rules.save(raw)
    unaffected = workspace.rules.save(raw)
    history = StationHistory(workspace.repo)
    try:
        assert history.submit('hydro:stations', hydro_response(-2, 65))
        workspace.rules.save(rule_input(changed, name='Edited'), changed['id'])
        await history.flush()
        workspace.monitor.process()
        assert workspace.events.list(rule_id=changed['id'])['total'] == 0
        assert workspace.events.list(rule_id=unaffected['id'])['total'] == 1
        assert history.submit('hydro:stations', hydro_response(-1, 70))
        await history.flush()
        workspace.monitor.process()
        assert workspace.events.list(rule_id=changed['id'])['total'] == 1
    finally:
        await history.close()


@pytest.mark.asyncio
async def test_new_server_receipts_remain_eligible_for_persisted_rule(tmp_path):
    from wici.monitor_epochs import RECEIPT_KEY, rule_epoch
    path = tmp_path/'restart.sqlite'
    repo = Repository(path, clock=lambda: NOW)
    workspace = WorkspaceService(repo)
    rule = transport(workspace, circle(workspace, [22, 53]))
    old_boundary = rule_epoch(repo, rule['id'])
    repo.close()
    repo = Repository(path, clock=lambda: NOW)
    workspace = WorkspaceService(repo)
    ingestion = MovingIngestion(workspace.moving)
    try:
        ingestion.enqueue('aircraft', snapshot(-1))
        token = ingestion.observations[0][1][RECEIPT_KEY]
        assert token[0] != old_boundary[0]
        await ingestion.flush(timeout=5)
        workspace.monitor.process()
        assert workspace.events.list(rule_id=rule['id'])['total'] == 1
    finally:
        await ingestion.close()
        repo.close()


@pytest.mark.asyncio
async def test_failed_rule_mutation_does_not_reuse_receipt_generation(workspace):
    rule = transport(workspace, circle(workspace, [22, 53]))
    ingestion = MovingIngestion(workspace.moving)
    # Receive an actual source snapshot while a mutation is in progress, then
    # force its transaction to fail after the epoch was allocated.
    def receive_during_failure():
        ingestion.enqueue('aircraft', snapshot(-2))
        return 1
    workspace.db.create_function('receive_during_failure', 0, receive_during_failure)
    with workspace.db:
        workspace.db.execute('''CREATE TEMP TRIGGER fail_epoch_edit BEFORE INSERT ON workspace_rule_revisions
            WHEN NEW.revision=2 BEGIN SELECT receive_during_failure();
            SELECT RAISE(ABORT,'injected rule history failure'); END''')
    try:
        with pytest.raises(sqlite3.IntegrityError, match='injected'):
            workspace.rules.save(rule_input(rule, name='Failed edit'), rule['id'])
        assert workspace.rules.detail(rule['id'])['revision'] == 1
        with workspace.db:
            workspace.db.execute('DROP TRIGGER fail_epoch_edit')
        workspace.rules.save(rule_input(rule, name='Successful edit'), rule['id'])
        await ingestion.flush(timeout=5)
        workspace.monitor.process()
        assert workspace.events.list(rule_id=rule['id'])['total'] == 0
        ingestion.enqueue('aircraft', snapshot(-1, 22.001))
        await ingestion.flush(timeout=5)
        workspace.monitor.process()
        assert workspace.events.list(rule_id=rule['id'])['total'] == 1
    finally:
        await ingestion.close()
