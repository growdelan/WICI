"""Local workspace contracts and regressions for civil-alert region analysis."""
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wici.repository import Repository
from wici.workspace_api import create_workspace_router
from wici.workspace_models import SavedView, UkraineReplay, WorkspaceQuery
from wici.workspace_service import QueryChanged, WorkspaceService

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
OBLAST = 'ua_region:neptun:oblast:київська область'
RAION = 'ua_region:neptun:raion:бучанський'
OTHER = 'ua_region:neptun:oblast:львівська область'
POLYGON = {'type': 'Polygon', 'coordinates': [[[30, 50], [31, 50], [31, 51], [30, 51], [30, 50]]]}


def at(seconds=0):
    return (NOW+timedelta(seconds=seconds)).isoformat()


def feature(key, name, *, raion=False, oblast=None):
    return {'type': 'Feature', 'properties': {'key': key, 'rayon' if raion else 'region': name,
                                              'oblast': oblast}, 'geometry': POLYGON}


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'ukraine.sqlite3', clock=lambda: NOW)
    service = WorkspaceService(repo)
    service.ukraine.register_geometry({'fetched_at': at(), 'oblasts': {'features': [
        feature('київська область', 'Київська область'), feature('львівська область', 'Львівська область')]},
        'raions': {'features': [feature('бучанський', 'Бучанський район', raion=True, oblast='київська область')]}})
    yield service
    repo.close()


def snapshot(workspace, seconds=0, level='red', ref=RAION, *, record=None):
    workspace.repo.clock = lambda: NOW+timedelta(seconds=seconds)
    _, _, scope, key = ref.split(':', 3)
    items = [] if level is None else [{'scope': scope, 'key': key, 'name': 'Бучанський район' if ref == RAION else key,
        'oblast': 'київська область', 'level': level, 'since': at(), 'reasons': ['Повітряна тривога']}]
    workspace.ukraine.ingest({'status': 'ready', 'stale': False, 'fetched_at': at(seconds),
        'updated_at': at(seconds), 'version': 1, 'items': items}, record=record)


def range_query(start=0, end=60, **kwargs):
    return {'types': ['ua_region', 'civil_alert'], 'country': 'UA', 'time': {'mode': 'range',
        'filter_range': {'from': at(start), 'to': at(end)}}, **kwargs}


def recorded(workspace):
    workspace.ukraine.set_recording(True)
    snapshot(workspace)
    snapshot(workspace, 15)
    snapshot(workspace, 30, 'yellow')
    snapshot(workspace, 40, 'yellow')
    snapshot(workspace, 45, None)
    workspace.repo.clock = lambda: NOW+timedelta(seconds=60)


def client_for(workspace):
    app = FastAPI()
    app.state.workspace = workspace
    app.include_router(create_workspace_router())
    return TestClient(app)


def test_country_region_hierarchy_and_current_geometry_are_shared_by_map_and_table(workspace):
    recorded(workspace)
    query = range_query(region_ref=OBLAST)
    result = workspace.query(query)
    refs = {item['ref'] for item in result['items']}
    assert OBLAST in refs and RAION in refs and OTHER not in refs
    assert len(refs) == 3  # Two administrative regions and one alarm episode.
    assert {item['ref'] for item in result['map']['areas']} == refs
    assert not result['map']['points']
    assert all(item['geometry'] == POLYGON and item['areas'] == [] for item in result['map']['areas'])
    assert workspace.query(range_query(region_ref=RAION))['total'] == 2
    assert workspace.query({'country': 'PL', 'types': ['area'], 'province': '14'})['total'] > 0
    assert workspace.query({'country': 'PL', 'types': ['ua_region', 'civil_alert']})['total'] == 0
    assert workspace.query({'country': 'UA', 'q': 'Бучанський'})['total'] == 1  # Live includes regions, not ended episodes.


def test_missing_geometry_retains_searchable_region_and_alarm(workspace):
    workspace.ukraine.set_recording(True)
    missing = 'ua_region:neptun:raion:без геометрії'
    snapshot(workspace, ref=missing)
    result = workspace.query({'types': ['ua_region', 'civil_alert'], 'q': 'без геометрії'})
    assert result['total'] == result['map']['unlocated_total'] == 2
    assert result['map']['items'] == []
    assert workspace.query({'types': ['ua_region'], 'q': 'без геометрії', 'include_unlocated': False})['total'] == 0


