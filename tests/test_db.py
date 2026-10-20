"""Historical schemas remain readable without downgrading or discarding data."""
import sqlite3
from pathlib import Path

import pytest

from wici.db import connect


@pytest.mark.parametrize('version', [4, 7, 8])
def test_historical_schema_upgrade_and_reopen_preserve_data(tmp_path, version):
    path = tmp_path / 'app.sqlite3'
    migrations = sorted((Path(__file__).parents[1] / 'src/wici/migrations').glob('*.sql'))
    db = sqlite3.connect(path)
    for migration in migrations[:version]:
        db.executescript(migration.read_text())
    db.execute(f'PRAGMA user_version={version}')
    db.execute("INSERT INTO app_state VALUES('historical-marker','preserved')")
    if version >= 7:
        db.execute('''INSERT INTO egms_imports(source_id,filename,sha256,release,version,
            period_start,period_end,imported_at,bbox_json,point_count)
            VALUES('egms','fixture.csv','hash','2026',1,'2020-01-01','2025-12-31',
                   '2026-10-16T00:00:00Z','[]',0)''')
        if version == 8:
            db.execute("UPDATE egms_imports SET metadata_json=?", ('{"origin":"preserved"}',))
    db.commit()
    db.close()

    for _ in range(2):
        db = connect(path)
        assert db.execute('PRAGMA user_version').fetchone()[0] == len(migrations)
        assert db.execute("SELECT value FROM app_state WHERE key='historical-marker'").fetchone()[0] == 'preserved'
        if version >= 7:
            expected = '{"origin":"preserved"}' if version == 8 else '{}'
            assert db.execute('SELECT metadata_json FROM egms_imports').fetchone()[0] == expected
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        db.close()


def test_version_12_track_upgrade_preserves_history_and_unknown_classification(tmp_path):
    path = tmp_path/'tracks.sqlite3'
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    db = sqlite3.connect(path)
    for migration in migrations[:12]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=12')
    db.execute("""INSERT INTO object_tracks
        (id,kind,object_id,label,active,started_at,status)
        VALUES('existing','aircraft','48abcd','TEST',1,'2026-10-20T10:00:00+00:00','live')""")
    db.execute("""INSERT INTO object_track_points VALUES(
        'existing','2026-10-20T10:00:00+00:00',52,19,8000,600,90,1,'2026-10-20T10:00:00+00:00')""")
    original = db.execute('SELECT * FROM object_track_points').fetchone()
    db.commit()
    db.close()
    for _ in range(2):
        db = connect(path)
        try:
            assert db.execute('PRAGMA user_version').fetchone()[0] == len(migrations)
            track = db.execute("SELECT * FROM object_tracks WHERE id='existing'").fetchone()
            assert track['active'] == 1 and track['label'] == 'TEST'
            assert track['military'] is None
            assert tuple(db.execute('SELECT * FROM object_track_points').fetchone()) == original
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("UPDATE object_tracks SET military=2 WHERE id='existing'")
            db.rollback()
        finally:
            db.close()


def test_version_13_track_upgrade_preserves_history_and_aircraft_classification(tmp_path):
    path = tmp_path/'tracks.sqlite3'
    migrations = sorted((Path(__file__).parents[1]/'src/wici/migrations').glob('*.sql'))
    db = sqlite3.connect(path)
    for migration in migrations[:13]:
        db.executescript(migration.read_text())
    db.execute('PRAGMA user_version=13')
    db.executemany("""INSERT INTO object_tracks
        (id,kind,object_id,label,active,started_at,status,military)
        VALUES(?,?,?,?,1,'2026-10-20T10:00:00+00:00','live',?)""",
        [('plane', 'aircraft', '48abcd', 'TEST', 1), ('ship', 'ship', '261123456', 'BALTIC', None)])
    for track_id in ('plane', 'ship'):
        db.execute("""INSERT INTO object_track_points VALUES(
            ?,'2026-10-20T10:00:00+00:00',52,19,8000,600,90,1,'2026-10-20T10:00:00+00:00')""",
            (track_id,))
    original = db.execute('SELECT * FROM object_track_points ORDER BY track_id').fetchall()
    db.commit()
    db.close()
    for _ in range(2):
        db = connect(path)
        try:
            assert db.execute('PRAGMA user_version').fetchone()[0] == len(migrations)
            plane = db.execute("SELECT * FROM object_tracks WHERE id='plane'").fetchone()
            ship = db.execute("SELECT * FROM object_tracks WHERE id='ship'").fetchone()
            assert plane['military'] == 1 and plane['ship_type_code'] is None
            assert ship['military'] is None and ship['ship_type_code'] is None
            assert plane['label'] == 'TEST' and ship['label'] == 'BALTIC'
            assert plane['active'] == ship['active'] == 1
            assert [tuple(row) for row in db.execute(
                'SELECT * FROM object_track_points ORDER BY track_id')] == original
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            for invalid_code in (0, -1, 100, 35.5, 'cargo'):
                with pytest.raises(sqlite3.IntegrityError):
                    db.execute("UPDATE object_tracks SET ship_type_code=? WHERE id='ship'", (invalid_code,))
                db.rollback()
        finally:
            db.close()
