"""Rebuild the pinned browser runtime with Python's standard library only.

Run explicitly: ``python scripts/vendor_cesium.py``. Application startup never
downloads dependencies. ``--check`` verifies the installed files offline;
``--archive FILE`` rebuilds from an already downloaded, checksum-verified tarball.
No package lifecycle scripts, npm install, or JavaScript build are executed.
"""
import argparse
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

VERSION = '1.146.0'
ARCHIVE_URL = f'https://registry.npmjs.org/cesium/-/cesium-{VERSION}.tgz'
ARCHIVE_SHA256 = '9e4166f2d61e1088c94c1161ab92493750959160e5a37893a8b8c50c494048d5'
DESTINATION = Path(__file__).resolve().parents[1] / 'src/wici/static/vendor/cesium'
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
MAX_RUNTIME_BYTES = 20 * 1024 * 1024
RUNTIME_DIRECTORIES = {'Assets', 'Workers', 'ThirdParty', 'Widgets'}
NOTICES = {'LICENSE.md', 'ThirdParty.json', 'ThirdParty.extra.json'}
REQUIRED = {
    'Cesium.js', 'Widgets/widgets.css', 'Workers/createGeometry.js',
    'Workers/transferTypedArrayTest.js', 'Assets/approximateTerrainHeights.json',
    'ThirdParty/draco_decoder.wasm', *NOTICES,
}
GLOBAL_LOOKUP = b'var t=this||(0,eval)("this"),n=t.document'
SAFE_GLOBAL_LOOKUP = b'var t=globalThis,n=t.document'
MODIFICATION_NOTICE = (
    b'\n/* WICI modification (2026): Knockout global lookup uses globalThis instead of eval for strict CSP. */\n'
)


def patch_runtime(files):
    """Replace Knockout's obsolete eval global lookup; do not enable JS eval in CSP."""
    if files['Cesium.js'].count(GLOBAL_LOOKUP) != 1:
        raise ValueError('Pinned Knockout global lookup changed; review the Cesium upgrade')
    files['Cesium.js'] = files['Cesium.js'].replace(GLOBAL_LOOKUP, SAFE_GLOBAL_LOOKUP)
    files['Cesium.js'] = files['Cesium.js'].replace(b' */', b' */' + MODIFICATION_NOTICE, 1)
    return files


def fetch_archive():
    request = urllib.request.Request(ARCHIVE_URL, headers={'User-Agent': 'WICI-vendor-Cesium'})
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError('Cesium archive exceeds the download limit')
    return archive


def runtime_files(archive):
    """Verify before reading; copy only regular files under known runtime paths."""
    if len(archive) > MAX_ARCHIVE_BYTES or hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Cesium archive SHA-256 mismatch')
    files = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe Cesium archive path')
            if member.name.startswith('package/Build/Cesium/'):
                name = member.name.removeprefix('package/Build/Cesium/')
                parts = PurePosixPath(name).parts
                if not parts or not (name == 'Cesium.js' or parts[0] in RUNTIME_DIRECTORIES):
                    continue
                if name.endswith('.map'):
                    continue
            elif member.name in {f'package/{name}' for name in NOTICES}:
                name = member.name.removeprefix('package/')
            else:
                continue
            if member.isdir():
                continue
            if not member.isfile() or name in files:
                raise ValueError('Non-regular or duplicate Cesium runtime file')
            total += member.size
            if total > MAX_RUNTIME_BYTES:
                raise ValueError('Cesium runtime exceeds the extraction limit')
            with source.extractfile(member) as resource:
                files[name] = resource.read()
    if not REQUIRED <= files.keys():
        raise ValueError('Incomplete Cesium runtime')
    return files


def manifest_for(files):
    return {
        'package': 'cesium',
        'version': VERSION,
        'archive_url': ARCHIVE_URL,
        'archive_sha256': ARCHIVE_SHA256,
        'selection': 'Build/Cesium browser IIFE and runtime directories; no index modules or source maps',
        'patches': ['Knockout global object lookup: replace eval("this") with globalThis (strict CSP)',
                    'Add a prominent WICI modification notice to Cesium.js'],
        'files': {
            name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        },
    }


def check_vendor(destination):
    manifest = json.loads((destination / 'VENDOR.json').read_text())
    files = {
        path.relative_to(destination).as_posix(): path.read_bytes()
        for path in destination.rglob('*') if path.is_file() and path.name != 'VENDOR.json'
    }
    if manifest != manifest_for(files) or not REQUIRED <= files.keys():
        raise ValueError('Cesium runtime differs from the pinned VENDOR.json manifest')
    return files


def install(files, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cesium-vendor-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'runtime'
        stage.mkdir()
        for name, data in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (stage / 'VENDOR.json').write_text(json.dumps(manifest_for(files), indent=2) + '\n')
        check_vendor(stage)
        if destination.exists():
            shutil.rmtree(destination)
        stage.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify the vendored files without network access')
    parser.add_argument('--archive', type=Path, help='use a local copy of the pinned npm tarball')
    args = parser.parse_args()
    if args.check:
        files = check_vendor(DESTINATION)
    else:
        archive = args.archive.read_bytes() if args.archive else fetch_archive()
        files = patch_runtime(runtime_files(archive))
        install(files, DESTINATION)
    print(f'Cesium {VERSION}: {len(files)} files, {sum(map(len, files.values())):,} bytes; SHA-256 verified')


if __name__ == '__main__':
    main()
