"""Local moving-object projection; observation tracks remain the history authority.

No network access. Ingestion receives already normalized source snapshots. A live
position expires independently of the durable identity and the user's watchlist.
"""
import re
from datetime import UTC, timedelta

from wici.geo import provinces_for_point
from wici.tracking import MAX_AGE, RETENTION_DAYS, finite, timestamp
from wici.workspace_models import MovingReplay
from wici.workspace_repository import WorkspaceRepository, encode, iso, search_text

MOVING_TYPES = ('aircraft', 'ship')
MAX_REPLAY_POINTS = 12000
REF = re.compile(r'^(aircraft:icao:([a-f0-9]{6})|ship:mmsi:([1-9][0-9]{8}))$')
SOURCE_IDS = {'aircraft': 'aircraft', 'ship': 'ships'}
SOURCE_NAMES = {'aircraft': 'adsb.fi', 'ship': 'AISStream'}
SOURCE_URLS = {'aircraft': 'https://adsb.fi/', 'ship': 'https://aisstream.io/'}


def identity(ref):
    match = REF.fullmatch(ref)
    if not match:
        raise ValueError('Nieprawidłowy identyfikator samolotu lub statku')
    return ('aircraft', match[2]) if match[2] else ('ship', match[3])


def object_ref(kind, native_id):
    if kind not in MOVING_TYPES:
        raise ValueError('Nieprawidłowy typ obiektu ruchomego')
    value = str(native_id).lower()
    ref = f'{kind}:{"icao" if kind == "aircraft" else "mmsi"}:{value}'
    identity(ref)
    return ref


