"""Rule definitions are selectors, versioned independently of their detections."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from wici.repository import Repository
from wici.rule_models import RuleInput, RulePreview
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'rules.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def transport(workspace, **values):
    area = workspace.areas.save({'name': 'Obszar', 'shape': 'circle', 'center': [21, 52], 'radius_m': 1000})
    return dict({'name': 'Transport', 'template': 'transport', 'enabled': True,
                 'config': {'area_id': area['id'], 'object_type': 'aircraft'}}, **values)


def test_rule_edits_conflict_and_keep_revision_history(workspace):
    raw = transport(workspace)
    first = workspace.rules.save(raw)
    assert first['revision'] == 1
    raw.update(revision=1, name='Nowa nazwa')
    second = workspace.rules.save(raw, first['id'])
    assert second['revision'] == 2
    assert second['condition_state'] == 'unknown'
    with pytest.raises(QueryChanged):
        workspace.rules.save(raw, first['id'])
    assert [i['rule']['name'] for i in workspace.rules.history(first['id'])['items']] == ['Transport', 'Nowa nazwa']


@pytest.mark.parametrize('config', [
    {}, {'area_id': 'a'}, {'area_id': 'a', 'object_ref': 'aircraft:icao:!bad'},
    {'area_id': 'a', 'object_ref': 'ship:mmsi:123456789', 'object_type': 'aircraft'},
    {'area_id': 'a', 'object_type': 'aircraft', 'transition': 'vanished'},
])
def test_transport_selector_is_strict(config):
    with pytest.raises(ValidationError):
        RuleInput.model_validate({'name': 'Rule', 'template': 'transport', 'config': config})


@pytest.mark.parametrize('changes', [
    {'threshold': float('nan')}, {'threshold': float('inf')}, {'return_threshold': 61},
    {'sensor_id': ''}, {'metric': 'official_index'}, {'unit': ''}, {'unexpected': 'script()'},
])
def test_measurement_selector_requires_exact_sensor_parameter_unit(changes):
    config = {'object_ref': 'air_quality_station:gios:1', 'sensor_id': '11', 'metric': 'PM10', 'unit': 'µg/m³', 'threshold': 60}
    config.update(changes)
    with pytest.raises(ValidationError):
        RuleInput.model_validate({'name': 'Rule', 'template': 'measurement', 'config': config})


def test_catalogue_rejects_mismatched_sensor_and_accepts_hydro_metrics(workspace):
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station('hydro_station:imgw:1', 'imgw', '1', 'Wodowskaz')
    for metric, unit in [('water_level', 'cm'), ('discharge', 'm³/s'), ('temperature', '°C')]:
        saved = workspace.rules.save({'name': metric, 'template': 'measurement', 'config': {
            'object_ref': 'hydro_station:imgw:1', 'sensor_id': '', 'metric': metric, 'unit': unit, 'threshold': 10}})
        assert saved['config']['metric'] == metric
    with pytest.raises(ValueError):
        workspace.rules.save({'name': 'Wrong', 'template': 'measurement', 'config': {
            'object_ref': 'hydro_station:imgw:1', 'sensor_id': '', 'metric': 'discharge', 'unit': 'cm', 'threshold': 10}})


def test_archived_area_and_unknown_administrative_area_rejected(workspace):
    raw = transport(workspace)
    area = workspace.areas.detail(raw['config']['area_id'])
    workspace.areas.save({'name': area['name'], 'shape': 'circle', 'center': area['center'],
                          'radius_m': area['radius_m'], 'revision': area['revision'], 'archived': True}, area['id'])
    with pytest.raises(ValueError):
        workspace.rules.save(raw)
    with pytest.raises(ValueError):
        workspace.rules.save({'name': 'Unknown', 'template': 'communication', 'config': {'admin_code': '99'}})


def test_active_rule_limit_and_disable_frees_slot(workspace):
    raw = transport(workspace)
    rules = [workspace.rules.save(dict(raw, name=f'Rule {i}')) for i in range(50)]
    with pytest.raises(ValueError, match='50'):
        workspace.rules.save(raw)
    workspace.rules.save(dict(raw, enabled=False, revision=rules[0]['revision']), rules[0]['id'])
    assert workspace.rules.save(raw)['enabled']


@pytest.mark.parametrize('start,end', [(NOW, NOW), (NOW, NOW-timedelta(seconds=1)),
                                     (NOW-timedelta(days=91), NOW), (NOW.replace(tzinfo=None), NOW)])
def test_preview_time_range_is_bounded(workspace, start, end):
    with pytest.raises(ValidationError):
        RulePreview.model_validate({'rule': transport(workspace), 'from': start, 'to': end})


def test_preview_reads_history_without_creating_events_or_rule(workspace):
    from wici.workspace_monitor import append_observation
    raw = transport(workspace)
    with workspace.repo.lock, workspace.db:
        append_observation(workspace.repo, 'transport', 'aircraft:icao:abcdef', 'aircraft', NOW.isoformat(), 'position',
                           {'longitude': 21, 'latitude': 52, 'object_type': 'aircraft'})
    result = workspace.rules.preview({'rule': raw, 'from': NOW-timedelta(minutes=1), 'to': NOW+timedelta(minutes=1)})
    assert result['dry_run'] and len(result['items']) == 1
    assert 'wewnątrz' in result['items'][0]['description']
    assert workspace.rules.list()['items'] == []
    assert workspace.events.list()['items'] == []
