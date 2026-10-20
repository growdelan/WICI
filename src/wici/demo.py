"""Persistent, explicitly synthetic scenario. Never calls a publisher."""
import json
from datetime import UTC, datetime

from wici.models import Document

DEMO_NOW = datetime(2026,10,11,12,tzinfo=UTC)

def seed(repo):
    seed_ioda(repo)
    if repo.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]:
        # Older offline scenarios kept their display metadata in proposals only.
        # Enrich these explicitly synthetic documents without resetting history.
        with repo.db:
            for row in repo.db.execute("SELECT dv.id,dv.fields_json FROM document_versions dv JOIN documents d ON d.id=dv.document_id WHERE d.identity_key LIKE 'demo-%'").fetchall():
                fields=json.loads(row['fields_json'])
                if 'event' not in fields:
                    review=repo._one('SELECT proposed_json FROM review_items WHERE document_version_id=? LIMIT 1',(row['id'],))
                    event=repo._one('SELECT e.data_json FROM event_evidence ee JOIN events e ON e.id=ee.event_id WHERE ee.document_version_id=? LIMIT 1',(row['id'],))
                    value=json.loads(review['proposed_json'])['event'] if review else json.loads(event['data_json']) if event else None
                    if value:
                        fields['event']=value
                        repo.db.execute('UPDATE document_versions SET fields_json=? WHERE id=?',(json.dumps(fields,ensure_ascii=False),row['id']))
        return
    examples = [
        ('imgw_meteo','demo-meteo','DEMO: silny wiatr','warning','14','warning_area'),
        ('rso','demo-rso','DEMO: ostrzeżenie dla mieszkańców','warning','02','notification_area'),
        ('sg','demo-border','DEMO: utrudnienie na przejściu granicznym','notice',None,None),
        ('rcb','demo-rcb','DEMO: alert dla mieszkańców','notice',None,None),
        ('rso','demo-exercise','DEMO: ćwiczenie i test syren','notice','12','notification_area'),
    ]
    for source,key,title,kind,code,role in examples:
        locations=[{'name':{'14':'mazowieckie','02':'dolnośląskie','12':'małopolskie'}[code],
            'role':role,'precision':'administrative','admin_code':code,'geometry_ref':code,
            'source':'syntetyczny scenariusz'}] if code else []
        text='Materiał syntetyczny do demonstracji; nie opisuje prawdziwego zdarzenia.'
        fields={'locations':locations,'valid_from':'2026-10-10T00:00:00+00:00' if kind=='warning' else None,
            'valid_until':'2026-10-12T00:00:00+00:00' if kind=='warning' else None,'official_severity':'1' if source=='imgw_meteo' else None}
        doc=Document(source_id=source,identity_key=key,url='https://example.invalid/demo/'+key,title=title,text=text,
            fields={'event':fields,'contract_validated':True,'recognized_warning_type':True,
                'location_unambiguous':True,'access_allowed':True},
            source_published_at=datetime(2026,10,10,tzinfo=UTC),redaction_note='Syntetyczne dane demonstracyjne')
        repo.ingest(doc,now=DEMO_NOW)

def seed_ioda(repo):
    """Idempotent offline migration of demo scenarios; no real API fixtures."""
    from wici.ioda import SIGNALS, parse_alert, parse_event
    if repo.db.execute('SELECT 1 FROM ioda_events WHERE synthetic=1').fetchone():
        return
    n = int(DEMO_NOW.timestamp())
    entities = [
        {'type':'country','code':'PL','name':'Poland','attrs':{'fqid':'synthetic/country/PL'}},
        {'type':'region','code':'3297','name':'Masovian','attrs':{'country_code':'PL','fqid':'synthetic/region/3297'}},
        {'type':'asn','code':'5617','name':'DEMO AS5617','attrs':{'fqid':'synthetic/asn/5617'}},
        {'type':'region','code':'4849','name':'Unknown Region in Poland','attrs':{'country_code':'PL'}},
    ]
    repo.save_ioda_metadata(entities)
    for i,e in enumerate(entities[:3]):
        alerts = [{'entity':e,'datasource':'bgp','method':'median','time':n-10800,
                   'level':'critical','condition':'< 0.8','value':100,'historyValue':200}]
        if i==1:
            alerts.append(dict(alerts[0],time=n-7200,level='normal',condition='normal',value=200))
        raw = {'entity':e,'from':n-10800,'until':n-7200,'score':3000,
               'datasource':'bgp','method':'median','alerts':alerts}
        repo.save_ioda_events([parse_event(raw)],{'synthetic':True,'description':'Syntetyczny scenariusz offline'},True)
        repo.save_ioda_alerts([parse_alert(a) for a in alerts])
        repo.save_ioda_samples([{'entity_type': e['type'],'entity_code': e['code'],'datasource': 'bgp',
            'measured_at': n-14400+j*300,'step': 300,'native_step': 300,'value': 200 if j<12 else 100}
            for j in range(25)])
    repo.save_ioda_run({'result':'partial','synthetic':True,'at':DEMO_NOW.isoformat(),
        'window_start':n-172800,'window_end':n-7200,'requests':0,
        'entities':['country/PL','region/3297','asn/5617','region/4849'],
        'signal_checks':{f"{e['type']}/{e['code']}/{s}":{'result':'success',
            'measurement_at':n-7200 if e in entities[:3] and s=='bgp' else None} for e in entities for s in SIGNALS},
        'coverage':['Syntetyczne dane offline'],
        'errors':['DEMO: nieaktualne źródło; region 4849 bez pomiarów; odczyty sieciowe wyłączone']})
    with repo.lock,repo.db:
        at = datetime.fromtimestamp(n-7200,UTC).isoformat()
        repo.db.execute("""UPDATE sources SET last_attempt_at=?,last_successful_check=?,last_result='partial',
            error='DEMO: syntetyczny nieaktualny odczyt',coverage='Scenariusz offline IODA' WHERE id='ioda'""",(at,at))