class MovingObjects:
    def __init__(self, repo):
        self.repo, self.db = repo, repo.db
        self.catalog = WorkspaceRepository(repo)
        with self.repo.lock, self.db:
            # A persisted identity survives restart; a live feed must reconnect.
            self.db.execute("UPDATE workspace_moving_sources SET status='not_loaded',stale=1 WHERE status!='not_loaded' OR stale!=1")

    def _project(self, kind, native_id, label, metadata, previous=None):
        point = metadata.get('last_known_position') or {}
        lat, lon = point.get('latitude'), point.get('longitude')
        if previous and lat == previous.get('latitude') and lon == previous.get('longitude'):
            areas = previous['areas']
        else:
            areas = [{'admin_code': code, 'role': 'last_known_position',
                      'basis': 'Ostatnia znana pozycja w lokalnych granicach PRG'}
                     for code in provinces_for_point(lon, lat)]
        fields = [label, native_id, object_ref(kind, native_id)]
        fields.extend(str(metadata.get(key) or '') for key in ('registration', 'callsign', 'imo', 'name', 'type_code'))
        self.catalog.upsert({'ref': object_ref(kind, native_id), 'type': kind,
            'source_id': SOURCE_IDS[kind], 'native_id': native_id, 'label': label,
            'search_text': search_text(' '.join(fields)), 'latitude': lat, 'longitude': lon,
            'updated_at': point.get('position_at'), 'metadata_json': encode(metadata)}, areas)

    @staticmethod
    def _point(kind, item):
        at = timestamp(item.get('position_at'))
        lat, lon = finite(item.get('latitude'), -90, 90), finite(item.get('longitude'), -180, 180)
        if at is None or lat is None or lon is None:
            return None
        speed = finite(item.get('speed_kmh'), 0, 6000)
        if kind == 'ship':
            knots = finite(item.get('speed_knots'), 0, 102.2)
            speed = knots*1.852 if knots is not None else None
        heading = item.get('track') if kind == 'aircraft' else item.get('heading')
        if finite(heading, 0, 360) is None and kind == 'ship':
            heading = item.get('course')
        return {'position_at': iso(at), 'latitude': lat, 'longitude': lon,
                'altitude_m': finite(item.get('altitude_m'), -1000, 40000) if kind == 'aircraft' else None,
                'speed_kmh': speed, 'heading': finite(heading, 0, 360)}

    def ingest(self, kind, snapshot):
        """Persist an idempotent projection of a normalized collector snapshot."""
        if kind not in MOVING_TYPES:
            raise ValueError('Nieprawidłowy typ obiektu ruchomego')
        now = self.repo.clock().astimezone(UTC)
        status = str(snapshot.get('status', 'unknown'))
        stale = bool(snapshot.get('stale'))
        available = status == 'ready' and not stale and not snapshot.get('demo')
        seen = set()
        with self.repo.lock, self.db:
            for item in snapshot.get('items', []):
                if not isinstance(item, dict):
                    continue
                native_id = str(item.get('hex' if kind == 'aircraft' else 'mmsi', '')).lower()
                try:
                    ref = object_ref(kind, native_id)
                except ValueError:
                    # Non-ICAO ADS-B addresses do not become asserted ICAO identities.
                    continue
                previous = self.catalog.object(ref)
                metadata = dict(previous['metadata']) if previous else {'first_seen_at': iso(now)}
                fields = ('registration', 'type_code', 'military') if kind == 'aircraft' else ('name', 'imo', 'type_code', 'destination')
                for key in fields:
                    if item.get(key) is not None:
                        metadata[key] = item[key]
                if kind == 'aircraft' and item.get('id'):
                    metadata['callsign'] = item['id']
                point = self._point(kind, item)
                previous_at = timestamp((metadata.get('last_known_position') or {}).get('position_at'))
                if point and timestamp(point['position_at']) <= now and (previous_at is None or timestamp(point['position_at']) >= previous_at):
                    metadata['last_known_position'] = point
                fresh = point and 0 <= (now-timestamp(point['position_at'])).total_seconds() <= MAX_AGE[kind]
                metadata.update(source_name=SOURCE_NAMES[kind], live_present=bool(available and fresh),
                                icao=native_id if kind == 'aircraft' else None,
                                mmsi=native_id if kind == 'ship' else None)
                label = (metadata.get('callsign') or metadata.get('registration')) if kind == 'aircraft' else metadata.get('name')
                self._project(kind, native_id, str(label or native_id), metadata, previous)
                seen.add(ref)
            for row in self.db.execute('SELECT * FROM catalog_objects WHERE type=?', (kind,)).fetchall():
                if row['ref'] not in seen:
                    value = self.catalog.decode(row)
                    if value['metadata'].get('live_present'):
                        value['metadata']['live_present'] = False
                        self._project(kind, value['native_id'], value['label'], value['metadata'], value)
            # Unwatched identities without retained sessions expire after seven days.
            # Watchlist and retained tracks protect metadata independently of a live feed.
            cutoff = iso(now-timedelta(days=RETENTION_DAYS))
            self.db.execute('''DELETE FROM catalog_objects WHERE type=?
                AND COALESCE(updated_at,json_extract(metadata_json,'$.first_seen_at'),'')<?
                AND NOT EXISTS (SELECT 1 FROM workspace_watchlist w WHERE w.ref=catalog_objects.ref)
                AND NOT EXISTS (SELECT 1 FROM object_tracks t WHERE t.kind=catalog_objects.type
                    AND t.object_id=catalog_objects.native_id)''', (kind, cutoff))
            # Status changes matter even if the source returns the same cached points.
            fetched = timestamp(snapshot.get('fetched_at'))
            self.db.execute('''INSERT INTO workspace_moving_sources(resource,status,stale,fetched_at,item_count)
                VALUES(?,?,?,?,?) ON CONFLICT(resource) DO UPDATE SET status=excluded.status,
                stale=excluded.stale,fetched_at=excluded.fetched_at,item_count=excluded.item_count
                WHERE status!=excluded.status OR stale!=excluded.stale
                OR fetched_at IS NOT excluded.fetched_at OR item_count!=excluded.item_count''',
                (SOURCE_IDS[kind], 'disabled' if snapshot.get('demo') else status, int(stale),
                 iso(fetched) if fetched else None, len(seen)))

    def backfill_tracks(self):
        """Make existing recorded identities discoverable without claiming live data."""
        with self.repo.lock, self.db:
            rows = self.db.execute('SELECT * FROM object_tracks ORDER BY started_at DESC,id DESC').fetchall()
            for track in rows:
                try:
                    ref = object_ref(track['kind'], track['object_id'])
                except ValueError:
                    continue
                if self.catalog.object(ref):
                    continue
                kind = track['kind']
                row = self.db.execute('''SELECT p.* FROM object_track_points p JOIN object_tracks t ON t.id=p.track_id
                    WHERE t.kind=? AND t.object_id=? ORDER BY p.position_at DESC LIMIT 1''',
                    (kind, track['object_id'])).fetchone()
                point = {key: row[key] for key in ('position_at', 'latitude', 'longitude', 'speed_kmh', 'altitude_m', 'heading')} if row else None
                metadata = {'source_name': SOURCE_NAMES[kind], 'live_present': False,
                            'last_known_position': point, 'first_seen_at': track['started_at'], 'icao' if kind == 'aircraft' else 'mmsi': track['object_id']}
                if kind == 'aircraft' and track['military'] is not None:
                    metadata['military'] = bool(track['military'])
                if kind == 'ship':
                    metadata['type_code'] = track['ship_type_code']
                self._project(kind, track['object_id'], track['label'], metadata)

    def sessions(self, ref):
        kind, native_id = identity(ref)
        rows = self.db.execute('''SELECT t.*,COUNT(p.position_at) point_count,
            MIN(p.position_at) first_position_at,MAX(p.position_at) last_position_at
            FROM object_tracks t LEFT JOIN object_track_points p ON p.track_id=t.id
            WHERE t.kind=? AND t.object_id=? GROUP BY t.id ORDER BY t.started_at DESC,t.id''', (kind, native_id))
        result = []
        for row in rows:
            value = dict(row)
            value['active'] = bool(value['active'])
            value.pop('pending_break', None)
            result.append(value)
        return result

    def point_at(self, ref, start, end, cursor_at=None):
        kind, native_id = identity(ref)
        params = [kind, native_id, iso(start), iso(end)]
        cursor_filter = ''
        if cursor_at:
            cursor_filter = ' AND p.position_at<=?'
            params.append(iso(cursor_at))
        row = self.db.execute('''SELECT p.* FROM object_track_points p JOIN object_tracks t ON t.id=p.track_id
            WHERE t.kind=? AND t.object_id=? AND p.position_at>=? AND p.position_at<?'''+cursor_filter+
            ' ORDER BY p.position_at DESC,p.track_id LIMIT 1', params).fetchone()
        if row is None:
            return None
        if cursor_at and (cursor_at-timestamp(row['position_at'])).total_seconds() > MAX_AGE[kind]:
            return None
        return self._point_result(row)

    @staticmethod
    def _point_result(row):
        return {key: row[key] for key in ('track_id', 'position_at', 'latitude', 'longitude', 'altitude_m', 'speed_kmh', 'heading')} | {
            'at': row['position_at'], 'break_before': bool(row['break_before'])}

    def present(self, item, now, interval, historical=False, cursor_at=None):
        item = dict(item)
        ref, kind = item['ref'], item['type']
        item['watched'] = self.db.execute('SELECT 1 FROM workspace_watchlist WHERE ref=?', (ref,)).fetchone() is not None
        last = item['metadata'].get('last_known_position')
        item['last_known_position'] = last
        source = self.db.execute('SELECT * FROM workspace_moving_sources WHERE resource=?', (SOURCE_IDS[kind],)).fetchone()
        item['fetched_at'] = source['fetched_at'] if source else None
        item['provenance'] = {'attribution': SOURCE_NAMES[kind], 'source_url': SOURCE_URLS[kind],
                              'fetched_at': item['fetched_at']}
        source_ok = source and source['status'] == 'ready' and not source['stale']
        at = timestamp(last.get('position_at')) if last else None
        age = (now-at).total_seconds() if at else None
        fresh = source_ok and item['metadata'].get('live_present') and age is not None and 0 <= age <= MAX_AGE[kind]
        position = self.point_at(ref, *interval, cursor_at) if historical or cursor_at else last if fresh else None
        item.update(position=position, latitude=position['latitude'] if position else None,
                    longitude=position['longitude'] if position else None,
                    freshness=('recorded' if position else 'no_data') if historical or cursor_at else
                    'fresh' if fresh else 'stale' if at else 'unknown_time',
                    value_context='cursor' if cursor_at else 'period_overview' if historical else 'current',
                    gap_seconds=MAX_AGE[kind], source_status=source['status'] if source else 'not_loaded')
        # A missing point must not become a province polygon derived from last-known data.
        item['areas'] = []
        return item

    def watch(self, ref, watched):
        identity(ref)
        with self.repo.lock, self.db:
            if not self.catalog.object(ref):
                raise KeyError(ref)
            if watched:
                self.db.execute('INSERT OR IGNORE INTO workspace_watchlist VALUES(?,?)', (ref, iso(self.repo.clock())))
            else:
                self.db.execute('DELETE FROM workspace_watchlist WHERE ref=?', (ref,))
            return {'ref': ref, 'watched': watched}

    def replay(self, raw):
        request = MovingReplay.model_validate(raw)
        result = []
        with self.repo.lock:
            for ref in request.refs:
                obj = self.catalog.object(ref)
                if obj is None:
                    raise KeyError(ref)
                kind, native_id = identity(ref)
                params = (kind, native_id, iso(request.start), iso(request.end))
                base = '''FROM object_track_points p JOIN object_tracks t ON t.id=p.track_id
                    WHERE t.kind=? AND t.object_id=? AND p.position_at>=? AND p.position_at<?'''
                total = self.db.execute('SELECT count(*) '+base, params).fetchone()[0]
                if total > MAX_REPLAY_POINTS:
                    raise ValueError(f'{obj["label"]}: {total} punktów przekracza limit {MAX_REPLAY_POINTS}. Zawęź przedział odtwarzania; punkty nie są pomijane.')
                rows = self.db.execute('SELECT p.* '+base+' ORDER BY p.position_at,p.track_id', params).fetchall()
                points, previous = [], None
                for row in rows:
                    point = self._point_result(row)
                    point['break_before'] = bool(row['break_before'] or previous is None or
                        row['track_id'] != previous['track_id'] or
                        (timestamp(row['position_at'])-timestamp(previous['position_at'])).total_seconds() > MAX_AGE[kind])
                    points.append(point)
                    previous = row
                result.append({'ref': ref, 'label': obj['label'], 'type': kind, 'points': points,
                               'sessions': self.sessions(ref), 'gap_seconds': MAX_AGE[kind],
                               'total_points': total, 'returned_points': len(points), 'downsampled': False,
                               'sampling': 'all_recorded_points'})
        return {'series': result, 'range': {'from': iso(request.start), 'to': iso(request.end)},
                'retention_days': RETENTION_DAYS, 'max_points_per_object': MAX_REPLAY_POINTS,
                'interpolation': False,
                'note': 'Wyłącznie zapisane punkty. Przerwy pozostają przerwami; brak interpolacji i próbkowania.'}
