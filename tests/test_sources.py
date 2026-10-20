import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from wici.models import Document, SourceMetadata
from wici.sources import IMGWPDFAdapter, RCBAdapter, RSOAdapter, SGAdapter
from wici.sources.base import SourceError
from wici.sources.normalize import geo_index, instant, plain

FIXTURES = Path(__file__).parent / 'fixtures'








def test_rso_synthetic_exercise_and_absent_coordinates():
    result = RSOAdapter().parse(json.loads((FIXTURES / 'rso_synthetic.json').read_text()))
    assert result.status == 'success'
    for d in result.documents:
        Document.model_validate(d)
        event = SourceMetadata.model_validate(d['fields']['event'])
        assert all(x.role == 'notification_area' for x in event.locations)
    assert 'ćwicz' in result.documents[1]['text'].lower()


def test_rso_incomplete_does_not_claim_complete():
    data = json.loads((FIXTURES / 'rso_synthetic.json').read_text())
    data['pagination']['totalitems'] = 122
    assert RSOAdapter().parse(data).status == 'partial'


def test_rso_bad_record_preserves_good_record():
    data = json.loads((FIXTURES / 'rso_synthetic.json').read_text())
    data['newses'][0].pop('id')
    r = RSOAdapter().parse(data)
    assert r.status == 'partial' and len(r.documents) == 1


def test_rso_healthy_empty():
    assert RSOAdapter().parse({'newses': [], 'pagination': {'totalitems': 0}}).status == 'success'




def test_sg_synthetic_advisory_date_stays_date():
    html = (FIXTURES / 'sg_synthetic.html').read_text()
    doc = SGAdapter().parse_article(html, 'https://www.strazgraniczna.pl/pl/aktualnosci/16278,advisory.html')
    Document.model_validate(doc)
    assert doc['fields']['source_published_date'] == '2026-10-12'
    assert doc.get('source_published_at') is None
    assert not doc['fields']['event']['locations']
    assert 'Prace konserwacyjne' in doc['text']


def test_sg_sensitive_details_removed_before_storage():
    html = '''<div id="content"><div class="head"><h2>Jan Kowalski zatrzymany</h2><h3>Patrol funkcjonariuszy przy ulicy Tajnej.</h3></div><section class="metryka"><div class="data">12.10.2026</div></section><article class="txt">Jan Kowalski PESEL 12345678901</article></div>'''
    doc = SGAdapter().parse_article(html, 'https://www.strazgraniczna.pl/pl/aktualnosci/123,test.html')
    serialized = json.dumps(doc, ensure_ascii=False)
    assert 'Kowalski' not in serialized and '12345678901' not in serialized and 'Tajnej' not in serialized
    assert doc['redaction_note']


def test_rcb_synthetic_exercise_always_review():
    html = '<article><h1>Alert RCB - ćwiczenia</h1><div class="date">11.10.2026</div><div class="editor-content">ĆWICZENIA jutro. Zachowaj spokój.</div></article>'
    doc = RCBAdapter().parse_article(html, 'https://www.gov.pl/web/rcb/alert-rcb-synthetic')
    assert 'ĆWICZENIA' in doc['text']
    assert doc['fields']['event']['locations'] == []


def test_times_dst_ambiguity_and_nonexistent_rejected():
    for value in ('2026-10-25 02:30:00', '2026-03-29 02:30:00'):
        with pytest.raises(ValueError):
            instant(value)
    assert instant('2026-10-12 15:00:00') == '2026-10-12T13:00:00+00:00'


def test_html_strips_executable_nodes():
    assert plain('<script>alert(1)</script><b>tekst</b><iframe>bad</iframe>') == 'tekst'


