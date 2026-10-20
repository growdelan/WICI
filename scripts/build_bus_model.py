"""Build WICI's original 12 m bus: +X front, +Y up, wheels touching Y=0.

All geometry is authored here with the aircraft builder's geometry primitives.
There are no downloaded assets, textures or external packages. --check validates
the actual committed geometry and requires reproducible byte content.
SPDX-License-Identifier: MIT
"""
import argparse
import base64
import json
import math
import struct
from pathlib import Path

from build_aircraft_model import Geometry, cross, subtract, unit

DESTINATION = Path(__file__).resolve().parents[1] / 'src/wici/static/models/bus.gltf'


def box(mesh, low, high):
    x1, y1, z1 = low
    x2, y2, z2 = high
    vertices = [(x1, y1, z1), (x2, y1, z1), (x2, y2, z1), (x1, y2, z1),
                (x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2)]
    mesh.solid(vertices, [(0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 5, 1),
                          (3, 2, 6, 7), (0, 3, 7, 4), (1, 5, 6, 2)])


def wheel(mesh, centre_x, side, radius, half_width):
    # The rotation axis runs across the bus along Z. Sixteen sides give a
    # recognizable tyre without increasing the schematic model's detail level.
    vertices = [(centre_x + radius * math.cos(index * math.tau / 16),
                 .48 + radius * math.sin(index * math.tau / 16), side * 1.15 + offset)
                for offset in (-half_width, half_width) for index in range(16)]
    faces = [tuple(range(16)), tuple(range(16, 32))]
    faces.extend((index, (index + 1) % 16, (index + 1) % 16 + 16, index + 16)
                 for index in range(16))
    mesh.solid(vertices, faces)


def geometry():
    cream, teal, red, tyre, light = (Geometry() for _ in range(5))
    box(cream, (-6, .62, -1.22), (6, 3.18, 1.22))
    box(cream, (-4, 3.18, -.8), (2.7, 3.25, .8))
    box(red, (-6.005, .72, -1.225), (6.005, 1.28, 1.225))
    # Recessed-looking dark windows are authored surfaces, clear of the body.
    for side in (-1, 1):
        for index in range(8):
            back = -5.6 + index * 1.4
            # Leave two full-height openings for the front and centre doors.
            if side == 1 and index in (4, 7):
                continue
            teal.surface([(back, 1.65, side * 1.232), (back + 1.18, 1.65, side * 1.232),
                          (back + 1.18, 2.9, side * 1.232), (back, 2.9, side * 1.232)])
        for axle in (-3.7, 3.9):
            wheel(tyre, axle, side, .48, .15)
            wheel(light, axle, side, .24, .152)
    # Right-side passenger doors, including a visible cream centre divider.
    for back in (0, 4.2):
        teal.surface([(back, .68, 1.238), (back + 1.18, .68, 1.238),
                      (back + 1.18, 2.9, 1.238), (back, 2.9, 1.238)])
        box(cream, (back + .56, .68, 1.238), (back + .62, 2.9, 1.245))
    teal.surface([(6.014, 1.55, -1.06), (6.014, 1.55, 1.06),
                  (6.014, 2.94, 1.06), (6.014, 2.94, -1.06)])
    teal.surface([(-6.014, 1.65, -1.06), (-6.014, 2.9, -1.06),
                  (-6.014, 2.9, 1.06), (-6.014, 1.65, 1.06)])
    for side in (-1, 1):
        box(light, (6.014, .91, side * .82 - .13), (6.025, 1.12, side * .82 + .13))
        box(red, (-6.025, 1.32, side * .94 - .09), (-6.014, 1.57, side * .94 + .09))
    # A contrasting blank destination panel remains generic across every city.
    teal.surface([(6.014, 2.98, -.8), (6.014, 2.98, .8),
                  (6.014, 3.12, .8), (6.014, 3.12, -.8)])
    return [cream, teal, red, tyre, light]


