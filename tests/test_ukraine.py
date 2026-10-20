"""Offline NEPTUN transport, schema, freshness and cache regressions."""
import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from wici.ukraine import (
    ALERTS_URL,
    MAX_BYTES,
    MAX_GEOMETRY_BYTES,
    OBLASTS_URL,
    RAIONS_URL,
    THREATS_URL,
    UkraineService,
)

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def alert(**updates):
    return {'key': 'київський', 'name': 'Київський район', 'oblast': 'Київська область',
            'level': 'red', 'since': NOW.isoformat(), 'reasons': ['Повітряна тривога'], **updates}


def alerts(*items, **updates):
    return {'version': 12, 'updatedAt': NOW.isoformat(), 'raions': list(items), 'oblasts': [], **updates}


def threat(**updates):
    return {'id': 'sample-1', 'type': 'uav', 'title': 'БпЛА', 'region': 'Київська область',
            'district': '', 'locality': 'Київ', 'lat': 50.45, 'lon': 30.52,
            'updatedAt': NOW.isoformat(), 'status': 'active', 'positionQuality': 'approx',
            'uncertaintyKm': 4, 'confidenceLevel': 'medium', 'sourceCount': 2,
            'explanationShort': 'Повідомлення про загрозу', **updates}


def threats(*items, now=NOW, **updates):
    return {'epoch': 'test-epoch', 'seq': 4, 'serverTime': now.isoformat(), 'threats': list(items), **updates}


def feature(kind='oblasts', **updates):
    return {'type': 'Feature', 'properties': {'key': 'київський',
            ('region' if kind == 'oblasts' else 'rayon'): 'Київський'},
            'geometry': {'type': 'Polygon', 'coordinates': [
                [[30, 50], [31, 50], [31, 51], [30, 51], [30, 50]]]}, **updates}


def geometry(*items):
    return {'type': 'FeatureCollection', 'features': list(items)}


@pytest.mark.asyncio
async def test_lazy_shared_cache_concurrent_viewers_and_copies():
    calls, now = [], [NOW]

    async def handler(request):
        calls.append(request)
        assert request.extensions['timeout']['read'] == 10
        await asyncio.sleep(0)
        return httpx.Response(200, json=(alerts(alert()) if str(request.url) == ALERTS_URL
                                        else threats(threat(), now=now[0])))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0], timeout=60)
        assert not calls
        results = await asyncio.gather(*(service.fetch() for _ in range(6)))
        assert len(calls) == 2 and {str(r.url) for r in calls} == {ALERTS_URL, THREATS_URL}
        assert all(result == results[0] for result in results)
        assert results[0]['status'] == 'ready' and results[0]['refresh_seconds'] == 15
        results[0]['alerts']['items'][0]['reasons'].append('mutated')
        assert len((await service.fetch())['alerts']['items'][0]['reasons']) == 1
        now[0] += timedelta(seconds=14)
        await service.fetch()
        assert len(calls) == 2
        now[0] += timedelta(seconds=1)
        await service.fetch()
        assert len(calls) == 4


def test_alert_state_change_time_is_not_a_heartbeat_and_exact_keys_preserved():
    data = alerts(alert(since='2022-12-10T22:22:00Z', reasons=None),
                  updatedAt='2026-01-02T10:00:00.123456789Z',
                  oblasts=[alert(key='київська область', level='yellow')])
    result = UkraineService.normalize_alerts(data, NOW)
    assert result['status'] == 'ready'
    assert result['items'][0]['key'] == 'київський' and result['items'][0]['reasons'] == []
    assert result['items'][1]['scope'] == 'oblast' and result['items'][1]['level'] == 'yellow'
    assert result['updated_at'] == '2026-01-02T10:00:00.123456+00:00'


def test_malformed_alert_records_do_not_claim_all_clear():
    result = UkraineService.normalize_alerts(alerts(alert(level='purple'), alert(), None,
              alert(key='other', since='2026-10-17T12:00:00'), alert(key='bad', reasons=False)), NOW)
    assert result['status'] == 'partial' and result['invalid_count'] == 5
    assert len(result['items']) == 2 and result['items'][0]['level'] == 'unknown'
    assert result['items'][1]['since'] is None
    for update in ({'raions': {}}, {'version': True}, {'updatedAt': 'bad'},
                   {'updatedAt': (NOW+timedelta(seconds=31)).isoformat()}):
        with pytest.raises(ValueError):
            UkraineService.normalize_alerts(alerts(**update), NOW)


