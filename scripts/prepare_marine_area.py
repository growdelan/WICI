"""Rebuild the offline sea mask from explicitly downloaded EEA and VLIZ GeoJSON.

uv run --group geo python scripts/prepare_marine_area.py --eea FILE --iho FILE
No downloads or geometry dependencies are required at application runtime.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from shapely import make_valid
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import unary_union

EEA = 'https://marine.discomap.eea.europa.eu/arcgis/rest/services/Marine/Marine_regions_subregions/MapServer/2/query'
IHO = 'https://geo.vliz.be/geoserver/MarineRegions/wfs'


def rounded(value):
    if isinstance(value, dict):
        return {key: rounded(part) for key, part in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(part) for part in value]
    return round(value, 6) if isinstance(value, float) else value


def save(geometry, output, sources):
    # Rounding may collapse sub-metre islets; discard collapsed rings, preserving water holes.
    geometry = make_valid(shape(rounded(mapping(geometry))), method='structure', keep_collapsed=False)
    if geometry.geom_type == 'Polygon':
        geometry = MultiPolygon([geometry])
    if not geometry.is_valid or geometry.is_empty:
        raise ValueError('Invalid marine water geometry')
    payload = {'type': 'Feature', 'properties': {
        'name': 'Baltic Sea and Danish Straits including Kattegat',
        'sources': sources, 'simplification_degrees': .0001,
        'note': 'Cartographic water mask; shoreline simplified, not a navigation boundary.'},
        'geometry': mapping(geometry)}
    data = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(data, mtime=0))
    print(f'{output}: {len(data)} bytes raw, {output.stat().st_size} bytes gzip')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eea', type=Path, required=True)
    parser.add_argument('--iho', type=Path, required=True)
    parser.add_argument('--output', type=Path,
        default=Path(__file__).resolve().parents[1]/'src/wici/static/geo/baltic-water.geojson.gz')
    args = parser.parse_args()
    eea = json.loads(args.eea.read_text())
    iho = json.loads(args.iho.read_text())
    baltic = [shape(f['geometry']) for f in eea['features'] if f['properties']['name_text'] == 'Baltic Sea']
    straits = [shape(f['geometry']) for f in iho['features'] if f['properties']['name'] == 'Kattegat']
    if len(baltic) != 1 or len(straits) != 1:
        raise ValueError('Expected exactly one Baltic Sea and one Kattegat feature')
    # EEA has the marine coastline rather than IHO's connected inland lake basins.
    geometry = unary_union(baltic + straits).simplify(.0001, preserve_topology=True)
    sources = [{'name': 'EEA / ETC-ICM / EC, MSFD Baltic Sea marine region', 'url': EEA,
                'sha256': hashlib.sha256(args.eea.read_bytes()).hexdigest()},
               {'name': 'Flanders Marine Institute, IHO Sea Areas v3 (2018), Kattegat',
                'url': IHO, 'doi': 'https://doi.org/10.14284/323',
                'sha256': hashlib.sha256(args.iho.read_bytes()).hexdigest()}]
    save(geometry, args.output, sources)


if __name__ == '__main__':
    main()
