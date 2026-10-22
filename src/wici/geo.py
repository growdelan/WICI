"""Local PRG geometry identities and deterministic, hole-aware point assignment."""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).with_name('static') / 'geo'


def on_segment(point, a, b):
    x, y = point
    ax, ay = a[:2]
    bx, by = b[:2]
    return (abs((x-ax)*(by-ay)-(y-ay)*(bx-ax)) < 1e-10
            and min(ax, bx)-1e-10 <= x <= max(ax, bx)+1e-10
            and min(ay, by)-1e-10 <= y <= max(ay, by)+1e-10)


def in_ring(point, ring):
    """Return 0 outside, 1 inside, 2 on a boundary."""
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if on_segment(point, a, b):
            return 2
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return int(inside)


def contains(geometry, longitude, latitude):
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    for rings in polygons:
        if not rings or not in_ring((longitude, latitude), rings[0]):
            continue
        # A hole interior is outside; a shared boundary belongs to both areas.
        if not any(in_ring((longitude, latitude), ring) == 1 for ring in rings[1:]):
            return True
    return False


@lru_cache(maxsize=1)
def units():
    return json.loads((ROOT / 'administrative-units.json').read_text())['units']


@lru_cache(maxsize=2)
def features(level='provinces'):
    return json.loads((ROOT / f'{level}.geojson').read_text())['features']


@lru_cache(maxsize=1)
def province_bounds():
    result = {}
    for feature in features():
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        points = [p for polygon in polygons for ring in polygon for p in ring]
        result[feature['properties']['admin_code']] = [min(p[0] for p in points), min(p[1] for p in points),
                                                      max(p[0] for p in points), max(p[1] for p in points)]
    return result


def provinces_for_point(longitude, latitude):
    if longitude is None or latitude is None:
        return []
    result = []
    bounds = province_bounds()
    for feature in features():
        code = feature['properties']['admin_code']
        west, south, east, north = bounds[code]
        if west <= longitude <= east and south <= latitude <= north and contains(feature['geometry'], longitude, latitude):
            result.append(code)
    return sorted(result)
