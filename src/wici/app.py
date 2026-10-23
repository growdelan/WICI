"""Loopback-only API and static UI with per-start CSRF protection."""
import asyncio
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from datetime import date as CivilDate
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from wici.aircraft import AircraftService
from wici.buses import CityBusService
from wici.config import ROOT, Config
from wici.demo import DEMO_NOW, seed
from wici.effis import EffisService
from wici.gddkia import GddkiaService
from wici.gfm import GFMService, GFMUnavailable
from wici.gfm_monitor import GFMMonitor, view_bbox
from wici.gios import GiosService
from wici.hydro import HydroService
from wici.imagery import ImageryService, ImageryUnavailable
from wici.lightning import LightningService, LightningUnavailable
from wici.moving_ingestion import MovingIngestion
from wici.position_quality import PositionQuality
from wici.radar import RadarService, RadarUnavailable
from wici.repository import Repository
from wici.runtime import InstanceLock, configure_logs
from wici.scheduler import Scheduler
from wici.sentinel2 import SentinelError, SentinelService
from wici.sentinel5p import Sentinel5PError, Sentinel5PService
from wici.ships import ShipService
from wici.station_history import StationHistory
from wici.tracking import TrackingService, TrackRequest
from wici.traffic import RoadService, TrafficService, TrafficUnavailable
from wici.trains import TrainService
from wici.ukraine import UkraineService
from wici.weather import WeatherService
from wici.workspace_api import create_workspace_router
from wici.workspace_service import WorkspaceService


