"""Conservative normalization; dates are never promoted to invented instants."""
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

WARSAW = ZoneInfo('Europe/Warsaw')
PROVINCES = {'dolnoslaskie': '02', 'kujawsko-pomorskie': '04', 'lubelskie': '06', 'lubuskie': '08',
             'lodzkie': '10', 'malopolskie': '12', 'mazowieckie': '14', 'opolskie': '16',
             'podkarpackie': '18', 'podlaskie': '20', 'pomorskie': '22', 'slaskie': '24',
             'swietokrzyskie': '26', 'warminsko-mazurskie': '28', 'wielkopolskie': '30',
             'zachodniopomorskie': '32'}
EXERCISE = re.compile(r'ćwicze|cwicze|trening|test\w* syren|prób\w* syren', re.IGNORECASE)


def plain(value):
    soup = BeautifulSoup(str(value or ''), 'html.parser')
    for node in soup(['script', 'style', 'iframe', 'object']):
        node.decompose()
    return ' '.join(soup.get_text(' ', strip=True).split())


def instant(value):
    if not value:
        return None
    if len(str(value).strip()) <= 10:
        raise ValueError('Sama data nie jest chwilą czasu')
    dt = datetime.fromisoformat(str(value))
    if dt.year == 9999:
        raise ValueError('Techniczna wartość czasu nie jest datą ważności; wymaga kontroli')
    if dt.tzinfo:
        return dt.astimezone(UTC).isoformat()
    # Reject ambiguous/nonexistent local times instead of guessing DST fold.
    a, b = dt.replace(tzinfo=WARSAW, fold=0), dt.replace(tzinfo=WARSAW, fold=1)
    if a.utcoffset() != b.utcoffset() or a.astimezone(UTC).astimezone(WARSAW).replace(tzinfo=None) != dt:
        raise ValueError('Niejednoznaczny lokalny czas Europe/Warsaw')
    return a.astimezone(UTC).isoformat()


@lru_cache(maxsize=1)
def administrative_index():
    """PRG names/codes are independent of optional drawing geometries."""
    path = Path(__file__).parents[1] / 'static' / 'geo' / 'administrative-units.json'
    return json.loads(path.read_text())['units']


@lru_cache(maxsize=1)
def geo_index():
    base = Path(__file__).parents[1] / 'static' / 'geo'
    result = {}
    for name in ('provinces.geojson', 'counties.geojson'):
        path = base / name
        if path.exists():
            for feature in json.loads(path.read_text())['features']:
                p = feature['properties']
                result[p['admin_code']] = p['name']
    return result


def location(code, role, source, name=None):
    index = geo_index()
    names = administrative_index()
    known = code in names or code in PROVINCES.values()
    return {'name': name or names.get(code, code), 'role': role,
            'precision': 'administrative' if known else 'unknown', 'admin_code': code,
            'geometry_ref': code if code in index else None, 'source': source,
            'note': None if code in index else 'Brak lokalnej geometrii' if known else 'Nieznany kod administracyjny'}


def document(source_id, identity, url, title, text, event, reasons, **extra):
    event={k:v for k,v in event.items() if k in ('locations','valid_from','valid_until','warning_status','official_severity')}
    cleaned_title, cleaned_text = plain(title), plain(text)
    sensitive = re.search(
        r'patrol|funkcjonariusz|rozmieszczeni|poszukiw|zatrzyman|\bPESEL\b|\b\d{11}\b|'
        r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|pozycj\w*\s+(?:jednost|służb)',
        cleaned_title + ' ' + cleaned_text, re.IGNORECASE,
    )
    if sensitive:
        cleaned_title = f'Materiał źródła {source_id} z treścią zminimalizowaną'
        cleaned_text = 'Szczegółowa treść pominięta przed zapisem ze względu na możliwe dane osobowe lub operacyjne. Sprawdź oryginał u wydawcy.'
        event = dict(event, locations=[])
        reasons = [*reasons, 'Minimalizacja danych osobowych i operacyjnych przed zapisem']
        extra['redaction_note'] = 'Usunięto potencjalnie wrażliwy tytuł i tekst; zachowano wyłącznie URL oraz bezpieczne metadane.'
    return {'source_id': source_id, 'identity_key': str(identity), 'source_document_id': str(identity),
            'url': url, 'title': cleaned_title or 'Komunikat bez tytułu', 'text': cleaned_text,
            'fields': {'event': event, 'validation_issues': reasons,
                       'contract_validated': True, 'access_allowed': True},
            'parser_version': '2-source-only', **extra}
