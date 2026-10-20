"""Small central-site HTML readers. Detailed SG incident text is not persisted."""
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .base import USER_AGENT, Adapter, FetchResult, SourceError
from .normalize import document, plain


class SGAdapter(Adapter):
    source_id = 'sg'
    host = 'www.strazgraniczna.pl'
    path_prefix = '/pl/aktualnosci'
    endpoint = 'https://www.strazgraniczna.pl/pl/aktualnosci'
    coverage = 'Centralne aktualności, maksymalnie 3 strony / 7 dni; bez oddziałów. Szczegóły osób i operacji nie są zapisywane.'

    def parse_listing(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        if not soup.select_one('#content .okno ul'):
            raise ValueError('Brak rozpoznanej listy aktualności SG')
        entries = []
        for li in soup.select('#content li.news'):
            a, title, date = li.select_one('a[href]'), li.select_one('h3'), li.select_one('.data')
            if not a or not title or not date:
                raise ValueError('Uszkodzona pozycja listy SG')
            url = urljoin(self.endpoint, a['href'])
            if self.allowed(url):
                entries.append((url, plain(title.get_text()), plain(date.get_text())))
        return entries

    def parse_article(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        title, article, date = soup.select_one('#content .head h2'), soup.select_one('#content article.txt'), soup.select_one('#content .metryka .data')
        if not title or not article or not date:
            raise ValueError('Brak rozpoznanego artykułu SG')
        original = plain(title.get_text())
        # Travel advisories are the sole detailed SG text admitted by this MVP.
        advisory = bool(re.search(r'^(Utrudnienia|Ograniczenia|Zamknięcie|Przywrócenie).*przejści', original, re.IGNORECASE))
        body = plain(article.get_text(' '))
        headline = soup.select_one('#content .head h3')
        if headline:
            body = plain(headline.get_text()) + ' ' + body
        sensitive = re.search(r'patrol|funkcjonariusz|zatrzyma|poszukiw|obywatel|\bPESEL\b|\b\d{11}\b|@|\b(?:ul\.|ulica)\b', body, re.IGNORECASE)
        safe = advisory and not sensitive
        title_text = original if safe else 'Materiał centralnego serwisu Straży Granicznej'
        text = body if safe else 'Szczegółowa treść pominięta przed zapisem: minimalizacja danych osobowych i operacyjnych. Pełny komunikat dostępny u wydawcy.'
        event={'locations':[]}
        reasons=['Treść zminimalizowana przed zapisem'] if not safe else []
        identity = re.search(r'/([0-9]+),', url)
        if not identity:
            raise ValueError('Brak stabilnego identyfikatora SG')
        doc = document(self.source_id, identity[1], url, title_text, text, event, reasons,
                       redaction_note='Bez multimediów, nazwisk i szczegółów operacyjnych; pełny tekst tylko publicznego komunikatu podróżnego bez wskazanych danych.')
        doc['fields']['source_published_date'] = datetime.strptime(plain(date.get_text()), '%d.%m.%Y').date().isoformat()
        return doc

    async def collect(self, client):
        urls, reached_old = [], False
        cutoff = (self.clock() - timedelta(days=7)).date()
        for page in range(3):
            url = self.endpoint if page == 0 else self.endpoint + f'?page={page}'
            entries = self.parse_listing(await self.request(client, url))
            if not entries:
                break
            for entry_url, _, date in entries:
                if datetime.strptime(date, '%d.%m.%Y').date() < cutoff:
                    reached_old = True
                    continue
                urls.append(entry_url)
            if reached_old:
                break
        docs, errors = [], 0
        for url in dict.fromkeys(urls):
            if self.robots and not self.robots.can_fetch(USER_AGENT, url):
                errors += 1
                continue
            try:
                docs.append(self.parse_article(await self.request(client, url), url))
            except (ValueError, SourceError, httpx.HTTPError) as exc:
                if isinstance(exc, SourceError) and exc.blocked:
                    raise
                errors += 1
        return FetchResult(documents=docs, status='partial' if errors or not reached_old else 'success',
                           message=f'SG: {len(docs)} komunikatów, {errors} błędów; ' + ('osiągnięto granicę 7 dni.' if reached_old else 'limit stron; niepełny zakres.'), coverage=self.coverage)


class RCBAdapter(Adapter):
    source_id = 'rcb'
    host = 'www.gov.pl'
    path_prefix = '/web/rcb'
    endpoint = 'https://www.gov.pl/web/rcb/komunikaty'
    robots_redirect_paths = ('/robots.txt', '/static/code/robots.txt')
    coverage = 'Sekcja Komunikaty RCB: tylko Alert RCB, maksymalnie 3 strony i 7 dni; bez raportu dobowego/multimediów.'

    def unavailable_redirect(self, url, target):
        # A removed alert may redirect to the portal root. Never fetch that root.
        return (self.allowed(url) and urlsplit(url).path.startswith('/web/rcb/alert-rcb-')
                and target == 'https://www.gov.pl/')

    def parse_listing(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        listing = soup.select_one('main') or soup.select_one('#main-content')
        if not listing or not listing.select_one('article .art-prev ul'):
            raise ValueError('Niepotwierdzony schemat wykazu RCB')
        urls = []
        for a in listing.select('a[href]'):
            url = urljoin(self.endpoint, a['href'])
            if self.allowed(url) and '/alert-rcb-' in url and 'alert rcb' in plain(a.get_text()).lower():
                urls.append(url)
        return list(dict.fromkeys(urls))

    def parse_article(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        container = soup.select_one('article')
        if not container:
            raise ValueError('Niepotwierdzony schemat artykułu RCB')
        heading = container.select_one('h1, h2')
        content = container.select_one('.editor-content')
        if not heading or not content or 'alert rcb' not in plain(heading.get_text()).lower():
            raise ValueError('Niepotwierdzony artykuł Alert RCB')
        title, text = plain(heading.get_text()), plain(content.get_text(' '))
        event={'locations':[]}
        reasons=[]
        doc = document(self.source_id, url, url, title, text, event, reasons)
        date_node = container.select_one('time, .event-date, .date')
        if date_node:
            date = plain(date_node.get_text())
            try:
                doc['fields']['source_published_date'] = datetime.strptime(date, '%d.%m.%Y').date().isoformat()
            except ValueError:
                reasons.append('Nieznana data publikacji')
        return doc

    async def collect(self, client):
        url, urls, complete = self.endpoint, [], False
        cutoff = (self.clock() - timedelta(days=7)).date()
        for _ in range(3):
            html = await self.request(client, url)
            self.parse_listing(html)  # reject an unrecognized page before claiming an empty result
            soup = BeautifulSoup(html, 'html.parser')
            for li in soup.select('article .art-prev li'):
                a, date = li.select_one('.title a[href]'), li.select_one('.date')
                if not a or not date:
                    raise ValueError('Uszkodzona pozycja wykazu RCB')
                if datetime.strptime(plain(date.get_text()), '%d.%m.%Y').date() < cutoff:
                    complete = True
                    continue
                entry_url = urljoin(self.endpoint, a['href'])
                if self.allowed(entry_url) and '/alert-rcb-' in entry_url:
                    urls.append(entry_url)
            next_page = soup.select_one('#js-pagination-page-next[href]')
            if complete or not next_page:
                complete = True
                break
            next_url = urljoin(self.endpoint, next_page['href'])
            if not self.allowed(next_url) or not next_url.startswith(self.endpoint + '?'):
                raise SourceError('Paginacja RCB poza wykazem', blocked=True)
            url = next_url
        docs, errors = [], 0
        for url in dict.fromkeys(urls):
            if self.robots and not self.robots.can_fetch(USER_AGENT, url):
                errors += 1
                continue
            try:
                docs.append(self.parse_article(await self.request(client, url), url))
            except (ValueError, SourceError, httpx.HTTPError) as exc:
                if isinstance(exc, SourceError) and exc.blocked:
                    raise
                errors += 1
        return FetchResult(documents=docs, status='partial' if errors or not complete else 'success',
                           message=f'RCB: {len(docs)} alertów, {errors} błędów; ' + ('osiągnięto granicę 7 dni.' if complete else 'limit stron; niepełny zakres.'), coverage=self.coverage)
