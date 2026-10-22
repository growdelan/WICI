import copy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from wici.geo import contains, provinces_for_point
from wici.repository import Repository
from wici.sources.normalize import document, location
from wici.workspace_models import SavedView, WorkspaceQuery
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'workspace.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def communication(workspace, identity='notice', published='2026-10-22T08:00:00Z', title='Żółć', areas=('14',)):
    value = document('rso', identity, 'https://example.org/source', title, 'Oficjalny komunikat',
                     {'locations': [location(a, 'notification_area', 'RSO') for a in areas]}, [],
                     source_published_at=published)
    result = workspace.repo.ingest(value)
    with workspace.repo.lock, workspace.db:
        workspace.catalog.project_document(result['document_id'])
    return f"communication:{result['document_id']}", value


def station(workspace, identity='1', label='Stacja', latitude=52.2, longitude=21.0):
    ref = 'hydro_station:imgw:'+identity
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station(ref, 'imgw', identity, label, latitude, longitude, {'province': '14'})
    return ref


def sample(workspace, ref, value=100, at='2026-10-22T08:00:00+00:00', revision=1, metric='water_level', sensor=''):
    with workspace.repo.lock, workspace.db:
        workspace.db.execute('UPDATE station_measurements SET is_current=0 WHERE object_ref=? AND sensor_id=? AND metric=? AND observed_key=?', (ref, sensor, metric, at))
        workspace.db.execute('''INSERT INTO station_measurements(object_ref,sensor_id,metric,observed_key,
            observed_at,source_time,value,unit,fetched_at,first_fetched_at,revision,quality,content_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ref, sensor, metric, at, at, at, value, 'cm', NOW.isoformat(), NOW.isoformat(), revision, 'valid', str(value)))
        workspace.db.execute('UPDATE catalog_objects SET revision=revision+1 WHERE ref=?', (ref,))


def test_backfill_idempotent_and_original_documents_not_duplicated(workspace):
    ref, value = communication(workspace)
    before = dict(workspace.db.execute('SELECT * FROM catalog_objects WHERE ref=?', (ref,)).fetchone())
    workspace.catalog.backfill()
    workspace.catalog.backfill()
    after = dict(workspace.db.execute('SELECT * FROM catalog_objects WHERE ref=?', (ref,)).fetchone())
    assert before == after
    assert workspace.db.execute('SELECT count(*) FROM document_versions').fetchone()[0] == 1
    value['fields']['access_allowed'] = False
    workspace.repo.ingest(value)
    workspace.catalog.backfill()
    assert workspace.catalog.object(ref) is None


def test_table_map_and_time_share_scope_but_map_ignores_paging(workspace):
    for number in range(5):
        communication(workspace, str(number), title=f'Komunikat {number}')
    result = workspace.query({'types': ['communication'], 'page_size': 2, 'province': '14'})
    assert result['total'] == 5
    assert len(result['items']) == 2
    assert len(result['map']['areas']) == 5
    assert result['timeline_summary']['event_total'] == 5
    assert result['next_cursor']
    page2 = workspace.query({'types': ['communication'], 'page_size': 2, 'province': '14', 'cursor': result['next_cursor']})
    assert page2['as_of'] == result['as_of']
    assert {i['ref'] for i in page2['items']}.isdisjoint(i['ref'] for i in result['items'])
    assert workspace.query({'types': ['communication'], 'q': 'zolc'})['total'] == 0


def test_search_polish_identifiers_unlocated_and_no_fictitious_region(workspace):
    communication(workspace, areas=())
    assert workspace.query({'types': ['communication'], 'q': 'zolc'})['total'] == 1
    assert workspace.query({'types': ['communication'], 'include_unlocated': False})['total'] == 0
    assert workspace.query({'types': ['communication'], 'province': '14'})['total'] == 0
    assert workspace.query({'types': ['area'], 'q': '1416'})['items'][0]['ref'] == 'area:prg:1416'


def test_cursor_conflict_on_changed_data_and_unrelated_changes_ignored(workspace):
    communication(workspace, 'a')
    communication(workspace, 'b')
    query = {'types': ['communication'], 'page_size': 1}
    result = workspace.query(query)
    station(workspace)
    assert workspace.query(dict(query, cursor=result['next_cursor']))['total'] == 2
    communication(workspace, 'c')
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=result['next_cursor']))
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=result['next_cursor']+'bad'))


def test_frozen_clock_preserves_live_window_across_midnight(workspace):
    communication(workspace, 'a')
    communication(workspace, 'b')
    query = {'types': ['communication'], 'page_size': 1}
    result = workspace.query(query)
    workspace.repo.clock = lambda: NOW+timedelta(days=1)
    assert workspace.query(dict(query, cursor=result['next_cursor']))['total'] == 2
    assert workspace.query(query)['total'] == 0


def test_histogram_backdrop_distinct_from_selection_and_areas_timeless(workspace):
    communication(workspace, 'a', '2026-10-21T10:00:00Z')
    communication(workspace, 'b', '2026-10-22T10:00:00Z')
    time = {'mode': 'range', 'filter_range': {'from': '2026-10-22T00:00:00Z', 'to': '2026-10-23T00:00:00Z'},
            'overview_range': {'from': '2026-10-21T00:00:00Z', 'to': '2026-10-23T00:00:00Z'}}
    result = workspace.query({'types': ['communication'], 'time': time})
    assert result['total'] == 1
    assert result['timeline_summary']['event_total'] == 2
    assert result['timeline_summary']['selected_event_total'] == 1
    timeless = workspace.query({'types': ['area'], 'time': time})
    assert timeless['timeline_summary']['event_total'] == 0
    assert timeless['timeline_summary']['selected_event_total'] == 0
    assert timeless['timeline_summary']['timeless_total'] == timeless['total']


def test_day_precision_dst_and_half_open_range(workspace):
    ref, value = communication(workspace)
    value['source_published_at'] = None
    value['fields']['source_published_date'] = '2026-03-29'
    result = workspace.repo.ingest(value)
    workspace.catalog.project_document(result['document_id'])
    obj = workspace.catalog.object(ref)
    assert obj['date_precision'] == 'day'
    a = datetime.fromisoformat(obj['published_at'])
    b = datetime.fromisoformat(obj['metadata']['published_until'])
    assert (b-a).total_seconds() == 23*3600
    query = {'types': ['communication'], 'time': {'mode': 'range', 'filter_range': {
        'from': '2026-03-29T12:00:00Z', 'to': '2026-03-29T13:00:00Z'}}}
    assert workspace.query(query)['total'] == 1
    query['time']['filter_range'] = {'from': '2026-03-29T22:00:00Z', 'to': '2026-03-30T01:00:00Z'}
    assert workspace.query(query)['total'] == 0


def test_station_corrections_null_and_cursor_within_selected_interval(workspace):
    ref = station(workspace)
    sample(workspace, ref, 120)
    sample(workspace, ref, None, '2026-10-22T09:00:00+00:00')
    sample(workspace, ref, 130, revision=2)
    query = {'types': ['hydro_station'], 'time': {'mode': 'range', 'filter_range': {
        'from': '2026-10-22T07:00:00Z', 'to': '2026-10-22T10:00:00Z'}}}
    result = workspace.query(query)
    assert result['items'][0]['measurement']['value'] is None
    assert result['timeline_summary']['event_total'] == 2
    detail = workspace.detail(ref, result['as_of'], result['data_revision'], '2026-10-22T08:30:00Z')
    assert detail['selected_measurement']['value'] == 130
    assert detail['object']['value_context'] == 'cursor'
    assert workspace.detail(ref, result['as_of'], result['data_revision'], '2026-10-22T07:30:00Z')['selected_measurement'] is None
    with pytest.raises(ValueError):
        workspace.detail(ref, result['as_of'], result['data_revision'], '2026-10-22T10:00:00Z')
    assert workspace.timeline(ref)['total'] == 3


def test_missing_samples_default_selectable_and_opt_out(workspace):
    station(workspace)
    assert workspace.query({'types': ['hydro_station']})['total'] == 1
    assert workspace.query({'types': ['hydro_station'], 'include_without_samples': False})['total'] == 0


def test_large_map_groups_province_type_and_no_paginated_truncation(workspace):
    with workspace.repo.lock, workspace.db:
        for number in range(1001):
            workspace.catalog.upsert_station(f'hydro_station:imgw:{number}', 'imgw', str(number), 'Stacja',
                                             52.2, 21.0, {'province': '14'})
    result = workspace.query({'types': ['hydro_station'], 'page_size': 1})
    assert result['map']['mode'] == 'aggregates'
    assert result['map']['aggregates'][0]['count'] == 1001
    assert not result['map']['points']


def test_saved_views_optimistic_updates_and_schema_rejects_unknown(workspace):
    original = workspace.save_view({'name': ' Powódź ', 'config': {'query': {'types': ['hydro_station']}}})
    assert original['name'] == 'Powódź'
    updated = workspace.save_view({'name': 'Woda', 'config': {}, 'revision': 1}, original['id'])
    assert updated['revision'] == 2
    with pytest.raises(QueryChanged):
        workspace.save_view({'name': 'Inny', 'config': {}, 'revision': 1}, original['id'])
    with pytest.raises(ValidationError):
        SavedView.model_validate({'name': 'Widok', 'config': {'api_key': 'secret'}})
    workspace.delete_view(original['id'])
    assert workspace.views() == {'items': []}


def test_known_polygons_holes_and_shared_boundary():
    geometry = {'type': 'Polygon', 'coordinates': [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                                                  [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]}
    assert contains(geometry, 0, 2)
    assert contains(geometry, 1, 1.5)
    assert not contains(geometry, 1.5, 1.5)
    assert provinces_for_point(21.0122, 52.2297) == ['14']


@pytest.mark.parametrize('invalid', [
    {'types': ['bad']}, {'province': '1416'}, {'q': 'a'*201}, {'page_size': 201},
    {'time': {'mode': 'range', 'filter_range': {'from': '2026-01-01T00:00:00', 'to': '2026-01-02T00:00:00'}}},
    {'time': {'mode': 'range', 'filter_range': {'from': '2026-01-01T00:00:00Z', 'to': '2026-02-01T00:00:00Z'}}},
])
def test_strict_query_contract(invalid):
    with pytest.raises(ValidationError):
        WorkspaceQuery.model_validate(copy.deepcopy(invalid))


def test_fixed_clock_queries_with_distinct_time_ranges_keep_their_detail_context(workspace):
    ref = station(workspace)
    sample(workspace, ref, 100, '2026-10-21T08:00:00+00:00')
    sample(workspace, ref, 200, '2026-10-22T08:00:00+00:00')
    first = workspace.query({'types': ['hydro_station'], 'time': {'mode': 'range', 'filter_range': {
        'from': '2026-10-21T00:00:00Z', 'to': '2026-10-22T00:00:00Z'}}})
    second = workspace.query({'types': ['hydro_station'], 'time': {'mode': 'range', 'filter_range': {
        'from': '2026-10-22T00:00:00Z', 'to': '2026-10-23T00:00:00Z'}}})
    assert first['as_of'] == second['as_of']
    assert first['data_revision'] != second['data_revision']
    assert workspace.detail(ref, first['as_of'], first['data_revision'])['object']['measurement']['value'] == 100
    assert workspace.detail(ref, second['as_of'], second['data_revision'])['object']['measurement']['value'] == 200


def test_timeline_sql_pages_2000_samples_with_nulls_and_revisions_preserved(workspace):
    ref = station(workspace)
    with workspace.repo.lock, workspace.db:
        for i in range(2100):
            instant = (NOW-timedelta(minutes=2100-i)).isoformat()
            workspace.db.execute('''INSERT INTO station_measurements(object_ref,sensor_id,metric,observed_key,
                observed_at,source_time,value,unit,fetched_at,first_fetched_at,revision,quality,content_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ref, '', 'water_level', instant, instant, instant, None if i == 1999 else i, 'cm',
                 NOW.isoformat(), NOW.isoformat(), 1, 'valid', str(i)))
    page1 = workspace.timeline(ref)
    assert page1['total'] == 2100
    assert len(page1['items']) == 2000
    assert page1['items'][-1]['value'] is None
    page2 = workspace.timeline(ref, cursor=page1['next_cursor'])
    assert len(page2['items']) == 100
    assert page2['items'][-1]['value'] == 2099
    assert page2['next_cursor'] is None