def test_area_only_advisory_and_no_motion_prediction_fields():
    raw = threat(areaOnly=True, advisory=True, heading=123, velocity=100,
                 trail=[{'lat': 50, 'lon': 30}], destination='Somewhere',
                 presumptiveCourse=True, count=2)
    item = UkraineService.normalize_threats(threats(raw), NOW)['items'][0]
    assert item['area_only'] and item['advisory']
    assert item['latitude'] is None and item['longitude'] is None
    assert item['count'] == 2 and item['source_count'] == 2 and item['uncertainty_km'] == 4
    assert item['position_quality'] == 'approx' and item['confidence'] == 'medium'
    assert not {'heading', 'velocity', 'trail', 'destination', 'presumptiveCourse'} & item.keys()


def test_threats_exclude_resolved_stale_and_invalid_time_with_diagnostics():
    records = [threat(), threat(id='old', updatedAt=(NOW-timedelta(seconds=421)).isoformat()),
               threat(id='stale', status='stale'), threat(id='resolved', status='resolved'),
               threat(id='naive', updatedAt='2026-10-17T12:00:00'),
               threat(id='future', updatedAt=(NOW+timedelta(seconds=31)).isoformat()),
               threat(id='flag', areaOnly='false'), threat(id='flag2', advisory=1),
               threat(id='bad-status', status='whatever'), threat(), None]
    result = UkraineService.normalize_threats(threats(*records), NOW)
    assert result['status'] == 'partial' and result['stale_count'] == 2 and result['invalid_count'] == 7
    assert [item['id'] for item in result['items']] == ['sample-1']
    for update in ({'serverTime': '2026-10-17T12:00:00'}, {'seq': True}, {'threats': {}},
                   {'serverTime': (NOW-timedelta(seconds=421)).isoformat()}):
        with pytest.raises(ValueError):
            UkraineService.normalize_threats(threats(**update), NOW)


@pytest.mark.parametrize('updates', [
    {'lat': True}, {'lat': '50.45'}, {'lat': float('nan')}, {'lon': 21}, {'lat': 54},
    {'sourceCount': True}, {'count': -1}, {'uncertaintyKm': float('inf')},
    {'positionQuality': 'prediction'}, {'confidenceLevel': '100%'},
])
def test_invalid_optional_values_are_explicit_partial(updates):
    result = UkraineService.normalize_threats(threats(threat(**updates)), NOW)
    assert result['status'] == 'partial' and result['invalid_count'] == 1
    item = result['items'][0]
    if 'lat' in updates or 'lon' in updates:
        assert item['latitude'] is None and item['longitude'] is None


@pytest.mark.asyncio
async def test_partial_failure_keeps_alerts_and_independently_refreshes_threats():
    calls, now = [], [NOW]

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == ALERTS_URL:
            if calls.count(ALERTS_URL) > 1:
                raise httpx.ReadTimeout('timeout')
            return httpx.Response(200, json=alerts(alert()))
        return httpx.Response(200, json=threats(threat(updatedAt=now[0].isoformat()), now=now[0]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=16)
        result = await service.fetch()
        assert result['status'] == 'partial' and result['alerts']['status'] == 'error'
        assert result['alerts']['stale'] and result['alerts']['items']
        assert result['alerts']['fetched_at'] == NOW.isoformat()
        assert result['threats']['status'] == 'ready' and result['retry_after_seconds'] == 15
        now[0] += timedelta(seconds=16)
        result = await service.fetch()
        assert calls.count(ALERTS_URL) == 2 and calls.count(THREATS_URL) == 3
        assert result['alerts']['stale']


@pytest.mark.asyncio
async def test_cached_threats_expire_without_reviving_old_snapshot():
    calls, now = [], [NOW]

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == ALERTS_URL:
            return httpx.Response(200, json=alerts())
        if calls.count(THREATS_URL) == 1:
            return httpx.Response(200, json=threats(threat()))
        return httpx.Response(200, json=threats())  # Old serverTime, not an all-clear snapshot.

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=421)
        result = await service.fetch()
        assert result['status'] == 'partial' and result['threats']['status'] == 'error'
        assert result['threats']['stale'] and not result['threats']['items']
        assert result['threats']['stale_count'] == 1 and result['threats']['fetched_at'] == NOW.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize('retry_after', ['180', format_datetime(NOW+timedelta(seconds=180), usegmt=True)])
