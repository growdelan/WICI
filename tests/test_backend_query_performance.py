"""Query optimizations retain complete results and bounded SQL fan-out."""
import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from wici.repository import Repository
from wici.sources.normalize import document, location
from wici.workspace_models import WorkspaceQuery
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'queries.sqlite3', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


@pytest.mark.parametrize('mode', ['live', 'range'])
def test_station_map_batches_preserve_corrections_nulls_sensors_and_half_open_window(workspace, mode):
    repo = workspace.repo
    start, end = NOW-timedelta(hours=2), NOW-timedelta(hours=1)
    refs = []
    with repo.lock, repo.db:
        for number in range(520):
            hydro = number % 2 == 0
            source = 'imgw' if hydro else 'gios'
            ref = f'{"hydro" if hydro else "air_quality"}_station:{source}:{number}'
            refs.append(ref)
            workspace.catalog.upsert_station(ref, source, str(number), f'Stacja {number:04}',
                                             52.2, 21.0, {'province': '14'})
            metric = 'water_level' if hydro else 'PM10'
            sensor = '' if hydro else str(number)
            for instant, revision, value, quality in (
                (start, 1, 100, 'valid'), (start, 2, None, 'valid'),
                (end, 1, 200, 'valid'), (NOW+timedelta(hours=1), 1, 300, 'future'),
            ):
                at = instant.isoformat()
                repo.db.execute('''INSERT INTO station_measurements
                    (object_ref,sensor_id,metric,observed_key,observed_at,value,unit,fetched_at,
                     first_fetched_at,revision,quality,content_hash,is_current)
                    VALUES(?,?,?,?,?,?,'cm',?,?,?,?,?,?)''',
                    (ref, sensor, metric, at, at, value, NOW.isoformat(), NOW.isoformat(), revision,
                     quality, str(value), int(instant != start or revision == 2)))
            # A later secondary hydro metric must not replace the water level.
            if hydro:
                at = (end+timedelta(minutes=1)).isoformat()
                repo.db.execute('''INSERT INTO station_measurements
                    (object_ref,metric,observed_key,observed_at,value,fetched_at,first_fetched_at,
                     revision,quality,content_hash) VALUES(?,'temperature',?,?,9,?,?,1,'valid','temperature')''',
                    (ref, at, at, NOW.isoformat(), NOW.isoformat()))
            else:
                at = start.isoformat()
                repo.db.execute('''INSERT INTO station_index_observations
                    (object_ref,observed_key,observed_at,value,fetched_at,first_fetched_at,revision,
                     quality,content_hash) VALUES(?,?,?,2,?,?,1,'valid','index')''',
                    (ref, at, at, NOW.isoformat(), NOW.isoformat()))
        missing = 'hydro_station:imgw:missing'
        workspace.catalog.upsert_station(missing, 'imgw', 'missing', 'Brak pomiaru', None, None, {})
    query = {'types': ['hydro_station', 'air_quality_station'], 'page_size': 200}
    if mode == 'range':
        query['time'] = {'mode': mode, 'filter_range': {'from': start.isoformat(), 'to': end.isoformat()}}
    statements = []
    repo.db.set_trace_callback(statements.append)
    try:
        result = workspace.query(query)
    finally:
        repo.db.set_trace_callback(None)
    assert len(statements) < 50
    assert result['total'] == 521
    assert result['map']['located_total'] == 520
    assert len(result['map']['points']) == 520
    parsed = WorkspaceQuery.model_validate(query)
    interval, _ = workspace._ranges(parsed, NOW)
    for item in result['map']['points']:
        # The detail/individual presentation path is independent of batching.
        expected = workspace._present(workspace.catalog.object(item['ref']), NOW, interval, parsed)
        assert item == expected
        assert item['measurement']['value'] == (None if mode == 'range' else 200)
        assert item['measurement']['revision'] == (2 if mode == 'range' else 1)
        if item['type'] == 'air_quality_station':
            assert item['official_index']['value'] == 2
    page = {item['ref']: item for item in result['items']}
    assert all(page[item['ref']] == item for item in result['map']['points'] if item['ref'] in page)
    assert page[missing]['measurement'] is None


def make_notice(identity, *, source='rso', published=None, updated=None, published_date=None,
                start=None, end=None, text='Woda nadaje się do picia.', area='14'):
    value = document(source, identity, 'https://example.org/synthetic', identity, text,
                     {'locations': [location(area, 'notification_area', 'synthetic')],
                      'valid_from': start, 'valid_until': end}, [],
                     source_published_at=published, source_updated_at=updated)
    if published_date:
        value['fields']['source_published_date'] = published_date
    return value


