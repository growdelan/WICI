"""Bounded publisher requests: no off-site redirects or access-control bypass."""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from posixpath import normpath
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = 'WICI/0.1 (private local pilot; public warnings)'
MAX_BYTES = 10 * 1024 * 1024


class SourceError(Exception):
    def __init__(self, message, *, blocked=False, retry_after=None):
        super().__init__(message)
        self.blocked = blocked
        self.retry_after = retry_after


@dataclass
class FetchResult:
    documents: list[dict] = field(default_factory=list)
    status: str = 'success'
    availability: str = 'enabled'
    message: str = ''
    coverage: str = ''
    retry_after: float | None = None


class Adapter:
    source_id = ''
    endpoint = ''
    host = ''
    path_prefix = '/'
    coverage = ''
    robots_redirect_paths = ('/robots.txt',)
    timeout_seconds = 20
    max_response_bytes = MAX_BYTES

    def __init__(self):
        self.cache = {}
        self.binary_cache = {}
        self.robots = None
        self.clock = lambda: datetime.now(UTC)
        self.checked_payloads = self.unchanged_payloads = 0

    def allowed(self, url):
        parsed = urlsplit(url)
        path = normpath(unquote(parsed.path))
        prefixes = getattr(self, 'path_prefixes', (self.path_prefix,))
        return (parsed.scheme == 'https' and parsed.hostname == self.host
                and parsed.port in (None, 443) and not parsed.username
                and '\\' not in path
                and any(path == prefix or path.startswith(prefix.rstrip('/') + '/') for prefix in prefixes))

    async def request_bytes(self, client, url, *, robots=False):
        return await self.request(client, url, robots=robots, binary=True)

    def unavailable_redirect(self, url, target):
        return False

    async def request(self, client, url, *, robots=False, binary=False):
        if not (self.allowed(url) or (robots and url == f'https://{self.host}/robots.txt')):
            raise SourceError('Adres poza dopuszczonym zakresem źródła', blocked=True)
        representations = self.binary_cache if binary else self.cache
        cache = representations.get(url)
        headers = {'User-Agent': USER_AGENT}
        if cache:
            if cache[1]:
                headers['If-None-Match'] = cache[1]
            if cache[2]:
                headers['If-Modified-Since'] = cache[2]
        for _ in range(4):
            async with client.stream('GET', url, headers=headers, timeout=self.timeout_seconds, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    target = urljoin(url, r.headers.get('location', ''))
                    parsed_target = urlsplit(target)
                    robots_target = (robots and parsed_target.scheme == 'https' and parsed_target.hostname == self.host
                                     and parsed_target.port in (None, 443)
                                     and parsed_target.path in self.robots_redirect_paths and not parsed_target.username)
                    if not (self.allowed(target) or robots_target):
                        if not robots and self.unavailable_redirect(url, target):
                            raise SourceError('Dokument niedostępny: przekierowanie do strony głównej')
                        raise SourceError('Przekierowanie poza dopuszczony zakres', blocked=True)
                    url = target
                    headers = {'User-Agent': USER_AGENT}
                    cache = representations.get(url)
                    continue
                if r.status_code == 304:
                    if not cache:
                        raise SourceError('304 bez zapisanej reprezentacji')
                    if not robots:
                        self.checked_payloads += 1
                        self.unchanged_payloads += 1
                    return cache[0]
                if robots and r.status_code == 404:
                    return b'' if binary else ''
                if r.status_code in (401, 403, 429):
                    retry = r.headers.get('retry-after')
                    try:
                        seconds = float(retry)
                    except (TypeError, ValueError):
                        try:
                            seconds = max(0, (parsedate_to_datetime(retry) - self.clock()).total_seconds())
                        except (TypeError, ValueError):
                            seconds = None
                    seconds = max(0, seconds) if seconds is not None and isfinite(seconds) else None
                    raise SourceError(f'HTTP {r.status_code}: dostęp/limit źródła', blocked=r.status_code in (401, 403), retry_after=seconds)
                r.raise_for_status()
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise SourceError(f'Odpowiedź przekracza limit {self.max_response_bytes} bajtów')
                    chunks.append(chunk)
                payload = b''.join(chunks)
                # PDF streams can contain arbitrary text: inspect only HTML-like
                # binary responses for access controls, never decode a PDF.
                html_like = ('html' in r.headers.get('content-type', '').lower()
                             or payload.lstrip().lower().startswith((b'<html', b'<!doctype')))
                if not binary or (html_like and not payload.startswith(b'%PDF-')):
                    text = payload.decode('utf-8-sig', errors='replace')
                    lowered = text.lower()
                    if any(marker in lowered for marker in ('cf-chl-', 'g-recaptcha', 'verify you are human', 'access denied')):
                        raise SourceError('Strona kontroli dostępu zamiast danych', blocked=True)
                value = payload if binary else text
                representations[url] = (value, r.headers.get('etag'), r.headers.get('last-modified'))
                if not robots:
                    self.checked_payloads += 1
                return value
        raise SourceError('Zbyt wiele przekierowań', blocked=True)

    async def check_robots(self, client):
        if self.robots is None:
            text = await self.request(client, f'https://{self.host}/robots.txt', robots=True)
            if '<html' in text.lower() or '<!doctype' in text.lower():
                raise SourceError('Nieznany schemat robots.txt', blocked=True)
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            self.robots = parser
        if not self.robots.can_fetch(USER_AGENT, self.endpoint):
            raise SourceError('robots.txt wyklucza adres adaptera', blocked=True)

    async def fetch(self, client):
        self.checked_payloads = self.unchanged_payloads = 0
        try:
            await self.check_robots(client)
            result = await self.collect(client)
            if (result.status == 'success' and self.checked_payloads > 0
                    and self.checked_payloads == self.unchanged_payloads):
                result.status = 'not_modified'
            return result
        except SourceError as exc:
            return FetchResult(status='error', availability='blocked_access' if exc.blocked else 'enabled',
                               message=str(exc), coverage=self.coverage, retry_after=exc.retry_after)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return FetchResult(status='error', message=f'Błąd źródła: {type(exc).__name__}', coverage=self.coverage)