@pytest.mark.parametrize('config', [{'layout': {'token': 'secret'}}, {'camera': {'lat': 0, 'lng': 0, 'zoom': 4, 'key': 'secret'}},
                                   {'camera': {'lat': 999, 'lng': 0, 'zoom': 4}}, {'columns': ['private_field']}])
def test_saved_view_rejects_unknown_nested_configuration(config):
    with pytest.raises(ValidationError):
        SavedView.model_validate({'name': 'Widok', 'config': config})


def test_historical_query_revision_ignores_new_observations_outside_overview(workspace):
    ref = station(workspace)
    sample(workspace, ref, 100, '2026-10-21T08:00:00+00:00')
    query = {'types': ['hydro_station'], 'time': {'mode': 'range', 'filter_range': {
        'from': '2026-10-21T00:00:00Z', 'to': '2026-10-22T00:00:00Z'}}}
    first = workspace.query(query)
    sample(workspace, ref, 200, '2026-10-22T08:00:00+00:00')
    second = workspace.query(query)
    assert first['data_revision'] == second['data_revision']
    assert workspace.detail(ref, first['as_of'], first['data_revision'])['selected_measurement']['value'] == 100
    sample(workspace, ref, 150, '2026-10-21T08:00:00+00:00', revision=2)
    with pytest.raises(QueryChanged):
        workspace.detail(ref, first['as_of'], first['data_revision'])


