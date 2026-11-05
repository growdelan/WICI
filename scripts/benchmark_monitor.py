"""Offline monitor benchmark with repeatable database-state comparison.

uv run --locked python scripts/benchmark_monitor.py --runs 9 --compare-ref 128de1a
The optional reference loads only workspace_monitor.py from local Git history.
"""
import argparse
import hashlib
import itertools
import json
import statistics
import subprocess
import tempfile
import time
import types
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from wici.monitor_epochs import receipt
from wici.repository import Repository
from wici.workspace_monitor import WorkspaceMonitor, append_observation
from wici.workspace_service import WorkspaceService

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def seed(workspace, scenario, rules, observations):
    repo = workspace.repo
    with repo.lock, repo.db:
        for number in range(10):
            workspace.catalog.upsert_station(f'hydro_station:imgw:{number}', 'imgw', str(number),
                                             f'Stacja syntetyczna {number}')
    ids = []
    for number in range(rules):
        result = workspace.rules.save({'name': f'Reguła {number}', 'template': 'measurement', 'enabled': True,
            'config': {'object_ref': f'hydro_station:imgw:{number % 10 if scenario == "mixed" else 0}',
                       'sensor_id': '', 'metric': 'water_level', 'unit': 'cm',
                       'threshold': 60 if scenario == 'mixed' else 1000, 'return_threshold': 50}})
        ids.append(result['id'])
    token = receipt(repo)
    with repo.lock, repo.db:
        for number in range(observations):
            at = NOW-timedelta(seconds=observations-number)
            payload = {'sensor_id': '', 'metric': 'water_level', 'unit': 'cm',
                       'value': 65 if number % 3 else 45, 'quality': 'valid',
                       'provenance': {'source_url': 'https://example.org/synthetic'}}
            kind, ref = 'measurement', f'hydro_station:imgw:{number % 10 if scenario == "mixed" else 0}'
            if scenario == 'mixed' and number % 31 == 0:
                kind, ref, payload = 'gap', '*', {'reason': 'synthetic source gap'}
            received = [token[0], 0] if scenario == 'mixed' and number % 17 == 0 else token
            append_observation(repo, kind, ref, 'imgw', at, number, payload,
                               trusted=kind != 'gap', receipt=received)
        if scenario == 'mixed':
            # A resumed rule may start at a different persisted checkpoint.
            repo.db.executemany('UPDATE workspace_rules SET checkpoint_id=? WHERE id=?',
                                [(index % 20, identity) for index, identity in enumerate(ids)])


def measure(source, folder, monitor_class, runs):
    repo = Repository(Path(folder)/'run.sqlite3', clock=lambda: NOW)
    try:
        workspace = WorkspaceService(repo)
        monitor = monitor_class(workspace)
        timings, digest, processed = [], None, None
        for _ in range(runs):
            source.db.backup(repo.db)
            counter = itertools.count(1)
            with patch('wici.workspace_events.uuid.uuid4', side_effect=lambda counter=counter: uuid.UUID(int=next(counter))):
                start = time.perf_counter()
                processed = monitor.process()
                timings.append((time.perf_counter()-start)*1000)
            current = hashlib.sha256('\n'.join(repo.db.iterdump()).encode()).hexdigest()
            if digest is not None and current != digest:
                raise AssertionError('Repeated processing changed the database result')
            digest = current
        source.db.backup(repo.db)
        statements = []
        repo.db.set_trace_callback(statements.append)
        counter = itertools.count(1)
        try:
            with patch('wici.workspace_events.uuid.uuid4', side_effect=lambda: uuid.UUID(int=next(counter))):
                monitor.process()
        finally:
            repo.db.set_trace_callback(None)
        return {'median_ms': round(statistics.median(timings), 3),
                'p95_ms': round(sorted(timings)[min(len(timings)-1, int(.95*len(timings)))], 3),
                'sql_statements': len(statements), 'processed_observations': processed,
                'events': repo.db.execute('SELECT count(*) FROM workspace_events').fetchone()[0],
                'database_sha256': digest}
    finally:
        repo.close()


def run(runs=9, rules=50, observations=256, compare_ref=None):
    reference = None
    if compare_ref:
        source = subprocess.check_output(['git', 'show', f'{compare_ref}:src/wici/workspace_monitor.py'], text=True)
        module = types.ModuleType('wici._benchmark_monitor_reference')
        # Explicit offline comparison with the user's selected local Git revision.
        exec(compile(source, '<reference workspace_monitor.py>', 'exec'), module.__dict__)  # noqa: S102
        reference = module.WorkspaceMonitor
    result = {'runs': runs, 'rules': rules, 'observations': observations, 'scenarios': {}}
    with tempfile.TemporaryDirectory(prefix='wici-monitor-benchmark-') as folder:
        for scenario in ('all_match', 'mixed'):
            source = Repository(Path(folder)/f'{scenario}.sqlite3', clock=lambda: NOW)
            try:
                seed(WorkspaceService(source), scenario, rules, observations)
                before = measure(source, folder, reference, runs) if reference else None
                after = measure(source, folder, WorkspaceMonitor, runs)
                result['scenarios'][scenario] = {'current': after}
                if before is not None:
                    equal = before['database_sha256'] == after['database_sha256']
                    result['scenarios'][scenario].update(reference=before, full_database_equal=equal)
                    if not equal:
                        raise AssertionError(f'{scenario}: reference and current database results differ')
            finally:
                source.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=9)
    parser.add_argument('--rules', type=int, default=50)
    parser.add_argument('--observations', type=int, default=256)
    parser.add_argument('--compare-ref')
    args = parser.parse_args()
    if not 1 <= args.rules <= 50 or min(args.runs, args.observations) < 1:
        parser.error('Rules must be between 1 and 50; runs and observations must be positive.')
    print(json.dumps(run(**vars(args)), ensure_ascii=False, indent=2))
