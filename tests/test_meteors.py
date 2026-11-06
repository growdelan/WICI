import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from wici import meteors as m

NOW = datetime(2026, 11, 6, 18, tzinfo=UTC)
# Reduced synthetic version of the two-line GMN table, in source column order.
FIELDS = ['id', 'start', 'speed', 'lat1', 'lon1', 'ht1', 'lat2', 'lon2', 'ht2', 'duration', 'mag']
NAMES = ['Unique trajectory', 'Beginning', 'Vinit', 'LatBeg', 'LonBeg', 'HtBeg',
         'LatEnd', 'LonEnd', 'HtEnd', 'Duration', 'Peak']
UNITS = ['identifier', 'UTC Time', 'km/s', '+N deg', '+E deg', 'km', '+N deg', '+E deg', 'km', 'sec', 'AbsMag']


def row(stamp, *, latitude=52, longitude=19, identity='20261031230000_abcde', **fields):
    data = {'id': identity, 'start': stamp, 'duration': '0.5', 'speed': '20.25', 'mag': '-1.5',
            'lat1': str(latitude), 'lon1': str(longitude), 'ht1': '100.1',
            'lat2': '52.1', 'lon2': '19.1', 'ht2': '80.2'}
    data.update(fields)
    return ';'.join(str(data[k]) for k in FIELDS)


def table(*rows):
    return ('# Summary generated on 2026-11-06 UTC\r\n# ' + ';'.join(NAMES) +
            '\n# ' + ';'.join(UNITS) + '\n# -------\n' + '\n'.join(rows) + '\n').encode()


def stamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


def catalog(*entries):
    return '\n'.join(f'<a href="traj_summary_{day}_solrange_{angle:03}.0-{(angle + 1) % 360:03}.0.txt">x</a>'
                     for day, angle in entries)


def archived_files():
    # A solar day starts in the evening, and a local night spans a UTC month boundary.
    return {
        'traj_summary_20261031_solrange_218.0-219.0.txt': table(
            row('2026-10-31 10:00:00', latitude=0),
            row('2026-10-31 23:00:00.123456'),
            row('2026-11-01 03:00:00', identity='20261101030000_abcde')),
        'traj_summary_20261101_solrange_219.0-220.0.txt': table(
            row('2026-11-01 10:59:59.999999', identity='20261101105959_abcde'),
            row('2026-11-01 11:00:00', identity='20261101110000_abcde'),
            row('2026-11-01 19:00:00', latitude=0)),
    }


def handler_for(files, calls):
    async def handler(request):
        calls.append(str(request.url))
        timeout = request.extensions['timeout']
        assert timeout['connect'] == 18 and timeout['write'] == 18
        if str(request.url) == m.DAILY:
            assert timeout['read'] == 35
            return httpx.Response(200, text=catalog(('20261031', 218), ('20261101', 219)))
        assert timeout['read'] == 18
        return httpx.Response(200, content=files[request.url.path.split('/')[-1]])
    return handler


@pytest.mark.parametrize('day,hours', [(date(2026, 3, 28), 23), (date(2026, 10, 24), 25),
                                      (date(2026, 11, 4), 24)])
def test_local_noons_include_clock_changes(day, hours):
    start, end = m.night_bounds(day)
    assert end - start == hours * 3600
    assert datetime.fromtimestamp(start, m.WARSAW).hour == 12
    assert datetime.fromtimestamp(end, m.WARSAW).hour == 12


def test_parser_uses_named_units_fractional_utc_and_polish_geometry():
    body = table(row('2026-10-31 23:00:00.123456'),
                 row('2026-10-31 23:01:00', latitude=50, longitude=24.2),  # Outside PL, inside bbox.
                 row('2026-10-31 23:02:00', latitude=-20),
                 row('2026-10-31 23:03:00', identity='20261031230300_abcde', speed='None', mag='nan'))
    parsed = m.parse_table(body)
    assert len(parsed.events) == 2
    one, two = parsed.events
    assert one['start'] == stamp('2026-10-31 23:00:00.123456')
    assert one['begin'] == {'lat': 52, 'lon': 19, 'alt_km': 100.1}
    assert one['duration'] == .5 and one['speed_kms'] == 20.25 and one['magnitude'] == -1.5
    assert two['speed_kms'] is None and two['magnitude'] is None
    assert parsed.last == stamp('2026-10-31 23:03:00')


@pytest.mark.parametrize('data', [b'<html>Unavailable</html>', b'', table('too;short'),
    table(row('2026-10-31 23:00:00', ht1='nan')), table(row('2026-10-31 23:00:00', duration='0')),
    table(row('2026-10-31 23:00:00', lon1='inf')), table(row('wrong time')), table(row('2026-10-31')),
    table(row('2026-10-31 23:00:00+02:00')), table(row('2026-10-31 23:00:00', speed='inf')),
    table(row('2026-10-31 23:00:00')).replace(b'+N deg', b'radians')])
def test_malformed_source_is_unavailable(data):
    with pytest.raises(m.MeteorUnavailable):
        m.parse_table(data)


