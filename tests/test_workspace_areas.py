"""Own geometry revisions, precise membership and integration with durable analysis."""
import copy
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from wici.area_models import AreaInput
from wici.repository import Repository
from wici.workspace_areas import EARTH_RADIUS, contains
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
POLYGON = {'type': 'Polygon', 'coordinates': [[[20, 51], [22, 51], [20, 53], [20, 51]]]}


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'areas.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def create(workspace, **kwargs):
    return workspace.areas.save(dict(name='Mój obszar', geometry=copy.deepcopy(POLYGON), **kwargs))


def writable(area):
    value = {key: area[key] for key in ('name', 'description', 'color', 'shape', 'revision', 'archived')}
    if area['shape'] == 'circle':
        value.update(center=area['center'], radius_m=area['radius_m'])
    else:
        value['geometry'] = area['geometry']
    return value


def test_precise_polygon_membership_concavity_and_boundary():
    area = {'shape': 'polygon', 'geometry': POLYGON}
    assert contains(area, 20.1, 51.1)
    assert contains(area, 21, 52)
    assert contains(area, 20, 52)
    assert not contains(area, 21.8, 52.8)  # In the bounding box, outside the triangle.
    assert not contains(area, None, None)
    assert not contains(area, math.nan, 52)
    assert not contains(area, 19.99, 52)


def test_circle_uses_great_circle_distance_and_includes_boundary(workspace):
    area = workspace.areas.save({'name': 'Koło', 'shape': 'circle', 'center': [21, 52], 'radius_m': 1000})
    assert contains(area, 21, 52)
    assert contains(area, 21, 52+math.degrees(1000/EARTH_RADIUS))
    assert not contains(area, 21.014, 52.008)  # A corner of the approximate bounding box.
    assert len(area['geometry']['coordinates'][0]) == 97
    assert area['geometry']['coordinates'][0][0] == area['geometry']['coordinates'][0][-1]


@pytest.mark.parametrize('changes', [
    {'name': '  '}, {'color': 'red'}, {'geometry': {'type': 'Polygon', 'coordinates': []}},
    {'geometry': {'type': 'Polygon', 'coordinates': [[[20, 51], [22, 53], [20, 53], [22, 51], [20, 51]]]}},
    {'geometry': {'type': 'Polygon', 'coordinates': [[[20, 51], [21, 52], [22, 53], [20, 51]]]}},
    {'geometry': {'type': 'Polygon', 'coordinates': [[[20, 51], [21, 52], [22, 51]]]}},
    {'shape': 'rectangle'}, {'center': [21, 52]},
    {'geometry': {'type': 'Polygon', 'coordinates': [[[20, 51], [181, 51], [20, 52], [20, 51]]]}},
])
def test_rejects_invalid_shapes(changes):
    with pytest.raises(ValidationError):
        AreaInput.model_validate(dict({'name': 'Test', 'geometry': POLYGON}, **changes))


def test_revisions_duplicate_archive_and_conflict_do_not_rewrite_old_geometry(workspace):
    area = create(workspace)
    second = workspace.areas.save(dict(writable(area), name='Drugi obszar',
        geometry={'type': 'Polygon', 'coordinates': [[[10, 50], [11, 50], [10, 51], [10, 50]]]}), area['id'])
    assert second['revision'] == 2
    assert workspace.areas.detail(area['id'], 1)['geometry'] == area['geometry']
    with pytest.raises(QueryChanged):
        workspace.areas.save(writable(area), area['id'])
    duplicate = workspace.areas.duplicate(second['id'])
    assert duplicate['id'] != second['id'] and duplicate['revision'] == 1
    archived = workspace.areas.save(dict(writable(second), archived=True), second['id'])
    assert archived['archived']
    assert len(workspace.areas.list()['items']) == 1
    assert len(workspace.areas.list(True)['items']) == 2
    with pytest.raises(sqlite3.IntegrityError), workspace.db:
        workspace.db.execute("UPDATE workspace_area_revisions SET name='Changed' WHERE id=?", (area['id'],))


