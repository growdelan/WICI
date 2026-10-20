"""Independently authored synthetic IODA contract cases; no network in this suite."""
import asyncio
import copy
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wici.app import create_app
from wici.config import Config
from wici.demo import DEMO_NOW, seed
from wici.ioda import (
    REGIONS,
    Collector,
    ContractError,
    envelope,
    geometry_ref,
    parse_alert,
    parse_event,
    parse_signals,
    retry_after,
)
from wici.repository import Repository
from wici.scheduler import INTERVALS, Scheduler

FIX = Path(__file__).parent/'fixtures/ioda'
NOW = datetime(2026,10,17,8,tzinfo=UTC)
SYNTHETIC_NOTICE = 'Synthetic WICI test data (MIT); not an IODA response.'


def fixture(name):
    return json.loads((FIX/f'{name}.json').read_text())


def mock_api(fail=None):
    calls = []
    def handler(request):
        calls.append(request)
        path, q = request.url.path, request.url.params
        if fail:
            response = fail(request)
            if response is not None:
                return response
        if path.endswith('/datasources/'):
            result = fixture('datasources')
        elif path.endswith('/entities/query'):
            kind = q['entityType']
            result = fixture({'country':'country','region':'regions','asn':'asn'}[kind])
        elif '/outages/' in path:
            result = fixture('events_ioda' if path.endswith('events') else 'alerts')
            if q['entityType'] != 'asn':
                result['data'] = []
        else:
            result = fixture('signals' if '/country/' in path else 'signals_multi')
            if '/asn/' in path:
                for group in result['data']:
                    for row in group:
                        row.update(entityType='asn',entityCode='64512')
            for group in result['data']:
                for row in group:
                    row['datasource'] = q['datasource']
        return httpx.Response(200,json=result)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def test_synthetic_contract_preserves_zero_null_and_explicit_end():
    for path in FIX.glob('*.json'):
        payload = fixture(path.stem)
        assert payload['metadata']['synthetic'] is True
        assert payload['copyright']==SYNTHETIC_NOTICE
    assert envelope(fixture('country'),'entities.lookup')[0]['code']=='PL'
    event = parse_event(fixture('events_ioda')['data'][0])
    assert event['entity_code']=='64512' and event['name']=='WICI synthetic network'
    assert event['ended_at']==event['source_until'] and event['method']=='median'
    assert event['ended_at']-event['started_at']==300
    assert event['score']==fixture('events')['data'][0]['score']
    assert parse_alert(fixture('alerts')['data'][0])['measured_at']==event['started_at']
    assert parse_alert(fixture('alerts')['data'][1])['measured_at']==event['ended_at']
    samples = parse_signals(fixture('signals'))
    assert [s['value'] for s in samples]==[8,None,0,6]
    assert samples[1]['measured_at']-samples[0]['measured_at']==samples[0]['step']
    assert {s['entity_code'] for s in parse_signals(fixture('signals_multi'))}=={'3296','3297'}
    # A synthetic CODF status is deliberately never used as recovery evidence.
    with pytest.raises(KeyError):
        parse_event(fixture('events')['data'][0])


@pytest.mark.parametrize('mutate',[
    lambda r:r.pop('entity'), lambda r:r.update(score=float('nan')),
    lambda r:r.update(until=r['from']-1), lambda r:r.update(alerts=[]),
    lambda r:r['alerts'][0]['entity'].update(code='elsewhere'),
])
def test_event_contract_rejects_drift(mutate):
    raw=copy.deepcopy(fixture('events_ioda')['data'][0]);mutate(raw)
    with pytest.raises((ContractError,KeyError,TypeError)):
        parse_event(raw)


