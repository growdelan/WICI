"""Persist publisher documents and versions; no editorial publication queue."""
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from functools import wraps
from pathlib import Path
from threading import RLock

from wici.daily import WARSAW, civil_day
from wici.db import connect
from wici.models import Document
from wici.processing.normalize import clean_text


def utcnow():
    return datetime.now(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat()


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=str)


def serialized_query(method):
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with self.lock:
            return method(self,*args,**kwargs)
    return wrapped


class Repository:
    def __init__(self,path: str | Path,clock=utcnow):
        self.db=connect(path)
        self.lock=RLock()
        self.clock=clock

    def close(self):
        with self.lock:
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.db.close()

    def _one(self,sql,params=()):
        row=self.db.execute(sql,params).fetchone()
        return dict(row) if row else None

    @serialized_query
    def ioda_metadata(self):
        rows = self.db.execute('SELECT metadata_json,verified_at FROM ioda_entities').fetchall()
        return [dict(json.loads(r['metadata_json']), _verified_at=r['verified_at']) for r in rows]

    def save_ioda_metadata(self, entities):
        with self.lock, self.db:
            for item in entities:
                raw = {k: v for k, v in item.items() if not k.startswith('_')}
                self.db.execute('''INSERT INTO ioda_entities VALUES(?,?,?,?,?)
                    ON CONFLICT(entity_type,entity_code) DO UPDATE SET name=excluded.name,
                    metadata_json=excluded.metadata_json,verified_at=excluded.verified_at''',
                    (item['type'],item['code'],item['name'],encode(raw),stamp(self.clock())))

    def save_ioda_events(self, events, provenance, synthetic=False):
        changed = 0
        now = stamp(self.clock())
        with self.lock, self.db:
            for e in events:
                raw = encode(e['raw'])
                previous = self._one('SELECT raw_json FROM ioda_events WHERE id=?', (e['id'],))
                changed += int(not previous or previous['raw_json'] != raw)
                self.db.execute('''INSERT INTO ioda_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,source_until=excluded.source_until,
                    ended_at=excluded.ended_at,score=excluded.score,measured_at=excluded.measured_at,
                    raw_json=excluded.raw_json,provenance_json=excluded.provenance_json,fetched_at=excluded.fetched_at''',
                    (e['id'],e['entity_type'],e['entity_code'],e['name'],e['datasource'],e['method'],
                     e['started_at'],e['source_until'],e['ended_at'],e['score'],e['measured_at'],raw,
                     encode(provenance),now,now,int(synthetic)))
        return changed

    def save_ioda_alerts(self, alerts, provenance=None):
        with self.lock, self.db:
            for e in alerts:
                self.db.execute('''INSERT INTO ioda_alerts VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id)
                    DO UPDATE SET raw_json=excluded.raw_json,provenance_json=excluded.provenance_json,fetched_at=excluded.fetched_at''',
                    (e['id'],e['entity_type'],e['entity_code'],e['datasource'],e['method'],
                     e['measured_at'],encode(e['raw']),encode(provenance or {'synthetic':True}),stamp(self.clock())))

    def save_ioda_samples(self, samples, provenance=None):
        # Preserve the value and its response metadata together. Later null
        # attempts are reported separately by sources and app_state.ioda_run.
        with self.lock, self.db:
            self.db.executemany('''INSERT INTO ioda_samples VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT
                (entity_type,entity_code,datasource,measured_at,step) DO UPDATE SET
                value=excluded.value,native_step=excluded.native_step,
                fetched_at=excluded.fetched_at,provenance_json=excluded.provenance_json
                WHERE excluded.value IS NOT NULL OR ioda_samples.value IS NULL''',
                [(s['entity_type'],s['entity_code'],s['datasource'],s['measured_at'],s['step'],
                  s['native_step'],s['value'],stamp(self.clock()),encode(provenance or {'synthetic':True})) for s in samples])

    def save_ioda_run(self, summary):
        cutoff = int((self.clock()-timedelta(days=30)).timestamp())
        with self.lock, self.db:
            self.db.execute("INSERT INTO app_state VALUES('ioda_run',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (encode(summary),))
            # Unknown-end events retain a 30-day last-seen grace period.
            self.db.execute('DELETE FROM ioda_events WHERE source_until<? AND fetched_at<?',
                            (cutoff,stamp(self.clock()-timedelta(days=30))))
            for table in ('ioda_alerts','ioda_samples'):
                self.db.execute(f'DELETE FROM {table} WHERE measured_at<?', (cutoff,))

    @serialized_query
    def ioda_status(self):
        row = self._one("SELECT value FROM app_state WHERE key='ioda_run'")
        summary = json.loads(row['value']) if row else {}
        latest = self.db.execute('SELECT MAX(measured_at) FROM ioda_samples WHERE value IS NOT NULL').fetchone()[0]
        source = self._one("SELECT * FROM sources WHERE id='ioda'") or {}
        now = self.clock()
        latest_at = datetime.fromtimestamp(latest,UTC) if latest else None
        age = max(0,int((now-latest_at).total_seconds())) if latest_at else None
        checks = summary.get('signal_checks', {})
        coverage_counts = {'available':0, 'stale':0, 'no_measurements':0, 'read_error':0}
        for check in checks.values():
            measured = check.get('measurement_at')
            state = ('read_error' if check.get('result')=='error' else 'no_measurements' if measured is None
                     else 'stale' if now.timestamp()-measured>3600 else 'available')
            coverage_counts[state] += 1
        return dict(summary, signal_coverage=coverage_counts, last_attempt_at=source.get('last_attempt_at'),
                    last_successful_check=source.get('last_successful_check'),
                    last_result=source.get('last_result'), access_state=source.get('access_state'),
                    interval_seconds=source.get('interval_seconds',300),
                    measurement_at=stamp(latest_at) if latest_at else None,
                    measurement_age_seconds=age, measurement_stale=age is None or age>3600,
                    measurement_state='no_measurements' if age is None else 'stale' if age>3600 else 'available')

    @serialized_query
    def list_ioda(self, hours=24, selected_date=None, level=None, voivodeship=None, limit=500):
        from wici.ioda import SCORE_UNIT, SIGNAL_MEANINGS, SIGNALS, SITE, geometry_ref
        if hours not in (24,48) or level not in (None,'country','region','asn'):
            raise ValueError('IODA: wybierz 24/48 godzin i poziom country/region/asn')
        now = self.clock()
        today = now.astimezone(WARSAW).date()
        day = date.fromisoformat(selected_date) if selected_date else today
        if day>today:
            raise ValueError('Data IODA nie może być w przyszłości')
        end = now if day==today else datetime.combine(day+timedelta(days=1),time(),WARSAW).astimezone(UTC)
        start = end-timedelta(hours=hours)
        a,b = int(start.timestamp()),int(end.timestamp())
        metadata = {(e['type'],e['code']):e for e in self.ioda_metadata()}
        def ref(kind,code):
            return geometry_ref(metadata[(kind,code)]) if (kind,code) in metadata else None
        # Day selects an overlap window. Unknown ends are included only while
        # the source last reported overlap with this window, not indefinitely.
        rows = self.db.execute('''SELECT * FROM ioda_events WHERE started_at<? AND
            (CASE WHEN ended_at IS NULL THEN source_until ELSE ended_at END)>?
            ORDER BY started_at DESC,id''',(b,a))
        items = []
        for row in rows:
            e = dict(row)
            if level and e['entity_type'] != level:
                continue
            e['geometry_ref'] = ref(e['entity_type'],e['entity_code'])
            # Province filter is strict: country and ASNs do not acquire a province.
            if voivodeship and (e['entity_type'] != 'region' or e['geometry_ref'] != voivodeship):
                continue
            e['raw'] = json.loads(e.pop('raw_json'))
            e['provenance'] = json.loads(e.pop('provenance_json'))
            e['url'] = f"{SITE}/{e['entity_type']}/{e['entity_code']}"
            e['score_unit'],e['signal_unit'] = SCORE_UNIT,SIGNALS.get(e['datasource'],'Jednostka źródłowa nieustalona')
            e['signal_meaning'] = SIGNAL_MEANINGS.get(e['datasource'],'Sprawdź opis sygnału w IODA.')
            e['end_state'] = 'source_normal' if e['ended_at'] else 'unconfirmed'
            e['measurement_age_seconds'] = max(0,int(now.timestamp())-e['measured_at'])
            e['fetch_age_seconds'] = max(0,int((now-datetime.fromisoformat(e['fetched_at'])).total_seconds()))
            items.append(e)
        selected = []
        status = self.ioda_status()
        for (kind,code),e in metadata.items():
            geometry = ref(kind,code)
            if level and kind!=level or voivodeship and (kind!='region' or geometry!=voivodeship):
                continue
            series = []
            for signal,unit in SIGNALS.items():
                points = [dict(r) for r in self.db.execute('''SELECT measured_at,value,step,native_step,fetched_at
                    FROM ioda_samples WHERE entity_type=? AND entity_code=? AND datasource=?
                    AND measured_at>=? AND measured_at<? ORDER BY measured_at DESC,step LIMIT 600''',
                    (kind,code,signal,a,b))]
                # Overlapping aggregated grids: retain most recently fetched
                # representation per timestamp; report the real step explicitly.
                unique = {}
                for p in sorted(points,key=lambda p:p['fetched_at']):
                    unique[p['measured_at']] = p
                points = sorted(unique.values(),key=lambda p:p['measured_at'])
                latest = max((p['measured_at'] for p in points if p['value'] is not None),default=None)
                series.append({'datasource':signal,'unit':unit,'meaning':SIGNAL_MEANINGS[signal],'points':points[-288:],
                               'last_check':status.get('signal_checks',{}).get(f'{kind}/{code}/{signal}'),
                               'measurement_at':latest,'stale':latest is None or now.timestamp()-latest>3600})
            selected.append({'type':kind,'code':code,'name':e['name'],'geometry_ref':geometry,'signals':series})
        limit = max(1,min(limit,500))
        return {'items':items[:limit],'total':len(items),'limited':len(items)>limit,'entities':selected,
                'window_start':stamp(start),'window_end':stamp(end),'hours':hours,'status':status,
                'history_note':'Lokalnie zapisane dane; bez gwarancji kompletnego archiwum i odtworzenia dawnego stanu wiedzy.',
                'scope_note':'Poziomy mogą opisywać tę samą anomalię. ASN powiązany z Polską może mieć pomiary poza Polską.',
                'filter_note':'Wybrany dzień kończy okno 24/48 h w Europe/Warsaw; dziś do teraz. Filtr województwa obejmuje wyłącznie zweryfikowane regiony; wyklucza kraj, ASN i regiony bez mapowania.'}

    def ingest_fires(self, observations):
        now = stamp(self.clock())
        changed = 0
        with self.lock, self.db:
            for item in observations:
                old = self._one('SELECT id FROM fire_observations WHERE id=?', (item['id'],))
                fields = ('id','product','satellite','instrument','latitude','longitude','observed_at',
                          'confidence','frp','voivodeship','voivodeship_name')
                self.db.execute('''INSERT INTO fire_observations
                    (id,product,satellite,instrument,latitude,longitude,observed_at,confidence,frp,
                     voivodeship,voivodeship_name,first_seen_at,last_seen_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    confidence=excluded.confidence,frp=excluded.frp,last_seen_at=excluded.last_seen_at''',
                    (*[item[field] for field in fields], now, now))
                changed += int(old is None)
        return changed

    @serialized_query
    def list_fires(self, hours=24, selected_date=None, voivodeship=None, limit=2000):
        if hours not in (24, 48):
            raise ValueError('Okno obserwacji musi wynosić 24 lub 48 godzin')
        now = self.clock()
        day = date.fromisoformat(selected_date) if selected_date else now.astimezone(WARSAW).date()
        if day > now.astimezone(WARSAW).date():
            raise ValueError('Data obserwacji nie może być w przyszłości')
        end = now if day == now.astimezone(WARSAW).date() else datetime.combine(day+timedelta(days=1), time(), WARSAW)
        start = end-timedelta(hours=hours) if end.tzinfo == UTC else end.astimezone(UTC)-timedelta(hours=hours)
        params = [stamp(start), stamp(end)]
        where = 'observed_at>=? AND observed_at<?'
        if voivodeship:
            where += ' AND voivodeship=?'
            params.append(voivodeship)
        total = self.db.execute(f'SELECT COUNT(*) FROM fire_observations WHERE {where}', params).fetchone()[0]
        items = [dict(row) for row in self.db.execute(
            f'SELECT * FROM fire_observations WHERE {where} ORDER BY observed_at DESC,id LIMIT ?', (*params, max(1,min(limit,2000))))]
        for item in items:
            item['age_minutes'] = max(0, int((now-datetime.fromisoformat(item['observed_at'])).total_seconds()/60))
        return {'items': items,'total': total,'limited': total>len(items),'hours': hours,
                    'window_start': stamp(start),'window_end': stamp(end)}

    def ingest(self,document: Document | dict,now=None):
        from wici.workspace_repository import WorkspaceRepository
        document=Document.model_validate(document)
        document=Document.model_validate(dict(document.model_dump(),title=clean_text(document.title),text=clean_text(document.text)))
        time=stamp(now or self.clock())
        payload=document.model_dump(mode='json')
        significant={key:payload[key] for key in ('title','text','fields','source_published_at','source_updated_at','redaction_note')}
        pdf=document.source_id=='imgw_meteo' and document.identity_key.startswith('imgw-pdf:')
        if pdf:
            significant['fields']={k:v for k,v in significant['fields'].items() if k!='source_pdf_url'}
        digest=hashlib.sha256(encode(significant).encode()).hexdigest()
        with self.lock,self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(id,name) VALUES(?,?)',(document.source_id,document.source_id))
            row=self._one('SELECT * FROM documents WHERE source_id=? AND identity_key=?',(document.source_id,document.identity_key))
            if not row:
                id=self.db.execute('INSERT INTO documents(source_id,identity_key,source_document_id,url,first_seen_at,last_checked_at) VALUES(?,?,?,?,?,?)',
                    (document.source_id,document.identity_key,document.source_document_id,document.url,time,time)).lastrowid
                row=self._one('SELECT * FROM documents WHERE id=?',(id,))
            current=self._one('SELECT * FROM document_versions WHERE document_id=? AND version_number=?',(row['id'],row['current_version']))
            self.db.execute('UPDATE documents SET last_checked_at=? WHERE id=?',(time,row['id']))
            if current and current['content_hash']==digest:
                self.db.execute('UPDATE documents SET url=? WHERE id=?',(document.url,row['id']))
                WorkspaceRepository(self).project_document(row['id'])
                return {'document_id':row['id'],'document_version_id':current['id'],'changed':False}
            prior_issued=(current['source_updated_at'] or current['source_published_at']) if current else None
            issued=document.source_updated_at or document.source_published_at
            older=bool(pdf and prior_issued and issued and issued<datetime.fromisoformat(prior_issued))
            if older:
                known=self._one('SELECT id FROM document_versions WHERE document_id=? AND content_hash=?',(row['id'],digest))
                if known:
                    return {'document_id':row['id'],'document_version_id':known['id'],'changed':False,'out_of_order':True}
            number=self.db.execute('SELECT COALESCE(MAX(version_number),0)+1 FROM document_versions WHERE document_id=?',(row['id'],)).fetchone()[0]
            version_id=self.db.execute("""INSERT INTO document_versions(document_id,version_number,content_hash,title,text,fields_json,
                source_published_at,source_updated_at,parser_version,redaction_note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (row['id'],number,digest,document.title,document.text,encode(payload['fields']),payload['source_published_at'],
                 payload['source_updated_at'],document.parser_version,document.redaction_note,time)).lastrowid
            if not older:
                self.db.execute('UPDATE documents SET current_version=?,url=? WHERE id=?',(number,document.url,row['id']))
            projected = WorkspaceRepository(self).project_document(row['id'])
            if older and not projected:
                self.db.execute('UPDATE catalog_objects SET revision=revision+1 WHERE ref=?',
                                (f"communication:{row['id']}",))
            if not older and payload['fields'].get('contract_validated') is True and payload['fields'].get('access_allowed') is True:
                from wici.workspace_monitor import append_observation
                areas = [dict(area) for area in self.db.execute(
                    'SELECT admin_code,role,basis FROM catalog_object_areas WHERE ref=?',
                    (f"communication:{row['id']}",))]
                append_observation(self, 'communication', f"communication:{row['id']}", document.source_id,
                                   time, version_id, {'document_id': row['id'], 'version_id': version_id,
                                    'version_number': number, 'title': document.title, 'text': document.text,
                                    'url': document.url, 'areas': areas, 'content_hash': digest,
                                    'source_published_at': payload['source_published_at'],
                                    'source_updated_at': payload['source_updated_at']})
            return {'document_id':row['id'],'document_version_id':version_id,'changed':True,'out_of_order':older}

    @serialized_query
    def list_communications(self, filters=None, limit=1000):
        from wici.communications import SOURCES, communication, matches
        results=[]
        for row in self.db.execute('''SELECT d.id,d.source_id,d.url,d.first_seen_at,d.last_checked_at,
            dv.id document_version_id,dv.version_number,dv.title,dv.text,dv.fields_json,
            dv.source_published_at,dv.source_updated_at,dv.redaction_note,s.name source_name
            FROM documents d JOIN document_versions dv ON dv.document_id=d.id AND dv.version_number=d.current_version
            JOIN sources s ON s.id=d.source_id ORDER BY COALESCE(dv.source_published_at,dv.source_updated_at,d.first_seen_at) DESC,d.id DESC'''):
            fields=json.loads(row['fields_json'])
            if row['source_id'] not in SOURCES or fields.get('contract_validated') is not True or fields.get('access_allowed') is not True:
                continue
            item=communication({k:v for k,v in dict(row).items() if k!='fields_json'},fields,self.clock())
            if matches(item,filters or {},self.clock()):
                selected=(filters or {}).get('date')
                item['selection_basis']='publication_day'
                if selected and item['publication_day']!=selected:
                    item['selection_basis']='source_updated_at' if civil_day(item['source_updated_at'])==selected else 'display_window' if item['source_id']=='rso' else 'warning_validity'
                results.append(item)
        return {'items':results[:limit],'total':len(results),'limited':len(results)>limit}

    @serialized_query
    def communication_detail(self, document_id):
        # Same eligibility and projection as the list; history contains source
        # versions, never invented decisions or duplicated publications.
        from wici.communications import SOURCES, communication, original_url
        row=self._one('''SELECT d.id,d.source_id,d.url,d.first_seen_at,d.last_checked_at,
            dv.id document_version_id,dv.version_number,dv.title,dv.text,dv.fields_json,
            dv.source_published_at,dv.source_updated_at,dv.redaction_note,s.name source_name
            FROM documents d JOIN document_versions dv ON dv.document_id=d.id AND dv.version_number=d.current_version
            JOIN sources s ON s.id=d.source_id WHERE d.id=?''',(document_id,))
        if not row or row['source_id'] not in SOURCES:
            raise KeyError(document_id)
        fields=json.loads(row.pop('fields_json'))
        if fields.get('contract_validated') is not True or fields.get('access_allowed') is not True:
            raise KeyError(document_id)
        item=communication(row,fields,self.clock())
        item['history']=[dict(r) for r in self.db.execute('''SELECT id,version_number,title,text,
            source_published_at,source_updated_at,created_at,fields_json FROM document_versions
            WHERE document_id=? ORDER BY version_number DESC''',(document_id,))]
        for version in item['history']:
            version_fields=json.loads(version.pop('fields_json'))
            version['original_url']=original_url(row['source_id'],version_fields,row['url'])
        return item
