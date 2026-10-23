"""Civil-alert history tests use isolated synthetic snapshots, never LIVE storage."""
import copy
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wici.db import connect
from wici.repository import Repository
from wici.ukraine_history import UkraineHistory, region_ref

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
OBLAST = region_ref('oblast', 'Київська')
RAION = region_ref('raion', 'Бучанський')


@pytest.fixture
def history(tmp_path):
    clock = [NOW]
    repo = Repository(tmp_path/'ukraine.sqlite', clock=lambda: clock[0])
    service = UkraineHistory(repo)
    service.test_clock = clock
    yield service
    repo.close()


def snapshot(history, second=0, items=None, **changes):
    at = NOW+timedelta(seconds=second)
    history.test_clock[0] = at
    value = {'status': 'ready', 'stale': False, 'fetched_at': at.isoformat(), 'updated_at': at.isoformat(),
             'source_version': second+1, 'items': items if items is not None else [
                 {'scope': 'oblast', 'key': 'Київська', 'name': 'Київська область', 'oblast': None,
                  'level': 'red', 'since': (NOW-timedelta(minutes=10)).isoformat(), 'reasons': ['test fixture']}]}
    value.update(changes)
    history.ingest(value)
    return value


def geometry(history):
    polygon = {'type': 'Polygon', 'coordinates': [[[30, 50], [31, 50], [31, 51], [30, 50]]]}
    history.register_geometry({'status': 'ready', 'fetched_at': NOW.isoformat(),
        'oblasts': {'features': [{'type': 'Feature', 'properties': {'key': 'Київська', 'region': 'Київська область'}, 'geometry': polygon}]},
        'raions': {'features': [{'type': 'Feature', 'properties': {'key': 'Бучанський', 'rayon': 'Бучанський район', 'oblast': 'Київська'}, 'geometry': polygon}]}})


def replay(history, a=0, b=60, refs=None):
    return history.replay(refs or [OBLAST], NOW+timedelta(seconds=a), NOW+timedelta(seconds=b))


def rows(history, table):
    return [dict(row) for row in history.db.execute('SELECT * FROM '+table)]


def test_default_off_projects_current_regions_without_archiving(history):
    snapshot(history)
    assert not history.status()['recording']
    assert not rows(history, 'workspace_ukraine_runs')
    assert not rows(history, 'workspace_ukraine_episodes')
    item = history.catalog.object(OBLAST)
    assert item['type'] == 'ua_region'
    assert item['metadata']['country'] == 'UA'
    assert item['native_id'] == 'Київська'
    assert history.present(item, NOW, (NOW, NOW+timedelta(minutes=1)))['alert_state'] == 'red'
    assert not history.present(item, NOW, (NOW, NOW+timedelta(minutes=1)))['geometry']


def test_geometry_exact_identity_parent_and_missing_geometry_are_catalogued(history):
    geometry(history)
    snapshot(history, items=[{'scope': 'raion', 'key': 'Unknown exact key', 'name': 'Region without polygon',
        'oblast': 'Київська', 'level': 'yellow', 'since': NOW.isoformat(), 'reasons': []}])
    items = {r['ref']: r for r in history.regions()}
    assert items[RAION]['parent_ref'] == OBLAST
    assert items[OBLAST]['geometry']['type'] == 'Polygon'
    assert items[region_ref('raion', 'Unknown exact key')]['geometry'] is None
    assert region_ref('raion', 'Ключ:зі:знаками') == 'ua_region:neptun:raion:Ключ:зі:знаками'
    assert history.catalog.object(OBLAST)['source_id'] == 'ukraine_alerts'


def test_cached_snapshot_does_not_duplicate_runs_or_advance_episode_confirmation(history):
    history.set_recording(True)
    value = snapshot(history)
    history.test_clock[0] += timedelta(seconds=5)
    history.ingest(value)
    assert len(rows(history, 'workspace_ukraine_runs')) == 1
    assert len(rows(history, 'workspace_ukraine_episodes')) == 1
    assert len(rows(history, 'workspace_ukraine_observations')) == 1
    assert rows(history, 'workspace_ukraine_episodes')[0]['last_seen_at'] == NOW.isoformat()
    assert history.status()['last_recorded_at'] == NOW.isoformat()


