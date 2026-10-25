"""Revisioned own areas and precise spatial membership; no provider requests."""
import json
import math
import uuid
from datetime import timedelta
from itertools import pairwise

from wici.area_models import AreaInput, on_segment
from wici.workspace_repository import encode, iso, search_text

EARTH_RADIUS = 6371008.8


def contains(area, longitude, latitude):
    """Boundary-inclusive WGS84 point membership; never just a bounding box."""
    if (longitude is None or latitude is None or not isinstance(longitude, (int, float))
            or not isinstance(latitude, (int, float)) or not math.isfinite(longitude) or not math.isfinite(latitude)):
        return False
    if area['shape'] == 'circle':
        lon, lat = area['center']
        p1, p2 = math.radians(lat), math.radians(latitude)
        h = math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(longitude-lon)/2)**2
        return 2*EARTH_RADIUS*math.asin(math.sqrt(min(1, max(0, h)))) <= area['radius_m']+1e-6
    ring = area['geometry']['coordinates'][0]
    inside = False
    p = (longitude, latitude)
    for a, b in pairwise(ring):
        if on_segment(a, b, p):
            return True
        if (a[1] > latitude) != (b[1] > latitude):
            x = a[0]+(latitude-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if longitude < x:
                inside = not inside
    return inside


def display_geometry(area):
    if area['shape'] != 'circle':
        return area['geometry']
    lon, lat = map(math.radians, area['center'])
    angle = area['radius_m']/EARTH_RADIUS
    ring = []
    for index in range(96):
        bearing = index*2*math.pi/96
        y = math.asin(math.sin(lat)*math.cos(angle)+math.cos(lat)*math.sin(angle)*math.cos(bearing))
        x = lon+math.atan2(math.sin(bearing)*math.sin(angle)*math.cos(lat), math.cos(angle)-math.sin(lat)*math.sin(y))
        ring.append([math.degrees(x), math.degrees(y)])
    return {'type': 'Polygon', 'coordinates': [ring+[ring[0]]]}


class WorkspaceAreas:
    def __init__(self, workspace):
        self.workspace, self.repo, self.db = workspace, workspace.repo, workspace.db

    @staticmethod
    def _decode(row):
        result = dict(row)
        value = json.loads(result.pop('definition_json'))
        result.update(value)
        result['archived'] = bool(result['archived'])
        result['ref'] = 'custom_area:'+result['id']
        result['geometry'] = display_geometry(result)
        return result

    def detail(self, area_id, revision=None):
        area_id = area_id.removeprefix('custom_area:')
        with self.repo.lock:
            if revision is None:
                row = self.db.execute('SELECT * FROM workspace_areas WHERE id=?', (area_id,)).fetchone()
            else:
                row = self.db.execute('SELECT * FROM workspace_area_revisions WHERE id=? AND revision=?', (area_id, revision)).fetchone()
            if row is None:
                raise KeyError(area_id)
            return self._decode(row)

    def list(self, include_archived=False):
        with self.repo.lock:
            return {'items': [self._decode(row) for row in self.db.execute(
                'SELECT * FROM workspace_areas WHERE (? OR archived=0) ORDER BY name,id', (include_archived,))]}

    def history(self, area_id):
        with self.repo.lock:
            self.detail(area_id)
            return {'items': [self._decode(row) for row in self.db.execute(
                'SELECT * FROM workspace_area_revisions WHERE id=? ORDER BY revision DESC', (area_id.removeprefix('custom_area:'),))]}

    def save(self, raw, area_id=None):
        value = AreaInput.model_validate(raw)
        area_id = area_id.removeprefix('custom_area:') if area_id else None
        with self.repo.lock, self.db:
            previous = self.detail(area_id) if area_id else None
            if previous and value.revision != previous['revision']:
                from wici.workspace_service import QueryChanged
                raise QueryChanged('Obszar zmienił się w innym oknie; odśwież przed zapisem')
            if not previous and self.db.execute('SELECT count(*) FROM workspace_areas').fetchone()[0] >= 100:
                raise ValueError('Limit 100 własnych obszarów został osiągnięty')
            if not previous and value.revision is not None:
                raise ValueError('Nowy obszar nie ma poprzedniej rewizji')
            identity = area_id or str(uuid.uuid4())
            revision = previous['revision']+1 if previous else 1
            now = iso(self.repo.clock())
            definition = value.model_dump(mode='json', exclude={'revision', 'archived', 'name', 'description', 'color'}, exclude_none=True)
            args = (identity, value.name, value.description, value.color, revision, int(value.archived),
                    encode(definition), previous['created_at'] if previous else now, now)
            self.db.execute('''INSERT INTO workspace_areas VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,color=excluded.color,
                revision=excluded.revision,archived=excluded.archived,definition_json=excluded.definition_json,updated_at=excluded.updated_at''', args)
            self.db.execute('INSERT INTO workspace_area_revisions VALUES(?,?,?,?,?,?,?,?,?)', args)
            result = self.detail(identity)
            if previous:
                # Pending observations belong to the pre-edit geometry epoch.
                # Reset atomically with the geometry; never evaluate old points
                # against a new boundary or mutate earlier event evidence.
                rule_ids = [row['id'] for row in self.db.execute('''SELECT id FROM workspace_rules
                    WHERE template='transport' AND json_extract(config_json,'$.area_id') IN (?,?)''',
                    (identity, result['ref']))]
                checkpoint = self.db.execute('SELECT COALESCE(max(id),0) FROM workspace_observations').fetchone()[0]
                for rule_id in rule_ids:
                    self.db.execute('''UPDATE workspace_rules SET checkpoint_id=?,condition_state='unknown',
                        last_evaluated_at=NULL,last_successful_at=NULL,error=NULL WHERE id=?''', (checkpoint, rule_id))
                    self.db.execute('DELETE FROM workspace_rule_states WHERE rule_id=?', (rule_id,))
            self.workspace.catalog.upsert({'ref': result['ref'], 'type': 'custom_area', 'source_id': 'custom',
                'native_id': identity, 'label': value.name, 'search_text': search_text(value.name+' '+value.description),
                'date_precision': 'timeless', 'updated_at': now,
                'metadata_json': encode(dict(result, source_name='Własny obszar analityczny'))}, [])
            return result

    def duplicate(self, area_id):
        value = self.detail(area_id)
        raw = {key: value[key] for key in ('name', 'description', 'color', 'shape')}
        raw['name'] = (value['name'][:110]+' — kopia')
        if value['shape'] == 'circle':
            raw.update(center=value['center'], radius_m=value['radius_m'])
        else:
            raw['geometry'] = value['geometry']
        return self.save(raw)

    def contains(self, area_id, longitude, latitude, revision=None):
        area = self.detail(area_id, revision) if isinstance(area_id, str) else area_id
        return contains(area, longitude, latitude)

    def members(self, area_id, limit=100):
        limit = max(1, min(200, limit))
        with self.repo.lock:
            area = self.detail(area_id)
            now = self.repo.clock()
            interval = (now-timedelta(days=14), now+timedelta(microseconds=1))
            items, total = [], 0
            for row in self.db.execute("SELECT * FROM catalog_objects WHERE type IN ('hydro_station','air_quality_station','aircraft','ship')"):
                item = self.workspace._present(self.workspace.catalog.decode(row), now, interval)
                if contains(area, item.get('longitude'), item.get('latitude')):
                    total += 1
                    if len(items) < limit:
                        items.append(item)
            return {'area': area, 'items': items, 'total': total, 'limited': total > limit,
                    'basis': 'Rzeczywiste współrzędne dostępnych aktualnych pozycji; punkty na granicy należą do obszaru'}
