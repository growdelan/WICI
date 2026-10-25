"""Local, typed relationship exploration; no network reads or inferred causality."""
import hashlib
import json
import secrets
import uuid
from datetime import UTC, timedelta
from types import SimpleNamespace

from wici.communications import communication
from wici.geo import provinces_for_point, units
from wici.relation_models import AnalystRelation, GraphNeighbors, GraphQuery, WorkingGraph
from wici.tracking import MAX_AGE, timestamp
from wici.workspace_repository import encode, iso
from wici.workspace_service import QueryChanged, parse_time

MAX_CANDIDATES = 5000
MAX_RELATIONS = 500
MAX_EDGES = 500


class WorkspaceRelations:
    def __init__(self, workspace):
        self.workspace, self.repo, self.db = workspace, workspace.repo, workspace.db
        self.secret = secrets.token_bytes(32)
        self.epoch = secrets.token_hex(8)
        self._stamp = None
        self._source_revision = None
        self._raw_cache = {}
        self._node_cache = {}
        self._out_cache = {}

    def _begin_read(self):
        self._raw_cache, self._node_cache, self._out_cache = {}, {}, {}
        self._moving_status = None

    def _raw(self, ref):
        if ref not in self._raw_cache:
            self._raw_cache[ref] = self.workspace.catalog.object(ref)
        return self._raw_cache[ref]

    def _position(self, item, query, now):
        if query.time.mode == 'range' or query.cursor_at:
            return self.workspace.moving.point_at(item['ref'], *self._interval(query, now), query.cursor_at)
        if self._moving_status is None:
            self._moving_status = {row['resource']: dict(row) for row in self.db.execute('SELECT * FROM workspace_moving_sources')}
        source = self._moving_status.get(item['source_id'])
        point = item['metadata'].get('last_known_position')
        when = timestamp(point.get('position_at')) if point else None
        if (source and source['status'] == 'ready' and not source['stale'] and when is not None
                and item['metadata'].get('live_present') and 0 <= (now-when).total_seconds() <= MAX_AGE[item['type']]):
            return point
        return None

    def _dossier(self, dossier_id):
        return self.workspace.dossiers._row(dossier_id)

    def _interval(self, query, now):
        value = query.time.filter_range
        return (value.start, value.end) if value else (now-timedelta(days=14), now+timedelta(microseconds=1))

    def _revision(self, query, now):
        stamp = (self.db.total_changes, self.db.execute('PRAGMA data_version').fetchone()[0])
        if stamp != self._stamp:
            digest = hashlib.sha256()
            # Every source writer shares this connection. Cache invalidation is
            # broad, but note edits do not alter the resulting source revision.
            statements = (
                'SELECT ref,revision,metadata_json FROM catalog_objects ORDER BY ref',
                'SELECT * FROM catalog_object_areas ORDER BY ref,admin_code,role',
                'SELECT * FROM workspace_moving_sources ORDER BY resource',
                'SELECT id,kind,object_id,active,status FROM object_tracks ORDER BY id',
                'SELECT count(*),max(rowid),max(position_at),max(recorded_at) FROM object_track_points',
                'SELECT count(*),max(id),sum(revision) FROM station_measurements',
                'SELECT count(*),max(id),sum(revision) FROM station_index_observations',
                'SELECT * FROM workspace_ukraine_regions ORDER BY ref',
                'SELECT * FROM workspace_ukraine_episodes ORDER BY ref',
                'SELECT count(*),max(id),max(observed_at) FROM workspace_ukraine_observations',
                'SELECT count(*),max(id),max(observed_at) FROM workspace_ukraine_runs',
                'SELECT * FROM workspace_ukraine_state',
            )
            for sql in statements:
                for row in self.db.execute(sql):
                    digest.update(encode(list(row)).encode())
            self._source_revision, self._stamp = digest.hexdigest(), stamp
        local = []
        if query.dossier_id:
            self._dossier(query.dossier_id)
            local = [list(row) for row in self.db.execute(
                'SELECT id,revision,deleted FROM workspace_relations WHERE dossier_id=? ORDER BY id', (query.dossier_id,))]
            # Deleted evidence is visible in the graph inspector and changes its revision.
            local += [list(row) for row in self.db.execute('''SELECT r.id,
                (SELECT revision FROM workspace_dossier_notes n WHERE n.id=r.note_id AND n.dossier_id=r.dossier_id),
                EXISTS(SELECT 1 FROM workspace_dossier_materials m WHERE m.id=r.material_id AND m.dossier_id=r.dossier_id)
                FROM workspace_relations r WHERE r.dossier_id=? ORDER BY r.id''', (query.dossier_id,))]
        clock_context = {'time': query.time.model_dump(mode='json', by_alias=True),
                         'cursor_at': iso(query.cursor_at) if query.cursor_at else None,
                         'version_ids': query.version_ids, 'as_of': iso(now)}
        return hashlib.sha256(encode([self.epoch, self._source_revision, local, clock_context]).encode()).hexdigest()

    def _prepare(self, raw):
        query = GraphQuery.model_validate(raw)
        now = query.as_of or self.repo.clock().astimezone(UTC)
        query.as_of = now
        revision = self._revision(query, now)
        if query.expected_revision and query.expected_revision != revision:
            raise QueryChanged('Graf zmienił się; odśwież graf przed dalszą eksploracją lub zapisem')
        return query, now, revision

    def _document(self, item, query, now):
        version_id = query.version_ids.get(item['ref'], item['document_version_id'])
        row = self.db.execute('''SELECT v.*,d.url,d.source_id,d.first_seen_at,d.last_checked_at,s.name source_name
            FROM document_versions v JOIN documents d ON d.id=v.document_id JOIN sources s ON s.id=d.source_id
            WHERE v.id=? AND v.document_id=?''', (version_id, item['document_id'])).fetchone()
        if row is None:
            raise KeyError(version_id)
        fields = json.loads(row['fields_json'])
        if fields.get('access_allowed') is not True or fields.get('contract_validated') is not True:
            raise ValueError('Wersja komunikatu nie jest dopuszczona do katalogu')
        value = communication({k: v for k, v in dict(row).items() if k != 'fields_json'}, fields, now)
        return value, version_id

    def _node(self, ref, query, now):
        if ref not in self._node_cache:
            self._node_cache[ref] = self._read_node(ref, query, now)
        return self._node_cache[ref]

    def _read_node(self, ref, query, now):
        item = self._raw(ref)
        if item is None:
            saved = None
            if query.dossier_id:
                saved = self.db.execute('''SELECT source_label label,source_type type FROM workspace_relations
                    WHERE dossier_id=? AND source_ref=? UNION ALL
                    SELECT target_label,target_type FROM workspace_relations WHERE dossier_id=? AND target_ref=? LIMIT 1''',
                    (query.dossier_id, ref, query.dossier_id, ref)).fetchone()
                if saved is None:
                    saved = self.db.execute('SELECT label,type FROM workspace_dossier_pins WHERE dossier_id=? AND ref=?',
                                            (query.dossier_id, ref)).fetchone()
            return {'ref': ref, 'label': saved['label'] if saved else ref,
                    'type': saved['type'] if saved else ref.split(':')[0], 'available': False,
                    'availability': 'unavailable', 'metadata': {}, 'areas': [], 'latitude': None, 'longitude': None}
        interval = self._interval(query, now)
        if item['type'] in ('aircraft', 'ship'):
            node = self.workspace.moving.present(item, now, interval,
                historical=query.time.mode == 'range', cursor_at=query.cursor_at)
        elif item['type'] in ('ua_region', 'civil_alert'):
            node = self.workspace.ukraine.present(item, now, interval,
                historical=query.time.mode == 'range', cursor_at=query.cursor_at)
        else:
            node = self.workspace._present(item, now, interval, SimpleNamespace(time=query.time))
            if item['type'].endswith('_station') and query.cursor_at:
                node['measurement'] = self.workspace._sample(ref, *interval, query.cursor_at)
                node['value_context'] = 'cursor'
                index = self.db.execute('''SELECT * FROM station_index_observations WHERE object_ref=?
                    AND quality='valid' AND observed_at>=? AND observed_at<? AND observed_at<=?
                    ORDER BY observed_at DESC,revision DESC LIMIT 1''',
                    (ref, iso(interval[0]), iso(interval[1]), iso(query.cursor_at))).fetchone()
                node['official_index'] = self.workspace._observation(index) if index else None
        if item['type'] == 'communication':
            document, version_id = self._document(item, query, now)
            node.update(label=document['title'], document_version_id=version_id,
                communication={key: document.get(key) for key in ('title', 'text', 'source_published_at',
                    'source_updated_at', 'source_published_date', 'original_url', 'locations', 'valid_from', 'valid_until')},
                metadata_context='selected_document_version' if ref in query.version_ids else 'current')
            node.update(published_at=document.get('source_published_at') or document.get('source_published_date'),
                updated_at=document.get('source_updated_at'), valid_from=document.get('valid_from'),
                valid_until=document.get('valid_until'), warning_status=document.get('warning_status'),
                date_precision='instant' if document.get('source_published_at') else
                    'day' if document.get('source_published_date') else 'unknown',
                areas=[{'admin_code': loc['admin_code'], 'role': loc['role'], 'basis': loc.get('source')}
                       for loc in document['locations']])
            node['metadata'] = dict(node['metadata'], version_number=document.get('version_number'),
                original_url=document['original_url'], source_published_date=document.get('source_published_date'),
                source_warning_status=document['fields'].get('event', {}).get('warning_status', 'unknown'))
        node['available'] = True
        return node

    @staticmethod
    def _edge(source, target, kind, label, category, provenance, time=None, identity=None, directed=True):
        return {'id': identity or hashlib.sha256(encode([source, target, kind, provenance]).encode()).hexdigest()[:32],
                'source_ref': source, 'target_ref': target, 'type': kind, 'label': label,
                'category': category, 'directed': directed, 'provenance': provenance,
                'time': time or {'kind': 'current_metadata'}}

    def _outgoing(self, ref, query, now):
        if ref not in self._out_cache:
            self._out_cache[ref] = self._read_outgoing(ref, query, now)
        return self._out_cache[ref]

    def _read_outgoing(self, ref, query, now):
        item = self._raw(ref)
        edges = []
        if item:
            typ = item['type']
            if typ == 'communication':
                document, version_id = self._document(item, query, now)
                for loc in document['locations']:
                    role = loc['role']
                    edges.append(self._edge(ref, 'area:prg:'+loc['admin_code'], 'communication_area',
                        'Obszar ostrzeżenia' if role == 'warning_area' else 'Obszar powiadomienia', 'source',
                        {'source_id': item['source_id'], 'source_url': document['original_url'],
                         'document_version_id': version_id, 'role': role, 'basis': loc.get('source')},
                        {'kind': 'source_version', 'valid_from': document.get('valid_from'),
                         'valid_until': document.get('valid_until'), 'source_published_at': document.get('source_published_at'),
                         'source_published_date': document.get('source_published_date')}))
            elif typ.endswith('_station'):
                for area in item['areas']:
                    basis = area['basis']
                    derived = 'Położenie punktu' in basis
                    edges.append(self._edge(ref, 'area:prg:'+area['admin_code'], 'station_area',
                        'Lokalizacja stacji', 'derived' if derived else 'source',
                        {'source_id': item['source_id'], 'basis': basis, 'role': area['role'],
                         'method': 'point_in_prg' if derived else 'source_administrative_code',
                         'source_url': item['metadata'].get('source_url'), 'geometry_context': 'current'}))
            elif typ == 'area' and len(item['native_id']) == 4 and item['native_id'][:2] in units():
                edges.append(self._edge(ref, 'area:prg:'+item['native_id'][:2], 'administrative_parent',
                    'Należy do województwa', 'source', {'source_id': 'prg', 'basis': 'Hierarchia kodów lokalnego zbioru PRG'}))
            elif typ == 'ua_region':
                parent = item['metadata'].get('parent_ref')
                if parent:
                    edges.append(self._edge(ref, parent, 'region_parent', 'Należy do obwodu', 'source',
                        {'source_id': 'ukraine_alerts', 'source_url': 'https://neptun.in.ua/',
                         'basis': item['metadata'].get('parent_basis'), 'geometry_context': 'current'}))
            elif typ == 'civil_alert':
                meta = item['metadata']
                start, end = self._interval(query, now)
                active = True
                if query.time.mode == 'range':
                    active = (parse_time(meta['first_seen_at']) < end and
                              (not meta.get('ended_before') or parse_time(meta['ended_before']) > start))
                    if query.cursor_at:
                        active = (parse_time(meta['first_seen_at']) <= query.cursor_at and
                                  (not meta.get('ended_before') or query.cursor_at < parse_time(meta['ended_before'])))
                if active:
                    edges.append(self._edge(ref, meta['region_ref'], 'alert_region', 'Epizod dotyczy regionu', 'source',
                        {'source_id': 'ukraine_alerts', 'source_url': 'https://neptun.in.ua/', 'basis': 'Identyfikator regionu zapisanego epizodu'},
                        dict(kind='interval', **{key: meta.get(key) for key in ('first_seen_at', 'last_seen_at',
                            'source_since', 'ended_after', 'ended_before')})))
            elif typ in ('aircraft', 'ship'):
                point = self._position(item, query, now)
                if point:
                    for code in provinces_for_point(point['longitude'], point['latitude']):
                        edges.append(self._edge(ref, 'area:prg:'+code, 'reported_in_area',
                            'Raport pozycji w obszarze', 'derived',
                            {'source_id': item['source_id'], 'source_url': 'https://adsb.fi/' if typ == 'aircraft' else 'https://aisstream.io/',
                             'method': 'reported_point_in_prg', 'geometry_context': 'current',
                             'track_id': point.get('track_id'), 'latitude': point['latitude'], 'longitude': point['longitude']},
                            {'kind': 'observation', 'observed_at': point['position_at']}))
        if query.dossier_id and self._allowed(query, 'analyst_related', 'analyst'):
            rows = self.db.execute('''SELECT * FROM workspace_relations WHERE dossier_id=? AND deleted=0
                AND (source_ref=? OR target_ref=?) ORDER BY id''', (query.dossier_id, ref, ref))
            for row in rows:
                value = self._relation(row)
                edges.append(self._edge(value['source_ref'], value['target_ref'], 'analyst_related',
                    'Powiązanie analityczne', 'analyst',
                    {key: value[key] for key in ('id', 'dossier_id', 'justification', 'note_id', 'material_id',
                        'evidence_missing', 'evidence', 'revision', 'created_at', 'updated_at')},
                    {'kind': 'analyst_assertion'}, identity=value['id'], directed=False))
        return [edge for edge in edges if (not query.relation_types or edge['type'] in query.relation_types)
                and (not query.categories or edge['category'] in query.categories)]

    @staticmethod
    def _allowed(query, typ, category=None):
        return ((not query.relation_types or typ in query.relation_types)
                and (category is None or not query.categories or category in query.categories))

    def _area_adjacent(self, ref, query, now):
        """Read high-degree area links with joins, not one full card per neighbor."""
        code = ref.split(':')[-1]
        edges = list(self._outgoing(ref, query, now))
        types = []
        if self._allowed(query, 'communication_area', 'source'):
            types.append('communication')
        if self._allowed(query, 'station_area') and (not query.categories or {'source', 'derived'} & set(query.categories)):
            types.extend(['hydro_station', 'air_quality_station'])
        if types:
            rows = self.db.execute(f'''SELECT o.ref,o.type,o.source_id,o.document_version_id,
                o.metadata_json,o.valid_from,o.valid_until,a.role,a.basis,v.source_published_at
                FROM catalog_object_areas a JOIN catalog_objects o ON o.ref=a.ref
                LEFT JOIN document_versions v ON v.id=o.document_version_id
                WHERE a.admin_code=? AND o.type IN ({','.join('?' for _ in types)}) LIMIT ?''',
                (code, *types, MAX_CANDIDATES+1)).fetchall()
            if len(rows) > MAX_CANDIDATES:
                raise ValueError('Otoczenie przekracza 5000 kandydatów. Wybierz bardziej szczegółowy obiekt.')
            for row in rows:
                if row['ref'] in query.version_ids:
                    # The selected document version, not the current projection,
                    # decides whether this edge belongs to this area.
                    continue
                meta = json.loads(row['metadata_json'])
                if row['type'] == 'communication':
                    edges.append(self._edge(row['ref'], ref, 'communication_area',
                        'Obszar ostrzeżenia' if row['role'] == 'warning_area' else 'Obszar powiadomienia', 'source',
                        {'source_id': row['source_id'], 'source_url': meta.get('original_url'),
                         'document_version_id': row['document_version_id'], 'role': row['role'], 'basis': row['basis']},
                        {'kind': 'source_version', 'valid_from': row['valid_from'], 'valid_until': row['valid_until'],
                         'source_published_at': row['source_published_at'], 'source_published_date': meta.get('source_published_date')}))
                else:
                    derived = 'Położenie punktu' in row['basis']
                    category = 'derived' if derived else 'source'
                    if self._allowed(query, 'station_area', category):
                        edges.append(self._edge(row['ref'], ref, 'station_area', 'Lokalizacja stacji', category,
                            {'source_id': row['source_id'], 'basis': row['basis'], 'role': row['role'],
                             'method': 'point_in_prg' if derived else 'source_administrative_code',
                             'source_url': meta.get('source_url'), 'geometry_context': 'current'}))
            for selected in query.version_ids:
                edges.extend(edge for edge in self._outgoing(selected, query, now) if edge['target_ref'] == ref)
        if len(code) == 2 and self._allowed(query, 'administrative_parent', 'source'):
            for row in self.db.execute("SELECT ref FROM catalog_objects WHERE type='area' AND native_id LIKE ?", (code+'__',)):
                edges.append(self._edge(row['ref'], ref, 'administrative_parent', 'Należy do województwa', 'source',
                    {'source_id': 'prg', 'basis': 'Hierarchia kodów lokalnego zbioru PRG'}))
        if len(code) == 2 and self._allowed(query, 'reported_in_area', 'derived'):
            if query.time.mode == 'live':
                rows = self.db.execute('''SELECT o.* FROM catalog_objects o JOIN catalog_object_areas a ON a.ref=o.ref
                    WHERE a.admin_code=? AND o.type IN ('aircraft','ship') LIMIT ?''', (code, MAX_CANDIDATES+1)).fetchall()
            else:
                rows = self.db.execute("SELECT * FROM catalog_objects WHERE type IN ('aircraft','ship') LIMIT ?",
                                       (MAX_CANDIDATES+1,)).fetchall()
            if len(rows) > MAX_CANDIDATES:
                raise ValueError('Otoczenie przekracza 5000 kandydatów. Wybierz bardziej szczegółowy obiekt.')
            for row in rows:
                if row['ref'] not in self._raw_cache:
                    item = dict(row)
                    item['metadata'] = json.loads(item.pop('metadata_json'))
                    item.pop('search_text', None)
                    item['areas'] = []
                    self._raw_cache[item['ref']] = item
                edges.extend(edge for edge in self._outgoing(row['ref'], query, now) if edge['target_ref'] == ref)
        if len({edge['source_ref'] if edge['target_ref'] == ref else edge['target_ref'] for edge in edges}) > MAX_CANDIDATES:
            raise ValueError('Otoczenie przekracza 5000 kandydatów. Wybierz bardziej szczegółowy obiekt.')
        return edges

    def _candidates(self, ref, query):
        refs = {ref}
        if ref.startswith('ua_region:'):
            if self._allowed(query, 'region_parent', 'source'):
                refs.update(row[0] for row in self.db.execute(
                    'SELECT ref FROM workspace_ukraine_regions WHERE parent_ref=? LIMIT ?', (ref, MAX_CANDIDATES+1)))
            if self._allowed(query, 'alert_region', 'source'):
                refs.update(row[0] for row in self.db.execute(
                    'SELECT ref FROM workspace_ukraine_episodes WHERE region_ref=? LIMIT ?', (ref, MAX_CANDIDATES+1)))
        if query.dossier_id and self._allowed(query, 'analyst_related', 'analyst'):
            for row in self.db.execute('''SELECT source_ref,target_ref FROM workspace_relations
                WHERE dossier_id=? AND deleted=0 AND (source_ref=? OR target_ref=?)''', (query.dossier_id, ref, ref)):
                refs.update(row)
        if len(refs) > MAX_CANDIDATES:
            raise ValueError('Otoczenie przekracza 5000 kandydatów. Wybierz bardziej szczegółowy obiekt.')
        return refs

    def _adjacent(self, ref, query, now):
        if ref.startswith('area:prg:'):
            return list({edge['id']: edge for edge in self._area_adjacent(ref, query, now)}.values())
        edges = {}
        candidates = sorted(self._candidates(ref, query))
        # Ukraine links use metadata only; batch-load it before traversing a
        # region's many episodes rather than issuing two reads per episode.
        if ref.startswith('ua_region:') and candidates:
            missing = [value for value in candidates if value not in self._raw_cache]
            if missing:
                for row in self.db.execute(f"SELECT * FROM catalog_objects WHERE ref IN ({','.join('?' for _ in missing)})", missing):
                    item = dict(row)
                    item['metadata'] = json.loads(item.pop('metadata_json'))
                    item.pop('search_text', None)
                    item['areas'] = []
                    self._raw_cache[item['ref']] = item
        for candidate in candidates:
            for edge in self._outgoing(candidate, query, now):
                if ref in (edge['source_ref'], edge['target_ref']) and edge['source_ref'] != edge['target_ref']:
                    edges[edge['id']] = edge
        return list(edges.values())

    def query(self, raw):
        with self.repo.lock:
            self._begin_read()
            query, now, revision = self._prepare(raw)
            nodes = [self._node(ref, query, now) for ref in query.node_refs]
            visible, edges, counts = set(query.node_refs), {}, {}
            for ref in query.node_refs:
                adjacent = self._adjacent(ref, query, now)
                neighbors = {edge['target_ref'] if edge['source_ref'] == ref else edge['source_ref'] for edge in adjacent}
                shown = len(neighbors & visible)
                counts[ref] = {'total': len(neighbors), 'shown': shown, 'remaining': len(neighbors)-shown}
                for edge in adjacent:
                    if {edge['source_ref'], edge['target_ref']}.issubset(visible):
                        edges[edge['id']] = edge
            ordered = sorted(edges.values(), key=lambda edge: edge['id'])
            edge_limited = len(ordered) > MAX_EDGES
            ordered = ordered[:MAX_EDGES]
            selector = query.model_dump(mode='json', by_alias=True)
            selector['expected_revision'] = revision
            return {'nodes': nodes, 'edges': ordered, 'revision': revision, 'as_of': iso(now), 'selector': selector,
                'neighbor_counts': counts, 'partial': edge_limited or any(v['remaining'] for v in counts.values()),
                'edge_total': len(edges), 'edge_limit_reached': edge_limited,
                'limits': {'max_seeds': 20, 'max_nodes': 200, 'max_edges': MAX_EDGES, 'neighbor_page_size': 50},
                'notice': 'Graf jest eksplorowanym fragmentem danych. Wspólny obszar nie dowodzi związku przyczynowego.'}

    def neighbors(self, raw):
        body = GraphNeighbors.model_validate(raw)
        with self.repo.lock:
            self._begin_read()
            query, now, revision = self._prepare(body.graph)
            grouped = {}
            for edge in self._adjacent(body.ref, query, now):
                other = edge['target_ref'] if edge['source_ref'] == body.ref else edge['source_ref']
                grouped.setdefault(other, []).append(edge)
            refs = sorted(grouped)
            fingerprint = hashlib.sha256(encode([body.ref, query.model_dump(mode='json',
                exclude={'expected_revision', 'node_refs', 'expanded_refs', 'seed_refs'})]).encode()).hexdigest()
            offset = 0
            if body.cursor:
                cursor = self.workspace._decode_cursor(body.cursor)
                if cursor.get('graph_revision') != revision or cursor.get('fingerprint') != fingerprint:
                    raise QueryChanged('Strony otoczenia zmieniły się; odśwież graf')
                offset = cursor['offset']
            selected = refs[offset:offset+body.limit]
            next_cursor = self.workspace._encode_cursor({'graph_revision': revision, 'fingerprint': fingerprint,
                'offset': offset+body.limit}) if offset+body.limit < len(refs) else None
            return {'items': [{'node': self._node(ref, query, now), 'edges': grouped[ref]} for ref in selected],
                    'total': len(refs), 'next_cursor': next_cursor, 'revision': revision, 'as_of': iso(now)}

    def _relation(self, row):
        value = dict(row)
        value['deleted'] = bool(value['deleted'])
        missing, evidence = [], {}
        for key, table in (('note_id', 'workspace_dossier_notes'), ('material_id', 'workspace_dossier_materials')):
            if value[key]:
                columns = 'id,body,revision,updated_at' if key == 'note_id' else 'id,title,kind,sha256,captured_at'
                row = self.db.execute(f'SELECT {columns} FROM {table} WHERE id=? AND dossier_id=?',
                                      (value[key], value['dossier_id'])).fetchone()
                if row:
                    evidence[key] = dict(row)
                else:
                    missing.append(key)
        value['evidence_missing'] = missing
        value['evidence'] = evidence
        return value

    def relations(self, dossier_id, include_deleted=False):
        with self.repo.lock:
            self._dossier(dossier_id)
            return {'items': [self._relation(row) for row in self.db.execute(
                'SELECT * FROM workspace_relations WHERE dossier_id=?'+('' if include_deleted else ' AND deleted=0')+
                ' ORDER BY created_at,id', (dossier_id,))]}

    def _audit(self, relation_id, action):
        row = self.db.execute('SELECT * FROM workspace_relations WHERE id=?', (relation_id,)).fetchone()
        self.db.execute('INSERT INTO workspace_relation_revisions VALUES(?,?,?,?,?)',
            (relation_id, row['revision'], action, encode(self._relation(row)), iso(self.repo.clock())))

    def save_relation(self, dossier_id, raw, relation_id=None):
        value = AnalystRelation.model_validate(raw)
        with self.repo.lock, self.db:
            self._dossier(dossier_id)
            refs = sorted((value.source_ref, value.target_ref))
            previous = None
            if relation_id:
                previous = self.db.execute('SELECT * FROM workspace_relations WHERE dossier_id=? AND id=? AND deleted=0',
                                           (dossier_id, relation_id)).fetchone()
                if previous is None:
                    raise KeyError(relation_id)
                if value.revision != previous['revision']:
                    raise QueryChanged('Relacja została zmieniona; wczytaj aktualną wersję')
            else:
                count = self.db.execute('SELECT count(*) FROM workspace_relations WHERE dossier_id=? AND deleted=0', (dossier_id,)).fetchone()[0]
                if count >= MAX_RELATIONS:
                    raise ValueError('Teczka ma już 500 relacji analitycznych')
            duplicate = self.db.execute('''SELECT id FROM workspace_relations WHERE dossier_id=?
                AND source_ref=? AND target_ref=? AND deleted=0 AND id!=?''', (dossier_id, *refs, relation_id or '')).fetchone()
            if duplicate:
                raise ValueError('Te obiekty mają już relację analityczną w tej teczce')
            endpoints = []
            for ref in refs:
                obj = self.workspace.catalog.object(ref)
                if obj is None and previous and ref in (previous['source_ref'], previous['target_ref']):
                    prefix = 'source' if ref == previous['source_ref'] else 'target'
                    obj = {'label': previous[prefix+'_label'], 'type': previous[prefix+'_type']}
                if obj is None:
                    raise KeyError(ref)
                endpoints.append(obj)
            for key, table in (('note_id', 'workspace_dossier_notes'), ('material_id', 'workspace_dossier_materials')):
                identity = getattr(value, key)
                if identity and not self.db.execute(f'SELECT 1 FROM {table} WHERE id=? AND dossier_id=?', (identity, dossier_id)).fetchone():
                    raise ValueError('Dowód musi należeć do tej teczki i nadal być dostępny')
            now = iso(self.repo.clock())
            if previous:
                self.db.execute('''UPDATE workspace_relations SET source_ref=?,target_ref=?,source_label=?,target_label=?,
                    source_type=?,target_type=?,justification=?,note_id=?,material_id=?,revision=revision+1,updated_at=? WHERE id=?''',
                    (*refs, *(obj['label'] for obj in endpoints), *(obj['type'] for obj in endpoints),
                     value.justification, value.note_id, value.material_id, now, relation_id))
            else:
                relation_id = str(uuid.uuid4())
                self.db.execute('INSERT INTO workspace_relations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (relation_id, dossier_id, *refs, *(obj['label'] for obj in endpoints), *(obj['type'] for obj in endpoints),
                     value.justification, value.note_id, value.material_id, 1, 0, now, now))
            self._audit(relation_id, 'update' if previous else 'create')
            self.workspace.dossiers._touch(dossier_id)
            return self._relation(self.db.execute('SELECT * FROM workspace_relations WHERE id=?', (relation_id,)).fetchone())

    def delete_relation(self, dossier_id, relation_id, revision):
        with self.repo.lock, self.db:
            self._dossier(dossier_id)
            row = self.db.execute('SELECT * FROM workspace_relations WHERE dossier_id=? AND id=? AND deleted=0', (dossier_id, relation_id)).fetchone()
            if row is None:
                raise KeyError(relation_id)
            if row['revision'] != revision:
                raise QueryChanged('Relacja została zmieniona; wczytaj aktualną wersję')
            self.db.execute('UPDATE workspace_relations SET deleted=1,revision=revision+1,updated_at=? WHERE id=?',
                            (iso(self.repo.clock()), relation_id))
            self._audit(relation_id, 'delete')
            self.workspace.dossiers._touch(dossier_id)
            return {'deleted': True}

    def relation_history(self, dossier_id, relation_id):
        with self.repo.lock:
            self._dossier(dossier_id)
            if not self.db.execute('SELECT 1 FROM workspace_relations WHERE dossier_id=? AND id=?', (dossier_id, relation_id)).fetchone():
                raise KeyError(relation_id)
            return {'items': [{'revision': row['revision'], 'action': row['action'], 'payload': json.loads(row['payload_json']), 'at': row['at']}
                for row in self.db.execute('SELECT * FROM workspace_relation_revisions WHERE relation_id=? ORDER BY revision', (relation_id,))]}

    def working_graph(self, dossier_id):
        with self.repo.lock:
            self._dossier(dossier_id)
            row = self.db.execute('SELECT * FROM workspace_graphs WHERE dossier_id=?', (dossier_id,)).fetchone()
            if row is None:
                raise KeyError(dossier_id)
            return dict(json.loads(row['config_json']), id=dossier_id, revision=row['revision'], updated_at=row['updated_at'])

    def save_graph(self, dossier_id, raw):
        value = WorkingGraph.model_validate(raw)
        with self.repo.lock, self.db:
            self._dossier(dossier_id)
            if value.graph.dossier_id not in (None, dossier_id):
                raise ValueError('Graf musi należeć do tej teczki')
            value.graph.dossier_id = dossier_id
            previous = self.db.execute('SELECT revision FROM workspace_graphs WHERE dossier_id=?', (dossier_id,)).fetchone()
            revision = previous['revision'] if previous else 0
            if value.revision != revision:
                raise QueryChanged('Układ grafu zmieniono w innym oknie; wczytaj aktualną wersję')
            config = value.model_dump(mode='json', by_alias=True, exclude={'revision'})
            config['graph']['expected_revision'] = None
            config['graph']['as_of'] = None
            self.db.execute('''INSERT INTO workspace_graphs VALUES(?,?,?,?) ON CONFLICT(dossier_id)
                DO UPDATE SET config_json=excluded.config_json,revision=excluded.revision,updated_at=excluded.updated_at''',
                (dossier_id, encode(config), revision+1, iso(self.repo.clock())))
            self.workspace.dossiers._touch(dossier_id)
            return self.working_graph(dossier_id)