def test_card_scope_is_not_inferred_from_first_page(workspace):
    first, _ = communication(workspace, 'one', title='AlphaUnique')
    second, _ = communication(workspace, 'two', title='BetaUnique')
    query = workspace.query({'types': ['communication'], 'page_size': 1})
    assert query['items'][0]['ref'] == first
    assert workspace.detail(second, query['as_of'], query['data_revision'])['in_scope']
    narrowed = workspace.query({'types': ['communication'], 'q': 'AlphaUnique'})
    assert not workspace.detail(second, narrowed['as_of'], narrowed['data_revision'])['in_scope']


def test_date_only_version_timeline_keeps_civil_day_precision(workspace):
    ref, value = communication(workspace)
    value['source_published_at'] = None
    value['fields']['source_published_date'] = '2026-10-25'
    workspace.repo.ingest(value)
    workspace.catalog.backfill()
    result = workspace.timeline(ref, start='2026-10-25T12:00:00Z', end='2026-10-25T13:00:00Z')
    event = result['items'][0]
    assert result['total'] == 1
    assert event['date_precision'] == 'day'
    assert event['source_date'] == '2026-10-25'
    assert (datetime.fromisoformat(event['end_at'])-datetime.fromisoformat(event['at'])).total_seconds() == 25*3600


