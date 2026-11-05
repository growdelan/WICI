"""Local PRG geometry identities and deterministic, hole-aware point assignment."""
import json
import math
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).with_name('static') / 'geo'
EDGE_EPSILON = 1e-10
EDGE_ROWS_PER_DEGREE = 20


class RingIndex:
    """Index exact edges of a bundled ring; no rounding or simplification.

    A horizontal ray only meets edges spanning its latitude. Boundary checks
    use the original tolerance, including horizontal and zero-length edges.
    This index is built only for the finite bundled PRG dataset, not queries.
    """

    def __init__(self, ring):
        self.bounds = (min(p[0] for p in ring), min(p[1] for p in ring),
                       max(p[0] for p in ring), max(p[1] for p in ring))
        rows = defaultdict(list)
        for a, b in zip(ring, ring[1:] + ring[:1]):
            ax, ay = a[:2]
            bx, by = b[:2]
            edge = (ax, ay, bx, by)
            first = math.floor((min(ay, by)-EDGE_EPSILON)*EDGE_ROWS_PER_DEGREE)
            last = math.floor((max(ay, by)+EDGE_EPSILON)*EDGE_ROWS_PER_DEGREE)
            for row in range(first, last+1):
                rows[row].append(edge)
        self.rows = {row: tuple(edges) for row, edges in rows.items()}

    def locate(self, longitude, latitude, *, boundary=True):
        """Return the existing 0/1/2 classification, or plain ray parity."""
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            return 0
        inside = False
        for ax, ay, bx, by in self.rows.get(math.floor(latitude*EDGE_ROWS_PER_DEGREE), ()):
            if (boundary and abs((longitude-ax)*(by-ay)-(latitude-ay)*(bx-ax)) < EDGE_EPSILON
                    and min(ax, bx)-EDGE_EPSILON <= longitude <= max(ax, bx)+EDGE_EPSILON
                    and min(ay, by)-EDGE_EPSILON <= latitude <= max(ay, by)+EDGE_EPSILON):
                return 2
            if (ay > latitude) != (by > latitude) and longitude < (bx-ax)*(latitude-ay)/(by-ay)+ax:
                inside = not inside
        return int(inside)


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


@lru_cache(maxsize=1)
def indexed_provinces():
    """Share one bounded, immutable edge index across the PRG consumers."""
    result = []
    bounds = province_bounds()
    for feature in features():
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        result.append((feature['properties'], tuple(tuple(RingIndex(ring) for ring in rings)
                                                    for rings in polygons),
                       bounds[feature['properties']['admin_code']]))
    return tuple(result)


def provinces_for_point(longitude, latitude):
    if longitude is None or latitude is None:
        return []
    result = []
    for properties, polygons, (west, south, east, north) in indexed_provinces():
        if west <= longitude <= east and south <= latitude <= north and any(
                rings[0].locate(longitude, latitude)
                and not any(hole.locate(longitude, latitude) == 1 for hole in rings[1:])
                for rings in polygons):
            result.append(properties['admin_code'])
    return sorted(result)
