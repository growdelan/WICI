"""Bounded per-cycle reuse cannot change rule evidence, epochs or checkpoints."""
import collections
import json
from datetime import UTC, datetime, timedelta

import pytest

from wici import workspace_monitor as monitor_module
from wici.monitor_epochs import receipt
from wici.repository import Repository
from wici.workspace_monitor import BATCH, append_observation
from wici.workspace_service import WorkspaceService

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'monitor-performance.sqlite3', clock=lambda: NOW)
    service = WorkspaceService(repo)
    with repo.lock, repo.db:
        service.catalog.upsert_station('hydro_station:imgw:0', 'imgw', '0', 'Stacja')
    yield service
    repo.close()


def rule(workspace, threshold=60):
    return workspace.rules.save({'name': f'Próg {threshold}', 'template': 'measurement', 'enabled': True,
        'config': {'object_ref': 'hydro_station:imgw:0', 'sensor_id': '', 'metric': 'water_level',
                   'unit': 'cm', 'threshold': threshold, 'return_threshold': 50}})


def observation(workspace, number, value=65, *, token=None, kind='measurement', source='imgw', ref=None):
    with workspace.repo.lock, workspace.db:
        return append_observation(workspace.repo, kind, ref or ('*' if kind == 'gap' else 'hydro_station:imgw:0'),
            source, NOW-timedelta(seconds=1000-number), number,
            {'sensor_id': '', 'metric': 'water_level', 'unit': 'cm', 'value': value},
            trusted=kind != 'gap', receipt=token)


def test_shared_decode_keeps_rule_specific_event_triggers_out_of_peer_inputs(workspace, monkeypatch):
    rules = [rule(workspace, threshold) for threshold in (60, 70, 80)]
    for number in range(24):
        observation(workspace, number, 90 if number % 2 else 45)
    original_decode, original_evaluate = monitor_module.decode_observation, monitor_module.evaluate
    decoded, evaluated = [], []

    def decode(row):
        decoded.append(row['id'])
        return original_decode(row)

    def evaluate(value, item, *args):
        assert 'trigger' not in item
        evaluated.append((value['id'], item['id']))
        return original_evaluate(value, item, *args)

    monkeypatch.setattr(monitor_module, 'decode_observation', decode)
    monkeypatch.setattr(monitor_module, 'evaluate', evaluate)
    assert workspace.monitor.process() == 24*3
    assert len(decoded) == 24 and len(evaluated) == 72
    for value in rules:
        events = workspace.events.list(rule_id=value['id'])
        assert events['total'] == 12
        for event in events['items']:
            evidence = workspace.events.detail(event['id'])['evidence']
            assert evidence['rule']['id'] == value['id']
            assert evidence['observation']['trigger'] == 'threshold'
            assert evidence['rule']['config']['threshold'] == value['config']['threshold']


def test_decode_cache_stays_bounded_across_different_checkpoints_and_resets_each_cycle(workspace, monkeypatch):
    rules = [rule(workspace, 1000) for _ in range(3)]
    initial = rules[0]['checkpoint_id']
    for number in range(600):
        observation(workspace, number, number)
    with workspace.repo.lock, workspace.db:
        workspace.db.executemany('UPDATE workspace_rules SET checkpoint_id=? WHERE id=?',
                                [(initial+checkpoint, value['id']) for checkpoint, value in zip((0, 130, 300), rules)])
    caches = []

    class CountedCache(collections.OrderedDict):
        def __init__(self):
            super().__init__()
            self.maximum = 0
            caches.append(self)

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            self.maximum = max(self.maximum, len(self))

    monkeypatch.setattr(monitor_module, 'OrderedDict', CountedCache)
    assert workspace.monitor.process() == 3*BATCH
    assert caches[0].maximum == BATCH
    for value, last in zip(rules, (255, 385, 555)):
        state = workspace.db.execute('SELECT state_json FROM workspace_rule_states WHERE rule_id=?', (value['id'],)).fetchone()
        assert json.loads(state[0])['value'] == last
    final = observation(workspace, 999, 123)
    for _ in range(2):
        workspace.monitor.process()
    assert len(caches) == 3 and all(cache.maximum <= BATCH for cache in caches)
    for value in rules:
        assert workspace.rules.detail(value['id'])['checkpoint_id'] == final
        state = workspace.db.execute('SELECT state_json FROM workspace_rule_states WHERE rule_id=?', (value['id'],)).fetchone()
        assert json.loads(state[0])['value'] == 123


def test_distinct_receipt_epochs_gaps_and_unrelated_rows_keep_exact_checkpoints(workspace):
    first = rule(workspace, 60)
    old_token = receipt(workspace.repo)
    observation(workspace, 0, 45)
    second = rule(workspace, 100)
    observation(workspace, 1, 65, token=old_token)
    observation(workspace, 2, 120)
    observation(workspace, 3, kind='gap', source='gios')
    observation(workspace, 4, kind='gap')
    observation(workspace, 5, 45)
    observation(workspace, 6, 120)
    final = observation(workspace, 7, 999, ref='hydro_station:imgw:unrelated')
    statements = []
    workspace.db.set_trace_callback(statements.append)
    try:
        assert workspace.monitor.process() == 15
    finally:
        workspace.db.set_trace_callback(None)
    state_reads = [sql for sql in statements if 'SELECT state_json FROM workspace_rule_states' in sql]
    assert len(state_reads) == 8
    for value in (first, second):
        current = workspace.rules.detail(value['id'])
        assert current['checkpoint_id'] == final and current['condition_state'] == 'met'
        assert workspace.events.list(rule_id=value['id'])['total'] == 2
    first_values = [workspace.events.detail(event['id'])['evidence']['observation']['payload']['value']
                    for event in workspace.events.list(rule_id=first['id'])['items']]
    second_values = [workspace.events.detail(event['id'])['evidence']['observation']['payload']['value']
                     for event in workspace.events.list(rule_id=second['id'])['items']]
    assert sorted(first_values) == [65, 120]
    assert second_values == [120, 120]


def test_failure_after_a_peer_event_rolls_back_all_checkpoints_and_retry_redecodes(workspace, monkeypatch):
    rules = [rule(workspace, 60), rule(workspace, 70)]
    final = observation(workspace, 0, 90)
    emit = workspace.events.emit
    calls = []

    def fail_second(*args):
        value = emit(*args)
        calls.append(value['id'])
        if len(calls) == 2:
            raise RuntimeError('Synthetic transaction failure')
        return value

    monkeypatch.setattr(workspace.events, 'emit', fail_second)
    with pytest.raises(RuntimeError, match='Synthetic transaction failure'):
        workspace.monitor.process()
    assert workspace.events.list()['total'] == 0
    assert workspace.db.execute('SELECT count(*) FROM workspace_rule_states').fetchone()[0] == 0
    assert all(workspace.rules.detail(value['id'])['checkpoint_id'] == value['checkpoint_id'] for value in rules)
    monkeypatch.setattr(workspace.events, 'emit', emit)
    assert workspace.monitor.process() == 2
    assert workspace.events.list()['total'] == 2
    assert all(workspace.rules.detail(value['id'])['checkpoint_id'] == final for value in rules)