def test_catalog_card_map_members_graph_and_dossier_pin(workspace):
    area = create(workspace)
    for identity, lat, lon in [('in', 51.1, 20.1), ('boxonly', 52.8, 21.8)]:
        with workspace.repo.lock, workspace.db:
            workspace.catalog.upsert_station('hydro_station:imgw:'+identity, 'imgw', identity, identity, lat, lon)
    result = workspace.query({'types': ['custom_area'], 'include_unlocated': False})
    assert result['total'] == 1 and result['map']['areas'][0]['geometry'] == area['geometry']
    assert result['items'][0]['ref'] == area['ref']
    assert workspace.detail(area['ref'])['custom_area']['name'] == area['name']
    assert [item['native_id'] for item in workspace.areas.members(area['id'])['items']] == ['in']
    refs = [area['ref'], 'hydro_station:imgw:in', 'hydro_station:imgw:boxonly']
    graph = workspace.relations.query({'seed_refs': refs, 'relation_types': ['custom_area_member']})
    assert len(graph['edges']) == 1
    edge = graph['edges'][0]
    assert edge['source_ref'] == 'hydro_station:imgw:in'
    assert edge['target_ref'] == area['ref']
    assert edge['provenance']['area_revision'] == 1 and edge['category'] == 'derived'
    neighbors = workspace.relations.neighbors({'graph': graph['selector'], 'ref': area['ref']})
    assert neighbors['total'] == 1
    dossier = workspace.dossiers.save({'name': 'Teczka'})
    workspace.dossiers.pin(dossier['id'], {'ref': area['ref']})
    assert workspace.dossiers.detail(dossier['id'])['pins'][0]['ref'] == area['ref']
    workspace.areas.save(dict(writable(area), archived=True), area['id'])
    assert workspace.query({'types': ['custom_area']})['total'] == 0
    assert workspace.detail(area['ref'])['custom_area']['archived']


def test_migration_from_v20_preserves_fk_children_and_immutable_material_bytes(tmp_path):
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    path = tmp_path/'old.sqlite'
    db = sqlite3.connect(path)
    for migration in migrations[:20]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=20')
    db.execute("INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text) VALUES('ua_region:neptun:oblast:1','ua_region','ukraine_alerts','1','A','a')")
    db.execute("INSERT INTO workspace_ukraine_regions(ref,scope,native_key,label,first_seen_at) VALUES('ua_region:neptun:oblast:1','oblast','1','A',?)", (NOW.isoformat(),))
    db.execute("INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text) VALUES('civil_alert:neptun:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','civil_alert','ukraine_alerts','a','Alert','alert')")
    db.execute("INSERT INTO workspace_ukraine_episodes(ref,region_ref,first_seen_at,last_seen_at,level) VALUES('civil_alert:neptun:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','ua_region:neptun:oblast:1',?,?,'red')", (NOW.isoformat(), NOW.isoformat()))
    db.execute("INSERT INTO workspace_ukraine_runs(id,observed_at,recorded_at,status) VALUES(1,?,?,'ready')", (NOW.isoformat(), NOW.isoformat()))
    db.execute("INSERT INTO workspace_ukraine_observations(run_id,region_ref,episode_ref,observed_at,state) VALUES(1,'ua_region:neptun:oblast:1','civil_alert:neptun:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',?,'red')", (NOW.isoformat(),))
    db.execute("INSERT INTO workspace_dossiers(id,name,created_at,updated_at) VALUES('d','D',?,?)", (NOW.isoformat(), NOW.isoformat()))
    db.execute("INSERT INTO workspace_dossier_materials VALUES('m','d','Old','object',NULL,?,'hash',11,'{ \"x\": 1 }')", (NOW.isoformat(),))
    tables = ['catalog_objects', 'workspace_ukraine_regions', 'workspace_ukraine_episodes', 'workspace_ukraine_observations', 'workspace_dossier_materials']
    before = {table: db.execute('SELECT * FROM '+table).fetchall() for table in tables}
    db.commit()
    db.close()
    repo = Repository(path, clock=lambda: NOW)
    try:
        assert {table: [tuple(row) for row in repo.db.execute('SELECT * FROM '+table)] for table in tables} == before
        assert not repo.db.execute('PRAGMA foreign_key_check').fetchall()
        assert repo.db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError), repo.db:
            repo.db.execute("UPDATE workspace_dossier_materials SET title='Changed'")
    finally:
        repo.close()