async def test_month_boundary_solar_days_cache_and_concurrency():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(archived_files(), calls))) as client:
        service = m.MeteorService(client, lambda: NOW)
        results = await asyncio.gather(*(service.night(date(2026, 10, 31)) for _ in range(5)))
        assert len(calls) == 3
        one = results[0]
        assert one['date'] == '2026-10-31' and not one['bundled']
        assert len(one['events']) == 3
        assert one['events'][-1]['start'] < one['end']
        assert all(result == one for result in results)
        # A response belongs to its caller and does not mutate cached events.
        one['events'].clear()
        assert len((await service.night(date(2026, 10, 31)))['events']) == 3


async def test_no_polish_meteors_is_a_success_but_missing_time_coverage_is_not():
    files = {key: value.replace(b';52;', b';0;') for key, value in archived_files().items()}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(files, []))) as client:
        service = m.MeteorService(client, lambda: NOW)
        assert (await service.night(date(2026, 10, 31)))['events'] == []
    files = archived_files()
    files['traj_summary_20261101_solrange_219.0-220.0.txt'] = table(row('2026-11-01 09:00:00'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(files, []))) as client:
        with pytest.raises(m.MeteorUnavailable, match='pełnego zakresu'):
            await m.MeteorService(client, lambda: NOW).night(date(2026, 10, 31))


@pytest.mark.parametrize('code', [404, 429, 500])
async def test_http_failures_are_not_empty_nights_and_back_off(code):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(code)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = m.MeteorService(client, lambda: NOW)
        for _ in range(2):
            with pytest.raises(m.MeteorUnavailable):
                await service.night(date(2026, 10, 31))
        assert len(calls) == 1


async def test_missing_solar_bin_is_unavailable():
    async def handler(request):
        if str(request.url) == m.DAILY:
            return httpx.Response(200, text=catalog(('20261030', 217), ('20261101', 219)))
        return httpx.Response(200, content=table(row('2026-11-01 15:00:00')))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(m.MeteorUnavailable):
            await m.MeteorService(client, lambda: NOW).night(date(2026, 10, 31))


async def test_multiple_solar_bins_on_one_date_and_equinox_wrap():
    async def handler(request):
        if str(request.url) == m.DAILY:
            return httpx.Response(200, text=catalog(('20260319', 359), ('20260319', 0), ('20260320', 1)))
        if '359.0' in str(request.url):
            body = table(row('2026-03-19 10:00:00'), row('2026-03-19 15:00:00'))
        elif '000.0-001.0' in str(request.url):
            body = table(row('2026-03-19 20:00:00'), row('2026-03-20 12:00:00'))
        else:
            raise AssertionError('Unnecessary third file')
        return httpx.Response(200, content=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        one = await m.MeteorService(client, lambda: NOW).night(date(2026, 3, 19))
        assert one['events']


async def test_date_bounds_and_demo_bundled_data_never_use_network():
    def handler(request):
        raise AssertionError('Unexpected network call')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for demo in (True, False):
            service = m.MeteorService(client, lambda: NOW, demo=demo)
            one = await service.night(m.FEATURED_NIGHT)
            assert len(one['events']) == 265 and one['bundled']
            nysa = next(e for e in one['events'] if e['id'] == '20261104215730_pYgTq')
            assert nysa['start'] == stamp('2026-11-04 21:57:30.241314')
            assert nysa['duration'] == 4.08 and nysa['begin']['alt_km'] == 82.6655
            assert nysa['end']['alt_km'] == 60.5933
            if demo:
                with pytest.raises(m.MeteorUnavailable, match='demonstracyjny'):
                    await service.night(date(2020, 1, 1))
            else:
                for day in (date(2018, 12, 8), NOW.date(), NOW.date() + timedelta(days=1)):
                    with pytest.raises(ValueError):
                        await service.night(day)


async def test_oversized_source_and_rate_limit(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(archived_files(), []))) as client:
        service = m.MeteorService(client, lambda: NOW)
        monkeypatch.setattr(m, 'MAX_FILE', 10)
        with pytest.raises(m.MeteorUnavailable, match='limit pobierania'):
            await service.night(date(2026, 10, 31))
        service.requests.extend([NOW.timestamp()] * 16)
        with pytest.raises(m.MeteorUnavailable, match='Limit pobrań'):
            await service.night(date(2026, 10, 31))


async def test_retry_after_and_featured_temporal_rules_in_live_vs_demo():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={'Retry-After': '900'})
    now = [NOW]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = m.MeteorService(client, lambda: now[0])
        with pytest.raises(m.MeteorUnavailable):
            await service.night(date(2026, 10, 31))
        now[0] += timedelta(minutes=3)
        with pytest.raises(m.MeteorUnavailable):
            await service.night(date(2026, 10, 31))
        assert len(calls) == 1
        now[0] = datetime(2026, 11, 4, 6, tzinfo=UTC)
        with pytest.raises(ValueError):
            await service.night(m.FEATURED_NIGHT)
        demo = m.MeteorService(client, lambda: now[0], demo=True)
        assert (await demo.night(m.FEATURED_NIGHT))['bundled']
