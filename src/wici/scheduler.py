"""One shared scheduler; bounded concurrency, no replay of missed intervals."""
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from wici.repository import stamp

INTERVALS = {'imgw_meteo': 300, 'rso': 300, 'rcb': 600, 'sg': 1800, 'firms': 900, 'ioda': 300}
NAMES = {'ioda': 'IODA — problemy łączności internetowej', 'imgw_meteo': 'IMGW — meteorologia', 'rso': 'Regionalny System Ostrzegania',
         'rcb': 'Rządowe Centrum Bezpieczeństwa', 'sg': 'Straż Graniczna', 'firms': 'NASA FIRMS — wykrycia satelitarne'}
URLS = {'ioda': 'https://ioda.inetintel.cc.gatech.edu', 'imgw_meteo': 'https://danepubliczne.imgw.pl/data/current/ost_meteo/',
        'rso': 'https://komunikaty.tvp.pl/komunikatyxml/wszystkie/wszystkie/0?_format=json',
        'rcb': 'https://www.gov.pl/web/rcb', 'sg': 'https://www.strazgraniczna.pl/pl/aktualnosci',
        'firms': 'https://firms.modaps.eosdis.nasa.gov/'}

class Scheduler:
    def __init__(self, repo, config, client, demo=False):
        self.repo, self.config, self.client, self.demo = repo, config, client, demo
        if config.firms_key():
            from wici.runtime import redact_firms_logs
            redact_firms_logs(config.firms_key())
        self.semaphore = asyncio.Semaphore(2)
        self.tasks = {}
        self.loop_task = None
        self.gap_seconds = 0
        self.previous_tick = None
        with repo.lock, repo.db:
            for key, interval in INTERVALS.items():
                enabled = config.enabled(key) and (key != 'firms' or bool(config.firms_key()))
                state = 'disabled_by_user' if demo or not enabled else 'enabled'
                repo.db.execute('''INSERT INTO sources(id,name,url,access_state,interval_seconds) VALUES(?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url,interval_seconds=excluded.interval_seconds,
                    next_due_at=CASE WHEN sources.url<>excluded.url THEN NULL ELSE sources.next_due_at END,
                    failures=CASE WHEN sources.url<>excluded.url THEN 0 ELSE sources.failures END,
                    access_state=CASE WHEN excluded.access_state='disabled_by_user' THEN excluded.access_state
                    WHEN sources.url<>excluded.url THEN 'enabled'
                    WHEN sources.access_state='disabled_by_user' THEN 'enabled' ELSE sources.access_state END''',
                    (key,NAMES[key],URLS[key],state,config.interval(key,interval)))
                if key == 'firms':
                    # A restart applies a replaced local key and permits a new validation.
                    repo.db.execute('UPDATE sources SET access_state=? WHERE id=?', (state,key))
            last = repo.db.execute("SELECT value FROM app_state WHERE key='last_tick'").fetchone()
            if last:
                self.gap_seconds = max(0, (datetime.now(UTC)-datetime.fromisoformat(last[0])).total_seconds())

    def sources(self):
        now = self.repo.clock()
        with self.repo.lock:
            items = [dict(r) for r in self.repo.db.execute('SELECT * FROM sources ORDER BY id')
                     if r['id'] in INTERVALS]
        for item in items:
            last = item['last_successful_check']
            item['stale'] = not last or (now-datetime.fromisoformat(last)).total_seconds() > 3*item['interval_seconds']+120
            item['freshness'] = 'nieaktualne' if item['stale'] else 'aktualne technicznie'
            item['running'] = item['id'] in self.tasks
            if item['id'] == 'ioda':
                item['ioda'] = self.repo.ioda_status()
            if self.demo:
                item['coverage'] = 'Dane syntetyczne; pobieranie wyłączone'
        return items

    def refresh(self, source):
        if source not in INTERVALS:
            raise KeyError(source)
        if self.demo or not self.config.enabled(source) or (source == 'firms' and not self.config.firms_key()):
            raise ValueError('Pobieranie wyłączone w tym trybie')
        if source in self.tasks:
            return False
        if source == 'ioda':
            status = self.repo.ioda_status()
            with self.repo.lock:
                row = self.repo.db.execute("SELECT next_due_at FROM sources WHERE id='ioda'").fetchone()
            if status.get('retry_after_seconds') and row and row['next_due_at'] and datetime.fromisoformat(row['next_due_at'])>self.repo.clock():
                raise ValueError('IODA: trwa oczekiwanie Retry-After do '+row['next_due_at'])
        task = asyncio.create_task(self.fetch(source))
        self.tasks[source] = task
        task.add_done_callback(lambda _: self.tasks.pop(source, None))
        return True

    async def fetch(self, source):
        if source == 'ioda':
            return await self.fetch_ioda()
        if source == 'firms':
            return await self.fetch_firms()
        from wici.sources import ADAPTERS
        ADAPTERS[source].timeout_seconds = self.config.timeout_seconds
        ADAPTERS[source].max_response_bytes = self.config.max_response_bytes
        ADAPTERS[source].clock = self.repo.clock
        if source=='imgw_meteo':
            with self.repo.lock:
                active_urls = self.repo.db.execute("""SELECT DISTINCT d.url,d.identity_key FROM documents d
                    JOIN document_versions dv ON dv.document_id=d.id AND dv.version_number=d.current_version
                    WHERE d.source_id=? AND json_extract(dv.fields_json,'$.event.warning_status') IS NOT 'cancelled'
                    AND json_extract(dv.fields_json,'$.access_allowed')=1
                    AND json_extract(dv.fields_json,'$.event.valid_until')>?""",(source,stamp(self.repo.clock()))).fetchall()
                ADAPTERS[source].tracked_urls = tuple(sorted({row['url'] for row in active_urls}))
                ADAPTERS[source].tracked_identities = {row['identity_key'] for row in active_urls}
        async with self.semaphore:
            start = stamp(self.repo.clock())
            with self.repo.lock, self.repo.db:
                row = dict(self.repo.db.execute('SELECT * FROM sources WHERE id=?',(source,)).fetchone())
                run = self.repo.db.execute('INSERT INTO fetch_runs(source_id,started_at) VALUES(?,?)',(source,start)).lastrowid
                self.repo.db.execute('UPDATE sources SET last_attempt_at=? WHERE id=?',(start,source))
            changed = invalid = fetched = 0
            result, coverage, message, availability, retry = 'error','nieustalone',None,'enabled',None
            try:
                response = await ADAPTERS[source].fetch(self.client)
                result,coverage,message,availability,retry = response.status,response.coverage,response.message,response.availability,response.retry_after
                if result == 'not_modified' and not row['last_successful_check']:
                    raise ValueError('HTTP304 bez zapisanej reprezentacji')
                for document in response.documents:
                    fetched += 1
                    try:
                        saved = await asyncio.to_thread(self.repo.ingest, document)
                        changed += int(saved['changed'])
                    except (ValueError, TypeError):
                        invalid += 1
                if invalid:
                    result = 'partial'
                    message = f'{invalid} rekordów z błędnymi polami; pozostałe zachowano'
            except asyncio.CancelledError:
                result, message = 'error','Pobieranie przerwane przy zatrzymaniu'
                raise
            except Exception as exc:  # noqa: BLE001 — isolate a failing adapter without ending the scheduler
                # Do not log remote text or URLs containing personal data.
                message = f'Błąd pobrania: {type(exc).__name__}'
                logging.getLogger('wici').warning('%s %s', source, message)
            finally:
                now = self.repo.clock()
                finish = stamp(now)
                healthy = result in ('success','not_modified')
                failures = 0 if healthy else row['failures']+1
                delay = row['interval_seconds'] if healthy else min(3600,row['interval_seconds']*2**min(failures,6))
                delay = max(delay,retry or 0)
                with self.repo.lock, self.repo.db:
                    self.repo.db.execute('''UPDATE fetch_runs SET finished_at=?,result=?,fetched_count=?,changed_count=?,invalid_count=?,coverage=?,error=? WHERE id=?''',
                        (finish,result,fetched,changed,invalid,coverage,message,run))
                    self.repo.db.execute('''UPDATE sources SET last_result=?,last_successful_check=CASE WHEN ? THEN ? ELSE last_successful_check END,
                        coverage=?,error=?,access_state=?,next_due_at=?,failures=? WHERE id=?''',
                        (result,healthy,finish,coverage,message,availability,stamp(now+timedelta(seconds=delay)),failures,source))
                    self.repo.db.execute('DELETE FROM fetch_runs WHERE started_at<?',(stamp(now-timedelta(days=30)),))

    async def fetch_ioda(self):
        from wici.ioda import Collector
        if self.demo or not self.config.enabled('ioda'):
            return
        async with self.semaphore:
            start = stamp(self.repo.clock())
            with self.repo.lock, self.repo.db:
                row = dict(self.repo.db.execute("SELECT * FROM sources WHERE id='ioda'").fetchone())
                run = self.repo.db.execute("INSERT INTO fetch_runs(source_id,started_at) VALUES('ioda',?)",(start,)).lastrowid
                self.repo.db.execute("UPDATE sources SET last_attempt_at=? WHERE id='ioda'",(start,))
            collector = Collector(self.repo,self.client,self.config)
            summary = {'result':'error','errors':['Odczyt przerwany'],'coverage':[]}
            try:
                summary = await collector.run()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — isolate collector, preserve committed pages.
                self.repo.save_ioda_run(summary)
            finally:
                now = self.repo.clock()
                healthy = summary['result']=='success'
                failures = 0 if healthy else row['failures']+1
                delay = row['interval_seconds'] if healthy else min(3600,row['interval_seconds']*2**min(failures,6))
                delay = max(delay,collector.retry)
                coverage = 'country/PL + regiony PL + zweryfikowane ASN; ' + ', '.join(summary['coverage'])
                message = '; '.join(summary['errors']) or None
                with self.repo.lock,self.repo.db:
                    self.repo.db.execute("""UPDATE fetch_runs SET finished_at=?,result=?,changed_count=?,
                        fetched_count=?,coverage=?,error=? WHERE id=?""",
                        (stamp(now),summary['result'],collector.changed,collector.requests,coverage,message,run))
                    self.repo.db.execute("""UPDATE sources SET last_result=?,last_successful_check=CASE WHEN ?
                        THEN ? ELSE last_successful_check END,coverage=?,error=?,next_due_at=?,failures=? WHERE id='ioda'""",
                        (summary['result'],healthy,stamp(now),coverage,message,stamp(now+timedelta(seconds=delay)),failures))
                    self.repo.db.execute('DELETE FROM fetch_runs WHERE started_at<?',(stamp(now-timedelta(days=30)),))

    async def fetch_firms(self):
        from wici.firms import fetch_fires
        if self.demo or not self.config.enabled('firms') or not self.config.firms_key():
            return
        async with self.semaphore:
            start = stamp(self.repo.clock())
            with self.repo.lock, self.repo.db:
                row = dict(self.repo.db.execute("SELECT * FROM sources WHERE id='firms'").fetchone())
                run = self.repo.db.execute("INSERT INTO fetch_runs(source_id,started_at) VALUES('firms',?)", (start,)).lastrowid
                self.repo.db.execute("UPDATE sources SET last_attempt_at=? WHERE id='firms'", (start,))
            result, message, coverage = 'error', 'Pobieranie FIRMS przerwane', 'nieustalone'
            fetched = changed = invalid = 0
            availability, retry = 'enabled', 0
            try:
                response = await fetch_fires(self.client, self.config, self.repo.clock())
                result, message, coverage, invalid = response.status, response.message, response.coverage, response.invalid
                availability, retry = response.availability, response.retry_after
                fetched = len(response.observations)
                changed = await asyncio.to_thread(self.repo.ingest_fires, response.observations)
            except asyncio.CancelledError:
                result = 'error'
                raise
            except Exception:  # noqa: BLE001 — isolate this source and never expose credentials in exceptions.
                result, message = 'error', 'Błąd przetwarzania FIRMS; zachowano zapisane obserwacje'
            finally:
                now = self.repo.clock()
                healthy = result == 'success'
                failures = 0 if healthy else row['failures']+1
                delay = row['interval_seconds'] if healthy else min(3600,row['interval_seconds']*2**min(failures,6))
                delay = max(delay,retry)
                with self.repo.lock, self.repo.db:
                    self.repo.db.execute('''UPDATE fetch_runs SET finished_at=?,result=?,fetched_count=?,changed_count=?,
                        invalid_count=?,coverage=?,error=? WHERE id=?''',
                        (stamp(now),result,fetched,changed,invalid,coverage,message,run))
                    self.repo.db.execute('''UPDATE sources SET last_result=?,last_successful_check=CASE WHEN ? THEN ?
                        ELSE last_successful_check END,coverage=?,error=?,next_due_at=?,failures=?,access_state=? WHERE id='firms' ''',
                        (result,healthy,stamp(now),coverage,message,stamp(now+timedelta(seconds=delay)),failures,availability))
                    self.repo.db.execute('DELETE FROM fetch_runs WHERE started_at<?',(stamp(now-timedelta(days=30)),))

    async def loop(self):
        while True:
            now = datetime.now(UTC)
            if self.previous_tick and (now-self.previous_tick).total_seconds()>60:
                self.gap_seconds = (now-self.previous_tick).total_seconds()
            self.previous_tick = now
            with self.repo.lock,self.repo.db:
                self.repo.db.execute("INSERT INTO app_state(key,value) VALUES('last_tick',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(stamp(now),))
                rows = list(self.repo.db.execute('SELECT id,access_state,next_due_at FROM sources'))
            for row in rows:
                # Retain sources from newer/retired integrations as historical data.
                if row['id'] not in INTERVALS:
                    continue
                if row['access_state'] in ('enabled','needs_verification') and (not row['next_due_at'] or datetime.fromisoformat(row['next_due_at'])<=self.repo.clock()):
                    self.refresh(row['id'])
            await asyncio.sleep(5)

    def start(self):
        if not self.demo:
            self.loop_task = asyncio.create_task(self.loop())

    async def stop(self):
        pending = list(self.tasks.values())
        if self.loop_task:
            pending.append(self.loop_task)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
