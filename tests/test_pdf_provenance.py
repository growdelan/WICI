"""Original publisher links stay bound to source versions, never to arbitrary fields."""
from datetime import UTC, datetime

import pytest

from wici.models import Document
from wici.repository import Repository

FIRST='https://danepubliczne.imgw.pl/data/current/ost_meteo/SLW_STAN_202610120900.pdf'
SECOND='https://danepubliczne.imgw.pl/data/current/ost_meteo/SLW_STAN_202610121100.pdf'


def doc(url,*,field_url=None):
    return Document(source_id='imgw_meteo',identity_key='imgw-pdf:2026:1465:123',url=url,
        title='Burze',text=url,fields={'contract_validated':True,'access_allowed':True,
            'recognized_warning_type':True,'source_pdf_url':field_url or url,'event':{}})


def test_original_urls_are_preserved_on_each_source_version(tmp_path):
    repo=Repository(tmp_path/'app.sqlite',clock=lambda:datetime(2026,10,13,tzinfo=UTC))
    first=repo.ingest(doc(FIRST));repo.ingest(doc(SECOND))
    detail=repo.communication_detail(first['document_id'])
    assert detail['original_url']==SECOND
    assert [v['original_url'] for v in detail['history']]==[SECOND,FIRST]
    assert repo.db.execute('SELECT COUNT(*) FROM review_items').fetchone()[0]==0
    repo.close()


@pytest.mark.parametrize('field_url',[
    'https://evil.example/data/current/ost_meteo/test.pdf',
    'http://danepubliczne.imgw.pl/data/current/ost_meteo/test.pdf',
    'https://user:pass@danepubliczne.imgw.pl/data/current/ost_meteo/test.pdf',
    'https://danepubliczne.imgw.pl:443/data/current/ost_meteo/test.pdf',
    'https://danepubliczne.imgw.pl/data/current/ost_meteo/../test.pdf',
    'https://danepubliczne.imgw.pl/data/current/ost_meteo/%2e%2e/test.pdf',
    'https://danepubliczne.imgw.pl/data/current/ost_meteo/test.pdf?redirect=evil',
    'https://danepubliczne.imgw.pl/data/current/ost_meteo/test.pdf#fragment',
    'https://danepubliczne.imgw.pl/data/arch/ost_meteo/2026/13.zip',None,42,
])
def test_untrusted_field_url_does_not_replace_publisher_url(tmp_path,field_url):
    repo=Repository(tmp_path/'app.sqlite')
    document=doc(FIRST);document.fields['source_pdf_url']=field_url
    result=repo.ingest(document)
    assert repo.communication_detail(result['document_id'])['original_url']==FIRST
    repo.close()


def test_archive_pdf_provenance_is_preserved(tmp_path):
    repo=Repository(tmp_path/'app.sqlite')
    archive='https://danepubliczne.imgw.pl/data/arch/ost_meteo/2026/09.zip'
    saved=repo.ingest(doc(FIRST,field_url=archive))
    assert repo.communication_detail(saved['document_id'])['original_url']==archive
    repo.close()