def test_corrected_source_since_and_level_preserve_episode_and_immutable_revisions(history):
    history.set_recording(True)
    first = snapshot(history)
    item = copy.deepcopy(first['items'][0])
    item.update(level='yellow', since=(NOW-timedelta(hours=1)).isoformat())
    snapshot(history, 15, items=[item])
    episodes = rows(history, 'workspace_ukraine_episodes')
    observations = rows(history, 'workspace_ukraine_observations')
    assert len(episodes) == 1
    assert episodes[0]['source_since'] == item['since']
    assert observations[0]['source_since'] == first['items'][0]['since']
    assert observations[1]['source_since'] == item['since']
    assert observations[0]['episode_ref'] == observations[1]['episode_ref']
    assert episodes[0]['first_seen_at'] == NOW.isoformat()
    assert episodes[0]['source_updated_at'] != episodes[0]['first_seen_at']
    assert history.detail(episodes[0]['ref'], NOW, NOW+timedelta(minutes=1))['revisions'][0]['state'] == 'red'


@pytest.mark.parametrize('status,stale', [('partial', False), ('error', True), ('disabled', False)])
def test_failed_or_partial_snapshot_opens_gap_and_never_ends_episode(history, status, stale):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 15, items=[], status=status, stale=stale)
    assert rows(history, 'workspace_ukraine_episodes')[0]['active'] == 1
    assert rows(history, 'workspace_ukraine_episodes')[0]['ended_before'] is None
    snapshot(history, 30)
    history.test_clock[0] = NOW+timedelta(seconds=45)
    result = replay(history, b=45)['series'][0]
    assert [(s['from'], s['to'], s['state']) for s in result['segments']] == [
        (NOW.isoformat(), (NOW+timedelta(seconds=15)).isoformat(), 'red'),
        ((NOW+timedelta(seconds=15)).isoformat(), (NOW+timedelta(seconds=30)).isoformat(), 'unknown'),
        ((NOW+timedelta(seconds=30)).isoformat(), (NOW+timedelta(seconds=45)).isoformat(), 'red')]
    assert result['stats']['alarm_seconds'] == 30
    assert result['stats']['longest_alarm_seconds'] == 15
    assert result['stats']['coverage_ratio'] == pytest.approx(2/3)
    assert result['stats']['episode_count'] == 1


def test_complete_absence_records_end_bounds_and_uncertain_interval(history):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 15)
    snapshot(history, 30, items=[])
    history.test_clock[0] = NOW+timedelta(seconds=45)
    episode = rows(history, 'workspace_ukraine_episodes')[0]
    assert episode['active'] == 0
    assert episode['ended_after'] == (NOW+timedelta(seconds=15)).isoformat()
    assert episode['ended_before'] == (NOW+timedelta(seconds=30)).isoformat()
    series = replay(history, b=45)['series'][0]
    assert [s['state'] for s in series['segments']] == ['red', 'unknown', 'none']
    assert series['segments'][1]['reason'] == 'end_uncertain'
    assert series['segments'][1]['episode_ref'] == episode['ref']
    assert series['stats']['alarm_seconds'] == 15
    assert series['stats']['episode_count'] == 1
    assert history.timeline(episode['ref'], NOW, NOW+timedelta(minutes=1))['items'][-1]['state'] == 'none'
    snapshot(history, 45)
    assert len(rows(history, 'workspace_ukraine_episodes')) == 2


@pytest.mark.parametrize('start,end,episode_indexes,states,alarm_seconds,unknown_seconds', [
    (29, 60, [0], ['unknown', 'none'], 0, 1),
    (30, 60, [], ['none'], 0, 0),
    (31, 60, [], ['none'], 0, 0),
    (30, 61, [1], ['none', 'red'], 1, 0),
    (60, 75, [1], ['red'], 15, 0),
])
def test_episode_counts_and_details_use_half_open_range_boundaries(
        history, start, end, episode_indexes, states, alarm_seconds, unknown_seconds):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 15)
    snapshot(history, 30, items=[])
    snapshot(history, 45, items=[])
    snapshot(history, 60)
    snapshot(history, 75)
    episodes = sorted(rows(history, 'workspace_ukraine_episodes'), key=lambda row: row['first_seen_at'])

    series = replay(history, a=start, b=end)['series'][0]
    detail = history.detail(OBLAST, NOW+timedelta(seconds=start), NOW+timedelta(seconds=end))

    assert series['stats']['episode_count'] == len(episode_indexes)
    assert {episode['ref'] for episode in detail['episodes']} == {episodes[i]['ref'] for i in episode_indexes}
    assert detail['stats'] == series['stats']
    assert [segment['state'] for segment in series['segments']] == states
    assert series['stats']['alarm_seconds'] == alarm_seconds
    assert series['stats']['unknown_seconds'] == unknown_seconds
    assert series['stats']['covered_seconds'] == end-start-unknown_seconds


