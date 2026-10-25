"""Real SQLite checkpointing and the semantic difference between gaps and exits."""
import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from wici.moving_ingestion import MovingIngestion
from wici.repository import Repository
from wici.sources.normalize import document, location
from wici.workspace_monitor import append_observation, evaluate
from wici.workspace_service import WorkspaceService

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path):
    repo = Repository(tmp_path/'monitor.sqlite', clock=lambda: NOW)
    service = WorkspaceService(repo)
    yield service
    repo.close()


def transport(workspace, transition='both'):
    area = workspace.areas.save({'name': 'Trójkąt', 'geometry': {
        'type': 'Polygon', 'coordinates': [[[20, 51], [22, 51], [20, 53], [20, 51]]]}})
    rule = workspace.rules.save({'name': 'Transport', 'template': 'transport', 'enabled': True,
                                 'config': {'area_id': area['id'], 'object_type': 'aircraft', 'transition': transition}})
    return rule, area


def observation(workspace, kind, ref, source, seconds, payload, identity=None, trusted=True):
    at = (NOW+timedelta(seconds=seconds)).isoformat()
    workspace.repo.clock = lambda: NOW+timedelta(seconds=max(0, seconds))
    with workspace.repo.lock, workspace.db:
        append_observation(workspace.repo, kind, ref, source, at, identity or [seconds, payload], payload, trusted)


def point(workspace, seconds, lon, lat, identity=None):
    observation(workspace, 'transport', 'aircraft:icao:abcdef', 'aircraft', seconds,
                {'longitude': lon, 'latitude': lat, 'object_type': 'aircraft'}, identity)


def events(workspace):
    return workspace.events.list()['items']


def test_boundary_and_true_polygon_not_bbox_entry_exit(workspace):
    rule, area = transport(workspace)
    point(workspace, 0, 21.8, 52.8)  # In bbox; outside the actual triangle.
    point(workspace, 10, 21, 52)  # On inclusive boundary.
    point(workspace, 20, 21.8, 52.8)
    workspace.monitor.process()
    descriptions = [item['description'] for item in events(workspace)]
    assert len(descriptions) == 2
    assert any('wejście' in value for value in descriptions)
    assert any('wyjście' in value for value in descriptions)
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unmet'
    evidence = workspace.events.detail(events(workspace)[0]['id'])['evidence']
    assert evidence['area']['revision'] == area['revision']


def test_first_inside_is_observation_not_confirmed_entry(workspace):
    transport(workspace)
    point(workspace, 0, 20.5, 51.5)
    workspace.monitor.process()
    assert len(events(workspace)) == 1
    assert 'brak potwierdzonego' in events(workspace)[0]['description']


def test_gap_never_becomes_exit_and_restart_deduplicates(workspace):
    rule, _ = transport(workspace)
    point(workspace, 0, 20.5, 51.5, 'first')
    workspace.monitor.process()
    observation(workspace, 'gap', '*', 'aircraft', 10, {'reason': 'error'}, trusted=False)
    workspace.monitor.process()
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    point(workspace, 20, 21.8, 52.8, 'outside')
    workspace.monitor.process()
    assert len(events(workspace)) == 1
    # New service simulates restart, preserving source epoch/checkpoint.
    other = WorkspaceService(workspace.repo)
    other.monitor.process()
    point(other, 20, 21.8, 52.8, 'outside')
    other.monitor.process()
    assert len(events(other)) == 1


def test_missing_object_and_old_report_do_not_infer_exit(workspace):
    rule, _ = transport(workspace)
    point(workspace, 0, 20.5, 51.5)
    workspace.monitor.process()
    workspace.repo.clock = lambda: NOW+timedelta(minutes=5)
    workspace.monitor.process()
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    point(workspace, 300, 21.8, 52.8)
    workspace.monitor.process()
    assert len(events(workspace)) == 1


def test_changed_rule_does_not_reprocess_old_stream(workspace):
    rule, _ = transport(workspace)
    point(workspace, 0, 20.5, 51.5)
    raw = {key: rule[key] for key in ('name', 'template', 'enabled', 'config', 'revision')}
    workspace.rules.save(dict(raw, priority='high'), rule['id'])
    workspace.monitor.process()
    assert events(workspace) == []


def measurement_rule(workspace):
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station('hydro_station:imgw:1', 'imgw', '1', 'Wodowskaz')
    return workspace.rules.save({'name': 'Próg', 'template': 'measurement', 'enabled': True,
                                 'config': {'object_ref': 'hydro_station:imgw:1', 'sensor_id': '',
                                            'metric': 'water_level', 'unit': 'cm', 'threshold': 60, 'return_threshold': 50}})


