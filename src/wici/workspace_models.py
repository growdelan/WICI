"""Strict public contracts for the local analytical workspace."""
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wici.geo import units

ObjectType = Literal['communication', 'hydro_station', 'air_quality_station', 'area', 'aircraft', 'ship']
MovingRef = Annotated[str, Field(pattern=r'^(aircraft:icao:[a-f0-9]{6}|ship:mmsi:[1-9][0-9]{8})$')]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)


class TimeRange(StrictModel):
    start: datetime = Field(alias='from')
    end: datetime = Field(alias='to')

    @field_validator('start', 'end')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Czas wymaga strefy czasowej')
        return value.astimezone(UTC)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('Przedział czasu musi mieć dodatnią długość')
        return self


class TimeContext(StrictModel):
    mode: Literal['live', 'range'] = 'live'
    overview_range: TimeRange | None = None
    filter_range: TimeRange | None = None

    @model_validator(mode='after')
    def ranges(self):
        if self.mode == 'range' and self.filter_range is None:
            raise ValueError('Przedział wymaga filter_range')
        if (self.overview_range and self.filter_range
                and (self.filter_range.start < self.overview_range.start
                     or self.filter_range.end > self.overview_range.end)):
            raise ValueError('Wybór musi mieścić się w osi czasu')
        return self


class Sort(StrictModel):
    field: Literal['label', 'type', 'updated_at', 'published_at', 'source_id'] = 'label'
    direction: Literal['asc', 'desc'] = 'asc'


class WorkspaceQuery(StrictModel):
    types: list[ObjectType] = Field(default_factory=lambda: ['communication', 'hydro_station', 'air_quality_station', 'area', 'aircraft', 'ship'], max_length=6)
    source_ids: list[Literal['imgw_meteo', 'rso', 'rcb', 'sg', 'imgw', 'gios', 'prg', 'aircraft', 'ships']] = Field(default_factory=list, max_length=9)
    q: str = Field(default='', max_length=200)
    province: str | None = None
    time: TimeContext = Field(default_factory=TimeContext)
    include_periods: bool = True
    include_unlocated: bool = True
    include_without_samples: bool = True
    watched_only: bool = False
    sort: Sort = Field(default_factory=Sort)
    page_size: int = Field(default=100, ge=1, le=200)
    cursor: str | None = Field(default=None, max_length=4096)
    query_revision: int = Field(default=0, ge=0)

    @field_validator('province')
    @classmethod
    def province_known(cls, value):
        if value is not None and (value not in units() or len(value) != 2):
            raise ValueError('Wybierz znany kod województwa PRG')
        return value

    @model_validator(mode='after')
    def station_window(self):
        if any(t in self.types for t in ('hydro_station', 'air_quality_station')):
            for value in (self.time.filter_range, self.time.overview_range):
                if value and (value.end-value.start).total_seconds() > 14*86400:
                    raise ValueError('Historia stacji obejmuje najwyżej 14 dni')
        return self


class ViewCamera(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    zoom: float = Field(ge=0, le=22)


class ViewLayout(StrictModel):
    tablePercent: float = Field(default=42, ge=20, le=80)
    mobilePanel: Literal['map', 'table'] = 'table'


class ViewConfig(StrictModel):
    query: WorkspaceQuery | None = None
    time: TimeContext | None = None
    sort: Sort | None = None
    columns: list[Literal['label', 'type', 'source_id', 'updated_at', 'published_at', 'measurement', 'location', 'status']] | None = Field(default=None, max_length=8)
    camera: ViewCamera | None = None
    layout: ViewLayout | None = None
    selectedRef: str | None = Field(default=None, max_length=200, pattern=r'^(communication:[0-9]+|hydro_station:imgw:[A-Za-z0-9_-]+|air_quality_station:gios:[0-9]+|area:prg:[0-9]{2,4}|aircraft:icao:[a-f0-9]{6}|ship:mmsi:[1-9][0-9]{8})$')
    comparedRefs: list[MovingRef] | None = Field(default=None, max_length=5)
    relative_seconds: int | None = Field(default=None, ge=60, le=1209600)

    @field_validator('comparedRefs')
    @classmethod
    def distinct_refs(cls, value):
        if value and len(set(value)) != len(value):
            raise ValueError('Obiekty porównania nie mogą się powtarzać')
        return value


class MovingReplay(TimeRange):
    refs: list[MovingRef] = Field(min_length=1, max_length=5)

    @model_validator(mode='after')
    def bounded(self):
        if len(set(self.refs)) != len(self.refs):
            raise ValueError('Obiekty porównania nie mogą się powtarzać')
        if (self.end-self.start).total_seconds() > 14*86400:
            raise ValueError('Porównanie obejmuje najwyżej 14 dni')
        return self


class SavedView(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    schema_version: Literal[1] = 1
    config: dict
    revision: int | None = Field(default=None, ge=1)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Podaj nazwę widoku')
        return value

    @field_validator('config')
    @classmethod
    def valid_config(cls, value):
        return ViewConfig.model_validate(value).model_dump(mode='json', by_alias=True, exclude_none=True, exclude_unset=True)
