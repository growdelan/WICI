'use strict';
// Shared cache; only index requests use the two-slot, 600ms admission queue.
(function (root) {
  const MAX_INDEX_QUEUE = 256;
  function create({read, now = Date.now, hidden = () => typeof document !== 'undefined' && document.hidden,
    delay = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id)} = {}) {
    const cache = new Map(), pending = new Map(), listeners = new Set(), polls = new Map();
    let activeTypes = [], visible = false, live = true, indexIds = [], sensorId = null, desired = new Set();
    let jobs = [], running = 0, nextStart = 0, gate = null, retryAt = 0;
    const keyFor = path => {
      const url = new URL(path, 'http://localhost'); url.searchParams.sort();
      return url.pathname.replace(/^\/api/, '') + url.search;
    };
    const isIndex = path => path.startsWith('/gios?') && new URL(path, 'http://localhost').searchParams.get('kind') === 'index';
    const isMoving = path => path === '/aircraft' || path === '/ships';
    const ttl = path => isMoving(path) ? 10000 : path.includes('/hydro') ? 300000 : path.includes('kind=stations') ? 86400000
      : path.includes('kind=sensors') ? 21600000 : 1800000;
    const aborted = () => new DOMException('Zapotrzebowanie na źródło wygasło', 'AbortError');
    function emit(event) {for (const fn of listeners) {try {fn(event);} catch { /* Isolated consumers. */ }}}
    function wanted(job) {
      return !hidden() && (job.external || [...job.signals].some(signal => !signal.aborted) || desired.has(job.key));
    }
    function pruneJobs() {
      jobs = jobs.filter(job => {
        if (wanted(job)) return true;
        if (pending.get(job.key) === job) pending.delete(job.key);
        job.reject(aborted()); return false;
      });
      if (!jobs.length && gate !== null) {cancel(gate); gate = null;}
    }
    function pump() {
      // Withdrawn demand consumes neither an upstream request nor a rate slot.
      pruneJobs();
      if (gate !== null || running >= 2 || !jobs.length) return;
      const wait = Math.max(0, nextStart - now(), retryAt - now());
      if (wait) {gate = delay(() => {gate = null; pump();}, wait); return;}
      const job = jobs.shift(); running++; nextStart = now() + 600;
      Promise.resolve().then(job.run).then(job.resolve, job.reject).finally(() => {running--; pump();});
      pump();
    }
    function enqueue(job) {
      pruneJobs();
      return new Promise((resolve, reject) => {
        job.resolve = resolve; job.reject = reject;
        if (jobs.length >= MAX_INDEX_QUEUE) {reject(new Error('Kolejka indeksów jest pełna. Zawęź zakres stacji.')); return;}
        jobs.push(job); pump();
      });
    }
    function withSignal(promise, signal) {
      if (!signal) return promise;
      if (signal.aborted) return Promise.reject(aborted());
      return new Promise((resolve, reject) => {
        const abort = () => reject(aborted()); signal.addEventListener('abort', abort, {once:true});
        promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
      });
    }
    function consumer(job, options) {
      if (!options.workspaceDemand) {
        if (options.signal) {
          job.signals.add(options.signal);
          const abort = () => pump(); options.signal.addEventListener('abort', abort, {once:true});
          job.promise.then(() => options.signal.removeEventListener('abort', abort),
            () => options.signal.removeEventListener('abort', abort));
        } else job.external = true;
      }
      return withSignal(job.promise, options.signal);
    }
    function request(path, body, options = {}) {
      if (options.signal?.aborted) return Promise.reject(aborted());
      const key = keyFor(path), previous = cache.get(key);
      if (previous && previous.until > now()) return withSignal(Promise.resolve(previous.data), options.signal);
      if (pending.has(key)) return consumer(pending.get(key), options);
      if (hidden()) return previous ? Promise.resolve(previous.data) : Promise.reject(aborted());
      const job = {key, signals:new Set(options.signal && !options.workspaceDemand ? [options.signal] : []),
        external:!options.workspaceDemand && !options.signal, promise:null};
      job.run = async () => {
        if (!wanted(job)) throw aborted();
        const data = await read(key, body, {...options, signal:undefined});
        const failed = ['error', 'partial'].includes(data.status);
        const wait = Math.max(0, Number(data.service_retry_after_seconds) || 0) * 1000;
        if (isIndex(key)) retryAt = Math.max(retryAt, now() + wait);
        cache.delete(key);
        const fetched = Date.parse(data.fetched_at);
        // AIS fetched_at is the last message, not the local cache read. A quiet
        // stream must not accelerate polling or make an old position look new.
        const deadline = isMoving(key) ? now() + ttl(key) : Number.isFinite(fetched) ? Math.max(now() + 1000, Math.min(now(), fetched) + ttl(key)) : now() + ttl(key);
        cache.set(key, {data, until:data.enabled === false ? now() + 300000 : failed ? now() + Math.max(isMoving(key) ? 10000 : 300000, wait) : deadline});
        while (cache.size > 2048) cache.delete(cache.keys().next().value);
        emit({resource:key, data}); return data;
      };
      job.promise = (isIndex(key) ? enqueue(job) : Promise.resolve().then(job.run))
        .catch(error => {emit({resource:key, error}); throw error;})
        .finally(() => {if (pending.get(key) === job) pending.delete(key);});
      pending.set(key, job); return consumer(job, options);
    }
    function schedule(path, entry) {
      if (!live || entry.timer !== null || entry.inFlight || polls.get(path) !== entry) return;
      const next = Math.max(1000, (cache.get(path)?.until || now() + (isMoving(path) ? 10000 : 300000)) - now());
      entry.timer = delay(() => {entry.timer = null; if (polls.get(path) === entry) {polls.delete(path); poll(path);}}, next);
    }
    function poll(path) {
      if (!desired.has(path) || polls.has(path)) return;
      const entry = {timer:null, inFlight:true}; polls.set(path, entry);
      request(path, undefined, {workspaceDemand:true}).catch(() => {}).finally(() => {
        entry.inFlight = false;
        if (polls.get(path) === entry && desired.has(path)) schedule(path, entry);
      });
    }
    function sync() {
      const next = new Set();
      if (visible && !hidden()) {
        if (live && activeTypes.includes('aircraft')) next.add('/aircraft');
        if (live && activeTypes.includes('ship')) next.add('/ships');
        if (activeTypes.includes('hydro_station')) next.add(keyFor('/hydro?kind=stations'));
        if (activeTypes.includes('air_quality_station')) {
          next.add(keyFor('/gios?kind=stations'));
          if (live) {
            for (const id of indexIds) next.add(keyFor(`/gios?kind=index&id=${id}`));
            if (sensorId !== null) next.add(keyFor(`/gios?kind=data&id=${sensorId}`));
          }
        }
      }
      desired = next;
      for (const [path, entry] of polls) {
        if (!desired.has(path)) {if (entry.timer !== null) cancel(entry.timer); polls.delete(path);}
        else if (!live && entry.timer !== null) {cancel(entry.timer); entry.timer = null;}
      }
      pruneJobs();
      for (const path of desired) {if (polls.has(path)) schedule(path, polls.get(path)); else poll(path);}
      pump();
    }
    return {
      request, subscribe(fn) {listeners.add(fn); return () => listeners.delete(fn);},
      setTypes(types, options = {}) {activeTypes = [...types]; live = options.live !== false; sync();},
      activateType(type) {if (!activeTypes.includes(type)) activeTypes.push(type); sync();},
      setVisible(value) {visible = !!value; sync();},
      demandIndexes(ids) {
        const next = [...new Set(ids.map(String).filter(id => /^\d+$/.test(id)))].slice(0, 1000);
        if (next.join(',') === indexIds.join(',')) return;
        indexIds = next; sync();
      },
      demandSensor(id) {const next = id == null ? null : String(id); sensorId = next && /^\d+$/.test(next) ? next : null; sync();},
      loadSensors: id => request(`/gios?kind=sensors&id=${encodeURIComponent(id)}`),
      loadSensor: id => request(`/gios?kind=data&id=${encodeURIComponent(id)}`),
      deactivate() {visible = false; sync();},
      clear() {visible = false; sync(); cache.clear();},
      get pendingCount() {return pending.size;},
      get queuedCount() {return jobs.length;}
    };
  }
  if (typeof module !== 'undefined') module.exports = {create, MAX_INDEX_QUEUE};
  if (root) root.WiciWorkspaceSources = {create};
})(typeof window !== 'undefined' ? window : null);
