"""Validated IMGW provincial PDF tables; each printed county warning is a logical document."""
import io
import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .base import FetchResult
from .normalize import EXERCISE, administrative_index, document, instant, location

TYPES = {'Intensywne opady deszczu', 'Silny wiatr', 'Upał', 'Burze'}
DATE = r'(\d{2}:\d{2}) dnia (\d{2}\.\d{2}\.\d{4})'
LABELS = ['Zjawisko/Stopień zagrożenia', 'Obszar (w nawiasie numer ostrzeżenia dla powiatu)',
          'Ważność', 'Prawdopodobieństwo', 'Przebieg', 'Czas odwołania', 'Przyczyna',
          'SMS', 'RSO', 'Uwagi', 'Godzina i data wydania']
LABEL = re.compile('(' + '|'.join(re.escape(v) for v in sorted(LABELS, key=len, reverse=True)) + ')')


def normalized(value):
    value = unicodedata.normalize('NFKD', value.casefold().replace('ł', 'l'))
    return ''.join(c for c in value if not unicodedata.combining(c)).strip()


def moment(clock, day):
    return instant(datetime.strptime(day+' '+clock, '%d.%m.%Y %H:%M').isoformat())


def extract_pdf(payload):
    if not payload.startswith(b'%PDF-'):
        raise ValueError('IMGW: oczekiwano PDF, nie HTML ani JSON')
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 6:
            raise ValueError('IMGW: zaszyfrowany PDF lub nieobsługiwana liczba stron')
        # No OCR, scripts, attachments or annotations executed; retain only table text.
        pages = []
        for page in reader.pages:
            contents = page.get_contents()
            if contents and len(contents.get_data()) > 8_000_000:
                raise ValueError('IMGW: strumień strony przekracza limit parsera')
            pages.append(page.extract_text() or '')
        text = '\n'.join(pages)
        if not text.strip() or len(text) > 100_000:
            raise ValueError('IMGW: brak tekstu lub zbyt duży dokument; OCR nie jest używany')
        return text
    except (PdfReadError, OSError, IndexError) as exc:
        raise ValueError('IMGW: nieczytelny PDF') from exc


