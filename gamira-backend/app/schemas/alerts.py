"""Request and response models for the SOS alert lifecycle."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    ActorType,
    AlertEventType,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AlertType,
)
from app.schemas.common import ApiModel


class SosAlertCreate(BaseModel):
    source: Literal["parent_app", "watch", "family_app", "approved_device"] = "parent_app"
    note: str | None = Field(default=None, max_length=500)


class SosAlertOut(BaseModel):
    """The record of one SOS press.

    ``delivery`` is deliberately explicit and deliberately constant. Gamira
    raises the alert inside the app for every other member of the family and
    repeats it to the same people if nobody answers. It does not call anyone,
    send SMS, contact emergency services, or reach outside the family.
    """

    id: uuid.UUID
    senior_profile_id: uuid.UUID
    senior_name: str
    raised_at: dt.datetime
    raised_by_user_id: uuid.UUID | None = None
    source: str
    note: str | None = None
    status: AlertStatus
    notified_user_ids: list[uuid.UUID]
    delivery: Literal["in_app_only"] = "in_app_only"


class AlertOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    senior_profile_id: uuid.UUID
    type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    source: AlertSource
    raised_by_user_id: uuid.UUID | None = None
    raised_at: dt.datetime
    note: str | None = None
    acknowledged_by_user_id: uuid.UUID | None = None
    acknowledged_at: dt.datetime | None = None
    escalation_count: int
    last_escalated_at: dt.datetime | None = None
    next_escalation_at: dt.datetime | None = None
    resolved_by_user_id: uuid.UUID | None = None
    resolved_at: dt.datetime | None = None
    resolution: str | None = None
    cancelled_by_user_id: uuid.UUID | None = None
    cancelled_at: dt.datetime | None = None
    cancel_reason: str | None = None
    notified_user_count: int
    delivery: Literal["in_app_only"] = "in_app_only"


class AlertEventOut(ApiModel):
    id: uuid.UUID
    alert_id: uuid.UUID
    type: AlertEventType
    actor_type: ActorType
    actor_user_id: uuid.UUID | None = None
    detail: dict[str, Any] | None = None
    occurred_at: dt.datetime


class AlertAcknowledgeIn(BaseModel):
    note: str | None = Field(default=None, max_length=400)


class AlertResolveIn(BaseModel):
    resolution: str | None = Field(default=None, max_length=400)


class AlertCancelIn(BaseModel):
    # Required, and required to be non-empty: an alert withdrawn without a
    # stated reason leaves nothing for the family to read afterwards.
    reason: str = Field(min_length=1, max_length=400)


__all__ = [
    "AlertAcknowledgeIn",
    "AlertCancelIn",
    "AlertEventOut",
    "AlertOut",
    "AlertResolveIn",
    "SosAlertCreate",
    "SosAlertOut",
]
