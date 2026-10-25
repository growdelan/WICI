"""A coherent local query across object table, map, timeline and detail cards."""
import base64
import hashlib
import hmac
import json
import math
import secrets
import uuid
from collections import OrderedDict
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache

from wici.daily import WARSAW
from wici.geo import provinces_for_point
from wici.ukraine_history import UkraineHistory
from wici.workspace_models import SavedView, WorkspaceQuery
from wici.workspace_moving import MOVING_TYPES, MovingObjects
from wici.workspace_repository import WorkspaceRepository, encode, iso, search_text


class QueryChanged(ValueError):
    pass


def parse_time(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError('Czas wymaga strefy czasowej')
    return result.astimezone(UTC)


def publication_bound(value, offset=0):
    if not value:
        return None
    try:
        day = datetime.fromisoformat(value).date()+timedelta(days=offset)
        return iso(datetime.combine(day, time(), WARSAW))
    except (TypeError, ValueError):
        return None


class WorkspaceService:
    def __init__(self, repo):
        self.repo, self.db = repo, repo.db
        self.catalog = WorkspaceRepository(repo)
        self.moving = MovingObjects(repo)
        self.ukraine = UkraineHistory(repo)
        self.db.create_function('workspace_in_province', 3,
            lru_cache(maxsize=4096)(lambda lon, lat, code: int(code in provinces_for_point(lon, lat))), deterministic=True)
        self.db.create_function('workspace_in_poland', 2,
            lru_cache(maxsize=4096)(lambda lon, lat: int(bool(provinces_for_point(lon, lat)))), deterministic=True)
        self.db.create_function('workspace_day_start', 1, publication_bound, deterministic=True)
        self.db.create_function('workspace_day_end', 1, lambda value: publication_bound(value, 1), deterministic=True)
        self.secret = secrets.token_bytes(32)
        self.contexts = OrderedDict()
        self.histograms = OrderedDict()
        self.revisions = OrderedDict()
        self.source_enabled = {}
        from wici.workspace_areas import WorkspaceAreas
        self.areas = WorkspaceAreas(self)
        self.catalog.backfill()
        self.moving.backfill_tracks()
        from wici.workspace_dossiers import WorkspaceDossiers
        self.dossiers = WorkspaceDossiers(self)
        from wici.workspace_relations import WorkspaceRelations
        self.relations = WorkspaceRelations(self)
        from wici.workspace_events import WorkspaceEvents
        from wici.workspace_monitor import WorkspaceMonitor
        from wici.workspace_rules import WorkspaceRules
        self.events = WorkspaceEvents(self)
        self.rules = WorkspaceRules(self)
        self.monitor = WorkspaceMonitor(self)

    def _encode_cursor(self, value):
        payload = base64.urlsafe_b64encode(encode(value).encode()).decode().rstrip('=')
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return payload+'.'+signature

    def _decode_cursor(self, value):
        try:
            payload, signature = value.split('.')
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            return json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload) % 4)))
        except (ValueError, KeyError, TypeError):
            raise QueryChanged('Kursor wygasł; odśwież cały wynik') from None

    @staticmethod
    def _includes_ukraine(query):
        return (query.country != 'PL' and not query.province
                and any(t in ('ua_region', 'civil_alert') for t in query.types)
                and (not query.source_ids or 'ukraine_alerts' in query.source_ids))

    def _base(self, query, now=None, interval=None):
        where, params = ["(o.type!='custom_area' OR json_extract(o.metadata_json,'$.archived')=0)"], []
        if not query.types:
            where.append('0=1')
        else:
            where.append(f'o.type IN ({",".join("?" for _ in query.types)})')
            params.extend(query.types)
        if query.source_ids:
            where.append(f'o.source_id IN ({",".join("?" for _ in query.source_ids)})')
            params.extend(query.source_ids)
        if query.q.strip():
            where.append("o.search_text LIKE ? ESCAPE '\\'")
            value = search_text(query.q.strip()).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params.append('%'+value+'%')
        if query.country == 'UA':
            where.append("o.type IN ('ua_region','civil_alert')")
        elif query.country == 'PL':
            if query.time.mode == 'range':
                where.append("""(o.type NOT IN ('ua_region','civil_alert','aircraft','ship') OR
                    (o.type IN ('aircraft','ship') AND COALESCE((SELECT workspace_in_poland(p.longitude,p.latitude)
                    FROM object_track_points p JOIN object_tracks t ON t.id=p.track_id WHERE t.kind=o.type
                    AND t.object_id=o.native_id AND p.position_at>=? AND p.position_at<?
                    ORDER BY p.position_at DESC,p.track_id LIMIT 1),0)=1))""")
                params.extend([iso(interval[0]), iso(interval[1])])
            else:
                where.append("(o.type NOT IN ('ua_region','civil_alert','aircraft','ship') OR EXISTS (SELECT 1 FROM catalog_object_areas a WHERE a.ref=o.ref))")
        if query.region_ref:
            where.append("""EXISTS (SELECT 1 FROM workspace_ukraine_regions r
                WHERE r.ref=CASE WHEN o.type='ua_region' THEN o.ref ELSE json_extract(o.metadata_json,'$.region_ref') END
                AND (r.ref=? OR r.parent_ref=?))""")
            params.extend([query.region_ref, query.region_ref])
        if query.province:
            if query.time.mode == 'range':
                start, end = map(iso, interval)
                where.append("""((o.type NOT IN ('aircraft','ship') AND EXISTS
                    (SELECT 1 FROM catalog_object_areas a WHERE a.ref=o.ref AND a.admin_code LIKE ?))
                    OR (o.type IN ('aircraft','ship') AND COALESCE((SELECT workspace_in_province(p.longitude,p.latitude,?)
                    FROM object_track_points p JOIN object_tracks t ON t.id=p.track_id WHERE t.kind=o.type
                    AND t.object_id=o.native_id AND p.position_at>=? AND p.position_at<?
                    ORDER BY p.position_at DESC,p.track_id LIMIT 1),0)=1))""")
                params.extend([query.province+'%', query.province, start, end])
            else:
                where.append('EXISTS (SELECT 1 FROM catalog_object_areas a WHERE a.ref=o.ref AND a.admin_code LIKE ?)')
                params.append(query.province+'%')
        if not query.include_unlocated:
            located, location_params = self._located(query, interval, now)
            where.append('('+located+')')
            params.extend(location_params)
        if query.watched_only:
            where.append('EXISTS (SELECT 1 FROM workspace_watchlist w WHERE w.ref=o.ref)')
        return ' AND '.join(where), params

    def _located(self, query, interval, now):
        static = """((o.type NOT IN ('aircraft','ship','ua_region','civil_alert') AND
            (o.type='custom_area' OR o.latitude IS NOT NULL AND o.longitude IS NOT NULL OR EXISTS (SELECT 1 FROM catalog_object_areas a WHERE a.ref=o.ref)))
            OR (o.type IN ('ua_region','civil_alert') AND EXISTS (SELECT 1 FROM workspace_ukraine_regions r
                WHERE r.ref=CASE WHEN o.type='ua_region' THEN o.ref ELSE json_extract(o.metadata_json,'$.region_ref') END
                AND r.geometry_json IS NOT NULL)))"""
        if query.time.mode == 'range':
            return static+""" OR (o.type IN ('aircraft','ship') AND EXISTS (SELECT 1 FROM object_tracks t
                JOIN object_track_points p ON p.track_id=t.id WHERE t.kind=o.type AND t.object_id=o.native_id
                AND p.position_at>=? AND p.position_at<?))""", [iso(interval[0]), iso(interval[1])]
        return static+""" OR (o.type IN ('aircraft','ship') AND o.latitude IS NOT NULL AND o.longitude IS NOT NULL
            AND json_extract(o.metadata_json,'$.live_present')=1 AND EXISTS
            (SELECT 1 FROM workspace_moving_sources s WHERE s.resource=o.source_id AND s.status='ready' AND s.stale=0)
            AND (julianday(?)-julianday(o.updated_at))*86400 BETWEEN -0.001
            AND CASE WHEN o.type='aircraft' THEN 120.001 ELSE 900.001 END)""", [iso(now)]

    def _revision(self, where, params, query=None, overview=None, now=None):
        # All writers share this SQLite connection and Repository lock. A mutation
        # invalidates this bounded cache, including retention and backdated corrections.
        cache_key = (self.db.total_changes, where, encode(params),
                     encode(query.model_dump(mode='json', exclude={'cursor', 'query_revision'})) if query else '')
        if cache_key in self.revisions:
            self.revisions.move_to_end(cache_key)
            return self.revisions[cache_key]
        digest = hashlib.sha256()
        revision_where, revision_params = where, list(params)
        ranged = query is not None and query.time.mode == 'range'
        if ranged:
            time_where, time_params = self._time_filter(query, overview, now)
            revision_where, revision_params = f'({where}) AND {time_where}', list(params)+time_params
        columns = 'ref,revision,type,source_id,native_id,label,latitude,longitude,metadata_json,projection_version,updated_at' if ranged else 'ref,revision'
        rows = self.db.execute(f'SELECT {columns} FROM catalog_objects o WHERE {revision_where} ORDER BY ref', revision_params)
        for row in rows:
            if ranged and row['type'].endswith('_station'):
                # Current station metadata remains part of the view, while observations
                # outside its overview cannot invalidate a frozen historical query.
                stable = {key: row[key] for key in ('ref', 'type', 'source_id', 'native_id', 'label',
                          'latitude', 'longitude', 'metadata_json', 'projection_version')}
                digest.update(encode(stable).encode())
                if query.sort.field == 'updated_at':
                    digest.update(str(row['updated_at']).encode())
            elif ranged and row['type'] in MOVING_TYPES:
                metadata = json.loads(row['metadata_json'])
                for key in ('last_known_position', 'live_present'):
                    metadata.pop(key, None)
                digest.update(encode({key: row[key] for key in ('ref', 'type', 'source_id', 'native_id', 'label')}).encode())
                digest.update(encode(metadata).encode())
                if query.sort.field == 'updated_at':
                    digest.update(str(row['updated_at']).encode())
            elif ranged and row['type'] in ('ua_region', 'civil_alert'):
                # Current source status is separate from recorded history. Geometry
                # and labels remain current catalogue metadata in historical views.
                digest.update(encode({key: row[key] for key in ('ref', 'type', 'source_id', 'native_id', 'label')}).encode())
                if query.sort.field == 'updated_at':
                    digest.update(str(row['updated_at']).encode())
            else:
                digest.update(f"{row['ref']}:{row['revision']};".encode())
        if ranged and any(t.endswith('_station') for t in query.types):
            for table in ('station_measurements', 'station_index_observations'):
                row = self.db.execute(f'''SELECT count(*),coalesce(max(m.id),0) FROM {table} m INDEXED BY {table.replace('observations', '').rstrip('_') + '_current_window'}
                    WHERE m.is_current=1 AND m.quality='valid' AND m.object_ref IN
                    (SELECT o.ref FROM catalog_objects o WHERE {where}) AND m.observed_at>=? AND m.observed_at<?''', list(params)+[iso(overview[0]), iso(overview[1])]).fetchone()
                digest.update(encode(list(row)).encode())
        if query and any(t in MOVING_TYPES for t in query.types):
            # Track storage is independent of catalogue writes; recording, retention,
            # watch changes and source outages still invalidate the relevant result.
            watches = self.db.execute(f'''SELECT w.ref FROM workspace_watchlist w
                WHERE w.ref IN (SELECT o.ref FROM catalog_objects o WHERE {where}) ORDER BY w.ref''', params)
            digest.update(encode([r['ref'] for r in watches]).encode())
            if not ranged:
                sources = self.db.execute(f'''SELECT resource,status,stale FROM workspace_moving_sources
                    WHERE resource IN (SELECT o.source_id FROM catalog_objects o WHERE {where}) ORDER BY resource''', params)
                digest.update(encode([dict(r) for r in sources]).encode())
            track_where = f'''t.kind IN ('aircraft','ship') AND EXISTS (SELECT 1 FROM catalog_objects o
                WHERE {where} AND o.type=t.kind AND o.native_id=t.object_id)'''
            time_clause, track_params = '', list(params)
            if ranged:
                time_clause = ' AND p.position_at>=? AND p.position_at<?'
                track_params += [iso(overview[0]), iso(overview[1])]
            # Track points are immutable append-only records (apart from retention).
            # A compact storage token detects additions/deletions without serializing
            # every retained point on each live catalogue query under the writer lock.
            points = self.db.execute(f'''SELECT count(*),max(p.rowid),max(p.recorded_at),
                min(p.position_at),max(p.position_at) FROM catalog_objects o
                JOIN object_tracks t ON t.kind=o.type AND t.object_id=o.native_id
                JOIN object_track_points p ON p.track_id=t.id WHERE {where}{time_clause}''', track_params).fetchone()
            digest.update(encode(list(points)).encode())
            if not ranged:
                tracks = self.db.execute(f'SELECT t.* FROM object_tracks t WHERE {track_where} ORDER BY t.id', params)
                digest.update(encode([dict(r) for r in tracks]).encode())
        if query and self._includes_ukraine(query):
            digest.update(encode(self.ukraine.revision_token(*(overview if ranged else (None, None)))).encode())
            watches = self.db.execute(f'''SELECT w.ref FROM workspace_watchlist w
                WHERE w.ref IN (SELECT o.ref FROM catalog_objects o WHERE {where}) ORDER BY w.ref''', params)
            digest.update(encode([r['ref'] for r in watches]).encode())
        revision = digest.hexdigest()[:24]
        self.revisions[cache_key] = revision
        while len(self.revisions) > 16:
            self.revisions.popitem(last=False)
        return revision

    def _ranges(self, query, now):
        day = now.astimezone(WARSAW).date()
        start = datetime.combine(day, time(), WARSAW).astimezone(UTC)
        end = datetime.combine(day+timedelta(days=1), time(), WARSAW).astimezone(UTC)
        selected = query.time.filter_range
        overview = query.time.overview_range or selected
        return ((selected.start, selected.end) if selected else (start, end),
                (overview.start, overview.end) if overview else (start, end))

    def _time_filter(self, query, interval, now):
        start, end = map(iso, interval)
        comm = '(o.published_at>=? AND o.published_at<?) OR (o.updated_at>=? AND o.updated_at<?)'
        params = [start, end, start, end]
        # Date-only publications denote the civil day, not an invented midnight event.
        comm += " OR (o.date_precision='day' AND o.published_at<? AND json_extract(o.metadata_json,'$.published_until')>?)"
        params.extend([end, start])
        if query.include_periods:
            if query.time.mode == 'live':
                comm += " OR (o.valid_from IS NOT NULL AND o.valid_until>? AND json_extract(o.metadata_json,'$.source_warning_status')!='cancelled') OR (o.display_from<=? AND o.display_until>?)"
                params.extend([iso(now), iso(now), iso(now)])
            else:
                comm += ' OR (o.valid_from<? AND o.valid_until>?) OR (o.display_from<? AND o.display_until>?)'
                params.extend([end, start, end, start])
        stations = '1=1'
        if not query.include_without_samples:
            sample_start, sample_end = start, end
            if query.time.mode == 'live':
                sample_start, sample_end = iso(now-timedelta(days=14)), iso(now+timedelta(microseconds=1))
            stations = '''(EXISTS (SELECT 1 FROM station_measurements m WHERE m.object_ref=o.ref
                AND m.quality='valid' AND m.observed_at>=? AND m.observed_at<?)
                OR EXISTS (SELECT 1 FROM station_index_observations i WHERE i.object_ref=o.ref
                AND i.quality='valid' AND i.observed_at>=? AND i.observed_at<?))'''
            params.extend([sample_start, sample_end, sample_start, sample_end])
        movers = '1=1'
        if query.time.mode == 'range':
            movers = '''EXISTS (SELECT 1 FROM object_tracks t JOIN object_track_points p ON p.track_id=t.id
                WHERE t.kind=o.type AND t.object_id=o.native_id AND p.position_at>=? AND p.position_at<?)'''
            params.extend([start, end])
        episodes = "e.active=1"
        if query.time.mode == 'range':
            retained_start = max(interval[0], now-timedelta(days=30))
            episodes = 'e.first_seen_at<? AND COALESCE(e.ended_before,?)>? AND ?<?'
            params.extend([end, iso(now), iso(retained_start), iso(retained_start), end])
        return f"""(o.type IN ('area','ua_region','custom_area') OR (o.type='communication' AND ({comm}))
            OR (o.type IN ('hydro_station','air_quality_station') AND ({stations}))
            OR (o.type IN ('aircraft','ship') AND ({movers}))
            OR (o.type='civil_alert' AND EXISTS (SELECT 1 FROM workspace_ukraine_episodes e WHERE e.ref=o.ref AND ({episodes}))))""", params

    def _sample(self, ref, start, end, cursor_at=None, sensor_id=None, metric=None):
        clauses = ["object_ref=?", "quality='valid'", 'observed_at>=?', 'observed_at<?']
        params = [ref, iso(start), iso(end)]
        if cursor_at:
            clauses.append('observed_at<=?')
            params.append(iso(cursor_at))
        if sensor_id is not None:
            clauses.append('sensor_id=?')
            params.append(str(sensor_id))
        if metric:
            clauses.append('metric=?')
            params.append(metric)
        if ref.startswith('hydro_station:') and not metric:
            clauses.append("metric='water_level'")
        row = self.db.execute(f'SELECT * FROM station_measurements WHERE {" AND ".join(clauses)} '
                              'ORDER BY observed_at DESC,revision DESC,id DESC LIMIT 1', params).fetchone()
        return self._observation(row) if row else None

    def _observation(self, row):
        item = dict(row)
        for name in ('provenance', 'thresholds'):
            if name+'_json' in item:
                item[name] = json.loads(item.pop(name+'_json'))
        item.pop('content_hash', None)
        item['ref'] = item.get('object_ref')
        item['at'] = item.get('observed_at')
        return item

    def _present(self, item, now, interval, query=None):
        item = dict(item)
        if item['type'] == 'communication':
            meta = item['metadata']
            status = meta.get('source_warning_status', 'unknown')
            start, end = parse_time(item.get('valid_from')), parse_time(item.get('valid_until'))
            if status != 'cancelled' and start and end:
                status = 'upcoming' if now < start else 'expired' if now >= end else 'active'
            item['warning_status'] = status
        elif item['type'].endswith('_station'):
            start, end = interval
            if query is None or query.time.mode == 'live':
                start, end = now-timedelta(days=14), now+timedelta(microseconds=1)
            item['measurement'] = self._sample(item['ref'], start, end)
            index = self.db.execute('''SELECT * FROM station_index_observations WHERE object_ref=?
                AND quality='valid' AND observed_at>=? AND observed_at<? ORDER BY observed_at DESC,revision DESC LIMIT 1''',
                (item['ref'], iso(start), iso(end))).fetchone()
            item['official_index'] = self._observation(index) if index else None
            observed = (item['measurement'] or item['official_index'] or {}).get('observed_at')
            item['freshness'] = ('unknown_time' if not observed else 'future' if parse_time(observed) > now
                                 else 'stale' if (now-parse_time(observed)).total_seconds() > 10800 else 'fresh')
            item['value_context'] = 'current' if query is None or query.time.mode == 'live' else 'period_overview'
        elif item['type'] == 'custom_area':
            item['geometry'] = item['metadata']['geometry']
            item['color'] = item['metadata']['color']
        elif item['type'] in MOVING_TYPES:
            return self.moving.present(item, now, interval, historical=query is not None and query.time.mode == 'range')
        elif item['type'] in ('ua_region', 'civil_alert'):
            return self.ukraine.present(item, now, interval, historical=query is not None and query.time.mode == 'range')
        return item

    def query(self, raw):
        query = WorkspaceQuery.model_validate(raw)
        fingerprint = hashlib.sha256(encode(query.model_dump(mode='json', exclude={'cursor', 'query_revision'})).encode()).hexdigest()
        cursor = self._decode_cursor(query.cursor) if query.cursor else None
        if cursor and cursor.get('fingerprint') != fingerprint:
            raise QueryChanged('Filtry zmieniły się; odśwież cały wynik')
        now = parse_time(cursor['as_of']) if cursor else self.repo.clock().astimezone(UTC)
        interval, overview = self._ranges(query, now)
        where, params = self._base(query, now, interval)
        with self.repo.lock:
            base_revision = self._revision(where, params, query, overview, now)
            revision = hashlib.sha256((base_revision+fingerprint).encode()).hexdigest()[:24]
            if cursor and cursor['revision'] != revision:
                raise QueryChanged('Dane zmieniły się; odśwież cały wynik')
            time_where, time_params = self._time_filter(query, interval, now)
            selected_where, selected_params = f'({where}) AND {time_where}', params+time_params
            order = {'label': 'search_text', 'type': 'type', 'updated_at': 'updated_at',
                     'published_at': 'published_at', 'source_id': 'source_id'}[query.sort.field]
            offset = cursor['offset'] if cursor else 0
            total = self.db.execute(f'SELECT count(*) FROM catalog_objects o WHERE {selected_where}', selected_params).fetchone()[0]
            rows = self.db.execute(f'SELECT o.* FROM catalog_objects o WHERE {selected_where} '
                                  f'ORDER BY o.{order} {query.sort.direction},o.ref ASC LIMIT ? OFFSET ?',
                                  selected_params+[query.page_size, offset]).fetchall()
            items = [self._present(self.catalog.decode(row), now, interval, query) for row in rows]
            map_data = self._map(selected_where, selected_params, now, interval, query, total)
            histogram_key = revision+encode([iso(x) for x in overview])
            timeline = self.histograms.get(histogram_key)
            if timeline is None:
                timeline = self._histogram(where, params, overview, interval,
                    self._includes_ukraine(query), now-timedelta(days=30))
                self.histograms[histogram_key] = timeline
                while len(self.histograms) > 16:
                    self.histograms.popitem(last=False)
            context_key = revision+':'+iso(now)
            self.contexts[context_key] = (where, params, query, interval, base_revision, overview)
            self.contexts.move_to_end(context_key)
            while len(self.contexts) > 64:
                self.contexts.popitem(last=False)
            next_cursor = self._encode_cursor({'fingerprint': fingerprint, 'revision': revision, 'as_of': iso(now),
                                                   'offset': offset+query.page_size}) if offset+len(items) < total else None
            warnings = []
            if map_data['mode'] == 'aggregates':
                warnings.append('Mapa grupuje ponad 1000 obiektów. Wybierz województwo, typ lub zawęź wyszukiwanie.')
            if map_data.get('truncated'):
                warnings.append('Mapa pokazuje pierwsze 1000 obiektów z pozycją. Zawęź typ, wyszukiwanie lub listę obserwowanych; tabela obejmuje cały wynik.')
            if query.time.mode == 'range':
                warnings.append('Metadane opisują bieżący katalog. Pozycje samolotów i statków w przedziale pochodzą wyłącznie z zapisanych tras; historia innych obiektów obejmuje lokalne obserwacje.')
            return {'query_revision': query.query_revision, 'data_revision': revision, 'as_of': iso(now), 'items': items,
                        'total': total, 'next_cursor': next_cursor, 'map': map_data, 'timeline_summary': timeline,
                        'coverage': self._coverage(), 'warnings': warnings}

    def _map(self, where, params, now, interval, query, total):
        located, location_params = self._located(query, interval, now)
        located = '('+located+')'
        map_params = params+location_params
        count = self.db.execute(f'SELECT count(*) FROM catalog_objects o WHERE {where} AND {located}', map_params).fetchone()[0]
        result = {'mode': 'objects', 'points': [], 'areas': [], 'aggregates': [], 'located_total': count,
                      'unlocated_total': total-count, 'total': count}
        movers = self.db.execute(f"SELECT 1 FROM catalog_objects o WHERE {where} AND {located} AND o.type IN ('aircraft','ship','ua_region','civil_alert') LIMIT 1", map_params).fetchone()
        if count <= 1000 or movers:
            result['truncated'] = count > 1000
            rows = self.db.execute(f'SELECT o.* FROM catalog_objects o WHERE {where} AND {located} ORDER BY o.ref LIMIT 1000', map_params).fetchall()
            for row in rows:
                item = self._present(self.catalog.decode(row), now, interval, query)
                result['points' if item.get('latitude') is not None and item.get('longitude') is not None else 'areas'].append(item)
        else:
            result['mode'] = 'aggregates'
            groups = self.db.execute(f'''SELECT o.type,substr(a.admin_code,1,2) province,count(DISTINCT o.ref) count
                FROM catalog_objects o LEFT JOIN catalog_object_areas a ON a.ref=o.ref WHERE {where}
                AND {located} GROUP BY o.type,substr(a.admin_code,1,2) ORDER BY o.type,province''', map_params)
            result['aggregates'] = [dict(row, ref=f"aggregate:{row['type']}:{row['province'] or 'unknown'}") for row in groups]
        result['items'] = result['points']+result['areas']+result['aggregates']
        return result

    def _histogram(self, where, params, overview, interval, include_ukraine=False, ukraine_cutoff=None):
        start, end = overview
        seconds = (end-start).total_seconds()
        step = next((s for s in (300, 900, 3600, 10800, 21600, 86400, 604800, 2592000, 31536000)
                     if seconds/s <= 300), math.ceil(seconds/300))
        counts = {}
        def add(timestamp, count=1):
            instant = parse_time(timestamp)
            if instant and start <= instant < end:
                index = int((instant-start).total_seconds()//step)
                counts[index] = counts.get(index, 0)+count
        publications = self.db.execute(f'''SELECT o.published_at,o.updated_at FROM catalog_objects o
            WHERE {where} AND o.type='communication' AND ((o.published_at>=? AND o.published_at<?)
            OR (o.updated_at>=? AND o.updated_at<?))''', params+[iso(start), iso(end), iso(start), iso(end)])
        for row in publications:
            add(row['published_at'])
            if row['updated_at'] != row['published_at']:
                add(row['updated_at'])
        # Latest-revision projection avoids grouping every immutable correction before
        # bucketing; a partial covering index bounds historical window scans.
        for table in ('station_measurements', 'station_index_observations'):
            rows = self.db.execute(f'''SELECT CAST((julianday(m.observed_at)-julianday(?))*86400/? AS INTEGER) bucket,
                count(*) count FROM {table} m INDEXED BY {table.replace('observations', '').rstrip('_') + '_current_window'} WHERE m.object_ref IN (SELECT o.ref FROM catalog_objects o WHERE {where})
                AND m.is_current=1 AND m.quality='valid' AND m.observed_at>=? AND m.observed_at<?
                GROUP BY bucket''', [iso(start), step]+params+[iso(start), iso(end)])
            for row in rows:
                index = max(0, row['bucket'])
                counts[index] = counts.get(index, 0)+row['count']
        rows = self.db.execute(f'''SELECT CAST((julianday(p.position_at)-julianday(?))*86400/? AS INTEGER) bucket,
            count(*) count FROM catalog_objects o
            JOIN object_tracks t ON t.kind=o.type AND t.object_id=o.native_id
            JOIN object_track_points p ON p.track_id=t.id WHERE {where} AND o.type IN ('aircraft','ship')
            AND p.position_at>=? AND p.position_at<? GROUP BY bucket''', [iso(start), step]+params+[iso(start), iso(end)])
        for row in rows:
            index = max(0, row['bucket'])
            counts[index] = counts.get(index, 0)+row['count']
        if include_ukraine and (ukraine_cutoff is None or end > ukraine_cutoff):
            retained_start = max(start, ukraine_cutoff) if ukraine_cutoff else start
            rows = self.db.execute(f'''SELECT CAST((julianday(u.observed_at)-julianday(?))*86400/? AS INTEGER) bucket,
                count(*) count FROM workspace_ukraine_observations u WHERE EXISTS
                (SELECT 1 FROM catalog_objects o WHERE {where} AND (o.ref=u.region_ref OR o.ref=u.episode_ref))
                AND u.observed_at>=? AND u.observed_at<? GROUP BY bucket''', [iso(start), step]+params+[iso(retained_start), iso(end)])
            for row in rows:
                index = max(0, row['bucket'])
                counts[index] = counts.get(index, 0)+row['count']
        buckets = [dict(**{'from': iso(start+timedelta(seconds=i*step)),
                          'to': iso(min(end, start+timedelta(seconds=(i+1)*step)))}, count=counts.get(i, 0))
                   for i in range(math.ceil(seconds/step))]
        timeless = self.db.execute(f"SELECT count(*) FROM catalog_objects o WHERE {where} AND o.type IN ('area','ua_region','custom_area')", params).fetchone()[0]
        selected_total = (sum(counts.values()) if overview == interval
                          else self._histogram(where, params, interval, interval, include_ukraine, ukraine_cutoff)['event_total'])
        return {'buckets': buckets, 'bucket_seconds': step, 'event_total': sum(counts.values()), 'timeless_total': timeless,
                    'selected_event_total': selected_total,
                    'overview_range': {'from': iso(start), 'to': iso(end)},
                    'filter_range': {'from': iso(interval[0]), 'to': iso(interval[1])},
                    'count_basis': 'Obserwacje stacji, zapisane pozycje tras, zmiany alarmów Ukrainy oraz publikacje/aktualizacje; obszary nie są zdarzeniami'}

    def _coverage(self):
        rows = self.db.execute('''SELECT * FROM workspace_source_runs WHERE id IN
            (SELECT max(id) FROM workspace_source_runs GROUP BY resource) ORDER BY resource''')
        sources = {row['resource']: dict(row) for row in rows}
        for resource in ('hydro:stations', 'gios:stations'):
            if resource not in sources:
                sources[resource] = {'resource': resource,
                                     'status': 'not_loaded' if self.source_enabled.get(resource, True) else 'disabled',
                                     'fetched_at': None, 'item_count': 0, 'complete': False}
        for resource in ('aircraft', 'ships'):
            row = self.db.execute('SELECT * FROM workspace_moving_sources WHERE resource=?', (resource,)).fetchone()
            sources[resource] = dict(row) if row else {'resource': resource,
                'status': 'not_loaded' if self.source_enabled.get(resource, True) else 'disabled',
                'fetched_at': None, 'item_count': 0}
            sources[resource]['complete'] = False
        ukraine = self.ukraine.status()
        sources['ukraine_alerts'] = dict(ukraine, resource='ukraine_alerts', complete=False)
        if not self.source_enabled.get('ukraine_alerts', True):
            sources['ukraine_alerts']['status'] = 'disabled'
        return {'sources': list(sources.values()), 'history_days': 14,
                'moving_history_days': 7,
                'ukraine_history_days': 30,
                'history_note': 'Historia stacji rośnie po pobraniu źródła. Historia ruchu obejmuje tylko zapisane sesje (7 dni). Historia alarmów Ukrainy obejmuje lokalną rejestrację (30 dni); lista obserwowanych nie włącza zapisu.'}

    def status(self):
        with self.repo.lock:
            return dict(status='ready', projection_version=1,
                        counts={r['type']: r['count'] for r in self.db.execute('SELECT type,count(*) count FROM catalog_objects GROUP BY type')},
                        **self._coverage())

    def _context(self, data_revision, as_of):
        now = parse_time(as_of) if as_of else self.repo.clock().astimezone(UTC)
        context = self.contexts.get((data_revision or '')+':'+iso(now))
        if data_revision and (context is None or self._revision(context[0], context[1], context[2], context[5], now) != context[4]):
            raise QueryChanged('Dane zmieniły się; odśwież cały wynik')
        return now, context

    def detail(self, ref, as_of=None, data_revision=None, cursor_at=None, sensor_id=None, metric=None, version_id=None):
        with self.repo.lock:
            now, context = self._context(data_revision, as_of)
            item = self.catalog.object(ref)
            if not item:
                raise KeyError(ref)
            interval = context[3] if context else (now-timedelta(days=14)+timedelta(microseconds=1), now+timedelta(microseconds=1))
            query = context[2] if context else None
            item = self._present(item, now, interval, query)
            result = {'object': item, 'communication': None, 'measurements': [], 'sensors': [], 'versions': [], 'as_of': iso(now),
                          'data_revision': data_revision, 'geometry_context': 'Aktualne metadane i geometria katalogu'}
            if context:
                time_where, time_params = self._time_filter(query, interval, now)
                result['in_scope'] = self.db.execute(f'SELECT 1 FROM catalog_objects o WHERE ({context[0]}) AND {time_where} AND o.ref=?',
                                                     context[1]+time_params+[ref]).fetchone() is not None
            else:
                result['in_scope'] = True
            if item['type'] == 'custom_area':
                result['custom_area'] = self.areas.detail(item['native_id'])
                result['area_history'] = self.areas.history(item['native_id'])['items']
                result['geometry_context'] = 'Własny obszar, rewizja '+str(result['custom_area']['revision'])
            elif item['type'] == 'communication':
                detail = self.repo.communication_detail(item['document_id'])
                detail['warning_status'] = item['warning_status']
                result['communication'] = detail
                result['versions'] = detail['history']
                if version_id is not None:
                    version = next((v for v in detail['history'] if v['id'] == int(version_id)), None)
                    if version is None:
                        raise KeyError(version_id)
                    result['selected_version'] = version
            elif item['type'].endswith('_station'):
                result['sensors'] = [dict(row) for row in self.db.execute(
                    'SELECT sensor_id,parameter,name,unit FROM station_sensors WHERE object_ref=? ORDER BY parameter,sensor_id', (ref,))]
                start, end = interval
                if query is None or query.time.mode == 'live':
                    start, end = now-timedelta(days=14), now+timedelta(microseconds=1)
                cursor_time = parse_time(cursor_at) if cursor_at else None
                if cursor_time and not start <= cursor_time < end:
                    raise ValueError('Kursor musi mieścić się w wybranym przedziale')
                selected = self._sample(ref, start, end, cursor_time, sensor_id, metric)
                result['selected_measurement'] = selected
                result['object']['measurement'] = selected
                result['object']['value_context'] = 'cursor' if cursor_at else item['value_context']
                if cursor_time:
                    index = self.db.execute('''SELECT * FROM station_index_observations WHERE object_ref=?
                        AND quality='valid' AND observed_at>=? AND observed_at<? AND observed_at<=?
                        ORDER BY observed_at DESC,revision DESC LIMIT 1''',
                        (ref, iso(start), iso(end), iso(cursor_time))).fetchone()
                    result['object']['official_index'] = self._observation(index) if index else None
                # All latest hydro metrics, or selected GIOS sensor, with original units/provenance.
                series = self.db.execute('SELECT DISTINCT sensor_id,metric FROM station_measurements WHERE object_ref=?', (ref,))
                for entry in series:
                    if sensor_id is not None and str(sensor_id) != entry['sensor_id']:
                        continue
                    value = self._sample(ref, start, end, cursor_time, entry['sensor_id'], entry['metric'])
                    if value:
                        result['measurements'].append(value)
            elif item['type'] in MOVING_TYPES:
                cursor_time = parse_time(cursor_at) if cursor_at else None
                if cursor_time and not interval[0] <= cursor_time < interval[1]:
                    raise ValueError('Kursor musi mieścić się w wybranym przedziale')
                result['object'] = self.moving.present(item, now, interval,
                    historical=query is not None and query.time.mode == 'range', cursor_at=cursor_time)
                result['track_sessions'] = self.moving.sessions(ref)
                result['geometry_context'] = 'Pozycja z zapisu w wybranym przedziale' if cursor_time or query and query.time.mode == 'range' else 'Świeża pozycja źródłowa; ostatnia znana pozycja dostępna osobno'
            elif item['type'] in ('ua_region', 'civil_alert'):
                cursor_time = parse_time(cursor_at) if cursor_at else None
                if cursor_time and not interval[0] <= cursor_time < interval[1]:
                    raise ValueError('Kursor musi mieścić się w wybranym przedziale')
                result['object'] = self.ukraine.present(item, now, interval,
                    historical=query is not None and query.time.mode == 'range', cursor_at=cursor_time)
                result['ukraine'] = self.ukraine.detail(ref, *interval, cursor_at=cursor_time)
                result['geometry_context'] = 'Aktualna geometria regionu; zapisany stan alarmu z jawnymi lukami obserwacji'
            return result

    def timeline(self, ref, start=None, end=None, sensor_id=None, metric=None, cursor=None, limit=2000,
                 as_of=None, data_revision=None, index_cursor=None):
        with self.repo.lock:
            now, context = self._context(data_revision, as_of)
            item = self.catalog.object(ref)
            if not item:
                raise KeyError(ref)
            interval = context[3] if context else (now-timedelta(days=14)+timedelta(microseconds=1), now+timedelta(microseconds=1))
            if item['type'].endswith('_station') and context and context[2].time.mode == 'live':
                interval = (now-timedelta(days=14)+timedelta(microseconds=1), now+timedelta(microseconds=1))
            a, b = parse_time(start) if start else interval[0], parse_time(end) if end else interval[1]
            if b <= a or ((item['type'].endswith('_station') or item['type'] in MOVING_TYPES) and (b-a).total_seconds() > 14*86400):
                raise ValueError('Nieprawidłowy przedział historii')
            if item['type'] in ('ua_region', 'civil_alert') and (b-a).total_seconds() > 30*86400:
                raise ValueError('Historia alarmów Ukrainy obejmuje najwyżej 30 dni')
            offset = int(cursor or 0)
            if offset < 0 or offset > 10000000 or not 1 <= limit <= 2000:
                raise ValueError('Nieprawidłowa strona historii')
            events, total = [], 0
            if item['type'] == 'communication':
                source_day = "json_extract(fields_json,'$.source_published_date')"
                instant = f'COALESCE(source_updated_at,source_published_at,workspace_day_start({source_day}),created_at)'
                day_only = f'source_updated_at IS NULL AND source_published_at IS NULL AND workspace_day_start({source_day}) IS NOT NULL'
                predicate = f'document_id=? AND (({instant}>=? AND {instant}<?) OR ({day_only} AND workspace_day_start({source_day})<? AND workspace_day_end({source_day})>?))'
                params = (item['document_id'], iso(a), iso(b), iso(b), iso(a))
                total = self.db.execute(f'SELECT count(*) FROM document_versions WHERE {predicate}', params).fetchone()[0]
                rows = self.db.execute(f'''SELECT id,version_number,title,source_published_at,source_updated_at,created_at,
                    {instant} at,{source_day} source_date,CASE WHEN {day_only} THEN 'day' ELSE 'instant' END date_precision,
                    CASE WHEN {day_only} THEN workspace_day_end({source_day}) ELSE NULL END end_at
                    FROM document_versions WHERE {predicate} ORDER BY version_number LIMIT ? OFFSET ?''',
                    (*params, limit, offset))
                for row in rows:
                    event = dict(row)
                    events.append(dict(event, ref=ref, kind='version', version_id=event['id']))
            elif item['type'].endswith('_station'):
                clauses = ["object_ref=?", "quality='valid'", 'observed_at>=?', 'observed_at<?']
                params = [ref, iso(a), iso(b)]
                if sensor_id is not None:
                    clauses.append('sensor_id=?')
                    params.append(str(sensor_id))
                if metric:
                    clauses.append('metric=?')
                    params.append(metric)
                predicate = ' AND '.join(clauses)
                columns = 'id,object_ref,observed_at,source_time,value,fetched_at,first_fetched_at,revision,quality,provenance_json'
                sql = f"SELECT {columns},sensor_id,metric,unit,thresholds_json,NULL name,NULL calculated_at,NULL source_calculated_time,'measurement' kind FROM station_measurements WHERE {predicate}"
                count_sql = f'SELECT count(*) FROM station_measurements WHERE {predicate}'
                total = self.db.execute(count_sql, params).fetchone()[0]
                if sensor_id is None and metric is None:
                    index_predicate = "object_ref=? AND quality='valid' AND observed_at>=? AND observed_at<?"
                    total += self.db.execute(f'SELECT count(*) FROM station_index_observations WHERE {index_predicate}',
                                             (ref, iso(a), iso(b))).fetchone()[0]
                    sql += f" UNION ALL SELECT {columns},'' sensor_id,'official_index' metric,NULL unit,'{{}}' thresholds_json,name,calculated_at,source_calculated_time,'official_index' kind FROM station_index_observations WHERE {index_predicate}"
                    params += [ref, iso(a), iso(b)]
                rows = self.db.execute(sql+' ORDER BY observed_at,id,kind LIMIT ? OFFSET ?', [*params, limit, offset])
                # SQL caps every page; raw correction rows preserve extrema, nulls and gaps.
                events = [self._observation(row) for row in rows]
            elif item['type'] in MOVING_TYPES:
                predicate = 't.kind=? AND t.object_id=? AND p.position_at>=? AND p.position_at<?'
                params = (item['type'], item['native_id'], iso(a), iso(b))
                total = self.db.execute(f'''SELECT count(*) FROM object_track_points p JOIN object_tracks t
                    ON t.id=p.track_id WHERE {predicate}''', params).fetchone()[0]
                rows = self.db.execute(f'''SELECT p.* FROM object_track_points p JOIN object_tracks t
                    ON t.id=p.track_id WHERE {predicate} ORDER BY p.position_at,p.track_id LIMIT ? OFFSET ?''',
                    (*params, limit, offset))
                events = [dict(self.moving._point_result(row), ref=ref, kind='track_point') for row in rows]
            elif item['type'] in ('ua_region', 'civil_alert'):
                history = self.ukraine.timeline(ref, a, b)
                all_events = history['items'] if isinstance(history, dict) else history
                total = len(all_events)
                events = all_events[offset:offset+limit]
            indices, index_count, index_offset = [], 0, int(index_cursor or 0)
            if index_offset < 0 or index_offset > 10000000:
                raise ValueError('Nieprawidłowa strona indeksów')
            if item['type'] == 'air_quality_station':
                predicate = "object_ref=? AND is_current=1 AND quality='valid' AND observed_at>=? AND observed_at<?"
                params = (ref, iso(a), iso(b))
                index_count = self.db.execute(f'SELECT count(*) FROM station_index_observations WHERE {predicate}', params).fetchone()[0]
                rows = self.db.execute(f'SELECT * FROM station_index_observations WHERE {predicate} ORDER BY observed_at,id LIMIT 2000 OFFSET ?',
                                       (*params, index_offset))
                indices = [dict(self._observation(row), kind='official_index') for row in rows]
            return {'ref': ref, 'items': events, 'total': total,
                    'official_indices': indices, 'official_indices_total': index_count,
                    'official_indices_next_cursor': str(index_offset+2000) if index_offset+2000 < index_count else None,
                    'next_cursor': str(offset+limit) if offset+limit < total else None,
                    'aggregated': False, 'range': {'from': iso(a), 'to': iso(b)},
                    'timezone': 'Europe/Warsaw', 'as_of': iso(now), 'data_revision': data_revision,
                    'note': 'Luki i jawne braki wartości pozostają lukami; brak interpolacji.'}

    def watchlist(self):
        now = self.repo.clock().astimezone(UTC)
        with self.repo.lock:
            rows = self.db.execute('''SELECT o.* FROM catalog_objects o JOIN workspace_watchlist w ON w.ref=o.ref
                ORDER BY o.label,o.ref''')
            return {'items': [self._present(self.catalog.decode(row), now,
                (now-timedelta(days=7), now+timedelta(microseconds=1))) for row in rows]}

    def watch(self, ref, watched):
        with self.repo.lock, self.db:
            item = self.catalog.object(ref)
            if item is None:
                raise KeyError(ref)
            if item['type'] not in (*MOVING_TYPES, 'ua_region'):
                raise ValueError('Obserwować można samoloty, statki i regiony Ukrainy')
            if watched:
                self.db.execute('INSERT OR IGNORE INTO workspace_watchlist VALUES(?,?)', (ref, iso(self.repo.clock())))
            else:
                self.db.execute('DELETE FROM workspace_watchlist WHERE ref=?', (ref,))
            return {'ref': ref, 'watched': watched}

    def ukraine_regions(self):
        with self.repo.lock:
            return {'items': self.ukraine.regions()}

    def ukraine_replay(self, body):
        with self.repo.lock:
            return self.ukraine.replay(body.refs, body.start, body.end)

    def views(self):
        with self.repo.lock:
            return {'items': [self._view(row) for row in self.db.execute('SELECT * FROM workspace_views ORDER BY name,id')]}

    def _view(self, row):
        item = dict(row)
        item['config'] = json.loads(item.pop('config_json'))
        return item

    def save_view(self, raw, view_id=None):
        view = SavedView.model_validate(raw)
        now = iso(self.repo.clock())
        with self.repo.lock, self.db:
            if view_id:
                old = self.db.execute('SELECT * FROM workspace_views WHERE id=?', (view_id,)).fetchone()
                if not old:
                    raise KeyError(view_id)
                if view.revision != old['revision']:
                    raise QueryChanged('Widok został zmieniony; odczytaj jego bieżącą wersję')
                self.db.execute('UPDATE workspace_views SET name=?,schema_version=?,config_json=?,revision=revision+1,updated_at=? WHERE id=?',
                                (view.name, view.schema_version, encode(view.config), now, view_id))
            else:
                view_id = str(uuid.uuid4())
                self.db.execute('INSERT INTO workspace_views VALUES(?,?,?,?,?,?,?)',
                                (view_id, view.name, view.schema_version, encode(view.config), 1, now, now))
            return self._view(self.db.execute('SELECT * FROM workspace_views WHERE id=?', (view_id,)).fetchone())

    def delete_view(self, view_id):
        with self.repo.lock, self.db:
            if not self.db.execute('DELETE FROM workspace_views WHERE id=?', (view_id,)).rowcount:
                raise KeyError(view_id)
        return {'deleted': True}
