"""Explicit LIVE smoke test: at most 3 Catalog queries and 6 small Process requests.

Run: uv run python scripts/check_sentinel5p.py --day YYYY-MM-DD
The optional --use-existing-cdse enables this probe in memory only; no config file is written.
"""
import argparse
import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from wici.config import Config
from wici.sentinel5p import PARAMETERS, Sentinel5PError, Sentinel5PService, selection

LIMITATIONS = [
    'Jedna obserwacja na parametr i jeden wybrany dzień UTC; nie weryfikuje kompletności archiwum.',
    'Dwa rastry tego samego produktu: minQa=0 i próg produktu; footprint katalogu jest przybliżony.',
    'Przedział czasu pochodzi z nazwy produktu. Czas generacji nie jest czasem publikacji w CDSE.',
    'Nie zmierzono opóźnienia publikacji NRT ani gwarancji dostępności w ciągu 3 godzin.',
    'CDSE nie dokumentuje wariantu wysokościowego SO2. WICI nie przypisuje stałej wysokości warstwy.',
    'UVAI 2.09.01: znane przesunięcie około +0,2 indeksu nie jest usuwane przez QA; brak własnej korekty.',
    'Ujemne wartości i zera pozostają prawidłowymi retrievalami; brak sygnału nie oznacza czystego powietrza.',
]


async def run_probe(config, day, directory, client):
    """Return sanitized evidence; caller controls network client and destination."""
    selection('no2', day)
    service = Sentinel5PService(client, config)
    report = {'checked_at': datetime.now(UTC).isoformat(), 'selected_day': day,
              'status': 'unconfigured' if not service.enabled else 'checked', 'searches': 0,
              'render_attempts': 0, 'catalog_results': [], 'results': [], 'limitations': LIMITATIONS}
    try:
        if not service.enabled:
            report['message'] = service.status()['message']
            return report
        for parameter in PARAMETERS:
            try:
                report['searches'] += 1
                found = await service.search(parameter, day)
                report['catalog_results'].append({
                    'parameter': parameter, 'status': found['status'], 'count': len(found['items']),
                    'truncated': found.get('truncated', False),
                    'unsupported_product_count': found.get('unsupported_product_count', 0),
                    'message': found.get('message', ''), 'fetched_at': found.get('fetched_at')})
                if not found['items']:
                    report['results'].append({'parameter_id': parameter, 'status': 'no_data',
                                              'message': found.get('message', '')})
                    continue
                report['render_attempts'] += 1
                result = await service.render(parameter, day, found['items'][0]['id'])
                directory.mkdir(parents=True, exist_ok=True)
                for key in ('image', 'mask'):
                    filename = f'live-{parameter}-{key}.png'
                    (directory/filename).write_bytes(base64.b64decode(result.pop(key), validate=True))
                    result[key+'_file'] = filename
                report['results'].append(result)
            except Sentinel5PError as exc:
                report['results'].append({'parameter_id': parameter, 'status': exc.status,
                                          'http_status': exc.code, 'message': str(exc),
                                          'retry_after_seconds': exc.retry})
                report['status'] = 'partial'
                # Do not spend more quota after auth/account/rate-limit responses.
                if exc.code in (401, 403, 429) or exc.retry:
                    break
        if any(result['status'] not in ('ready',) for result in report['results']):
            report['status'] = 'partial'
        return report
    finally:
        await service.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day', default=(datetime.now(UTC).date()-timedelta(days=1)).isoformat(),
                        help='Jeden dzień UTC (domyślnie wczoraj); nigdy nie zastępuje go innym dniem.')
    parser.add_argument('--use-existing-cdse', action='store_true',
                        help='Włącz wyłącznie tę próbę w pamięci, z istniejącym klientem CDSE '
                             '(Sentinel-5P lub fallback Sentinel-2). Nie zmienia config.local.toml.')
    parser.add_argument('--output', type=Path, default=Path('tmp/live-checks/sentinel5p'),
                        help='Katalog na bezpieczne metadane JSON i PNG.')
    args = parser.parse_args()
    try:
        selection('no2', args.day)
    except ValueError as exc:
        parser.error(str(exc))
    config = Config.load()
    if args.use_existing_cdse:
        config = config.model_copy(deep=True)
        config.sources.setdefault('sentinel5p', {})['enabled'] = True
    counts = {'oauth': 0, 'catalog': 0, 'process': 0}
    async def count_request(request):
        key = 'oauth' if request.url.path.endswith('/token') else (
            'catalog' if request.url.path.endswith('/search') else 'process')
        counts[key] += 1
    async with httpx.AsyncClient(event_hooks={'request': [count_request]}) as client:
        report = await run_probe(config, args.day, args.output, client)
    report['request_counts'] = counts
    report['ephemeral_enable'] = args.use_existing_cdse
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'live.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(f"LIVE {report['status']}: dzień {args.day}; żądania {counts}")
    if report.get('message'):
        print(report['message'])
    for result in report['results']:
        parameter = result.get('parameter', {}).get('id', result.get('parameter_id'))
        print(parameter, result['status'], result.get('item', {}).get('id', ''),
              'ważne piksele:', result.get('quality', {}).get('valid_percent', '—'), '%')
    print('Ograniczenia i pochodzenie zapisano w', args.output/'live.json')
    if report['status'] != 'checked':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
