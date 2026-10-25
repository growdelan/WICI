"""Independent regressions for real source contracts and read-only rule previews."""
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from wici.hydro import stations
from wici.repository import Repository
from wici.sources.normalize import document, location
from wici.station_history import StationHistory
from wici.workspace_monitor import append_observation
from wici.workspace_service import WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'review.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def area(workspace):
    return workspace.areas.save({'name': 'Test', 'shape': 'rectangle', 'geometry': {
        'type': 'Polygon', 'coordinates': [[[20, 51], [22, 51], [22, 53], [20, 53], [20, 51]]]}})


def transport(workspace):
    return {'name': 'Wejścia', 'template': 'transport', 'config': {
        'area_id': area(workspace)['id'], 'object_type': 'aircraft', 'transition': 'both'}}


def preview(workspace, rule):
    checkpoint = [tuple(row) for row in workspace.db.execute('SELECT id,checkpoint_id FROM workspace_rules')]
    before = workspace.db.total_changes
    result = workspace.rules.preview({'rule': rule, 'from': (NOW-timedelta(hours=1)).isoformat(),
                                      'to': (NOW+timedelta(seconds=1)).isoformat()})
    assert workspace.db.total_changes == before
    assert [tuple(row) for row in workspace.db.execute('SELECT id,checkpoint_id FROM workspace_rules')] == checkpoint
    assert workspace.events.list()['total'] == 0
    assert result['dry_run']
    return result


def test_preview_scopes_gaps_and_never_changes_events_or_checkpoints(workspace):
    rule = transport(workspace)
    workspace.rules.save(dict(rule, enabled=True))
    with workspace.repo.lock, workspace.db:
        for seconds, kind, source, lon in [(-40, 'transport', 'aircraft', 19),
                (-30, 'gap', 'ships', None), (-20, 'transport', 'aircraft', 21),
                (-15, 'gap', 'aircraft', None), (-10, 'transport', 'aircraft', 19)]:
            at = (NOW+timedelta(seconds=seconds)).isoformat()
            append_observation(workspace.repo, kind, '*' if kind == 'gap' else 'aircraft:icao:abc123', source,
                at, str(seconds), {'object_type': 'aircraft', 'latitude': 52, 'longitude': lon}, kind != 'gap')
    result = preview(workspace, rule)
    assert [item['trigger'] for item in result['items']] == ['enter']
    assert result['coverage']['gaps'] >= 1


def test_transport_preview_uses_composite_track_point_identity(workspace):
    rule = transport(workspace)
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('''INSERT INTO object_tracks(id,kind,object_id,label,active,started_at,status)
            VALUES('old-track','aircraft','abc123','Test',0,?,'stopped')''', ((NOW-timedelta(minutes=1)).isoformat(),))
        for second, lon, gap in [(-40, 19, 1), (-30, 19, 0), (-20, 21, 0)]:
            at = (NOW+timedelta(seconds=second)).isoformat()
            workspace.db.execute('''INSERT INTO object_track_points(track_id,position_at,latitude,longitude,
                break_before,recorded_at) VALUES('old-track',?,52,?,?,?)''', (at, lon, gap, at))
    result = preview(workspace, rule)
    assert [item['trigger'] for item in result['items']] == ['enter']
    assert result['items'][0]['observation']['payload']['track_id'] == 'old-track'


def test_document_preview_uses_original_version_event_locations(workspace):
    raw = document('rso', 'review-notice', 'https://example.org/notice', 'Komunikat', 'Treść',
                   {'locations': [location('14', 'notification_area', 'RSO')]}, [],
                   source_published_at=(NOW-timedelta(minutes=1)).isoformat())
    workspace.repo.ingest(raw)
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM workspace_observations')  # Retained document history still exists.
    result = preview(workspace, {'name': 'Mazowsze', 'template': 'communication', 'config': {'admin_code': '14'}})
    assert len(result['items']) == 1
    assert result['items'][0]['observation']['payload']['areas'][0]['admin_code'] == '14'
    assert 'administracyjnego' in result['items'][0]['description']