async def test_rate_limit_is_per_source_and_honors_seconds_or_http_date(retry_after):
    calls, now = [], [NOW]

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == THREATS_URL:
            return httpx.Response(200, json=threats(now=now[0]))
        if calls.count(ALERTS_URL) == 1:
            return httpx.Response(429, headers={'Retry-After': retry_after})
        return httpx.Response(200, json=alerts())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        assert (await service.fetch())['status'] == 'partial'
        now[0] += timedelta(seconds=179)
        assert (await service.fetch())['alerts']['status'] == 'error'
        assert calls.count(ALERTS_URL) == 1 and calls.count(THREATS_URL) == 2
        now[0] += timedelta(seconds=1)
        result = await service.fetch()
        assert calls.count(ALERTS_URL) == 2 and result['status'] == 'ready'


@pytest.mark.asyncio
@pytest.mark.parametrize('retry_after', ['', 'NaN', 'nonsense', '9'*50, '-100'])
async def test_malformed_retry_after_stays_bounded(retry_after):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={'Retry-After': retry_after}))) as client:
        service = UkraineService(client, lambda: NOW)
        assert (await service.fetch())['status'] == 'error'
        assert 60 <= (service.states['alerts']['retry']-NOW).total_seconds() <= 86400


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    httpx.Response(200, json={}),
    httpx.Response(200, content=b'{bad', headers={'Content-Type': 'application/json'}),
    httpx.Response(200, content=b'{}', headers={'Content-Type': 'text/html'}),
    httpx.Response(200, content=b' '*(MAX_BYTES+1), headers={'Content-Type': 'application/json'}),
    httpx.Response(302, headers={'Location': 'https://example.com/'}),
])
async def test_bad_payloads_and_redirects_are_bounded_and_not_followed(response):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await UkraineService(client, lambda: NOW).fetch()
        assert result['status'] == 'error' and result['message']
        assert not result['alerts']['items'] and not result['threats']['items']
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_geometry_runtime_cache_partial_failure_and_shared_copies():
    calls, now = [], [NOW]

    def handler(request):
        calls.append(str(request.url))
        kind = 'oblasts' if str(request.url) == OBLASTS_URL else 'raions'
        if kind == 'raions' and calls.count(RAIONS_URL) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=geometry(feature(kind)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        result = await service.geometry()
        assert result['status'] == 'partial' and len(result['oblasts']['features']) == 1
        assert result['raions']['features'] == []
        result['oblasts']['features'][0]['properties']['key'] = 'mutated'
        now[0] += timedelta(seconds=60)
        results = await asyncio.gather(*(service.geometry() for _ in range(3)))
        assert all(item['status'] == 'ready' for item in results)
        assert calls.count(OBLASTS_URL) == 1 and calls.count(RAIONS_URL) == 2
        assert results[0]['oblasts']['features'][0]['properties']['key'] == 'київський'
        now[0] += timedelta(hours=24)
        await service.geometry()
        assert calls.count(OBLASTS_URL) == 2 and calls.count(RAIONS_URL) == 3


def test_geometry_rejects_invalid_shapes_and_duplicate_keys():
    bad = feature(geometry={'type': 'Polygon', 'coordinates': [[[0, 0], [1, 1], [0, 0]]]})
    unique = feature(properties={'key': 'унікальний', 'region': 'Унікальний'})
    result = UkraineService.normalize_geometry(geometry(feature(), feature(), bad, None, unique), 'region')
    assert result['status'] == 'partial' and result['invalid_count'] == 4
    assert len(result['collection']['features']) == 1
    assert result['collection']['features'][0]['properties']['key'] == 'унікальний'
    with pytest.raises(ValueError):
        UkraineService.normalize_geometry(geometry(bad), 'region')


def test_kyiv_city_geometry_and_oblast_alert_without_parent_name():
    result = UkraineService.normalize_geometry(geometry(feature(properties={
        'key': 'м. київ', 'name': 'м. Київ'})), 'region')
    assert result['status'] == 'ready'
    assert result['collection']['features'][0]['properties'] == {'key': 'м. київ', 'region': 'м. Київ'}
    result = UkraineService.normalize_alerts(alerts(oblasts=[alert(key='м. київ', oblast='')]), NOW)
    assert result['status'] == 'ready' and result['items'][0]['oblast'] is None
    result = UkraineService.normalize_alerts(alerts(alert(since=None)), NOW)
    assert result['status'] == 'partial' and result['items'][0]['since'] is None


@pytest.mark.asyncio
async def test_geometry_payload_limit():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=b' '*(MAX_GEOMETRY_BYTES+1), headers={'Content-Type': 'application/geo+json'}))) as client:
        result = await UkraineService(client, lambda: NOW).geometry()
        assert result['status'] == 'error' and result['oblasts']['features'] == []


