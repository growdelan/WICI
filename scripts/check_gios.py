"""Bounded LIVE smoke: five v1 resources, memory only; no config, DB or collector."""
import asyncio
import json
from datetime import UTC, datetime

import httpx

from wici.gios import GiosService


async def main():
    async with httpx.AsyncClient(headers={'User-Agent': 'WICI-local/GIOS-bounded-verification'}) as client:
        service = GiosService(client, lambda: datetime.now(UTC))
        results = []
        for kind, identity in [('stations', None), ('sensors', 52), ('index', 52),
                               ('data', 14397), ('data', 295)]:
            result = await service.fetch(kind, identity)
            results.append({'kind': kind, 'id': identity, 'status': result['status'],
                            'items': len(result['items']), 'fetched_at': result['fetched_at'],
                            'latest': result.get('latest'), 'message': result['message']})
        print(json.dumps({'checked_at': datetime.now(UTC).isoformat(), 'scope': '5 resources; memory only',
                          'results': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
