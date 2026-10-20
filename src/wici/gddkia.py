"""On-demand official GDDKiA XML snapshot, separate from traffic flow and archives."""
import asyncio
import hashlib
import math
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import httpx

from wici.sources.base import Adapter, SourceError
from wici.sources.normalize import plain

ENDPOINT = 'https://www.archiwum.gddkia.gov.pl/dane/zima_html/utrdane.xml'
REFRESH_SECONDS = 300
TYPES = {'U':'Roboty drogowe', 'W':'Wypadek', 'I':'Inne zdarzenie', 'K':'Katastrofa'}
# Official XML specification v1.1, October 2014, tables 4 and 5.
CAUSES = {
    'I02':'Blokada drogi', 'I04':'Inne', 'I05':'Rajd', 'I06':'Pielgrzymka',
    'I07':'Zawody sportowe', 'I08':'Demonstracja', 'I09':'Uroczystość',
    'I10':'Przejazd ważnej osobistości', 'I11':'Przejazd pojazdu nienormatywnego',
    'I12':'Zwiększone natężenie ruchu', 'I13':'Protest',
    'K00':'Katastrofa budowlana', 'K01':'Katastrofa ekologiczna', 'K02':'Pożar',
    'K03':'Inne', 'K04':'Powódź', 'S00':'Brak informacji',
    'U27':'Remont mostu', 'U33':'Roboty drogowe', 'U42':'Inne',
    'R00':'Zderzenie czołowe', 'R01':'Zderzenie boczne', 'R02':'Zderzenie tylne',
    'R03':'Najechanie pojazdu na pieszego', 'R04':'Najechanie na pojazd unieruchomiony',
    'R05':'Najechanie na drzewo lub słup', 'R06':'Najechanie na zaporę kolejową',
    'R07':'Najechanie na urządzenie drogowe', 'R08':'Najechanie na zwierzę',
    'R09':'Wywrócenie się pojazdu', 'R10':'Inne', 'R11':'Zderzenie się pojazdów w ruchu',
    'R12':'Wypadnięcie pojazdu z jezdni', 'R13':'Wjechanie pojazdu do rowu', 'R14':'Awaria pojazdu',
}
EFFECTS = {
    'J00':'Brak informacji', 'J01':'Wytyczony objazd', 'J02':'Przerwa w ruchu',
    'J03':'Kierowanie ruchem przez policję', 'J04':'Inne', 'J05':'Zator drogowy',
    'S00':'Brak informacji', 'S01':'Wytyczony objazd', 'S02':'Przerwa w ruchu',
    'S03':'Kierowanie ruchem przez policję', 'S04':'Inne', 'S05':'Droga zablokowana',
    'S06':'Ruch wahadłowy', 'S07':'Zablokowany pas ruchu',
    'S08':'Zablokowana część pasa ruchu', 'S09':'Zablokowane pobocze',
}
FLAGS = {'ruch_wahadlowy':'Ruch wahadłowy', 'sygnalizacja_swietlna':'Sygnalizacja świetlna',
         'awaria_mostu':'Uszkodzony obiekt mostowy', 'ruch_2_kierunkowy':'Ruch dwukierunkowy',
         'droga_zamknieta':'Droga zamknięta'}
RESTRICTIONS = {'ogr_predkosc':('Ograniczenie prędkości','km/h'),
                'ogr_nosnosc':('Ograniczenie nośności','t'), 'ogr_nacisk':('Ograniczenie nacisku','t'),
                'ogr_skrajnia_pozioma':('Skrajnia pozioma','m'),
                'ogr_skrajnia_pionowa':('Skrajnia pionowa','m'), 'ogr_szerokosc':('Szerokość','m')}


def source_time(value):
    if not value or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.year == 9999:
        raise ValueError('Nieprawidłowy czas źródła GDDKiA')
    return parsed.astimezone(UTC)


def text(node, tag):
    value = node.findtext(tag) or ''
    if len(value) > 20_000:
        raise ValueError('Zbyt długi tekst źródła')
    return plain(value)


