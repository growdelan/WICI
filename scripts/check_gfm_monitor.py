"""Opt-in: real national catalog, ONE recent native tile, independent pixel checks.

uv run python scripts/check_gfm_monitor.py
No whole TIFF downloads or background monitor. Writes metadata and small evidence only.
"""
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.warp import transform
from rasterio.windows import Window

from wici.gfm import REQUIRED, GDALRangeReader, GFMService, classify, cog_errors
from wici.gfm_monitor import GFMMonitor, scan_product


async def main():
    directory = Path('tmp/live-checks/gfm/monitor')
    directory.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        mon = GFMMonitor(GFMService(client, lambda: datetime.now(UTC)))
        await mon._catalog()
    # Prefer the Poland/Kłodzko tile if available; otherwise newest complete product.
    complete = [item for item in mon.catalog if not item['missing_assets']]
    item = next((item for item in complete if 'E051N018T3' in item['id']), complete[0])
    started = time.monotonic()
    record = await asyncio.to_thread(scan_product, item, mon.geometries)
    elapsed = time.monotonic()-started
    mon.records[item['key']] = record
    summary = mon._snapshot(None)
    assert record['total'] > 0, 'No positive pixels in selected real product; choose another product to verify placement'
    selected = record['points'][np.linspace(0, len(record['points'])-1, 5, dtype=int)]
    checks, values = [], []
    budget = {'bytes': 0, 'requests': 0, 'deadline': time.monotonic()+40}
    with cog_errors(budget), httpx.Client() as client, rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'):
        for name in REQUIRED:
            url = item['assets'][name]['href']
            def opener(path, mode='rb', url=url):
                if path != url:
                    raise FileNotFoundError(path)
                return GDALRangeReader(url, client, budget)
            with rasterio.open(url, opener=opener, driver='GTiff') as src:
                values.append([int(src.read(1, window=Window(int(col), int(row), 1, 1))[0, 0])
                               for row, col, *_ in selected])
    assert np.all(classify(*(np.array(v, dtype='uint8') for v in values)) == 1)
    affine = rasterio.Affine(*record['grid']['transform'])
    for index, (row, col, flags, likelihood) in enumerate(selected):
        x, y = affine*(int(col)+.5, int(row)+.5)
        lon, lat = transform(record['grid']['crs'], 'EPSG:4326', [x], [y])
        detail = mon._snapshot((lon[0]-.000001,lat[0]-.000001,lon[0]+.000001,lat[0]+.000001))
        assert any(f['properties']['pixels'] for f in detail['features'])
        checks.append({'row': int(row), 'col': int(col), 'lon': lon[0], 'lat': lat[0],
                       'native_required_values': [v[index] for v in values], 'flags': int(flags),
                       'likelihood': int(likelihood), 'subpixel_view_has_native_geometry': True})
    evidence = {'checked_at': datetime.now(UTC).isoformat(), 'catalog_products': len(mon.catalog),
        'missing_required_masks': sum(bool(i['missing_assets']) for i in mon.catalog),
        'catalog_limited': mon.limited, 'scanned_products': 1, 'product': item,
        'scan_seconds': elapsed, 'native_flood_pixels_in_poland': record['total'],
        'clusters': len(summary['clusters']), 'transfer': record['transfer'], 'cache_bytes': record['size'],
        'native_checks': checks, 'scope': 'One real tile, native class and georeferencing agreement; not field validation or complete national coverage'}
    (directory/'verification.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps({k:v for k,v in evidence.items() if k != 'product'}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
