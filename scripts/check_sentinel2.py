"""Explicit bounded LIVE check: one Catalog search, two Process renders, no credential output."""
import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from wici.config import Config
from wici.sentinel2 import SentinelError, SentinelService


async def main():
    config = Config.load()
    directory = Path('tmp/live-checks/sentinel2')
    directory.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        service = SentinelService(client, config)
        if not service.enabled:
            print('LIVE pominięte: brak konfiguracji CDSE.')
            return
        try:
            end = datetime.now(UTC).date()-timedelta(days=1)
            result = await service.search(52.02, 19.12, 4, (end-timedelta(days=45)).isoformat(),
                                          end.isoformat(), 80)
            chosen = []
            for item in reversed(result['items']):
                if not chosen or item['observed_at'][:10] != chosen[-1]['observed_at'][:10]:
                    chosen.append(item)
                if len(chosen) == 2:
                    break
            reports = []
            for index, item in enumerate(reversed(chosen)):
                image = await service.render(52.02, 19.12, 4, item['id'])
                for key in ('image', 'mask'):
                    (directory/f'live-{index}-{key}.png').write_bytes(base64.b64decode(image.pop(key)))
                reports.append(image)
                print('LIVE OK:', item['id'], image['quality'])
            assert len(reports) == 2 and reports[0]['grid'] == reports[1]['grid']
            (directory/'live.json').write_text(json.dumps({'checked_at': datetime.now(UTC).isoformat(),
                'search_count': len(result['items']), 'truncated': result['truncated'],
                'renders': reports}, indent=2))
        except SentinelError as exc:
            print(f'LIVE niedostępne: {exc.code} {exc}')
            raise SystemExit(1) from None
        finally:
            await service.close()


if __name__ == '__main__':
    asyncio.run(main())
