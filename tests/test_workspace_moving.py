import copy
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wici.db import connect
from wici.repository import Repository
from wici.workspace_api import create_workspace_router
from wici.workspace_models import MovingReplay, SavedView, WorkspaceQuery
from wici.workspace_moving import MAX_REPLAY_POINTS
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'moving.sqlite3', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def snapshot(workspace, kind='aircraft', native_id='abc123', **changes):
    fields = {'hex': native_id, 'id': 'LOT123', 'registration': 'SP-ABC', 'type_code': 'B738',
              'speed_kmh': 800, 'altitude_m': 10000, 'track': 90} if kind == 'aircraft' else {
                  'mmsi': native_id, 'name': 'Żuraw', 'imo': 1234567, 'speed_knots': 10, 'heading': 180}
    item = dict(fields, latitude=52.2 if kind == 'aircraft' else 56.0, longitude=21.0,
                position_at=NOW.isoformat())
    item.update(changes)
    value = {'items': [item], 'status': 'ready', 'stale': False, 'fetched_at': NOW.isoformat()}
    workspace.moving.ingest(kind, value)
    return f'{kind}:{"icao" if kind == "aircraft" else "mmsi"}:{native_id}', value


def track(workspace, ref, track_id='session-1', *, active=False, points=None):
    kind, _, native_id = ref.split(':')
    points = points or [(NOW-timedelta(hours=1), 52.2, 21.0, True), (NOW-timedelta(minutes=59), 52.3, 21.1, False)]
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('''INSERT INTO object_tracks(id,kind,object_id,label,active,started_at,stopped_at,status)
            VALUES(?,?,?,?,?,?,?,?)''', (track_id, kind, native_id, 'Recorded '+native_id, int(active),
                points[0][0].isoformat(), None if active else points[-1][0].isoformat(), 'live' if active else 'stopped'))
        workspace.db.executemany('''INSERT INTO object_track_points(track_id,position_at,latitude,longitude,
            altitude_m,speed_kmh,heading,break_before,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)''',
            [(track_id, at.isoformat(), lat, lon, 10000 if kind == 'aircraft' else None,
                800 if kind == 'aircraft' else 18.52, 90, int(gap), at.isoformat()) for at, lat, lon, gap in points])
    return track_id


def ranged(ref_type='aircraft', **kwargs):
    return dict(types=[ref_type], time={'mode': 'range', 'filter_range': {
        'from': (NOW-timedelta(hours=2)).isoformat(), 'to': NOW.isoformat()}}, **kwargs)


@pytest.mark.parametrize('kind,classification', [
    ('aircraft', True), ('aircraft', False), ('aircraft', None),
    ('ship', 35), ('ship', 70), ('ship', None),
])
def test_replay_includes_current_symbol_classification_without_replacing_recorded_bearing(workspace, kind, classification):
    changes = {'military': classification} if kind == 'aircraft' else {'type_code': classification}
    if kind == 'aircraft':
        changes['track'] = 270
    ref, _ = snapshot(workspace, kind, 'abc123' if kind == 'aircraft' else '261000001', **changes)
    track(workspace, ref)
    result = workspace.moving.replay({'refs': [ref], 'from': (NOW-timedelta(hours=2)).isoformat(), 'to': NOW.isoformat()})
    series = result['series'][0]
    assert series['metadata_context'] == 'current'
    assert series['metadata']['military' if kind == 'aircraft' else 'type_code'] == classification
    assert [point['heading'] for point in series['points']] == [90, 90]
    assert 'last_known_position' not in series['metadata']
    assert series['label'] == ('LOT123' if kind == 'aircraft' else 'Żuraw')