def test_histogram_counts_state_changes_once_when_regions_and_episodes_are_both_selected(workspace):
    recorded(workspace)
    result = workspace.query(range_query())
    changes = workspace.db.execute('SELECT count(*) FROM workspace_ukraine_observations').fetchone()[0]
    assert result['timeline_summary']['event_total'] == changes
    assert result['timeline_summary']['timeless_total'] == 3
    assert changes > 0


def test_retained_boundary_records_do_not_expose_history_before_thirty_day_cutoff(workspace):
    recorded(workspace)
    workspace.repo.clock = lambda: NOW+timedelta(days=31)
    # Even before scheduled pruning, old storage rows must not reappear as
    # historical events. Boundary observations may legitimately remain on disk.
    assert workspace.db.execute('SELECT count(*) FROM workspace_ukraine_observations').fetchone()[0] > 0
    result = workspace.query(range_query())
    assert all(item['type'] == 'ua_region' for item in result['items'])
    assert result['timeline_summary']['event_total'] == 0
    assert workspace.timeline(RAION, start=at(), end=at(60))['total'] == 0


def test_detail_timeline_and_replay_share_half_open_cursor_state(workspace):
    recorded(workspace)
    result = workspace.query(range_query())
    detail = workspace.detail(RAION, result['as_of'], result['data_revision'], cursor_at=at(30))
    assert detail['object']['state'] == 'yellow'
    assert detail['object']['value_context'] == 'cursor'
    assert len(detail['ukraine']['episodes']) == 1
    replay = workspace.ukraine_replay(UkraineReplay.model_validate({'refs': [RAION], 'from': at(), 'to': at(60)}))
    segment = next(s for s in replay['series'][0]['segments'] if s['from'] <= at(30) < s['to'])
    assert segment['state'] == detail['object']['state']
    assert replay['series'][0]['stats']['alarm_seconds'] == 40
    assert any(s['state'] == 'unknown' and s['from'] == at(40) and s['to'] == at(45)
               for s in replay['series'][0]['segments'])
    timeline = workspace.timeline(RAION, start=at(), end=at(60), limit=2,
        as_of=result['as_of'], data_revision=result['data_revision'])
    assert timeline['total'] == 3 and timeline['next_cursor'] == '2'
    assert len(timeline['items']) == 2
    assert workspace.timeline(RAION, start=at(), end=at(30))['total'] == 1
    with pytest.raises(ValueError, match='Kursor'):
        workspace.detail(RAION, result['as_of'], result['data_revision'], cursor_at=at(60))


def test_query_page_and_detail_conflict_after_relevant_watch_change(workspace):
    snapshot(workspace)
    query = {'types': ['ua_region'], 'page_size': 1}
    result = workspace.query(query)
    assert result['next_cursor']
    workspace.watch(RAION, True)
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=result['next_cursor']))
    with pytest.raises(QueryChanged):
        workspace.detail(RAION, result['as_of'], result['data_revision'])


def test_pagination_keeps_query_clock_when_live_source_expires(workspace):
    snapshot(workspace)
    query = {'types': ['ua_region'], 'page_size': 1}
    initial = workspace.query(query)
    assert next(item for item in initial['map']['areas'] if item['ref'] == RAION)['state'] == 'red'
    workspace.repo.clock = lambda: NOW+timedelta(seconds=120)
    following = workspace.query(dict(query, cursor=initial['next_cursor']))
    assert following['as_of'] == initial['as_of']
    assert next(item for item in following['map']['areas'] if item['ref'] == RAION)['state'] == 'red'
    refreshed = workspace.query(query)
    assert next(item for item in refreshed['map']['areas'] if item['ref'] == RAION)['state'] == 'unknown'


def test_polish_only_query_does_not_expire_when_ukraine_receives_new_data(workspace):
    query = {'types': ['area', 'ua_region'], 'country': 'PL', 'page_size': 1}
    initial = workspace.query(query)
    snapshot(workspace, 15)
    following = workspace.query(dict(query, cursor=initial['next_cursor']))
    assert following['data_revision'] == initial['data_revision']
    assert following['total'] == initial['total']


