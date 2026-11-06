"""Serve one locally prepared flight and its time-matched radar tiles."""
import os
from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from threading import Lock
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

Timestamp = Annotated[int, Field(strict=True, gt=0, le=4102444800)]
Name = Annotated[str, Field(min_length=1, max_length=300)]
MAX_MANIFEST = 4 * 1024 * 1024
MAX_TILE = 1024 * 1024


class Position(BaseModel):
    time: Timestamp
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    alt_m: float = Field(ge=-500, le=30000)
    heading: float | None = Field(default=None, ge=0, le=360)


class RadarTile(BaseModel):
    z: int = Field(strict=True, ge=0, le=14)
    x: int = Field(strict=True, ge=0)
    y: int = Field(strict=True, ge=0)
    file: str = Field(min_length=1, max_length=250)

    @model_validator(mode='after')
    def check_xyz(self):
        if max(self.x, self.y) >= 2**self.z:
            raise ValueError('Współrzędne poza piramidą kafli.')
        return self


class RadarFrame(BaseModel):
    time: Timestamp
    tiles: list[RadarTile] = Field(min_length=1, max_length=64)


class Episode(BaseModel):
    label: Name
    flight_source: Name
    radar_source: Name
    flight_source_url: str | None = None
    radar_source_url: str | None = None
    note: str = Field(default='', max_length=1600)
    points: list[Position] = Field(min_length=2, max_length=20000)
    frames: list[RadarFrame] = Field(min_length=1, max_length=300)

    @field_validator('flight_source_url', 'radar_source_url')
    @classmethod
    def source_link(cls, url):
        if url is not None:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None:
                raise ValueError('Niepoprawny odnośnik do źródła.')
        return url

    @model_validator(mode='after')
    def check_times(self):
        for series in (self.points, self.frames):
            if any(a.time >= b.time for a, b in pairwise(series)):
                raise ValueError('Próbki i klatki wymagają rosnących czasów UTC.')
        frame_times = [frame.time for frame in self.frames]
        for point in self.points:
            preceding = bisect_right(frame_times, point.time) - 1
            if preceding >= 0 and point.time - frame_times[preceding] <= 900:
                return self
        raise ValueError('Brak wspólnego czasu radaru i obserwacji lotu.')


@dataclass(frozen=True)
class Snapshot:
    public: dict
    revision: str
    files: dict[tuple[int, int, int, int], Path]


class FlightReplay:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.lock = Lock()
        self.snapshot = None
        self.signature = None

    def load(self) -> Snapshot:
        manifest = self.directory / 'episode.json'
        with self.lock:
            try:
                if manifest.is_symlink():
                    raise ValueError('Dowiązanie manifestu')
                with manifest.open('rb') as stream:
                    stat = os.fstat(stream.fileno())
                    signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
                    if signature == self.signature:
                        return self.snapshot
                    raw = stream.read(MAX_MANIFEST + 1)
                if len(raw) > MAX_MANIFEST:
                    raise ValueError('Limit manifestu')
                episode = Episode.model_validate_json(raw)
                snapshot = self.build(episode, sha256(raw).hexdigest()[:20])
            except FileNotFoundError:
                raise HTTPException(404, 'Brak zapisanego lotu. Przygotuj nagranie poleceniem '
                                    'uv run --locked python scripts/capture_flight_replay.py.') from None
            except (OSError, ValueError, RuntimeError):
                raise HTTPException(503, 'Nie można odczytać zapisanego lotu. Sprawdź pliki nagrania.') from None
            self.signature, self.snapshot = signature, snapshot
            return snapshot

    def build(self, episode: Episode, revision: str) -> Snapshot:
        public = episode.model_dump(exclude={'frames'}, exclude_none=True)
        files = {}
        frames = []
        for frame in episode.frames:
            tiles = []
            for tile in frame.tiles:
                relative = Path(tile.file)
                if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.png':
                    raise ValueError('Niepoprawna ścieżka obrazu.')
                key = (frame.time, tile.z, tile.x, tile.y)
                if key in files:
                    raise ValueError('Powtórzony kafel w klatce radaru.')
                files[key] = self.directory / relative
                tiles.append({'z': tile.z, 'x': tile.x, 'y': tile.y,
                              'url': f'/api/flight-replay/tiles/{revision}/{frame.time}/{tile.z}/{tile.x}/{tile.y}.png'})
            frames.append({'time': frame.time, 'tiles': tiles})
        return Snapshot({**public, 'demo': False, 'frames': frames}, revision, files)

    def read_tile(self, revision, key) -> bytes:
        snapshot = self.load()
        path = snapshot.files.get(key)
        if revision != snapshot.revision or path is None:
            raise HTTPException(404, 'Kafelek spoza wybranego nagrania.')
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(self.directory) or not resolved.is_file():
                raise ValueError('Niepoprawna ścieżka')
            with resolved.open('rb') as stream:
                data = stream.read(MAX_TILE + 1)
            if len(data) > MAX_TILE or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Niepoprawny PNG')
        except (ValueError, RuntimeError, OSError):
            raise HTTPException(503, 'Obraz tej klatki jest niedostępny.') from None
        return data


def create_replay_router(root: Path, demo: bool):
    router = APIRouter(prefix='/api/flight-replay')
    store = FlightReplay(root / 'var' / 'live' / 'flight-replay')

    def check_access(request: Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            raise HTTPException(403, 'Odczyt dostępny z WICI.')
        if demo:
            raise HTTPException(404, 'Zapis rzeczywistego lotu jest dostępny w trybie zwykłym WICI.')

    @router.get('')
    def replay(request: Request):
        check_access(request)
        return JSONResponse(store.load().public)

    @router.get('/tiles/{revision}/{time}/{z}/{x}/{y}.png')
    def tile(request: Request, revision: str, time: int, z: int, x: int, y: int):
        check_access(request)
        return Response(store.read_tile(revision, (time, z, x, y)), media_type='image/png')

    return router