@pytest.mark.asyncio
async def test_demo_disabled_never_connect_and_return_explicit_empty_geometry():
    def handler(request):
        raise AssertionError('No external requests permitted')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for settings, expected in [({'demo': True}, 'demo_no_data'), ({'enabled': False}, 'disabled')]:
            service = UkraineService(client, lambda: NOW, **settings)
            result = await service.fetch()
            boundaries = await service.geometry()
            assert result['status'] == expected and boundaries['status'] == expected
            assert result['alerts']['items'] == result['threats']['items'] == []
            assert boundaries['oblasts']['features'] == boundaries['raions']['features'] == []


@pytest.mark.asyncio
async def test_slow_response_gets_full_cache_lifetime_after_publication():
    calls, now = [], [NOW]

    async def handler(request):
        calls.append(request)
        now[0] += timedelta(seconds=8)
        return httpx.Response(200, json=alerts() if str(request.url) == ALERTS_URL else threats(now=now[0]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=6)
        await service.fetch()
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_total_request_deadline_bounds_a_never_finishing_stream(monkeypatch):
    monkeypatch.setattr('wici.ukraine.MAX_REQUEST_SECONDS', 0.01)

    class TrickleStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                yield b' '
                await asyncio.sleep(0.001)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, stream=TrickleStream(), headers={'Content-Type': 'application/json'}))) as client:
        result = await UkraineService(client, lambda: NOW).fetch()
        assert result['status'] == 'error' and result['alerts']['error'] and result['threats']['error']


@pytest.mark.asyncio
async def test_cached_threat_ages_out_before_the_next_network_refresh():
    calls, now = [], [NOW]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=alerts() if str(request.url) == ALERTS_URL else threats(
            threat(updatedAt=(NOW-timedelta(seconds=415)).isoformat())))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        assert (await service.fetch())['threats']['items']
        now[0] += timedelta(seconds=6)
        result = await service.fetch()
        assert len(calls) == 2 and result['threats']['items'] == []
        assert result['threats']['status'] == 'partial' and result['threats']['stale_count'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['alerts', 'threats'])
async def test_source_time_rollback_preserves_newer_cache_and_equal_time_can_refresh(source):
    now, attempt = [NOW], {'alerts': 0, 'threats': 0}

    def handler(request):
        key = 'alerts' if str(request.url) == ALERTS_URL else 'threats'
        attempt[key] += 1
        rolled_back = key == source and attempt[key] == 2
        source_time = NOW-timedelta(seconds=1) if rolled_back else NOW
        if key == 'alerts':
            data = alerts(*([] if rolled_back else [alert()]), updatedAt=source_time.isoformat())
        else:
            data = threats(*([] if rolled_back else [threat()]), now=source_time)
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = UkraineService(client, lambda: now[0])
        first = await service.fetch()
        now[0] += timedelta(seconds=16)
        result = await service.fetch()
        other = 'threats' if source == 'alerts' else 'alerts'
        assert result['status'] == 'partial'
        assert result[source]['status'] == 'error' and result[source]['stale']
        assert result[source]['items'] == first[source]['items']
        assert result[source]['fetched_at'] == NOW.isoformat()
        assert result[other]['status'] == 'ready' and result[other]['fetched_at'] == now[0].isoformat()
        now[0] += timedelta(seconds=60)
        result = await service.fetch()
        assert result['status'] == 'ready' and not result[source]['stale']
        assert result[source]['fetched_at'] == now[0].isoformat()
        assert result[source]['items'] == first[source]['items']
        assert attempt == {'alerts': 3, 'threats': 3}