@pytest.mark.parametrize('level', [None, 'red', 'yellow'])
def test_completed_history_keeps_detail_timeline_and_pagination_after_new_poll(workspace, level):
    recorded(workspace)
    query = range_query(page_size=1)
    initial = workspace.query(query)
    params = {'as_of': initial['as_of'], 'data_revision': initial['data_revision']}
    before = workspace.detail(RAION, **params, cursor_at=at(30))
    events = workspace.timeline(RAION, **params)['items']
    snapshot(workspace, 75, level)

    with client_for(workspace) as client:
        path = '/api/workspace/objects/'+quote(RAION, safe='')
        detail = client.get(path, params=dict(params, cursor_at=at(30)))
        timeline = client.get(path+'/timeline', params=params)
        following = client.post('/api/workspace/query', json=dict(query, cursor=initial['next_cursor']))
    assert detail.status_code == timeline.status_code == following.status_code == 200
    assert detail.json()['object']['state'] == 'yellow'
    assert detail.json()['ukraine']['stats'] == before['ukraine']['stats']
    assert timeline.json()['items'] == events
    assert following.json()['data_revision'] == initial['data_revision']
    assert following.json()['as_of'] == initial['as_of']
    assert following.json()['items'][0]['ref'] != initial['items'][0]['ref']


@pytest.mark.parametrize('level', [None, 'red', 'yellow'])
def test_later_changes_to_ongoing_episode_preserve_earlier_history(workspace, level):
    workspace.ukraine.set_recording(True)
    snapshot(workspace)
    snapshot(workspace, 15)
    query = range_query(end=15)
    initial = workspace.query(query)
    snapshot(workspace, 75, level)
    detail = workspace.detail(RAION, initial['as_of'], initial['data_revision'], cursor_at=at(5))
    assert detail['object']['state'] == 'red'
    assert detail['ukraine']['stats']['alarm_seconds'] == 15
    assert workspace.query(query)['data_revision'] == initial['data_revision']


def test_later_alarm_end_invalidates_history_when_uncertainty_overlaps_it(workspace):
    workspace.ukraine.set_recording(True)
    snapshot(workspace)
    snapshot(workspace, 15)
    workspace.repo.clock = lambda: NOW+timedelta(seconds=30)
    query = range_query(end=30, page_size=1)
    initial = workspace.query(query)
    snapshot(workspace, 75, None)
    with pytest.raises(QueryChanged):
        workspace.detail(RAION, initial['as_of'], initial['data_revision'])
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=initial['next_cursor']))
    updated = workspace.ukraine.detail(RAION, at(), at(30))
    assert updated['stats']['alarm_seconds'] == 15
    assert updated['segments'][-1]['reason'] == 'end_uncertain'


@pytest.mark.parametrize('change', ['in_range', 'preceding_gap', 'geometry', 'watch'])
def test_relevant_history_changes_still_invalidate_frozen_context(workspace, change):
    workspace.ukraine.set_recording(True)
    snapshot(workspace)
    snapshot(workspace, 15)
    query = range_query(start=20, end=60, page_size=1)
    initial = workspace.query(query)
    if change == 'in_range':
        snapshot(workspace, 30, 'yellow')
    elif change == 'preceding_gap':
        workspace.ukraine.mark_gap('test_outage', NOW+timedelta(seconds=18))
    elif change == 'geometry':
        updated = feature('київська область', 'Київська область')
        updated['geometry'] = {'type': 'Polygon', 'coordinates': [[[30, 50], [32, 50], [32, 51], [30, 50]]]}
        workspace.ukraine.register_geometry({'fetched_at': at(75), 'oblasts': {'features': [updated]}})
    else:
        workspace.watch(RAION, True)
    with pytest.raises(QueryChanged):
        workspace.detail(RAION, initial['as_of'], initial['data_revision'])
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=initial['next_cursor']))