@pytest.mark.parametrize('metric,source_field,time_field,unit,value,threshold', [
    ('discharge', 'przeplyw', 'przeplyw_data', 'm³/s', 2, 1),
    ('temperature', 'temperatura_wody', 'temperatura_wody_data_pomiaru', '°C', 25, 20),
])
def test_rules_accept_actual_hydro_normalizer_metrics(workspace, metric, source_field, time_field, unit, value, threshold):
    history = StationHistory(workspace.repo)
    raw = json.loads((Path(__file__).parent/'fixtures/imgw_hydro/hydro.json').read_text())[0]
    raw[time_field] = NOW.strftime('%Y-%m-%d %H:%M:%S')
    raw[source_field] = 0
    def response(row):
        return {'status': 'ready', 'items': stations([row], NOW)[0], 'fetched_at': NOW.isoformat(),
                'source_url': 'https://danepubliczne.imgw.pl/api/data/hydro/'}
    history.write('hydro:stations', response(raw))
    ref = 'hydro_station:imgw:'+raw['id_stacji']
    workspace.rules.save({'name': metric, 'template': 'measurement', 'enabled': True,
        'config': {'object_ref': ref, 'sensor_id': '', 'metric': metric, 'unit': unit, 'threshold': threshold}})
    changed = copy.deepcopy(raw)
    changed[source_field] = value
    history.write('hydro:stations', response(changed))
    workspace.monitor.process()
    assert workspace.events.list()['total'] == 1
    event = workspace.events.detail(workspace.events.list()['items'][0]['id'])
    assert event['evidence']['observation']['payload']['metric'] == metric
    assert event['evidence']['observation']['payload']['unit'] == unit


@pytest.mark.asyncio
async def test_background_gios_deduplicates_resources_and_uses_integer_identity(workspace):
    history = StationHistory(workspace.repo)
    history.write('gios:sensors:1', {'status': 'ready', 'fetched_at': NOW.isoformat(), 'items': [
        {'id': 10, 'station_id': 1, 'parameter': 'PM10', 'name': 'PM10', 'unit': 'µg/m³'}]})
    for name in ('Pierwszy próg', 'Drugi próg'):
        workspace.rules.save({'name': name, 'template': 'measurement', 'mode': 'background', 'enabled': True,
            'config': {'object_ref': 'air_quality_station:gios:1', 'sensor_id': '10', 'metric': 'PM10',
                       'unit': 'µg/m³', 'threshold': 60}})
    class Gios:
        def __init__(self):
            self.calls = []
        async def fetch(self, kind, identity):
            assert type(identity) is int  # This is the real GiosService contract.
            self.calls.append((kind, identity))
            return {'status': 'ready', 'stale': False}
    source = Gios()
    workspace.monitor.bind(SimpleNamespace(gios=source))
    await workspace.monitor._background()
    assert set(source.calls) == {('sensors', 1), ('data', 10)}
    assert len(source.calls) == 2
    await workspace.monitor._background()
    assert len(source.calls) == 2  # A second rule and immediate tick reuse the same fetch.


def test_legacy_ukraine_short_gap_prevents_false_clear_at_same_timestamp(workspace):
    with workspace.repo.lock, workspace.db:
        ref = workspace.ukraine._region('oblast', 'legacy', 'Obwód')
        for seconds, state in [(-40, 'red'), (-20, 'none')]:
            at = (NOW+timedelta(seconds=seconds)).isoformat()
            run = workspace.db.execute('''INSERT INTO workspace_ukraine_runs
                (observed_at,recorded_at,status) VALUES(?,?,'ready')''', (at, at)).lastrowid
            workspace.db.execute('''INSERT INTO workspace_ukraine_observations
                (run_id,region_ref,observed_at,state) VALUES(?,?,?,?)''', (run, ref, at, state))
        gap = (NOW-timedelta(seconds=20)).isoformat()
        workspace.db.execute('''INSERT INTO workspace_ukraine_runs(observed_at,recorded_at,status,reason)
            VALUES(?,?,'unknown','storage_error')''', (gap, gap))
        workspace.db.execute('DELETE FROM workspace_observations')
    result = preview(workspace, {'name': 'Alarm historyczny', 'template': 'ukraine', 'config': {'region_ref': ref}})
    assert [item['trigger'] for item in result['items']] == ['observed_active']
    assert result['coverage']['gaps'] >= 1


