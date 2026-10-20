"""Build original synthetic PDF contract cases, offline, using only pypdf.

No downloaded document, embedded font, logo, map or provider text is used.
Run: uv run --locked python scripts/prepare_imgw_pdf_fixtures.py
"""
import hashlib
import json
import textwrap
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from wici.sources.normalize import administrative_index

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/imgw_pdf_synthetic'
NAMES = {
    'initial': 'PMW_STAN_20260903080000000.pdf',
    'aggregate': 'PMW_STAN_20260904080000000.pdf',
    'rain': 'DSW_STAN_20260909080000000.pdf',
    'change': 'SLW_STAN_20260923120000000.pdf',
    'before_cancel': 'PMW_STAN_20260905080000000.pdf',
    'mixed': 'OPW_STAN_20260916080000000.pdf',
    'heat': 'MAW_STAN_20260909080000000.pdf',
    'cancel': 'PMW_STAN_20260905160000000.pdf',
    'older': 'SLW_STAN_20260923100000000.pdf',
}
# PDF standard font glyph names: no external font binary is distributed.
POLISH = dict(zip('ĄąĆćĘęŁłŃńÓóŚśŹźŻż',
    ['Aogonek', 'aogonek', 'Cacute', 'cacute', 'Eogonek', 'eogonek', 'Lslash', 'lslash', 'Nacute', 'nacute', 'Oacute', 'oacute', 'Sacute', 'sacute', 'Zacute', 'zacute', 'Zdotaccent', 'zdotaccent']))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def write_pdf(path, text):
    writer = PdfWriter()
    encoding = {char: 128 + i for i, char in enumerate(POLISH)}
    differences = ArrayObject([NumberObject(128)] + [NameObject('/' + glyph) for glyph in POLISH.values()])
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
        NameObject('/Encoding'): DictionaryObject({NameObject('/Type'): NameObject('/Encoding'),
            NameObject('/BaseEncoding'): NameObject('/WinAnsiEncoding'), NameObject('/Differences'): differences})}))
    lines = [wrapped for line in text.splitlines() for wrapped in (textwrap.wrap(line, 88) or [''])]
    for offset in range(0, len(lines), 35):
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        commands = ['BT /F1 10 Tf 14 TL 40 800 Td']
        for line in lines[offset:offset + 35]:
            raw = bytes(encoding[c] if c in encoding else ord(c) for c in line)
            commands.append('<' + raw.hex() + '> Tj T*')
        commands.append('ET')
        stream = DecodedStreamObject(); stream.set_data('\n'.join(commands).encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_metadata({'/Title': 'WICI synthetic parser fixture - not an IMGW warning', '/Author': 'WICI',
                         '/Subject': 'Original offline test content, MIT'})
    with path.open('wb') as output:
        writer.write(output)


def section(province, count, number, kind='Intensywne opady deszczu', grade='1',
            day=4, issue_day=3, issue_hour=8, action='warning', start_hour=10, end_hour=20):
    index = administrative_index()
    counties = [{'code': c, 'name': n.removeprefix('powiat '), 'warning_number': str(number)}
                for c, n in sorted(index.items()) if len(c) == 4 and c.startswith(province)][:count]
    return {'phenomenon': kind, 'grade': grade, 'action': action, 'counties': counties,
            'published_utc': f'2026-09-{issue_day:02d}T{issue_hour-2:02d}:00:00+00:00',
            'valid_from_utc': None if action == 'ODWOŁANIE' else f'2026-09-{day:02d}T{start_hour-2:02d}:00:00+00:00',
            'valid_until_utc': None if action == 'ODWOŁANIE' else f'2026-09-{day:02d}T{end_hour-2:02d}:00:00+00:00',
            'issue': f'godz. {issue_hour:02d}:00 dnia {issue_day:02d}.09.2026',
            'validity': f'od godz. {start_hour:02d}:00 dnia {day:02d}.09.2026 do godz. {end_hour:02d}:00 dnia {day:02d}.09.2026'}


def table(province, sections):
    lines = ['WICI - SYNTETYCZNE DANE TESTOWE. NIE JEST TO OSTRZEŻENIE.',
             f'WOJEWÓDZTWO {administrative_index()[province]} OSTRZEŻENIA METEOROLOGICZNE ZBIORCZO NR 1',
             'WYKAZ OBOWIĄZUJĄCYCH OSTRZEŻEŃ']
    for sec in sections:
        lines += ['Zjawisko/Stopień zagrożenia', sec['phenomenon'] + '/' + sec['grade'] +
                  ('' if sec['action'] == 'warning' else ' ' + sec['action']),
                  'Obszar (w nawiasie numer ostrzeżenia dla powiatu)',
                  'powiaty: ' + ', '.join(c['name'] + '(' + c['warning_number'] + ')' for c in sec['counties'])]
        if sec['action'] == 'ODWOŁANIE':
            lines += ['Czas odwołania', sec['issue'], 'Przyczyna', 'Syntetyczny koniec scenariusza testowego WICI.']
        else:
            lines += ['Ważność', sec['validity'], 'Prawdopodobieństwo', '65%', 'Przebieg',
                      'Prognozowane wartości są fikcyjne i służą wyłącznie testom WICI.']
        lines += ['Uwagi', 'Brak.', 'Godzina i data wydania', sec['issue']]
    return '\n'.join(lines) + '\n'


def main():
    a = section('22', 20, 100)
    scenarios = [
        ('development', 'initial', '22', [a]),
        ('development', 'aggregate', '22', [a, section('22', 20, 200, kind='Silny wiatr', day=5, issue_day=4)]),
        ('development', 'rain', '02', [section('02', 3, 400, day=9, issue_day=9)]),
        ('development', 'change', '24', [section('24', 9, 500, kind='Upał', day=23, issue_day=23, issue_hour=12, action='ZMIANA')]),
        ('development', 'before_cancel', '22', [section('22', 20, 300, day=5, issue_day=5)]),
        ('heldout', 'mixed', '16', [section('16', 3, 600, day=16, issue_day=16),
             section('16', 2, 601, kind='Burze', grade='2', day=16, issue_day=16),
             section('16', 2, 602, kind='Silny wiatr', grade='3', day=16, issue_day=16, action='ZMIANA')]),
        ('heldout', 'heat', '14', [section('14', 5, 700, kind='Upał', day=9, issue_day=9)]),
        ('heldout', 'cancel', '22', [section('22', 20, 300, day=5, issue_day=5, issue_hour=16, action='ODWOŁANIE'),
             section('22', 6, 301, kind='Burze', day=5, issue_day=5, issue_hour=16)]),
        ('heldout', 'older', '24', [section('24', 9, 500, kind='Upał', day=23, issue_day=23, issue_hour=10)]),
    ]
    heldout, manifest = [], []
    for split, key, province, sections in scenarios:
        path = DEST / split / NAMES[key]; path.parent.mkdir(parents=True, exist_ok=True)
        text = table(province, sections)
        write_pdf(path, text); path.with_suffix('.txt').write_text(text)
        meta = {'synthetic': True, 'license': 'MIT', 'generator': 'scripts/prepare_imgw_pdf_fixtures.py',
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'case': key}
        write_json(path.with_suffix('.json'), meta); manifest.append({'file': str(path.relative_to(DEST)), **meta})
        if split == 'heldout':
            heldout.append({'member': path.name, 'sections': [{k: v for k, v in s.items() if k not in ('issue', 'validity')} for s in sections]})
    area = a['counties'][0]['name'] + '(100)'
    last = a['counties'][-1]['name'] + '(100)'
    edits = [
        ('unknown_county', area, 'Atlantyda(100)'), ('unparsed_area_suffix', last, last + ', dodatkowy obszar'),
        ('duplicate_county', area, area + ', ' + area), ('zero_warning_number', area, area.replace('100', '0')),
        ('missing_warning_number', area, a['counties'][0]['name']), ('missing_validity', 'Ważność', 'Nieznana ważność'),
        ('reversed_validity', 'do godz. 20:00 dnia 04.09.2026', 'do godz. 09:00 dnia 04.09.2026'),
        ('invalid_calendar_day', '04.09.2026', '31.09.2026'),
        ('ambiguous_publication_dst', a['issue'], 'godz. 02:30 dnia 25.10.2026'),
        ('nonexistent_publication_dst', a['issue'], 'godz. 02:30 dnia 29.03.2026'),
        ('unsupported_phenomenon', 'Intensywne opady deszczu/1', 'Mgła/1'),
        ('zero_grade', 'Intensywne opady deszczu/1', 'Intensywne opady deszczu/0'),
        ('out_of_range_grade', 'Intensywne opady deszczu/1', 'Intensywne opady deszczu/4'),
        ('missing_forecast_label', 'Przebieg', 'Nieznany przebieg'), ('zero_probability', '65%', '0%'),
        ('excess_probability', '65%', '101%'), ('missing_issuance', 'Godzina i data wydania', 'Nieznana data wydania'),
        ('exercise_note', 'Uwagi\nBrak.', 'Uwagi\nĆwiczenie ostrzegania.'),
        ('correction_note', 'Uwagi\nBrak.', 'Uwagi\nSprostowanie komunikatu.'),
        ('negated_warning', 'Uwagi\nBrak.', 'Uwagi\nOstrzeżenie nie obowiązuje.'),
        ('duplicate_probability_label', 'Prawdopodobieństwo\n65%', 'Prawdopodobieństwo\n0%\nPrawdopodobieństwo\n65%'),
    ]
    write_json(DEST / 'manifest.json', {'synthetic': True, 'license': 'MIT', 'samples': manifest})
    write_json(ROOT / 'tests/fixtures/imgw_pdf_quality.json', {'synthetic': True, 'license': 'MIT',
        'annotation_method': 'Expected values specified in synthetic scenario definitions, not read back from parser output.',
        'heldout': heldout, 'adversarial_variants': [{'id': 'pdf-derived-' + key,
            'origin': 'adversarial_text_variant_of_original_synthetic_fixture', 'source_member': NAMES['initial'],
            'replace_from': old, 'replace_to': new} for key, old, new in edits]})
    (DEST / 'README.md').write_text('# Syntetyczne dokumenty PDF\n\nAutorskie dane testowe WICI na MIT, wygenerowane offline przez '
        '`scripts/prepare_imgw_pdf_fixtures.py`. Nie są dokumentami IMGW ani rzeczywistymi ostrzeżeniami. '
        'Nazwy pól są kontraktem parsera; nazwy i kody jednostek pochodzą z lokalnego słownika PRG. '
        'Czasy, numery i treść zdarzeń są zmyślone. PDF używa standardowej czcionki Helvetica bez dołączania pliku fontu.\n\n'
        'Zestaw obejmuje agregację, zmianę, odwołanie, kilka sekcji, wiele stron i 21 błędnych wariantów tekstu. '
        '`heldout` oznacza odrębne scenariusze regresji, nie niezależny zbiór autentycznych dokumentów.\n')


if __name__ == '__main__':
    main()
