"""Prepare one offline flight replay in var/live/flight-replay (personal/educational use).

With no arguments, use one adsb.fi snapshot to identify civil aircraft over Poland,
then try at most three individual adsb.lol traces in RainViewer's last two hours.
--icao skips discovery. --import-episode installs an existing local episode folder.
"""
import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import HTTPException

from wici.radar import RadarUnavailable
from wici.replay_capture import capture, publish, read_saved

DEST = Path(__file__).resolve().parents[1] / 'var/live/flight-replay'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--icao', help='6 cyfr szesnastkowych ICAO wybranego samolotu')
    group.add_argument('--import-episode', type=Path, metavar='KATALOG', help='wczytaj zapis offline')
    parser.add_argument('--callsign', default='', help='wybierz konkretny znak lotu')
    args = parser.parse_args()
    if args.icao and not re.fullmatch('[a-fA-F0-9]{6}', args.icao):
        parser.error('--icao wymaga 6 cyfr szesnastkowych')
    if args.import_episode and args.callsign:
        parser.error('--callsign dotyczy wyłącznie pobierania')

    async def run():
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            return await capture(client, args.icao.lower() if args.icao else None, args.callsign.upper())
    try:
        episode, images = read_saved(args.import_episode) if args.import_episode else asyncio.run(run())
        result = publish(DEST, episode, images)
    except (KeyError, TypeError, ValueError, HTTPException, OSError, httpx.HTTPError, RadarUnavailable) as exc:
        sys.exit(f'Nie zapisano lotu: {exc}')
    start = datetime.fromtimestamp(result.points[0].time, UTC).isoformat()
    end = datetime.fromtimestamp(result.points[-1].time, UTC).isoformat()
    print(f'{result.label}: {start} – {end}; {len(result.points)} pozycji, {len(result.frames)} klatek. '
          f'{DEST / "episode.json"}')


if __name__ == '__main__':
    main()
