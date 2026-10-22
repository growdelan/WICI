"""Transactional projections sharing Repository's connection and reentrant lock."""
import json
import unicodedata
from datetime import UTC, datetime, time, timedelta

from wici.communications import SOURCES, communication
from wici.daily import WARSAW
from wici.geo import provinces_for_point, units

PROJECTION_VERSION = 1


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def search_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold().replace('ł', 'l'))
                   if not unicodedata.combining(c))


def iso(value):
    return value.astimezone(UTC).isoformat()


class WorkspaceRepository:
    """Writes do not commit: callers can include projection updates in their transaction."""

    def __init__(self, repo):
        self.repo, self.db = repo, repo.db

    def upsert(self, value, areas):
        value = dict(value, projection_version=PROJECTION_VERSION)
        previous = self.db.execute('SELECT * FROM catalog_objects WHERE ref=?', (value['ref'],)).fetchone()
        old_areas = [dict(r) for r in self.db.execute(
            'SELECT admin_code,role,basis FROM catalog_object_areas WHERE ref=? ORDER BY admin_code,role',
            (value['ref'],))]
        areas = sorted(areas, key=lambda a: (a['admin_code'], a['role']))
        changed = not previous or any(previous[k] != v for k, v in value.items()) or old_areas != areas
        if not changed:
            return False
        value['revision'] = previous['revision']+1 if previous else 1
        columns = ','.join(value)
        updates = ','.join(f'{k}=excluded.{k}' for k in value if k != 'ref')
        self.db.execute(f'INSERT INTO catalog_objects({columns}) VALUES({",".join("?" for _ in value)}) '
                        f'ON CONFLICT(ref) DO UPDATE SET {updates}', tuple(value.values()))
        self.db.execute('DELETE FROM catalog_object_areas WHERE ref=?', (value['ref'],))
        self.db.executemany('INSERT INTO catalog_object_areas(ref,admin_code,role,basis) VALUES(?,?,?,?)',
                            [(value['ref'], a['admin_code'], a['role'], a['basis']) for a in areas])
        return True

    def project_document(self, document_id):
        row = self.db.execute('''SELECT d.id,d.source_id,d.url,d.first_seen_at,d.last_checked_at,
            dv.id document_version_id,dv.version_number,dv.title,dv.text,dv.fields_json,
            dv.source_published_at,dv.source_updated_at,dv.redaction_note,s.name source_name
            FROM documents d JOIN document_versions dv ON dv.document_id=d.id AND dv.version_number=d.current_version
            JOIN sources s ON s.id=d.source_id WHERE d.id=?''', (document_id,)).fetchone()
        ref = f'communication:{document_id}'
        if not row:
            return False
        fields = json.loads(row['fields_json'])
        if row['source_id'] not in SOURCES or fields.get('contract_validated') is not True or fields.get('access_allowed') is not True:
            return bool(self.db.execute('DELETE FROM catalog_objects WHERE ref=?', (ref,)).rowcount)
        item = communication({k: v for k, v in dict(row).items() if k != 'fields_json'}, fields, self.repo.clock())
        published = item['source_published_at']
        precision = 'instant'
        published_until = None
        if not published and fields.get('source_published_date'):
            try:
                day = datetime.fromisoformat(fields['source_published_date']).date()
                published = iso(datetime.combine(day, time(), WARSAW))
                published_until = iso(datetime.combine(day+timedelta(days=1), time(), WARSAW))
                precision = 'day'
            except (TypeError, ValueError):
                pass
        if not published:
            published = item.get('source_updated_at') or item['first_seen_at']
            precision = 'first_seen' if not item.get('source_updated_at') else 'instant'
        metadata = {key: item.get(key) for key in ('source_name', 'category', 'communication_type',
                    'official_severity', 'map_note', 'original_url', 'version_number', 'redacted',
                    'publication_day', 'publication_day_basis', 'source_published_date')}
        # Warning state depends on the query clock and is calculated at read time.
        metadata['source_warning_status'] = fields.get('event', {}).get('warning_status', 'unknown')
        metadata['published_until'] = published_until
        window = item.get('display_window') or {}
        return self.upsert({'ref': ref, 'type': 'communication', 'source_id': item['source_id'], 'native_id': str(document_id),
            'label': item['title'], 'search_text': search_text(' '.join([item['title'], item['text'], str(document_id)])),
            'latitude': None, 'longitude': None, 'published_at': published, 'updated_at': item.get('source_updated_at'),
            'valid_from': item.get('valid_from'), 'valid_until': item.get('valid_until'),
            'display_from': window.get('valid_from'), 'display_until': window.get('valid_until'), 'date_precision': precision,
            'document_id': document_id, 'document_version_id': item['document_version_id'], 'metadata_json': encode(metadata)},
            [{'admin_code': loc['admin_code'], 'role': loc['role'], 'basis': loc.get('source', item['source_id'])}
             for loc in item['locations']])

    def upsert_station(self, ref, source_id, native_id, label, latitude=None, longitude=None, metadata=None, areas=None):
        metadata = metadata or {}
        if areas is None:
            province = metadata.get('province')
            codes = []
            if province in units() and len(province) == 2:
                codes = [province]
            elif isinstance(province, str):
                codes = [code for code, name in units().items() if len(code) == 2 and search_text(name) == search_text(province)]
            basis = 'Kod lub nazwa województwa ze źródła'
            if not codes:
                codes = provinces_for_point(longitude, latitude)
                basis = 'Położenie punktu w lokalnych granicach PRG'
            areas = [{'admin_code': code, 'role': 'station_location', 'basis': basis} for code in codes]
        return self.upsert({'ref': ref, 'type': 'hydro_station' if source_id == 'imgw' else 'air_quality_station',
            'source_id': source_id, 'native_id': str(native_id), 'label': label,
            'search_text': search_text(' '.join([label, str(native_id), str(metadata.get('code', '')),
                                             str(metadata.get('river', '')), str(metadata.get('address', ''))])),
            'latitude': latitude, 'longitude': longitude, 'metadata_json': encode(metadata)}, areas)

    def backfill(self):
        with self.repo.lock, self.db:
            self.db.execute("INSERT INTO workspace_meta VALUES('status','preparing') ON CONFLICT(key) DO UPDATE SET value='preparing'")
            for code, name in units().items():
                self.upsert({'ref': f'area:prg:{code}', 'type': 'area', 'source_id': 'prg', 'native_id': code, 'label': name,
                                 'search_text': search_text(f'{name} {code}'), 'date_precision': 'timeless',
                                 'metadata_json': encode({'admin_code': code, 'level': 'province' if len(code) == 2 else 'county',
                                                       'source_name': 'GUGiK PRG', 'geometry_ref': code})},
                            [{'admin_code': code, 'role': 'administrative_boundary', 'basis': 'Lokalny zbiór PRG'}])
            # A repeated startup is idempotent and repairs projections written by an older version.
            for row in self.db.execute('SELECT id FROM documents').fetchall():
                self.project_document(row['id'])
            self.db.execute("INSERT INTO workspace_meta VALUES('projection_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(PROJECTION_VERSION),))
            self.db.execute("UPDATE workspace_meta SET value='ready' WHERE key='status'")

    def object(self, ref):
        row = self.db.execute('SELECT * FROM catalog_objects WHERE ref=?', (ref,)).fetchone()
        return self.decode(row) if row else None

    def decode(self, row):
        item = dict(row)
        item['metadata'] = json.loads(item.pop('metadata_json'))
        item.pop('search_text', None)
        item['areas'] = [dict(r) for r in self.db.execute(
            'SELECT admin_code,role,basis FROM catalog_object_areas WHERE ref=? ORDER BY admin_code,role', (item['ref'],))]
        return item