def create_app(demo=False, root=ROOT, config=None, client=None):
    config = config or Config.load(root)
    static = Path(__file__).with_name('static')
    token = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{config.port}'

    @asynccontextmanager
    async def lifespan(app):
        directory = root / 'var' / ('demo' if demo else 'live')
        lock = InstanceLock(directory)
        handler = configure_logs(directory/'logs')
        repo = None
        network = None
        scheduler = None
        ships = None
        quality = None
        tracking = None
        station_history = None
        moving_ingestion = None
        try:
            repo = Repository(directory/'app.sqlite3',clock=(lambda:DEMO_NOW) if demo else (lambda:datetime.now(UTC)))
            station_history = StationHistory(repo)
            station_history.start()
            app.state.station_history = station_history
            network = client or httpx.AsyncClient(timeout=config.timeout_seconds,follow_redirects=False,
                headers={'User-Agent':'WICI-local/0.1 (private local pilot)'})
            scheduler = Scheduler(repo,config,network,demo)
            app.state.repo, app.state.scheduler = repo,scheduler
            app.state.effis = EffisService(network, repo.clock, config.timeout_seconds, demo)
            app.state.gddkia = GddkiaService(network, repo.clock, config.timeout_seconds,
                enabled=config.enabled('gddkia'), demo=demo)
            app.state.aircraft = AircraftService(network, repo.clock, config.timeout_seconds,
                enabled=config.enabled('aircraft'), demo=demo)
            app.state.ukraine = UkraineService(network, repo.clock, config.timeout_seconds,
                enabled=config.enabled('ukraine'), demo=demo)
            quality = PositionQuality(repo, app.state.aircraft, enabled=config.position_quality.enabled,
                interval=config.position_quality.interval_seconds, retention=config.position_quality.retention_hours, demo=demo)
            app.state.position_quality = quality
            quality.start()
            app.state.buses = CityBusService(network, repo.clock, config, demo=demo)
            app.state.trains = TrainService(network, repo.clock, timeout=config.timeout_seconds,
                enabled=config.enabled('trains'), demo=demo)
            ships = ShipService(repo.clock, key=config.ships_key(), enabled=config.enabled('ships'), demo=demo)
            app.state.ships = ships
            tracking = TrackingService(repo, app.state.aircraft, ships, demo=demo)
            app.state.tracking = tracking
            tracking.start()
            app.state.lightning = LightningService(network, repo.clock, config.timeout_seconds, enabled=config.enabled('lightning'), demo=demo)
            app.state.radar = RadarService(network, repo.clock, config.timeout_seconds, enabled=config.enabled('radar'), demo=demo)
            app.state.imagery = ImageryService(network, repo.clock, config.timeout_seconds,
                enabled=config.enabled('imagery'), demo=demo)
            app.state.gios = GiosService(network, repo.clock, config.timeout_seconds,
                enabled=config.enabled('gios'), demo=demo, history=station_history)
            app.state.gfm = GFMService(network, repo.clock, enabled=config.enabled('gfm'), demo=demo)
            app.state.sentinel2 = SentinelService(network, config, demo=demo)
            app.state.sentinel5p = Sentinel5PService(network, config, demo=demo)
            app.state.gfm_monitor = GFMMonitor(app.state.gfm)
            app.state.hydro = HydroService(network, repo.clock, config.timeout_seconds,
                enabled=config.enabled('hydro_imgw'), demo=demo, history=station_history)
            app.state.weather = WeatherService(network, repo.clock, config.timeout_seconds, demo=demo,
                measurement_enabled=config.enabled('weather_imgw'),
                forecast_enabled=config.enabled('weather_forecast'))
            app.state.traffic = TrafficService(network, repo.clock, directory/'tomtom-usage.json',
                key=config.tomtom_key(), enabled=config.enabled('tomtom'), demo=demo,
                timeout=config.timeout_seconds)
            app.state.roads = RoadService(network, repo.clock, directory/'tomtom-road-usage.json',
                key=config.tomtom_key(), enabled=config.enabled('tomtom'), demo=demo,
                timeout=config.timeout_seconds, monthly_limit=19_000)
            if demo:
                seed(repo)
            app.state.workspace = WorkspaceService(repo)
            moving_ingestion = MovingIngestion(app.state.workspace.moving)
            app.state.moving_ingestion = moving_ingestion
            app.state.aircraft.on_snapshot = moving_ingestion.enqueue
            ships.on_snapshot = moving_ingestion.enqueue
            app.state.workspace.source_enabled = {
                'hydro:stations': app.state.hydro.enabled and not demo,
                'gios:stations': app.state.gios.enabled and not demo,
                'aircraft': app.state.aircraft.enabled and not demo,
                'ships': ships.enabled and bool(config.ships_key()) and not demo,
            }
            if demo:
                from wici.workspace_demo import seed_workspace
                seed_workspace(repo, station_history)
            scheduler.start()
            yield
        finally:
            if tracking:
                await tracking.close()
            if quality:
                await quality.stop()
            if ships:
                await ships.stop()
            if scheduler:
                await scheduler.stop()
            if hasattr(app.state, 'sentinel2'):
                await app.state.sentinel2.close()
            if hasattr(app.state, 'sentinel5p'):
                await app.state.sentinel5p.close()
            if hasattr(app.state, 'gfm_monitor'):
                await app.state.gfm_monitor.close()
            if network and client is None:
                await network.aclose()
            if station_history:
                await station_history.close()
            if moving_ingestion:
                await moving_ingestion.close()
            if repo:
                repo.close()
            handler.close()
            import logging
            logging.getLogger('wici').removeHandler(handler)
            lock.close()

    app = FastAPI(title='WICI',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.include_router(create_workspace_router())

    @app.middleware('http')
    async def security(request,call_next):
        if request.headers.get('host') != f'127.0.0.1:{config.port}':
            return JSONResponse({'detail':'Niedozwolony Host'},status_code=400)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.headers.get('origin')!=origin or not secrets.compare_digest(request.headers.get('x-csrf-token',''),token):
                return JSONResponse({'detail':'Nieprawidłowe pochodzenie lub token CSRF'},status_code=403)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse({'detail':'Żądanie zbyt duże'},status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        # Cesium fetches raster tiles before decoding them through local blob URLs.
        # Workers and all scripts stay local; demo authorizes no external origins.
        # Cesium initializes local meshopt WASM at startup. JavaScript eval stays forbidden.
        map_origin = ' https://tile.openstreetmap.org' if not demo else ''
        image_sources = "'self' data: blob:" + map_origin
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; connect-src 'self'{map_origin}; script-src 'self' 'wasm-unsafe-eval'; "
            "worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
            f"img-src {image_sources}; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        response.headers['X-Content-Type-Options']='nosniff'
        # OSM requires a valid browser Referer for both Leaflet and Cesium tiles.
        # Cross-origin requests disclose only the local origin, never paths/queries.
        response.headers['Referrer-Policy']='no-referrer' if demo else 'strict-origin-when-cross-origin'
        response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api') else 'no-cache'
        return response

    @app.exception_handler(KeyError)
    async def missing(request,exc):
        return JSONResponse({'detail':'Nie znaleziono obiektu'},status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=422)

    @app.get('/')
    def index():
        return FileResponse(static/'index.html')
    @app.get('/notices')
    def notices():
        return FileResponse(root/'THIRD_PARTY_NOTICES.md',media_type='text/plain; charset=utf-8')
    @app.get('/api/health')
    def health():
        return {'mode':'demo' if demo else 'live','now':app.state.repo.clock().isoformat(),
                'csrf_token':token,'gap_seconds':app.state.scheduler.gap_seconds,'presentation':'automatic_communications'}
    @app.get('/api/sources')
    def sources():
        return {'items':app.state.scheduler.sources()}
    @app.post('/api/sources/{source_id}/refresh')
    async def refresh(source_id:str):
        return {'scheduled':app.state.scheduler.refresh(source_id)}
    @app.get('/api/communications')
    def communications(date:CivilDate|None=None,voivodeship:str|None=None,source_id:str|None=None,
                       communication_type:str|None=None,category:str|None=None,
                       include_active:bool=False,limit:int=1000):
        return app.state.repo.list_communications(dict(locals(),date=date.isoformat() if date else None),
                                                  limit=max(1,min(limit,1000)))
    @app.get('/api/communications/{document_id}')
    def communication(document_id:int):
        return app.state.repo.communication_detail(document_id)
    @app.get('/api/ioda')
    def ioda(hours:int=24,date:CivilDate|None=None,level:Literal['country','region','asn']|None=None,
             voivodeship:str|None=None,limit:int=500):
        return app.state.repo.list_ioda(hours,date.isoformat() if date else None,level,voivodeship,limit)

    @app.get('/api/fires')
    def fires(hours:int=24,date:CivilDate|None=None,voivodeship:str|None=None,limit:int=2000):
        return app.state.repo.list_fires(hours,date.isoformat() if date else None,voivodeship,limit)
    @app.get('/api/effis')
    async def effis(day:CivilDate|None=None):
        return await app.state.effis.metadata(day)
    @app.get('/api/traffic')
    async def traffic():
        return app.state.traffic.metadata()
    @app.get('/api/lightning')
    async def lightning(request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        return await app.state.lightning.metadata()
    @app.get('/api/lightning/map')
    async def lightning_map(time:int,request:Request):
        if request.headers.get('sec-fetch-site','same-origin')!='same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        try:
            return Response((await app.state.lightning.image(time))['body'],media_type='image/png')
        except LightningUnavailable as exc:
            return JSONResponse({'detail':str(exc)},status_code=503)
    @app.get('/api/lightning/legend')
    async def lightning_legend(request:Request):
        if request.headers.get('sec-fetch-site','same-origin')!='same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        try:
            return Response(await app.state.lightning.legend_image(),media_type='image/png')
        except LightningUnavailable as exc:
            return JSONResponse({'detail':str(exc)},status_code=503)
    @app.get('/api/lightning/point')
    async def lightning_point(time:int,lat:float,lon:float,request:Request):
        if request.headers.get('sec-fetch-site','same-origin')!='same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        try:
            return await app.state.lightning.point(time,lat,lon)
        except LightningUnavailable as exc:
            return JSONResponse({'detail':str(exc)},status_code=503)
    @app.get('/api/radar')
    async def radar(request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        return await app.state.radar.metadata()
    @app.get('/api/radar/tiles/{time}/{z}/{x}/{y}.png')
    async def radar_tile(time:int, z:int, x:int, y:int, request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            return Response(await app.state.radar.tile(time,z,x,y), media_type='image/png')
        except RadarUnavailable as exc:
            return JSONResponse({'detail':str(exc)}, status_code=503)
    @app.get('/api/imagery')
    async def imagery(request:Request, lat:float, lon:float):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        return await app.state.imagery.search(lat, lon)
    @app.get('/api/imagery/preview/{image_id}')
    async def imagery_preview(image_id:str, request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            body, media_type = await app.state.imagery.preview(image_id)
            return Response(body, media_type=media_type)
        except ImageryUnavailable as exc:
            return JSONResponse({'detail':str(exc)}, status_code=503)
    @app.get('/api/gios')
    async def gios(request:Request, kind:Literal['stations', 'sensors', 'data', 'index']='stations',
                   id:int | None=None):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        if kind != 'stations' and (id is None or id <= 0 or id > 2**63-1):
            return JSONResponse({'detail':'Wymagany poprawny identyfikator GIOŚ'}, status_code=422)
        result = await app.state.gios.fetch(kind, id if kind != 'stations' else None)
        await app.state.station_history.flush()
        return result
    @app.get('/api/sentinel2/status')
    @app.get('/api/sentinel2/search')
    @app.get('/api/sentinel2/render')
    async def sentinel2(request: Request, lat: float = 52.05, lon: float = 19.2,
                        size: float = 4, start: str = '', end: str = '', cloud: float = 80,
                        identifier: str = '', full_only: bool = True):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        svc = app.state.sentinel2
        try:
            if request.url.path.endswith('/status'):
                return svc.status()
            if request.url.path.endswith('/search'):
                return await svc.search(lat, lon, size, start, end, cloud, full_only=full_only)
            return await svc.render(lat, lon, size, identifier)
        except SentinelError as exc:
            return JSONResponse({'detail': str(exc)}, status_code=exc.code,
                                headers={'Retry-After': str(exc.retry)} if exc.retry else {})

    @app.get('/api/sentinel5p/status')
    @app.get('/api/sentinel5p/search')
    @app.get('/api/sentinel5p/render')
    async def sentinel5p(request: Request, parameter: Literal['no2', 'so2', 'aer_ai'] = 'no2',
                         day: str = '', identifier: str = ''):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        svc = app.state.sentinel5p
        try:
            if request.url.path.endswith('/status'):
                return svc.status()
            if request.url.path.endswith('/search'):
                return await svc.search(parameter, day)
            return await svc.render(parameter, day, identifier)
        except Sentinel5PError as exc:
            return JSONResponse({'detail': str(exc), 'status': exc.status}, status_code=exc.code,
                                headers={'Retry-After': str(exc.retry)} if exc.retry else {})

    @app.get('/api/gfm')
    async def gfm_search(request:Request, bbox:str, start:str, end:str):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            return await app.state.gfm.search(bbox.split(','), start, end)
        except ValueError as exc:
            return JSONResponse({'detail':str(exc)}, status_code=422)
        except (GFMUnavailable, TimeoutError, httpx.HTTPError, KeyError, TypeError) as exc:
            return JSONResponse({'detail':str(exc) or 'GFM niedostępne'}, status_code=503)

    @app.get('/api/gfm/monitor')
    async def gfm_monitor(request:Request, bbox:str | None=None):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            return await app.state.gfm_monitor.snapshot(view_bbox(bbox))
        except ValueError as exc:
            return JSONResponse({'detail':str(exc)}, status_code=422)

    @app.get('/api/gfm/render/{identifier}')
    async def gfm_render(request:Request, identifier:str, bbox:str):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            return await app.state.gfm.render(identifier, bbox.split(','))
        except ValueError as exc:
            return JSONResponse({'detail':str(exc)}, status_code=422)
        except KeyError:
            return JSONResponse({'detail':'Wyszukaj obserwacje ponownie.'}, status_code=404)
        except (GFMUnavailable, TimeoutError) as exc:
            return JSONResponse({'detail':str(exc)}, status_code=503)

    @app.get('/api/hydro')
    async def hydro(request:Request, kind:Literal['stations', 'warnings']='stations'):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        result = await app.state.hydro.fetch(kind)
        await app.state.station_history.flush()
        return result
    @app.get('/api/weather')
    async def weather(request:Request, mode:str='measurement', voivodeship:str=''):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        return await app.state.weather.fetch(mode, voivodeship)
    @app.get('/api/gddkia')
    async def gddkia(request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        return await app.state.gddkia.fetch()
    @app.get('/api/position-quality')
    async def position_quality(request: Request, date: CivilDate | None = None,
                               hours: Literal['24', '48'] = '24', voivodeship: str | None = None):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        from wici.daily import WARSAW
        day = date or app.state.repo.clock().astimezone(WARSAW).date()
        return await asyncio.to_thread(app.state.position_quality.history, day, int(hours), voivodeship)

    @app.get('/api/aircraft')
    async def aircraft(request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        snapshot = await app.state.aircraft.fetch()
        app.state.moving_ingestion.enqueue('aircraft', snapshot)
        await app.state.moving_ingestion.flush(timeout=0.1)
        return snapshot
    @app.get('/api/ukraine')
    async def ukraine(request:Request):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        return await app.state.ukraine.fetch()
    @app.get('/api/ukraine/geometry')
    async def ukraine_geometry(request:Request):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        return await app.state.ukraine.geometry()
    @app.get('/api/buses')
    async def buses(request:Request, city:Literal['szczecin', 'krakow', 'poznan', 'warszawa']='szczecin'):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        return await app.state.buses.fetch(city)
    @app.get('/api/ships')
    async def ships(request:Request):
        if (request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'
                or request.headers.get('origin', origin) != origin):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        snapshot = await app.state.ships.fetch()
        app.state.moving_ingestion.enqueue('ship', snapshot)
        await app.state.moving_ingestion.flush(timeout=0.1)
        return snapshot

    def tracking_origin_allowed(request):
        return (request.headers.get('sec-fetch-site', 'same-origin') == 'same-origin'
                and request.headers.get('origin', origin) == origin)

    @app.get('/api/tracks')
    async def tracks(request: Request):
        if not tracking_origin_allowed(request):
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        return await asyncio.to_thread(app.state.tracking.listing)

    @app.post('/api/tracks')
    async def start_track(request: Request, body: TrackRequest):
        if not tracking_origin_allowed(request):
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        return await app.state.tracking.begin(body.kind, body.object_id)

    @app.get('/api/tracks/{track_id}')
    async def track_history(track_id: str, request: Request):
        if not tracking_origin_allowed(request):
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        return await asyncio.to_thread(app.state.tracking.detail, track_id)

    @app.post('/api/tracks/{track_id}/stop')
    async def stop_track(track_id: str, request: Request):
        if not tracking_origin_allowed(request):
            return JSONResponse({'detail': 'Niedozwolone pochodzenie'}, status_code=403)
        return await app.state.tracking.stop(track_id)

    def train_origin_allowed(request):
        return (request.headers.get('sec-fetch-site', 'same-origin') == 'same-origin'
                and request.headers.get('origin', origin) == origin)

    @app.get('/api/trains/stations')
    async def train_stations(request:Request):
        if not train_origin_allowed(request):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        return await app.state.trains.stations()

    @app.get('/api/trains/positions')
    async def train_positions(request:Request):
        if not train_origin_allowed(request):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        return await app.state.trains.positions()

    @app.get('/api/trains/stations/{station_id}')
    async def train_station(station_id:str, request:Request):
        if not train_origin_allowed(request):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        result = await app.state.trains.station(station_id)
        return JSONResponse(result, status_code=404 if result.get('status') == 'not_found' else 200)

    @app.get('/api/trains/trips/{trip_id}')
    async def train_trip(trip_id:str, start_date:CivilDate, request:Request):
        if not train_origin_allowed(request):
            return JSONResponse({'detail':'Niedozwolone pochodzenie'},status_code=403)
        result = await app.state.trains.trip(trip_id, start_date.isoformat())
        return JSONResponse(result, status_code=404 if result.get('status') == 'not_found' else 200)
    @app.get('/api/traffic/road')
    async def traffic_road(lat:float, lon:float, request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            return await app.state.roads.lookup(lat, lon)
        except TrafficUnavailable as exc:
            return JSONResponse({'detail':str(exc)}, status_code=503)
    @app.get('/api/traffic/tiles/{z}/{x}/{y}.png')
    async def traffic_tile(z:int, x:int, y:int, request:Request):
        if request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin':
            return JSONResponse({'detail':'Niedozwolone pochodzenie'}, status_code=403)
        try:
            image = await app.state.traffic.tile(z, x, y)
        except TrafficUnavailable as exc:
            return JSONResponse({'detail':str(exc)}, status_code=503)
        return Response(image, media_type='image/png')
    @app.get('/api/effis/map')
    async def effis_map(day:CivilDate|None=None):
        image = await app.state.effis.map_image(day)
        if image is None:
            return JSONResponse({'detail':'Prognoza EFFIS niedostępna'},status_code=503)
        return Response(image,media_type='image/png')
    @app.get('/api/effis/legend')
    async def effis_legend(day:CivilDate|None=None):
        image = await app.state.effis.legend_image(day)
        if image is None:
            return JSONResponse({'detail':'Legenda EFFIS niedostępna'},status_code=503)
        return Response(image,media_type='image/png')
    app.mount('/static',StaticFiles(directory=static),name='static')
    return app
