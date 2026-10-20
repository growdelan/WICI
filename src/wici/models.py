"""Validate publisher documents and source metadata consumed by the map."""
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')


class SourceArea(BaseModel):
    model_config=ConfigDict(extra='ignore')
    name: str
    role: Literal['warning_area','notification_area','event_location']
    precision: Literal['administrative','unknown','approximate','exact']='unknown'
    admin_code: str | None=None
    geometry_ref: str | None=None
    source: str='source document'


class SourceMetadata(BaseModel):
    # Old stored fields remain readable; only metadata used by the map is validated.
    model_config=ConfigDict(extra='ignore')
    locations: list[SourceArea]=Field(default_factory=list)
    valid_from: datetime | None=None
    valid_until: datetime | None=None
    warning_status: Literal['unknown','active','upcoming','expired','cancelled']='unknown'
    official_severity: str | None=None

    @field_validator('valid_from','valid_until')
    @classmethod
    def aware(cls,value):
        if value is not None and (value.tzinfo is None or value.year==9999):
            raise ValueError('Known source windows require a timezone and real dates')
        return value

    @model_validator(mode='after')
    def ordered(self):
        if self.valid_from and self.valid_until and self.valid_until<=self.valid_from:
            raise ValueError('Source window must be a positive interval')
        return self


class Document(Model):
    source_id: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    url: str
    title: str = Field(min_length=1,max_length=1000)
    text: str = Field(default='',max_length=20000)
    source_document_id: str | None = None
    source_published_at: datetime | None = None
    source_updated_at: datetime | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    parser_version: str = '1'
    redaction_note: str | None = None

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
            raise ValueError('Only publisher HTTP(S) URLs allowed')
        return value

    @field_validator('source_published_at', 'source_updated_at')
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('Known source instants require a timezone')
        return value.astimezone(UTC) if value is not None else None

    @field_validator('fields')
    @classmethod
    def source_metadata(cls,value):
        if 'event' in value:
            SourceMetadata.model_validate(value['event'])
        return value
