"""Typed relationships, bounded graph fragments and durable analyst provenance."""
import copy
import hashlib
import sqlite3
from datetime import timedelta
from pathlib import Path
from time import perf_counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_workspace_dossiers import NOW, ORIGIN, dossier, notice, station
from test_workspace_moving import snapshot, track

from wici.app import create_app
from wici.db import connect
from wici.dossier_models import MaterialCapture
from wici.relation_models import AnalystRelation, GraphNeighbors, GraphQuery, WorkingGraph
from wici.repository import Repository
from wici.workspace_api import create_workspace_router
from wici.workspace_repository import encode
from wici.workspace_service import QueryChanged, WorkspaceService


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'graph.sqlite', clock=lambda: NOW)
    result = WorkspaceService(repo)
    yield result
    repo.close()


def graph(workspace, refs, **kwargs):
    return workspace.relations.query({'seed_refs': refs[:20], 'node_refs': refs, **kwargs})


def relation(workspace, did, left='area:prg:14', right='area:prg:12', **kwargs):
    return workspace.relations.save_relation(did, dict(source_ref=left, target_ref=right,
        justification='Własna interpretacja analityka', **kwargs))


def range_time():
    return {'mode': 'range', 'filter_range': {'from': (NOW-timedelta(hours=2)).isoformat(), 'to': NOW.isoformat()}}


def test_station_area_publisher_role_hierarchy_and_explicit_fragment(workspace):
    ref = station(workspace)
    comm, _ = notice(workspace)
    result = graph(workspace, [ref, comm, 'area:prg:14', 'area:prg:1465'])
    by_type = {edge['type']: edge for edge in result['edges']}
    assert by_type['communication_area']['category'] == 'source'
    assert by_type['communication_area']['label'] == 'Obszar powiadomienia'
    assert by_type['communication_area']['provenance']['source_url'] == 'https://example.org/source'
    assert by_type['station_area']['category'] == 'derived'
    assert by_type['station_area']['provenance']['method'] == 'point_in_prg'
    assert by_type['administrative_parent']['target_ref'] == 'area:prg:14'
    assert result['partial'] is True
    assert result['neighbor_counts']['area:prg:14']['remaining'] > 0
    assert not any(edge['source_ref'] == edge['target_ref'] for edge in result['edges'])
    # The graph is deliberately independent of the catalogue's station-only filter.
    assert {n['type'] for n in result['nodes']} == {'communication', 'hydro_station', 'area'}


def test_station_source_area_is_not_mislabeled_as_derived(workspace):
    ref = station(workspace)
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station(ref, 'imgw', 'abc', 'Stacja', 52.2, 21, {'province': '14'})
    edge = graph(workspace, [ref, 'area:prg:14'])['edges'][0]
    assert edge['category'] == 'source'
    assert edge['provenance']['method'] == 'source_administrative_code'


def test_neighbors_paginate_exactly_and_categories_filter_before_display(workspace):
    for index in range(57):
        with workspace.repo.lock, workspace.db:
            workspace.catalog.upsert_station(f'hydro_station:imgw:n{index}', 'imgw', f'n{index}',
                                             f'Stacja {index}', 52, 21, {'province': '14'})
    result = graph(workspace, ['area:prg:14'], relation_types=['station_area'], categories=['source'])
    request = {'graph': result['selector'], 'ref': 'area:prg:14'}
    page1 = workspace.relations.neighbors(request)
    page2 = workspace.relations.neighbors(dict(request, cursor=page1['next_cursor']))
    assert page1['total'] == page2['total'] == 57
    assert len(page1['items']) == 50 and len(page2['items']) == 7
    assert page2['next_cursor'] is None
    assert len({item['node']['ref'] for item in page1['items']+page2['items']}) == 57
    assert page1['revision'] == page2['revision'] == result['revision']
    expanded = workspace.relations.query(dict(result['selector'],
        node_refs=['area:prg:14']+[item['node']['ref'] for item in page1['items']], expanded_refs=['area:prg:14']))
    continued = workspace.relations.neighbors({'graph': expanded['selector'], 'ref': 'area:prg:14', 'cursor': page1['next_cursor']})
    assert continued['items'] == page2['items']
    altered = copy.deepcopy(request)
    altered['graph']['categories'] = ['derived']
    with pytest.raises(QueryChanged):
        workspace.relations.neighbors(dict(altered, cursor=page1['next_cursor']))


