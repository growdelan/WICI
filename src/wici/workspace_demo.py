"""Small, visibly synthetic analytical scenario, isolated in the demo database."""
from datetime import timedelta

from wici.demo import DEMO_NOW


def seed_workspace(repo, history):
    if repo.db.execute("SELECT 1 FROM catalog_objects WHERE ref='hydro_station:imgw:demo-wisla'").fetchone():
        return

    def response(items, at, source):
        return {"status": 'ready', "items": items, "fetched_at": at.isoformat(), "synthetic": True,
                    "source_url": source, "message": 'DEMO: syntetyczny scenariusz, nie rzeczywiste pomiary.'}

    for hours, value in [(24, 238), (18, 247), (12, None), (6, 261), (1, 274)]:
        at = DEMO_NOW-timedelta(hours=hours)
        sample = {"value": value, "unit": 'cm', "observed_at": at.isoformat(), "source_time": at.isoformat()}
        history.write('hydro:stations', response([
            {"id": 'demo-wisla', "name": 'DEMO: wodowskaz Wisła', "river": 'Wisła', "province": 'mazowieckie',
                 "latitude": 52.23, "longitude": 21.03, "warning_level_cm": 300, "alarm_level_cm": 400,
                 "synthetic": True, "measurements": {'water_level': sample}},
            {"id": 'demo-unlocated', "name": 'DEMO: stacja bez lokalizacji', "river": 'Rzeka demonstracyjna',
                 "latitude": None, "longitude": None, "synthetic": True, "measurements": {}},
        ], at, 'https://example.invalid/demo/hydro'))
    history.write('gios:stations', response([
        {"id": 9000001, "name": 'DEMO: jakość powietrza Warszawa', "latitude": 52.21, "longitude": 21.02,
             "province": 'mazowieckie', "address": 'Adres syntetyczny', "synthetic": True},
    ], DEMO_NOW, 'https://example.invalid/demo/gios'))
    history.write('gios:sensors:9000001', response([
        {"id": 9000011, "station_id": 9000001, "parameter": 'PM10', "name": 'DEMO: PM10', "unit": 'µg/m³', "synthetic": True},
        {"id": 9000012, "station_id": 9000001, "parameter": 'PM10', "name": 'DEMO: drugi PM10', "unit": 'µg/m³', "synthetic": True},
    ], DEMO_NOW, 'https://example.invalid/demo/gios'))
    for sensor, offset in [(9000011, 0), (9000012, 4)]:
        history.write(f'gios:data:{sensor}', response([
            {"value": None if hours == 12 else value+offset, "unit": 'µg/m³',
                 "observed_at": (DEMO_NOW-timedelta(hours=hours)).isoformat(),
                 "source_time": (DEMO_NOW-timedelta(hours=hours)).isoformat()}
            for hours, value in [(24, 18), (18, 24), (12, 0), (6, 29), (1, 22)]
        ], DEMO_NOW, 'https://example.invalid/demo/gios'))
    history.write('gios:index:9000001', response([
        {"value": 1, "name": 'DEMO: Dobry', "observed_at": (DEMO_NOW-timedelta(hours=1)).isoformat(),
             "source_time": (DEMO_NOW-timedelta(hours=1)).isoformat(),
             "calculated": {'observed_at': DEMO_NOW.isoformat(), 'source_time': DEMO_NOW.isoformat()}},
    ], DEMO_NOW, 'https://example.invalid/demo/gios'))