def request(adapter, handler, url=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await adapter.request(client, url or adapter.endpoint)
    return asyncio.run(run())


def test_redirect_does_not_fetch_other_host():
    visited = []
    def handler(req):
        visited.append(str(req.url))
        return httpx.Response(302, headers={'location': 'https://example.org/private'})
    with pytest.raises(SourceError):
        request(IMGWPDFAdapter(), handler)
    assert len(visited) == 1


def test_redirect_same_host_outside_scope_is_blocked():
    with pytest.raises(SourceError):
        request(IMGWPDFAdapter(), lambda req: httpx.Response(302, headers={'location': '/api/data/warningshydro'}))


def test_rcb_unavailable_alert_preserves_other_documents_without_fetching_root():
    visited = []
    listing = '''<main><article><div class="art-prev"><ul>
      <li><div class="title"><a href="/web/rcb/alert-rcb-missing">Alert RCB</a></div><span class="date">13.10.2026</span></li>
      <li><div class="title"><a href="/web/rcb/alert-rcb-present">Alert RCB</a></div><span class="date">13.10.2026</span></li>
      </ul></div></article></main>'''
    def handler(req):
        visited.append(str(req.url))
        if req.url.path == '/robots.txt':
            return httpx.Response(404)
        if req.url.path == '/web/rcb/komunikaty':
            return httpx.Response(200,text=listing)
        if req.url.path == '/web/rcb/alert-rcb-missing':
            return httpx.Response(301,headers={'location':'/'})
        assert req.url.path == '/web/rcb/alert-rcb-present'
        return httpx.Response(200,text=(FIXTURES/'rcb_synthetic.html').read_text())
    async def run():
        adapter = RCBAdapter()
        adapter.clock = lambda: datetime(2026,10,13,tzinfo=UTC)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await adapter.fetch(client)
    result = asyncio.run(run())
    assert result.status == 'partial' and result.availability == 'enabled'
    assert len(result.documents) == 1 and '1 błędów' in result.message
    assert 'https://www.gov.pl/' not in visited


@pytest.mark.parametrize('target',['https://example.org/','http://www.gov.pl/',
    'https://www.gov.pl/web/inna-sekcja','https://www.gov.pl/?redirect=x'])
def test_rcb_root_exception_does_not_allow_other_redirects(target):
    assert not RCBAdapter().unavailable_redirect('https://www.gov.pl/web/rcb/alert-rcb-example',target)


def test_conditional_request_reuses_representation():
    adapter, requests = IMGWPDFAdapter(), []
    def handler(req):
        requests.append(req)
        return httpx.Response(304) if len(requests) == 2 else httpx.Response(200, text='[]', headers={'etag': 'v1'})
    assert request(adapter, handler) == '[]'
    assert request(adapter, handler) == '[]'
    assert requests[1].headers['if-none-match'] == 'v1'


def test_304_without_representation_fails():
    with pytest.raises(SourceError):
        request(IMGWPDFAdapter(), lambda req: httpx.Response(304))


def test_429_backoff_and_body_size_limits():
    with pytest.raises(SourceError) as info:
        request(IMGWPDFAdapter(), lambda req: httpx.Response(429, headers={'retry-after': '120'}))
    assert info.value.retry_after == 120 and not info.value.blocked
    adapter = IMGWPDFAdapter()
    adapter.max_response_bytes = 8
    with pytest.raises(SourceError):
        request(adapter, lambda req: httpx.Response(200, text='123456789'))


def test_antibot_200_not_empty_snapshot():
    with pytest.raises(SourceError):
        request(IMGWPDFAdapter(), lambda req: httpx.Response(200, text='<html>Verify you are human</html>'))


def test_robots_disallow_prevents_endpoint_fetch():
    visited = []
    def handler(req):
        visited.append(str(req.url))
        return httpx.Response(200, text='User-agent: *\nDisallow: /data/')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await IMGWPDFAdapter().fetch(client)
    result = asyncio.run(run())
    assert result.availability == 'blocked_access'
    assert len(visited) == 1 and visited[0].endswith('/robots.txt')


def test_real_prg_complete_and_poland_bounds():
    base = Path(__file__).parents[1] / 'src/wici/static/geo'
    assert len(geo_index()) == 396
    for name, count in [('provinces', 16), ('counties', 380)]:
        data = json.loads((base / f'{name}.geojson').read_text())
        assert len(data['features']) == count
        assert len({f['properties']['admin_code'] for f in data['features']}) == count
        def check(coords):
            if isinstance(coords[0], (float, int)):
                assert 14 <= coords[0] <= 25 and 49 <= coords[1] <= 55
            else:
                for c in coords:
                    check(c)
        for feature in data['features']:
            check(feature['geometry']['coordinates'])


def test_rcb_synthetic_contract_date_and_listing():
    adapter = RCBAdapter()
    urls = adapter.parse_listing((FIXTURES / 'rcb_list_synthetic.html').read_text())
    assert len(urls) == 10
    doc = adapter.parse_article((FIXTURES / 'rcb_synthetic.html').read_text(), urls[0])
    Document.model_validate(doc)
    assert doc['fields']['source_published_date'] == '2026-10-11'
    assert doc['fields']['contract_validated']
    assert 'ćwicz' in (doc['title']+' '+doc['text']).lower()
    assert doc.get('source_published_at') is None


def test_date_only_not_promoted_to_midnight():
    with pytest.raises(ValueError):
        instant('2026-10-12')


def test_geo_hashes_and_vendor_assets_complete():
    import hashlib
    base = Path(__file__).parents[1] / 'src/wici/static'
    metadata = json.loads((base / 'geo/metadata.json').read_text())
    for name, info in metadata['layers'].items():
        assert hashlib.sha256((base / f'geo/{name}.geojson').read_bytes()).hexdigest() == info['output_sha256']
    for name in ('leaflet.js', 'leaflet.css', 'LICENSE', 'images/marker-icon.png', 'images/marker-icon-2x.png', 'images/marker-shadow.png', 'images/layers.png', 'images/layers-2x.png'):
        assert (base / 'vendor/leaflet' / name).stat().st_size > 100
    validation = json.loads((base / 'geo/validation.json').read_text())
    assert validation['provinces']['coverage_valid_after_rounding']
    assert validation['counties']['coverage_valid_after_rounding']
    assert abs(validation['counties']['overlap_km2']) < 0.001
    assert validation['layer_symdiff_fraction'] < 0.0001


def test_operational_or_personal_rso_text_is_not_persisted():
    data = json.loads((FIXTURES / 'rso_synthetic.json').read_text())
    data['newses'][0].update(title='Jan Kowalski poszukiwany',content='Patrol przy Tajnej. PESEL 12345678901',shortcut='Jan Kowalski poszukiwany')
    doc = RSOAdapter().parse(data).documents[0]
    serialized = json.dumps(doc,ensure_ascii=False)
    assert 'Kowalski' not in serialized and '12345678901' not in serialized and 'Tajnej' not in serialized
    assert doc['redaction_note']


@pytest.mark.asyncio
async def test_304_fetch_distinguishes_unchanged_snapshot():
    adapter=IMGWPDFAdapter()
    attempts=0
    def handler(req):
        nonlocal attempts
        if req.url.path=='/robots.txt':
            return httpx.Response(404)
        attempts+=1
        return httpx.Response(304) if attempts>1 else httpx.Response(200,text='<h1>Index of /data/current/ost_meteo</h1>',headers={'etag':'sample'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await adapter.fetch(client)).status=='success'
        assert (await adapter.fetch(client)).status=='not_modified'


@pytest.mark.parametrize('url',['https://www.gov.pl/web/rcb-inna-sekcja/alert','https://www.gov.pl/web/rcb/%2e%2e/inna-sekcja/alert','https://www.gov.pl:444/web/rcb/alert'])
def test_allowlist_does_not_accept_neighbor_paths_or_encoded_traversal(url):
    assert not RCBAdapter().allowed(url)


def test_retry_after_nonfinite_falls_back_to_normal_backoff():
    with pytest.raises(SourceError) as info:
        request(IMGWPDFAdapter(),lambda req:httpx.Response(429,headers={'retry-after':'Infinity'}))
    assert info.value.retry_after is None


def test_far_future_validity_sentinel_never_becomes_real_date():
    data=json.loads((FIXTURES/'rso_synthetic.json').read_text())
    data['newses'][0]['valid_to']='9999-12-31 23:59:59'
    doc=RSOAdapter().parse(data).documents[0]
    assert not doc['fields']['event'].get('valid_until')
    assert doc['fields']['source_validity_original']['valid_to']=='9999-12-31 23:59:59'


def test_rso_timezone_assumption_and_original_times_are_saved():
    row=json.loads((FIXTURES/'rso_synthetic.json').read_text())
    doc=RSOAdapter().parse(row).documents[0]
    assert 'Europe/Warsaw' in doc['fields']['source_timezone_assumption']
    assert doc['fields']['source_times_original']['created_at']==row['newses'][0]['created_at']