def test_graph_revision_allows_expansion_but_guards_unrelated_catalog_filter_nodes(workspace):
    ref = station(workspace)
    initial = graph(workspace, [ref])
    expanded = dict(initial['selector'], node_refs=[ref, 'area:prg:14'])
    assert workspace.relations.query(expanded)['revision'] == initial['revision']
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station(ref, 'imgw', 'abc', 'Zmieniona stacja', 52, 21, {'province': '14'})
    with pytest.raises(QueryChanged):
        workspace.relations.query(expanded)


def test_selected_document_version_has_own_areas_text_and_provenance(workspace):
    ref, raw = notice(workspace)
    first = workspace.catalog.object(ref)['document_version_id']
    raw['fields']['event']['locations'][0]['admin_code'] = '12'
    raw['text'] = 'Nowa wersja w innym obszarze'
    workspace.repo.ingest(raw)
    workspace.catalog.backfill()
    latest = graph(workspace, [ref, 'area:prg:14', 'area:prg:12'])
    assert next(edge for edge in latest['edges'] if edge['type'] == 'communication_area')['target_ref'] == 'area:prg:12'
    old = graph(workspace, [ref, 'area:prg:14', 'area:prg:12'], version_ids={ref: first})
    edge = next(edge for edge in old['edges'] if edge['type'] == 'communication_area')
    assert edge['target_ref'] == 'area:prg:14'
    assert edge['provenance']['document_version_id'] == first
    node = next(node for node in old['nodes'] if node['ref'] == ref)
    assert node['communication']['text'] == 'Pierwsza treść'
    assert node['metadata_context'] == 'selected_document_version'
    assert [area['admin_code'] for area in node['areas']] == ['14']


@pytest.mark.parametrize('kind,native_id', [('aircraft', 'abc123'), ('ship', '261000001')])
def test_live_reported_point_requires_fresh_source_and_keeps_observation_time(workspace, kind, native_id):
    ref, feed = snapshot(workspace, kind, native_id, latitude=52.2, longitude=21)
    result = graph(workspace, [ref, 'area:prg:14'])
    edge = next(edge for edge in result['edges'] if edge['type'] == 'reported_in_area')
    assert edge['category'] == 'derived'
    assert edge['time']['kind'] == 'observation' and edge['time']['observed_at'] == NOW.isoformat()
    workspace.moving.ingest(kind, dict(feed, stale=True))
    assert graph(workspace, [ref, 'area:prg:14'])['edges'] == []


@pytest.mark.parametrize('kind,native_id', [('aircraft', 'abc123'), ('ship', '261000001')])
def test_recorded_transport_area_uses_cursor_without_bridging_gaps_or_live_position(workspace, kind, native_id):
    ref, _ = snapshot(workspace, kind, native_id, latitude=50.06, longitude=19.94)
    start = NOW-timedelta(hours=1)
    track(workspace, ref, points=[(start, 52.2, 21, True), (start+timedelta(minutes=1), 52.3, 21, False)])
    result = graph(workspace, [ref, 'area:prg:14', 'area:prg:12'], time=range_time(), cursor_at=(start+timedelta(minutes=1)).isoformat())
    edge = next(edge for edge in result['edges'] if edge['type'] == 'reported_in_area')
    assert edge['target_ref'] == 'area:prg:14'
    assert edge['provenance']['track_id'] == 'session-1'
    gap = graph(workspace, [ref, 'area:prg:14'], time=range_time(), cursor_at=(start+timedelta(minutes=30)).isoformat())
    assert gap['edges'] == []
    assert next(node for node in gap['nodes'] if node['ref'] == ref)['position'] is None


