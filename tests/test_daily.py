from datetime import UTC, date, datetime

import pytest

from wici.daily import civil_day, publication_day
from wici.repository import Repository


@pytest.mark.parametrize('instant,day', [
    ('2026-10-12T22:30:00+00:00', '2026-10-13'),
    ('2026-01-01T23:30:00+00:00', '2026-01-02'),
    ('2026-03-29T00:59:00+00:00', '2026-03-29'),
    ('2026-03-29T01:01:00+00:00', '2026-03-29'),
    ('2026-10-25T00:30:00+00:00', '2026-10-25'),
    ('2026-10-25T01:30:00+00:00', '2026-10-25'),
    ('2026-10-12', '2026-10-12'),
])
def test_warsaw_day(instant, day):
    assert civil_day(instant) == day


def test_day_priority_and_explicit_fallback():
    assert civil_day(date(2026,10,13)) == '2026-10-13'
    assert publication_day({'source_published_date': '2025-01-01', 'source_updated_at': '2026-01-01T00:00:00Z'}, '2026-10-12T00:00:00Z') == ('2025-01-01', 'source_published_date')
    assert publication_day({}, '2026-10-12T22:30:00Z') == ('2026-10-13', 'first_seen_at')
    with pytest.raises(ValueError):
        civil_day('2026-02-30')


def test_synthetic_pdf_counties_compact_to_one_visual_group(tmp_path):
    from pathlib import Path

    from wici.sources.imgw_pdf import parse_pdf
    fixture=Path(__file__).parent/'fixtures/imgw_pdf_synthetic/development/PMW_STAN_20260903080000000.pdf'
    repo=Repository(tmp_path/'authentic.sqlite',clock=lambda:datetime(2026,10,13,tzinfo=UTC))
    try:
        docs=parse_pdf(fixture.read_bytes(),'https://danepubliczne.imgw.pl/data/current/ost_meteo/PMW_STAN_20260903080000000.pdf').documents
        for doc in docs:repo.ingest(doc)
        rows=repo.list_communications({'date':'2026-09-03'})['items']
        assert len(rows)==20 and len({row['compact_group_key'] for row in rows})==1
    finally:repo.close()