def test_saved_view_keeps_public_from_to_aliases(workspace):
    result = workspace.save_view({'name': 'Przedział', 'config': {'query': {'types': ['communication'],
        'time': {'mode': 'range', 'filter_range': {'from': '2026-10-21T00:00:00Z', 'to': '2026-10-22T00:00:00Z'}}}}})
    interval = result['config']['query']['time']['filter_range']
    assert set(interval) == {'from', 'to'}
    assert workspace.query(result['config']['query'])['total'] == 0


def test_gios_sensor_timeline_keeps_independent_official_indices(workspace):
    ref = 'air_quality_station:gios:1'
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station(ref, 'gios', '1', 'Powietrze', 52.2, 21.0, {'province': '14'})
        workspace.db.execute('''INSERT INTO station_index_observations(object_ref,observed_key,observed_at,
            value,name,fetched_at,first_fetched_at,revision,quality,content_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (ref, '2026-10-22T08:00:00+00:00', '2026-10-22T08:00:00+00:00', 1, 'Dobry',
             NOW.isoformat(), NOW.isoformat(), 1, 'valid', 'fixture'))
    sample(workspace, ref, 4.5, metric='PM10', sensor='7')
    result = workspace.timeline(ref, sensor_id='7')
    assert len(result['items']) == 1
    assert result['items'][0]['metric'] == 'PM10'
    assert result['official_indices_total'] == 1
    assert result['official_indices'][0]['name'] == 'Dobry'
    assert result['official_indices_next_cursor'] is None


def test_out_of_order_pdf_preserves_current_projection_and_invalidates_history_context(workspace):
    current = {'source_id': 'imgw_meteo', 'identity_key': 'imgw-pdf:2026:1401:100',
               'url': 'https://danepubliczne.imgw.pl/data/current/ost_meteo/test.pdf',
               'title': 'Aktualne ostrzeżenie', 'text': 'Aktualna treść',
               'source_published_at': '2026-10-22T08:00:00Z',
               'fields': {'contract_validated': True, 'access_allowed': True}}
    inserted = workspace.repo.ingest(current)
    ref = f"communication:{inserted['document_id']}"
    first = workspace.query({'types': ['communication']})
    older = dict(current, title='Starsza wersja', text='Starsza treść', source_published_at='2026-10-21T08:00:00Z')
    result = workspace.repo.ingest(older)
    assert result['changed'] and result['out_of_order']
    assert workspace.catalog.object(ref)['label'] == 'Aktualne ostrzeżenie'
    with pytest.raises(QueryChanged):
        workspace.detail(ref, first['as_of'], first['data_revision'])
    refreshed = workspace.query({'types': ['communication']})
    assert len(workspace.detail(ref, refreshed['as_of'], refreshed['data_revision'])['versions']) == 2
    duplicate = workspace.repo.ingest(older)
    assert not duplicate['changed']
    assert workspace.query({'types': ['communication']})['data_revision'] == refreshed['data_revision']
