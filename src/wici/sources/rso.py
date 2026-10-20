"""Public RSO JSON /0: all currently exposed communications (not an archive)."""
import json

from .base import Adapter, FetchResult
from .normalize import PROVINCES, document, instant, location, plain


class RSOAdapter(Adapter):
    source_id = 'rso'
    host = 'komunikaty.tvp.pl'
    path_prefix = '/komunikaty'
    path_prefixes = ('/komunikaty', '/komunikatyxml')
    endpoint = 'https://komunikaty.tvp.pl/komunikatyxml/wszystkie/wszystkie/0?_format=json'
    coverage = 'Wszystkie pozycje zwrócone przez publiczny kanał /0; nie archiwum ani gwarancja nadrabiania przerwy.'

    def parse(self, data):
        if (not isinstance(data, dict) or not isinstance(data.get('newses'), list)
                or not isinstance(data.get('pagination'), dict)):
            raise ValueError('Nieznany schemat RSO')  # noqa: TRY004
        total = data['pagination'].get('totalitems')
        if not isinstance(total, int) or total < 0:
            raise ValueError('Niepoprawna liczba totalitems RSO')
        docs, invalid = [], 0
        for row in data['newses']:
            if not isinstance(row, dict) or not row.get('id') or not row.get('title'):
                invalid += 1
                continue
            title, text = plain(row['title']), plain(row.get('content'))
            event={'locations':[]}
            reasons=[]
            provinces = row.get('provinces', {})
            if not isinstance(provinces, dict):
                invalid += 1
                provinces = {}
            for province in provinces.values():
                if isinstance(province, dict):
                    code = PROVINCES.get(province.get('slug_name'))
                    if code:
                        event['locations'].append(location(code, 'notification_area', 'RSO', province.get('name')))
                    else:
                        reasons.append('Nierozpoznane województwo RSO')
            dates = {}
            for original, normalized in (('created_at', 'source_published_at'), ('updated_at', 'source_updated_at')):
                try:
                    dates[normalized] = instant(row.get(original))
                except ValueError:
                    reasons.append(f'Niejednoznaczny {original}')
            try:
                start, end = instant(row.get('valid_from')), instant(row.get('valid_to'))
                if start and end and end > start:
                    event.update(valid_from=start, valid_until=end)
                else:
                    reasons.append('Brak poprawnej ważności')
            except ValueError:
                reasons.append('Niejednoznaczny czas ważności')
            # Public JSON IDs differ from website permalink IDs. The feed is the
            # verified source representation; do not manufacture a document URL.
            url = self.endpoint
            doc = document(self.source_id, row['id'], url, title, text, event, reasons, **dates)
            doc['fields']['source_timezone_assumption'] = 'Godziny RSO bez offsetu są interpretowane jako Europe/Warsaw; niejednoznaczne DST do kontroli.'
            doc['fields']['source_times_original'] = {k: row.get(k) for k in ('created_at', 'updated_at')}
            doc['fields']['source_validity_original'] = {k: row.get(k) for k in ('valid_from', 'valid_to')}
            docs.append(doc)
        partial = invalid or total != len(data['newses'])
        return FetchResult(documents=docs, status='partial' if partial else 'success',
                           message=f'RSO: {len(docs)} komunikatów, {invalid} uszkodzonych; totalitems={total}.',
                           coverage=self.coverage + f' Odczytano {len(data["newses"])}/{total}.')

    async def collect(self, client):
        return self.parse(json.loads(await self.request(client, self.endpoint)))