def test_ukraine_region_hierarchy_alarm_time_and_uncertainty(workspace):
    from test_workspace_ukraine import OBLAST, RAION, feature, range_query, recorded
    workspace.ukraine.register_geometry({'fetched_at': NOW.isoformat(), 'oblasts': {'features': [
        feature('київська область', 'Київська область')]}, 'raions': {'features': [
        feature('бучанський', 'Бучанський район', raion=True, oblast='київська область')]}})
    recorded(workspace)
    alarm = workspace.db.execute('SELECT ref FROM workspace_ukraine_episodes LIMIT 1').fetchone()[0]
    time = range_query(0, 120)['time']
    result = graph(workspace, [alarm, RAION, OBLAST], time=time)
    edges = {edge['type']: edge for edge in result['edges']}
    assert edges['region_parent']['provenance']['basis'] == 'source_oblast_key'
    assert edges['alert_region']['target_ref'] in (RAION, OBLAST)
    assert edges['alert_region']['time']['ended_before'] is not None
    assert edges['alert_region']['time']['ended_after'] is not None
    assert next(node for node in result['nodes'] if node['ref'] == RAION)['geometry_context'] == 'current'


def test_analyst_relations_are_symmetric_scoped_versioned_and_keep_deleted_evidence(workspace):
    first, second = dossier(workspace), dossier(workspace, 'Inna')
    note = workspace.dossiers.save_note(first, {'body': 'Moja hipoteza, nie fakt źródłowy'})
    edge = relation(workspace, first, note_id=note['id'])
    with pytest.raises(ValueError, match='już relację'):
        relation(workspace, first, left=edge['target_ref'], right=edge['source_ref'])
    assert graph(workspace, ['area:prg:14', 'area:prg:12'], dossier_id=second)['edges'] == []
    displayed = graph(workspace, ['area:prg:14', 'area:prg:12'], dossier_id=first)['edges'][0]
    assert displayed['category'] == 'analyst' and displayed['directed'] is False
    assert displayed['provenance']['evidence']['note_id']['body'] == note['body']
    workspace.dossiers.save_note(first, {'body': 'Zmieniona podstawa', 'revision': 1}, note['id'])
    changed = workspace.relations.save_relation(first, {'source_ref': 'area:prg:14', 'target_ref': 'area:prg:12',
        'justification': 'Poprawione uzasadnienie', 'revision': 1, 'note_id': note['id']}, edge['id'])
    with pytest.raises(QueryChanged):
        workspace.relations.delete_relation(first, edge['id'], 1)
    workspace.dossiers.delete_note(first, note['id'], 2)
    assert workspace.relations.relations(first)['items'][0]['evidence_missing'] == ['note_id']
    workspace.relations.delete_relation(first, edge['id'], changed['revision'])
    assert workspace.relations.relations(first)['items'] == []
    assert workspace.relations.relations(first, include_deleted=True)['items'][0]['deleted'] is True
    assert graph(workspace, ['area:prg:14', 'area:prg:12'], dossier_id=first)['edges'] == []
    assert [r['action'] for r in workspace.relations.relation_history(first, edge['id'])['items']] == ['create', 'update', 'delete']
    audit = workspace.relations.relation_history(first, edge['id'])['items']
    assert audit[0]['payload']['evidence']['note_id']['body'] == note['body']
    assert audit[0]['payload']['evidence']['note_id']['revision'] == 1
    assert audit[1]['payload']['evidence']['note_id']['body'] == 'Zmieniona podstawa'
    with pytest.raises(KeyError):
        workspace.relations.relation_history(second, edge['id'])


def test_evidence_must_belong_to_relation_dossier(workspace):
    first, second = dossier(workspace), dossier(workspace, 'Inna')
    note = workspace.dossiers.save_note(first, {'body': 'Dowód'})
    with pytest.raises(ValueError, match='tej teczki'):
        relation(workspace, second, note_id=note['id'])


