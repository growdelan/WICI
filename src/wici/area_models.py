"""Bounded own-area geometry contracts, independent of optional GIS packages."""
import math
from itertools import pairwise
from typing import Literal

from pydantic import Field, field_validator, model_validator

from wici.workspace_models import StrictModel


def cross(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def on_segment(a, b, p):
    return (abs(cross(a, b, p)) <= 1e-10 and min(a[0], b[0])-1e-10 <= p[0] <= max(a[0], b[0])+1e-10
            and min(a[1], b[1])-1e-10 <= p[1] <= max(a[1], b[1])+1e-10)


def intersects(a, b, c, d):
    return ((cross(a, b, c)*cross(a, b, d) < 0 and cross(c, d, a)*cross(c, d, b) < 0)
            or on_segment(a, b, c) or on_segment(a, b, d) or on_segment(c, d, a) or on_segment(c, d, b))


def point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
            or not -180 <= value[0] <= 180 or not -85 <= value[1] <= 85):
        raise ValueError('Współrzędne wymagają [długość, szerokość] WGS84, szerokość od -85 do 85')
    return list(value)


class AreaInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=5000)
    color: str = Field(default='#238b8e', pattern=r'^#[0-9a-fA-F]{6}$')
    shape: Literal['polygon', 'rectangle', 'circle'] = 'polygon'
    geometry: dict | None = None
    center: list[float] | None = Field(default=None, min_length=2, max_length=2)
    radius_m: float | None = Field(default=None, gt=0, le=1_000_000)
    archived: bool = False
    revision: int | None = Field(default=None, ge=1)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError('Podaj nazwę obszaru')
        return value.strip()

    @model_validator(mode='after')
    def valid_shape(self):
        if self.shape == 'circle':
            if self.center is None or self.radius_m is None or not math.isfinite(self.radius_m):
                raise ValueError('Koło wymaga środka i promienia w metrach')
            self.center = point(self.center)
            # The supported map geometry deliberately does not cross poles/date line.
            spread = self.radius_m/111000/max(.01, math.cos(math.radians(self.center[1])))
            if abs(self.center[0])+spread > 180 or abs(self.center[1])+self.radius_m/111000 > 85:
                raise ValueError('Obszar nie może przecinać południka 180° ani biegunów')
            if self.geometry is not None:
                raise ValueError('Koło zapisuje środek i promień, bez alternatywnej geometrii')
            return self
        if self.center is not None or self.radius_m is not None:
            raise ValueError('Środek i promień dotyczą wyłącznie koła')
        geometry = self.geometry
        if not isinstance(geometry, dict) or set(geometry) != {'type', 'coordinates'} or geometry['type'] != 'Polygon':
            raise ValueError('Wymagany wielokąt GeoJSON Polygon')
        rings = geometry['coordinates']
        if not isinstance(rings, list) or len(rings) != 1 or not isinstance(rings[0], list):
            raise ValueError('Pierwsza wersja obsługuje pojedynczy wielokąt bez otworów')
        ring = [point(p) for p in rings[0]]
        if not 4 <= len(ring) <= 301 or ring[0] != ring[-1]:
            raise ValueError('Zamknięty wielokąt wymaga 3–300 wierzchołków')
        if len({tuple(p) for p in ring[:-1]}) != len(ring)-1:
            raise ValueError('Wierzchołki nie mogą się powtarzać')
        if max(p[0] for p in ring)-min(p[0] for p in ring) > 180:
            raise ValueError('Obszar nie może przecinać południka 180°')
        if abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in pairwise(ring))) < 1e-12:
            raise ValueError('Wielokąt musi mieć dodatnie pole')
        n = len(ring)-1
        for i in range(n):
            for j in range(i+1, n):
                if j == i+1 or (i == 0 and j == n-1):
                    continue
                if intersects(ring[i], ring[i+1], ring[j], ring[j+1]):
                    raise ValueError('Wielokąt nie może przecinać samego siebie')
        if self.shape == 'rectangle':
            xs, ys = {p[0] for p in ring}, {p[1] for p in ring}
            if len(ring) != 5 or len(xs) != 2 or len(ys) != 2 or any(a[0] != b[0] and a[1] != b[1] for a, b in pairwise(ring)):
                raise ValueError('Prostokąt wymaga czterech narożników i boków wzdłuż równoleżników/południków')
        self.geometry = {'type': 'Polygon', 'coordinates': [ring]}
        return self