def test_area_api_revisions_edit_circle_archive_and_invalid_geometry(workspace):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from wici.workspace_api import create_workspace_router
    app = FastAPI()
    app.state.workspace = workspace
    app.include_router(create_workspace_router())
    with TestClient(app) as client:
        endpoint = '/api/workspace/areas'
        response = client.post(endpoint, json={'name': 'Obszar', 'shape': 'circle', 'center': [21, 52], 'radius_m': 1000})
        assert response.status_code == 201, response.text
        original = response.json()
        base = endpoint+'/'+original['id']
        response = client.put(base, json=dict(writable(original), radius_m=2000))
        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated['radius_m'] == 2000 and updated['revision'] == 2
        assert client.put(base, json=writable(original)).status_code == 409
        assert client.get(base+'?revision=1').json()['radius_m'] == 1000
        assert len(client.get(base+'/history').json()['items']) == 2
        assert client.get(base+'/members').json()['total'] == 0
        assert client.post(base+'/duplicate').status_code == 201
        assert client.put(base, json=dict(writable(updated), archived=True)).status_code == 200
        assert len(client.get(endpoint).json()['items']) == 1
        assert len(client.get(endpoint+'?include_archived=true').json()['items']) == 2
        assert client.post(endpoint, json={'name': 'Invalid', 'geometry': {}}).status_code == 422


@pytest.mark.parametrize('prefix', ['', 'custom_area:'])
def test_geometry_edit_checkpoints_pending_points_and_keeps_frozen_event_geometry(workspace, prefix):
    from datetime import timedelta

    from wici.workspace_monitor import append_observation
    area = create(workspace)
    rule = workspace.rules.save({'name': 'Wejścia', 'template': 'transport', 'enabled': True,
        'config': {'area_id': prefix+area['id'], 'object_ref': 'aircraft:icao:abc123', 'transition': 'both'}})
    def report(at, lon, lat):
        with workspace.repo.lock, workspace.db:
            append_observation(workspace.repo, 'transport', 'aircraft:icao:abc123', 'aircraft', at.isoformat(),
                str(at), {'longitude': lon, 'latitude': lat, 'object_type': 'aircraft'})
    report(NOW, 20.1, 51.1)
    workspace.monitor.process()
    event = workspace.events.list()['items'][0]
    original = workspace.events.detail(event['id'])
    assert original['evidence']['area']['revision'] == 1
    report(NOW+timedelta(seconds=1), 21.8, 52.8)  # Queued outside observation from old epoch.
    updated = workspace.areas.save(dict(writable(area), name='Granice po edycji'), area['id'])
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    workspace.monitor.process()
    assert workspace.events.list()['total'] == 1
    assert workspace.events.detail(event['id'])['evidence']['area']['geometry'] == area['geometry']
    report(NOW+timedelta(seconds=2), 20.2, 51.2)
    workspace.monitor.process()
    events = workspace.events.list()['items']
    assert len(events) == 2
    newest = next(e for e in events if e['id'] != event['id'])
    evidence = workspace.events.detail(newest['id'])['evidence']
    assert evidence['area']['revision'] == updated['revision'] == 2
    assert evidence['observation']['trigger'] == 'observed_inside'