def test_region_mapping_requires_code_name_and_country():
    regions=fixture('regions')['data']
    assert len([e for e in regions if geometry_ref(e)])==16
    assert geometry_ref(next(e for e in regions if e['code']=='999999')) is None
    for e in regions:
        if e['code'] in REGIONS:
            assert geometry_ref(e)==REGIONS[e['code']][1]
    e=copy.deepcopy(regions[0]);e['name']='changed';assert geometry_ref(e) is None
    e=copy.deepcopy(regions[0]);e['attrs']['country_code']='DE';assert geometry_ref(e) is None
    e=copy.deepcopy(regions[0]);e.pop('attrs')
    with pytest.raises(ContractError):geometry_ref(e)
    assert geometry_ref(fixture('asn')['data'][0]) is None
    local=json.loads((Path(__file__).parents[1]/'src/wici/static/geo/provinces.geojson').read_text())
    assert {v[1] for v in REGIONS.values()}=={e['properties']['admin_code'] for e in local['features']}


def test_dedup_event_updates_unknown_end_missing_record_restart(tmp_path):
    path=tmp_path/'app.sqlite';repo=Repository(path,clock=lambda:NOW)
    raw=fixture('events_ioda')['data'][0];raw['alerts']=raw['alerts'][:1]
    event=parse_event(raw)
    assert event['ended_at'] is None
    assert repo.save_ioda_events([event],{'test':True})==1
    assert repo.save_ioda_events([event],{'test':True})==0
    raw['until']+=300
    event=parse_event(raw)
    assert repo.save_ioda_events([event],{'test':True})==1
    repo.save_ioda_events([],{});repo.save_ioda_run({'result':'error'})
    repo.close();repo=Repository(path,clock=lambda:NOW)
    assert repo.list_ioda(hours=48)['total']==1
    assert repo.list_ioda(hours=48)['items'][0]['ended_at'] is None
    closed=parse_event(fixture('events_ioda')['data'][0])
    repo.save_ioda_events([closed],{})
    assert repo.list_ioda(hours=48)['items'][0]['ended_at']==closed['ended_at']
    assert repo.db.execute('SELECT COUNT(*) FROM ioda_events').fetchone()[0]==1
    assert repo.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0
    repo.close()


def test_time_boundaries_and_dst_window(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:datetime(2026,11,2,tzinfo=UTC))
    # Europe/Warsaw DST transition day ends at 23:00 UTC; elapsed window is 24h.
    data=repo.list_ioda(selected_date='2026-10-25')
    assert data['window_end']=='2026-10-25T23:00:00+00:00'
    assert data['window_start']=='2026-10-24T23:00:00+00:00'
    raw=fixture('events_ioda')['data'][0]
    b=int(datetime.fromisoformat(data['window_end']).timestamp())
    a=b-86400
    def record(start,end):
        r=copy.deepcopy(raw);r['from']=start;r['until']=end
        r['alerts'][0]['time']=start;r['alerts'][1]['time']=end
        return parse_event(r)
    repo.save_ioda_events([record(a-100,a),record(b,b+100),record(a-200,a+1)],{})
    assert repo.list_ioda(selected_date='2026-10-25')['total']==1
    with pytest.raises(ValueError):repo.list_ioda(hours=72)
    with pytest.raises(ValueError):repo.list_ioda(selected_date='2026-11-03')
    repo.close()


async def test_collector_end_to_end_fixture_and_durable_metadata_cache(tmp_path):
    path=tmp_path/'app.sqlite';repo=Repository(path,clock=lambda:NOW)
    client,calls=mock_api();config=Config(sources={'ioda':{'asns':[64512]}})
    scheduler=Scheduler(repo,config,client)
    await scheduler.fetch('ioda')
    assert repo.ioda_status()['last_result']=='success'
    assert repo.list_ioda(hours=48)['total']==1
    assert repo.db.execute('SELECT COUNT(*) FROM ioda_samples').fetchone()[0]>0
    first=len(calls);await scheduler.fetch('ioda')
    assert all('/entities/query' not in r.url.path for r in calls[first:])
    assert repo.list_ioda(hours=48)['total']==1
    assert all(r.url.params.get('page','0')=='0' for r in calls)
    assert all('country/PL'==r.url.params['relatedTo'] for r in calls if r.url.params.get('relatedTo'))
    assert repo.ioda_status()['requests']<=60
    sample=json.loads(repo.db.execute('SELECT provenance_json FROM ioda_samples LIMIT 1').fetchone()[0])
    assert 'api.ioda.inetintel.cc.gatech.edu' in sample['url']
    assert sample['metadata']['synthetic'] is True and sample['copyright']==SYNTHETIC_NOTICE
    saved_event=repo.list_ioda(hours=48)['items'][0]
    assert saved_event['entity_code']=='64512'
    assert saved_event['provenance']['metadata']['synthetic'] is True
    assert saved_event['provenance']['copyright']==SYNTHETIC_NOTICE
    repo.close();repo=Repository(path,clock=lambda:NOW)
    await Collector(repo,client,config).run()
    assert repo.list_ioda(hours=48)['total']==1
    assert len(repo.ioda_metadata())==19
    await client.aclose();repo.close()


