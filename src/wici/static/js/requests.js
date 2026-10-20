'use strict';

// Repeat reads only; an interrupted source refresh may already be scheduled.
async function fetchJSON(url, options = {}, description = 'danych') {
  const finish = typeof window !== 'undefined' ? window.WiciRegion?.begin(url) : null;
  try { return await readJSON(url, options, description, finish); } catch (err) { finish?.(err.name === 'AbortError' ? 'cancelled' : 'error'); throw err; }
  finally { finish?.(); }
}

async function readJSON(url, options, description, finish) {
  const read = !options.method || options.method === 'GET';
  const attempts = read ? 3 : 1;
  for (let attempt = 0; attempt < attempts; attempt++) {
    options.signal?.throwIfAborted();
    const controller = new AbortController();
    const cancel = () => controller.abort(options.signal.reason);
    options.signal?.addEventListener('abort', cancel, {once: true});
    const timer = setTimeout(() => controller.abort(), Math.min(60000, Math.max(1000, options.timeoutMs || 10000)));
    try {
      const response = await fetch(url, {...options, signal: controller.signal});
      const data = await response.json();
      finish?.(!response.ok || data?.status === 'error' ? 'error' : data?.stale || data?.status === 'partial' ? 'partial' : 'ready');
      return {response, data};
    } catch (err) {
      if (options.signal?.aborted) throw err;
      const network = err instanceof TypeError || err.name === 'AbortError';
      if (network && attempt + 1 < attempts) {
        clearTimeout(timer);
        await new Promise(resolve => setTimeout(resolve, 150 * (attempt + 1)));
        continue;
      }
      console.warn('WICI: nieudany odczyt', url, err);
      if (!network) throw new Error(`Serwer zwrócił nieprawidłowe dane podczas wczytywania ${description}.`);
      throw new Error(read
        ? `Nie udało się wczytać ${description} z lokalnego serwera. Sprawdź, czy aplikacja działa, i wybierz „Odśwież widok”. Wcześniej wczytane dane pozostają na ekranie.`
        : 'Połączenie przerwało się podczas odświeżania źródła. Pobieranie mogło już zostać zaplanowane — odśwież widok i sprawdź stan źródła przed ponowieniem.');
    } finally {
      options.signal?.removeEventListener('abort', cancel);
      clearTimeout(timer);
    }
  }
}
