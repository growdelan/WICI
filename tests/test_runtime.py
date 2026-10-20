"""Controlled local API/system contracts; no real HTTP requests."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.config import Config
from wici.demo import DEMO_NOW
from wici.repository import Repository
from wici.runtime import InstanceLock
from wici.scheduler import Scheduler


@pytest.fixture
def ui(tmp_path):
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        yield client

def headers(client):
    return {'Origin':'http://127.0.0.1:8765','X-CSRF-Token':client.get('/api/health').json()['csrf_token']}

def test_T23_csrf_host_and_static(ui):
    assert ui.get('/api/health',headers={'Host':'attacker.example'}).status_code==400
    assert ui.post('/api/sources/rso/refresh').status_code==403
    assert ui.post('/api/sources/rso/refresh',headers={**headers(ui),'Origin':'https://evil.example'}).status_code==403
    assert ui.get('/').status_code==200
    assert ui.get('/static/vendor/leaflet/leaflet.js').status_code==200
    assert "frame-ancestors 'none'" in ui.get('/').headers['content-security-policy']

def test_T27_demo_zero_network_isolated_and_clock(ui,tmp_path):
    assert ui.get('/api/health').json()['now']==DEMO_NOW.isoformat()
    assert ui.post('/api/sources/rso/refresh',headers=headers(ui)).status_code==422
    assert len(ui.get('/api/communications').json()['items'])==5
    assert all(e['warning_status']=='active' for e in ui.get('/api/communications').json()['items'] if e['communication_type']=='warning')


def test_request_limit(ui):
    assert ui.post('/api/sources/rso/refresh',headers=headers(ui),content=b'x'*65537).status_code==413

def test_T25_lock(tmp_path):
    lock=InstanceLock(tmp_path)
    with pytest.raises(RuntimeError):
        InstanceLock(tmp_path)
    lock.close()
    second=InstanceLock(tmp_path)
    second.close()

@pytest.mark.asyncio
async def test_blocked_source_manual_retry_keeps_block_until_success(tmp_path,monkeypatch):
    from wici import sources
    calls = 0
    class Adapter:
        async def fetch(self,client):
            nonlocal calls
            calls += 1
            return SimpleNamespace(status='error' if calls == 1 else 'success',
                availability='blocked_access' if calls == 1 else 'enabled',
                coverage='Kontrolowany odczyt',message='HTTP 403' if calls == 1 else '',
                retry_after=None,documents=[])
    monkeypatch.setitem(sources.ADAPTERS,'rcb',Adapter())
    repo = Repository(tmp_path/'app.sqlite3')
    config = Config(sources={key:{'enabled':key=='rcb'} for key in sources.ADAPTERS})
    scheduler = Scheduler(repo,config,None)
    with repo.db:
        repo.db.execute("UPDATE sources SET access_state='blocked_access',error='Poprzednia blokada' WHERE id='rcb'")
    try:
        scheduler.start()
        await asyncio.sleep(0.02)
        assert calls == 0  # automatic collection stays stopped after a block
        assert scheduler.refresh('rcb')
        await asyncio.gather(*list(scheduler.tasks.values()))
        row = repo.db.execute("SELECT * FROM sources WHERE id='rcb'").fetchone()
        assert row['access_state'] == 'blocked_access' and row['last_result'] == 'error'
        assert scheduler.refresh('rcb')
        await asyncio.gather(*list(scheduler.tasks.values()))
        row = repo.db.execute("SELECT * FROM sources WHERE id='rcb'").fetchone()
        assert row['access_state'] == 'enabled' and row['last_result'] == 'success'
        assert row['last_successful_check'] and row['failures'] == 0
        assert repo.db.execute("SELECT COUNT(*) FROM fetch_runs WHERE source_id='rcb'").fetchone()[0] == 2
    finally:
        await scheduler.stop()
        repo.close()

@pytest.mark.asyncio
async def test_T25_scheduler_single_and_two_concurrent(tmp_path,monkeypatch):
    from wici import sources
    active=peak=calls=0
    release=asyncio.Event()
    class Adapter:
        async def fetch(self,client):
            nonlocal active,peak,calls
            active+=1; calls+=1; peak=max(peak,active)
            await release.wait()
            active-=1
            return SimpleNamespace(status='success',coverage='Kontrolowany pusty zestaw',message='',availability='enabled',retry_after=None,documents=[])
    monkeypatch.setattr(sources,'ADAPTERS',{s:Adapter() for s in ('imgw_meteo','rso','rcb','sg')})
    repo=Repository(tmp_path/'app.sqlite3')
    scheduler=Scheduler(repo,Config(),None)
    assert scheduler.refresh('rso')
    assert not scheduler.refresh('rso')
    scheduler.refresh('imgw_meteo'); scheduler.refresh('sg')
    await asyncio.sleep(0.02)
    assert peak==2 and calls==2
    release.set()
    await asyncio.gather(*list(scheduler.tasks.values()))
    assert calls==3
    assert repo.db.execute('SELECT COUNT(*) FROM fetch_runs').fetchone()[0]==3
    await scheduler.stop(); repo.close()

@pytest.mark.asyncio
async def test_T26_gap_and_no_replay(tmp_path,monkeypatch):
    repo=Repository(tmp_path/'app.sqlite3')
    with repo.db:
        repo.db.execute("INSERT INTO app_state VALUES('last_tick',?)",((repo.clock()-timedelta(hours=6)).isoformat(),))
        repo.db.execute("INSERT INTO sources(id,name,access_state) VALUES('retired','Historical source','enabled')")
    scheduler=Scheduler(repo,Config(),None)
    assert scheduler.gap_seconds>21000
    assert 'retired' not in {source['id'] for source in scheduler.sources()}
    requests=[]
    monkeypatch.setattr(scheduler,'refresh',lambda s:requests.append(s))
    task=asyncio.create_task(scheduler.loop())
    await asyncio.sleep(0.01)
    task.cancel(); await asyncio.gather(task,return_exceptions=True)
    assert set(requests)=={'imgw_meteo','rso','rcb','sg','ioda'} and len(requests)==5
    assert repo.db.execute("SELECT name FROM sources WHERE id='retired'").fetchone()[0]=='Historical source'
    repo.close()

@pytest.mark.asyncio
async def test_T28_offline_keeps_saved_data(tmp_path):
    def reject(request):
        raise httpx.ConnectError('No network')
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as network:
        repo=Repository(tmp_path/'app.sqlite3')
        from wici.demo import seed
        seed(repo)
        scheduler=Scheduler(repo,Config(),network)
        before=repo.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
        await scheduler.fetch('imgw_meteo')
        assert repo.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==before
        assert repo.db.execute("SELECT last_result FROM sources WHERE id='imgw_meteo'").fetchone()[0]=='error'
        repo.close()


def test_T27_lifespan_never_contacts_sources(tmp_path):
    requests=[]
    def forbid(request):
        requests.append(str(request.url))
        raise AssertionError('Demo attempted network')
    network=httpx.AsyncClient(transport=httpx.MockTransport(forbid))
    with TestClient(create_app(demo=True,root=tmp_path,client=network),base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/communications').json()['total']==5
        for source in ('imgw_meteo','rso','rcb','sg'):
            assert client.post(f'/api/sources/{source}/refresh',headers=headers(client)).status_code==422
        assert not client.app.state.scheduler.tasks
        assert client.app.state.scheduler.loop_task is None
        assert (tmp_path/'var'/'demo'/'app.sqlite3').exists()
        assert not (tmp_path/'var'/'live').exists()
        assert requests==[]
