"""Explicit developer-only vendoring of the pinned browser graph renderer."""
import argparse
import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

VERSION = '3.34.4'
URL = f'https://registry.npmjs.org/cytoscape/-/cytoscape-{VERSION}.tgz'
INTEGRITY = 'sha512-msY99tMY8iWTg+sIPGfSqDcPNOt4xcj+v/K/7qUFaCUxxlqnMkUYLBjRUzn9W5CU/R2hrmtJa5+UtovrEM2ctg=='
DESTINATION = Path(__file__).resolve().parents[1]/'src/wici/static/vendor/cytoscape'
FILES = {'package/dist/cytoscape.min.js': 'cytoscape.min.js', 'package/LICENSE': 'LICENSE'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify local files without network access')
    args = parser.parse_args()
    if args.check:
        manifest = json.loads((DESTINATION/'VENDOR.json').read_text())
        if manifest['version'] != VERSION or manifest['integrity'] != INTEGRITY or manifest['url'] != URL:
            raise SystemExit('Cytoscape manifest does not match the pinned package')
        for filename in FILES.values():
            digest = hashlib.sha256((DESTINATION/filename).read_bytes()).hexdigest()
            if digest != manifest['sha256'][filename]:
                raise SystemExit(f'Cytoscape file changed: {filename}')
        print(f'Cytoscape.js {VERSION}: local files verified')
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        payload = response.read(10 * 1024 * 1024 + 1)
    if len(payload) > 10 * 1024 * 1024:
        raise SystemExit('Cytoscape archive is too large')
    actual = 'sha512-'+base64.b64encode(hashlib.sha512(payload).digest()).decode()
    if actual != INTEGRITY:
        raise SystemExit('Cytoscape archive integrity mismatch')
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for source, filename in FILES.items():
            member = archive.getmember(source)
            if not member.isfile() or member.size > 5 * 1024 * 1024:
                raise SystemExit(f'Invalid Cytoscape member: {source}')
            contents[filename] = archive.extractfile(member).read()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for filename, content in contents.items():
        (DESTINATION/filename).write_bytes(content)
    manifest = {'name': 'cytoscape', 'version': VERSION, 'license': 'MIT', 'url': URL,
                'integrity': INTEGRITY, 'modifications': [],
                'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    (DESTINATION/'VENDOR.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Vendored Cytoscape.js {VERSION}; no source modifications')


if __name__ == '__main__':
    main()
