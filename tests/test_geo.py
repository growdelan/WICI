"""The bundled edge index preserves exact rings and each consumer's boundaries."""
import random

import pytest

from wici import aircraft, firms, geo, weather


def reference_provinces(longitude, latitude):
    return sorted(feature['properties']['admin_code'] for feature in geo.features()
                  if geo.contains(feature['geometry'], longitude, latitude))


def source_polygons():
    for feature in geo.features():
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        yield feature['properties'], polygons


def reference_aircraft(longitude, latitude):
    for _, polygons in source_polygons():
        for rings in polygons:
            outer = rings[0]
            if (min(p[0] for p in outer) <= longitude <= max(p[0] for p in outer)
                    and min(p[1] for p in outer) <= latitude <= max(p[1] for p in outer)
                    and weather.inside_ring(latitude, longitude, outer)
                    and not any(weather.inside_ring(latitude, longitude, hole) for hole in rings[1:])):
                return True
    return False


def reference_firms(longitude, latitude):
    for properties, polygons in source_polygons():
        points = [point for rings in polygons for ring in rings for point in ring]
        if not (min(p[0] for p in points) <= longitude <= max(p[0] for p in points)
                and min(p[1] for p in points) <= latitude <= max(p[1] for p in points)):
            continue
        if any(firms.in_ring(longitude, latitude, rings[0])
               and not any(firms.in_ring(longitude, latitude, hole) for hole in rings[1:]) for rings in polygons):
            return properties
    return None


@pytest.mark.parametrize('ring', [
    [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
    [[-2, -.1], [0, .05], [3, -.05], [1, .1], [-2, -.1]],
    [[0, 0], [1, 0], [1, 0], [1, 1], [0, 1]],  # repeated vertex, implicit closing edge
    [[0, 0], [1e-12, 0], [1e-12, 1e-12], [0, 0]],
])
def test_ring_index_matches_boundary_tolerance_and_plain_ray(ring):
    index = geo.RingIndex(ring)
    samples = [(x/20, y/20) for x in range(-4, 6) for y in range(-4, 6)]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        for point in (a, [(a[0]+b[0])/2, (a[1]+b[1])/2]):
            samples.extend((point[0]+dx, point[1]+dy) for dx in (0, -1e-10, -1e-11, 1e-11, 1e-10)
                           for dy in (0, -1e-10, -1e-11, 1e-11, 1e-10))
    for lon, lat in samples:
        assert index.locate(lon, lat) == geo.in_ring((lon, lat), ring)
        assert bool(index.locate(lon, lat, boundary=False)) == weather.inside_ring(lat, lon, ring)


def test_every_bundled_vertex_remains_a_boundary_and_sampled_rays_match():
    for (_, raw_polygons), (_, indexed_polygons, _) in zip(source_polygons(), geo.indexed_provinces()):
        for raw_rings, indexed_rings in zip(raw_polygons, indexed_polygons):
            for ring, index in zip(raw_rings, indexed_rings):
                for lon, lat in ring:
                    assert index.locate(lon, lat) == 2
                for lon, lat in ring[::max(1, len(ring)//12)]:
                    assert bool(index.locate(lon, lat, boundary=False)) == weather.inside_ring(lat, lon, ring)


def test_bundled_assignments_match_reference_for_distinct_points():
    rng = random.Random(20261105)
    points = [(rng.uniform(13, 25), rng.uniform(48, 56)) for _ in range(256)]
    for properties, polygons in source_polygons():
        for rings in polygons:
            points.extend(rings[0][::max(1, len(rings[0])//3)])
    for lon, lat in points:
        assert geo.provinces_for_point(lon, lat) == reference_provinces(lon, lat)
        assert aircraft.in_poland(lat, lon) == reference_aircraft(lon, lat)
        assert firms.province_at(lon, lat) == reference_firms(lon, lat)


def test_consumer_hole_boundary_policies_and_shared_province_borders(monkeypatch):
    outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    hole = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]
    second = [[4, 0], [5, 0], [5, 4], [4, 4], [4, 0]]
    indexes = ((geo.RingIndex(outer), geo.RingIndex(hole)),)
    prepared = (({'admin_code': '01'}, indexes, (0, 0, 4, 4)),
                ({'admin_code': '02'}, ((geo.RingIndex(second),),), (4, 0, 5, 4)))
    monkeypatch.setattr(geo, 'indexed_provinces', lambda: prepared)
    monkeypatch.setattr(firms, 'indexed_provinces', lambda: prepared)
    monkeypatch.setattr(aircraft, 'POLYGONS', ((indexes[0][0].bounds, indexes[0]),))
    monkeypatch.setattr(weather, 'REGION_POLYGONS', {'01': indexes})
    assert geo.provinces_for_point(4, 2) == ['01', '02']
    assert geo.provinces_for_point(1, 1.5) == ['01']
    assert firms.province_at(1, 1.5) is None
    for lon, lat in [(1, 1.5), (2, 1.5), (0, 2), (4, 2), (1.5, 1.5), (3, 3)]:
        expected = weather.inside_ring(lat, lon, outer) and not weather.inside_ring(lat, lon, hole)
        assert aircraft.in_poland(lat, lon) == expected
        assert weather.in_region(lat, lon, '01') == expected


def test_index_is_bounded_by_bundled_edges_not_query_count():
    prepared = geo.indexed_provinces()
    before = sum(len(edges) for _, polygons, _ in prepared for rings in polygons
                 for ring in rings for edges in ring.rows.values())
    for number in range(1000):
        geo.provinces_for_point(14+number/100, 50+number/500)
    after = sum(len(edges) for _, polygons, _ in prepared for rings in polygons
                for ring in rings for edges in ring.rows.values())
    assert after == before
    assert geo.indexed_provinces.cache_info().maxsize == 1
    assert geo.provinces_for_point(None, 52) == []
    assert geo.provinces_for_point(21, None) == []
    for value in (float('nan'), float('inf'), -float('inf')):
        assert geo.provinces_for_point(21, value) == []
        assert not aircraft.in_poland(value, 21)
        assert not weather.in_region(value, 21, '14')