def test_orphaned_manual_endpoints_restore_labels_and_can_be_edited(workspace):
    ref, _ = snapshot(workspace)
    did = dossier(workspace)
    edge = relation(workspace, did, left=ref)
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM catalog_objects WHERE ref=?', (ref,))
    result = graph(workspace, [ref, 'area:prg:12'], dossier_id=did)
    assert next(n for n in result['nodes'] if n['ref'] == ref)['available'] is False
    assert next(n for n in result['nodes'] if n['ref'] == ref)['label'] == 'LOT123'
    assert result['edges'][0]['id'] == edge['id']
    updated = workspace.relations.save_relation(did, {'source_ref': edge['source_ref'], 'target_ref': edge['target_ref'],
        'justification': 'Obiekt wygasł', 'revision': 1}, edge['id'])
    assert updated['revision'] == 2


def test_working_graph_optimistic_restore_keeps_layout_without_stale_read_token(workspace):
    did = dossier(workspace)
    selected = graph(workspace, ['area:prg:14'], dossier_id=did)
    body = {'graph': selected['selector'], 'positions': {'area:prg:14': {'x': 12, 'y': -5}},
            'hidden_refs': ['area:prg:14'], 'layout': 'concentric', 'node_type': 'area', 'revision': 0}
    saved = workspace.relations.save_graph(did, body)
    assert saved['revision'] == 1 and saved['layout'] == 'concentric'
    assert saved['graph']['expected_revision'] is saved['graph']['as_of'] is None
    with pytest.raises(QueryChanged):
        workspace.relations.save_graph(did, body)
    restored = workspace.relations.working_graph(did)
    assert restored['positions'] == body['positions']
    assert restored['node_type'] == 'area'
    assert graph(workspace, ['area:prg:14'], dossier_id=did)['revision'] == selected['revision']


def test_graph_copy_server_rebuild_hash_and_restart_survive_source_retention(tmp_path):
    path = tmp_path/'durable.sqlite'
    repo = Repository(path, clock=lambda: NOW)
    workspace = WorkspaceService(repo)
    ref, _ = snapshot(workspace)
    did = dossier(workspace)
    relation(workspace, did, left=ref)
    selected = graph(workspace, [ref, 'area:prg:12', 'area:prg:14'], dossier_id=did)
    body = {'kind': 'graph', 'graph': selected['selector'], 'positions': {ref: {'x': 1, 'y': 2}},
            'hidden_refs': ['area:prg:14'], 'layout': 'concentric', 'node_type': 'aircraft', 'title': 'Dawny graf'}
    saved = workspace.dossiers.capture(did, body)
    assert saved['snapshot']['schema_version'] == 2
    assert saved['snapshot']['graph']['edges'] == selected['edges']
    assert saved['snapshot']['graph']['hidden_refs'] == ['area:prg:14']
    assert saved['snapshot']['graph']['node_type'] == 'aircraft'
    assert saved['snapshot']['graph']['partial'] is True
    assert hashlib.sha256(encode(saved['snapshot']).encode()).hexdigest() == saved['sha256']
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('DELETE FROM catalog_objects WHERE ref=?', (ref,))
    assert workspace.dossiers.material(did, saved['id']) == saved
    repo.close()
    repo = Repository(path, clock=lambda: NOW+timedelta(days=40))
    workspace = WorkspaceService(repo)
    assert workspace.dossiers.material(did, saved['id']) == saved
    repo.close()


def test_graph_capture_rejects_stale_revision_foreign_case_and_oversize_atomically(workspace, monkeypatch):
    import wici.workspace_dossiers as module
    did, other = dossier(workspace), dossier(workspace, 'Druga')
    selected = graph(workspace, ['area:prg:14', 'area:prg:12'], dossier_id=did)
    body = {'kind': 'graph', 'graph': selected['selector']}
    with pytest.raises(ValueError, match='tej teczki'):
        workspace.dossiers.capture(other, body)
    relation(workspace, did)
    with pytest.raises(QueryChanged):
        workspace.dossiers.capture(did, body)
    body['graph'] = graph(workspace, ['area:prg:14', 'area:prg:12'], dossier_id=did)['selector']
    monkeypatch.setattr(module, 'MAX_MATERIAL_BYTES', 1)
    with pytest.raises(ValueError, match='5 MiB'):
        workspace.dossiers.capture(did, body)
    assert workspace.dossiers.detail(did)['materials'] == []


