"""Strict selectors for local monitoring; no user scripts are evaluated."""
import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from wici.workspace_models import StrictModel


class RuleInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=5000)
    template: Literal['transport', 'measurement', 'communication', 'ukraine']
    mode: Literal['available', 'background'] = 'available'
    enabled: bool = False
    priority: Literal['low', 'normal', 'high'] = 'normal'
    config: dict
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def valid_selector(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('Podaj nazwę reguły')
        selectors = {
            'transport': TransportSelector,
            'measurement': MeasurementSelector,
            'communication': CommunicationSelector,
            'ukraine': UkraineSelector,
        }
        self.config = selectors[self.template].model_validate(self.config).model_dump(mode='json')
        return self


class TransportSelector(StrictModel):
    area_id: str = Field(min_length=1, max_length=100)
    object_ref: str | None = Field(default=None, pattern=r'^(aircraft:icao:[a-f0-9]{6}|ship:mmsi:[1-9][0-9]{8})$')
    object_type: Literal['aircraft', 'ship'] | None = None
    transition: Literal['enter', 'exit', 'both'] = 'both'

    @model_validator(mode='after')
    def target(self):
        if not self.object_ref and not self.object_type:
            raise ValueError('Wybierz obiekt albo typ transportu')
        if self.object_ref and self.object_type and not self.object_ref.startswith(self.object_type+':'):
            raise ValueError('Obiekt nie odpowiada wybranemu typowi')
        return self


class MeasurementSelector(StrictModel):
    object_ref: str = Field(pattern=r'^(air_quality_station:gios:[0-9]+|hydro_station:imgw:[A-Za-z0-9_-]+)$')
    sensor_id: str = Field(max_length=100)
    metric: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=50)
    threshold: float
    return_threshold: float | None = None

    @model_validator(mode='after')
    def finite_threshold(self):
        if not math.isfinite(self.threshold) or (self.return_threshold is not None and not math.isfinite(self.return_threshold)):
            raise ValueError('Próg musi być skończoną liczbą')
        if self.return_threshold is not None and self.return_threshold > self.threshold:
            raise ValueError('Próg powrotu nie może być wyższy od progu przekroczenia')
        if self.object_ref.startswith('air_quality_station:') and not self.sensor_id:
            raise ValueError('Wybierz konkretny czujnik GIOŚ')
        if self.metric == 'official_index':
            raise ValueError('Próg użytkownika dotyczy pomiaru, nie oficjalnego indeksu')
        return self


class CommunicationSelector(StrictModel):
    admin_code: str = Field(pattern=r'^[0-9]{2}([0-9]{2})?$')
    source_ids: list[Literal['imgw_meteo', 'rso', 'rcb', 'sg']] = Field(default_factory=list, max_length=4)


class UkraineSelector(StrictModel):
    region_ref: str = Field(pattern=r'^ua_region:neptun:(oblast|raion):[^\x00-\x1f]{1,256}$')


class RulePreview(StrictModel):
    rule: RuleInput
    start: datetime = Field(alias='from')
    end: datetime = Field(alias='to')

    @model_validator(mode='after')
    def bounded(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError('Czas wymaga strefy czasowej')
        self.start, self.end = self.start.astimezone(UTC), self.end.astimezone(UTC)
        if not 0 < (self.end-self.start).total_seconds() <= 90*86400:
            raise ValueError('Podgląd obejmuje dodatni przedział do 90 dni')
        return self
