"""Bundled sea-water mask, with latitude-indexed edges and indexed island holes."""
import gzip
import json
from collections import defaultdict
from functools import cache
from itertools import pairwise
from math import floor, isfinite
from pathlib import Path


def cell(value):
    return floor(value*4)


class Ring:
    def __init__(self, points):
        self.bounds = (min(p[0] for p in points), min(p[1] for p in points),
                       max(p[0] for p in points), max(p[1] for p in points))
        self.edges = defaultdict(list)
        for previous, current in pairwise(points):
            x1, y1 = previous
            x2, y2 = current
            if y1 == y2:
                continue
            for row in range(cell(min(y1, y2)), cell(max(y1, y2))+1):
                self.edges[row].append((x1, y1, x2, y2))

    def contains(self, lat, lon):
        left, bottom, right, top = self.bounds
        if not left <= lon <= right or not bottom <= lat <= top:
            return False
        inside = False
        for x1, y1, x2, y2 in self.edges.get(cell(lat), ()):
            if (y1 > lat) != (y2 > lat) and lon < (x2-x1)*(lat-y1)/(y2-y1)+x1:
                inside = not inside
        return inside


class WaterPolygon:
    def __init__(self, coordinates):
        self.outer = Ring(coordinates[0])
        self.holes = defaultdict(list)
        for points in coordinates[1:]:
            ring = Ring(points)
            left, bottom, right, top = ring.bounds
            for row in range(cell(bottom), cell(top)+1):
                for column in range(cell(left), cell(right)+1):
                    self.holes[row, column].append(ring)

    def contains(self, lat, lon):
        return self.outer.contains(lat, lon) and not any(
            hole.contains(lat, lon) for hole in self.holes.get((cell(lat), cell(lon)), ()))


@cache
def water_polygons():
    path = Path(__file__).parent/'static/geo/baltic-water.geojson.gz'
    with gzip.open(path, 'rt') as file:
        geometry = json.load(file)['geometry']
    coordinates = geometry['coordinates']
    return tuple(WaterPolygon(p) for p in coordinates)


def in_baltic(lat, lon):
    if (isinstance(lat, bool) or isinstance(lon, bool)
            or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
            or not 53 <= lat <= 66 or not 9 <= lon <= 31 or not isfinite(lat) or not isfinite(lon)):
        return False
    return any(polygon.contains(lat, lon) for polygon in water_polygons())
