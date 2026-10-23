"""Same-origin analytical workspace routes. Query endpoints never fetch upstream."""
from fastapi import APIRouter, HTTPException, Query, Request

from wici.workspace_models import MovingReplay, SavedView, WorkspaceQuery
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
        return result

    @router.get('/watchlist')
    def watchlist(request: Request):
        return request.app.state.workspace.watchlist()

    @router.put('/watchlist/{ref}')
    def watch(request: Request, ref: str):
        return _call(request.app.state.workspace.moving.watch, ref, True)

    @router.delete('/watchlist/{ref}')
    def unwatch(request: Request, ref: str):
        return _call(request.app.state.workspace.moving.watch, ref, False)

    @router.post('/moving/replay')
    def replay(request: Request, body: MovingReplay):
        return _call(request.app.state.workspace.moving.replay, body)

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

    return router
