"""Station archive contracts use local, synthetic responses only."""
import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from wici.gios import FIELDS, GiosService, normalize
from wici.hydro import HydroService, stations
from wici.repository import Repository
from wici.station_history import StationHistory

NOW = datetime(2026, 10, 17, 6, 30, tzinfo=UTC)
FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def archive(tmp_path):
    clock = [NOW]
    repo = Repository(tmp_path / 'history.db', clock=lambda: clock[0])
    yield repo, StationHistory(repo), clock
    repo.close()


def hydro_response(now=NOW, value=200, when=None):
    raw = json.loads((FIXTURES / 'imgw_hydro/hydro.json').read_text())[0]
    raw['stan_wody'] = value
    raw['stan_wody_data_pomiaru'] = when or '2026-10-17 06:00:00'
    return {'status': 'ready', 'items': stations([raw], now)[0], 'fetched_at': now.isoformat(),
            'source_url': 'https://danepubliczne.imgw.pl/api/data/hydro/', 'time_basis': 'UTC'}


def gios_response(kind, now=NOW):
    payload = json.loads((FIXTURES / f'gios/{kind}.json').read_text())[FIELDS[kind]]
    rows = [payload] if isinstance(payload, dict) else payload
    return {'status': 'ready', 'items': normalize(kind, rows)[0], 'fetched_at': now.isoformat(),
            'source_url': 'https://powietrze.gios.gov.pl/pjp/content/api'}


def test_corrections_are_immutable_latest_revision_dedup_and_null_is_not_zero(archive):
    repo, history, clock = archive
    response = hydro_response()
    station = response['items'][0]
    ref = f'hydro_station:imgw:{station["id"]}'
    history.write('hydro:stations', response)
    original = dict(repo.db.execute("SELECT * FROM station_measurements WHERE metric='water_level'").fetchone())
    clock[0] += timedelta(minutes=6)
    history.write('hydro:stations', {**response, 'fetched_at': clock[0].isoformat()})
    assert dict(repo.db.execute("SELECT * FROM station_measurements WHERE metric='water_level'").fetchone()) == original
    assert repo.db.execute('SELECT COUNT(*) FROM workspace_source_runs').fetchone()[0] == 2
    for value in (250, 200, None, 0):
        clock[0] += timedelta(minutes=6)
        history.write('hydro:stations', hydro_response(clock[0], value=value))
    rows = repo.db.execute("SELECT value,revision,fetched_at,first_fetched_at,thresholds_json FROM station_measurements "
                           "WHERE object_ref=? AND metric='water_level' ORDER BY revision", (ref,)).fetchall()
    assert [r['value'] for r in rows] == [200, 250, 200, None, 0]
    assert [r['revision'] for r in rows] == [1, 2, 3, 4, 5]
    assert repo.db.execute("SELECT value FROM station_measurements WHERE object_ref=? AND metric='water_level' "
                           "AND is_current=1", (ref,)).fetchall()[0][0] == 0
    assert repo.db.execute("SELECT count(*) FROM station_measurements WHERE object_ref=? AND metric='water_level' "
                           "AND is_current=1", (ref,)).fetchone()[0] == 1
    assert len({r['first_fetched_at'] for r in rows}) == 1
    assert rows[0]['fetched_at'] == NOW.isoformat()
    assert json.loads(rows[0]['thresholds_json']) == {'warning_level_cm': 300, 'alarm_level_cm': 340}
    assert repo.db.execute('SELECT updated_at FROM catalog_objects WHERE ref=?', (ref,)).fetchone()[0] == original['observed_at']


def test_registry_renames_partial_failures_and_complete_empty_are_distinct(archive):
    repo, history, _ = archive
    response = hydro_response()
    ref = 'hydro_station:imgw:' + response['items'][0]['id']
    history.write('hydro:stations', response)
    history.write('hydro:stations', {**response, 'status': 'partial', 'items': [], 'rejected_count': 1})
    history.write('hydro:stations', {**response, 'status': 'error', 'items': []})
    metadata = lambda: json.loads(repo.db.execute('SELECT metadata_json FROM catalog_objects WHERE ref=?', (ref,)).fetchone()[0])
    assert metadata()['catalogue_present'] is True
    history.write('hydro:stations', {**response, 'status': 'empty', 'items': []})
    assert metadata()['catalogue_present'] is False
    response['items'][0]['name'] = 'Nowa nazwa tej samej stacji'
    history.write('hydro:stations', response)
    assert metadata()['catalogue_present'] is True
    assert repo.db.execute('SELECT COUNT(*) FROM catalog_objects WHERE type=?', ('hydro_station',)).fetchone()[0] == 1
    assert repo.db.execute('SELECT COUNT(*) FROM station_measurements').fetchone()[0] == 3


def test_separate_sensor_identity_official_index_and_reopen(archive):
    repo, history, _ = archive
    station_response, sensors = gios_response('stations'), gios_response('sensors')
    history.write('gios:stations', station_response)
    station_id = sensors['items'][0]['station_id']
    history.write(f'gios:sensors:{station_id}', sensors)
    same_parameter = [s for s in sensors['items'] if s['parameter'] == 'PM10']
    assert len(same_parameter) == 2
    for sensor in same_parameter:
        history.write(f'gios:data:{sensor["id"]}', gios_response('data'))
    history.write(f'gios:index:{station_id}', gios_response('index'))
    refs = repo.db.execute('SELECT DISTINCT object_ref,sensor_id,metric FROM station_measurements').fetchall()
    assert len(refs) == 2 and {r['sensor_id'] for r in refs} == {str(s['id']) for s in same_parameter}
    assert all(r['object_ref'] == f'air_quality_station:gios:{station_id}' for r in refs)
    index = repo.db.execute('SELECT * FROM station_index_observations').fetchone()
    assert index['value'] == 1 and index['observed_at'] != index['calculated_at']
    assert not repo.db.execute("SELECT 1 FROM station_measurements WHERE metric='official_index'").fetchone()
    # A new writer has no in-memory sensor registry; the persistent mapping is sufficient.
    second_writer = StationHistory(repo)
    second_writer.write(f'gios:data:{same_parameter[0]["id"]}', gios_response('data'))
    assert repo.db.execute('SELECT COUNT(*) FROM station_index_observations').fetchone()[0] == 1


