"""Explicit, bounded NEPTUN probe; no WICI database, keys or other collectors."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from wici.ukraine import UkraineService


async def probe():
    requests = []

    async def record(response):
        requests.append({'path': response.request.url.path, 'status': response.status_code})

    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False,
        headers={'User-Agent': 'WICI-local/0.1 (private local pilot)'},
        event_hooks={'response': [record]},
    ) as client:
        service = UkraineService(client, lambda: datetime.now(UTC))
        geometry = await service.geometry()
        snapshot = await service.fetch()
        # A second read must reuse the shared in-memory cache.
        first_count = len(requests)
        cached = await service.fetch()
        keys = {
            scope: {feature['properties']['key'] for feature in geometry.get(collection, {}).get('features', [])}
            for scope, collection in [('oblast', 'oblasts'), ('raion', 'raions')]
        }
        alerts = snapshot.get('alerts', {})
        threats = snapshot.get('threats', {})
        return {
            'checked_at': datetime.now(UTC).isoformat(),
            'source': 'https://neptun.in.ua/',
            'status': snapshot.get('status'),
            'geometry_status': geometry.get('status'),
            'requests': requests,
            'second_read_used_cache': first_count == len(requests),
            'cached_status': cached.get('status'),
            'geometry_counts': {scope: len(values) for scope, values in keys.items()},
            'alert_count': len(alerts.get('items', [])),
            'unmatched_alert_count': sum(item['key'] not in keys.get(item['scope'], set())
                                         for item in alerts.get('items', [])),
            'threat_count': len(threats.get('items', [])),
            'area_only_count': sum(item.get('area_only', False) for item in threats.get('items', [])),
            'advisory_count': sum(item.get('advisory', False) for item in threats.get('items', [])),
            'components': {
                name: {key: component.get(key) for key in
                       ('status', 'fetched_at', 'updated_at', 'server_time', 'stale', 'error',
                        'invalid_count', 'stale_count')}
                for name, component in [('alerts', alerts), ('threats', threats)]
            },
            'limitations': 'One bounded access sample, not validation of coverage or real-world attacks. '
                            'No current locations, trajectories or raw messages are saved.',
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('tmp/live-checks/ukraine-live.json'))
    args = parser.parse_args()
    result = asyncio.run(probe())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Filtering expired reports is expected and is explicitly represented as partial.
    valid = (result['status'] in ('ready', 'partial') and result['geometry_status'] == 'ready'
             and result['unmatched_alert_count'] == 0 and result['second_read_used_cache']
             and all(not part['error'] and not part['invalid_count'] for part in result['components'].values()))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
