"""Explicit live IMGW smoke in a temporary database; never opens var/live.

Only public hydrology is fetched. A deliberately chosen *user* threshold verifies
local detection and deduplication; this is not an official hydrological warning.
"""
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from wici.hydro import HydroService
from wici.repository import Repository
from wici.station_history import StationHistory
from wici.workspace_service import WorkspaceService


async def main():
    checked = datetime.now(UTC)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await HydroService(client, lambda: datetime.now(UTC)).fetch('stations')
    if response.get('status') != 'ready':
        raise RuntimeError('IMGW did not return a ready hydrology snapshot: '+str(response.get('status')))
    candidates = [item for item in response['items'] if item.get('measurements', {}).get('water_level', {}).get('status') == 'fresh'
                  and item['measurements']['water_level']['value'] is not None]
    if not candidates:
        raise RuntimeError('No fresh water level measurement; no live detection claimed')
    item = candidates[0]
    ref = 'hydro_station:imgw:'+str(item['id'])
    with tempfile.TemporaryDirectory(prefix='wici-monitor-live-') as folder:
        repo = Repository(Path(folder)/'isolated.sqlite', clock=lambda: datetime.now(UTC))
        try:
            workspace = WorkspaceService(repo)
            with repo.lock, repo.db:
                workspace.catalog.upsert_station(ref, 'imgw', str(item['id']), item['name'], item.get('latitude'), item.get('longitude'))
            rule = workspace.rules.save({'name': 'LIVE test — własny próg poniżej odczytu', 'template': 'measurement',
                'enabled': True, 'config': {'object_ref': ref, 'sensor_id': '', 'metric': 'water_level', 'unit': 'cm',
                                         'threshold': item['measurements']['water_level']['value']-1}})
            history = StationHistory(repo)
            history.write('hydro:stations', response)
            workspace.monitor.process()
            first = workspace.events.list(rule_id=rule['id'])
            assert first['total'] == 1, first
            history.write('hydro:stations', response)
            workspace.monitor.process()
            assert workspace.events.list(rule_id=rule['id'])['total'] == 1
            event = workspace.events.detail(first['items'][0]['id'])
            dossier = workspace.dossiers.save({'name': 'LIVE smoke — baza tymczasowa'})
            saved = workspace.events.capture(event['id'], {'dossier_id': dossier['id']})
            assert saved['snapshot']['event']['evidence']['observation']['payload']['value'] == item['measurements']['water_level']['value']
            report = {'checked_at': checked.isoformat(), 'source': response.get('source_url'), 'source_status': response['status'],
                'station_ref': ref, 'measurement_at': event['observed_at'], 'detected_at': event['detected_at'],
                'event_count_after_repeat': 1, 'material_sha256': saved['sha256'], 'temporary_database': True,
                'notice': 'User-defined test threshold; no official warning inferred. All temporary source data removed.'}
        finally:
            repo.close()
    output = Path(__file__).resolve().parents[1]/'tmp'/'live-checks'/'workspace-monitor.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