async def test_pagination_zero_three_page_limit_and_partial_commit(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    pages=[]
    full=False
    def handler(r):
        page=int(r.url.params['page']);pages.append(page)
        return httpx.Response(200,json={'type':'entities.lookup','metadata':{},'error':None,
                                       'data':[{'page':page}] if full or page<2 else []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector=Collector(repo,client,Config());seen=[]
        await collector.pages('entities/query',{},'entities.lookup',lambda rows,p:seen.extend(rows),limit=1)
        assert pages==[0,1,2] and len(seen)==2
        pages.clear();full=True
        with pytest.raises(ContractError):
            await collector.pages('entities/query',{},'entities.lookup',lambda rows,p:None,limit=1)
        assert pages==[0,1,2]
    repo.close()


@pytest.mark.parametrize('failure',['500','timeout','contract','large'])
async def test_partial_failure_preserves_event_and_full_success_clock(tmp_path,failure):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    config=Config(sources={'ioda':{'asns':[64512]}})
    client,_=mock_api();scheduler=Scheduler(repo,config,client);await scheduler.fetch('ioda')
    before=repo.ioda_status()['last_successful_check'];await client.aclose()
    def fail(r):
        if '/signals/raw/' in r.url.path:
            if failure=='timeout':raise httpx.ReadTimeout('test',request=r)
            if failure=='500':return httpx.Response(500)
            if failure=='large':return httpx.Response(200,content=b'x'*4_000_001)
            return httpx.Response(200,json={'type':'signals','metadata':{},'error':None,'data':[{'bad':True}]})
    client,_=mock_api(fail);scheduler.client=client
    await scheduler.fetch('ioda')
    status=repo.ioda_status()
    assert status['last_result']=='partial' and status['errors']
    assert status['last_successful_check']==before
    assert repo.list_ioda(hours=48)['total']==1
    assert repo.db.execute("SELECT failures FROM sources WHERE id='ioda'").fetchone()[0]==1
    assert status['measurement_at'] is not None
    await client.aclose();repo.close()


async def test_429_stops_run_retry_after_survives_restart(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    client,calls=mock_api(lambda r:httpx.Response(429,headers={'Retry-After':'1800'}))
    config=Config(sources={'ioda':{'asns':[]}});scheduler=Scheduler(repo,config,client)
    await scheduler.fetch('ioda')
    assert len(calls)==1
    with pytest.raises(ValueError,match='Retry-After'):scheduler.refresh('ioda')
    row=repo._one("SELECT * FROM sources WHERE id='ioda'")
    assert row['last_result']=='error' and row['last_successful_check'] is None
    assert datetime.fromisoformat(row['next_due_at'])==NOW+timedelta(seconds=1800)
    assert repo.list_ioda()['total']==0
    repo.close();repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    Scheduler(repo,config,client)
    assert repo._one("SELECT next_due_at FROM sources WHERE id='ioda'")['next_due_at']==row['next_due_at']
    await client.aclose();repo.close()


def test_retry_after_http_date_and_bad_header():
    assert retry_after('Sat, 17 Oct 2026 08:30:00 GMT',NOW)==1800
    assert retry_after('garbage',NOW)==600


async def test_no_events_no_measurements_and_read_error_are_distinct(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    def empty(r):
        if '/outages/' in r.url.path or '/signals/' in r.url.path:
            kind='signals' if '/signals/' in r.url.path else 'outages.'+r.url.path.rsplit('/',1)[1]
            return httpx.Response(200,json={'type':kind,'metadata':{},'error':None,'data':[]})
    client,_=mock_api(empty);config=Config(sources={'ioda':{'asns':[]}})
    scheduler=Scheduler(repo,config,client);await scheduler.fetch('ioda')
    assert repo.ioda_status()['last_result']=='success'
    assert repo.ioda_status()['measurement_state']=='no_measurements'
    assert repo.list_ioda()['total']==0
    await client.aclose();repo.close()


@pytest.mark.parametrize('settings',[{'asns':list(range(1,10))},{'asns':[64512,64512]},
    {'asns':['bad']},{'asns':[0]},{'interval_seconds':60},{'interval_seconds':301}])
def test_config_bounds(settings):
    with pytest.raises(ValidationError):Config(sources={'ioda':settings})


def test_demo_offline_api_filters_and_repeat_seed(tmp_path):
    def blocked(r):raise AssertionError('Offline demo attempted a network read')
    network=httpx.AsyncClient(transport=httpx.MockTransport(blocked))
    with TestClient(create_app(demo=True,root=tmp_path,config=Config(),client=network),
                    base_url='http://127.0.0.1:8765') as client:
        app=client.app;seed(app.state.repo)
        result=client.get('/api/ioda').json()
        assert result['total']==3 and all(i['synthetic'] for i in result['items'])
        assert result['status']['measurement_stale']
        assert any(not s['points'] for e in result['entities'] for s in e['signals'])
        asn=client.get('/api/ioda?level=asn').json()
        assert asn['total']==1 and asn['items'][0]['geometry_ref'] is None
        assert client.get('/api/ioda?voivodeship=14').json()['total']==1
        assert client.get('/api/ioda?level=asn&voivodeship=14').json()['total']==0
        assert client.get('/api/ioda?hours=3').status_code==422
        assert client.get('/api/ioda?level=bogus').status_code==422
        assert client.get('/api/communications').json()['total']>0
        assert next(s for s in client.get('/api/sources').json()['items'] if s['id']=='ioda')['ioda']['errors']
    with TestClient(create_app(demo=True,root=tmp_path,config=Config(),client=network),
                    base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/ioda').json()['total']==3


async def test_background_scheduler_ioda_independent_of_ui(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    config=Config(sources={k:{'enabled':k=='ioda',**({'asns':[64512]} if k=='ioda' else {})} for k in INTERVALS})
    client,_=mock_api();scheduler=Scheduler(repo,config,client);scheduler.start()
    try:
        for _ in range(100):
            if repo.ioda_status()['last_successful_check']:
                break
            await asyncio.sleep(.01)
        assert repo.list_ioda(hours=48)['total']==1
        assert repo.ioda_status()['last_successful_check']
    finally:
        await scheduler.stop();await client.aclose();repo.close()


def test_migration_preserves_existing_tables(tmp_path):
    path=tmp_path/'app.sqlite';db=sqlite3.connect(path)
    migrations=sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    for migration in migrations[:8]:db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=8');db.execute("INSERT INTO app_state VALUES('history','preserved')")
    db.commit();db.close();repo=Repository(path,clock=lambda:DEMO_NOW)
    assert repo.db.execute('PRAGMA user_version').fetchone()[0]==len(migrations)
    assert repo.db.execute("SELECT value FROM app_state WHERE key='history'").fetchone()[0]=='preserved'
    repo.close()


async def test_invalid_event_row_keeps_valid_sibling_and_does_not_promote_alerts(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    def mixed(r):
        if r.url.path.endswith('/events'):
            result=fixture('events_ioda')
            if r.url.params['entityType']=='asn':result['data'].append({'not':'an event'})
            else:result['data']=[]
            return httpx.Response(200,json=result)
    client,_=mock_api(mixed)
    summary=await Collector(repo,client,Config(sources={'ioda':{'asns':[64512]}})).run()
    assert summary['result']=='partial' and 'event: KeyError' in summary['errors']
    assert repo.list_ioda(hours=48)['total']==1
    await client.aclose();repo.close()


async def test_changed_units_are_not_saved_under_old_units(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    def changed(r):
        if r.url.path.endswith('/datasources/'):
            payload=fixture('datasources')
            for item in payload['data']:item['units']='Changed unit'
            return httpx.Response(200,json=payload)
    client,calls=mock_api(changed)
    summary=await Collector(repo,client,Config(sources={'ioda':{'asns':[64512]}})).run()
    assert summary['result']=='partial'
    assert not any('/signals/raw/' in r.url.path for r in calls)
    assert repo.db.execute('SELECT COUNT(*) FROM ioda_samples').fetchone()[0]==0
    await client.aclose();repo.close()


def test_poll_freshness_does_not_make_old_measurements_fresh(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    rows=parse_signals(fixture('signals'))
    repo.save_ioda_samples(rows,{'test':True})
    repo.clock=lambda:NOW+timedelta(hours=2)
    scheduler=Scheduler(repo,Config(sources={'ioda':{'interval_seconds':600}}),None)
    with repo.lock,repo.db:
        repo.db.execute("UPDATE sources SET last_successful_check=? WHERE id='ioda'",(repo.clock().isoformat(),))
    source=next(s for s in scheduler.sources() if s['id']=='ioda')
    assert source['stale'] is False and source['ioda']['measurement_stale'] is True
    assert source['interval_seconds']==600
    repo.close()


def test_null_sample_preserves_value_metadata_and_provenance_after_restart(tmp_path):
    path=tmp_path/'app.sqlite'
    repo=Repository(path,clock=lambda:NOW)
    sample=parse_signals(fixture('signals'))[0]
    assert sample['value'] is not None
    first={'url':'https://example.test/first','metadata':{'responseTime':NOW.isoformat()}}
    repo.save_ioda_samples([sample],first)
    original=dict(repo.db.execute('SELECT * FROM ioda_samples').fetchone())
    repo.clock=lambda:NOW+timedelta(minutes=5)
    second={'url':'https://example.test/null','metadata':{'responseTime':repo.clock().isoformat()}}
    # Native resolution is part of the preserved measurement metadata too.
    repo.save_ioda_samples([dict(sample,value=None,native_step=60)],second)
    repo.save_ioda_run({'result':'success','at':repo.clock().isoformat(),
        'signal_checks':{'country/PL/bgp':{'result':'success','measurement_at':None}}})
    assert dict(repo.db.execute('SELECT * FROM ioda_samples').fetchone())==original
    assert repo.ioda_status()['signal_checks']['country/PL/bgp']['measurement_at'] is None
    repo.close()
    repo=Repository(path,clock=lambda:NOW+timedelta(minutes=10))
    assert dict(repo.db.execute('SELECT * FROM ioda_samples').fetchone())==original
    # A later real value, including zero, must replace all measurement metadata.
    third={'url':'https://example.test/zero'}
    repo.save_ioda_samples([dict(sample,value=0,native_step=60)],third)
    updated=dict(repo.db.execute('SELECT * FROM ioda_samples').fetchone())
    assert updated['value']==0 and updated['native_step']==60
    assert updated['fetched_at']==repo.clock().isoformat()
    assert json.loads(updated['provenance_json'])==third
    repo.close()


def test_empty_sample_can_be_refreshed_then_filled(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    sample=dict(parse_signals(fixture('signals'))[0],value=None)
    repo.save_ioda_samples([sample],{'response':'initial-null'})
    repo.clock=lambda:NOW+timedelta(minutes=5)
    repo.save_ioda_samples([sample],{'response':'later-null'})
    row=dict(repo.db.execute('SELECT * FROM ioda_samples').fetchone())
    assert row['value'] is None and row['fetched_at']==repo.clock().isoformat()
    assert json.loads(row['provenance_json'])=={'response':'later-null'}
    repo.save_ioda_samples([dict(sample,value=123)],{'response':'filled'})
    row=dict(repo.db.execute('SELECT * FROM ioda_samples').fetchone())
    assert row['value']==123 and json.loads(row['provenance_json'])=={'response':'filled'}
    repo.close()
