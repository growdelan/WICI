"""Offline checks of weather provider units, hour alignment and bounded fetch/cache behaviour."""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wici.weather import GRID, MAX_BYTES, VARIABLES, WeatherService, inside_ring

NOW = datetime(2026, 10, 14, 14, 12, tzinfo=UTC)


def station(**updates):
    return {'kod_stacji': '123', 'nazwa_stacji': 'TEST', 'lat': '52.23', 'lon': '21.01',
            'wiatr_srednia_predkosc': '4', 'wiatr_srednia_predkosc_data': '2026-10-14 14:00:00',
            'wiatr_kierunek': '270', 'wiatr_kierunek_data': '2026-10-14 14:00:00',
            'wiatr_poryw_10min': '9', 'wiatr_poryw_10min_data': '2026-10-14 14:00:00',
            'opad_10min': '0', 'opad_10min_data': '2026-10-14 13:50:00', **updates}


def forecast():
    times = [(NOW.replace(minute=0)+timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M') for i in range(48)]
    return [{'utc_offset_seconds': 0,
             'hourly_units': dict(zip(VARIABLES, ['km/h', '°', 'km/h', 'mm'], strict=True)),
             'hourly': {'time': times.copy(), **dict(zip(VARIABLES, [[20]*48, [270]*48, [32]*48, [1.2]*48],
                                                       strict=True))}}
            for _ in GRID]


@pytest.mark.asyncio
async def test_imgw_units_observation_times_and_single_concurrent_fetch():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[station(), station(kod_stacji='bad', lat='nan')])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(client, lambda: now[0])
        assert not calls
        results = await asyncio.gather(*(service.fetch() for _ in range(4)))
        assert len(calls) == 1 and results[0] == results[3]
        data = results[0]
        assert data['precipitation_period_minutes'] == 10 and len(data['points']) == 1
        assert data['times'] == ['2026-10-14T14:00:00+00:00']
        sample = data['points'][0]['samples'][0]
        assert sample['wind_speed_kmh'] == 14.4 and sample['wind_gust_kmh'] == 32.4
        assert sample['wind_direction_deg'] == 270 and sample['precipitation_mm'] == 0
        assert sample['precipitation_time'] == '2026-10-14T13:50:00+00:00'
        now[0] += timedelta(minutes=10)
        await service.fetch()
        assert len(calls) == 2


def test_missing_invalid_stale_and_misaligned_measurements():
    service = WeatherService(None, lambda: NOW)
    _, points = service.measurements([station(wiatr_srednia_predkosc='nan', wiatr_kierunek='361',
                                              wiatr_poryw_10min_data='2026-10-09 14:00:00')], NOW)
    sample = points[0]['samples'][0]
    assert sample['wind_speed_kmh'] is None and sample['wind_direction_deg'] is None
    assert sample['wind_gust_kmh'] is None and sample['wind_gust_time'].startswith('2026-10-09')
    _, points = service.measurements([station(wiatr_kierunek_data='2026-10-14 13:30:00',
                                              opad_10min=None, opad_10min_data=None)], NOW)
    sample = points[0]['samples'][0]
    assert sample['wind_direction_deg'] is None and sample['precipitation_mm'] is None
    assert sample['precipitation_time'] is None
    times, points = service.measurements([station(wiatr_srednia_predkosc_data='invalid',
                                                 wiatr_kierunek_data=None,
                                                 wiatr_poryw_10min_data=None,
                                                 opad_10min_data='2020-01-01')], NOW)
    assert times == [] and points == []
    assert len(service.measurements([station(), station()], NOW)[1]) == 1


@pytest.mark.asyncio
async def test_forecast_parameters_hour_alignment_units_and_cache():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        assert request.url.params['start_hour'] == '2026-10-14T14:00'
        assert request.url.params['end_hour'] == '2026-10-16T13:00'
        assert request.url.params['timezone'] == 'GMT'
        assert len(request.url.params['latitude'].split(',')) == len(GRID)
        return httpx.Response(200, json=forecast())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(client, lambda: now[0])
        data = await service.fetch('forecast')
        assert data['status'] == 'ready' and len(data['points']) == len(GRID)
        assert len(data['times']) == 48 and data['precipitation_period_minutes'] == 60
        sample = data['points'][0]['samples'][0]
        assert sample['wind_speed_kmh'] == 20 and sample['wind_direction_deg'] == 270
        now[0] += timedelta(minutes=59)
        assert (await service.fetch('forecast'))['times'] == data['times'] and len(calls) == 1


def test_forecast_null_values_preserved_and_malformed_arrays_rejected():
    service, payload = WeatherService(None, lambda: NOW), forecast()
    payload[0]['hourly']['wind_speed_10m'][0] = None
    payload[0]['hourly']['precipitation'][1] = 'nan'
    _, points = service.forecasts(payload, NOW.replace(minute=0))
    assert points[0]['samples'][0]['wind_speed_kmh'] is None
    assert points[0]['samples'][1]['precipitation_mm'] is None
    for malformed in ('hours', 'units', 'offset', 'array'):
        data = forecast()
        if malformed == 'hours':
            data[0]['hourly']['time'][0] = '2026-10-14T15:00'
        elif malformed == 'units':
            data[0]['hourly_units']['wind_speed_10m'] = 'm/s'
        elif malformed == 'offset':
            data[0]['utc_offset_seconds'] = 7200
        else:
            data[0]['hourly']['precipitation'] = []
        with pytest.raises(ValueError):
            service.forecasts(data, NOW.replace(minute=0))


@pytest.mark.asyncio
async def test_stale_retained_on_failure_and_retry_after():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return (httpx.Response(200, json=[station()]) if len(calls) == 1 else
                httpx.Response(429, text='private upstream body', headers={'Retry-After': '1200'}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(client, lambda: now[0])
        good = await service.fetch()
        now[0] += timedelta(seconds=601)
        failed = await service.fetch()
        assert failed['stale'] and failed['status'] == 'error' and failed['points'] == good['points']
        assert 'private' not in str(failed)
        now[0] += timedelta(seconds=600)
        await service.fetch()
        assert len(calls) == 2
        now[0] += timedelta(seconds=601)
        await service.fetch()
        assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(302, headers={'Location': 'https://bad.test'}),
    httpx.Response(200, content=b'[]', headers={'Content-Type': 'text/html'}),
    httpx.Response(200, content=b'broken', headers={'Content-Type': 'application/json'}),
    httpx.Response(200, json={'wrong': []}), httpx.Response(200, json=[]),
    httpx.Response(200, content=b'x'*(MAX_BYTES+1), headers={'Content-Type': 'application/json'})])
async def test_bad_response_bounded_and_backed_off(response):
    calls = []
    def handler(request):
        calls.append(request)
        return response
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        service = WeatherService(client, lambda: NOW)
        assert (await service.fetch())['status'] == 'error'
        assert (await service.fetch())['points'] == [] and len(calls) == 1


@pytest.mark.asyncio
async def test_demo_disabled_and_invalid_mode_never_network():
    def forbidden(request):
        pytest.fail('Unexpected network')
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        service = WeatherService(client, lambda: NOW, demo=True)
        for mode in ('measurement', 'forecast'):
            data = await service.fetch(mode)
            assert data['demo'] and data['status'] == 'demo' and 'syntetyczne' in data['source_name']
            assert data == await service.fetch(mode)
        disabled = WeatherService(client, lambda: NOW, measurement_enabled=False, forecast_enabled=False)
        assert (await disabled.fetch())['status'] == 'disabled'
        assert (await disabled.fetch('forecast'))['status'] == 'disabled'
        with pytest.raises(ValueError):
            await service.fetch('bad')


def test_grid_is_bounded_and_clipped_and_ring_handles_holes():
    assert 30 <= len(GRID) <= 100 and len(GRID) == len(set(GRID))
    assert (49.3, 14.5) not in GRID and (52.55, 19.5) in GRID
    square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    assert inside_ring(1, 1, square) and not inside_ring(3, 1, square)


@pytest.mark.asyncio
async def test_repeated_failure_renews_backoff_after_expiry():
    calls, now = [], [NOW]
    def handler(request):
        calls.append(request)
        return httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(client, lambda: now[0])
        await service.fetch()
        now[0] += timedelta(seconds=301)
        await service.fetch()
        await service.fetch()
        assert len(calls) == 2
        now[0] += timedelta(seconds=301)
        await service.fetch()
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_regional_forecasts_request_only_selected_grid_and_keep_separate_cache():
    from wici.weather import REGION_GRIDS, in_region

    calls = []

    def handler(request):
        calls.append(request)
        count = len(request.url.params['latitude'].split(','))
        payload = forecast()[:count]
        return httpx.Response(200, json=payload[0] if count == 1 else payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(client, lambda: NOW)
        for code in ['02', '14', '', '02']:
            data = await service.fetch('forecast', code)
            grid = REGION_GRIDS[code] if code else GRID
            assert len(data['points']) == len(grid)
            assert all(in_region(p['latitude'], p['longitude'], code) for p in data['points'])
        assert len(calls) == 3
        assert [len(r.url.params['latitude'].split(',')) for r in calls] == [
            len(REGION_GRIDS['02']), len(REGION_GRIDS['14']), len(GRID)]
        for invalid in ['99', '2', '../02']:
            with pytest.raises(ValueError):
                await service.fetch('forecast', invalid)
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_regions_share_measurements_and_backoff_but_never_stale_forecast_points():
    from wici.weather import in_region

    calls, now, failed = [], [NOW], [False]

    def handler(request):
        calls.append(request)
        if failed[0]:
            return httpx.Response(503)
        if request.url.path.endswith('/meteo/'):
            return httpx.Response(200, json=[station()])
        count = len(request.url.params['latitude'].split(','))
        return httpx.Response(200, json=forecast()[:count])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WeatherService(client, lambda: now[0])
        await service.fetch('measurement', '02')
        await service.fetch('measurement', '14')
        assert len(calls) == 1
        first = await service.fetch('forecast', '02')
        second = await service.fetch('forecast', '14')
        now[0] += timedelta(hours=2)
        failed[0] = True
        stale = await service.fetch('forecast', '02')
        assert stale['stale'] and stale['fetched_at'] == first['fetched_at']
        assert stale['points'] == first['points']
        assert all(in_region(p['latitude'], p['longitude'], '02') for p in stale['points'])
        backed_off = await service.fetch('forecast', '14')
        assert backed_off['points'] == second['points'] and backed_off['stale']
        assert len(calls) == 4