def test_new_coverage_without_state_change_invalidates_history(workspace):
    workspace.ukraine.set_recording(True)
    snapshot(workspace)
    workspace.repo.clock = lambda: NOW+timedelta(seconds=45)
    query = range_query(end=90)
    initial = workspace.query(query)
    before = workspace.ukraine.detail(RAION, at(), at(90))
    observations = workspace.db.execute('SELECT count(*) FROM workspace_ukraine_observations').fetchone()[0]
    snapshot(workspace, 60)
    workspace.repo.clock = lambda: NOW+timedelta(seconds=75)
    assert workspace.db.execute('SELECT count(*) FROM workspace_ukraine_observations').fetchone()[0] == observations
    after = workspace.ukraine.detail(RAION, at(), at(90))
    assert before['stats']['covered_seconds'] == 45
    assert after['stats']['covered_seconds'] == 60
    with pytest.raises(QueryChanged):
        workspace.detail(RAION, initial['as_of'], initial['data_revision'])


def test_gap_at_exclusive_end_and_later_recording_stop_preserve_history(workspace):
    recorded(workspace)
    query = range_query(page_size=1)
    initial = workspace.query(query)
    workspace.ukraine.mark_gap('source_error', NOW+timedelta(seconds=60))
    workspace.repo.clock = lambda: NOW+timedelta(seconds=75)
    workspace.ukraine.set_recording(False)
    following = workspace.query(dict(query, cursor=initial['next_cursor']))
    assert following['data_revision'] == initial['data_revision']
    assert workspace.detail(RAION, initial['as_of'], initial['data_revision'], cursor_at=at(30))['object']['state'] == 'yellow'


def test_removing_history_by_retention_invalidates_region_context(workspace):
    recorded(workspace)
    query = range_query(types=['ua_region'], page_size=1)
    initial = workspace.query(query)
    workspace.repo.clock = lambda: NOW+timedelta(days=31)
    workspace.ukraine.prune()
    with pytest.raises(QueryChanged):
        workspace.detail(RAION, initial['as_of'], initial['data_revision'])
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=initial['next_cursor']))


def test_retention_invalidates_history_even_when_boundary_rows_survive(workspace):
    workspace.ukraine.set_recording(True)
    snapshot(workspace)
    snapshot(workspace, 15)
    workspace.repo.clock = lambda: NOW+timedelta(seconds=30)
    query = range_query(end=30, types=['ua_region'], page_size=1)
    initial = workspace.query(query)
    before = workspace.ukraine.detail(RAION, at(), at(30))
    runs = [row['id'] for row in workspace.db.execute('SELECT id FROM workspace_ukraine_runs')]
    observations = [row['id'] for row in workspace.db.execute('SELECT id FROM workspace_ukraine_observations')]
    snapshot(workspace, 31*86400)
    assert [row['id'] for row in workspace.db.execute(
        'SELECT id FROM workspace_ukraine_runs WHERE observed_at<?', (at(30),))] == runs
    assert [row['id'] for row in workspace.db.execute('SELECT id FROM workspace_ukraine_observations')] == observations
    after = workspace.ukraine.detail(RAION, at(), at(30))
    assert before['stats']['alarm_seconds'] == 30
    assert after['stats']['alarm_seconds'] == after['stats']['coverage_ratio'] == after['stats']['episode_count'] == 0
    with pytest.raises(QueryChanged):
        workspace.detail(RAION, initial['as_of'], initial['data_revision'])
    with pytest.raises(QueryChanged):
        workspace.query(dict(query, cursor=initial['next_cursor']))


def test_region_watchlist_does_not_enable_recording_and_rejects_alarm_and_polish_area(workspace):
    snapshot(workspace)
    assert not workspace.ukraine.status()['recording']
    workspace.watch(RAION, True)
    assert [item['ref'] for item in workspace.watchlist()['items']] == [RAION]
    assert workspace.query({'types': ['ua_region'], 'watched_only': True})['items'][0]['watched']
    assert not workspace.ukraine.status()['recording']
    assert workspace.db.execute('SELECT count(*) FROM workspace_ukraine_runs').fetchone()[0] == 0
    with pytest.raises(ValueError):
        workspace.watch('area:prg:14', True)
    recorded(workspace)
    alarm = workspace.db.execute('SELECT ref FROM workspace_ukraine_episodes LIMIT 1').fetchone()[0]
    with pytest.raises(ValueError):
        workspace.watch(alarm, True)
    workspace.watch(RAION, False)
    assert workspace.watchlist()['items'] == []


