"""Reproducible offline list benchmark: temporary DB, publisher documents and current versions."""
import argparse
import json
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from wici.app import create_app
from wici.repository import Repository


def benchmark(records=10000, runs=3):
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    time_text = now.isoformat()
    with tempfile.TemporaryDirectory(prefix='wici-benchmark-') as directory:
        repo = Repository(Path(directory) / 'benchmark.sqlite3', clock=lambda: now)
        try:
            with repo.db:
                repo.db.execute("INSERT INTO sources(id,name) VALUES('sg','Syntetyczny pomiar')")
                repo.db.executemany('''INSERT INTO documents(id,source_id,identity_key,url,first_seen_at,
                    last_checked_at,current_version) VALUES(?,?,?,?,?,?,1)''',
                    [(i, 'sg', str(i), f'https://example.org/{i}', time_text, time_text) for i in range(1, records + 1)])
                repo.db.executemany('''INSERT INTO document_versions(id,document_id,version_number,content_hash,
                    title,text,fields_json,source_published_at,parser_version,created_at) VALUES(?,?,1,?,?,?,?,?,?,?)''',
                    [(i, i, str(i), 'Pomiar', 'Bezpieczny tekst', '{"contract_validated":true,"access_allowed":true}', time_text, '1', time_text)
                     for i in range(1, records + 1)])
            measurements = []
            app = create_app(demo=True, root=Path(directory))
            app.state.repo = repo
            client = TestClient(app, base_url='http://127.0.0.1:8765')
            for _ in range(runs):
                started = time.perf_counter()
                result = repo.list_communications(limit=1000)
                listed = time.perf_counter()
                response = JSONResponse(result)
                serialized = time.perf_counter()
                http_started = time.perf_counter()
                api_response = client.get('/api/communications')
                api_finished = time.perf_counter()
                assert api_response.status_code == 200
                assert api_response.json()['total'] == records
                measurements.append({'repository_ms': round((listed - started) * 1000, 2),
                                     'with_json_ms': round((serialized - started) * 1000, 2),
                                     'api_testclient_ms': round((api_finished - http_started) * 1000, 2)})
            client.close()
            return {'records': records, 'returned': len(result['items']),
                    'total': result['total'], 'limited': result['limited'], 'response_bytes': len(response.body),
                    'measurements': measurements, 'python': platform.python_version(), 'system': platform.system(),
                    'machine': platform.machine(), 'processor': platform.processor(),
                    'scope': 'Repository, JSON serialization and actual FastAPI GET /api/communications through in-process TestClient; excludes socket transport/browser/network sources.'}
        finally:
            repo.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=10000)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.records <= 10000 or not 1 <= args.runs <= 10:
        parser.error('Records: 1..10000; runs: 1..10')
    print(json.dumps(benchmark(args.records, args.runs), ensure_ascii=False, indent=2))