@pytest.mark.parametrize('model,body', [
    (GraphQuery, {'seed_refs': ['area:prg:14']*2}),
    (GraphQuery, {'seed_refs': ['area:prg:14'], 'node_refs': ['area:prg:12']}),
    (GraphQuery, {'seed_refs': ['area:prg:14'], 'expected_revision': 'invalid'}),
    (GraphQuery, {'seed_refs': ['area:prg:14'], 'version_ids': {'area:prg:14': 1}}),
    (GraphQuery, {'seed_refs': ['area:prg:14'], 'cursor_at': NOW.isoformat()}),
    (GraphNeighbors, {'graph': {'seed_refs': ['area:prg:14']}, 'ref': 'area:prg:12'}),
    (AnalystRelation, {'source_ref': 'area:prg:14', 'target_ref': 'area:prg:14', 'justification': 'Teza'}),
    (AnalystRelation, {'source_ref': 'area:prg:14', 'target_ref': 'area:prg:12', 'justification': ' '}),
    (WorkingGraph, {'graph': {'seed_refs': ['area:prg:14']}, 'positions': {'area:prg:14': {'x': float('nan'), 'y': 2}}}),
    (MaterialCapture, {'kind': 'graph', 'graph': {'seed_refs': ['area:prg:14']}}),
    (MaterialCapture, {'kind': 'object', 'ref': 'area:prg:14', 'query': {}, 'graph': {}}),
])
def test_invalid_or_client_forged_graph_inputs(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)


def test_migration20_keeps_all_old_material_bytes_hashes_and_immutable_trigger(tmp_path):
    path = tmp_path/'upgrade.sqlite'
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    db = sqlite3.connect(path)
    for migration in migrations[:19]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=19')
    db.execute("INSERT INTO workspace_dossiers VALUES('d','Stara teczka','Opis',3,'a','b')")
    payload = '{ "żółć": [1, null], "schema_version":1 }'
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.execute('INSERT INTO workspace_dossier_materials VALUES(?,?,?,?,?,?,?,?,?)',
               ('m', 'd', 'Stary materiał', 'object', 'area:prg:14', 'a', digest, len(payload.encode()), payload))
    db.execute("INSERT INTO workspace_dossier_notes VALUES('n','d','Notatka',2,'a','b')")
    db.execute("INSERT INTO workspace_dossier_pins VALUES('d','area:prg:14','Obszar','area','prg','a')")
    tables = ['workspace_dossiers', 'workspace_dossier_materials', 'workspace_dossier_notes', 'workspace_dossier_pins']
    before = {name: db.execute(f'SELECT * FROM {name}').fetchall() for name in tables}
    db.commit()
    db.close()
    for _ in range(2):
        db = connect(path)
        assert {name: [tuple(row) for row in db.execute(f'SELECT * FROM {name}')] for name in tables} == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            db.execute("UPDATE workspace_dossier_materials SET snapshot_json='{}' WHERE id='m'")
        db.rollback()
        db.close()


