"""Local civil-alert history. Missing coverage is never evidence that an alert ended.

The current geometry cache is intentionally separate from observations. Successful
polls establish coverage; sparse immutable observations retain state corrections.
No network requests are made by this module.
"""
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from wici.workspace_repository import WorkspaceRepository, encode, iso, search_text

RETENTION_DAYS = 30
MAX_GAP_SECONDS = 45
LIVE_FRESH_SECONDS = 90
MAX_REGION_CHANGES = 12000
SOURCE_ID = 'ukraine_alerts'
SOURCE_URL = 'https://neptun.in.ua/'


def moment(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Czas historii Ukrainy wymaga strefy czasowej')
    return result.astimezone(UTC)


def region_ref(scope, key):
    if scope not in ('oblast', 'raion') or not isinstance(key, str) or not key or len(key) > 256:
        raise ValueError('Nieprawidłowy identyfikator regionu Ukrainy')
    if any(ord(c) < 32 for c in key):
        raise ValueError('Nieprawidłowy identyfikator regionu Ukrainy')
    return f'ua_region:neptun:{scope}:{key}'


class UkraineHistory:
    def __init__(self, repo):
        self.repo, self.db = repo, repo.db
        self.catalog = WorkspaceRepository(repo)
        with self.repo.lock, self.db:
            # An existing last-known state never becomes live solely on restart.
            self.mark_gap('restart')
            self.db.execute("UPDATE workspace_ukraine_state SET status='not_loaded' WHERE id=1")
            self._prune(self._now())

    def _now(self):
        return self.repo.clock().astimezone(UTC)

    def _state(self):
        return dict(self.db.execute('SELECT * FROM workspace_ukraine_state WHERE id=1').fetchone())

    def status(self, now=None):
        with self.repo.lock:
            value = self._state()
            value.pop('id')
            value['recording'] = bool(value['recording'])
            value['enabled'] = value['recording']
            value['retention_days'] = RETENTION_DAYS
            value['gap_seconds'] = MAX_GAP_SECONDS
            if value['status'] == 'ready' and (not value['fetched_at'] or
                    ((moment(now) if now is not None else self._now())-moment(value['fetched_at'])).total_seconds() > LIVE_FRESH_SECONDS):
                value['status'] = 'stale'
            value['regions'] = self.db.execute('SELECT COUNT(*) FROM workspace_ukraine_regions').fetchone()[0]
            value['episodes'] = self.db.execute('SELECT COUNT(*) FROM workspace_ukraine_episodes').fetchone()[0]
            return value

    def set_recording(self, enabled):
        if not isinstance(enabled, bool):
            raise TypeError('Stan rejestracji musi być logiczny')
        with self.repo.lock, self.db:
            current = self._state()
            if bool(current['recording']) != enabled:
                self.mark_gap('recording_started' if enabled else 'recording_stopped')
                self.db.execute('''UPDATE workspace_ukraine_state SET recording=?,recording_since=?,updated_at=?
                    WHERE id=1''', (int(enabled), iso(self._now()) if enabled else None, iso(self._now())))
            return self.status()

    def mark_gap(self, reason, at=None):
        at = moment(at) if at is not None else self._now()
        reason = str(reason)[:100]
        with self.repo.lock, self.db:
            previous = self.db.execute('SELECT * FROM workspace_ukraine_runs ORDER BY observed_at DESC,id DESC LIMIT 1').fetchone()
            if previous and previous['status'] == 'ready':
                self.db.execute('''INSERT INTO workspace_ukraine_runs(observed_at,recorded_at,status,reason)
                    VALUES(?,?,'unknown',?)''', (iso(at), iso(self._now()), reason))
            self.db.execute('''UPDATE workspace_ukraine_state SET status='unknown',gap_reason=?,updated_at=?
                WHERE id=1 AND (status!='unknown' OR gap_reason IS NOT ?)''', (reason, iso(at), reason))

    def _parent(self, oblast):
        if not oblast:
            return None, None
        exact = self.db.execute("SELECT ref FROM workspace_ukraine_regions WHERE scope='oblast' AND native_key=?", (oblast,)).fetchone()
        if exact:
            return exact['ref'], 'source_oblast_key'
        labels = self.db.execute("SELECT ref FROM workspace_ukraine_regions WHERE scope='oblast' AND label=?", (oblast,)).fetchall()
        return (labels[0]['ref'], 'source_oblast_name') if len(labels) == 1 else (None, None)

    def _region(self, scope, key, label, oblast=None, geometry=None, geometry_at=None):
        ref = region_ref(scope, key)
        previous = self.db.execute('SELECT * FROM workspace_ukraine_regions WHERE ref=?', (ref,)).fetchone()
        oblast = oblast or (previous['oblast'] if previous else None)
        parent, parent_basis = self._parent(oblast) if scope == 'raion' else (None, None)
        metadata = {'country': 'UA', 'scope': scope, 'native_key': key, 'oblast': oblast or (previous['oblast'] if previous else None),
                    'parent_ref': parent, 'parent_basis': parent_basis,
                    'source_name': 'NEPTUN', 'region_ref': ref}
        self.catalog.upsert({'ref': ref, 'type': 'ua_region', 'source_id': SOURCE_ID, 'native_id': key,
            'label': label, 'search_text': search_text(f'{label} {key} {oblast or ""} Ukraina Україна'),
            'date_precision': 'timeless', 'metadata_json': encode(metadata)}, [])
        self.db.execute('''INSERT INTO workspace_ukraine_regions(ref,scope,native_key,label,oblast,parent_ref,parent_basis,
            geometry_json,geometry_fetched_at,first_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ref) DO UPDATE SET label=excluded.label,oblast=COALESCE(excluded.oblast,oblast),
            parent_ref=excluded.parent_ref,parent_basis=excluded.parent_basis,geometry_json=COALESCE(excluded.geometry_json,geometry_json),
            geometry_fetched_at=COALESCE(excluded.geometry_fetched_at,geometry_fetched_at)''',
            (ref, scope, key, label, oblast, parent, parent_basis, encode(geometry) if geometry else None,
             geometry_at, iso(self._now())))
        return ref

    def register_geometry(self, payload):
        """Cache exact source keys and current polygons, including geometry-only regions."""
        with self.repo.lock, self.db:
            for scope, collection, field in (('oblast', 'oblasts', 'region'), ('raion', 'raions', 'rayon')):
                for feature in (payload.get(collection) or {}).get('features', []):
                    props = feature.get('properties') or {}
                    key, label = props.get('key'), props.get(field) or props.get('name')
                    geometry = feature.get('geometry')
                    if not key or not label or not geometry:
                        continue
                    self._region(scope, key, label, props.get('oblast'), geometry, payload.get('fetched_at'))
            # The provider names a parent by its exact label, while polygon keys differ.
            # Accept only a unique exact label or key; never infer from similar names.
            for row in self.db.execute("SELECT * FROM workspace_ukraine_regions WHERE scope='raion'").fetchall():
                parent, basis = self._parent(row['oblast'])
                if (parent, basis) != (row['parent_ref'], row['parent_basis']):
                    self._region(row['scope'], row['native_key'], row['label'], row['oblast'])

    def _project_episode(self, episode):
        region = self.db.execute('SELECT * FROM workspace_ukraine_regions WHERE ref=?', (episode['region_ref'],)).fetchone()
        metadata = {key: episode[key] for key in ('region_ref', 'first_seen_at', 'last_seen_at', 'source_since',
                    'source_updated_at', 'ended_after', 'ended_before', 'level')}
        metadata.update(country='UA', source_name='NEPTUN', active=bool(episode['active']),
                        scope=region['scope'], oblast=region['oblast'], parent_ref=region['parent_ref'],
                        reasons=json.loads(episode['reasons_json']))
        self.catalog.upsert({'ref': episode['ref'], 'type': 'civil_alert', 'source_id': SOURCE_ID,
            'native_id': episode['ref'].rsplit(':', 1)[-1], 'label': f'Alarm · {region["label"]}',
            'search_text': search_text(f'{region["label"]} {region["native_key"]} alarm Ukraina Україна'),
            'published_at': episode['first_seen_at'], 'updated_at': episode['last_seen_at'],
            'valid_from': episode['first_seen_at'], 'valid_until': episode['ended_before'],
            'metadata_json': encode(metadata)}, [])

    def ingest(self, snapshot, record=None):
        """Project a normalized alerts component; record only fresh complete snapshots."""
        now = self._now()
        with self.repo.lock, self.db:
            state = self._state()
            recording = bool(state['recording']) if record is None else bool(record)
            available = snapshot.get('status') == 'ready' and not snapshot.get('stale') and not snapshot.get('demo')
            try:
                fetched = moment(snapshot.get('fetched_at'))
                if fetched > now+timedelta(seconds=30):
                    available = False
            except (ValueError, TypeError):
                fetched = None
                available = False
            alerts = {}
            for item in snapshot.get('items', []):
                if not isinstance(item, dict):
                    continue
                try:
                    ref = self._region(item['scope'], item['key'], item['name'], item.get('oblast'))
                except (KeyError, ValueError, TypeError):
                    available = False
                    continue
                if item.get('level') not in ('red', 'yellow') or ref in alerts:
                    available = False
                alerts[ref] = item
            if not available:
                if recording:
                    self.mark_gap(snapshot.get('status') or 'invalid_snapshot')
                invalid_status = str(snapshot.get('status') or 'error')
                if invalid_status == 'ready':
                    invalid_status = 'partial'
                self.db.execute('''UPDATE workspace_ukraine_state SET status=?,gap_reason=?,updated_at=? WHERE id=1''',
                    (invalid_status, invalid_status, iso(now)))
                return self.status()
            if state['fetched_at'] and fetched < moment(state['fetched_at']):
                if recording:
                    self.mark_gap('out_of_order')
                return self.status()
            fetched_at = iso(fetched)
            updated = snapshot.get('updated_at')
            version = snapshot.get('source_version', snapshot.get('version'))
            version = str(version) if version is not None else None
            self.db.execute('''UPDATE workspace_ukraine_state SET status='ready',fetched_at=?,source_updated_at=?,
                source_version=?,last_successful_at=?,gap_reason=NULL,updated_at=? WHERE id=1''',
                (fetched_at, updated, version, fetched_at, iso(now)))
            for region in self.db.execute('SELECT ref FROM workspace_ukraine_regions').fetchall():
                item = alerts.get(region['ref'])
                self.db.execute('''UPDATE workspace_ukraine_regions SET current_state=?,source_since=?,
                    source_updated_at=?,fetched_at=? WHERE ref=?''',
                    (item['level'] if item else 'none', item.get('since') if item else None, updated, fetched_at, region['ref']))
            if not recording or (state['recording_since'] and fetched < moment(state['recording_since'])):
                return self.status()
            if self.db.execute("SELECT 1 FROM workspace_ukraine_runs WHERE status='ready' AND fetched_at=?", (fetched_at,)).fetchone():
                return self.status()
            run = self.db.execute('''INSERT INTO workspace_ukraine_runs(observed_at,fetched_at,recorded_at,status,
                source_updated_at,source_version) VALUES(?,?,?,'ready',?,?)''',
                (fetched_at, fetched_at, iso(now), updated, version)).lastrowid
            for region in self.db.execute('SELECT ref FROM workspace_ukraine_regions').fetchall():
                ref = region['ref']
                item = alerts.get(ref)
                current = self.db.execute('SELECT * FROM workspace_ukraine_episodes WHERE region_ref=? AND active=1', (ref,)).fetchone()
                ep_ref = None
                if item:
                    ep_ref = current['ref'] if current else f'civil_alert:neptun:{uuid.uuid4()}'
                    if current:
                        self.db.execute('''UPDATE workspace_ukraine_episodes SET last_seen_at=?,source_since=?,
                            source_updated_at=?,level=?,reasons_json=? WHERE ref=?''',
                            (fetched_at, item.get('since'), updated, item['level'], encode(item.get('reasons', [])), ep_ref))
                    else:
                        # Insert the parent catalogue row before the episode FK is materialized.
                        self.catalog.upsert({'ref': ep_ref, 'type': 'civil_alert', 'source_id': SOURCE_ID,
                            'native_id': ep_ref.rsplit(':', 1)[-1], 'label': 'Alarm', 'search_text': 'alarm'}, [])
                        self.db.execute('''INSERT INTO workspace_ukraine_episodes(ref,region_ref,first_seen_at,last_seen_at,
                            source_since,source_updated_at,level,reasons_json) VALUES(?,?,?,?,?,?,?,?)''',
                            (ep_ref, ref, fetched_at, fetched_at, item.get('since'), updated, item['level'], encode(item.get('reasons', []))))
                    self._project_episode(self.db.execute('SELECT * FROM workspace_ukraine_episodes WHERE ref=?', (ep_ref,)).fetchone())
                elif current:
                    self.db.execute('''UPDATE workspace_ukraine_episodes SET active=0,ended_after=last_seen_at,
                        ended_before=?,source_updated_at=? WHERE ref=?''', (fetched_at, updated, current['ref']))
                    self._project_episode(self.db.execute('SELECT * FROM workspace_ukraine_episodes WHERE ref=?', (current['ref'],)).fetchone())
                fields = (ep_ref, item['level'] if item else 'none', item.get('since') if item else None,
                          encode(item.get('reasons', [])) if item else '[]')
                previous = self.db.execute('''SELECT * FROM workspace_ukraine_observations WHERE region_ref=?
                    ORDER BY observed_at DESC,id DESC LIMIT 1''', (ref,)).fetchone()
                if not previous or tuple(previous[k] for k in ('episode_ref', 'state', 'source_since', 'reasons_json')) != fields:
                    self.db.execute('''INSERT INTO workspace_ukraine_observations(run_id,region_ref,episode_ref,
                        observed_at,state,source_since,source_updated_at,reasons_json) VALUES(?,?,?,?,?,?,?,?)''',
                        (run, ref, ep_ref, fetched_at, fields[1], fields[2], updated, fields[3]))
            self.db.execute('UPDATE workspace_ukraine_state SET last_recorded_at=? WHERE id=1', (fetched_at,))
            self._prune(now)
            return self.status()

    def prune(self):
        """Local maintenance, also used while recording is disabled or unavailable."""
        with self.repo.lock, self.db:
            self._prune(self._now())

    def _prune(self, now):
        """Keep one boundary observation per region and a preceding coverage run."""
        cutoff = iso(now-timedelta(days=RETENTION_DAYS))
        self.db.execute('''DELETE FROM workspace_ukraine_observations WHERE observed_at<? AND id NOT IN
            (SELECT o.id FROM workspace_ukraine_observations o WHERE o.observed_at<? AND NOT EXISTS
             (SELECT 1 FROM workspace_ukraine_observations newer WHERE newer.region_ref=o.region_ref
              AND newer.observed_at<? AND (newer.observed_at>o.observed_at OR (newer.observed_at=o.observed_at AND newer.id>o.id))))''',
            (cutoff, cutoff, cutoff))
        self.db.execute('''DELETE FROM workspace_ukraine_runs WHERE observed_at<? AND id NOT IN
            (SELECT run_id FROM workspace_ukraine_observations) AND id IS NOT
            (SELECT id FROM workspace_ukraine_runs WHERE observed_at<? ORDER BY observed_at DESC,id DESC LIMIT 1)''', (cutoff, cutoff))
        self.db.execute('''DELETE FROM catalog_objects WHERE type='civil_alert' AND ref IN
            (SELECT e.ref FROM workspace_ukraine_episodes e WHERE e.active=0 AND e.ended_before<?
            AND NOT EXISTS(SELECT 1 FROM workspace_ukraine_observations o WHERE o.episode_ref=e.ref))
            AND NOT EXISTS(SELECT 1 FROM workspace_watchlist w WHERE w.ref=catalog_objects.ref)''', (cutoff,))

    def regions(self):
        with self.repo.lock:
            result = []
            for row in self.db.execute('SELECT * FROM workspace_ukraine_regions ORDER BY scope,label,ref'):
                item = dict(row)
                raw_geometry = item.pop('geometry_json')
                item['geometry'] = json.loads(raw_geometry) if raw_geometry else None
                result.append(item)
            return result

    def _coverage(self, start, end):
        start = max(start, self._now()-timedelta(days=RETENTION_DAYS))
        if start >= end:
            return []
        preceding = self.db.execute('''SELECT id FROM workspace_ukraine_runs WHERE observed_at<=?
            ORDER BY observed_at DESC,id DESC LIMIT 1''', (iso(start),)).fetchone()
        rows = self.db.execute('''SELECT * FROM workspace_ukraine_runs WHERE (observed_at>=? AND observed_at<?)
            OR id=? ORDER BY observed_at,id''', (iso(start), iso(end), preceding['id'] if preceding else -1)).fetchall()
        result = []
        for index, row in enumerate(rows):
            if row['status'] != 'ready':
                continue
            at = moment(row['observed_at'])
            next_at = moment(rows[index+1]['observed_at']) if index+1 < len(rows) else min(end, self._now())
            stop = min(end, next_at, at+timedelta(seconds=MAX_GAP_SECONDS), self._now())
            at = max(start, at)
            if stop > at:
                if result and result[-1][1] == at:
                    result[-1] = (result[-1][0], stop)
                else:
                    result.append((at, stop))
        return result

    def _observations(self, ref, start, end):
        preceding = self.db.execute('''SELECT id FROM workspace_ukraine_observations WHERE region_ref=? AND observed_at<=?
            ORDER BY observed_at DESC,id DESC LIMIT 1''', (ref, iso(start))).fetchone()
        count = self.db.execute('''SELECT COUNT(*) FROM workspace_ukraine_observations
            WHERE region_ref=? AND ((observed_at>=? AND observed_at<?) OR id=?)''',
            (ref, iso(start), iso(end), preceding['id'] if preceding else -1)).fetchone()[0]
        if count > MAX_REGION_CHANGES:
            raise ValueError('Historia regionu przekracza limit 12000 zmian. Zawęź zakres czasu; dane nie są upraszczane.')
        return [dict(row) for row in self.db.execute('''SELECT o.*,r.fetched_at,r.recorded_at FROM workspace_ukraine_observations o
            JOIN workspace_ukraine_runs r ON r.id=o.run_id
            WHERE o.region_ref=? AND ((o.observed_at>=? AND o.observed_at<?) OR o.id=?) ORDER BY o.observed_at,o.id''',
            (ref, iso(start), iso(end), preceding['id'] if preceding else -1))]

    def _series(self, ref, start, end, coverage):
        region = self.db.execute('SELECT * FROM workspace_ukraine_regions WHERE ref=?', (ref,)).fetchone()
        if not region:
            raise KeyError(ref)
        observations = self._observations(ref, start, end)
        retained_start = max(start, self._now()-timedelta(days=RETENTION_DAYS))
        endings = [(moment(row['ended_after']), moment(row['ended_before']), row['ref'])
                   for row in self.db.execute('''SELECT ref,ended_after,ended_before FROM workspace_ukraine_episodes
                   WHERE region_ref=? AND ended_after<? AND ended_before>? ORDER BY ended_after,ended_before''', (ref, iso(end), iso(retained_start)))] if end > retained_start else []
        endings = [(max(a, retained_start), b, episode) for a, b, episode in endings]
        edges = {start, end}
        edges.update(max(start, moment(row['observed_at'])) for row in observations)
        for a, b in coverage:
            edges.update((a, b))
        for a, b, _ in endings:
            edges.update((max(start, a), min(end, b)))
        ordered = sorted(edges)
        segments, observed, ci, oi, ei = [], None, 0, 0, 0
        for a, b in pairwise(ordered):
            while oi < len(observations) and moment(observations[oi]['observed_at']) <= a:
                observed = observations[oi]
                oi += 1
            while ci < len(coverage) and coverage[ci][1] <= a:
                ci += 1
            known = ci < len(coverage) and coverage[ci][0] <= a < coverage[ci][1] and observed
            while ei < len(endings) and endings[ei][1] <= a:
                ei += 1
            uncertain_end = endings[ei][2] if ei < len(endings) and endings[ei][0] <= a < endings[ei][1] else None
            if uncertain_end:
                known = False
            segment = {'from': iso(a), 'to': iso(b), 'state': observed['state'] if known else 'unknown',
                       'episode_ref': observed['episode_ref'] if known else None,
                       'source_since': observed['source_since'] if known else None,
                       'source_updated_at': observed['source_updated_at'] if known else None,
                       'reason': 'end_uncertain' if uncertain_end else None}
            if uncertain_end:
                segment['episode_ref'] = uncertain_end
            if segments and all(segments[-1][k] == segment[k] for k in ('state', 'episode_ref', 'source_since', 'source_updated_at', 'reason')):
                segments[-1]['to'] = segment['to']
            else:
                segments.append(segment)
        covered = alarm = longest = streak = 0
        for segment in segments:
            seconds = (moment(segment['to'])-moment(segment['from'])).total_seconds()
            covered += seconds if segment['state'] != 'unknown' else 0
            if segment['state'] in ('red', 'yellow'):
                alarm += seconds
                streak += seconds
                longest = max(longest, streak)
            else:
                streak = 0
        episode_count = self.db.execute('''SELECT COUNT(*) FROM workspace_ukraine_episodes WHERE region_ref=?
            AND first_seen_at<? AND COALESCE(ended_before,?)>?''',
            (ref, iso(end), iso(self._now()), iso(retained_start))).fetchone()[0] if end > retained_start else 0
        duration = (end-start).total_seconds()
        return {'ref': ref, 'label': region['label'], 'scope': region['scope'], 'parent_ref': region['parent_ref'],
                'geometry': json.loads(region['geometry_json']) if region['geometry_json'] else None,
                'segments': segments, 'stats': {'episode_count': episode_count, 'alarm_seconds': alarm,
                    'longest_alarm_seconds': longest, 'covered_seconds': covered, 'unknown_seconds': duration-covered,
                    'coverage_ratio': covered/duration if duration else 0}}

    def replay(self, refs, start, end):
        start, end = moment(start), moment(end)
        if not 0 < (end-start).total_seconds() <= RETENTION_DAYS*86400:
            raise ValueError('Porównanie regionów wymaga zakresu do 30 dni')
        if not 1 <= len(refs) <= 5 or len(set(refs)) != len(refs):
            raise ValueError('Wybierz od jednego do pięciu różnych regionów')
        with self.repo.lock:
            coverage = self._coverage(start, end)
            return {'range': {'from': iso(start), 'to': iso(end)},
                    'series': [self._series(ref, start, end, coverage) for ref in refs],
                    'retention_days': RETENTION_DAYS, 'interpolation': False,
                    'geometry_context': 'current', 'source_url': SOURCE_URL}

    def present(self, item, now, interval, historical=False, cursor_at=None):
        with self.repo.lock:
            result = dict(item)
            ref = item['ref'] if item['type'] == 'ua_region' else item['metadata']['region_ref']
            region = self.db.execute('SELECT * FROM workspace_ukraine_regions WHERE ref=?', (ref,)).fetchone()
            status = self.status(now=now)
            result['geometry'] = json.loads(region['geometry_json']) if region and region['geometry_json'] else None
            result['geometry_context'] = 'current'
            result['watched'] = self.db.execute('SELECT 1 FROM workspace_watchlist WHERE ref=?', (item['ref'],)).fetchone() is not None
            result['region_ref'] = ref
            result['source_status'] = status['status']
            result['fetched_at'] = region['fetched_at'] if region else None
            result['provenance'] = {'attribution': 'NEPTUN', 'source_url': SOURCE_URL,
                'fetched_at': result['fetched_at'], 'source_updated_at': region['source_updated_at'] if region else None}
            value = region['current_state'] if region and status['status'] == 'ready' else 'unknown'
            episode_ref = None
            if historical or cursor_at:
                when = moment(cursor_at) if cursor_at else interval[1]-timedelta(microseconds=1)
                # A tiny exact slice gives the same half-open semantics as replay.
                series = self._series(ref, when, when+timedelta(microseconds=1), self._coverage(when, when+timedelta(microseconds=1)))
                sample = series['segments'][0]
                value, episode_ref = sample['state'], sample['episode_ref']
                if item['type'] == 'civil_alert' and episode_ref != item['ref']:
                    value = 'unknown' if value == 'unknown' else 'none'
            elif item['type'] == 'civil_alert':
                ep = self.db.execute('SELECT active,level,last_seen_at FROM workspace_ukraine_episodes WHERE ref=?', (item['ref'],)).fetchone()
                fresh_episode = ep and 0 <= (moment(now)-moment(ep['last_seen_at'])).total_seconds() <= LIVE_FRESH_SECONDS
                value = ep['level'] if (ep and ep['active'] and fresh_episode and status['status'] == 'ready'
                    and region and region['current_state'] == ep['level'] and region['fetched_at'] == ep['last_seen_at']) else 'none' if ep and not ep['active'] else 'unknown'
            result.update(state=value, alert_state=value, episode_ref=episode_ref,
                value_context='cursor' if cursor_at else 'period_overview' if historical else 'current',
                freshness='recorded' if historical or cursor_at else 'fresh' if value != 'unknown' else 'unknown_time')
            return result

    def timeline(self, ref, start, end):
        with self.repo.lock:
            item = self.catalog.object(ref)
            if not item or item['type'] not in ('ua_region', 'civil_alert'):
                raise KeyError(ref)
            region = ref if item['type'] == 'ua_region' else item['metadata']['region_ref']
            rows = self._observations(region, moment(start), moment(end))
            ended = item['metadata'].get('ended_before')
            retained_start = max(moment(start), self._now()-timedelta(days=RETENTION_DAYS))
            rows = [r for r in rows if moment(r['observed_at']) >= retained_start and
                    (item['type'] == 'ua_region' or r['episode_ref'] == ref or (r['state'] == 'none' and r['observed_at'] == ended))]
            events = [dict(r, at=r['observed_at'], kind='civil_alert', ref=r['episode_ref'] or region,
                           reasons=json.loads(r['reasons_json'])) for r in rows]
            return {'items': events, 'total': len(events), 'truncated': False, 'retention_days': RETENTION_DAYS}

    def detail(self, ref, start, end, cursor_at=None):
        with self.repo.lock:
            item = self.catalog.object(ref)
            if not item or item['type'] not in ('ua_region', 'civil_alert'):
                raise KeyError(ref)
            region = ref if item['type'] == 'ua_region' else item['metadata']['region_ref']
            retained_start = max(moment(start), self._now()-timedelta(days=RETENTION_DAYS))
            episodes = [dict(row) for row in self.db.execute('''SELECT * FROM workspace_ukraine_episodes
                WHERE region_ref=? AND first_seen_at<? AND (ended_before IS NULL OR ended_before>?)
                ORDER BY first_seen_at DESC''', (region, iso(moment(end)), iso(retained_start)))] if moment(end) > retained_start else []
            for episode in episodes:
                episode['active'] = bool(episode['active'])
                episode['reasons'] = json.loads(episode.pop('reasons_json'))
            series = self.replay([region], start, end)['series'][0]
            return {'region_ref': region, 'episodes': episodes,
                    'revisions': self.timeline(ref, start, end)['items'], 'stats': series['stats'],
                    'segments': series['segments'], 'retention_days': RETENTION_DAYS,
                    'status': self.status(), 'cursor_at': iso(moment(cursor_at)) if cursor_at else None}

    def revision_token(self, start=None, end=None):
        with self.repo.lock:
            regions = [tuple(row) for row in self.db.execute('''SELECT ref,parent_ref,geometry_fetched_at,geometry_json
                FROM workspace_ukraine_regions ORDER BY ref''')]
            if start is None or end is None:
                state = self._state()
                runs = self.db.execute('SELECT COUNT(*),MAX(id) FROM workspace_ukraine_runs').fetchone()
                observations = self.db.execute('SELECT COUNT(*),MAX(id) FROM workspace_ukraine_observations').fetchone()
                history = [state, tuple(runs), tuple(observations)]
            else:
                start, end = moment(start), moment(end)
                bounds = (iso(start), iso(end))
                # A later poll must not expire a completed historical query. Runs
                # establish coverage, while sparse observations carry state into
                # the window: both need their immediate predecessor as well.
                preceding_run = self.db.execute('''SELECT id FROM workspace_ukraine_runs
                    WHERE observed_at<? ORDER BY observed_at DESC,id DESC LIMIT 1''', (bounds[0],)).fetchone()
                runs = self.db.execute('''SELECT COUNT(*),MAX(id) FROM workspace_ukraine_runs
                    WHERE observed_at>=? AND observed_at<?''', bounds).fetchone()
                observations = self.db.execute('''SELECT COUNT(*),MAX(id) FROM workspace_ukraine_observations
                    WHERE observed_at>=? AND observed_at<?''', bounds).fetchone()
                preceding_states = [tuple(row) for row in self.db.execute('''SELECT r.ref,
                    (SELECT o.id FROM workspace_ukraine_observations o WHERE o.region_ref=r.ref AND o.observed_at<?
                     ORDER BY o.observed_at DESC,o.id DESC LIMIT 1)
                    FROM workspace_ukraine_regions r ORDER BY r.ref''', (bounds[0],))]
                # A later all-clear can change an earlier interval into an
                # uncertain ending. Include only the part affecting this window,
                # not mutable live metadata such as the episode's last_seen_at.
                endings = [(row['ref'], iso(max(start, moment(row['ended_after']))),
                            iso(min(end, moment(row['ended_before']))))
                           for row in self.db.execute('''SELECT ref,ended_after,ended_before
                           FROM workspace_ukraine_episodes WHERE ended_after<? AND ended_before>?
                           ORDER BY ref''', (bounds[1], bounds[0]))]
                # Retained boundary rows can outlive their visible history without
                # changing these counts. Expiry must still invalidate the window.
                retained_start = min(end, max(start, self._now()-timedelta(days=RETENTION_DAYS)))
                history = [iso(retained_start), preceding_run['id'] if preceding_run else None, tuple(runs), tuple(observations),
                           preceding_states, endings]
            return hashlib.sha256(encode([history, regions]).encode()).hexdigest()[:24]
