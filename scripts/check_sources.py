"""Explicit live probe, outside default tests. No database or original text output."""
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from wici.sources import ADAPTERS


async def main():
    results={}
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
        for source,adapter in ADAPTERS.items():
            result=await adapter.fetch(client)
            results[source]={'endpoint':adapter.endpoint,'status':result.status,'availability':result.availability,
                'documents':len(result.documents),'message':result.message,'coverage':result.coverage}
    output={'checked_at':datetime.now(UTC).isoformat(),'method':'controlled local httpx adapter fetch; no database write; no access-control bypass','results':results}
    path=Path(__file__).resolve().parents[1]/'tmp'/'live-checks'/'source-probe.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':
    asyncio.run(main())
