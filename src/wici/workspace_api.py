"""Same-origin analytical workspace routes. Query endpoints never fetch upstream."""
import inspect

from fastapi import APIRouter, HTTPException, Query, Request

from wici.area_models import AreaInput
from wici.dossier_models import DossierInput, DossierNote, DossierPin, MaterialCapture
from wici.event_models import EventCapture, EventComment, EventHandling
from wici.relation_models import AnalystRelation, GraphNeighbors, GraphQuery, WorkingGraph
from wici.rule_models import RuleInput, RulePreview
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

    @router.get('/areas')
    def areas(request: Request, include_archived: bool = False):
        return _call(request.app.state.workspace.areas.list, include_archived)

    @router.post('/areas', status_code=201)
    def create_area(request: Request, body: AreaInput):
        return _call(request.app.state.workspace.areas.save, body)

    @router.get('/areas/{area_id}')
    def area(request: Request, area_id: str, revision: int | None = Query(None, ge=1)):
        return _call(request.app.state.workspace.areas.detail, area_id, revision)

    @router.put('/areas/{area_id}')
    def update_area(request: Request, area_id: str, body: AreaInput):
        return _call(request.app.state.workspace.areas.save, body, area_id)

    @router.get('/areas/{area_id}/history')
    def area_history(request: Request, area_id: str):
        return _call(request.app.state.workspace.areas.history, area_id)

    @router.post('/areas/{area_id}/duplicate', status_code=201)
    def duplicate_area(request: Request, area_id: str):
        return _call(request.app.state.workspace.areas.duplicate, area_id)

    @router.get('/areas/{area_id}/members')
    def area_members(request: Request, area_id: str, limit: int = Query(100, ge=1, le=200)):
        return _call(request.app.state.workspace.areas.members, area_id, limit)

    @router.get('/rules')
    def rules(request: Request):
        return _call(request.app.state.workspace.rules.list)

    @router.post('/rules', status_code=201)
    def create_rule(request: Request, body: RuleInput):
        return _call(request.app.state.workspace.rules.save, body)

    @router.post('/rules/preview')
    def preview_rule(request: Request, body: RulePreview):
        return _call(request.app.state.workspace.rules.preview, body)

    @router.get('/rules/{rule_id}')
    def rule(request: Request, rule_id: str):
        return _call(request.app.state.workspace.rules.detail, rule_id)

    @router.put('/rules/{rule_id}')
    def update_rule(request: Request, rule_id: str, body: RuleInput):
        return _call(request.app.state.workspace.rules.save, body, rule_id)

    @router.get('/rules/{rule_id}/history')
    def rule_history(request: Request, rule_id: str):
        return _call(request.app.state.workspace.rules.history, rule_id)

    @router.get('/monitor/status')
    def monitor_status(request: Request):
        return _call(request.app.state.workspace.monitor.status)

    @router.get('/events')
    def events(request: Request, rule_id: str | None = None, area_id: str | None = None,
               object_type: str | None = None, priority: str | None = None,
               start: str | None = Query(None, alias='from'), end: str | None = Query(None, alias='to'),
               status: str | None = None, condition_state: str | None = None,
               limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        return _call(request.app.state.workspace.events.list, rule_id=rule_id, area_id=area_id,
                     object_type=object_type, priority=priority, start=start, end=end,
                     status=status, condition_state=condition_state, limit=limit, offset=offset)

    @router.get('/events/{event_id}')
    def event(request: Request, event_id: str):
        return _call(request.app.state.workspace.events.detail, event_id)

    @router.patch('/events/{event_id}')
    def handle_event(request: Request, event_id: str, body: EventHandling):
        return _call(request.app.state.workspace.events.handle, event_id, body)

    @router.post('/events/{event_id}/comments', status_code=201)
    def comment_event(request: Request, event_id: str, body: EventComment):
        return _call(request.app.state.workspace.events.comment, event_id, body)

    @router.post('/events/{event_id}/capture', status_code=201)
    def capture_event(request: Request, event_id: str, body: EventCapture):
        return _call(request.app.state.workspace.events.capture, event_id, body)

    @router.post('/graph/query')
    def graph_query(request: Request, body: GraphQuery):
        return _call(request.app.state.workspace.relations.query, body)

    @router.post('/graph/neighbors')
    def graph_neighbors(request: Request, body: GraphNeighbors):
        return _call(request.app.state.workspace.relations.neighbors, body)

    @router.get('/dossiers/{dossier_id}/relations')
    def relations(request: Request, dossier_id: str, include_deleted: bool = False):
        return _call(request.app.state.workspace.relations.relations, dossier_id, include_deleted)

    @router.post('/dossiers/{dossier_id}/relations', status_code=201)
    def create_relation(request: Request, dossier_id: str, body: AnalystRelation):
        return _call(request.app.state.workspace.relations.save_relation, dossier_id, body)

    @router.put('/dossiers/{dossier_id}/relations/{relation_id}')
    def update_relation(request: Request, dossier_id: str, relation_id: str, body: AnalystRelation):
        return _call(request.app.state.workspace.relations.save_relation, dossier_id, body, relation_id)

    @router.delete('/dossiers/{dossier_id}/relations/{relation_id}')
    def delete_relation(request: Request, dossier_id: str, relation_id: str, revision: int = Query(..., ge=1)):
        return _call(request.app.state.workspace.relations.delete_relation, dossier_id, relation_id, revision)

    @router.get('/dossiers/{dossier_id}/relations/{relation_id}/history')
    def relation_history(request: Request, dossier_id: str, relation_id: str):
        return _call(request.app.state.workspace.relations.relation_history, dossier_id, relation_id)

    @router.get('/dossiers/{dossier_id}/graph')
    def working_graph(request: Request, dossier_id: str):
        return _call(request.app.state.workspace.relations.working_graph, dossier_id)

    @router.put('/dossiers/{dossier_id}/graph')
    def save_graph(request: Request, dossier_id: str, body: WorkingGraph):
        return _call(request.app.state.workspace.relations.save_graph, dossier_id, body)

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
