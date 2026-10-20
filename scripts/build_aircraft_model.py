"""Build WICI's original schematic aircraft, in metres: +X nose, +Y up, wings along Z.

All geometry is authored below; no downloaded assets, textures or external packages.
Run with --check to validate the committed model and its reproducible byte content.
SPDX-License-Identifier: MIT
"""
import argparse
import base64
import json
import math
import struct
from pathlib import Path

DESTINATION = Path(__file__).resolve().parents[1] / 'src/wici/static/models/aircraft.gltf'


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])


def unit(vector):
    length = math.sqrt(sum(value*value for value in vector))
    if length < 1e-10:
        raise ValueError('Degenerate model face')
    return tuple(value/length for value in vector)


class Geometry:
    def __init__(self):
        self.positions, self.normals, self.indices = [], [], []

    def solid(self, vertices, faces, smooth=False):
        centre = tuple(sum(vertex[axis] for vertex in vertices)/len(vertices) for axis in range(3))
        outward = []
        for face in faces:
            normal = cross(subtract(vertices[face[1]], vertices[face[0]]),
                           subtract(vertices[face[2]], vertices[face[0]]))
            direction = subtract(vertices[face[0]], centre)
            outward.append(tuple(reversed(face)) if sum(a*b for a, b in zip(normal, direction)) < 0 else face)
        if smooth:
            offset = len(self.positions)
            normals = [[0., 0., 0.] for _ in vertices]
            for face in outward:
                for index in range(1, len(face)-1):
                    triangle = (face[0], face[index], face[index+1])
                    normal = cross(subtract(vertices[triangle[1]], vertices[triangle[0]]),
                                   subtract(vertices[triangle[2]], vertices[triangle[0]]))
                    self.indices.extend(offset + vertex for vertex in triangle)
                    for vertex in triangle:
                        for axis in range(3):
                            normals[vertex][axis] += normal[axis]
            self.positions.extend(vertices)
            self.normals.extend(unit(normal) for normal in normals)
        else:
            for face in outward:
                self.surface([vertices[index] for index in face])

    def surface(self, vertices):
        normal = unit(cross(subtract(vertices[1], vertices[0]), subtract(vertices[2], vertices[0])))
        offset = len(self.positions)
        self.positions.extend(vertices)
        self.normals.extend([normal]*len(vertices))
        for index in range(1, len(vertices)-1):
            self.indices.extend((offset, offset+index, offset+index+1))


def prism(mesh, polygon, thickness):
    """Extrude a convex polygon vertically, retaining crisp surface normals."""
    count = len(polygon)
    vertices = [*polygon, *((x, y-thickness, z) for x, y, z in polygon)]
    faces = [tuple(range(count)), tuple(range(count, 2*count))]
    faces.extend((i, (i+1) % count, (i+1) % count+count, i+count) for i in range(count))
    mesh.solid(vertices, faces)


def hull(mesh, sections, rear, front, sides=8):
    """A tapered body of elliptical rings, with authored pointed ends."""
    vertices = [rear]
    for x, y, radius_y, radius_z in sections:
        vertices.extend((x, y+radius_y*math.sin(index*math.tau/sides),
                         radius_z*math.cos(index*math.tau/sides)) for index in range(sides))
    vertices.append(front)
    faces = [(0, 1+index, 1+(index+1) % sides) for index in range(sides)]
    for ring in range(len(sections)-1):
        first, second = 1+ring*sides, 1+(ring+1)*sides
        faces.extend((first+i, second+i, second+(i+1) % sides, first+(i+1) % sides)
                     for i in range(sides))
    last, tip = 1+(len(sections)-1)*sides, len(vertices)-1
    faces.extend((tip, last+(index+1) % sides, last+index) for index in range(sides))
    mesh.solid(vertices, faces, smooth=True)


def geometry():
    cream, teal, red = (Geometry() for _ in range(3))
    hull(cream, [(-10, .15, .8, .7), (-6, 0, 1.5, 1.45), (12, 0, 1.5, 1.45)],
         (-14, .25, 0), (18, .1, 0))
    for side in (-1, 1):
        # Swept main wings and horizontal stabilizers have real thickness.
        prism(cream, [(5, .35, side), (-1, .95, side*15), (-3.7, .95, side*15),
                      (-5.5, .35, side)], .24)
        prism(cream, [(-8, .8, side*.7), (-11.2, 1.1, side*4), (-13.4, 1.1, side*4),
                      (-13.2, .8, side*.7)], .16)
        # Original red tip panels follow the wing surface, clear of z-fighting.
        fraction = 13/14
        red.surface([(-1, .962, side*15), (-3.7, .962, side*15),
                     (-5.5+1.8*fraction, .35+.6*fraction+.012, side*14),
                     (5-6*fraction, .35+.6*fraction+.012, side*14)])
        # Two compact teal engine pods and pylons distinguish a transport aircraft.
        pod = Geometry()
        hull(pod, [(-1.4, -.85, .48, .48), (2.5, -.85, .65, .65)],
             (-1.8, -.85, 0), (2.8, -.85, 0), sides=6)
        offset = len(teal.positions)
        teal.positions.extend((x, y, z+side*4.5) for x, y, z in pod.positions)
        teal.normals.extend(pod.normals)
        teal.indices.extend(index+offset for index in pod.indices)
        teal.surface([(-.2, -.3, side*4.5), (1.8, -.3, side*4.5),
                      (1.8, .5, side*4.5), (-.2, .5, side*4.5)])
        # Windshield panels lie on the upper fuselage facets immediately behind the nose.
        slope = (1.5-1.5/math.sqrt(2))/(1.45/math.sqrt(2))
        teal.surface([(10.6, 1.512, 0), (12, 1.512, 0),
                      (12, 1.512-slope*.7, side*.7), (10.6, 1.512-slope*.7, side*.7)])
    # Thin triangular vertical tail: the overall model is exactly eight metres high.
    fin = [(-13.2, .8, -.16), (-7.8, .8, -.16), (-12.2, 6.5, -.16),
           (-13.2, .8, .16), (-7.8, .8, .16), (-12.2, 6.5, .16)]
    teal.solid(fin, [(0, 1, 2), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)])
    return [cream, teal, red]