def parse_pdf(payload, url):
    text = extract_pdf(payload)
    # Drop contacts, signatures and all non-table page furniture before persistence.
    text = '\n'.join(line for line in text.splitlines() if not re.match(
        r'^\s*(Instytut Meteorologii|Centralne Biuro|Regionalne Biuro|strona \d|Zasięg ostrzeżeń)', line))
    text = ' '.join(text.split())
    province_match = re.search(r'WOJEWÓDZTWO (.+?) OSTRZEŻENIA\s+METEOROLOGICZNE\s+ZBIORCZO\s+NR (\d+)', text)
    if not province_match or 'WYKAZ OBOWIĄZUJĄCYCH OSTRZEŻEŃ' not in text:
        raise ValueError('IMGW: nieobsługiwany szablon PDF')
    name = normalized(province_match[1])
    province_codes = [c for c, n in administrative_index().items() if len(c) == 2 and normalized(n) == name]
    if len(province_codes) != 1:
        raise ValueError('IMGW: nierozpoznane województwo PDF')
    province = province_codes[0]
    counties = {normalized(n.removeprefix('powiat ')): c for c, n in administrative_index().items()
                if len(c) == 4 and c.startswith(province)}
    sections = text.split('Zjawisko/Stopień zagrożenia')[1:]
    if not 1 <= len(sections) <= 20:
        raise ValueError('IMGW: brak lub nadmiar sekcji ostrzeżeń')
    docs, invalid = [], 0
    for section_index, section in enumerate(sections):
        parts = LABEL.split('Zjawisko/Stopień zagrożenia'+section)
        labels = parts[1::2]
        duplicates = {key for key in labels if labels.count(key) > 1}
        fields = {parts[i]: parts[i+1].strip() for i in range(1, len(parts)-1, 2)}
        # Stop at the source's own issuance field; later signatures/legal footer are never saved.
        release = re.match(r'godz\. '+DATE, fields.get('Godzina i data wydania', ''))
        if not release:
            invalid += 1
            safe = document('imgw_meteo', f'pdf-unparsed:{PurePosixPath(url).name}:{section_index}', url,
                            'Ostrzeżenie IMGW — niepełna sekcja PDF', 'Nie ustalono wymaganych pól tabeli. Sprawdź oryginał.',
                            {}, ['Niepełny schemat sekcji PDF'])
            safe['fields']['contract_validated'] = False
            docs.append(safe)
            continue
        fields['Godzina i data wydania'] = release[0]
        reasons = []
        if duplicates:
            reasons.append('Powtórzone pola tabeli wymagają kontroli: '+', '.join(sorted(duplicates)))
        phenomenon = re.fullmatch(r'(.+?)/(\d)(?:\s+(ZMIANA|ODWOŁANIE))?', fields.get(LABELS[0], ''))
        kind = phenomenon[1] if phenomenon else fields.get(LABELS[0], 'Nieznany typ')
        severity = phenomenon[2] if phenomenon else None
        action = phenomenon[3] if phenomenon else None
        if not phenomenon or kind not in TYPES or severity not in ('1','2','3'):
            reasons.append('Nieobsługiwany typ lub stopień ostrzeżenia PDF')
        try:
            published = moment(release[1], release[2])
        except ValueError:
            published = None
            reasons.append('Niejednoznaczny czas wydania')
        validity = re.fullmatch(r'od godz\. '+DATE+r' do godz\. '+DATE, fields.get('Ważność', ''))
        start = end = None
        try:
            if validity:
                start, end = moment(validity[1], validity[2]), moment(validity[3], validity[4])
                if end <= start:
                    raise ValueError('Nieprawidłowy przedział')
            if not validity and action != 'ODWOŁANIE':
                reasons.append('Nieustalona ważność ostrzeżenia')
        except ValueError:
            start = end = None
            reasons.append('Niejednoznaczny czas ważności')
        area = fields.get(LABELS[1], '')
        county_pairs = re.findall(r'([^,()]+)\((\d+)\)', area.removeprefix('powiaty:').strip())
        remainder = re.sub(r'[^,()]+\(\d+\)', '', area.removeprefix('powiaty:').strip()).replace(',', '').strip()
        if not county_pairs or remainder or len({normalized(n) for n, _ in county_pairs}) != len(county_pairs):
            reasons.append('Niepełny lub niejednoznaczny wykaz powiatów')
        if not county_pairs:
            county_pairs = [(area or 'Nieustalony obszar', 'unknown')]
        forecast = fields.get('Przebieg') or fields.get('Przyczyna') or ''
        if not forecast:
            reasons.append('Brak treści ostrzeżenia')
        if action != 'ODWOŁANIE' and not re.fullmatch(r'(?:100|[1-9]\d?)%', fields.get('Prawdopodobieństwo', '')):
            reasons.append('Niepoprawne prawdopodobieństwo')
        # Plain source table text only, source wording preserved, no new explanatory claims.
        safe_text = '\n'.join(f'{k}: {fields[k]}' for k in LABELS if k in fields)
        if duplicates:
            # Keep conflicting values visible to the reader, but stop before signatures.
            safe_text = ('Zjawisko/Stopień zagrożenia'+section).split('Godzina i data wydania', 1)[0]
            safe_text += ' Godzina i data wydania: '+release[0]
        if EXERCISE.search(safe_text) or re.search(r'(?i)nie obowiązuje|sprostow|dement', safe_text):
            reasons.append('Ćwiczenie, negacja lub sprostowanie wymaga kontroli')
        year = release[2][-4:]
        if validity and any(day[-4:] != year for day in (validity[2], validity[4])):
            reasons.append('Ostrzeżenie na granicy lat: numer roczny wymaga kontroli')
        for county_name, number in county_pairs:
            record_reasons = list(reasons)
            code = counties.get(normalized(county_name))
            if not code:
                record_reasons.append('Nieznana lub niejednoznaczna nazwa powiatu w województwie')
            if number == 'unknown' or int(number) < 1:
                record_reasons.append('Brak poprawnego numeru ostrzeżenia dla powiatu')
            title = f'{kind} — IMGW, {county_name.strip()}'
            event = {'official_severity':severity,'locations':[location(code,'warning_area','IMGW-PIB')] if code else [],
                     'valid_from':start,'valid_until':end}
            if action == 'ODWOŁANIE':
                event['warning_status'] = 'cancelled'
            identity = f'imgw-pdf:{year}:{code}:{number}' if code and number != 'unknown' else f'pdf-review:{PurePosixPath(url).name}:{section_index}:{county_name}'
            doc = document('imgw_meteo',identity,url,title,safe_text,event,record_reasons,
                           source_published_at=published,source_updated_at=published,
                           redaction_note='Zachowano tylko pola tabeli ostrzeżenia; usunięto podpisy, kontakty, mapę i stopki.')
            doc['parser_version'] = 'imgw-pdf/2'
            doc['fields'].update(recognized_warning_type=kind in TYPES and severity in ('1','2','3') and not (EXERCISE.search(safe_text) or re.search(r'(?i)nie obowiązuje|sprostow|dement',safe_text)), source_pdf_url=url,
                                 county_warning_number=number, county_code=code, issued_year=year,
                                 source_timezone_assumption='Europe/Warsaw: jawne godziny lokalne oficjalnego polskiego ostrzeżenia',
                                 pdf_action=action or 'warning')
            if duplicates:
                doc['fields']['contract_validated']=False
            docs.append(doc)
    # The same county warning number cannot describe two different sections in one snapshot.
    identities = [d['identity_key'] for d in docs]
    duplicate_ids = {identity for identity in identities if identities.count(identity) > 1}
    for doc in docs:
        if doc['identity_key'] in duplicate_ids:
            doc['fields']['contract_validated'] = False
            doc['fields']['validation_issues'].append('Sprzeczne sekcje o tym samym numerze ostrzeżenia powiatu')
    return FetchResult(documents=docs, status='partial' if invalid or any(d['fields']['validation_issues'] for d in docs) else 'success',
                       message=f'{len(docs)} ostrzeżeń powiatowych; ograniczenia odczytu są zapisane w metadanych.',
                       coverage='Najnowszy zbiorczy PDF każdego województwa; meteorologia, bez hydro i archiwalnego backfillu.')
