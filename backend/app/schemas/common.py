"""Shared schema primitives."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response models hydrated from SQLAlchemy rows."""

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    """Generic acknowledgement payload."""

    detail: str
    ok: bool = True


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int = 50
    offset: int = 0


class TimestampedRead(ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class IdResponse(BaseModel):
    id: str
    detail: str = ""


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
