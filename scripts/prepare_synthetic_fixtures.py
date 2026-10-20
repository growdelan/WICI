"""Create original offline contract samples. Never reads captured provider data or uses the network."""
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from wici.gfm import LAYERS
from wici.sources.normalize import document, location

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures'
NOTICE = {'synthetic': True, 'license': 'MIT', 'author': 'WICI', 'purpose': 'Offline contract regression; not provider data'}


def save(name, data):
    p = DEST / name; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def main():
    news = [{'id': f'wici-synthetic-{i}', 'title': title, 'content': content,
             'created_at': '2026-10-12 09:00:00', 'updated_at': '2026-10-12 10:00:00',
             'valid_from': '2026-10-12 08:00:00', 'valid_to': '2026-10-14 18:00:00',
             'provinces': {'test': {'slug_name': 'mazowieckie', 'name': 'mazowieckie'}}}
            for i, (title, content) in enumerate([
                ('WICI - syntetyczny komunikat', 'Przykładowa informacja o fikcyjnym zbiorniku Testowym.'),
                ('WICI - ćwiczenia testowe', 'Ćwiczenia w fikcyjnej miejscowości Testowo. Dane syntetyczne.')], 1)]
    save('rso_synthetic.json', {**NOTICE, 'newses': news, 'pagination': {'totalitems': 2}})
    cases = []
    for i in range(18):
        doc = document('rso', f'wici-case-{i}', 'https://example.invalid/rso', f'WICI test {i}',
                       f'Syntetyczna treść komunikatu {i}; nie opisuje rzeczywistego zdarzenia.',
                       {'locations': [location('14' if i % 2 else '22', 'notification_area', 'WICI synthetic')]}, [],
                       source_published_at='2026-10-13T08:00:00Z')
        cases.append({'case_id': f'synthetic-{i}', 'source_document_id': f'wici-case-{i}', 'document': doc})
    save('rso_synthetic_documents.json', {**NOTICE, 'cases': cases})
    (DEST / 'sg_synthetic.html').write_text('''<!doctype html><meta charset="utf-8"><!-- Original WICI synthetic fixture, MIT -->
<div id="content"><div class="head"><h2>Utrudnienia na przejściu Testowym - WICI</h2>
<h3>Syntetyczny komunikat do testu parsera.</h3></div><section class="metryka"><div class="data">12.10.2026</div></section>
<article class="txt">Prace konserwacyjne w fikcyjnym obiekcie. To nie jest informacja o prawdziwym przejściu.</article></div>''')
    (DEST / 'rcb_synthetic.html').write_text('''<!doctype html><meta charset="utf-8"><!-- Original WICI synthetic fixture, MIT -->
<article><h1>Alert RCB - ćwiczenia WICI</h1><div class="date">11.10.2026</div>
<div class="editor-content">Ćwiczenia fikcyjnego systemu Testowo. Autorski przykład testowy, nie rzeczywisty alert.</div></article>''')
    (DEST / 'rcb_list_synthetic.html').write_text('''<!doctype html><meta charset="utf-8"><!-- Original WICI synthetic fixture, MIT -->
<main><article><div class="art-prev"><ul>''' + ''.join(
        f'<li><div class="title"><a href="/web/rcb/alert-rcb-wici-synthetic-{i}">Alert RCB - test {i}</a></div><span class="date">11.10.2026</span></li>'
        for i in range(10)) + '</ul></div></article></main>')
    # GIOŚ field names are the application contract. IDs, sites and measurements are invented.
    fields = {'stations': 'Lista stacji pomiarowych', 'sensors': 'Lista stanowisk pomiarowych dla podanej stacji', 'data': 'Lista danych pomiarowych'}
    for kind, rows in [
        ('stations', [{'Identyfikator stacji': 9001 + i, 'Nazwa stacji': f'WICI syntetyczna stacja {i}',
                       'WGS84 φ N': [52.0, 54.0, 49.5][i], 'WGS84 λ E': [19.0, 14.5, 23.0][i],
                       'Nazwa miasta': 'Testowo', 'Kod stacji': f'WICI-{i}', 'Województwo': 'mazowieckie'} for i in range(3)]),
        ('sensors', [{'Identyfikator stanowiska': identity, 'Identyfikator stacji': 9001, 'Wskaźnik - kod': 'PM10'}
                     for identity in (9100, 9101)]),
        ('data', [{'Data': (datetime(2026, 10, 17, 8) - timedelta(hours=i)).isoformat(' '),
                   'Wartość': 12.5 if i == 0 else None if i == 2 else i % 9, 'Kod stanowiska': 'WICI-9101'} for i in range(30)]),
    ]:
        save(f'gios/{kind}.json', {**NOTICE, fields[kind]: rows, 'totalPages': 1, 'totalElements': len(rows),
                                 'links': {'next': 'https://example.invalid/broken-next'}})
    save('gios/manual.json', {**NOTICE, 'error_code': 'API-ERR-100003', 'error_reason': 'Syntetyczny przypadek stanowiska manualnego'})
    save('gios/index.json', {**NOTICE, 'totalPages': 1, 'AqIndex': {'Identyfikator stacji pomiarowej': 9001, 'Wartość indeksu': 1,
        'Nazwa kategorii indeksu': 'Dobry', 'Status indeksu ogólnego dla stacji pomiarowej': True,
        'Data danych źródłowych, z których policzono wartość indeksu dla wskaźnika st': '2026-10-17 08:00:00',
        'Data wykonania obliczeń indeksu': '2026-10-17 08:15:00'}})
    # Legend expectations are a contract of WICI's own UI, not a copied portal/document.
    save('gios/legend.json', {**NOTICE, 'categories': [{'color': color} for color in
        ['#57b108', '#b0dd10', '#ffd911', '#e58100', '#e50000', '#990000']]})
    hydro = [{'synthetic': True, 'id_stacji': f'wici-hydro-{i}', 'stacja': f'Stacja Testowa {i}', 'rzeka': 'Rzeka Testowa',
              'lat': 52.1 + i * .1, 'lon': 19.2, 'wojewodztwo': 'mazowieckie', 'stan_wody': str(200 + i),
              'stan_wody_data_pomiaru': '2026-10-17 05:20:00', 'stan_ostrzegawczy': '300', 'stan_alarmowy': '340',
              'przeplyw': '0.5', 'przeplyw_data': '2026-10-16 05:00:00', 'temperatura_wody': None}
             for i in range(5)]
    save('imgw_hydro/hydro.json', hydro)
    common = {'synthetic': True, 'biuro': 'WICI synthetic', 'przebieg': 'Fikcyjny scenariusz testowy WICI.',
              'komentarz': 'Nie jest to rzeczywiste ostrzeżenie.', 'prawdopodobienstwo': '60',
              'opublikowano': '2026-10-16 18:00:00', 'data_od': '2026-10-16 19:00:00',
              'obszary': [{'wojewodztwo': 'pomorskie', 'opis': 'Fikcyjna zlewnia testowa', 'kod_zlewni': ['WICI-1']}]}
    save('imgw_hydro/warningshydro.json', [{**common, 'numer': '900', 'zdarzenie': 'Syntetyczna susza',
          'stopień': '-1', 'data_do': '9999-12-31 23:59:59'}, {**common, 'numer': '901',
          'zdarzenie': 'Syntetyczne wezbranie', 'stopień': '1', 'data_do': '2026-10-18 18:00:00'}])
    root = Element('utrudnienia', gen='2026-10-14T15:00:00+0200', synthetic='true')
    for i in range(5):
        row = SubElement(root, 'utr')
        data = {'typ': 'W' if i == 2 else 'I' if i == 4 else 'U', 'nr_drogi': 'A1', 'woj': 'pomorskie',
                'nazwa_odcinka': f'WICI fikcyjny odcinek {i}', 'geo_lat': '' if i == 3 else '53.1', 'geo_long': '18.1',
                'data_powstania': '2026-10-01T08:00:00+0200', 'data_likwidacji': f'2026-10-{15+i}T18:00:00+0200',
                'objazd': 'Syntetyczny opis do testu, nie rzeczywiste utrudnienie.', 'skutki': 'S07' if i == 2 else ''}
        if i == 1: data.update(ruch_2_kierunkowy='true', ogr_predkosc='80')
        for key, value in data.items(): SubElement(row, key).text = value
        SubElement(SubElement(row, 'rodzaj'), 'poz').text = 'R07' if i == 2 else 'I04' if i == 4 else 'U33'
    indent(root)
    (DEST / 'gddkia_synthetic.xml').write_bytes(tostring(root, encoding='utf-8', xml_declaration=True))
    now = datetime(2026, 10, 17, 8, tzinfo=UTC).timestamp()
    save('aircraft/synthetic.json', {**NOTICE, 'now': now * 1000, 'ac': [{'hex': 'abcdef', 'lat': 52.1, 'lon': 19.2,
          'type': 'adsb_icao', 'seen': 0, 'seen_pos': 0, 'nac_p': 9, 'nic': 8, 'sil': 3, 'sil_type': 'perhour', 'rc': 100}]})
    features = []
    for i in range(3):
        layers = list(LAYERS)
        if i == 1: layers.remove('exclusion_mask')
        features.append({'type': 'Feature', 'id': f'WICI_SYNTHETIC_{i}', 'collection': 'GFM',
            'properties': {'datetime': f'2026-10-{16-i}T08:00:00Z', 'processing:datetime': f'2026-10-{16-i}T10:00:00Z',
                           'processing:version': 'GFM v3.1.0' if i == 0 else 'v4.1.1'},
            'assets': {key: {'href': f'https://data.eodc.eu/collections/GFM_LAYERS/WICI_SYNTHETIC_{i}_{key}.tif'} for key in layers}})
    save('gfm/stac.json', {**NOTICE, 'type': 'FeatureCollection', 'features': features, 'links': []})
    # The first ID is the UI's historical preset identifier; all associated pixels and metadata are fictional.
    products = [{**NOTICE, 'id': identity, 'observed_at': '2024-09-15T08:00:00Z', 'processed_at': '2024-09-15T10:00:00Z',
         'fetched_at': '2026-10-17T08:00:00Z', 'catalog_created_at': '2024-09-16T08:00:00Z',
         'version': 'GFM v3.1.0 - synthetic test', 'source_url': 'https://example.invalid/wici-gfm',
         'attribution': 'WICI synthetic test image (MIT), not Copernicus data', 'renderable': True, 'missing_assets': []}
        for identity in ['ENSEMBLE_FLOOD_20240915T050149_VV_EU020M_E051N018T3', 'WICI_SYNTHETIC_OTHER']]
    save('gfm/browser.json', {**NOTICE, 'bounds': [[50.35, 16.55], [50.55, 16.75]], 'status': 'flood',
         'counts': {'flood': 128, 'assessed_clear': 128, 'reference_water': 0, 'excluded': 0, 'no_observation': 0},
         'quality': {}, 'product': products[0], 'rendered_at': '2026-10-17T08:00:00Z',
         'verification': {'search': {'enabled': True, 'items': products}}})
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = b''.join(b'\0' + b''.join(bytes((60, 100, 220, 180) if (x + y) % 2 else (0, 0, 0, 0)) for x in range(16)) for y in range(16))
    (DEST / 'gfm/synthetic.png').write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 16, 16, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
    for folder in ['gios', 'imgw_hydro', 'aircraft', 'gfm']:
        (DEST / folder / 'README.md').write_text('# Original synthetic WICI fixtures\n\nMIT. Created from scratch by '
            '`scripts/prepare_synthetic_fixtures.py` using the application contract. No captured response, source document, '
            'measurement, vehicle history or satellite image is retained. Field names, enumerations and API hostnames are '
            'contract identifiers; all observations and entities are invented. The GFM browser preset ID matches an application '
            'constant, but its response and checkerboard image are synthetic. These tests do not verify live service availability.\n')


if __name__ == '__main__':
    main()