def legacy_measurements(workspace, ref, sensor='', metric='water_level', unit='cm'):
    for seconds, value in [(-40, 65), (-20, 58), (-10, 65)]:
        at = (NOW+timedelta(seconds=seconds)).isoformat()
        workspace.db.execute('''INSERT INTO station_measurements(object_ref,sensor_id,metric,observed_key,
            observed_at,value,unit,fetched_at,first_fetched_at,revision,quality,content_hash)
            VALUES(?,?,?,?,?,?,?,?,?,1,'valid',?)''',
            (ref, sensor, metric, at, at, value, unit, at, at, str(value)))


@pytest.mark.parametrize('resource,relevant', [('hydro:stations', True), ('hydro:warnings', False),
                                             ('gios:data:10', False)])
def test_legacy_station_failures_are_scoped_and_reset_hysteresis(workspace, resource, relevant):
    ref = 'hydro_station:imgw:legacy'
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station(ref, 'imgw', 'legacy', 'Wodowskaz')
        legacy_measurements(workspace, ref)
        gap = (NOW-timedelta(seconds=30)).isoformat()
        workspace.db.execute('''INSERT INTO workspace_source_runs(resource,fetched_at,status,complete,message)
            VALUES(?,?,'error',0,'storage_error')''', (resource, gap))
        workspace.db.execute('DELETE FROM workspace_observations')
    rule = {'name': 'Próg historyczny', 'template': 'measurement', 'config': {
        'object_ref': ref, 'sensor_id': '', 'metric': 'water_level', 'unit': 'cm',
        'threshold': 60, 'return_threshold': 50}}
    result = preview(workspace, rule)
    assert len(result['items']) == (2 if relevant else 1)
    assert result['coverage']['gaps'] >= 1 if relevant else True


@pytest.mark.parametrize('resource,relevant', [('gios:data:10', True), ('gios:sensors:1', True),
                                             ('gios:data:99', False), ('gios:sensors:2', False),
                                             ('gios:index:1', False)])
def test_legacy_gios_gaps_match_exact_sensor_and_station(workspace, resource, relevant):
    history = StationHistory(workspace.repo)
    history.write('gios:sensors:1', {'status': 'ready', 'fetched_at': NOW.isoformat(), 'items': [
        {'id': 10, 'station_id': 1, 'parameter': 'PM10', 'name': 'PM10', 'unit': 'µg/m³'}]})
    ref = 'air_quality_station:gios:1'
    with workspace.repo.lock, workspace.db:
        legacy_measurements(workspace, ref, '10', 'PM10', 'µg/m³')
        gap = (NOW-timedelta(seconds=30)).isoformat()
        workspace.db.execute('''INSERT INTO workspace_source_runs(resource,fetched_at,status,complete,message)
            VALUES(?,?,'error',0,'storage_error')''', (resource, gap))
        workspace.db.execute('DELETE FROM workspace_observations')
    rule = {'name': 'PM10 historyczne', 'template': 'measurement', 'config': {
        'object_ref': ref, 'sensor_id': '10', 'metric': 'PM10', 'unit': 'µg/m³',
        'threshold': 60, 'return_threshold': 50}}
    result = preview(workspace, rule)
    assert len(result['items']) == (2 if relevant else 1)