def measurement(workspace, seconds, value, identity=None, unit='cm'):
    observation(workspace, 'measurement', 'hydro_station:imgw:1', 'imgw', seconds,
                {'sensor_id': '', 'metric': 'water_level', 'unit': unit, 'value': value}, identity)


def test_hysteresis_null_not_zero_and_same_timestamp_correction(workspace):
    rule = measurement_rule(workspace)
    for seconds, value in [(0, 45), (10, 65), (20, 58), (30, 55), (40, 50), (50, 65)]:
        measurement(workspace, seconds, value)
    workspace.monitor.process()
    assert len(events(workspace)) == 2
    measurement(workspace, 50, 40, 'corrected')
    workspace.monitor.process()
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unmet'
    measurement(workspace, 60, None)
    workspace.monitor.process()
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    assert len(events(workspace)) == 2


def test_different_sensor_unit_and_source_gap_do_not_affect_rule(workspace):
    rule = measurement_rule(workspace)
    measurement(workspace, 0, 65)
    workspace.monitor.process()
    measurement(workspace, 10, 4, unit='m')
    observation(workspace, 'gap', '*', 'gios', 20, {'reason': 'error'}, trusted=False)
    workspace.monitor.process()
    assert len(events(workspace)) == 1
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'met'


def test_event_and_checkpoint_rollback_together_on_failure(workspace, monkeypatch):
    rule, _ = transport(workspace)
    point(workspace, 0, 20.5, 51.5)
    original = workspace.events.emit

    def failure(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Interrupted before checkpoint')

    monkeypatch.setattr(workspace.events, 'emit', failure)
    with pytest.raises(RuntimeError):
        workspace.monitor.process()
    assert events(workspace) == []
    assert workspace.rules.detail(rule['id'])['checkpoint_id'] == rule['checkpoint_id']
    monkeypatch.setattr(workspace.events, 'emit', original)
    workspace.monitor.process()
    assert len(events(workspace)) == 1


def test_communication_versions_and_preview_same_clock(workspace):
    workspace.rules.save({'name': 'Mazowsze', 'template': 'communication', 'enabled': True, 'config': {'admin_code': '14'}})
    value = document('rso', 'notice', 'https://example.org/source', 'Komunikat', 'Treść pierwsza',
                     {'locations': [location('14', 'notification_area', 'RSO')]}, [], source_published_at=NOW.isoformat())
    workspace.repo.ingest(value)
    value['text'] = 'Istotna aktualizacja'
    workspace.repo.ingest(value)
    workspace.repo.ingest(value)  # Cached representation does not enqueue again.
    workspace.monitor.process()
    assert len(events(workspace)) == 2
    rule = workspace.rules.list()['items'][0]
    raw = {key: rule[key] for key in ('name', 'template', 'enabled', 'config')}
    result = workspace.rules.preview({'rule': raw, 'from': NOW-timedelta(minutes=1), 'to': NOW+timedelta(minutes=1)})
    assert len(result['items']) == 2
    assert len(events(workspace)) == 2


def test_ukraine_change_gap_and_clear_have_distinct_semantics(workspace):
    ref = workspace.ukraine._region('oblast', '1', 'Obwód')
    with workspace.repo.lock, workspace.db:
        workspace.db.commit()
    rule = workspace.rules.save({'name': 'Alarm', 'template': 'ukraine', 'enabled': True, 'config': {'region_ref': ref}})
    for seconds, state in [(0, 'red'), (10, 'none'), (20, 'red')]:
        observation(workspace, 'ukraine', ref, 'ukraine_alerts', seconds, {'state': state})
    workspace.monitor.process()
    assert len(events(workspace)) == 3
    assert any(event['condition_state'] == 'unmet' for event in events(workspace))
    observation(workspace, 'gap', '*', 'ukraine_alerts', 30, {'reason': 'error'}, trusted=False)
    observation(workspace, 'ukraine', ref, 'ukraine_alerts', 40, {'state': 'none'})
    workspace.monitor.process()
    assert len(events(workspace)) == 3
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unmet'


@pytest.mark.asyncio
async def test_every_raw_transport_snapshot_survives_catalogue_coalescing(workspace):
    transport(workspace)
    writer = MovingIngestion(workspace.moving)
    try:
        for seconds, lon, lat in [(0, 21.8, 52.8), (10, 20.5, 51.5), (20, 21.8, 52.8)]:
            at = (NOW+timedelta(seconds=seconds)).isoformat()
            workspace.repo.clock = lambda: NOW+timedelta(seconds=20)
            writer.enqueue('aircraft', {'status': 'ready', 'fetched_at': at, 'items': [
                {'hex': 'abcdef', 'position_at': at, 'longitude': lon, 'latitude': lat}]})
        assert await writer.flush(5)
        workspace.monitor.process()
        assert len(events(workspace)) == 2
        assert writer.status()['coalesced_snapshots'] == 2
    finally:
        await writer.close()


@pytest.mark.asyncio
async def test_background_shares_sources_and_sensor_identity_is_integer(workspace):
    calls = []
    # Supply two rules for the same exact source resource.
    with workspace.repo.lock, workspace.db:
        workspace.catalog.upsert_station('air_quality_station:gios:1', 'gios', '1', 'Stacja')
        workspace.db.execute("INSERT INTO station_sensors VALUES('11','air_quality_station:gios:1','PM10','PM10','µg/m³','{}',?)", (NOW.isoformat(),))
    raw = {'name': 'PM10', 'template': 'measurement', 'enabled': True, 'mode': 'background', 'config': {
        'object_ref': 'air_quality_station:gios:1', 'sensor_id': '11', 'metric': 'PM10', 'unit': 'µg/m³', 'threshold': 60}}
    workspace.rules.save(raw)
    workspace.rules.save(dict(raw, name='Drugie kryterium'))

    class Source:
        async def fetch(self, kind, identity):
            assert isinstance(identity, int)
            calls.append((kind, identity))
            return {'status': 'ready'}

    workspace.monitor.bind(SimpleNamespace(gios=Source()))
    await workspace.monitor._background()
    await workspace.monitor._background()
    assert calls == [('sensors', 1), ('data', 11)]


def test_pure_preview_gap_resets_current_state(workspace):
    rule, area = transport(workspace)
    first = {'kind': 'transport', 'object_ref': 'aircraft:icao:abcdef', 'source_id': 'aircraft',
             'observed_at': NOW.isoformat(), 'trusted': True,
             'payload': {'longitude': 20.5, 'latitude': 51.5, 'object_type': 'aircraft'}}
    state, event = evaluate(rule, first, area=area)
    assert event['trigger'] == 'observed_inside'
    gap = dict(first, kind='gap', object_ref='*', trusted=False, observed_at=(NOW+timedelta(seconds=10)).isoformat())
    state, event = evaluate(rule, gap, state, area)
    assert state['condition_state'] == 'unknown' and event is None


def test_consumed_stream_is_compacted_under_pressure(workspace, monkeypatch):
    import wici.workspace_monitor as monitor_module
    monkeypatch.setattr(monitor_module, 'MAX_STREAM', 8)
    rule, _ = transport(workspace)
    for seconds in range(8):
        point(workspace, seconds, 20.5, 51.5)
    workspace.monitor.process()
    point(workspace, 9, 20.5, 51.5)
    workspace.monitor.process()
    assert workspace.monitor.status()['overload_at'] is None
    assert workspace.monitor.status()['retained_observations'] <= 8
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'met'
    assert len(events(workspace)) == 1


def test_unprocessed_overload_is_visible_and_breaks_continuity(workspace, monkeypatch):
    import wici.workspace_monitor as monitor_module
    monkeypatch.setattr(monitor_module, 'MAX_STREAM', 8)
    rule, _ = transport(workspace)
    for seconds in range(8):
        point(workspace, seconds, 20.5, 51.5)
    point(workspace, 9, 21.8, 52.8)  # Dropped: the checkpoint has not advanced.
    assert workspace.monitor.status()['overload_at'] is not None
    workspace.monitor.process()
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    point(workspace, 10, 21.8, 52.8)
    workspace.monitor.process()
    assert len(events(workspace)) == 1  # The lost observation cannot imply exit.


def test_restart_breaks_position_continuity_without_losing_checkpoint(workspace):
    rule, _ = transport(workspace)
    point(workspace, 0, 20.5, 51.5)
    workspace.monitor.process()
    prior = workspace.rules.detail(rule['id'])['checkpoint_id']
    resumed = WorkspaceService(workspace.repo)
    assert resumed.rules.detail(rule['id'])['checkpoint_id'] == prior
    assert resumed.rules.detail(rule['id'])['condition_state'] == 'unknown'
    point(resumed, 10, 21.8, 52.8)
    resumed.monitor.process()
    assert len(events(resumed)) == 1


def test_ukraine_actual_ingest_records_stream_with_history_disabled(workspace):
    with workspace.repo.lock, workspace.db:
        ref = workspace.ukraine._region('oblast', '1', 'Obwód')
    workspace.rules.save({'name': 'Alarm', 'template': 'ukraine', 'enabled': True, 'config': {'region_ref': ref}})
    active = {'scope': 'oblast', 'key': '1', 'name': 'Obwód', 'level': 'red', 'since': NOW.isoformat()}
    workspace.ukraine.ingest({'status': 'ready', 'fetched_at': NOW.isoformat(), 'items': [active]})
    workspace.monitor.process()
    assert workspace.db.execute('SELECT count(*) FROM workspace_ukraine_observations').fetchone()[0] == 0
    assert len(events(workspace)) == 1
    workspace.repo.clock = lambda: NOW+timedelta(seconds=10)
    workspace.ukraine.ingest({'status': 'error', 'fetched_at': None, 'items': []})
    workspace.repo.clock = lambda: NOW+timedelta(seconds=20)
    workspace.ukraine.ingest({'status': 'ready', 'fetched_at': (NOW+timedelta(seconds=20)).isoformat(), 'items': []})
    workspace.monitor.process()
    assert len(events(workspace)) == 1


@pytest.mark.asyncio
async def test_background_failure_stays_visible_and_resets_condition(workspace):
    rule = measurement_rule(workspace)
    raw = {key: rule[key] for key in ('name', 'template', 'enabled', 'config', 'revision')}
    workspace.rules.save(dict(raw, mode='background'), rule['id'])
    measurement(workspace, 0, 65)
    workspace.monitor.process()

    class Source:
        async def fetch(self):
            return {'status': 'error', 'stale': True}

    workspace.repo.clock = lambda: NOW+timedelta(seconds=10)
    workspace.monitor.bind(SimpleNamespace(hydro=Source()))
    await workspace.monitor._background()
    await asyncio.gather(*workspace.monitor.poll_tasks.values())
    workspace.monitor.process()
    await workspace.monitor._background()  # cache interval: no second fetch.
    assert workspace.monitor.status()['error']
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    assert workspace.rules.detail(rule['id'])['error']


def test_storage_recovery_marks_station_gap_before_new_measurement(workspace):
    from wici.station_history import StationHistory
    rule = measurement_rule(workspace)
    measurement(workspace, 0, 65)
    workspace.monitor.process()
    history = StationHistory(workspace.repo)
    history.errors['hydro:stations'] = 'Przepełnienie kolejki'
    history.error_generations['hydro:stations'] = 3
    workspace.repo.clock = lambda: NOW+timedelta(seconds=10)
    history.write('hydro:stations', {'status': 'ready', 'fetched_at': (NOW+timedelta(seconds=10)).isoformat(),
                                    'items': []}, generation=4)
    workspace.monitor.process()
    assert workspace.rules.detail(rule['id'])['condition_state'] == 'unknown'
    assert len(events(workspace)) == 1


def test_ukraine_storage_gap_does_not_invent_clear_transition(workspace):
    with workspace.repo.lock, workspace.db:
        ref = workspace.ukraine._region('oblast', '1', 'Obwód')
    workspace.rules.save({'name': 'Alarm', 'template': 'ukraine', 'enabled': True, 'config': {'region_ref': ref}})
    observation(workspace, 'ukraine', ref, 'ukraine_alerts', 0, {'state': 'red'})
    workspace.monitor.process()
    workspace.repo.clock = lambda: NOW+timedelta(seconds=10)
    workspace.ukraine.mark_gap('storage_error')
    observation(workspace, 'ukraine', ref, 'ukraine_alerts', 20, {'state': 'none'})
    workspace.monitor.process()
    assert len(events(workspace)) == 1


@pytest.mark.asyncio
async def test_slow_background_resource_does_not_block_evaluation_or_other_polls(workspace):
    slow_rule = measurement_rule(workspace)
    raw = {key: slow_rule[key] for key in ('name', 'template', 'enabled', 'config', 'revision')}
    slow_rule = workspace.rules.save(dict(raw, mode='background'), slow_rule['id'])
    transport(workspace)
    with workspace.repo.lock, workspace.db:
        ref = workspace.ukraine._region('oblast', 'independent', 'Obwód')
    workspace.rules.save({'name': 'Alarm w tle', 'template': 'ukraine', 'mode': 'background',
                          'enabled': True, 'config': {'region_ref': ref}})
    point(workspace, 0, 20.5, 51.5)
    entered, cancelled, polled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class SlowHydro:
        async def fetch(self):
            calls.append('hydro')
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    class Ukraine:
        async def geometry(self):
            return {'status': 'ready'}

        async def fetch_alerts(self):
            calls.append('ukraine')
            snapshot = {'status': 'ready', 'fetched_at': NOW.isoformat(), 'items': [{
                'scope': 'oblast', 'key': 'independent', 'name': 'Obwód', 'level': 'red'}]}
            await asyncio.to_thread(workspace.ukraine.ingest, snapshot)
            polled.set()
            return snapshot

    monitor = workspace.monitor.bind(SimpleNamespace(hydro=SlowHydro(), ukraine=Ukraine())).start()
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(polled.wait(), 1)

        async def detected():
            while len(events(workspace)) != 2:
                await asyncio.sleep(.01)

        await asyncio.wait_for(detected(), 2)
        assert not cancelled.is_set()
        await monitor._background()
        assert calls.count('hydro') == calls.count('ukraine') == 1
        assert len(monitor.poll_tasks) <= 2
        raw['revision'] = slow_rule['revision']
        workspace.rules.save(dict(raw, enabled=False, mode='background'), slow_rule['id'])
        await monitor._background()
        await asyncio.wait_for(cancelled.wait(), 1)
        assert not any(key.startswith('hydro|') for key in monitor.source_errors)
    finally:
        await monitor.close()
    assert not monitor.poll_tasks
    assert monitor.worker is None


@pytest.mark.asyncio
async def test_stop_polling_joins_started_source_gap_write(workspace, monkeypatch):
    rule = measurement_rule(workspace)
    raw = {key: rule[key] for key in ('name', 'template', 'enabled', 'config', 'revision')}
    workspace.rules.save(dict(raw, mode='background'), rule['id'])

    class Source:
        async def fetch(self):
            return {'status': 'error'}

    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    original = workspace.monitor._source_gap

    def blocked_write(*args):
        entered.set()
        assert release.wait(3)
        original(*args)
        completed.set()

    monkeypatch.setattr(workspace.monitor, '_source_gap', blocked_write)
    workspace.monitor.bind(SimpleNamespace(hydro=Source()))
    await workspace.monitor._background()
    assert await asyncio.to_thread(entered.wait, 1)
    stopping = asyncio.create_task(workspace.monitor.stop_polling())
    try:
        await asyncio.sleep(0)
        assert not stopping.done()
        assert not completed.is_set()
    finally:
        release.set()
        await asyncio.wait_for(stopping, 2)
    assert completed.is_set()
    assert not workspace.monitor.poll_tasks
    await workspace.monitor.close()


@pytest.mark.asyncio
async def test_gios_poll_waits_for_refreshed_sensor_metadata_before_samples(workspace, monkeypatch):
    from wici.gios import GiosService, normalize
    from wici.station_history import StationHistory

    history = StationHistory(workspace.repo)
    history.write('gios:sensors:1', {'status': 'ready', 'fetched_at': NOW.isoformat(), 'items': [
        {'id': 10, 'station_id': 1, 'parameter': 'PM10', 'name': 'PM10', 'unit': 'µg/m³'}]})
    rule = workspace.rules.save({'name': 'PM10', 'template': 'measurement', 'enabled': True,
        'mode': 'background', 'config': {'object_ref': 'air_quality_station:gios:1',
        'sensor_id': '10', 'metric': 'PM10', 'unit': 'µg/m³', 'threshold': 50}})
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    service = GiosService(None, lambda: NOW, history=history)

    async def download(kind, identity):
        calls.append((kind, identity))
        if kind == 'sensors':
            entered.set()
            await release.wait()
            raw = [{'Identyfikator stanowiska': 10, 'Identyfikator stacji': 1, 'Wskaźnik - kod': 'PM2.5'}]
        else:
            raw = [{'Data': '2026-10-25 13:00:00', 'Wartość': 65}]
        items, rejected = normalize(kind, raw)
        return {'status': 'ready', 'items': items, 'rejected_count': rejected}

    monkeypatch.setattr(service, 'download', download)
    workspace.monitor.bind(SimpleNamespace(gios=service))
    try:
        await workspace.monitor._background()
        await asyncio.wait_for(entered.wait(), 1)
        assert calls == [('sensors', 1)]
        release.set()
        await asyncio.gather(*workspace.monitor.poll_tasks.values())
        await history.flush()
        workspace.monitor.process()
        assert calls == [('sensors', 1), ('data', 10)]
        assert workspace.db.execute('SELECT metric FROM station_measurements').fetchone()[0] == 'PM2.5'
        assert workspace.events.list(rule_id=rule['id'])['total'] == 0
    finally:
        release.set()
        await workspace.monitor.stop_polling()
        await history.close()
