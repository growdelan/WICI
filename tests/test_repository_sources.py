"""Current persistence invariants, independently of removed editorial features."""
import copy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from wici.models import Document
from wici.repository import Repository
from wici.sources.imgw_pdf import parse_pdf

NOW=datetime(2026,10,13,tzinfo=UTC)
FIXTURES=Path(__file__).parent/'fixtures/imgw_pdf_synthetic'
URL='https://danepubliczne.imgw.pl/data/current/ost_meteo/PMW_STAN_20260903080000000.pdf'


def source(text='Treść',identity='1',**kwargs):
    return Document(source_id='rso',identity_key=identity,url='https://komunikaty.tvp.pl/komunikatyxml/wszystkie/wszystkie/0?_format=json',
        title='Komunikat',text=text,fields={'contract_validated':True,'access_allowed':True},**kwargs)


def test_dedup_a_b_a_and_no_editorial_side_effects(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:NOW)
    first=repo.ingest(source('A'));assert not repo.ingest(source('A'))['changed']
    repo.ingest(source('B'));repo.ingest(source('A'))
    detail=repo.communication_detail(first['document_id'])
    assert [v['text'] for v in detail['history']]==['A','B','A']
    for table in ('events','review_items','operator_actions','model_decisions'):
        assert repo.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
    repo.close()


def test_same_text_different_identity_is_not_merged(tmp_path):
    repo=Repository(tmp_path/'app.sqlite')
    repo.ingest(source(identity='one'));repo.ingest(source(identity='two'))
    assert repo.list_communications()['total']==2
    repo.close()


def test_html_content_never_executes_or_leaks_interface_markup(tmp_path):
    repo=Repository(tmp_path/'app.sqlite')
    saved=repo.ingest(source('<script>secret</script><p>Informacja</p><nav>Menu</nav><iframe>bad</iframe>'))
    assert repo.communication_detail(saved['document_id'])['summary']=='Informacja'
    repo.close()


@pytest.mark.parametrize('field,value',[
    ('valid_from','2026-10-13T12:00:00'),('valid_until','9999-12-31T23:59:59Z'),
])
def test_bad_source_windows_are_rejected_without_partial_storage(tmp_path,field,value):
    repo=Repository(tmp_path/'app.sqlite');data=source().model_dump();data['fields']['event']={field:value}
    with pytest.raises(ValidationError):repo.ingest(data)
    assert repo.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==0
    repo.close()


def test_reversed_source_window_is_rejected():
    data=source().model_dump();data['fields']['event']={'valid_from':'2026-10-14T00:00:00Z','valid_until':'2026-10-13T00:00:00Z'}
    with pytest.raises(ValidationError):Document.model_validate(data)


def pdf(name,split='development'):
    return parse_pdf((FIXTURES/split/name).read_bytes(),URL).documents


def test_synthetic_pdf_forecast_county_and_time_are_visible_without_approval(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:datetime(2026,9,4,12,tzinfo=UTC))
    docs=pdf('PMW_STAN_20260903080000000.pdf')
    for doc in docs:repo.ingest(doc)
    rows=repo.list_communications()['items'];assert len(rows)==20
    item=next(row for row in rows if row['locations'][0]['admin_code']=='2201')
    assert item['warning_status']=='active' and item['official_severity']=='1'
    assert item['valid_from']=='2026-09-04T08:00:00+00:00'
    assert item['valid_until']=='2026-09-04T18:00:00+00:00'
    assert item['locations'][0]['role']=='warning_area'
    assert 'Prognozowane' in item['summary'] and '@' not in item['summary']
    repo.close()


def test_same_pdf_warning_in_new_aggregate_updates_transport_not_substantive_version(tmp_path):
    repo=Repository(tmp_path/'app.sqlite')
    a=pdf('PMW_STAN_20260903080000000.pdf')[0]
    b=pdf('PMW_STAN_20260904080000000.pdf')[0]
    b['url']='https://danepubliczne.imgw.pl/data/current/ost_meteo/PMW_STAN_20260904080000000.pdf'
    b['fields']['source_pdf_url']=b['url']
    saved=repo.ingest(a);assert not repo.ingest(b)['changed']
    item=repo.communication_detail(saved['document_id'])
    assert item['original_url']==a['fields']['source_pdf_url'] and item['url']==b['url']
    assert len(item['history'])==1
    repo.close()


def test_late_pdf_retained_in_history_without_rolling_current_view_back(tmp_path):
    repo=Repository(tmp_path/'app.sqlite')
    older=pdf('SLW_STAN_20260923100000000.pdf','heldout')[0]
    newer=pdf('SLW_STAN_20260923120000000.pdf')[0]
    saved=repo.ingest(newer);late=repo.ingest(older)
    assert late['out_of_order'] and repo.communication_detail(saved['document_id'])['text']==newer['text']
    assert not repo.ingest(older)['changed']
    assert len(repo.communication_detail(saved['document_id'])['history'])==2
    later=copy.deepcopy(newer);later['text']+=' SYNTETYCZNY KOLEJNY ODCZYT.'
    repo.ingest(later)
    assert repo.communication_detail(saved['document_id'])['version_number']==3
    repo.close()


def test_synthetic_pdf_cancellation_updates_current_status_and_keeps_source_history(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:datetime(2026,9,5,16,30,tzinfo=UTC))
    before=pdf('PMW_STAN_20260905080000000.pdf')
    after=pdf('PMW_STAN_20260905160000000.pdf','heldout')
    for doc in [*before,*after]:repo.ingest(doc)
    cancelled=[r for r in repo.list_communications()['items'] if r['warning_status']=='cancelled']
    assert len(cancelled)==20
    assert all(len(repo.communication_detail(r['id'])['history'])==2 for r in cancelled)
    repo.close()


def test_sqlite_reopen_preserves_documents_and_rejects_future_schema(tmp_path):
    path=tmp_path/'app.sqlite';repo=Repository(path);repo.ingest(source());repo.close()
    repo=Repository(path);assert repo.list_communications()['total']==1
    repo.db.execute('PRAGMA user_version=99');repo.db.commit();repo.close()
    with pytest.raises(RuntimeError):Repository(path)
