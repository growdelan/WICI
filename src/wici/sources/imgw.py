"""Current official aggregate PDFs; no legacy JSON endpoint."""
import httpx

from .base import USER_AGENT, Adapter, FetchResult, SourceError
from .normalize import document


class IMGWPDFAdapter(Adapter):
    """Read only current official aggregate PDFs; never crawl archives at runtime."""
    source_id = 'imgw_meteo'
    host = 'danepubliczne.imgw.pl'
    endpoint = 'https://danepubliczne.imgw.pl/data/current/ost_meteo/'
    path_prefixes = ('/data/current/ost_meteo',)
    coverage = 'Najnowszy zbiorczy PDF na prefiks wydawniczy i znane aktywne dokumenty, do 20 plików; bez hydro i archiwalnego backfillu.'

    def parse_pdf(self, payload, url):
        from .imgw_pdf import parse_pdf
        if not self.allowed(url):
            raise ValueError('PDF poza oficjalnym bieżącym katalogiem ostrzeżeń')
        return parse_pdf(payload, url)

    async def collect(self, client):
        import asyncio
        import re
        from urllib.parse import urljoin

        from bs4 import BeautifulSoup

        text = await self.request(client, self.endpoint)
        soup = BeautifulSoup(text, 'html.parser')
        heading = soup.find('h1')
        if not heading or heading.get_text(strip=True) != 'Index of /data/current/ost_meteo':
            raise ValueError('Nieznany schemat indeksu PDF IMGW')
        newest = {}
        unexpected = False
        unknown_pdfs = set()
        for anchor in soup.find_all('a', href=True):
            href = anchor['href']
            if href.startswith('?') or href in ('../', '/data/current/'):
                continue
            match = re.fullmatch(r'([A-Z]{3})_STAN_(\d{17})\.pdf', href)
            url = urljoin(self.endpoint, href)
            if not match or not self.allowed(url):
                unexpected = True
                if self.allowed(url) and href.lower().endswith('.pdf'):
                    unknown_pdfs.add(url)
                continue
            prior = newest.get(match[1])
            if prior is None or match[2] > prior[0]:
                newest[match[1]] = (match[2], url)
        selected = sorted(newest.values())
        selected_urls = {url for _, url in selected}
        tracked = sorted({url for url in getattr(self, 'tracked_urls', ()) if self.allowed(url)
                          and re.fullmatch(r'[A-Z]{3}_STAN_\d{17}\.pdf', url.rsplit('/',1)[-1])
                          and url not in selected_urls})
        fetches = [(url, False) for _, url in selected] + [(url, True) for url in tracked]
        limited = len(fetches) > 20 or len(unknown_pdfs) > 20
        current_urls = {url for url, _ in fetches[:20]}
        self.binary_cache = {url: cached for url, cached in self.binary_cache.items() if url in current_urls}
        docs, errors, blocked, retry_after = [], 0, False, None
        for url in sorted(unknown_pdfs)[:20]:
            title = 'Dokument IMGW — nierozpoznana nazwa PDF'
            doc = document(self.source_id, 'pdf-unparsed:'+url, url, title,
                           'Plik figuruje w oficjalnym wykazie, ale jego format nazwy jest nieobsługiwany.',
                           {}, ['Nieznany format nazwy PDF; pliku nie pobrano automatycznie'])
            doc['fields']['contract_validated'] = False
            docs.append(doc)
        seen_identities = set()
        for url, is_tracked in fetches[:20]:
            try:
                if self.robots and not self.robots.can_fetch(USER_AGENT, url):
                    raise ValueError('robots.txt wyklucza PDF')
                payload = await self.request_bytes(client, url)
                result = await asyncio.to_thread(self.parse_pdf, payload, url)
                for doc in result.documents:
                    if is_tracked and (doc['identity_key'] in seen_identities
                                       or doc['identity_key'] not in getattr(self, 'tracked_identities', set())):
                        continue
                    docs.append(doc)
                    seen_identities.add(doc['identity_key'])
                errors += int(result.status == 'partial')
            except (ValueError, OSError, SourceError, httpx.HTTPError) as exc:
                errors += 1
                if isinstance(exc, SourceError):
                    blocked = blocked or exc.blocked
                    retry_after = max(retry_after or 0, exc.retry_after or 0) or None
                title = 'Ostrzeżenie IMGW — nieobsługiwany PDF'
                doc = document(self.source_id, 'pdf-unparsed:'+url, url, title,
                               'Nie udało się odczytać pól dokumentu; sprawdź oryginał u wydawcy.',
                               {}, ['Nieznany lub nieczytelny PDF: '+type(exc).__name__])
                doc['fields']['contract_validated'] = False
                docs.append(doc)
        partial = unexpected or limited or errors
        return FetchResult(documents=docs,status='partial' if partial else 'success',
                           availability='blocked_access' if blocked else 'enabled',coverage=self.coverage,retry_after=retry_after,
                           message=f'{len(fetches[:20])}/{len(fetches)} plików bieżących/znanych aktywnych; {len(docs)} ostrzeżeń powiatowych; '
                                   f'{errors} plików do kontroli. Nieobsługiwane odnośniki: {"tak" if unexpected else "nie"}.')
