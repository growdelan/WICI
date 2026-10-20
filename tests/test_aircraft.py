"""Offline adsb.fi transport, unit, freshness and geographic boundary checks."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wici.aircraft import AIRCRAFT_URL, MAX_BYTES, AircraftService, in_poland

NOW = datetime(2026, 10, 14, 18, tzinfo=UTC)


def aircraft(**updates):
    return {'hex': '48abcd', 'flight': 'LOT3JK  ', 'r': 'SP-LIO', 't': 'E75S',
            'type': 'adsb_icao', 'category': 'A3', 'lat': 52.23, 'lon': 21.01,
            'alt_baro': 10000, 'gs': 250, 'track': 120, 'seen_pos': 3.5, **updates}


def payload(*items, now=NOW):
    return {'now': now.timestamp()*1000, 'msg': 'No error', 'ac': list(items)}


@pytest.mark.asyncio
async def test_lazy_cached_concurrent_fetch_and_units():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        assert str(request.url) == AIRCRAFT_URL
        assert request.url.host == 'opendata.adsb.fi'
        assert request.url.path == '/api/v3/lat/52.05/lon/19.2/dist/250'
        assert request.extensions['timeout']['read'] == 10
        return httpx.Response(200, json=payload(aircraft(), now=now[0]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: now[0], timeout=20)
        assert calls == []
        results = await asyncio.gather(*(service.fetch() for _ in range(6)))
        assert len(calls) == 1 and all(result == results[0] for result in results)
        assert results[0]['source_name'] == 'adsb.fi'
        assert results[0]['source_url'] == 'https://adsb.fi/'
        assert results[0]['refresh_seconds'] == 10
        item = results[0]['items'][0]
        assert item['id'] == 'LOT3JK' and item['registration'] == 'SP-LIO' and item['type_code'] == 'E75S'
        assert item['altitude_m'] == 3048 and item['speed_kmh'] == 463 and item['track'] == 120
        assert item['position_at'] == (NOW-timedelta(seconds=3.5)).isoformat()
        # Callers cannot accidentally mutate the shared snapshot.
        item['id'] = 'mutated'
        assert (await service.fetch())['items'][0]['id'] == 'LOT3JK'
        now[0] += timedelta(seconds=9)
        await service.fetch()
        assert len(calls) == 1
        now[0] += timedelta(seconds=1)
        await service.fetch()
        assert len(calls) == 2


def test_exact_poland_filter_and_ground_nonaircraft_stale_exclusions():
    assert in_poland(52.23, 21.01) and in_poland(50.06, 19.94)
    assert not in_poland(52.52, 13.4)
    assert not in_poland(50.08, 14.43)  # Prague: inside the broad fetch rectangle.
    assert not in_poland(53.9, 23.9)  # Grodno, outside Poland.
    records = [aircraft(), aircraft(hex='48abc1', alt_baro='ground'),
               aircraft(hex='48abc2', category='C1'), aircraft(hex='48abc3', category='B2'),
               aircraft(hex='48abc4', type='adsb_icao_nt'), aircraft(hex='48abc5', seen_pos=121),
               aircraft(hex='48abc6', lat=50.08, lon=14.43), aircraft(hex='48abc7', seen_pos=None),
               aircraft(hex='48abc8', lat='nan'), aircraft(hex='invalid'), aircraft(), None]
    assert len(AircraftService(None, lambda: NOW).normalize(payload(*records), NOW)) == 1


def test_missing_optional_fields_not_invented_and_age_uses_source_timestamp():
    service = AircraftService(None, lambda: NOW)
    record = aircraft(flight=' ', r=None, t=None, gs='nan', track=361, alt_baro=None)
    item = service.normalize(payload(record, now=NOW-timedelta(seconds=10)), NOW)[0]
    assert all(item[key] is None for key in ('id', 'registration', 'type_code', 'speed_kmh', 'track', 'altitude_m'))
    assert item['position_at'] == (NOW-timedelta(seconds=13.5)).isoformat()
    assert item['military'] is False
    assert service.normalize(payload(aircraft(dbFlags=9)), NOW)[0]['military'] is True
    assert service.normalize(payload(aircraft(dbFlags=2)), NOW)[0]['military'] is False
    assert service.normalize(payload(aircraft(), now=NOW-timedelta(seconds=120)), NOW) == []
    with pytest.raises(ValueError):
        service.normalize(payload(aircraft(), now=NOW+timedelta(seconds=60)), NOW)
    with pytest.raises(ValueError):
        service.normalize(payload(now=NOW-timedelta(seconds=121)), NOW)


@pytest.mark.asyncio
async def test_failure_backoff_stale_last_snapshot_and_expiry():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=payload(aircraft()))
        raise httpx.ReadTimeout('upstream timeout')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=20)
        result = await service.fetch()
        assert result['status'] == 'error' and result['stale'] and len(result['items']) == 1
        assert result['fetched_at'] == NOW.isoformat()
        now[0] += timedelta(seconds=30)
        assert (await service.fetch())['stale'] and len(calls) == 2
        now[0] += timedelta(seconds=80)
        result = await service.fetch()
        assert result['stale'] and result['items'] == [] and len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    httpx.Response(200, json={'ac': []}),
    httpx.Response(200, json={'now': NOW.timestamp()*1000, 'ac': {}}),
    httpx.Response(200, json={'now': NOW.timestamp()*1000, 'ac': [], 'msg': 'error'}),
    httpx.Response(200, content=b'invalid', headers={'Content-Type': 'application/json'}),
    httpx.Response(200, content=b'{}', headers={'Content-Type': 'text/html'}),
    httpx.Response(200, content=b' '* (MAX_BYTES+1), headers={'Content-Type': 'application/json'}),
    httpx.Response(302, headers={'Location': 'https://example.com'}),
])
async def test_malformed_and_bounded_responses_return_explicit_error(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        result = await AircraftService(client, lambda: NOW).fetch()
        assert result['status'] == 'error' and not result['stale'] and result['items'] == []


@pytest.mark.asyncio
async def test_rate_limit_honours_retry_after_then_recovers_with_empty_snapshot():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return (httpx.Response(429, headers={'Retry-After': '180'}) if len(calls) == 1
                else httpx.Response(200, json=payload(now=now[0])))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: now[0])
        assert (await service.fetch())['status'] == 'error'
        now[0] += timedelta(seconds=179)
        await service.fetch()
        assert len(calls) == 1
        now[0] += timedelta(seconds=1)
        result = await service.fetch()
        assert len(calls) == 2 and result['status'] == 'ready' and result['items'] == []


@pytest.mark.asyncio
async def test_old_upstream_snapshot_preserves_last_good_positions():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=(payload(aircraft()) if len(calls) == 1 else
                                        payload(now=NOW-timedelta(minutes=3))))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=20)
        result = await service.fetch()
        assert result['status'] == 'error' and result['stale'] and len(result['items']) == 1
        assert result['fetched_at'] == NOW.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize('retry_after', ['not a date', '', 'NaN', '9999999999999999999999999999999999'])
async def test_malformed_retry_after_uses_bounded_backoff(retry_after):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={'Retry-After': retry_after}))) as client:
        service = AircraftService(client, lambda: NOW)
        assert (await service.fetch())['status'] == 'error'
        assert NOW+timedelta(seconds=60) <= service.retry_at <= NOW+timedelta(days=1)


@pytest.mark.asyncio
async def test_disabled_and_demo_never_use_network():
    def handler(request):
        raise AssertionError('No upstream requests expected')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        disabled = await AircraftService(client, lambda: NOW, enabled=False).fetch()
        demo = await AircraftService(client, lambda: NOW, demo=True).fetch()
        assert disabled['status'] == 'disabled' and disabled['items'] == []
        assert demo['demo'] and demo['items'] == [] and demo['message']


@pytest.mark.asyncio
async def test_slow_download_keeps_a_full_cache_interval_after_publication():
    now, calls = [NOW], []
    async def handler(request):
        calls.append(request)
        now[0] += timedelta(seconds=8)
        return httpx.Response(200, json=payload(aircraft(), now=NOW))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: now[0])
        result = await service.fetch()
        assert result['status'] == 'ready' and result['items']
        now[0] += timedelta(seconds=9)
        assert (await service.fetch())['status'] == 'ready'
        assert len(calls) == 1  # Past the old request-start expiry, still inside the published cache.


@pytest.mark.asyncio
async def test_total_download_deadline_returns_diagnostic_and_backs_off(caplog):
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.Event().wait()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: NOW, timeout=.01)
        result = await asyncio.wait_for(service.fetch(), timeout=1)
        assert result['status'] == 'error'
        assert 'limit czasu' in result['message'] and '60 s' in result['message']
        assert 'TimeoutError' in caplog.text
        assert (await service.fetch())['message'] == result['message']
        assert len(calls) == 1
        assert sum('Aircraft fetch failed' in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('code, expected', [(403, 'HTTP 403'), (429, 'ogranicza'), (503, 'HTTP 503')])
async def test_http_failure_diagnostic_survives_backoff_and_clears_on_recovery(code, expected):
    now, calls = [NOW], []
    def handler(request):
        calls.append(request)
        return (httpx.Response(code, headers={'Retry-After': '180'}) if len(calls) == 1
                else httpx.Response(200, json=payload(aircraft(), now=now[0])))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AircraftService(client, lambda: now[0])
        assert expected in (await service.fetch())['message']
        now[0] += timedelta(seconds=10)
        assert expected in (await service.fetch())['message'] and len(calls) == 1
        now[0] += timedelta(seconds=180)
        result = await service.fetch()
        assert result['status'] == 'ready' and result['message'] == '' and result['items']
