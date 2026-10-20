"""Binary publisher retrieval keeps PDF bytes and transport safeguards intact."""
import asyncio

import httpx
import pytest

from wici.sources.base import Adapter, SourceError


class PDFAdapter(Adapter):
    host = 'publisher.example'
    path_prefix = '/warnings'
    endpoint = 'https://publisher.example/warnings/current.pdf'


def retrieve(adapter, handler, *, binary=True):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await adapter.request(client, adapter.endpoint, binary=binary)
    return asyncio.run(run())


def test_pdf_bytes_and_conditional_cache_counters():
    adapter, requests = PDFAdapter(), []
    payload = b'%PDF-1.7\n\xff\x00access denied\n%%EOF'
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, content=payload, headers={'etag': 'pdf-v1', 'last-modified': 'Mon, 12 Oct 2026 10:00:00 GMT'})
        return httpx.Response(304)
    assert retrieve(adapter, handler) == payload
    assert retrieve(adapter, handler) == payload
    assert requests[1].headers['if-none-match'] == 'pdf-v1'
    assert 'if-modified-since' in requests[1].headers
    assert adapter.checked_payloads == 2
    assert adapter.unchanged_payloads == 1
    assert adapter.binary_cache[adapter.endpoint][0] == payload
    assert adapter.cache == {}


def test_binary_size_limit_counts_bytes_and_does_not_cache():
    adapter = PDFAdapter()
    adapter.max_response_bytes = 8
    with pytest.raises(SourceError, match='8 bajtów'):
        retrieve(adapter, lambda request: httpx.Response(200, content=b'%PDF-\xff\xff\xff\xff'))
    assert not adapter.binary_cache
    assert adapter.checked_payloads == 0


@pytest.mark.parametrize('target', ['https://other.example/warnings/doc.pdf', '/private/doc.pdf'])
def test_binary_redirect_scope_is_enforced(target):
    adapter, visited = PDFAdapter(), []
    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={'location': target})
    with pytest.raises(SourceError) as error:
        retrieve(adapter, handler)
    assert error.value.blocked
    assert visited == [adapter.endpoint]


@pytest.mark.parametrize('headers,body', [
    ({'content-type': 'text/html'}, b'<div class="cf-chl-test">challenge</div>'),
    ({}, b'  <!DOCTYPE html><html>Verify you are human</html>'),
])
def test_binary_html_access_controls_are_blocked(headers, body):
    adapter = PDFAdapter()
    with pytest.raises(SourceError) as error:
        retrieve(adapter, lambda request: httpx.Response(200, content=body, headers=headers))
    assert error.value.blocked
    assert not adapter.binary_cache


def test_text_and_binary_caches_do_not_share_validators_or_representations():
    adapter, requests = PDFAdapter(), []
    def handler(request):
        requests.append(request)
        if len(requests) <= 2:
            return httpx.Response(200, content=b'%PDF-\xff', headers={'etag': f'v{len(requests)}'})
        return httpx.Response(304)
    assert retrieve(adapter, handler, binary=False) == '%PDF-\ufffd'
    assert retrieve(adapter, handler) == b'%PDF-\xff'
    assert 'if-none-match' not in requests[1].headers
    assert retrieve(adapter, handler, binary=False) == '%PDF-\ufffd'
    assert requests[2].headers['if-none-match'] == 'v1'
    assert retrieve(adapter, handler) == b'%PDF-\xff'
    assert requests[3].headers['if-none-match'] == 'v2'


def test_binary_304_cannot_reuse_text_cache():
    adapter = PDFAdapter()
    adapter.cache[adapter.endpoint] = ('text', 'v1', None)
    with pytest.raises(SourceError, match='304'):
        retrieve(adapter, lambda request: httpx.Response(304))
