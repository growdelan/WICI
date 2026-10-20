"""Original synthetic PDF scenarios and adversarial text variants."""
import json
from pathlib import Path

import pytest

from wici.models import Document, SourceMetadata
from wici.sources import imgw_pdf

ROOT=Path(__file__).parents[1]
DATA=json.loads((ROOT/'tests/fixtures/imgw_pdf_quality.json').read_text())
FIXTURES=ROOT/'tests/fixtures/imgw_pdf_synthetic'
URL='https://danepubliczne.imgw.pl/data/arch/ost_meteo/2026/09.zip'

def observations(case):
    result=imgw_pdf.parse_pdf((FIXTURES/'heldout'/case['member']).read_bytes(),URL)
    rows=[]
    for raw in result.documents:
        doc=Document.model_validate(raw);event=SourceMetadata.model_validate(doc.fields['event'])
        rows.append({'name': doc.title.split('IMGW, ')[-1],'code': doc.fields.get('county_code'),'warning_number': doc.fields.get('county_warning_number'),'phenomenon': doc.title.split(' — ')[0],'grade': event.official_severity,'published_utc': doc.source_published_at.isoformat() if doc.source_published_at else None,'valid_from_utc': event.valid_from.isoformat() if event.valid_from else None,'valid_until_utc': event.valid_until.isoformat() if event.valid_until else None,'action': doc.fields.get('pdf_action'),'identity': doc.identity_key,'cancelled': event.warning_status=='cancelled','roles': [l.role for l in event.locations],'geometry': [l.geometry_ref for l in event.locations],'redaction_note': doc.redaction_note})
    return rows

def expected(case):
    return [dict(county,**{k:sec[k]for k in ['phenomenon','grade','published_utc','valid_from_utc','valid_until_utc','action']})for sec in case['sections'] for county in sec['counties']]

@pytest.mark.parametrize('case',DATA['heldout'],ids=[c['member']for c in DATA['heldout']])
def test_manual_table_annotation(case):
    actual=observations(case);want=expected(case)
    assert len(actual)==len(want)
    for a,e in zip(actual,want):
        for k,v in e.items():assert a[k]==v,(case['member'],e['name'],k,a[k],v)
        assert a['identity']==f"imgw-pdf:2026:{e['code']}:{e['warning_number']}"
        assert a['cancelled']==(e['action']=='ODWOŁANIE')
        assert a['roles']==['warning_area'] and a['geometry']==[e['code']]
        assert a['redaction_note']

@pytest.mark.parametrize('case',DATA['adversarial_variants'],ids=[c['id']for c in DATA['adversarial_variants']])
def test_explicit_negative_adversarial_variant(monkeypatch,case):
    original=(FIXTURES/'development'/Path(case['source_member']).with_suffix('.txt')).read_text()
    assert case['replace_from'] in original
    derived=original.replace(case['replace_from'],case['replace_to'])
    monkeypatch.setattr(imgw_pdf,'extract_pdf',lambda payload:derived)
    try:result=imgw_pdf.parse_pdf(b'%PDF-test-extracted-text-variant',URL)
    except ValueError:return  # whole-document rejection is safe for an invalid table
    assert result.documents
    target=result.documents[0]
    doc=Document.model_validate(target)
    metadata=SourceMetadata.model_validate(doc.fields['event'])
    assert not any(key in doc.fields['event'] for key in ('kind','summary','occurred_time','event_phase'))
    assert all(loc.precision=='administrative' and loc.admin_code for loc in metadata.locations)
    if 'grade' in case['id']:
        assert doc.fields['recognized_warning_type'] is False
    if any(term in case['id'] for term in ('missing_validity','reversed_validity','invalid_calendar_day')):
        assert metadata.valid_from is None and metadata.valid_until is None
    if any(term in case['id'] for term in ('ambiguous_publication','nonexistent_publication')):
        assert doc.source_published_at is None
    if 'unknown_county' in case['id']:
        assert not metadata.locations
    if 'duplicate_probability' in case['id']:
        assert doc.fields['contract_validated'] is False


def test_quality_traceability_and_case_count():
    assert len(DATA['adversarial_variants'])>=20
    assert len({c['id']for c in DATA['adversarial_variants']})==len(DATA['adversarial_variants'])
    assert all(c['origin'].startswith('adversarial_text_variant')for c in DATA['adversarial_variants'])
    assert len(DATA['heldout'])==4
