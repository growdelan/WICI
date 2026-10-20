"""Rebuild bundled PRG layers from official WFS GML, never at application startup.
Run in a local environment with pyproj and shapely (see docs/sources.md).
Input GML files are downloaded explicitly by the operator; no implicit network.
"""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from pyproj import Transformer
from shapely import coverage_is_valid, coverage_simplify
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform, unary_union

WFS = 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries'
NS = {'gml': 'http://www.opengis.net/gml/3.2', 'wfs': 'http://www.opengis.net/wfs/2.0',
      'ms': 'http://mapserver.gis.umn.edu/mapserver'}


def convert(path, level, tolerance):
    root = ET.parse(path).getroot()
    features = []
    transformer = Transformer.from_crs(2180, 4326, always_xy=True)
    versions = []
    original_geometries = []
    for member in root.findall('wfs:member', NS):
        record = next(iter(member))
        code = record.findtext('ms:JPT_KOD_JE', namespaces=NS)
        name = record.findtext('ms:JPT_NAZWA_', namespaces=NS)
        if not code or not name:
            raise ValueError('PRG record without TERYT/name')
        polygons = []
        for polygon in record.findall('.//gml:Polygon', NS):
            rings = []
            for ring in polygon.findall('.//gml:LinearRing/gml:posList', NS):
                values = list(map(float, ring.text.split()))
                # EPSG:2180 formal axis order is northing/easting in WFS GML.
                rings.append([(values[i+1], values[i]) for i in range(0, len(values), 2)])
            if rings:
                polygons.append(Polygon(rings[0], rings[1:]))
        geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
        if geom.is_empty or not geom.is_valid:
            raise ValueError(f'Invalid original geometry {code}')
        original_geometries.append(geom)
        features.append({'type': 'Feature', 'id': code, 'properties': {'name': name, 'admin_code': code, 'level': level},
                         'geometry': mapping(geom)})
        version = record.findtext('ms:WERSJA_OD', namespaces=NS)
        if version:
            versions.append(version)
    if not coverage_is_valid(original_geometries):
        raise ValueError('Original PRG geometries are not a valid polygon coverage')
    simplified = coverage_simplify(original_geometries, tolerance=tolerance)
    if not coverage_is_valid(simplified):
        raise ValueError('Simplified geometries lost shared-edge coverage')
    for feature, geom in zip(features, simplified, strict=True):
        geom = transform(transformer.transform, geom)
        if not geom.is_valid or geom.is_empty:
            raise ValueError('Invalid transformed geometry')
        feature['geometry'] = mapping(geom)
    expected = int(root.attrib['numberMatched'])
    if len(features) != expected or len({f['id'] for f in features}) != expected:
        raise ValueError('Incomplete PRG response or duplicate administrative codes')
    return {'type': 'FeatureCollection', 'features': features}, {
        'feature_count': len(features), 'wfs_timestamp': root.attrib.get('timeStamp'),
        'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'versions_min': min(versions), 'versions_max': max(versions)}


def write_country_border(output):
    """Dissolve bundled province polygons to exclude internal boundaries."""
    source = output / 'provinces.geojson'
    provinces = json.loads(source.read_text())
    country = unary_union([shape(f['geometry']) for f in provinces['features']])
    border = {'type': 'Feature', 'properties': {
        'name': 'Polska', 'provider': 'GUGiK / PRG',
        'derived_from': 'provinces.geojson',
        'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest()},
        'geometry': mapping(country.boundary)}
    (output / 'poland-border.geojson').write_text(
        json.dumps(border, ensure_ascii=False, separators=(',', ':')) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provinces', type=Path, required=True)
    parser.add_argument('--counties', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).parents[1] / 'src/wici/static/geo')
    parser.add_argument('--tolerance', type=float, default=150)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {'provider': 'Główny Urząd Geodezji i Kartografii — Państwowy Rejestr Granic',
                'source': WFS, 'prepared_at': datetime.now(UTC).isoformat(),
                'input_crs': 'EPSG:2180 (GML northing/easting)', 'output_crs': 'EPSG:4326 (longitude/latitude)',
                'simplification': {'algorithm': 'Visvalingam-Whyatt coverage_simplify; shared edges preserved', 'tolerance_metres': args.tolerance},
                'use': 'Wyłącznie orientacyjny podkład i obszary administracyjne; nie pomiary geodezyjne.',
                'terms': 'https://www.geoportal.gov.pl/pl/dane/panstwowy-rejestr-granic-prg/', 'layers': {}}
    validation, unions = {}, {}
    reverse = Transformer.from_crs(4326, 2180, always_xy=True)
    for name, path in [('provinces', args.provinces), ('counties', args.counties)]:
        collection, info = convert(path, name, args.tolerance)
        target = args.output / f'{name}.geojson'
        # Reduce coordinate serialization precision, retaining geographic shapes.
        encoded = json.dumps(collection, ensure_ascii=False, separators=(',', ':'))
        import re
        encoded = re.sub(r'(-?\d+\.\d{5})\d+', r'\1', encoded)
        target.write_text(encoded + '\n')
        info['output_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        metadata['layers'][name] = info
        rounded = [shape(f['geometry']) for f in json.loads(encoded)['features']]
        metric = [transform(reverse.transform, g) for g in rounded]
        union = unary_union(metric)
        unions[name] = union
        validation[name] = {'valid': all(g.is_valid for g in rounded),
                            'coverage_valid_after_rounding': bool(coverage_is_valid(rounded)),
                            'area_km2': union.area / 1e6,
                            'overlap_km2': (sum(g.area for g in metric) - union.area) / 1e6}
        if not validation[name]['valid'] or not validation[name]['coverage_valid_after_rounding']:
            raise ValueError('Coordinate rounding invalidated polygon coverage')
    write_country_border(args.output)
    difference = unions['counties'].symmetric_difference(unions['provinces']).area
    validation['layer_symdiff_km2'] = difference / 1e6
    validation['layer_symdiff_fraction'] = difference / unions['provinces'].area
    if validation['layer_symdiff_fraction'] > 0.0001:
        raise ValueError('Layer boundary discrepancy exceeds 0.01 percent')
    (args.output / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    (args.output / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    units, input_hashes = {}, {}
    for name in ('provinces.geojson', 'counties.geojson'):
        payload = (args.output / name).read_bytes()
        input_hashes[name] = hashlib.sha256(payload).hexdigest()
        for feature in json.loads(payload)['features']:
            units[feature['properties']['admin_code']] = feature['properties']['name']
    (args.output / 'administrative-units.json').write_text(json.dumps({
        'source': 'GUGiK PRG; names/codes independent of drawing geometry',
        'input_sha256': input_hashes, 'units': dict(sorted(units.items()))}, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
