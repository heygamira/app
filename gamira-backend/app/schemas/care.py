"""Request and response models for reminders, timeline, health and alerts."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    AppointmentStatus,
    HealthMetric,
    HealthSource,
    NoteCategory,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    ReminderStatus,
    ReminderType,
    TimelineEventType,
)
from app.schemas.common import ApiModel
from app.services.scheduling import load_timezone, parse_days_of_week

# Ranges are plausibility bounds for data entry, not clinical thresholds. Gamira
# rejects impossible values; it does not decide whether a value is healthy.
METRIC_UNITS: dict[HealthMetric, tuple[str, float, float]] = {
    HealthMetric.HEART_RATE: ("bpm", 20, 250),
    HealthMetric.BLOOD_PRESSURE_SYSTOLIC: ("mmHg", 50, 260),
    HealthMetric.BLOOD_PRESSURE_DIASTOLIC: ("mmHg", 30, 180),
    HealthMetric.OXYGEN_SATURATION: ("%", 50, 100),
    HealthMetric.BLOOD_GLUCOSE: ("mg/dL", 20, 600),
    HealthMetric.BODY_TEMPERATURE: ("C", 30, 45),
    HealthMetric.WEIGHT: ("kg", 20, 300),
    HealthMetric.STEPS: ("steps", 0, 100000),
    HealthMetric.SLEEP_DURATION: ("hours", 0, 24),
}


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: ReminderType = ReminderType.OTHER
    instructions: str | None = None
    local_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days_of_week: str = ""
    timezone: str | None = None
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return value if value is None else str(load_timezone(value).key)

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, value: str) -> str:
        parse_days_of_week(value)
        return value


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    type: ReminderType | None = None
    instructions: str | None = None
    local_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days_of_week: str | None = None
    status: ReminderStatus | None = None
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None


class ReminderOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    senior_profile_id: uuid.UUID
    type: ReminderType
    title: str
    instructions: str | None = None
    local_time: str | None = None
    days_of_week: str
    timezone: str
    status: ReminderStatus
    last_completed_at: dt.datetime | None = None
    created_at: dt.datetime


class TimelineEventOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    senior_profile_id: uuid.UUID
    type: TimelineEventType
    title: str
    description: str | None = None
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    occurred_at: dt.datetime


class HealthReadingCreate(BaseModel):
    metric: HealthMetric
    value: float
    unit: str
    source: HealthSource = HealthSource.MANUAL_FAMILY
    source_device: str | None = Field(default=None, max_length=120)
    measured_at: dt.datetime
    note: str | None = None


class HealthReadingOut(ApiModel):
    id: uuid.UUID
    senior_profile_id: uuid.UUID
    metric: HealthMetric
    value: float
    unit: str
    source: HealthSource
    source_device: str | None = None
    measured_at: dt.datetime
    note: str | None = None


class NotificationOut(ApiModel):
    id: uuid.UUID
    type: NotificationType
    # Always ``in_app`` here: the inbox endpoint returns in-app records only,
    # and the field is present so no client has to assume that.
    channel: NotificationChannel
    title: str
    body: str | None = None
    status: NotificationStatus
    senior_profile_id: uuid.UUID | None = None
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    opened_at: dt.datetime | None = None
    created_at: dt.datetime


class DeviceFlagCreate(BaseModel):
    """A paired device reporting that one of its own limits was crossed."""

    metric: HealthMetric
    value: float
    unit: str = Field(max_length=24)
    # The device's words for why it flagged this. Gamira repeats them and
    # attributes them; it does not form its own opinion of the reading.
    reason: str = Field(min_length=1, max_length=300)
    source_device: str | None = Field(default=None, max_length=120)
    measured_at: dt.datetime
    reading_id: uuid.UUID | None = None


class DeviceFlagOut(BaseModel):
    """A flag that has been shown to the family.

    ``delivery`` says what actually happened, as with an SOS: the family sees
    it in the app. Nobody is called, and this is not an emergency alert.
    """

    id: uuid.UUID
    senior_profile_id: uuid.UUID
    senior_name: str
    metric: HealthMetric
    value: float
    unit: str
    reason: str
    raised_at: dt.datetime
    notified_user_ids: list[uuid.UUID]
    delivery: Literal["in_app_only"] = "in_app_only"


class EmergencyContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=3, max_length=32)
    relationship_label: str | None = Field(default=None, max_length=64)
    priority: int = Field(default=1, ge=1, le=20)
    is_primary: bool = False
    consent_confirmed: bool = False


class EmergencyContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    relationship_label: str | None = Field(default=None, max_length=64)
    priority: int | None = Field(default=None, ge=1, le=20)
    is_primary: bool | None = None
    consent_confirmed: bool | None = None


class EmergencyContactOut(ApiModel):
    id: uuid.UUID
    senior_profile_id: uuid.UUID
    name: str
    phone: str
    relationship_label: str | None = None
    priority: int
    is_primary: bool
    consent_confirmed: bool


class AppointmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    clinician: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    starts_at: dt.datetime
    timezone: str | None = None


class AppointmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    clinician: str | None = None
    location: str | None = None
    notes: str | None = None
    starts_at: dt.datetime | None = None
    status: AppointmentStatus | None = None


class AppointmentOut(ApiModel):
    id: uuid.UUID
    senior_profile_id: uuid.UUID
    title: str
    clinician: str | None = None
    location: str | None = None
    notes: str | None = None
    starts_at: dt.datetime
    timezone: str
    status: AppointmentStatus


class FamilyNoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    category: NoteCategory = NoteCategory.NOTE
    senior_profile_id: uuid.UUID | None = None


class FamilyNoteOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    senior_profile_id: uuid.UUID | None = None
    category: NoteCategory
    title: str
    content: str
    author_user_id: uuid.UUID | None = None
    created_at: dt.datetime