def test_api_routes_mutation_revisions_and_graph_capture(workspace):
    app = FastAPI()
    app.state.workspace = workspace
    app.include_router(create_workspace_router())
    with TestClient(app) as client:
        did = client.post('/api/workspace/dossiers', json={'name': 'Graf'}).json()['id']
        base = f'/api/workspace/dossiers/{did}'
        created = client.post(base+'/relations', json={'source_ref': 'area:prg:14', 'target_ref': 'area:prg:12', 'justification': 'Hipoteza'})
        assert created.status_code == 201, created.text
        rid = created.json()['id']
        assert client.get(base+'/relations').json()['items'][0]['id'] == rid
        assert client.delete(base+'/relations/'+rid+'?revision=99').status_code == 409
        response = client.post('/api/workspace/graph/query', json={'seed_refs': ['area:prg:14'], 'node_refs': ['area:prg:14', 'area:prg:12'], 'dossier_id': did})
        assert response.status_code == 200, response.text
        selected = response.json()
        saved = client.post(base+'/materials', json={'kind': 'graph', 'graph': selected['selector']})
        assert saved.status_code == 201, saved.text
        assert saved.json()['snapshot']['graph']['edges'][0]['category'] == 'analyst'
        assert client.get(base+'/graph').status_code == 404
        assert client.put(base+'/graph', json={'graph': selected['selector'], 'revision': 0}).status_code == 200
        assert client.get(base+'/relations/'+rid+'/history').json()['items'][0]['action'] == 'create'
        assert client.delete(base+'/relations/'+rid+'?revision=1').status_code == 200
        assert client.get(base+'/relations').json()['items'] == []
        assert client.get(base+'/relations?include_deleted=true').json()['items'][0]['deleted'] is True


def test_high_degree_graph_reads_area_links_in_batches_with_bounded_sql(workspace):
    for index in range(1200):
        with workspace.repo.lock, workspace.db:
            workspace.catalog.upsert_station(f'hydro_station:imgw:p{index}', 'imgw', f'p{index}',
                                             f'Stacja {index}', 52, 21, {'province': '14'})
    graph(workspace, ['area:prg:14'], relation_types=['station_area'])
    statements = []
    workspace.db.set_trace_callback(statements.append)
    started = perf_counter()
    try:
        result = graph(workspace, ['area:prg:14']+[f'hydro_station:imgw:p{i}' for i in range(199)], relation_types=['station_area'])
    finally:
        workspace.db.set_trace_callback(None)
    elapsed = perf_counter()-started
    assert len(result['nodes']) == 200 and len(result['edges']) == 199
    assert result['neighbor_counts']['area:prg:14']['total'] == 1200
    assert len(statements) < 1250, len(statements)
    assert elapsed < 2, elapsed


def test_filtered_hierarchy_does_not_scan_irrelevant_transport_candidates(workspace):
    with workspace.repo.lock, workspace.db:
        workspace.db.executemany('''INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text)
            VALUES(?,'ship','ships',?,'Statek','statek')''',
            [(f'ship:mmsi:{261000000+i}', str(261000000+i)) for i in range(5100)])
    result = graph(workspace, ['area:prg:14'], relation_types=['administrative_parent'], categories=['source'])
    assert result['neighbor_counts']['area:prg:14']['total'] == 42
    assert all(item['node']['type'] == 'area' for item in workspace.relations.neighbors(
        {'graph': result['selector'], 'ref': 'area:prg:14'})['items'])


def test_new_graph_and_relation_mutations_use_csrf_and_origin_guard(tmp_path):
    app = create_app(demo=True, root=tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        token = client.get('/api/health').json()['csrf_token']
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': token}
        did = client.post('/api/workspace/dossiers', json={'name': 'Chroniona'}, headers=headers).json()['id']
        base = f'/api/workspace/dossiers/{did}'
        routes = [('POST', '/api/workspace/graph/query', {'seed_refs': ['area:prg:14']}),
                  ('POST', '/api/workspace/graph/neighbors', {'graph': {'seed_refs': ['area:prg:14']}, 'ref': 'area:prg:14'}),
                  ('POST', base+'/relations', {}), ('PUT', base+'/relations/x', {}),
                  ('DELETE', base+'/relations/x?revision=1', None), ('PUT', base+'/graph', {})]
        for method, route, body in routes:
            assert client.request(method, route, json=body).status_code == 403
            assert client.request(method, route, json=body, headers={'Origin': 'https://evil.example', 'X-CSRF-Token': token}).status_code == 403