def test_communication_prefilter_preserves_dst_date_precedence_updates_and_active_window(workspace):
    repo = workspace.repo
    notices = [
        make_notice('civil_day', published='2026-10-24T22:30:00Z'),
        make_notice('date_only', published_date='2026-10-25'),
        make_notice('updated', published='2026-10-20T10:00:00Z', updated='2026-10-25T10:00:00Z'),
        make_notice('fallback'),
        make_notice('precedence', published='2026-10-24T10:00:00Z', published_date='2026-10-25'),
        make_notice('active', published='2026-10-20T10:00:00Z',
                    start='2026-10-24T00:00:00Z', end='2026-10-26T00:00:00Z'),
        make_notice('ended', published='2026-10-20T10:00:00Z',
                    start='2026-10-24T00:00:00Z', end=NOW.isoformat()),
        make_notice('sg_old', source='sg', published='2026-10-20T10:00:00Z',
                    start='2026-10-24T00:00:00Z', end='2026-10-26T00:00:00Z'),
    ]
    for value in notices:
        repo.ingest(value)
    result = repo.list_communications({'date': '2026-10-25'})
    assert {item['title'] for item in result['items']} == {'civil_day', 'date_only', 'updated', 'fallback'}
    assert next(item for item in result['items'] if item['title'] == 'updated')['selection_basis'] == 'source_updated_at'
    active = repo.list_communications({'date': '2026-10-25', 'include_active': True})
    assert {item['title'] for item in active['items']} == {'civil_day', 'date_only', 'updated', 'fallback', 'active'}
    assert next(item for item in active['items'] if item['title'] == 'active')['selection_basis'] == 'display_window'
    assert repo.list_communications({'date': '2026-10-24', 'include_active': True})['total'] == 1


@pytest.mark.parametrize('filters', [
    {}, {'source_id': 'rso'}, {'category': 'weather'}, {'voivodeship': '14'},
    {'communication_type': 'exercise'}, {'date': '2026-10-25'},
    {'date': '2026-10-25', 'include_active': True},
])
def test_communication_limits_preserve_filtered_totals_order_and_boolean_admission(workspace, filters):
    repo = workspace.repo
    for number in range(12):
        value = make_notice(str(number), source='sg' if number % 4 == 0 else 'rso',
                            published='2026-10-24T22:30:00Z', area='14' if number % 2 else '02',
                            text='Ćwiczenia alarmowe.' if number % 3 == 0 else 'Burze i silny wiatr.')
        repo.ingest(value)
    for index, invalid in enumerate((False, 1, 'true', None)):
        value = make_notice(f'invalid-{index}', published='2026-10-24T22:30:00Z')
        value['fields']['contract_validated'] = invalid
        repo.ingest(value)
    full = repo.list_communications(filters, limit=100)
    expected = copy.deepcopy(full)
    for limit in (0, 1, 3):
        limited = repo.list_communications(filters, limit=limit)
        assert limited['total'] == expected['total']
        assert limited['items'] == expected['items'][:limit]
        assert limited['limited'] == (expected['total'] > limit)
        assert not any(item['title'].startswith('invalid') for item in limited['items'])
    assert json.dumps(full) == json.dumps(expected)


def test_custom_area_graph_batches_candidates_and_refreshes_geometry_changes(workspace):
    repo = workspace.repo
    with repo.lock, repo.db:
        for number in range(520):
            workspace.catalog.upsert_station(f'hydro_station:imgw:{number}', 'imgw', str(number),
                                             f'Stacja {number}', 52.2, 21.0, {'province': '14'})
    area = workspace.areas.save({'name': 'Obszar', 'shape': 'circle', 'center': [21, 52.2], 'radius_m': 1000})
    refs = [area['ref'], 'hydro_station:imgw:0', 'hydro_station:imgw:519']
    selector = {'seed_refs': refs, 'relation_types': ['custom_area_member']}
    statements = []
    repo.db.set_trace_callback(statements.append)
    try:
        result = workspace.relations.query(selector)
    finally:
        repo.db.set_trace_callback(None)
    assert len(statements) < 40
    assert result['neighbor_counts'][area['ref']] == {'total': 520, 'shown': 2, 'remaining': 518}
    assert len(result['edges']) == 2
    assert all(edge['type'] == 'custom_area_member' for edge in result['edges'])
    page = workspace.relations.neighbors({'graph': result['selector'], 'ref': area['ref'], 'limit': 50})
    assert page['total'] == 520 and len(page['items']) == 50
    with repo.lock, repo.db:
        workspace.catalog.upsert_station('hydro_station:imgw:519', 'imgw', '519', 'Przeniesiona stacja',
                                         50, 19, {'province': '12'})
    with pytest.raises(QueryChanged):
        workspace.relations.query(result['selector'])
    updated = workspace.relations.query(selector)
    assert updated['neighbor_counts'][area['ref']]['total'] == 519
    assert len(updated['edges']) == 1


def test_dossier_list_counts_and_order_do_not_need_per_dossier_queries(workspace):
    dossiers = workspace.dossiers
    values = [dossiers.save({'name': f'Teczka {number}'}) for number in range(50)]
    first, second = values[0]['id'], values[1]['id']
    dossiers.pin(first, {'ref': 'area:prg:14'})
    dossiers.pin(first, {'ref': 'area:prg:12'})
    dossiers.save_note(first, {'body': 'Notatka'})
    dossiers.save_note(second, {'body': 'Druga notatka'})
    expected = sorted((dossiers._summary(dossiers._row(value['id'])) for value in values), key=lambda item: item['id'])
    statements = []
    workspace.db.set_trace_callback(statements.append)
    try:
        result = dossiers.list()
    finally:
        workspace.db.set_trace_callback(None)
    assert len(statements) == 1
    assert result['items'] == expected
    dossiers.unpin(first, 'area:prg:14')
    refreshed = next(item for item in dossiers.list()['items'] if item['id'] == first)
    assert refreshed['pin_count'] == 1 and refreshed['note_count'] == 1 and refreshed['material_count'] == 0