def test_retention_does_not_renew_invalid_or_far_future_observations(archive):
    repo, history, clock = archive
    invalid = hydro_response(when='unknown')
    history.write('hydro:stations', invalid)
    future = hydro_response(when='2027-10-17 06:00:00')
    history.write('hydro:stations', future)
    assert {r[0] for r in repo.db.execute("SELECT quality FROM station_measurements WHERE metric='water_level'")} == {
        'future', 'unknown_time'}
    clock[0] += timedelta(days=13)
    history.write('hydro:stations', {**invalid, 'fetched_at': clock[0].isoformat()})
    clock[0] += timedelta(days=2)
    for response in (invalid, future):
        history.write('hydro:stations', {**response, 'fetched_at': clock[0].isoformat()})
    assert repo.db.execute('SELECT COUNT(*) FROM station_measurements').fetchone()[0] == 0
    assert repo.db.execute('SELECT COUNT(*) FROM catalog_objects').fetchone()[0] == 1
    assert repo.db.execute('SELECT COUNT(*) FROM station_observation_keys').fetchone()[0] >= 2
    assert all(r[0] >= (clock[0] - timedelta(days=14)).isoformat()
               for r in repo.db.execute('SELECT fetched_at FROM workspace_source_runs'))


@pytest.mark.asyncio
async def test_startup_maintenance_expires_idle_history_without_a_network_fetch(archive):
    repo, history, clock = archive
    history.write('hydro:stations', hydro_response())
    before = repo.db.execute('SELECT revision FROM catalog_objects').fetchone()[0]
    clock[0] += timedelta(days=15)
    history.start()
    await history.close()
    assert repo.db.execute('SELECT COUNT(*) FROM station_measurements').fetchone()[0] == 0
    assert repo.db.execute('SELECT revision FROM catalog_objects').fetchone()[0] > before
    assert history.status()['errors'] == {}


@pytest.mark.asyncio
async def test_source_cache_hits_do_not_archive_and_failures_preserve_good_data(archive):
    repo, history, clock = archive
    raw = json.loads((FIXTURES / 'imgw_hydro/hydro.json').read_text())
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=raw) if len(calls) == 1 else httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = HydroService(client, repo.clock, history=history)
        await asyncio.gather(*(service.fetch() for _ in range(4)))
        await history.flush()
        before = [dict(r) for r in repo.db.execute('SELECT * FROM station_measurements')]
        assert before and len(calls) == 1
        assert repo.db.execute('SELECT COUNT(*) FROM workspace_source_runs').fetchone()[0] == 1
        clock[0] += timedelta(minutes=6)
        failed = await service.fetch()
        await history.flush()
        assert failed['status'] == 'error'
        assert [dict(r) for r in repo.db.execute('SELECT * FROM station_measurements')] == before
        assert repo.db.execute('SELECT status FROM workspace_source_runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'error'
        await service.fetch()
        assert len(calls) == 2
    await history.close()


@pytest.mark.asyncio
async def test_gios_partial_new_response_saved_without_clearing_registry(archive):
    repo, history, _ = archive
    response = gios_response('stations')
    history.write('gios:stations', response)
    calls = []

    async with httpx.AsyncClient() as client:
        service = GiosService(client, repo.clock, history=history)

        async def download(kind, identity):
            calls.append((kind, identity))
            return {'status': 'partial', 'items': copy.deepcopy(response['items'][:1]), 'rejected_count': 2}

        service.download = download
        service.cache[('stations', None)] = (response, NOW - timedelta(days=2))
        result = await service.fetch()
        await history.flush()
        assert result['status'] == 'partial' and len(calls) == 1
        assert all(json.loads(r[0])['catalogue_present'] is True
                   for r in repo.db.execute('SELECT metadata_json FROM catalog_objects'))
        assert repo.db.execute('SELECT status FROM workspace_source_runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'partial'
        await service.fetch()
        await history.flush()
        assert len(calls) == 1
    await history.close()


@pytest.mark.asyncio
async def test_bounded_queue_and_writer_error_are_visible_without_crashing_sources(archive, monkeypatch):
    repo, _, _ = archive
    history = StationHistory(repo, queue_size=1)
    assert history.submit('hydro:stations', hydro_response()) is True
    assert history.submit('hydro:stations', hydro_response()) is False
    assert history.status()['rejected_submissions'] == 1
    assert 'hydro:stations' in history.status()['errors']
    await history.flush()
    assert 'hydro:stations' in history.status()['errors']
    assert history.submit('hydro:stations', hydro_response()) is True
    await history.flush()
    assert history.status()['errors'] == {}

    def fail(*args):
        raise OSError('private local path must not escape')

    monkeypatch.setattr(history, 'write', fail)
    assert history.submit('hydro:stations', hydro_response()) is True
    await history.flush()
    assert 'private' not in str(history.status())
    assert history.status()['errors']['hydro:stations']
    await history.close()
    assert history.submit('hydro:stations', hydro_response()) is False
