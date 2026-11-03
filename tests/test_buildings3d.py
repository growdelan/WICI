"""Synthetic MVT geometry: heights, holes, clipping, budgets and source lifecycle."""
import asyncio
import math

import httpx
import mapbox_vector_tile
import pytest
from shapely.geometry import MultiPolygon, Polygon, shape

from wici.buildings3d import LEVEL, MAX_BUILDINGS, decode_buildings, tile_bounds
from wici.scene3d import BUILDINGS_URL, Scene3DService

X, Y = 9148, 5395
TEMPLATE = 'https://tiles.openfreemap.org/planet/synthetic_20261103/{z}/{x}/{y}.pbf'


def encode(features):
    return mapbox_vector_tile.encode({'name': 'building', 'features': features},
                                    default_options={'y_coord_down': True})


def feature(geometry=None, **properties):
    return {'geometry': geometry or Polygon([(20, 20), (60, 20), (60, 60), (20, 60)]),
            'properties': properties}


def test_building_polygons_preserve_holes_parts_heights_and_skip_parent_outlines():
    courtyard = Polygon([(100, 100), (400, 100), (400, 400), (100, 400)],
                        holes=[[(200, 200), (200, 300), (300, 300), (300, 200)]])
    multipart = MultiPolygon([Polygon([(500, 100), (600, 100), (600, 200), (500, 200)]),
                              Polygon([(700, 100), (800, 100), (800, 200), (700, 200)])])
    data = encode([feature(courtyard, render_height=24, render_min_height=3),
                   feature(multipart, render_height=12), feature(hide_3d=True),
                   feature(render_height=4, render_min_height=5)])
    items, truncated, skipped = decode_buildings(data, X, Y)
    assert len(items) == 3 and not truncated and skipped == 1
    assert len(items[0]['rings']) == 2
    assert items[0]['height'] == 24 and items[0]['min_height'] == 3
    assert len({item['id'] for item in items}) == 3
    for item in items:
        assert shape({'type': 'Polygon', 'coordinates': item['rings']}).is_valid
        assert item['rings'][0][0] == item['rings'][0][-1]


def test_clips_tile_buffers_and_converts_mercator_y_in_correct_direction():
    items, _, _ = decode_buildings(encode([feature(Polygon([(-20, -20), (50, -20), (50, 50), (-20, 50)]))]), X, Y)
    west, south, east, north = tile_bounds(X, Y)
    points = items[0]['rings'][0]
    assert min(p[0] for p in points) == pytest.approx(west, abs=1e-7)
    assert max(p[1] for p in points) == pytest.approx(north, abs=1e-7)
    assert all(west-1e-7 <= p[0] <= east+1e-7 and south-1e-7 <= p[1] <= north+1e-7 for p in points)
    assert items[0]['height'] == 9 and items[0]['min_height'] == 0
    assert decode_buildings(b'', X, Y) == ([], False, 0)
    assert tile_bounds(X, Y)[2] == tile_bounds(X+1, Y)[0]
    assert tile_bounds(X, Y)[1] == tile_bounds(X, Y+1)[3]
    with pytest.raises(ValueError):
        tile_bounds(2**LEVEL, 0)
    with pytest.raises(ValueError):
        decode_buildings(b'broken tile', X, Y)


def test_geometry_budget_limits_dense_tiles_and_simplifies_complex_rings():
    points = [(2000+100*math.cos(i*math.pi/150), 2000+100*math.sin(i*math.pi/150)) for i in range(300)]
    items, truncated, _ = decode_buildings(encode([feature() for _ in range(MAX_BUILDINGS+1)]), X, Y)
    assert len(items) == MAX_BUILDINGS and truncated
    assert len({item['id'] for item in items}) == MAX_BUILDINGS
    items, _, skipped = decode_buildings(encode([feature(Polygon(points))]), X, Y)
    assert len(items) == 1 and skipped == 0
    assert len(items[0]['rings'][0]) < 257


@pytest.mark.asyncio
async def test_building_tiles_share_metadata_coalesce_and_reuse_cache():
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(.01)
        if str(request.url) == BUILDINGS_URL:
            return httpx.Response(200, json={'tiles': [TEMPLATE]})
        return httpx.Response(200, content=encode([feature(render_height=10)]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = Scene3DService(client)
        first, duplicate, neighbour = await asyncio.wait_for(asyncio.gather(
            service.buildings(X, Y), service.buildings(X, Y), service.buildings(X+1, Y)), timeout=3)
        assert first == duplicate and neighbour['status'] == first['status'] == 'ready'
        assert len(first['items']) == 1 and first['license'] == 'ODbL 1.0'
        assert len(calls) == 3
        await service.buildings(X, Y)
        assert len(calls) == 3
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['status', 'metadata', 'redirect', 'size', 'geometry'])
async def test_building_failures_are_nonfatal_cached_and_do_not_fetch_foreign_urls(problem):
    calls = []
    def handler(request):
        calls.append(request)
        if str(request.url) == BUILDINGS_URL:
            if problem == 'status':
                return httpx.Response(503)
            return httpx.Response(200, json={'tiles': [] if problem == 'metadata' else
                                           ['https://example.com/{z}/{x}/{y}.pbf' if problem == 'redirect' else TEMPLATE]})
        return httpx.Response(200, content=b'x'*4_000_001 if problem == 'size' else b'broken tile')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = Scene3DService(client)
        assert (await service.buildings(X, Y))['status'] == 'unavailable'
        count = len(calls)
        assert (await service.buildings(X, Y))['status'] == 'unavailable'
        assert len(calls) == count and all('example.com' not in str(call.url) for call in calls)
        await service.close()


@pytest.mark.asyncio
async def test_buildings_demo_disabled_and_outside_poland_are_offline():
    def forbidden(request):
        raise AssertionError(f'Unexpected request: {request.url}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        for options in ({'demo': True}, {'enabled': False}):
            assert (await Scene3DService(client, **options).buildings(X, Y))['status'] == 'empty'
        assert (await Scene3DService(client).buildings(0, 0))['status'] == 'empty'


def test_touching_buildings_in_one_height_group_are_not_discarded():
    a = Polygon([(100, 100), (200, 100), (200, 200), (100, 200)])
    b = Polygon([(200, 100), (300, 100), (300, 200), (200, 200)])
    group = MultiPolygon([a, b])
    assert not group.is_valid  # This is how real Podzamcze tiles group blocks.
    items, truncated, skipped = decode_buildings(encode([feature(group, render_height=30)]), X, Y)
    assert len(items) == 2 and skipped == 0 and not truncated
    assert all(item['height'] == 30 for item in items)
