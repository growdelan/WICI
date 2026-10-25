"""Strict inbox handling inputs; source evidence is always read by the server."""
from typing import Literal

from pydantic import Field, field_validator

from wici.workspace_models import StrictModel


class EventHandling(StrictModel):
    revision: int = Field(ge=1)
    status: Literal['new', 'accepted', 'closed']


class EventComment(StrictModel):
    revision: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=5000)

    @field_validator('body')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Komentarz nie może być pusty')
        return value.strip()


class EventCapture(StrictModel):
    dossier_id: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=160)