def test_stop_restart_and_resume_keep_gaps_and_persist_recording_setting(history):
    history.set_recording(True)
    snapshot(history)
    history.test_clock[0] = NOW+timedelta(seconds=10)
    history.set_recording(False)
    snapshot(history, 15)
    assert len(rows(history, 'workspace_ukraine_observations')) == 1
    history.test_clock[0] = NOW+timedelta(seconds=20)
    history.set_recording(True)
    snapshot(history, 30)
    history.test_clock[0] = NOW+timedelta(seconds=40)
    restarted = UkraineHistory(history.repo)
    assert restarted.status()['recording']
    assert restarted.status()['status'] == 'not_loaded'
    history.test_clock[0] = NOW+timedelta(seconds=50)
    segments = replay(history, b=50)['series'][0]['segments']
    assert [s['state'] for s in segments] == ['red', 'unknown', 'red', 'unknown']
    assert segments[0]['to'] == (NOW+timedelta(seconds=10)).isoformat()
    assert segments[2]['to'] == (NOW+timedelta(seconds=40)).isoformat()


def test_gap_threshold_never_connects_distant_successful_polls(history):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 180)
    history.test_clock[0] = NOW+timedelta(seconds=195)
    segments = replay(history, b=195)['series'][0]['segments']
    assert [s['state'] for s in segments] == ['red', 'unknown', 'red']
    assert segments[0]['to'] == (NOW+timedelta(seconds=45)).isoformat()
    assert segments[1]['to'] == (NOW+timedelta(seconds=180)).isoformat()


def test_half_open_cursor_is_consistent_with_replay_and_live_expires_independently(history):
    history.set_recording(True)
    snapshot(history)
    history.mark_gap('error', NOW+timedelta(seconds=15))
    history.test_clock[0] = NOW+timedelta(seconds=30)
    item = history.catalog.object(OBLAST)
    at = NOW+timedelta(seconds=15)
    assert history.present(item, history.test_clock[0], (NOW, NOW+timedelta(minutes=1)), historical=True, cursor_at=at)['state'] == 'unknown'
    snapshot(history, 30)
    history.test_clock[0] = NOW+timedelta(seconds=100)
    assert history.present(item, history.test_clock[0], (NOW, NOW+timedelta(minutes=2)))['state'] == 'red'
    assert replay(history, b=100)['series'][0]['segments'][-1]['state'] == 'unknown'
    history.test_clock[0] = NOW+timedelta(seconds=121)
    assert history.present(item, history.test_clock[0], (NOW, NOW+timedelta(minutes=3)))['state'] == 'unknown'


def test_region_comparison_keeps_separate_stats_and_missing_geometry(history):
    geometry(history)
    history.set_recording(True)
    first = snapshot(history)
    raion = dict(first['items'][0], scope='raion', key='Бучанський', name='Бучанський район', oblast='Київська')
    snapshot(history, 15, items=first['items']+[raion])
    history.test_clock[0] = NOW+timedelta(seconds=30)
    result = replay(history, b=30, refs=[OBLAST, RAION])
    assert [s['stats']['alarm_seconds'] for s in result['series']] == [30, 15]
    assert result['series'][1]['parent_ref'] == OBLAST
    assert 'total_alarm_seconds' not in result
    assert result['interpolation'] is False


def test_retention_boundary_preserves_carry_forward_but_hides_expired_history(history):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 15, items=[])
    history.test_clock[0] = NOW+timedelta(days=31)
    later = {'status': 'ready', 'stale': False, 'fetched_at': history.test_clock[0].isoformat(),
             'updated_at': history.test_clock[0].isoformat(), 'items': []}
    history.ingest(later)
    assert history.db.execute('PRAGMA foreign_key_check').fetchall() == []
    expired = replay(history, b=15)['series'][0]
    assert expired['segments'][0]['state'] == 'unknown'
    assert expired['stats']['alarm_seconds'] == 0
    assert history.status()['retention_days'] == 30


def test_record_false_never_changes_persisted_setting_or_creates_history(history):
    history.set_recording(True)
    at = NOW.isoformat()
    history.ingest({'status': 'ready', 'fetched_at': at, 'updated_at': at, 'items': []}, record=False)
    assert history.status()['recording']
    assert rows(history, 'workspace_ukraine_runs') == []