def build():
    binary, views, accessors, primitives = bytearray(), [], [], []

    def accessor(values, format_code, component_type, kind, target, bounds=False):
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        flattened = [number for value in values for number in value] if kind == 'VEC3' else values
        binary.extend(struct.pack('<' + format_code * len(flattened), *flattened))
        view = len(views)
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(binary) - offset, 'target': target})
        entry = {'bufferView': view, 'componentType': component_type, 'count': len(values), 'type': kind}
        if bounds:
            entry.update(min=[min(value[axis] for value in values) for axis in range(3)],
                         max=[max(value[axis] for value in values) for axis in range(3)])
        accessors.append(entry)
        return len(accessors) - 1

    for material, mesh in enumerate(geometry()):
        positions = accessor(mesh.positions, 'f', 5126, 'VEC3', 34962, bounds=True)
        normals = accessor(mesh.normals, 'f', 5126, 'VEC3', 34962)
        indices = accessor(mesh.indices, 'H', 5123, 'SCALAR', 34963)
        primitives.append({'attributes': {'POSITION': positions, 'NORMAL': normals},
                           'indices': indices, 'material': material, 'mode': 4})
    materials = [{'name': name, 'pbrMetallicRoughness': {'baseColorFactor': color, 'metallicFactor': 0,
                  'roughnessFactor': .8}, 'doubleSided': True} for name, color in [
                      ('WICI cream', [.91, .86, .73, 1]), ('WICI teal glass', [.035, .20, .23, 1]),
                      ('WICI red', [.77, .16, .13, 1]), ('WICI tyres', [.045, .05, .05, 1]),
                      ('WICI hubs and lamps', [.93, .92, .80, 1])]]
    model = {'asset': {'version': '2.0', 'generator': 'WICI original procedural bus',
                      'copyright': 'WICI; original schematic geometry, MIT'},
             'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': 'WICI schematic bus'}],
             'meshes': [{'primitives': primitives}], 'materials': materials,
             'buffers': [{'byteLength': len(binary), 'uri': 'data:application/octet-stream;base64,' +
                          base64.b64encode(binary).decode('ascii')}], 'bufferViews': views, 'accessors': accessors}
    validate(model)
    return (json.dumps(model, separators=(',', ':'), ensure_ascii=True) + '\n').encode('utf-8')


def validate(model):
    """Check buffer bytes, normals, triangles and a surface-level model origin."""
    buffer = model['buffers'][0]
    binary = base64.b64decode(buffer['uri'].split(',', 1)[1], validate=True)
    assert len(binary) == buffer['byteLength']
    decoded = []
    for accessor in model['accessors']:
        view = model['bufferViews'][accessor['bufferView']]
        components = 3 if accessor['type'] == 'VEC3' else 1
        code = 'f' if accessor['componentType'] == 5126 else 'H'
        count, offset = accessor['count'] * components, view['byteOffset']
        assert offset % 4 == 0 and view['byteLength'] == count * struct.calcsize(code)
        assert offset + view['byteLength'] <= len(binary)
        values = struct.unpack_from('<' + code * count, binary, offset)
        assert all(math.isfinite(value) for value in values)
        decoded.append(list(zip(*(iter(values),) * 3)) if components == 3 else values)
    positions = []
    for primitive in model['meshes'][0]['primitives']:
        points = decoded[primitive['attributes']['POSITION']]
        normals = decoded[primitive['attributes']['NORMAL']]
        indices = decoded[primitive['indices']]
        assert primitive['mode'] == 4 and len(indices) % 3 == 0 and max(indices) < len(points)
        assert len(normals) == len(points)
        assert all(abs(sum(axis * axis for axis in normal) - 1) < 1e-6 for normal in normals)
        for start in range(0, len(indices), 3):
            a, b, c = (points[indices[start + index]] for index in range(3))
            unit(cross(subtract(b, a), subtract(c, a)))
        positions.extend(points)
    low = [min(point[axis] for point in positions) for axis in range(3)]
    high = [max(point[axis] for point in positions) for axis in range(3)]
    assert all(abs(actual - expected) < 1e-5 for actual, expected in zip(low, [-6.025, 0, -1.302]))
    assert all(abs(actual - expected) < 1e-5 for actual, expected in zip(high, [6.025, 3.25, 1.302]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate committed glTF and require identical output')
    args = parser.parse_args()
    content = build()
    if args.check:
        validate(json.loads(DESTINATION.read_text()))
        if DESTINATION.read_bytes() != content:
            parser.error('Bus model differs; run the builder without --check')
    else:
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        DESTINATION.write_bytes(content)
    model = json.loads(content)
    triangles = sum(model['accessors'][primitive['indices']]['count'] // 3
                    for primitive in model['meshes'][0]['primitives'])
    print(f'{DESTINATION.name}: {len(content)} bytes JSON, {model["buffers"][0]["byteLength"]} bytes buffer, '
          f'{triangles} triangles; structural checks passed')


if __name__ == '__main__':
    main()