def test_saved_ukraine_view_preserves_region_comparison_timezone_and_legacy_views(workspace):
    config = {'query': range_query(), 'selectedRef': RAION, 'comparedRegionRefs': [RAION, OTHER],
              'displayTimezone': 'Europe/Kyiv', 'relative_seconds': 30*86400}
    view = workspace.save_view({'name': 'Ukraina', 'config': config})
    assert view['config']['comparedRegionRefs'] == [RAION, OTHER]
    assert view['config']['displayTimezone'] == 'Europe/Kyiv'
    legacy = {'comparedRefs': ['aircraft:icao:abc123'], 'selectedRef': 'area:prg:14'}
    assert workspace.save_view({'name': 'Transport', 'config': legacy})['config'] == legacy


@pytest.mark.parametrize('invalid', [
    {'country': 'DE'}, {'country': 'UA', 'province': '14'}, {'country': 'PL', 'region_ref': RAION},
    {'region_ref': 'area:prg:14'}, {'region_ref': 'ua_region:neptun:city:київ'},
    {'types': ['ua_region'], 'time': {'mode': 'range', 'filter_range': {'from': at(), 'to': at(31*86400)}}},
    {'types': ['ua_region', 'hydro_station'], 'time': {'mode': 'range', 'filter_range': {'from': at(), 'to': at(15*86400)}}},
])
def test_invalid_geography_and_mixed_source_history_limits_are_rejected(invalid):
    with pytest.raises(ValidationError):
        WorkspaceQuery.model_validate(invalid)


@pytest.mark.parametrize('invalid', [
    {'refs': [RAION, RAION]}, {'refs': ['aircraft:icao:abc123']}, {'refs': []},
    {'refs': [RAION], 'to': at(31*86400)}, {'refs': [RAION], 'from': '2026-10-23T12:00:00'},
])
def test_replay_contract_rejects_invalid_refs_duplicate_regions_and_ranges(invalid):
    with pytest.raises(ValidationError):
        UkraineReplay.model_validate({'refs': [RAION], 'from': at(), 'to': at(60)} | invalid)


def test_saved_view_rejects_invalid_timezone_and_duplicate_regions():
    for config in ({'displayTimezone': 'local'}, {'comparedRegionRefs': [RAION, RAION]}):
        with pytest.raises(ValidationError):
            SavedView.model_validate({'name': 'Invalid', 'config': config})


def test_api_regions_encoded_ids_replay_watch_and_recording_fallback(workspace):
    recorded(workspace)
    with client_for(workspace) as client:
        assert len(client.get('/api/workspace/ukraine/regions').json()['items']) == 3
        path = quote(RAION, safe='')
        assert client.get('/api/workspace/objects/'+path).json()['object']['ref'] == RAION
        assert client.put('/api/workspace/watchlist/'+path).json() == {'ref': RAION, 'watched': True}
        assert client.get('/api/workspace/watchlist').json()['items'][0]['ref'] == RAION
        assert client.delete('/api/workspace/watchlist/'+path).status_code == 200
        replay = client.post('/api/workspace/ukraine/replay', json={'refs': [RAION], 'from': at(), 'to': at(60)})
        assert replay.status_code == 200 and replay.json()['series'][0]['stats']['alarm_seconds'] == 40
        assert client.post('/api/workspace/ukraine/replay', json={'refs': [RAION, RAION], 'from': at(), 'to': at(60)}).status_code == 422
        assert client.post('/api/workspace/ukraine/replay', json={'refs': ['ua_region:neptun:oblast:невідомий'], 'from': at(), 'to': at(60)}).status_code == 404
        assert client.get('/api/workspace/ukraine/recording').json()['recording']
        assert client.put('/api/workspace/ukraine/recording', json={'enabled': False}).status_code == 503
        assert client.post('/api/workspace/query', json=range_query()).status_code == 200
        assert client.get('/api/workspace/status').json()['ukraine_history_days'] == 30


def test_recording_api_awaits_collector_and_returns_persisted_state(workspace):
    class Collector:
        async def set_enabled(self, enabled):
            workspace.ukraine.set_recording(enabled)

        def status(self):
            return workspace.ukraine.status()

    client = client_for(workspace)
    client.app.state.ukraine_collector = Collector()
    with client:
        assert client.put('/api/workspace/ukraine/recording', json={'enabled': True}).json()['recording']
        assert not client.put('/api/workspace/ukraine/recording', json={'enabled': False}).json()['recording']