def test_replay_rejects_invalid_size_range_and_unknown_identity(history):
    snapshot(history)
    for refs in ([], [OBLAST, OBLAST], ['x']*6):
        with pytest.raises(ValueError):
            history.replay(refs, NOW, NOW+timedelta(hours=1))
    with pytest.raises(ValueError):
        history.replay([OBLAST], NOW, NOW+timedelta(days=31))
    with pytest.raises(ValueError):
        history.replay([OBLAST], NOW, NOW)
    with pytest.raises(KeyError):
        history.replay(['ua_region:neptun:oblast:Missing'], NOW, NOW+timedelta(hours=1))
    with pytest.raises(ValueError):
        history.replay([OBLAST], NOW.replace(tzinfo=None), NOW+timedelta(hours=1))


def test_migration_18_preserves_all_catalogue_children_watchlist_and_other_tables(tmp_path):
    path = tmp_path/'upgrade.sqlite'
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    for migration in migrations[:17]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=17')
    ref = 'hydro_station:imgw:1'
    db.execute('''INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text)
        VALUES(?,'hydro_station','imgw','1','Station','station')''', (ref,))
    db.execute('INSERT INTO catalog_object_areas VALUES(?,?,?,?)', (ref, '14', 'station_location', 'fixture'))
    db.execute('INSERT INTO workspace_watchlist VALUES(?,?)', (ref, NOW.isoformat()))
    db.execute('INSERT INTO station_sensors VALUES(?,?,?,?,?,?,?)', ('sensor', ref, 'metric', 'Sensor', 'cm', '{}', NOW.isoformat()))
    db.execute('''INSERT INTO station_measurements(object_ref,metric,observed_key,fetched_at,first_fetched_at,revision,quality,content_hash)
        VALUES(?,'water_level','sample',?,?,1,'valid','hash')''', (ref, NOW.isoformat(), NOW.isoformat()))
    db.execute('''INSERT INTO station_index_observations(object_ref,observed_key,fetched_at,first_fetched_at,revision,quality,content_hash)
        VALUES(?,'index',?,?,1,'valid','hash')''', (ref, NOW.isoformat(), NOW.isoformat()))
    db.execute('INSERT INTO workspace_views VALUES(?,?,?,?,?,?,?)', ('view', 'View', 1, '{}', 3, NOW.isoformat(), NOW.isoformat()))
    tables = ['catalog_objects', 'catalog_object_areas', 'workspace_watchlist', 'station_sensors',
              'station_measurements', 'station_index_observations', 'workspace_views']
    before = {name: db.execute('SELECT * FROM '+name).fetchall() for name in tables}
    db.commit()
    db.close()
    db = connect(path)
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    for name in tables:
        assert [tuple(row) for row in db.execute('SELECT * FROM '+name)] == before[name]
    db.execute('''INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text)
        VALUES('ua_region:neptun:oblast:test','ua_region','ukraine_alerts','test','Test','test')''')
    db.execute('''INSERT INTO catalog_objects(ref,type,source_id,native_id,label,search_text)
        VALUES('civil_alert:neptun:test','civil_alert','ukraine_alerts','test','Test','test')''')
    db.close()


def test_parent_resolves_exact_unique_provider_label_after_geometry_arrives(history):
    snapshot(history, items=[{'scope': 'raion', 'key': 'Бучанський', 'name': 'Бучанський район',
        'oblast': 'Київська область', 'level': 'red', 'since': NOW.isoformat(), 'reasons': []}])
    assert history.regions()[0]['parent_ref'] is None
    geometry(history)
    region = next(r for r in history.regions() if r['ref'] == RAION)
    assert region['parent_ref'] == OBLAST
    assert region['parent_basis'] == 'source_oblast_key'  # Fixture geometry explicitly supplies a key.
    snapshot(history, 15, items=[{'scope': 'raion', 'key': 'Бучанський', 'name': 'Бучанський район',
        'oblast': 'Київська область', 'level': 'red', 'since': NOW.isoformat(), 'reasons': []}])
    region = next(r for r in history.regions() if r['ref'] == RAION)
    assert region['parent_ref'] == OBLAST
    assert region['parent_basis'] == 'source_oblast_name'
    assert history.catalog.object(RAION)['metadata']['parent_basis'] == 'source_oblast_name'


