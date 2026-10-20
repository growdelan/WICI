"""Real coastline cases: Baltic water and Danish straits, no inland or North Sea."""
import pytest

from wici.marine_area import in_baltic


@pytest.mark.parametrize('name,lat,lon', [
    ('Gulf of Gdansk', 54.5, 18.6), ('Baltic proper', 56, 19),
    ('Gulf of Bothnia', 64, 22), ('Gulf of Finland', 60, 27), ('Gulf of Riga', 57.5, 23.5),
    ('Great Belt', 55.35, 11), ('Little Belt', 55.4, 9.75),
    ('Oresund', 55.8, 12.7), ('Kattegat', 56.8, 11.7),
])
def test_baltic_and_danish_straits_are_included(name, lat, lon):
    assert in_baltic(lat, lon), name


@pytest.mark.parametrize('name,lat,lon', [
    ('North Sea', 56, 8), ('Skagerrak', 58.1, 10), ('Oslofjord', 59.5, 10.6),
    ('Elbe in Hamburg', 53.54, 9.96), ('Kiel Canal', 54.31, 9.7),
    ('Oder in Szczecin', 53.43, 14.58), ('Vistula in Gdansk', 54.3, 18.65),
    ('Neva in St Petersburg', 59.96, 30.32), ('Lake Malaren', 59.32, 17.95),
    ('Lake Ladoga', 61, 30.8), ('Lake Saimaa', 61.2, 28.2), ('Lake Vanern', 58.8, 13.3),
    ('Gotland island', 57.5, 18.5), ('Danish mainland', 56, 9.5),
])
def test_other_seas_land_rivers_canals_and_lakes_are_excluded(name, lat, lon):
    assert not in_baltic(lat, lon), name


@pytest.mark.parametrize('lat,lon', [
    (None, 19), (55, '19'), (True, 19), (55, False),
    (float('nan'), 19), (55, float('inf')), (10**1000, 19), (55, 10**1000),
])
def test_invalid_coordinates_fail_closed(lat, lon):
    assert not in_baltic(lat, lon)
