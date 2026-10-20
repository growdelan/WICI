"""Opt-in real provider verification. uv run python scripts/check_gfm.py

Saves only metadata, a rendered AOI and independent native-pixel checks (no whole COGs).
"""
import argparse
import asyncio
import base64
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import transform, transform_bounds

from wici.gfm import GDALRangeReader, GFMService, cog_errors

BOX = (16.55, 50.35, 16.75, 50.55)
ITEM = 'ENSEMBLE_FLOOD_20240915T050149_VV_EU020M_E051N018T3'


async def main(current=False):
    directory = Path('tmp/live-checks/gfm/current' if current else 'tmp/live-checks/gfm')
    identifier = 'ENSEMBLE_FLOOD_20261017T050827_VV_EU020M_E051N018T3' if current else ITEM
    directory.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        svc = GFMService(client, lambda: datetime.now(UTC))
        search = await svc.search(BOX, '2026-10-17' if current else '2024-09-14',
                                  '2026-10-17' if current else '2024-09-17')
        result = await svc.render(identifier, BOX)
        product = svc.products[identifier][1]
    image = base64.b64decode(result.pop('image'))
    (directory/'klodzko.png').write_bytes(image)
    (directory/'product.json').write_text(json.dumps(product, indent=2)+'\n')
    # Independently sample native COG at destination pixel centres; compare rendered colours.
    with rasterio.io.MemoryFile(image) as memory, memory.open() as raster:
        pixels = raster.read()
        rows, cols = np.where((pixels[0] == 225) & (pixels[1] == 30))
        assert len(rows) > 0, 'No flood pixels in real product'
        height, width = raster.height, raster.width
    dst = from_bounds(*transform_bounds('EPSG:4326', 'EPSG:3857', *BOX), width, height)
    pairs = [(int(rows[i]), int(cols[i])) for i in np.linspace(0, len(rows)-1, 5, dtype=int)]
    checks = []
    budget = {'bytes': 0, 'requests': 0, 'deadline': time.monotonic()+40}
    url = product['assets']['ensemble_flood_extent']['href']
    with cog_errors(budget), httpx.Client() as client, rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'):
        def opener(path, mode='rb'):
            if path != url:
                raise FileNotFoundError(path)
            return GDALRangeReader(url, client, budget)
        with rasterio.open(url, opener=opener, driver='GTiff') as src:
            for row, col in pairs:
                x, y = dst*(col+.5, row+.5)
                lon, lat = transform('EPSG:3857', 'EPSG:4326', [x], [y])
                sx, sy = transform('EPSG:3857', src.crs, [x], [y])
                value = int(next(src.sample([(sx[0], sy[0])]))[0])
                assert value == 1, (row, col, value)
                checks.append({'overlay_row': row, 'overlay_col': col, 'lon': lon[0], 'lat': lat[0],
                               'native_flood_value': value})
    result['verification'] = {'checked_at': datetime.now(UTC).isoformat(), 'bbox': BOX,
        'png_sha256': hashlib.sha256(image).hexdigest(), 'native_pixel_checks': checks,
        'scope': 'Georeferencing / native-class agreement, not independent thematic flood validation',
        'search': search, 'attribution': product['attribution']}
    (directory/'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'counts': result['counts'], 'source_counts': result['source_counts'],
                      'transfer': result['transfer'], 'native_checks': checks}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', action='store_true', help='Zweryfikuj obserwację 2026-10-17')
    asyncio.run(main(parser.parse_args().current))