def build():
    binary, views, accessors, primitives = bytearray(), [], [], []

    def accessor(values, format_code, component_type, kind, target, bounds=False):
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        flattened = [number for value in values for number in value] if kind == 'VEC3' else values
        binary.extend(struct.pack('<' + format_code*len(flattened), *flattened))
        view = len(views)
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(binary)-offset, 'target': target})
        entry = {'bufferView': view, 'componentType': component_type, 'count': len(values), 'type': kind}
        if bounds:
            entry.update(min=[min(value[axis] for value in values) for axis in range(3)],
                         max=[max(value[axis] for value in values) for axis in range(3)])
        accessors.append(entry)
        return len(accessors)-1

    meshes = geometry()
    for material, mesh in enumerate(meshes):
        position = accessor(mesh.positions, 'f', 5126, 'VEC3', 34962, bounds=True)
        normal = accessor(mesh.normals, 'f', 5126, 'VEC3', 34962)
        indices = accessor(mesh.indices, 'H', 5123, 'SCALAR', 34963)
        primitives.append({'attributes': {'POSITION': position, 'NORMAL': normal}, 'indices': indices,
                           'material': material, 'mode': 4})
    materials = [{'name': name, 'pbrMetallicRoughness': {'baseColorFactor': color, 'metallicFactor': 0,
                  'roughnessFactor': .76}, 'doubleSided': True} for name, color in [
                      ('WICI cream', [.91, .86, .73, 1]), ('WICI teal', [.045, .29, .30, 1]),
                      ('WICI red', [.77, .16, .13, 1])]]
    model = {'asset': {'version': '2.0', 'generator': 'WICI original procedural aircraft',
                      'copyright': 'WICI; original schematic geometry, MIT'},
             'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': 'WICI schematic aircraft'}],
             'meshes': [{'primitives': primitives}], 'materials': materials,
             'buffers': [{'byteLength': len(binary), 'uri': 'data:application/octet-stream;base64,' +
                          base64.b64encode(binary).decode('ascii')}],
             'bufferViews': views, 'accessors': accessors}
    validate(model)
    return (json.dumps(model, separators=(',', ':'), ensure_ascii=True)+'\n').encode('utf-8')


def validate(model):
    """Check actual buffer bytes, accessors, unit normals, indices and authored extents."""
    buffer = model['buffers'][0]
    binary = base64.b64decode(buffer['uri'].split(',', 1)[1], validate=True)
    assert len(binary) == buffer['byteLength']
    decoded = []
    for accessor in model['accessors']:
        view = model['bufferViews'][accessor['bufferView']]
        components = 3 if accessor['type'] == 'VEC3' else 1
        code = 'f' if accessor['componentType'] == 5126 else 'H'
        count, offset = accessor['count']*components, view['byteOffset']
        assert offset % 4 == 0 and view['byteLength'] == count*struct.calcsize(code)
        assert offset+view['byteLength'] <= len(binary)
        values = struct.unpack_from('<'+code*count, binary, offset)
        assert all(math.isfinite(value) for value in values)
        decoded.append(list(zip(*(iter(values),)*3)) if components == 3 else values)
    positions = []
    for primitive in model['meshes'][0]['primitives']:
        points = decoded[primitive['attributes']['POSITION']]
        normals = decoded[primitive['attributes']['NORMAL']]
        indices = decoded[primitive['indices']]
        assert primitive['mode'] == 4 and len(indices) % 3 == 0 and max(indices) < len(points)
        assert len(normals) == len(points)
        assert all(abs(sum(axis*axis for axis in normal)-1) < 1e-6 for normal in normals)
        for start in range(0, len(indices), 3):
            a, b, c = (points[indices[start+index]] for index in range(3))
            unit(cross(subtract(b, a), subtract(c, a)))
        positions.extend(points)
    dimensions = [max(point[axis] for point in positions)-min(point[axis] for point in positions)
                  for axis in range(3)]
    assert all(abs(actual-expected) < 1e-5 for actual, expected in zip(dimensions, [32, 8, 30]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate existing glTF and require identical output')
    args = parser.parse_args()
    content = build()
    if args.check:
        validate(json.loads(DESTINATION.read_text()))
        if DESTINATION.read_bytes() != content:
            parser.error('Aircraft model differs; run the builder without --check')
    else:
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        DESTINATION.write_bytes(content)
    model = json.loads(content)
    triangles = sum(model['accessors'][primitive['indices']]['count']//3
                    for primitive in model['meshes'][0]['primitives'])
    print(f'{DESTINATION.name}: {len(content)} bytes JSON, {model["buffers"][0]["byteLength"]} bytes buffer, '
          f'{triangles} triangles; structural checks passed')


if __name__ == '__main__':
    main()
