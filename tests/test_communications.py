import copy
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.communications import topic
from wici.models import Document
from wici.repository import Repository
from wici.sources import ADAPTERS
from wici.sources.normalize import document, location

NOW=datetime(2026,10,13,14,tzinfo=UTC)
CORPUS=json.loads((Path(__file__).parent/'fixtures/rso_synthetic_documents.json').read_text())['cases']


@pytest.mark.parametrize('case',CORPUS,ids=lambda c:c['case_id'])
def test_synthetic_communications_appear_without_decisions_or_approval(tmp_path,case):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    data={k:v for k,v in copy.deepcopy(case['document']).items() if k in Document.model_fields}
    data.update(identity_key=case['source_document_id'],url=ADAPTERS['rso'].endpoint)
    repo.ingest(data)
    item=repo.list_communications()['items'][0]
    assert repo.db.execute('SELECT COUNT(*) FROM review_items').fetchone()[0]==0
    assert repo.db.execute('SELECT COUNT(*) FROM model_decisions').fetchone()[0]==0
    assert item['title']==data['title'] and item['summary']==data['text']
    assert item['valid_until'] is None and 'occurred_time' not in item
    assert all(loc['role']=='notification_area' for loc in item['locations'])
    assert repo.communication_detail(item['id'])['history'][0]['text']==data['text']
    repo.close()


def sample(source='rso',identity='water',text='Woda nadaje się do spożycia po przegotowaniu.'):
    return document(source,identity,ADAPTERS[source].endpoint,'Komunikat',text,
        {'title':'Komunikat','summary':'Niepełny skrót','locations':[location('14','notification_area','RSO')],
         'valid_from':'2026-10-12T00:00:00Z','valid_until':'2026-10-14T00:00:00Z'},[],
        source_published_at='2026-10-12T22:30:00Z')


def test_current_source_version_dedup_updates_and_archive_persist(tmp_path):
    path=tmp_path/'app.sqlite';repo=Repository(path,clock=lambda:NOW)
    original=sample();repo.ingest(original);repo.ingest(original)
    assert repo.list_communications({'date':'2026-10-13'})['total']==1
    assert repo.list_communications({'date':'2026-10-12'})['total']==0
    assert repo.list_communications()['total']==1
    updated=sample(text='Odwołano ostrzeżenie. Woda nadaje się do spożycia.')
    repo.ingest(updated)
    id=repo.list_communications()['items'][0]['id']
    assert repo.communication_detail(id)['summary']==updated['text']
    assert len(repo.communication_detail(id)['history'])==2
    repo.close();repo=Repository(path,clock=lambda:NOW)
    assert len(repo.communication_detail(id)['history'])==2
    repo.close()