def test_live_catalog_identifiers_watchlist_metadata_and_converted_ship_units(workspace):
    plane, _ = snapshot(workspace)
    ship, _ = snapshot(workspace, 'ship', '123456789')
    result = workspace.query({'types': ['aircraft', 'ship']})
    assert result['total'] == result['map']['located_total'] == 2
    for text, expected in [('sp-abc', plane), ('abc123', plane), ('LOT123', plane), ('1234567', ship), ('zuraw', ship)]:
        assert workspace.query({'types': ['aircraft', 'ship'], 'q': text})['items'][0]['ref'] == expected
    detail = workspace.detail(ship)
    assert detail['object']['position']['speed_kmh'] == pytest.approx(18.52)
    assert detail['object']['metadata']['imo'] == 1234567
    assert detail['object']['freshness'] == 'fresh'
    assert workspace.query({'watched_only': True})['total'] == 0
    assert workspace.moving.watch(ship, True) == {'ref': ship, 'watched': True}
    assert workspace.moving.watch(ship, True)['watched']
    assert [i['ref'] for i in workspace.watchlist()['items']] == [ship]
    assert workspace.query({'watched_only': True})['items'][0]['ref'] == ship
    assert workspace.db.execute('SELECT count(*) FROM object_tracks').fetchone()[0] == 0
    workspace.moving.watch(ship, False)
    workspace.moving.watch(ship, False)
    assert workspace.watchlist()['items'] == []


def test_snapshot_idempotence_and_stale_missing_disabled_never_form_ghost_map_polygons(workspace):
    ref, initial = snapshot(workspace)
    revision = workspace.catalog.object(ref)['revision']
    changes = workspace.db.total_changes
    workspace.moving.ingest('aircraft', initial)
    assert workspace.db.total_changes == changes
    assert workspace.catalog.object(ref)['revision'] == revision
    for change in ({'status': 'error', 'stale': True}, {'items': []}, {'status': 'disabled'}, {'demo': True}):
        workspace.moving.ingest('aircraft', initial | change)
        result = workspace.query({'types': ['aircraft']})
        assert result['total'] == 1
        assert result['items'][0]['position'] is None
        assert result['items'][0]['last_known_position']['latitude'] == 52.2
        assert result['map']['located_total'] == 0
        assert result['map']['unlocated_total'] == 1
        assert result['map']['items'] == []
        assert workspace.query({'types': ['aircraft'], 'include_unlocated': False})['total'] == 0
        workspace.moving.ingest('aircraft', initial)
        assert workspace.query({'types': ['aircraft']})['map']['located_total'] == 1
    workspace.repo.clock = lambda: NOW+timedelta(seconds=121)
    assert workspace.query({'types': ['aircraft']})['map']['items'] == []


def test_durable_watchlist_retains_identity_across_restart_but_feed_must_reconnect(tmp_path):
    path = tmp_path/'persistent.sqlite'
    repo = Repository(path, clock=lambda: NOW)
    service = WorkspaceService(repo)
    ref, _ = snapshot(service)
    service.moving.watch(ref, True)
    repo.close()
    repo = Repository(path, clock=lambda: NOW)
    service = WorkspaceService(repo)
    assert service.watchlist()['items'][0]['ref'] == ref
    assert service.detail(ref)['object']['position'] is None
    assert service.detail(ref)['object']['source_status'] == 'not_loaded'
    repo.close()