def test_track_break_is_object_scoped_in_multi_object_preview(workspace):
    rule = transport(workspace)
    with workspace.repo.lock, workspace.db:
        for track, identity in [('track-a', 'aaa111'), ('track-b', 'bbb222')]:
            workspace.db.execute('''INSERT INTO object_tracks(id,kind,object_id,label,active,started_at,status)
                VALUES(?,'aircraft',?,?,0,?,'stopped')''', (track, identity, track, NOW.isoformat()))
        for track, seconds, lon, gap in [('track-a', -40, 19, 0), ('track-b', -30, 19, 1),
                                         ('track-a', -20, 21, 0)]:
            at = (NOW+timedelta(seconds=seconds)).isoformat()
            workspace.db.execute('''INSERT INTO object_track_points(track_id,position_at,latitude,longitude,
                break_before,recorded_at) VALUES(?,?,52,?,?,?)''', (track, at, lon, gap, at))
        workspace.db.execute('DELETE FROM workspace_observations')
    result = preview(workspace, rule)
    assert [(item['object_ref'], item['trigger']) for item in result['items']] == [('aircraft:icao:aaa111', 'enter')]


def test_live_object_gap_does_not_reset_other_aircraft_and_specific_rule_ignores_it(workspace):
    broad = transport(workspace)
    rule = workspace.rules.save(dict(broad, enabled=True))
    config = dict(broad['config'], object_type=None, object_ref='aircraft:icao:aaa111')
    specific = workspace.rules.save(dict(broad, name='Jeden obiekt', enabled=True, config=config))
    with workspace.repo.lock, workspace.db:
        for seconds, kind, ref, lon in [(-40, 'transport', 'aircraft:icao:aaa111', 19),
                (-30, 'gap', 'aircraft:icao:bbb222', None), (-20, 'transport', 'aircraft:icao:aaa111', 21)]:
            at = (NOW+timedelta(seconds=seconds)).isoformat()
            append_observation(workspace.repo, kind, ref, 'aircraft', at, [seconds, kind],
                               {'object_type': 'aircraft', 'longitude': lon, 'latitude': 52}, kind != 'gap')
    workspace.monitor.process()
    for identity in (rule['id'], specific['id']):
        items = workspace.events.list(rule_id=identity)['items']
        assert len(items) == 1
        evidence = workspace.events.detail(items[0]['id'])['evidence']
        assert evidence['observation']['trigger'] == 'enter'


def test_specific_aircraft_preview_uses_aircraft_gap_limit(workspace):
    rule = transport(workspace)
    rule['config'] = {'area_id': rule['config']['area_id'], 'object_ref': 'aircraft:icao:aaa111'}
    at = (NOW-timedelta(minutes=5)).isoformat()
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM workspace_observations')
        append_observation(workspace.repo, 'transport', 'aircraft:icao:aaa111', 'aircraft', at, 'old',
                           {'object_type': 'aircraft', 'latitude': 52, 'longitude': 21})
    result = preview(workspace, rule)
    assert result['coverage']['unknown_intervals'][-1]['from'] == at
    assert result['coverage']['unknown_intervals'][-1]['to'] == (NOW+timedelta(seconds=1)).isoformat()


def archive_ukraine_poll(workspace, seconds, state='red'):
    at = NOW+timedelta(seconds=seconds)
    workspace.repo.clock = lambda: at
    items = ([{'scope': 'oblast', 'key': 'coverage', 'name': 'Obwód', 'level': state}]
             if state != 'none' else [])
    return workspace.ukraine.ingest({'status': 'ready', 'fetched_at': at.isoformat(), 'items': items}, record=True)


def ukraine_archive_preview(workspace):
    workspace.repo.clock = lambda: NOW
    # Simulate pre-stream data or compaction; the actual sparse source archive
    # and its successful full-snapshot runs remain authoritative.
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM workspace_observations')
    before = workspace.db.total_changes
    result = workspace.rules.preview({'rule': {'name': 'Archiwum alarmów', 'template': 'ukraine',
        'config': {'region_ref': 'ua_region:neptun:oblast:coverage'}},
        'from': NOW-timedelta(seconds=125), 'to': NOW+timedelta(seconds=1)})
    assert workspace.db.total_changes == before
    assert workspace.events.list()['total'] == 0
    return result


