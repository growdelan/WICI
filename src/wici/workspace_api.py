"""Same-origin analytical workspace routes. Query endpoints never fetch upstream."""
import inspect

from fastapi import APIRouter, HTTPException, Query, Request

from wici.dossier_models import DossierInput, DossierNote, DossierPin, MaterialCapture
from wici.workspace_models import MovingReplay, SavedView, UkraineRecording, UkraineReplay, WorkspaceQuery
from wici.workspace_service import QueryChanged


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except QueryChanged as error:
        raise HTTPException(409, detail={'code': 'query_changed', 'message': str(error)}) from error
    except KeyError as error:
        raise HTTPException(404, detail='Obiekt lub widok nie istnieje') from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error


def create_workspace_router():
    router = APIRouter(prefix='/api/workspace')

    @router.post('/query')
    def query(request: Request, body: WorkspaceQuery):
        return _call(request.app.state.workspace.query, body)

    @router.get('/status')
    def status(request: Request):
        result = request.app.state.workspace.status()
        history = getattr(request.app.state, 'station_history', None)
        if history is not None and hasattr(history, 'status'):
            result['persistence'] = history.status()
        moving = getattr(request.app.state, 'moving_ingestion', None)
        if moving is not None:
            result['moving_persistence'] = moving.status()
        ukraine = getattr(request.app.state, 'ukraine_collector', None)
        if ukraine is not None:
            result['ukraine_recording'] = ukraine.status()
        return result

    @router.get('/watchlist')
    def watchlist(request: Request):
        return request.app.state.workspace.watchlist()

    @router.put('/watchlist/{ref}')
    def watch(request: Request, ref: str):
        return _call(request.app.state.workspace.watch, ref, True)

    @router.delete('/watchlist/{ref}')
    def unwatch(request: Request, ref: str):
        return _call(request.app.state.workspace.watch, ref, False)

    @router.post('/moving/replay')
    def replay(request: Request, body: MovingReplay):
        return _call(request.app.state.workspace.moving.replay, body)

    @router.get('/ukraine/regions')
    def ukraine_regions(request: Request):
        return request.app.state.workspace.ukraine_regions()

    @router.post('/ukraine/replay')
    def ukraine_replay(request: Request, body: UkraineReplay):
        return _call(request.app.state.workspace.ukraine_replay, body)

    @router.get('/ukraine/recording')
    def ukraine_recording(request: Request):
        collector = getattr(request.app.state, 'ukraine_collector', None)
        return collector.status() if collector is not None else request.app.state.workspace.ukraine.status()

    @router.put('/ukraine/recording')
    async def set_ukraine_recording(request: Request, body: UkraineRecording):
        collector = getattr(request.app.state, 'ukraine_collector', None)
        if collector is None:
            raise HTTPException(503, detail='Kolektor historii Ukrainy jest niedostępny')
        try:
            result = collector.set_enabled(body.enabled)
            if inspect.isawaitable(result):
                await result
            return collector.status()
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    @router.get('/objects/{ref}')
    def detail(request: Request, ref: str, as_of: str | None = None, data_revision: str | None = None,
               cursor_at: str | None = None, sensor_id: str | None = None, metric: str | None = None,
               version_id: int | None = None):
        return _call(request.app.state.workspace.detail, ref, as_of, data_revision, cursor_at,
                     sensor_id, metric, version_id)

    @router.get('/objects/{ref}/timeline')
    def timeline(request: Request, ref: str, start: str | None = Query(None, alias='from'),
                 end: str | None = Query(None, alias='to'), sensor_id: str | None = None,
                 metric: str | None = None, cursor: str | None = None,
                 limit: int = Query(2000, ge=1, le=2000), as_of: str | None = None,
                 data_revision: str | None = None, index_cursor: str | None = None):
        return _call(request.app.state.workspace.timeline, ref, start, end, sensor_id,
                     metric, cursor, limit, as_of, data_revision, index_cursor)

    @router.get('/views')
    def views(request: Request):
        return request.app.state.workspace.views()

    @router.post('/views', status_code=201)
    def create_view(request: Request, body: SavedView):
        return _call(request.app.state.workspace.save_view, body)

    @router.put('/views/{view_id}')
    def update_view(request: Request, view_id: str, body: SavedView):
        return _call(request.app.state.workspace.save_view, body, view_id)

    @router.delete('/views/{view_id}')
    def delete_view(request: Request, view_id: str):
        return _call(request.app.state.workspace.delete_view, view_id)

    @router.get('/dossiers')
    def dossiers(request: Request):
        return request.app.state.workspace.dossiers.list()

    @router.post('/dossiers', status_code=201)
    def create_dossier(request: Request, body: DossierInput):
        return _call(request.app.state.workspace.dossiers.save, body)

    @router.get('/dossiers/{dossier_id}')
    def dossier(request: Request, dossier_id: str):
        return _call(request.app.state.workspace.dossiers.detail, dossier_id)

    @router.put('/dossiers/{dossier_id}')
    def update_dossier(request: Request, dossier_id: str, body: DossierInput):
        return _call(request.app.state.workspace.dossiers.save, body, dossier_id)

    @router.delete('/dossiers/{dossier_id}')
    def delete_dossier(request: Request, dossier_id: str, revision: int = Query(..., ge=1)):
        return _call(request.app.state.workspace.dossiers.delete, dossier_id, revision)

    @router.post('/dossiers/{dossier_id}/pins', status_code=201)
    def pin_object(request: Request, dossier_id: str, body: DossierPin):
        return _call(request.app.state.workspace.dossiers.pin, dossier_id, body)

    @router.delete('/dossiers/{dossier_id}/pins/{ref}')
    def unpin_object(request: Request, dossier_id: str, ref: str):
        return _call(request.app.state.workspace.dossiers.unpin, dossier_id, ref)

    @router.post('/dossiers/{dossier_id}/notes', status_code=201)
    def create_note(request: Request, dossier_id: str, body: DossierNote):
        return _call(request.app.state.workspace.dossiers.save_note, dossier_id, body)

    @router.put('/dossiers/{dossier_id}/notes/{note_id}')
    def update_note(request: Request, dossier_id: str, note_id: str, body: DossierNote):
        return _call(request.app.state.workspace.dossiers.save_note, dossier_id, body, note_id)

    @router.delete('/dossiers/{dossier_id}/notes/{note_id}')
    def delete_note(request: Request, dossier_id: str, note_id: str, revision: int = Query(..., ge=1)):
        return _call(request.app.state.workspace.dossiers.delete_note, dossier_id, note_id, revision)

    @router.post('/dossiers/{dossier_id}/materials', status_code=201)
    def capture_material(request: Request, dossier_id: str, body: MaterialCapture):
        return _call(request.app.state.workspace.dossiers.capture, dossier_id, body)

    @router.get('/dossiers/{dossier_id}/materials/{material_id}')
    def material(request: Request, dossier_id: str, material_id: str):
        return _call(request.app.state.workspace.dossiers.material, dossier_id, material_id)

    @router.delete('/dossiers/{dossier_id}/materials/{material_id}')
    def delete_material(request: Request, dossier_id: str, material_id: str):
        return _call(request.app.state.workspace.dossiers.delete_material, dossier_id, material_id)

    return router