def test_query_as_of_clock_controls_presentation_freshness(history):
    snapshot(history)
    item = history.catalog.object(OBLAST)
    history.test_clock[0] = NOW+timedelta(minutes=3)
    assert history.status()['status'] == 'stale'
    assert history.present(item, NOW, (NOW, NOW+timedelta(minutes=1)))['state'] == 'red'


def test_invalid_ready_input_does_not_report_previous_state_as_current(history):
    snapshot(history)
    snapshot(history, 15, stale=True)
    assert history.status()['status'] == 'partial'
    assert history.present(history.catalog.object(OBLAST), NOW+timedelta(seconds=15), (NOW, NOW+timedelta(minutes=1)))['state'] == 'unknown'


def test_retention_prunes_without_source_fetch_and_hides_boundary_in_all_history_apis(history):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 15)
    history.set_recording(False)
    history.test_clock[0] = NOW+timedelta(days=31)
    history.prune()
    # The minimal carry-forward row and open identity survive, but are not history.
    assert rows(history, 'workspace_ukraine_observations')
    result = replay(history, b=15)['series'][0]
    assert result['stats']['episode_count'] == 0
    assert result['stats']['coverage_ratio'] == 0
    assert all(segment['state'] == 'unknown' for segment in result['segments'])
    assert history.timeline(OBLAST, NOW, NOW+timedelta(seconds=15))['items'] == []
    assert history.detail(OBLAST, NOW, NOW+timedelta(seconds=15))['episodes'] == []
    assert history.detail(OBLAST, NOW, NOW+timedelta(seconds=15))['revisions'] == []
    assert history.db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_startup_prunes_expired_completed_episodes_even_with_recording_disabled(history):
    history.set_recording(True)
    snapshot(history)
    snapshot(history, 15, items=[])
    history.set_recording(False)
    history.test_clock[0] = NOW+timedelta(days=31)
    restarted = UkraineHistory(history.repo)
    assert not restarted.status()['recording']
    assert rows(history, 'workspace_ukraine_episodes') == []
    assert history.db.execute("SELECT COUNT(*) FROM catalog_objects WHERE type='civil_alert'").fetchone()[0] == 0
    assert history.db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_replay_timeline_and_detail_reject_oversized_exact_history(history):
    history.set_recording(True)
    snapshot(history)
    run_id = rows(history, 'workspace_ukraine_runs')[0]['id']
    episode = rows(history, 'workspace_ukraine_episodes')[0]['ref']
    with history.db:
        history.db.executemany("""INSERT INTO workspace_ukraine_observations(run_id,region_ref,episode_ref,
            observed_at,state,source_since,source_updated_at) VALUES(?,?,?,?,?,?,?)""", [
            (run_id, OBLAST, episode, (NOW+timedelta(milliseconds=i)).isoformat(), 'red' if i%2 else 'yellow',
             NOW.isoformat(), NOW.isoformat()) for i in range(1, 12001)])
    for read in (lambda: replay(history), lambda: history.timeline(OBLAST, NOW, NOW+timedelta(minutes=1)),
                 lambda: history.detail(OBLAST, NOW, NOW+timedelta(minutes=1))):
        with pytest.raises(ValueError, match='12000'):
            read()
    # A narrower window remains available without altering the stored observations.
    assert replay(history, b=1)['series'][0]['segments']
    assert len(rows(history, 'workspace_ukraine_observations')) == 12001


def test_non_recorded_current_snapshot_never_reassigns_state_to_old_open_episode(history):
    history.set_recording(True)
    snapshot(history)
    episode = rows(history, 'workspace_ukraine_episodes')[0]['ref']
    history.test_clock[0] = NOW+timedelta(seconds=10)
    history.set_recording(False)
    snapshot(history, 15, items=[])
    interval = (NOW, NOW+timedelta(minutes=1))
    assert history.present(history.catalog.object(OBLAST), history.test_clock[0], interval)['state'] == 'none'
    assert history.present(history.catalog.object(episode), history.test_clock[0], interval)['state'] == 'unknown'
    assert rows(history, 'workspace_ukraine_episodes')[0]['active'] == 1
    # Even another current red snapshot cannot establish this old episode's identity.
    snapshot(history, 30)
    assert history.present(history.catalog.object(OBLAST), history.test_clock[0], interval)['state'] == 'red'
    assert history.present(history.catalog.object(episode), history.test_clock[0], interval)['state'] == 'unknown'
