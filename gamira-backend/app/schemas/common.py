"""Shared response envelopes."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str = ""


class ErrorResponse(BaseModel):
    """The single error shape every endpoint returns on failure."""

    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class HealthStatus(BaseModel):
    status: str
    version: str
    environment: str
    database: str
