"""Durable analyst work is distinct from live state and source-owned history."""
import copy
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wici.app import create_app
from wici.db import connect
from wici.dossier_models import DossierInput, DossierNote, MaterialCapture
from wici.repository import Repository
from wici.sources.normalize import document, location
from wici.workspace_api import create_workspace_router
from wici.workspace_repository import encode
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
ORIGIN = 'http://127.0.0.1:8765'


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'dossiers.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def notice(workspace, title='Komunikat', text='Pierwsza treść'):
    value = document('rso', 'notice', 'https://example.org/source', title, text,
                     {'locations': [location('14', 'notification_area', 'RSO')]}, [],
                     source_published_at=(NOW-timedelta(hours=2)).isoformat())
    row = workspace.repo.ingest(value)
    workspace.catalog.backfill()
    return f"communication:{row['document_id']}", value


def station(workspace, gios=False):
    ref = 'air_quality_station:gios:123' if gios else 'hydro_station:imgw:abc'
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station(ref, 'gios' if gios else 'imgw', '123' if gios else 'abc',
                                         'Stacja', 52.2, 21.0, {'source_url': 'https://example.org/station'})
    return ref


def samples(workspace, ref, count=2):
    with workspace.repo.lock, workspace.db:
        for index in range(count):
            at = (NOW-timedelta(minutes=count-index)).isoformat()
            workspace.db.execute('''INSERT INTO station_measurements(object_ref,sensor_id,metric,observed_key,
                observed_at,source_time,value,unit,fetched_at,first_fetched_at,revision,quality,content_hash,provenance_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ref, 'pm-1', 'PM10', at, at, at, None if index == count-1 else index, 'µg/m³',
                 NOW.isoformat(), NOW.isoformat(), 1, 'valid', str(index),
                 '{"source_url":"https://example.org/measurements","synthetic":true}'))


def dossier(workspace, name='Teczka'):
    return workspace.dossiers.save({'name': name})['id']


def capture_query(types, ranged=False):
    query = {'types': types}
    if ranged:
        query['time'] = {'mode': 'range', 'filter_range': {
            'from': (NOW-timedelta(days=3)).isoformat(), 'to': (NOW+timedelta(minutes=1)).isoformat()}}
    return query


def selector(workspace, ref, kind='object', **kwargs):
    query = capture_query([ref.split(':')[0]], ranged=kind != 'object')
    query = kwargs.pop('query', query)
    result = workspace.query(query)
    return {'kind': kind, 'ref': ref, 'query': query, 'as_of': result['as_of'],
            'data_revision': result['data_revision'], **kwargs}


def test_crud_revision_conflicts_notes_and_parent_delete_are_isolated(workspace):
    first, second = dossier(workspace), dossier(workspace, 'Druga')
    note = workspace.dossiers.save_note(first, {'body': '<script>nie wykonuj</script>'})
    assert note['body'] == '<script>nie wykonuj</script>'
    assert workspace.dossiers.detail(first)['revision'] == 2
    changed = workspace.dossiers.save_note(first, {'body': 'Poprawka', 'revision': 1}, note['id'])
    assert changed['revision'] == 2
    with pytest.raises(QueryChanged):
        workspace.dossiers.save_note(first, {'body': 'Utracona edycja', 'revision': 1}, note['id'])
    with pytest.raises(QueryChanged):
        workspace.dossiers.delete_note(first, note['id'], 1)
    with pytest.raises(KeyError):
        workspace.dossiers.delete_note(second, note['id'], 2)
    with pytest.raises(KeyError):
        workspace.dossiers.save_note(second, {'body': 'Obca edycja', 'revision': 2}, note['id'])
    with pytest.raises(QueryChanged):
        workspace.dossiers.delete(first, 1)
    before = workspace.dossiers.detail(first)
    renamed = workspace.dossiers.save({'name': 'Nowa nazwa', 'description': 'Opis',
                                       'revision': before['revision']}, first)
    assert renamed['description'] == 'Opis'
    with pytest.raises(QueryChanged):
        workspace.dossiers.save({'name': 'Nieaktualna nazwa', 'revision': before['revision']}, first)
    workspace.dossiers.delete_note(first, note['id'], 2)
    assert workspace.dossiers.detail(first)['note_count'] == 0
    workspace.dossiers.delete(first, workspace.dossiers.detail(first)['revision'])
    assert [value['id'] for value in workspace.dossiers.list()['items']] == [second]


def test_pins_do_not_watch_record_or_keep_catalog_entries_alive(workspace):
    from test_workspace_moving import snapshot
    ref, _ = snapshot(workspace)
    did = dossier(workspace)
    pin = workspace.dossiers.pin(did, {'ref': ref})
    assert pin['label'] == 'LOT123'
    revision = workspace.dossiers.detail(did)['revision']
    workspace.dossiers.pin(did, {'ref': ref})
    assert workspace.dossiers.detail(did)['revision'] == revision  # idempotent duplicate
    assert workspace.watchlist()['items'] == []
    assert workspace.db.execute('SELECT count(*) FROM object_tracks').fetchone()[0] == 0
    workspace.repo.clock = lambda: NOW+timedelta(days=8)
    workspace.moving.ingest('aircraft', {'items': [], 'status': 'ready', 'stale': False})
    assert workspace.catalog.object(ref) is None
    pin = workspace.dossiers.detail(did)['pins'][0]
    assert pin['available'] is False and pin['label'] == 'LOT123'
    workspace.dossiers.unpin(did, ref)
    assert workspace.dossiers.detail(did)['pins'] == []


def test_saved_old_document_version_and_hash_survive_source_update_and_restart(tmp_path):
    path = tmp_path/'persist.sqlite'
    repo = Repository(path, clock=lambda: NOW)
    workspace = WorkspaceService(repo)
    ref, raw = notice(workspace)
    first = workspace.detail(ref)['versions'][0]['id']
    raw.update(title='Nowy tytuł', text='Nowsza treść')
    repo.ingest(raw)
    workspace.catalog.backfill()
    did = dossier(workspace)
    saved = workspace.dossiers.capture(did, selector(workspace, ref, version_id=first))
    selected = saved['snapshot']['objects'][0]['selected_version']
    assert selected['text'] == 'Pierwsza treść'
    assert selected['original_url'].startswith('https://')
    assert saved['snapshot']['objects'][0]['communication']['text'] == 'Nowsza treść'
    canonical = encode(saved['snapshot']).encode()
    assert saved['sha256'] == hashlib.sha256(canonical).hexdigest()
    assert saved['byte_size'] == len(canonical)
    raw.update(text='Trzecia treść')
    repo.ingest(raw)
    workspace.catalog.backfill()
    assert workspace.dossiers.material(did, saved['id']) == saved
    repo.close()
    repo = Repository(path, clock=lambda: NOW+timedelta(days=30))
    workspace = WorkspaceService(repo)
    assert workspace.dossiers.material(did, saved['id']) == saved
    repo.close()


def test_saved_station_null_revision_source_time_and_unit_survive_source_pruning(workspace):
    ref = station(workspace)
    samples(workspace, ref)
    did = dossier(workspace)
    at = (NOW-timedelta(minutes=1)).isoformat()
    saved = workspace.dossiers.capture(did, selector(workspace, ref, 'timeline',
        cursor_at=at, sensor_id='pm-1', metric='PM10', display_timezone='Europe/Kyiv'))
    snapshot = saved['snapshot']
    point = snapshot['timeline']['items'][-1]
    assert point['value'] is None
    assert point['unit'] == 'µg/m³' and point['revision'] == 1
    assert point['provenance']['source_url'] == 'https://example.org/measurements'
    assert point['observed_at'] == at and point['fetched_at'] == NOW.isoformat()
    assert snapshot['context']['display_timezone'] == 'Europe/Kyiv'
    assert snapshot['objects'][0]['selected_measurement']['value'] is None
    assert snapshot['captured_at'] != point['observed_at']
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM station_measurements WHERE object_ref=?', (ref,))
        workspace.db.execute('DELETE FROM catalog_objects WHERE ref=?', (ref,))
    assert workspace.dossiers.material(did, saved['id']) == saved
    with workspace.repo.lock, workspace.db, pytest.raises(sqlite3.IntegrityError, match='immutable'):
        workspace.db.execute('UPDATE workspace_dossier_materials SET title=? WHERE id=?', ('Podmieniony', saved['id']))


def test_station_timeline_exhausts_both_pagination_streams_without_duplication(workspace):
    ref = station(workspace, gios=True)
    samples(workspace, ref, 2003)
    with workspace.repo.lock, workspace.db:
        for index in range(2002):
            at = (NOW-timedelta(minutes=2002-index)).isoformat()
            workspace.db.execute('''INSERT INTO station_index_observations(object_ref,observed_key,observed_at,
                source_time,value,name,fetched_at,first_fetched_at,revision,quality,content_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (ref, at, at, at, 1, 'Dobry', NOW.isoformat(), NOW.isoformat(), 1, 'valid', str(index)))
    did = dossier(workspace)
    saved = workspace.dossiers.capture(did, selector(workspace, ref, 'timeline', sensor_id='pm-1', metric='PM10'))
    timeline = saved['snapshot']['timeline']
    assert len(timeline['items']) == timeline['total'] == 2003
    assert len({item['id'] for item in timeline['items']}) == 2003
    assert len(timeline['official_indices']) == timeline['official_indices_total'] == 2002
    assert len({item['id'] for item in timeline['official_indices']}) == 2002
    assert timeline['next_cursor'] is timeline['official_indices_next_cursor'] is None


def test_stale_or_mismatched_capture_never_persists_and_own_writes_do_not_stale_query(workspace):
    ref, _ = notice(workspace)
    did = dossier(workspace)
    selected = selector(workspace, ref)
    bad = copy.deepcopy(selected)
    bad['query']['q'] = 'inne filtry'
    with pytest.raises(ValueError, match='Zapytanie'):
        workspace.dossiers.capture(did, bad)
    workspace.dossiers.save_note(did, {'body': 'Zmiana teczki nie zmienia źródeł'})
    saved = workspace.dossiers.capture(did, selected)
    notice(workspace, text='Zmiana źródłowa')
    with pytest.raises(QueryChanged):
        workspace.dossiers.capture(did, selected)
    assert workspace.dossiers.detail(did)['material_count'] == 1
    assert workspace.dossiers.material(did, saved['id'])['snapshot']['objects'][0]['communication']['text'] == 'Pierwsza treść'


def test_capture_outside_query_rejected_instead_of_unprotected_revision(workspace):
    ref, _ = notice(workspace)
    did = dossier(workspace)
    selected = selector(workspace, ref, query={'types': ['area']})
    with pytest.raises(ValueError, match='nie należy'):
        workspace.dossiers.capture(did, selected)
    assert workspace.dossiers.detail(did)['material_count'] == 0


def test_transport_comparison_preserves_complete_tracks_gaps_and_classification(workspace):
    from test_workspace_moving import snapshot, track
    plane, _ = snapshot(workspace, military=True)
    ship, _ = snapshot(workspace, 'ship', '261000001', type_code=35)
    track(workspace, plane, 'plane')
    track(workspace, ship, 'ship')
    did = dossier(workspace)
    query = capture_query(['aircraft', 'ship'], ranged=True)
    selected = selector(workspace, plane, 'comparison', query=query, moving_refs=[plane, ship])
    saved = workspace.dossiers.capture(did, selected)
    series = saved['snapshot']['moving']['series']
    assert len(series) == 2 and [entry['total_points'] for entry in series] == [2, 2]
    assert series[0]['metadata']['military'] is True and series[1]['metadata']['type_code'] == 35
    assert series[0]['points'][0]['break_before'] is True
    assert series[1]['points'][0]['speed_kmh'] == 18.52
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM object_tracks')
    assert workspace.dossiers.material(did, saved['id']) == saved


def test_ukraine_comparison_and_episode_snapshot_keep_coverage_and_uncertainty(workspace):
    from test_workspace_ukraine import RAION, feature, range_query, recorded
    workspace.ukraine.register_geometry({'fetched_at': NOW.isoformat(), 'oblasts': {'features': [
        feature('київська область', 'Київська область')]}, 'raions': {'features': [
        feature('бучанський', 'Бучанський район', raion=True, oblast='київська область')]}})
    recorded(workspace)
    did = dossier(workspace)
    query = range_query(0, 120)
    saved = workspace.dossiers.capture(did, selector(workspace, RAION, 'comparison', query=query, region_refs=[RAION]))
    series = saved['snapshot']['ukraine']['series'][0]
    assert series['stats']['alarm_seconds'] == 40
    assert series['stats']['unknown_seconds'] > 0
    assert saved['snapshot']['ukraine']['geometry_context'] == 'current'
    alert = next(item['ref'] for item in workspace.query(query)['items'] if item['type'] == 'civil_alert')
    episode = workspace.dossiers.capture(did, selector(workspace, alert, query=query))
    assert episode['snapshot']['objects'][0]['ukraine']['episodes'][0]['ended_before'] is not None
    assert workspace.dossiers.material(did, saved['id']) == saved


def test_material_limits_are_atomic_and_delete_scoped_to_parent(workspace, monkeypatch):
    import wici.workspace_dossiers as module
    ref, _ = notice(workspace)
    first, second = dossier(workspace), dossier(workspace, 'Druga')
    selected = selector(workspace, ref)
    saved = workspace.dossiers.capture(first, selected)
    with pytest.raises(KeyError):
        workspace.dossiers.material(second, saved['id'])
    with pytest.raises(KeyError):
        workspace.dossiers.delete_material(second, saved['id'])
    monkeypatch.setattr(module, 'MAX_MATERIAL_BYTES', 1)
    with pytest.raises(ValueError, match='5 MiB'):
        workspace.dossiers.capture(first, selected)
    assert workspace.dossiers.detail(first)['material_count'] == 1
    workspace.dossiers.delete_material(first, saved['id'])
    assert workspace.dossiers.detail(first)['material_count'] == 0


def test_timeline_limit_rejects_without_persisting_partial_data(workspace, monkeypatch):
    import wici.workspace_dossiers as module
    ref = station(workspace)
    samples(workspace, ref, 3)
    did = dossier(workspace)
    monkeypatch.setattr(module, 'MAX_TIMELINE_ROWS', 2)
    with pytest.raises(ValueError, match='rekordów'):
        workspace.dossiers.capture(did, selector(workspace, ref, 'timeline'))
    assert workspace.dossiers.detail(did)['material_count'] == 0


@pytest.mark.parametrize('model,payload', [
    (DossierInput, {'name': '  '}), (DossierNote, {'body': '\n'}),
    (MaterialCapture, {'kind': 'object', 'ref': 'area:prg:14', 'query': {}, 'snapshot': {}}),
    (MaterialCapture, {'kind': 'timeline', 'ref': 'area:prg:14', 'query': {}}),
    (MaterialCapture, {'kind': 'object', 'ref': 'area:prg:14', 'query': {}, 'data_revision': 'abc'}),
    (MaterialCapture, {'kind': 'object', 'ref': 'area:prg:14', 'query': {}, 'cursor_at': '2026-10-23T12:00:00'}),
    (MaterialCapture, {'kind': 'object', 'ref': 'area:prg:14', 'query': {}, 'version_id': 1}),
    (MaterialCapture, {'kind': 'object', 'ref': 'area:prg:14', 'query': {}, 'sensor_id': '123'}),
    (MaterialCapture, {'kind': 'comparison', 'query': {}}),
])
def test_invalid_or_client_supplied_evidence_is_rejected(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_migration_19_preserves_old_objects_views_watchlist_and_source_history(tmp_path):
    path = tmp_path/'upgrade.sqlite'
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    db = sqlite3.connect(path)
    for migration in migrations[:18]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=18')
    db.execute("INSERT INTO app_state VALUES('marker','preserved')")
    db.execute("INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text) VALUES('aircraft:icao:abc123','aircraft','aircraft','abc123','LOT','lot')")
    db.execute("INSERT INTO workspace_watchlist VALUES('aircraft:icao:abc123','2026-10-23')")
    db.execute("INSERT INTO workspace_views VALUES('v','Widok',1,'{}',1,'2026-10-23','2026-10-23')")
    tables = ['app_state', 'catalog_objects', 'workspace_watchlist', 'workspace_views']
    before = {name: db.execute(f'SELECT * FROM {name}').fetchall() for name in tables}
    db.commit()
    db.close()
    for _ in range(2):
        db = connect(path)
        assert {name: [tuple(row) for row in db.execute(f'SELECT * FROM {name}')] for name in tables} == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA user_version').fetchone()[0] == len(migrations)
        assert db.execute('SELECT count(*) FROM workspace_dossiers').fetchone()[0] == 0
        db.close()


def test_api_optimistic_mutations_unknown_parent_and_capture_roundtrip(workspace):
    app = FastAPI()
    app.state.workspace = workspace
    app.include_router(create_workspace_router())
    with TestClient(app) as client:
        did = client.post('/api/workspace/dossiers', json={'name': 'API'}).json()['id']
        base = '/api/workspace/dossiers/'+did
        assert client.get('/api/workspace/dossiers').json()['items'][0]['id'] == did
        assert client.post(base+'/pins', json={'ref': 'area:prg:14'}).status_code == 201
        note = client.post(base+'/notes', json={'body': 'Notatka'}).json()
        assert client.put(base+'/notes/'+note['id'], json={'body': 'Inna', 'revision': 99}).status_code == 409
        assert client.delete(base+'/notes/'+note['id']).status_code == 422
        assert client.delete(base+'/notes/'+note['id'], params={'revision': 1}).status_code == 200
        response = client.post(base+'/materials', json={'kind': 'object', 'ref': 'area:prg:14', 'query': {'types': ['area']}})
        assert response.status_code == 201, response.text
        material = response.json()
        assert client.get(base+'/materials/'+material['id']).json() == material
        assert client.put(base+'/materials/'+material['id'], json={}).status_code == 405
        assert client.get('/api/workspace/dossiers/missing').status_code == 404
        assert client.delete(base, params={'revision': 1}).status_code == 409
        revision = client.get(base).json()['revision']
        assert client.delete(base, params={'revision': revision}).status_code == 200
        assert client.get(base+'/materials/'+material['id']).status_code == 404
        assert client.get('/api/workspace/dossiers').json()['items'] == []
        assert workspace.catalog.object('area:prg:14') is not None


def test_all_new_mutations_use_existing_csrf_and_origin_guard(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        csrf = client.get('/api/health').json()['csrf_token']
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': csrf}
        response = client.post('/api/workspace/dossiers', json={'name': 'Chroniona'}, headers=headers)
        assert response.status_code == 201
        did = response.json()['id']
        base = '/api/workspace/dossiers/'+did
        routes = [
            ('POST', '/api/workspace/dossiers', {'name': 'Bez CSRF'}),
            ('PUT', base, {'name': 'Zmiana', 'revision': 1}),
            ('DELETE', base+'?revision=1', None),
            ('POST', base+'/pins', {'ref': 'area:prg:14'}),
            ('DELETE', base+'/pins/area:prg:14', None),
            ('POST', base+'/notes', {'body': 'Notatka'}),
            ('PUT', base+'/notes/missing', {'body': 'Notatka', 'revision': 1}),
            ('DELETE', base+'/notes/missing?revision=1', None),
            ('POST', base+'/materials', {'kind': 'object', 'ref': 'area:prg:14', 'query': {}}),
            ('DELETE', base+'/materials/missing', None),
        ]
        for method, route, payload in routes:
            assert client.request(method, route, json=payload).status_code == 403
            assert client.request(method, route, json=payload,
                headers={'Origin': 'https://evil.example', 'X-CSRF-Token': csrf}).status_code == 403
        assert client.get(base).json()['revision'] == 1


def test_station_corrections_and_captured_cursor_do_not_collapse_revisions(workspace):
    ref = station(workspace)
    samples(workspace, ref, 1)
    at = (NOW-timedelta(minutes=1)).isoformat()
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('UPDATE station_measurements SET is_current=0 WHERE object_ref=?', (ref,))
        workspace.db.execute('''INSERT INTO station_measurements(object_ref,sensor_id,metric,observed_key,
            observed_at,source_time,value,unit,fetched_at,first_fetched_at,revision,quality,content_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ref, 'pm-1', 'PM10', at, at, at, 0, 'µg/m³', NOW.isoformat(), NOW.isoformat(), 2, 'valid', 'corrected'))
    did = dossier(workspace)
    saved = workspace.dossiers.capture(did, selector(workspace, ref, 'timeline', cursor_at=at,
                                                    sensor_id='pm-1', metric='PM10'))
    rows = saved['snapshot']['timeline']['items']
    assert [(row['revision'], row['value']) for row in rows] == [(1, None), (2, 0)]
    assert saved['snapshot']['objects'][0]['selected_measurement']['value'] == 0
    assert saved['snapshot']['objects'][0]['selected_measurement']['revision'] == 2
    earlier = workspace.dossiers.capture(did, selector(workspace, ref, 'timeline',
        cursor_at=(NOW-timedelta(minutes=2)).isoformat(), sensor_id='pm-1', metric='PM10'))
    assert earlier['snapshot']['objects'][0]['selected_measurement'] is None
    assert earlier['snapshot']['timeline']['total'] == 2  # selected interval, not a cursor cutoff


def test_dossier_and_child_limits_and_cascade_do_not_delete_source_or_other_work(workspace, monkeypatch):
    import wici.workspace_dossiers as module
    first, second = dossier(workspace), dossier(workspace, 'Druga')
    ref, _ = notice(workspace)
    workspace.dossiers.pin(first, {'ref': ref})
    workspace.dossiers.save_note(first, {'body': 'Pierwsza'})
    selected = selector(workspace, ref)
    workspace.dossiers.capture(first, selected)
    other = workspace.dossiers.capture(second, selected)
    monkeypatch.setattr(module, 'MAX_DOSSIERS', 2)
    monkeypatch.setattr(module, 'MAX_PINS', 1)
    monkeypatch.setattr(module, 'MAX_NOTES', 1)
    monkeypatch.setattr(module, 'MAX_MATERIALS', 1)
    with pytest.raises(ValueError, match='limit'):
        dossier(workspace, 'Trzecia')
    with pytest.raises(ValueError, match='limit'):
        workspace.dossiers.pin(first, {'ref': 'area:prg:14'})
    with pytest.raises(ValueError, match='limit'):
        workspace.dossiers.save_note(first, {'body': 'Druga'})
    with pytest.raises(ValueError, match='limit'):
        workspace.dossiers.capture(first, selected)
    workspace.dossiers.delete(first, workspace.dossiers.detail(first)['revision'])
    for table in ('pins', 'notes', 'materials'):
        assert workspace.db.execute(f'SELECT count(*) FROM workspace_dossier_{table} WHERE dossier_id=?', (first,)).fetchone()[0] == 0
    assert workspace.catalog.object(ref) is not None
    assert workspace.dossiers.material(second, other['id']) == other
    assert workspace.db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_missing_object_and_wrong_document_version_leave_no_partial_material(workspace):
    ref, _ = notice(workspace)
    did = dossier(workspace)
    with pytest.raises(KeyError):
        workspace.dossiers.capture(did, selector(workspace, ref, version_id=999999))
    with pytest.raises(KeyError):
        workspace.dossiers.capture(did, {'kind': 'object', 'ref': 'aircraft:icao:ffffff',
                                        'query': {'types': ['aircraft']}})
    assert workspace.dossiers.detail(did)['revision'] == 1
    assert workspace.dossiers.detail(did)['materials'] == []


def test_selected_old_document_keeps_its_own_date_only_and_source_fields(workspace):
    raw = document('rso', 'date-only', 'https://example.org/dates', 'Pierwsza data', 'Dawna treść',
                   {'locations': [location('14', 'notification_area', 'RSO')]}, [])
    raw['fields'].update(source_published_date='2026-10-20', source_specific_note='Dawna informacja źródłowa')
    result = workspace.repo.ingest(raw)
    workspace.catalog.backfill()
    ref = f"communication:{result['document_id']}"
    version_id = workspace.detail(ref)['versions'][0]['id']
    raw['fields']['source_published_date'] = '2026-10-23'
    raw['fields']['source_specific_note'] = 'Zmieniona informacja źródłowa'
    raw['text'] = 'Nowsza treść'
    workspace.repo.ingest(raw)
    workspace.catalog.backfill()
    did = dossier(workspace)
    saved = workspace.dossiers.capture(did, selector(workspace, ref, version_id=version_id))
    detail = saved['snapshot']['objects'][0]
    assert detail['selected_version']['source_published_at'] is None
    assert detail['selected_version']['source_published_date'] == '2026-10-20'
    assert detail['selected_version']['date_precision'] == 'day'
    assert detail['selected_version']['fields']['source_specific_note'] == 'Dawna informacja źródłowa'
    assert detail['communication']['source_published_date'] == '2026-10-23'
    assert detail['selected_version']['text'] == 'Dawna treść'
    assert detail['communication']['text'] == 'Nowsza treść'
