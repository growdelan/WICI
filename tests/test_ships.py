"""Offline AIS normalization, source freshness and shared stream lifecycle checks."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from wici.ships import ShipService

NOW = datetime(2026, 10, 14, 18, tzinfo=UTC)
MMSI = 261000001


def test_newer_report_outside_water_mask_removes_previous_visible_position():
    service = ShipService(lambda: NOW)
    assert service.ingest(envelope())
    assert len(service.snapshot()['items']) == 1
    assert not service.ingest(envelope(Latitude=53.54, Longitude=9.96))
    assert service.snapshot()['items'] == []
    # The same rule applies beyond the coarse subscription envelope.
    assert service.ingest(envelope())
    assert not service.ingest(envelope(Latitude=52, Longitude=8))
    assert service.snapshot()['items'] == []


def test_old_outside_report_cannot_remove_newer_baltic_position():
    service = ShipService(lambda: NOW)
    assert service.ingest(envelope())
    assert not service.ingest(envelope(at=NOW-timedelta(seconds=1), Latitude=53.54, Longitude=9.96))
    assert not service.ingest(envelope(Latitude=91))
    assert len(service.snapshot()['items']) == 1


def envelope(kind='PositionReport', *, at=NOW, mmsi=MMSI, **updates):
    report = {'UserID': mmsi, 'Latitude': 54.5, 'Longitude': 18.6,
              'Sog': 12.4, 'Cog': 120.5, 'TrueHeading': 121, **updates}
    return {'MessageType': kind,
            'MetaData': {'MMSI': mmsi, 'ShipName': ' BALTIC TEST ',
                         'time_utc': at.isoformat() if isinstance(at, datetime) else at},
            'Message': {kind: report}}


class Stream:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.sent = []
        self.subscribed = asyncio.Event()
        self.closed = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed.set()

    async def send(self, value):
        self.sent.append(json.loads(value))
        self.subscribed.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.messages.get()

    async def recv(self):
        return await self.messages.get()


@pytest.fixture
async def feed():
    now, calls, stream = [NOW], [], Stream()

    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        return stream

    service = ShipService(lambda: now[0], key='offline-test-key', connector=connect)
    yield service, now, calls, stream
    await service.stop()


@pytest.mark.parametrize('kind', [
    'PositionReport', 'StandardClassBPositionReport', 'ExtendedClassBPositionReport',
])
async def test_position_report_types_and_provider_timestamp(feed, kind):
    service, _, _, _ = feed
    service.ingest(envelope(kind, at='2026-10-14 18:00:00.000000 +0000 UTC'))
    items = (await service.fetch())['items']
    assert len(items) == 1
    item = items[0]
    assert str(item['mmsi']) == str(MMSI)
    assert item['latitude'] == 54.5 and item['longitude'] == 18.6
    assert item['name'] == 'BALTIC TEST'
    assert item['speed_knots'] == 12.4 and item['course'] == 120.5 and item['heading'] == 121
    assert datetime.fromisoformat(item['position_at']) == NOW


@pytest.mark.parametrize('updates', [
    {'Latitude': 91}, {'Longitude': 181}, {'Latitude': 'nan'},
    {'Latitude': True}, {'Longitude': None}, {'Latitude': 52.9},
    {'Latitude': 66.1}, {'Longitude': 8.9}, {'Longitude': 31.1},
])
async def test_invalid_and_outside_baltic_positions_are_ignored(feed, updates):
    service, _, _, _ = feed
    service.ingest(envelope(**updates))
    assert (await service.fetch())['items'] == []


@pytest.mark.parametrize('at', ['garbage', '', NOW-timedelta(seconds=901), NOW+timedelta(hours=1)])
async def test_missing_invalid_old_and_future_source_time_are_ignored(feed, at):
    service, _, _, _ = feed
    service.ingest(envelope(at=at))
    assert (await service.fetch())['items'] == []


async def test_unavailable_navigation_sentinels_and_snapshot_isolation(feed):
    service, _, _, _ = feed
    service.ingest(envelope(Sog=102.3, Cog=360, TrueHeading=511))
    item = (await service.fetch())['items'][0]
    assert item['speed_knots'] is None and item['course'] is None and item['heading'] is None
    item['name'] = 'caller mutation'
    assert (await service.fetch())['items'][0]['name'] == 'BALTIC TEST'


async def test_metadata_merges_without_refreshing_position_age(feed):
    service, now, _, _ = feed
    service.ingest(envelope())
    now[0] += timedelta(seconds=800)
    service.ingest(envelope('ShipStaticData', at=now[0], Name=' NEW NAME ', ImoNumber=1234567,
                            Type=70, Destination=' GDANSK '))
    item = (await service.fetch())['items'][0]
    assert item['name'] == 'NEW NAME' and item['destination'] == 'GDANSK'
    assert str(item['imo']) == '1234567' and item['type_code'] == 70
    assert datetime.fromisoformat(item['position_at']) == NOW
    now[0] += timedelta(seconds=101)
    assert (await service.fetch())['items'] == []


async def test_older_position_does_not_replace_newer_and_static_only_is_not_a_position(feed):
    service, _, _, _ = feed
    service.ingest(envelope('ShipStaticData', mmsi=261000002, Name='STATIC ONLY'))
    service.ingest(envelope())
    service.ingest(envelope(at=NOW-timedelta(seconds=30), Latitude=55))
    items = (await service.fetch())['items']
    assert len(items) == 1 and items[0]['latitude'] == 54.5
    assert datetime.fromisoformat(items[0]['position_at']) == NOW


@pytest.mark.parametrize('settings', [{'key': ''}, {'enabled': False, 'key': 'test'},
                                      {'demo': True, 'key': 'test'}])
async def test_missing_key_disabled_and_demo_never_connect(settings):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline modes must not open upstream connections')
    service = ShipService(lambda: NOW, connector=forbidden, **settings)
    try:
        data = await service.fetch()
        await asyncio.sleep(0)
        assert data['items'] == [] and data['message']
        assert data['refresh_seconds'] == 10
    finally:
        await service.stop()


async def test_concurrent_fetch_shares_subscription_and_shutdown_closes_stream(feed):
    service, _, calls, stream = feed
    assert calls == []
    await asyncio.gather(*(service.fetch() for _ in range(8)))
    await asyncio.wait_for(stream.subscribed.wait(), timeout=1)
    assert len(calls) == 1 and len(stream.sent) == 1
    subscription = stream.sent[0]
    assert subscription['APIKey'] == 'offline-test-key'
    assert subscription['BoundingBoxes'] == [[[53, 9], [66, 31]]]
    await service.stop()
    assert stream.closed.is_set()


async def test_class_b_static_parts_merge_by_mmsi(feed):
    service, _, _, _ = feed
    service.ingest(envelope('StandardClassBPositionReport'))
    service.ingest(envelope('StaticDataReport', PartNumber=0,
                            ReportA={'Name': 'CLASS B NAME'}))
    service.ingest(envelope('StaticDataReport', PartNumber=1,
                            ReportB={'ShipType': 36, 'CallSign': 'SPTEST'}))
    item = (await service.fetch())['items'][0]
    assert item['name'] == 'CLASS B NAME' and item['type_code'] == 36
    assert datetime.fromisoformat(item['position_at']) == NOW


async def test_malformed_envelopes_do_not_break_later_valid_position(feed):
    service, _, _, _ = feed
    for value in (None, [], {}, {'MessageType': 'PositionReport'},
                  {'MessageType': 'PositionReport', 'Message': {'PositionReport': []}},
                  {'error': 'Invalid API key'}):
        service.ingest(value)
    service.ingest(envelope())
    assert len((await service.fetch())['items']) == 1


async def test_demand_lease_renews_then_idle_stream_closes():
    stream = Stream()
    service = ShipService(lambda: NOW, key='offline-key', connector=lambda *args, **kw: stream,
                          idle_seconds=.08)
    try:
        await service.fetch()
        await asyncio.wait_for(stream.subscribed.wait(), timeout=1)
        await asyncio.sleep(.05)
        await service.fetch()
        await asyncio.sleep(.05)
        assert not stream.closed.is_set()
        await asyncio.wait_for(stream.closed.wait(), timeout=1)
        await asyncio.wait_for(service.task, timeout=1)
    finally:
        await service.stop()


async def test_stream_message_and_provider_error_preserve_fresh_positions_without_secret(feed):
    service, _, _, stream = feed
    await service.fetch()
    await asyncio.wait_for(stream.subscribed.wait(), timeout=1)
    await stream.messages.put(json.dumps(envelope()))
    for _ in range(100):
        if service.snapshot()['status'] == 'ready':
            break
        await asyncio.sleep(.001)
    assert service.snapshot()['status'] == 'ready'
    await stream.messages.put(json.dumps({'error': 'echo offline-test-key'}))
    for _ in range(100):
        if service.snapshot()['status'] == 'error':
            break
        await asyncio.sleep(.001)
    data = service.snapshot()
    assert data['status'] == 'error' and data['stale'] and len(data['items']) == 1
    assert 'offline-test-key' not in json.dumps(data)


@pytest.mark.parametrize('updates', [{'Latitude': 10**1000}, {'Longitude': -(10**1000)}])
async def test_oversized_numeric_coordinates_are_rejected_without_crashing(feed, updates):
    service, _, _, _ = feed
    assert not service.ingest(envelope(**updates))
    assert service.snapshot()['items'] == []


async def test_oversized_mmsi_and_extreme_timestamp_are_rejected_without_crashing(feed):
    service, _, _, _ = feed
    assert not service.ingest(envelope(mmsi=10**1000))
    assert not service.ingest(envelope(at='0001-01-01T00:00:00+14:00'))
    assert service.snapshot()['items'] == []


async def test_provider_nanosecond_timestamp_and_boolean_class_b_parts(feed):
    service, _, _, _ = feed
    assert service.ingest(envelope(at='2026-10-14 18:00:00.000000123 +0000 UTC'))
    assert service.ingest(envelope('StaticDataReport', PartNumber=False,
                                   ReportA={'Name': 'LIVE BOOLEAN PART'}))
    assert service.ingest(envelope('StaticDataReport', PartNumber=True,
                                   ReportB={'ShipType': 36}))
    item = service.snapshot()['items'][0]
    assert datetime.fromisoformat(item['position_at']) == NOW
    assert item['name'] == 'LIVE BOOLEAN PART' and item['type_code'] == 36