def test_history_query_map_and_province_use_recorded_position_not_live_position(workspace):
    ref, current = snapshot(workspace, latitude=50.06, longitude=19.94)
    other, _ = snapshot(workspace, native_id='abc124')
    track(workspace, ref)
    result = workspace.query(ranged(province='14'))
    assert result['total'] == 1
    assert result['items'][0]['ref'] == ref
    assert result['items'][0]['position']['latitude'] == 52.3
    assert result['map']['points'][0]['latitude'] == 52.3
    assert result['timeline_summary']['event_total'] == 2
    assert workspace.query(ranged(province='12'))['total'] == 0
    assert workspace.query(ranged(q=other))['total'] == 0
    details = workspace.detail(ref, result['as_of'], result['data_revision'],
                               (NOW-timedelta(minutes=59, seconds=30)).isoformat())
    assert details['object']['position']['latitude'] == 52.2
    assert details['object']['value_context'] == 'cursor'
    assert len(details['track_sessions']) == 1
    gap = workspace.detail(ref, result['as_of'], result['data_revision'], (NOW-timedelta(minutes=50)).isoformat())
    assert gap['object']['position'] is None
    with pytest.raises(ValueError, match='Kursor'):
        workspace.detail(ref, result['as_of'], result['data_revision'], NOW.isoformat())
    # Changes to live position do not invalidate a frozen recorded position query.
    current['items'][0].update(latitude=49.9, longitude=19.8, position_at=(NOW+timedelta(seconds=10)).isoformat())
    workspace.repo.clock = lambda: NOW+timedelta(seconds=10)
    workspace.moving.ingest('aircraft', current)
    assert workspace.detail(ref, result['as_of'], result['data_revision'])['in_scope']


def test_replay_is_exact_half_open_preserves_gaps_sessions_and_all_selected_objects(workspace):
    plane, _ = snapshot(workspace)
    ship, _ = snapshot(workspace, 'ship', '123456789')
    start = NOW-timedelta(hours=1)
    track(workspace, plane, points=[(start, 52.2, 21, True), (start+timedelta(seconds=30), 52.3, 21, False),
        (start+timedelta(minutes=10), 52.4, 21, False)])
    track(workspace, plane, 'session-2', points=[(start+timedelta(minutes=11), 52.5, 21, False), (NOW, 52.6, 21, False)])
    track(workspace, ship, 'session-ship', points=[(start, 56, 18, True), (start+timedelta(minutes=10), 56.1, 18, False)])
    result = workspace.moving.replay({'refs': [plane, ship], 'from': start.isoformat(), 'to': NOW.isoformat()})
    assert result['interpolation'] is False
    assert result['retention_days'] == 7
    aircraft, vessel = result['series']
    assert aircraft['total_points'] == aircraft['returned_points'] == 4
    assert [p['break_before'] for p in aircraft['points']] == [True, False, True, True]
    assert [p['track_id'] for p in aircraft['points']] == ['session-1']*3+['session-2']
    assert len(aircraft['sessions']) == 2
    assert len(vessel['points']) == 2
    assert vessel['points'][1]['break_before'] is False
    assert vessel['points'][0]['altitude_m'] is None
    assert not aircraft['downsampled']
    assert aircraft['points'][0]['at'] == start.isoformat()
    timeline = workspace.timeline(plane, start.isoformat(), NOW.isoformat(), limit=2)
    assert timeline['total'] == 4
    assert timeline['next_cursor'] == '2'
    assert all(p['kind'] == 'track_point' for p in timeline['items'])


def test_replay_limit_is_explicit_and_does_not_silently_skip_recorded_points(workspace):
    ref, _ = snapshot(workspace)
    start = NOW-timedelta(hours=6)
    track(workspace, ref, points=[(start+timedelta(seconds=i), 52.2, 21, False) for i in range(MAX_REPLAY_POINTS+1)])
    with pytest.raises(ValueError, match='Zawęź przedział'):
        workspace.moving.replay({'refs': [ref], 'from': start.isoformat(), 'to': NOW.isoformat()})


def test_track_and_watch_mutations_invalidate_relevant_query_cursor_and_scope(workspace):
    a, _ = snapshot(workspace)
    b, _ = snapshot(workspace, native_id='abc124')
    query = {'types': ['aircraft'], 'page_size': 1}
    first = workspace.query(query)
    workspace.moving.watch(a, True)
    with pytest.raises(QueryChanged):
        workspace.query(query | {'cursor': first['next_cursor']})
    track(workspace, a)
    first = workspace.query(ranged(page_size=1))
    assert workspace.detail(b, first['as_of'], first['data_revision'])['in_scope'] is False
    track(workspace, a, 'second-session', points=[(NOW-timedelta(minutes=30), 52.4, 21, True)])
    with pytest.raises(QueryChanged):
        workspace.detail(a, first['as_of'], first['data_revision'])


