"""Bounded graph selectors and local analyst assertions."""
import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from wici.dossier_models import ObjectRef
from wici.workspace_models import ObjectType, StrictModel, TimeContext

RELATION_TYPES = ('communication_area', 'station_area', 'administrative_parent',
                  'region_parent', 'alert_region', 'reported_in_area', 'analyst_related')
RelationType = Literal['communication_area', 'station_area', 'administrative_parent',
                       'region_parent', 'alert_region', 'reported_in_area', 'analyst_related']
Category = Literal['source', 'derived', 'analyst']


class GraphQuery(StrictModel):
    seed_refs: list[ObjectRef] = Field(min_length=1, max_length=20)
    node_refs: list[ObjectRef] = Field(default_factory=list, max_length=200)
    expanded_refs: list[ObjectRef] = Field(default_factory=list, max_length=200)
    relation_types: list[RelationType] = Field(default_factory=list, max_length=7)
    categories: list[Category] = Field(default_factory=list, max_length=3)
    time: TimeContext = Field(default_factory=TimeContext)
    cursor_at: datetime | None = None
    version_ids: dict[ObjectRef, int] = Field(default_factory=dict, max_length=200)
    dossier_id: str | None = Field(default=None, max_length=100)
    as_of: datetime | None = None
    expected_revision: str | None = Field(default=None, max_length=128)
    display_timezone: Literal['Europe/Warsaw', 'Europe/Kyiv', 'UTC'] = 'Europe/Warsaw'

    @field_validator('as_of', 'cursor_at')
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('Czas wymaga strefy czasowej')
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode='after')
    def coherent(self):
        for values in (self.seed_refs, self.node_refs, self.expanded_refs, self.relation_types, self.categories):
            if len(values) != len(set(values)):
                raise ValueError('Elementy grafu nie mogą się powtarzać')
        if not self.node_refs:
            self.node_refs = list(self.seed_refs)
        if not set(self.seed_refs).issubset(self.node_refs):
            raise ValueError('Obiekty początkowe muszą należeć do grafu')
        if not set(self.expanded_refs).issubset(self.node_refs):
            raise ValueError('Rozwijane obiekty muszą należeć do grafu')
        if self.cursor_at:
            interval = self.time.filter_range
            if interval is None or not interval.start <= self.cursor_at < interval.end:
                raise ValueError('Kursor musi mieścić się w przedziale')
        for interval in (self.time.filter_range, self.time.overview_range):
            limit = 14 if any(r.startswith(('aircraft:', 'ship:')) for r in self.node_refs) else 30
            if interval and (interval.end-interval.start).total_seconds() > limit*86400:
                raise ValueError(f'Graf obejmuje najwyżej {limit} dni')
        for ref, value in self.version_ids.items():
            if not ref.startswith('communication:') or value < 1 or ref not in self.node_refs:
                raise ValueError('Wersja musi wskazywać komunikat należący do grafu')
        if self.expected_revision and self.as_of is None:
            raise ValueError('Rewizja grafu wymaga czasu as_of')
        return self


class GraphNeighbors(StrictModel):
    graph: GraphQuery
    ref: ObjectRef
    cursor: str | None = Field(default=None, max_length=4096)
    limit: int = Field(default=50, ge=1, le=50)

    @model_validator(mode='after')
    def known_node(self):
        if self.ref not in self.graph.node_refs:
            raise ValueError('Rozwijany obiekt musi należeć do grafu')
        return self


class AnalystRelation(StrictModel):
    source_ref: ObjectRef
    target_ref: ObjectRef
    justification: str = Field(min_length=1, max_length=5000)
    note_id: str | None = Field(default=None, max_length=100)
    material_id: str | None = Field(default=None, max_length=100)
    revision: int | None = Field(default=None, ge=1)

    @field_validator('justification')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Podaj uzasadnienie relacji analitycznej')
        return value.strip()

    @model_validator(mode='after')
    def distinct(self):
        if self.source_ref == self.target_ref:
            raise ValueError('Relacja wymaga dwóch różnych obiektów')
        return self


class GraphPosition(StrictModel):
    x: float
    y: float

    @field_validator('x', 'y')
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value) or abs(value) > 1000000:
            raise ValueError('Nieprawidłowa pozycja węzła')
        return value


class WorkingGraph(StrictModel):
    graph: GraphQuery
    positions: dict[ObjectRef, GraphPosition] = Field(default_factory=dict, max_length=200)
    hidden_refs: list[ObjectRef] = Field(default_factory=list, max_length=200)
    layout: Literal['breadthfirst', 'concentric'] = 'breadthfirst'
    node_type: ObjectType | None = None
    revision: int | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def positions_in_graph(self):
        if not set(self.positions).issubset(self.graph.node_refs):
            raise ValueError('Pozycje muszą dotyczyć węzłów grafu')
        if len(self.hidden_refs) != len(set(self.hidden_refs)) or not set(self.hidden_refs).issubset(self.graph.node_refs):
            raise ValueError('Ukryte węzły muszą należeć do grafu')
        return self
