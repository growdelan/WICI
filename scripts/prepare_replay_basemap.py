"""Prepare the offline 13–25°E, 48–56°N satellite backdrop from ESA WorldCover 2021.

The replay reads the committed WebP tiles. Run this manually only to rebuild them.
Source and attribution are documented in THIRD_PARTY_NOTICES.md.
"""
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning

OUT = Path(__file__).resolve().parents[1] / 'src/wici/static/geo/flight-satellite'
S3 = 'https://esa-worldcover-s2.s3.eu-central-1.amazonaws.com/rgbnir/2021'
SIZE = 512  # Pixels per geographical degree. Each tile covers two degrees on each axis.


def read_degree(lon, lat):
    url = f'{S3}/N{lat}/ESA_WorldCover_10m_2021_v200_N{lat}E{lon:03d}_S2RGBNIR.tif'
    # Entirely offshore grid cells may be absent from the source mosaic.
    background = np.array([32, 49, 58], dtype='uint8')[:, None, None]
    status = httpx.head(url, timeout=20)
    if status.status_code == 404:
        return np.broadcast_to(background, (3, SIZE, SIZE))
    status.raise_for_status()
    settings = {'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR', 'GDAL_HTTP_TIMEOUT': '30', 'GDAL_HTTP_MAX_RETRY': '2'}
    with rasterio.Env(**settings), rasterio.open(url) as ds:
        rgb = ds.read((1, 2, 3), out_shape=(3, SIZE, SIZE), resampling=Resampling.bilinear)
    # A common reflectance stretch preserves brightness differences across tile borders.
    scaled = np.clip((rgb.astype('float32') - 100) / 2300, 0, 1) ** 0.66
    return np.where(rgb.any(axis=0), np.round(255 * scaled).astype('uint8'), background)


def build_tile(x, y, stage):
    pixels = np.empty((3, 2 * SIZE, 2 * SIZE), dtype='uint8')
    for row in range(2):
        for column in range(2):
            lon = 13 + 2 * x + column
            lat = 55 - 2 * y - row
            pixels[:, row * SIZE:(row + 1) * SIZE, column * SIZE:(column + 1) * SIZE] = read_degree(lon, lat)
    # Blend the outer edge of the regional imagery into the global basemap.
    centers = (np.arange(2 * SIZE) + 0.5) / SIZE
    east = 2 * x + centers
    south = 2 * y + centers
    margin = np.minimum(np.minimum(east, 12 - east), np.minimum(south, 8 - south)[:, None])
    fraction = np.clip(margin / 0.75, 0, 1)
    opacity = np.round(255 * fraction ** 2 * (3 - 2 * fraction)).astype('uint8')
    path = stage / f'{x}-{y}.webp'
    with rasterio.open(path, 'w', driver='WEBP', width=2 * SIZE, height=2 * SIZE,
                       count=4, dtype='uint8', quality=84) as tile:
        tile.write(pixels, indexes=(1, 2, 3))
        tile.write(opacity, 4)
    return path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=OUT) as temp, warnings.catch_warnings():
        warnings.simplefilter('ignore', NotGeoreferencedWarning)
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(build_tile, x, y, Path(temp)) for y in range(4) for x in range(6)]
            tiles = [future.result() for future in futures]
        for path in tiles:
            path.replace(OUT / path.name)
    print(f'Zapisano {len(tiles)} kafli podkładu satelitarnego w {OUT}')


if __name__ == '__main__':
    main()
