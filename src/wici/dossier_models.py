"""Validated selectors for durable analyst notes and server-captured evidence."""
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from wici.workspace_models import MovingRef, ObjectType, StrictModel, UkraineRegionRef, WorkspaceQuery

ObjectRef = Annotated[str, Field(max_length=300, pattern=(
    r'^(communication:[0-9]+|hydro_station:imgw:[A-Za-z0-9_-]+|air_quality_station:gios:[0-9]+|'
    r'area:prg:[0-9]{2,4}|aircraft:icao:[a-f0-9]{6}|ship:mmsi:[1-9][0-9]{8}|'
    r'ua_region:neptun:(oblast|raion):[^\x00-\x1f]{1,256}|civil_alert:neptun:[a-f0-9-]{36}|custom_area:[a-f0-9-]{36})$'))]


class DossierInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=5000)
    revision: int | None = Field(default=None, ge=1)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Podaj nazwę teczki')
        return value.strip()


class DossierNote(StrictModel):
    body: str = Field(min_length=1, max_length=20000)
    revision: int | None = Field(default=None, ge=1)

    @field_validator('body')
    @classmethod
    def body_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Notatka nie może być pusta')
        return value.strip()


class DossierPin(StrictModel):
    ref: ObjectRef


class MaterialCapture(StrictModel):
    kind: Literal['object', 'timeline', 'comparison', 'graph']
    title: str | None = Field(default=None, max_length=160)
    ref: ObjectRef | None = None
    query: WorkspaceQuery | None = None
    graph: dict | None = None
    positions: dict = Field(default_factory=dict, max_length=200)
    hidden_refs: list[ObjectRef] = Field(default_factory=list, max_length=200)
    layout: Literal['breadthfirst', 'concentric'] = 'breadthfirst'
    node_type: ObjectType | None = None
    cursor_at: datetime | None = None
    sensor_id: str | None = Field(default=None, max_length=100)
    metric: str | None = Field(default=None, max_length=100)
    version_id: int | None = Field(default=None, ge=1)
    moving_refs: list[MovingRef] = Field(default_factory=list, max_length=5)
    region_refs: list[UkraineRegionRef] = Field(default_factory=list, max_length=5)
    as_of: datetime | None = None
    data_revision: str | None = Field(default=None, min_length=1, max_length=256)
    display_timezone: Literal['Europe/Warsaw', 'Europe/Kyiv', 'UTC'] = 'Europe/Warsaw'

    @field_validator('as_of', 'cursor_at')
    @classmethod
    def aware(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError('Czas wymaga strefy czasowej')
            return value.astimezone(UTC)
        return value

    @field_validator('title')
    @classmethod
    def clean_title(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode='after')
    def coherent_selection(self):
        if self.kind == 'graph':
            from wici.relation_models import GraphPosition, GraphQuery
            if self.graph is None or self.query is not None or self.ref is not None or self.sensor_id or self.metric or self.version_id or self.moving_refs or self.region_refs:
                raise ValueError('Zapis grafu wymaga wyłącznie selektora grafu')
            graph = GraphQuery.model_validate(self.graph)
            if not graph.expected_revision or graph.as_of is None:
                raise ValueError('Przed zapisem wczytaj aktualną rewizję grafu')
            if not set(self.positions).issubset(graph.node_refs) or not set(self.hidden_refs).issubset(graph.node_refs):
                raise ValueError('Układ musi dotyczyć węzłów grafu')
            if len(set(self.hidden_refs)) != len(self.hidden_refs):
                raise ValueError('Ukryte węzły nie mogą się powtarzać')
            self.positions = {key: GraphPosition.model_validate(value).model_dump() for key, value in self.positions.items()}
            self.graph = graph.model_dump(mode='json', by_alias=True)
            return self
        if self.query is None:
            raise ValueError('Materiał wymaga zapytania katalogu')
        if self.graph is not None or self.positions or self.hidden_refs or self.node_type:
            raise ValueError('Układ grafu dotyczy wyłącznie materiału grafowego')
        if self.query.cursor:
            raise ValueError('Materiał wymaga zapytania bez kursora stronicowania')
        if bool(self.as_of) != bool(self.data_revision):
            raise ValueError('Rewizja danych wymaga as_of i data_revision razem')
        if self.kind != 'comparison' and self.ref is None:
            raise ValueError('Wybierz obiekt do zapisania')
        if self.kind == 'comparison' and not (self.moving_refs or self.region_refs):
            raise ValueError('Wybierz obiekty do porównania')
        if len(set(self.moving_refs)) != len(self.moving_refs) or len(set(self.region_refs)) != len(self.region_refs):
            raise ValueError('Obiekty porównania nie mogą się powtarzać')
        if self.kind in ('timeline', 'comparison') and self.query.time.mode != 'range':
            raise ValueError('Zapis historii lub porównania wymaga wybranego przedziału czasu')
        if self.cursor_at is not None:
            interval = self.query.time.filter_range
            if interval is None or not interval.start <= self.cursor_at < interval.end:
                raise ValueError('Kursor musi mieścić się w wybranym przedziale')
        if self.version_id and (self.ref is None or not self.ref.startswith('communication:')):
            raise ValueError('Wersję treści można wybrać wyłącznie dla komunikatu')
        if (self.sensor_id is not None or self.metric is not None) and (
            self.ref is None or not self.ref.startswith(('hydro_station:', 'air_quality_station:'))
        ):
            raise ValueError('Czujnik i parametr dotyczą wyłącznie stacji')
        return self