def test_day_window_is_optional_today_only_and_not_physical_validity(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    data=sample();data['source_published_at']='2026-10-11T12:00:00Z';repo.ingest(data)
    assert repo.list_communications({'date':'2026-10-13'})['total']==0
    carried=repo.list_communications({'date':'2026-10-13','include_active':True})['items'][0]
    assert carried['valid_from'] is None and carried['display_window']['valid_until']
    assert repo.list_communications({'date':'2026-10-12','include_active':True})['total']==0
    assert repo.list_communications({'voivodeship':'14'})['total']==1
    assert repo.list_communications({'voivodeship':'02'})['total']==0
    repo.close()


@pytest.mark.parametrize('source',['rso','rcb','sg','imgw_meteo'])
def test_all_four_sources_need_no_model(tmp_path,source):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    repo.ingest(sample(source=source))
    assert repo.list_communications()['total']==1
    repo.close()


def test_rcb_explicit_provinces_unknown_codes_and_no_place_invention(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    data=sample('rcb',text='Alert w województwach mazowieckim i dolnośląskim. Unikaj podróży.')
    data['fields']['event']['locations']=[];repo.ingest(data)
    item=repo.list_communications()['items'][0]
    assert {loc['admin_code'] for loc in item['locations']}=={'14','02'}
    data=sample('rso','unknown');data['fields']['event']['locations']=[location('99','event_location','RSO')]
    repo.ingest(data)
    assert repo.list_communications()['items'][0]['locations']==[]
    repo.close()


def test_unverified_contract_is_not_misrepresented_and_limits_explicit(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    for identity in ('a','b'):
        repo.ingest(sample(identity=identity))
    bad=sample(identity='bad');bad['fields']['contract_validated']=False;repo.ingest(bad)
    result=repo.list_communications(limit=1)
    assert result['total']==2 and result['limited'] and len(result['items'])==1
    with pytest.raises(KeyError):repo.communication_detail(3)
    repo.close()


def test_demo_api_date_validation_and_removed_model_path(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','this-must-never-be-read-or-sent')
    (tmp_path/'config.local.toml').write_text('[llm]\nenabled=true\nmodel="gpt-6-luna"\n')
    with TestClient(create_app(demo=True,root=tmp_path),base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/health').json()['presentation']=='automatic_communications'
        assert 'llm' not in client.get('/api/health').json()
        rows=client.get('/api/communications?date=2026-10-11&include_active=true').json()['items']
        assert len(rows)==2 and any(row['locations'] for row in rows)
        assert client.get('/api/communications?date=2026-10-10').json()['total']==5
        assert client.get('/api/communications?date=2026-02-30').status_code==422
        assert client.get(f"/api/communications/{rows[0]['id']}").status_code==200
        assert client.get('/api/communications/999999').status_code==404


def test_schema_upgrade_preserves_historical_model_ledger(tmp_path):
    path=tmp_path/'app.sqlite';db=sqlite3.connect(path)
    migrations=Path(__file__).parents[1]/'src/wici/migrations'
    # Build an actual v2 database, independent of later migrations.
    db.executescript((migrations/'001_initial.sql').read_text()
                     +(migrations/'002_model_decisions.sql').read_text())
    data=sample();at='2026-10-13T12:00:00Z'
    db.execute("INSERT INTO sources(id,name) VALUES('rso','RSO')")
    db.execute('''INSERT INTO documents(id,source_id,identity_key,url,first_seen_at,last_checked_at,current_version)
        VALUES(1,'rso',?,?,?, ?,1)''',(data['identity_key'],data['url'],at,at))
    db.execute('''INSERT INTO document_versions(id,document_id,version_number,content_hash,title,text,
        fields_json,parser_version,created_at) VALUES(1,1,1,'legacy-hash',?,?,?,'legacy',?)''',
        (data['title'],data['text'],json.dumps(data['fields']),at))
    proposed=json.dumps({'event':{'title':'Historia','summary':'Historyczna interpretacja'}})
    db.execute("INSERT INTO review_items(document_id,document_version_id,proposed_json,reason,priority,created_at) VALUES(?,?,?,'Dawna kontrola','normal',?)",
        (1,1,proposed,'2026-10-13T12:00:00Z'))
    db.execute("""INSERT INTO model_decisions(review_id,document_version_id,review_version,created_at,
        budget_day,model,status,reserved_input_units,input_tokens) VALUES(?,?,1,?,?,?,'review',1234,456)""",
        (1,1,'2026-10-13T12:00:00Z','2026-10-13','gpt-6-luna'))
    db.execute('PRAGMA user_version=2');db.commit();db.close()
    repo=Repository(path)
    row=dict(repo.db.execute('SELECT * FROM model_decisions').fetchone())
    assert row['policy_version']=='v1' and row['reserved_input_units']==1234 and row['input_tokens']==456
    assert repo.db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert repo.list_communications()['total']==1
    repo.close()


@pytest.mark.parametrize('text,expected',[
    ('Susza hydrologiczna zlewnia rzeki Gwdy','weather'),
    ('Utrudnienia na dpg w Grzechotkach','border'),
    ('Utrudnienie na A1. Zderzenie pojazdów.','infrastructure'),
    ('Woda po przegotowaniu','public_safety'),
    ('Ćwiczenia Syrena-26','other_context'),
    ('Ograniczony przepływ wody. Susza hydrologiczna.','weather'),
    ('To nie są ćwiczenia. Realny alarm.','public_safety'),
])
def test_topics_are_navigation_tags_and_border_does_not_match_ograniczony(text,expected):
    assert topic(text,'rso')==expected


def test_imgw_source_severity_cancellation_and_identical_pdf_group(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    data=sample('imgw_meteo','a');data['fields'].update(recognized_warning_type=True,
        source_pdf_url='https://danepubliczne.imgw.pl/data/current/ost_meteo/test.pdf')
    data['fields']['event'].update(official_severity='3',warning_status='cancelled')
    repo.ingest(data);data['identity_key']='b';repo.ingest(data)
    rows=repo.list_communications()['items']
    assert all(r['official_severity']=='3' and r['warning_status']=='cancelled' for r in rows)
    assert rows[0]['compact_group_key']==rows[1]['compact_group_key']
    data['identity_key']='c';data['text']='Inny komunikat.';repo.ingest(data)
    assert repo.list_communications()['items'][0]['compact_group_key']!=rows[0]['compact_group_key']
    repo.close()
