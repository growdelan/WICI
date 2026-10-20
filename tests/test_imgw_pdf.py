"""Synthetic PDF contracts, lifecycle and conservative failures."""
import json
from pathlib import Path

import httpx
import pytest

from wici.repository import Repository
from wici.sources.imgw import IMGWPDFAdapter
from wici.sources.imgw_pdf import parse_pdf

FIXTURES = Path(__file__).parent / 'fixtures/imgw_pdf_synthetic'
ARCHIVE = 'https://danepubliczne.imgw.pl/data/arch/ost_meteo/2026/09.zip'
INDEX = 'https://danepubliczne.imgw.pl/data/current/ost_meteo/'


def sample(name, split='development'):
    return (FIXTURES / split / name).read_bytes()


def parsed(name, split='development'):
    return parse_pdf(sample(name, split), ARCHIVE)












@pytest.mark.asyncio
async def test_current_index_latest_pdf_and_no_runtime_archive_or_hydro(tmp_path):
    name='PMW_STAN_20260903080000000.pdf'
    newer='PMW_STAN_20260904080000000.pdf'
    visited=[]
    def handler(req):
        visited.append(str(req.url))
        if req.url.path=='/robots.txt': return httpx.Response(200,text='User-agent: *\nAllow: /')
        if str(req.url)==INDEX:
            return httpx.Response(200,text=f'<h1>Index of /data/current/ost_meteo</h1><a href="../">Parent</a><a href="{name}">{name}</a><a href="{newer}">{newer}</a>')
        if req.url.path.endswith(newer):return httpx.Response(200,content=sample(newer))
        pytest.fail('Unexpected URL '+str(req.url))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r=await IMGWPDFAdapter().fetch(client)
    assert len(r.documents)==40 and r.availability=='enabled'
    assert not any(name in u for u in visited)
    assert all('/arch/' not in u and 'hydro' not in u for u in visited)


@pytest.mark.asyncio
async def test_real_empty_index_keeps_saved_warning(tmp_path):
    repo=Repository(tmp_path/'empty.sqlite3')
    try:
        repo.ingest(parsed('PMW_STAN_20260903080000000.pdf').documents[0])
        def handler(req):
            return httpx.Response(200,text='User-agent: *\nAllow: /' if req.url.path=='/robots.txt'
                                  else '<h1>Index of /data/current/ost_meteo</h1><a href="/data/current/">Parent Directory</a>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            r=await IMGWPDFAdapter().fetch(client)
        assert r.status=='success' and r.availability=='enabled' and not r.documents
        assert repo.db.execute('SELECT count(*) FROM documents').fetchone()[0]==1
    finally: repo.close()


def test_synthetic_fixture_hashes_and_provenance():
    import hashlib
    for p in FIXTURES.rglob('*.pdf'):
        meta=json.loads(p.with_suffix('.json').read_text())
        assert meta['synthetic'] is True and meta['license'] == 'MIT'
        assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']






def test_source_route_migration_rechecks_pdf_without_resetting_application_data(tmp_path):
    from wici.config import Config
    from wici.scheduler import Scheduler
    repo=Repository(tmp_path/'route.sqlite3')
    try:
        repo.db.execute("INSERT INTO sources(id,name,url,access_state,failures,next_due_at) VALUES('imgw_meteo','IMGW','https://danepubliczne.imgw.pl/api/data/warningsmeteo','blocked_access',5,'2099-01-01T00:00:00+00:00')")
        with repo.db: pass
        scheduler=Scheduler(repo,Config(),None)
        row=next(r for r in scheduler.sources() if r['id']=='imgw_meteo')
        assert row['url']==INDEX and row['access_state']=='enabled'
        assert row['next_due_at'] is None and row['failures']==0
    finally: repo.close()


@pytest.mark.asyncio
async def test_good_pdf_survives_unreadable_pdf_and_foreign_link():
    good='PMW_STAN_20260903080000000.pdf';bad='SLW_STAN_20260923120000000.pdf';visited=[]
    def handler(req):
        visited.append(str(req.url))
        if req.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
        if str(req.url)==INDEX:return httpx.Response(200,text=f'<h1>Index of /data/current/ost_meteo</h1><a href="{good}">good</a><a href="{bad}">bad</a><a href="https://other.example/a.pdf">foreign</a>')
        return httpx.Response(200,content=sample(good) if req.url.path.endswith(good) else b'%PDF-damaged')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:r=await IMGWPDFAdapter().fetch(client)
    assert r.status=='partial' and len(r.documents)==21
    assert sum(d['fields']['contract_validated'] for d in r.documents)==20
    assert all('other.example' not in u for u in visited)
    assert not r.documents[-1]['fields']['contract_validated']


@pytest.mark.asyncio
async def test_pdf_request_redirect_is_blocked_and_has_no_auto():
    name='PMW_STAN_20260903080000000.pdf';visited=[]
    def handler(req):
        visited.append(str(req.url))
        if req.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
        if str(req.url)==INDEX:return httpx.Response(200,text=f'<h1>Index of /data/current/ost_meteo</h1><a href="{name}">PDF</a>')
        return httpx.Response(302,headers={'location':'https://other.example/private'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:r=await IMGWPDFAdapter().fetch(client)
    assert r.status=='partial' and r.availability=='blocked_access'
    assert not any(d['fields']['contract_validated'] for d in r.documents)
    assert all('other.example' not in u for u in visited)


@pytest.mark.asyncio
async def test_unknown_owned_pdf_name_creates_review_without_guessing_or_download():
    visited=[]
    def handler(req):
        visited.append(str(req.url))
        return httpx.Response(200,text='User-agent: *\nAllow: /' if req.url.path=='/robots.txt' else '<h1>Index of /data/current/ost_meteo</h1><a href="new-format.pdf">new</a>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:r=await IMGWPDFAdapter().fetch(client)
    assert r.status=='partial' and len(r.documents)==1
    assert not r.documents[0]['fields']['contract_validated']
    assert not any('new-format.pdf' in u for u in visited)


@pytest.mark.asyncio
async def test_known_active_pdf_checked_when_index_empty_without_republishing_untracked_counties():
    name='PMW_STAN_20260903080000000.pdf'
    adapter=IMGWPDFAdapter();adapter.tracked_urls=(INDEX+name,)
    adapter.tracked_identities={'imgw-pdf:2026:2201:100'}
    def handler(req):
        if req.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
        if str(req.url)==INDEX:return httpx.Response(200,text='<h1>Index of /data/current/ost_meteo</h1>')
        return httpx.Response(200,content=sample(name))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:r=await adapter.fetch(client)
    assert r.status=='success' and len(r.documents)==1
    assert r.documents[0]['identity_key']=='imgw-pdf:2026:2201:100'


@pytest.mark.asyncio
async def test_latest_snapshot_wins_over_tracked_older_pdf_without_versions_replay():
    old='PMW_STAN_20260903080000000.pdf';new='PMW_STAN_20260904080000000.pdf'
    adapter=IMGWPDFAdapter();adapter.tracked_urls=(INDEX+old,)
    adapter.tracked_identities={'imgw-pdf:2026:2201:100'}
    def handler(req):
        if req.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
        if str(req.url)==INDEX:return httpx.Response(200,text=f'<h1>Index of /data/current/ost_meteo</h1><a href="{new}">new</a>')
        return httpx.Response(200,content=sample(old if req.url.path.endswith(old) else new))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:r=await adapter.fetch(client)
    assert len(r.documents)==40 and len({d['identity_key'] for d in r.documents})==40
