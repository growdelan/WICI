"""Validated selectors for durable analyst notes and server-captured evidence."""
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from wici.workspace_models import MovingRef, StrictModel, UkraineRegionRef, WorkspaceQuery

ObjectRef = Annotated[str, Field(max_length=300, pattern=(
    r'^(communication:[0-9]+|hydro_station:imgw:[A-Za-z0-9_-]+|air_quality_station:gios:[0-9]+|'
    r'area:prg:[0-9]{2,4}|aircraft:icao:[a-f0-9]{6}|ship:mmsi:[1-9][0-9]{8}|'
    r'ua_region:neptun:(oblast|raion):[^\x00-\x1f]{1,256}|civil_alert:neptun:[a-f0-9-]{36})$'))]


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
    kind: Literal['object', 'timeline', 'comparison']
    title: str | None = Field(default=None, max_length=160)
    ref: ObjectRef | None = None
    query: WorkspaceQuery
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