def test_backfill_only_creates_missing_identities_from_recorded_sessions(workspace):
    ref = 'aircraft:icao:abc123'
    track(workspace, ref)
    workspace.moving.backfill_tracks()
    before = workspace.catalog.object(ref)
    workspace.moving.backfill_tracks()
    assert workspace.catalog.object(ref) == before
    details = workspace.detail(ref)
    assert details['object']['position'] is None
    assert details['object']['last_known_position']['latitude'] == 52.3
    assert details['track_sessions'][0]['point_count'] == 2


def test_backfill_uses_latest_session_label_and_classification(workspace):
    ref = 'aircraft:icao:abc123'
    track(workspace, ref, 'old', points=[(NOW-timedelta(hours=2), 52.0, 21.0, True)])
    track(workspace, ref, 'recent', points=[(NOW-timedelta(hours=1), 52.2, 21.0, True)])
    with workspace.db:
        workspace.db.execute("UPDATE object_tracks SET label='Old callsign',military=0 WHERE id='old'")
        workspace.db.execute("UPDATE object_tracks SET label='Recent callsign',military=1 WHERE id='recent'")
    workspace.moving.backfill_tracks()
    item = workspace.detail(ref)['object']
    assert item['label'] == 'Recent callsign'
    assert item['metadata']['military'] is True
    assert item['last_known_position']['latitude'] == 52.2


def test_retention_protects_watchlist_and_existing_sessions_but_bounds_unwatched_catalogue(workspace):
    expired, _ = snapshot(workspace)
    watched, _ = snapshot(workspace, native_id='abc124')
    recorded, _ = snapshot(workspace, native_id='abc125')
    workspace.moving.watch(watched, True)
    track(workspace, recorded)
    workspace.repo.clock = lambda: NOW+timedelta(days=8)
    workspace.moving.ingest('aircraft', {'items': [], 'status': 'ready'})
    assert workspace.catalog.object(expired) is None
    assert workspace.catalog.object(watched)
    assert workspace.catalog.object(recorded)


def test_moving_contract_validation_api_errors_and_saved_view(workspace):
    ref, _ = snapshot(workspace)
    cfg = {'comparedRefs': [ref], 'selectedRef': ref, 'query': {'types': ['aircraft', 'ship'], 'watched_only': True}}
    saved = workspace.save_view({'name': 'Porównanie', 'config': cfg})
    assert saved['config']['comparedRefs'] == [ref]
    for refs in ([ref, ref], ['aircraft:icao:~abc123'], ['ship:mmsi:abc'], [f'aircraft:icao:abc12{i}' for i in range(6)]):
        with pytest.raises(ValidationError):
            SavedView(name='Bad', config={'comparedRefs': refs})
        with pytest.raises(ValidationError):
            MovingReplay.model_validate({'refs': refs, 'from': NOW.isoformat(), 'to': (NOW+timedelta(hours=1)).isoformat()})
    with pytest.raises(ValidationError):
        MovingReplay.model_validate({'refs': [ref], 'from': NOW.isoformat(), 'to': (NOW+timedelta(days=15)).isoformat()})
    WorkspaceQuery.model_validate({'types': ['aircraft', 'ship'], 'source_ids': ['aircraft', 'ships'], 'watched_only': True})
    app = FastAPI()
    app.state.workspace = workspace
    app.include_router(create_workspace_router())
    with TestClient(app) as client:
        assert client.put('/api/workspace/watchlist/'+ref).json()['watched']
        assert client.get('/api/workspace/watchlist').json()['items'][0]['ref'] == ref
        assert client.delete('/api/workspace/watchlist/'+ref).status_code == 200
        assert client.put('/api/workspace/watchlist/area:prg:14').status_code == 422
        assert client.put('/api/workspace/watchlist/aircraft:icao:000000').status_code == 404
        assert client.post('/api/workspace/moving/replay', json={'refs': [], 'from': NOW.isoformat(), 'to': NOW.isoformat()}).status_code == 422
        assert client.post('/api/workspace/moving/replay', json={'refs': ['aircraft:icao:000000'], 'from': (NOW-timedelta(hours=1)).isoformat(), 'to': NOW.isoformat()}).status_code == 404
        assert client.get('/api/workspace/status').status_code == 200


