"""Transactional, forward-only SQLite migrations. A failed migration never resets data."""
import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=5000')
    current = connection.execute('PRAGMA user_version').fetchone()[0]
    migrations = sorted(Path(__file__).with_name('migrations').glob('*.sql'))
    if current > len(migrations):
        connection.close()
        raise RuntimeError('Database schema is newer than this application')
    for migration in migrations:
        number = int(migration.name.split('_')[0])
        if number > current:
            try:
                connection.executescript('BEGIN IMMEDIATE;\n' + migration.read_text() + f'\nPRAGMA user_version={number};\nCOMMIT;')
            except Exception:
                connection.rollback()
                connection.close()
                raise
    return connection