def parse_feed(body):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('Nieprawidłowy dokument XML')
    root = ET.fromstring(body)
    if root.tag != 'utrudnienia' or any(n.tag != 'utr' for n in root):
        raise ValueError('Nieznany format GDDKiA')
    rows = list(root)
    if len(rows) > 5000:
        raise ValueError('Zbyt wiele rekordów GDDKiA')
    generated = source_time(root.get('gen'))
    items, invalid, unmapped = [], 0, 0
    for node in rows:
        try:
            road = text(node,'nr_drogi')
            if not road:
                raise ValueError('Brak numeru drogi')
            dates = {}
            record_invalid = False
            for key, tag in [('start_at','data_powstania'), ('planned_end_at','data_likwidacji')]:
                try:
                    dates[key] = source_time(node.findtext(tag))
                except ValueError:
                    dates[key], record_invalid = None, True
            if dates['start_at'] and dates['planned_end_at'] and dates['planned_end_at'] < dates['start_at']:
                dates['planned_end_at'], record_invalid = None, True
            try:
                lat, lon = float(node.findtext('geo_lat')), float(node.findtext('geo_long'))
            except (ValueError, TypeError):
                unmapped += 1
                invalid += int(record_invalid)
                continue
            if not (math.isfinite(lat) and math.isfinite(lon) and 49 <= lat <= 55 and 14 <= lon <= 24.2):
                unmapped += 1
                invalid += int(record_invalid)
                continue
            kind = TYPES.get(text(node,'typ'), 'Utrudnienie')
            codes = [plain(p.text) for p in node.findall('rodzaj/poz') if p.text]
            causes = [CAUSES.get(code, f'{kind} (kod {code})') for code in codes]
            cause = '; '.join(causes) if causes else kind
            if cause in ('Inne','Brak informacji'):
                cause = f'{kind}: {cause}'
            effect = text(node,'skutki')
            effects = [EFFECTS.get(effect,effect)] if effect else []
            effects += [label for tag, label in FLAGS.items() if text(node,tag).lower() == 'true']
            for tag, (label, unit) in RESTRICTIONS.items():
                value = text(node,tag)
                if value:
                    try:
                        number = float(value)
                        if math.isfinite(number) and number > 0:
                            effects.append(f'{label}: {value} {unit}')
                        elif not math.isfinite(number) or number < 0:
                            record_invalid = True
                    except ValueError:
                        record_invalid = True
            item = {'id':hashlib.sha256(ET.tostring(node)).hexdigest()[:24], 'road':road,
                    'section':text(node,'nazwa_odcinka'), 'province':text(node,'woj'),
                    'latitude':lat, 'longitude':lon, 'cause':cause,
                    'effects':list(dict.fromkeys(effects)), 'description':text(node,'objazd'),
                    'source_url':ENDPOINT,
                    **{k:v.isoformat() if v else None for k,v in dates.items()}}
            items.append(item)
            invalid += int(record_invalid)
        except (ValueError, TypeError):
            invalid += 1
    if rows and not items and not unmapped:
        raise ValueError('Nie udało się odczytać żadnego rekordu GDDKiA')
    return {'items':items, 'total':len(rows), 'invalid_count':invalid, 'unmapped_count':unmapped,
            'source_generated_at':generated.isoformat() if generated else None}


class FeedAdapter(Adapter):
    host = 'www.archiwum.gddkia.gov.pl'
    endpoint = ENDPOINT
    path_prefix = '/dane/zima_html'


class GddkiaService:
    def __init__(self, client, clock, timeout=20, enabled=True, demo=False):
        self.client, self.clock, self.enabled, self.demo = client, clock, enabled, demo
        self.adapter = FeedAdapter()
        self.adapter.clock, self.adapter.timeout_seconds = clock, timeout
        self.adapter.max_response_bytes = 2*1024*1024
        self.lock = asyncio.Lock()
        self.snapshot = None
        self.last_attempt_at = self.last_success_at = self.next_due = None
        self.error = ''

    def result(self):
        now = self.clock()
        data = self.snapshot or {'items':[], 'total':0, 'invalid_count':0, 'unmapped_count':0,
                                 'source_generated_at':None}
        generated = source_time(data['source_generated_at'])
        stale = bool(self.error or not generated or now-generated > timedelta(minutes=30))
        status = 'error' if self.error else 'partial' if data['invalid_count'] else 'success'
        items = []
        for item in data['items']:
            end, start = source_time(item['planned_end_at']), source_time(item['start_at'])
            items.append({**item, 'planned_end_passed':bool(end and end < now),
                          'upcoming':bool(start and start > now)})
        return {**data, 'items':items, 'enabled':True, 'status':status, 'message':self.error,
                'stale':stale, 'last_attempt_at':self.last_attempt_at,
                'last_success_at':self.last_success_at, 'refresh_seconds':REFRESH_SECONDS,
                'source_url':ENDPOINT}

    async def fetch(self):
        if self.demo or not self.enabled:
            return {'enabled':False, 'status':'disabled', 'message':'GDDKiA wyłączone w tym trybie.',
                    'items':[], 'total':0, 'unmapped_count':0, 'invalid_count':0, 'stale':True,
                    'source_generated_at':None, 'last_success_at':None, 'last_attempt_at':None,
                    'refresh_seconds':REFRESH_SECONDS, 'source_url':ENDPOINT}
        async with self.lock:
            now = self.clock()
            if self.next_due and now < self.next_due:
                return self.result()
            self.last_attempt_at = now.isoformat()
            self.next_due = now+timedelta(seconds=REFRESH_SECONDS)
            try:
                await self.adapter.check_robots(self.client)
                parsed = parse_feed(await self.adapter.request_bytes(self.client, ENDPOINT))
                generated = source_time(parsed['source_generated_at'])
                if generated and generated > now+timedelta(minutes=5):
                    raise ValueError('Data zestawienia w przyszłości')
                if self.snapshot and generated:
                    previous = source_time(self.snapshot['source_generated_at'])
                    if previous and generated < previous:
                        raise ValueError('Starszy zestaw danych GDDKiA')
                self.snapshot = parsed
                self.last_success_at, self.error = self.clock().isoformat(), ''
            except SourceError as exc:
                delay = max(REFRESH_SECONDS, min(exc.retry_after or REFRESH_SECONDS, 31*86400))
                self.next_due = now+timedelta(seconds=delay)
                self.error = 'Odczyt GDDKiA niedostępny; poniżej ostatnie poprawnie pobrane dane, jeśli istnieją.'
            except (httpx.HTTPError, ValueError, TypeError, ET.ParseError):
                self.error = 'Odczyt GDDKiA niedostępny; poniżej ostatnie poprawnie pobrane dane, jeśli istnieją.'
            return self.result()