def test_snapshot_rejects_non_icao_non_mmsi_invalid_coordinates_and_future_time(workspace):
    snapshot(workspace, native_id='~abc123')
    snapshot(workspace, 'ship', '12345')
    assert workspace.query({'types': ['aircraft', 'ship']})['total'] == 0
    ref, _ = snapshot(workspace, latitude=float('nan'))
    assert workspace.detail(ref)['object']['position'] is None
    snapshot(workspace, position_at=(NOW+timedelta(hours=1)).isoformat())
    assert workspace.detail(ref)['object']['position'] is None


def test_large_maritime_map_has_real_positions_explicit_cap_and_correct_counts(workspace):
    _, base = snapshot(workspace, 'ship', '123456789')
    items = []
    for i in range(1001):
        value = copy.deepcopy(base['items'][0])
        value.update(mmsi=str(200000000+i))
        items.append(value)
    workspace.moving.ingest('ship', base | {'items': items})
    result = workspace.query({'types': ['ship']})
    assert result['total'] == 1002
    assert result['map']['located_total'] == 1001
    assert len(result['map']['points']) == 1000
    assert result['map']['truncated']
    assert result['warnings']
    assert result['map']['areas'] == []
    assert result['map']['unlocated_total'] == 1


def test_migration_17_preserves_foreign_key_children_and_prior_tables(tmp_path):
    path = tmp_path/'upgrade.sqlite'
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    for migration in migrations[:16]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=16')
    ref = 'hydro_station:imgw:1'
    db.execute('''INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text)
        VALUES(?,'hydro_station','imgw','1','Station','station')''', (ref,))
    db.execute('INSERT INTO catalog_object_areas VALUES(?,?,?,?)', (ref, '14', 'station_location', 'fixture'))
    db.execute('INSERT INTO station_sensors VALUES(?,?,?,?,?,?,?)', ('sensor', ref, 'metric', 'Sensor', 'cm', '{}', NOW.isoformat()))
    db.execute('''INSERT INTO station_measurements(object_ref,metric,observed_key,fetched_at,first_fetched_at,revision,quality,content_hash)
        VALUES(?,'water_level','sample',?,?,1,'valid','hash')''', (ref, NOW.isoformat(), NOW.isoformat()))
    db.execute('''INSERT INTO station_index_observations(object_ref,observed_key,fetched_at,first_fetched_at,revision,quality,content_hash)
        VALUES(?,'index',?,?,1,'valid','hash')''', (ref, NOW.isoformat(), NOW.isoformat()))
    db.execute('INSERT INTO workspace_views VALUES(?,?,?,?,?,?,?)', ('view', 'View', 1, '{}', 3, NOW.isoformat(), NOW.isoformat()))
    tables = ['catalog_objects', 'catalog_object_areas', 'station_sensors', 'station_measurements', 'station_index_observations', 'workspace_views']
    before = {name: db.execute('SELECT * FROM '+name).fetchall() for name in tables}
    db.commit()
    db.close()
    db = connect(path)
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    for name in tables:
        assert [tuple(row) for row in db.execute('SELECT * FROM '+name)] == before[name]
    db.execute('''INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text)
        VALUES('aircraft:icao:abc123','aircraft','aircraft','abc123','Airplane','airplane')''')
    db.close()
