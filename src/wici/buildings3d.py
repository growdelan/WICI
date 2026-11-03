"""Decode ready OSM vector tiles into bounded, clipped building extrusions."""
import math

import mapbox_vector_tile
from google.protobuf.message import DecodeError
from shapely import GEOSException
from shapely.geometry import box, shape

LEVEL = 14
MAX_BUILDINGS = 600
MAX_VERTICES = 30_000


def tile_bounds(x, y):
    if not (0 <= x < 2**LEVEL and 0 <= y < 2**LEVEL):
        raise ValueError('Nieprawidłowy kafel budynków 3D.')
    def lat(y):
        return math.degrees(math.atan(math.sinh(math.pi*(1-2*y/2**LEVEL))))
    return (x/2**LEVEL*360-180, lat(y+1), (x+1)/2**LEVEL*360-180, lat(y))


def elevation(value, fallback):
    if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1000:
        return value
    return fallback


def decode_buildings(body, x, y):
    tile_bounds(x, y)
    try:
        data = mapbox_vector_tile.decode(body, default_options={'y_coord_down': True})
    except (DecodeError, IndexError, KeyError, ValueError) as exc:
        raise ValueError('Nieprawidłowy kafel wektorowy.') from exc
    layer = data.get('building', {})
    extent = layer.get('extent', 4096)
    if not isinstance(extent, int) or not 1 <= extent <= 65536:
        raise ValueError('Nieprawidłowa skala kafla.')
    result, vertices, skipped, truncated = [], 0, 0, False
    clip = box(0, 0, extent, extent)

    def geographic(point):
        lon = (x+point[0]/extent)/2**LEVEL*360-180
        lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+point[1]/extent)/2**LEVEL))))
        return [round(lon, 7), round(lat, 7)]

    for index, feature in enumerate(layer.get('features', [])):
        props = feature.get('properties') or {}
        # OpenMapTiles hides parent outlines when detailed building parts exist.
        if props.get('hide_3d') in (True, 'true', 1):
            continue
        height, minimum = elevation(props.get('render_height'), 9), elevation(props.get('render_min_height'), 0)
        if height <= minimum:
            skipped += 1
            continue
        try:
            geometry = shape(feature.get('geometry'))
            if geometry.geom_type not in ('Polygon', 'MultiPolygon'):
                skipped += 1
                continue
            # Tile generators group touching buildings with the same attributes.
            # Such a MultiPolygon can be invalid as a whole even though every
            # individual building is valid. Validate/clip the parts separately.
            source_parts = list(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else [geometry]
            polygons = []
            for component in source_parts:
                if not component.is_valid:
                    skipped += 1
                    continue
                clipped = component.intersection(clip)
                if not clipped.is_empty:
                    polygons.extend(clipped.geoms if clipped.geom_type == 'MultiPolygon' else [clipped])
        except (GEOSException, ValueError, TypeError, AttributeError):
            skipped += 1
            continue
        for part, polygon in enumerate(polygons):
            if polygon.geom_type != 'Polygon' or polygon.area < 1:
                continue
            rings = [list(polygon.exterior.coords), *[list(h.coords) for h in polygon.interiors]]
            count = sum(len(r) for r in rings)
            if any(len(r) > 257 for r in rings) or len(rings) > 17:
                skipped += 1
                continue
            if len(result) >= MAX_BUILDINGS or vertices+count > MAX_VERTICES:
                truncated = True
                continue
            result.append({'id': f'{x}/{y}/{feature.get("id", index)}/{index}/{part}',
                           'rings': [[geographic(p) for p in ring] for ring in rings],
                           'height': height, 'min_height': minimum})
            vertices += count
    return result, truncated, skipped