def test_legacy_ukraine_ready_runs_preserve_long_alarm_and_known_clear(workspace):
    for seconds in range(-120, 1, 15):
        archive_ukraine_poll(workspace, seconds, 'none' if seconds == 0 else 'red')
    assert workspace.db.execute('SELECT count(*) FROM workspace_ukraine_observations').fetchone()[0] == 2
    assert workspace.db.execute("SELECT count(*) FROM workspace_ukraine_runs WHERE status='ready'").fetchone()[0] == 9
    result = ukraine_archive_preview(workspace)
    assert [item['trigger'] for item in result['items']] == ['observed_active', 'state_change']
    assert result['items'][-1]['condition_state'] == 'unmet'
    assert result['coverage']['gaps'] == 0


@pytest.mark.parametrize('reason', ['recording_stopped', 'restart', 'storage_error'])
def test_legacy_ukraine_ready_runs_preserve_explicit_breaks(workspace, reason):
    for seconds in (-120, -105, -90, -75):
        archive_ukraine_poll(workspace, seconds)
    workspace.repo.clock = lambda: NOW-timedelta(seconds=60)
    workspace.ukraine.mark_gap(reason)
    for seconds in (-45, -30, -15, 0):
        archive_ukraine_poll(workspace, seconds, 'none' if seconds == 0 else 'red')
    result = ukraine_archive_preview(workspace)
    assert [item['trigger'] for item in result['items']] == [
        'observed_active', 'observed_active', 'state_change']
    assert result['coverage']['gaps'] >= 1


def test_legacy_ukraine_missing_polls_do_not_confirm_clear(workspace):
    archive_ukraine_poll(workspace, -50)
    archive_ukraine_poll(workspace, 0, 'none')
    result = ukraine_archive_preview(workspace)
    # A 50-second hole exceeds the recorder's 45-second coverage window,
    # even though the live rule's maximum interval is 60 seconds.
    assert [item['trigger'] for item in result['items']] == ['observed_active']
    assert result['coverage']['gaps'] >= 1


def test_stream_polls_can_fill_period_without_ukraine_archive_runs(workspace):
    archive_ukraine_poll(workspace, -90)
    archive_ukraine_poll(workspace, 0, 'none')
    ref = 'ua_region:neptun:oblast:coverage'
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM workspace_observations')
        for seconds in (-75, -60, -45, -30, -15):
            at = NOW+timedelta(seconds=seconds)
            workspace.repo.clock = lambda: NOW
            append_observation(workspace.repo, 'ukraine', ref, 'ukraine_alerts', at, seconds, {'state': 'red'})
    result = preview(workspace, {'name': 'Pełne pokrycie', 'template': 'ukraine', 'config': {'region_ref': ref}})
    assert [item['trigger'] for item in result['items']] == ['observed_active', 'state_change']
    assert not [item for item in result['coverage']['unknown_intervals']
                if item['from'] >= (NOW-timedelta(seconds=90)).isoformat()]


def test_ukraine_stream_preview_retains_live_interval_contract(workspace):
    with workspace.repo.lock, workspace.db:
        ref = workspace.ukraine._region('oblast', 'stream', 'Obwód')
        workspace.db.execute('DELETE FROM workspace_observations')
        for seconds, state in [(-50, 'red'), (0, 'none')]:
            append_observation(workspace.repo, 'ukraine', ref, 'ukraine_alerts',
                               NOW+timedelta(seconds=seconds), seconds, {'state': state})
    result = preview(workspace, {'name': 'Strumień', 'template': 'ukraine', 'config': {'region_ref': ref}})
    assert [item['trigger'] for item in result['items']] == ['observed_active', 'state_change']
