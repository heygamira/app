"""Request and response models for the medication care loop."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    DoseSource,
    DoseStatus,
    MedicationStatus,
    ScheduleStatus,
)
from app.schemas.common import ApiModel
from app.services.scheduling import load_timezone, parse_days_of_week, parse_local_time


class ScheduleBase(BaseModel):
    local_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str | None = None
    days_of_week: str = ""
    dose_quantity: str | None = Field(default=None, max_length=64)
    dose_instructions: str | None = None
    late_after_minutes: int = Field(default=30, ge=1, le=1440)
    missed_after_minutes: int = Field(default=120, ge=2, le=2880)
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

    @field_validator("local_time")
    @classmethod
    def _time(cls, value: str) -> str:
        parse_local_time(value)
        return value


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    local_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str | None = None
    days_of_week: str | None = None
    dose_quantity: str | None = None
    dose_instructions: str | None = None
    late_after_minutes: int | None = Field(default=None, ge=1, le=1440)
    missed_after_minutes: int | None = Field(default=None, ge=2, le=2880)
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None
    status: ScheduleStatus | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return value if value is None else str(load_timezone(value).key)


class ScheduleOut(ApiModel):
    id: uuid.UUID
    medication_id: uuid.UUID
    local_time: str
    timezone: str
    days_of_week: str
    dose_quantity: str | None = None
    dose_instructions: str | None = None
    late_after_minutes: int
    missed_after_minutes: int
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None
    status: ScheduleStatus


class MedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    form: str | None = Field(default=None, max_length=64)
    strength: str | None = Field(default=None, max_length=64)
    instructions: str | None = None
    prescriber: str | None = Field(default=None, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    # Schedules can be supplied inline so one call from a form creates the whole
    # medication, matching how both apps collect the information.
    schedules: list[ScheduleCreate] = []


class MedicationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    form: str | None = Field(default=None, max_length=64)
    strength: str | None = Field(default=None, max_length=64)
    instructions: str | None = None
    prescriber: str | None = Field(default=None, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    status: MedicationStatus | None = None


class MedicationOut(ApiModel):
    id: uuid.UUID
    family_id: uuid.UUID
    senior_profile_id: uuid.UUID
    name: str
    form: str | None = None
    strength: str | None = None
    instructions: str | None = None
    prescriber: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    status: MedicationStatus
    schedules: list[ScheduleOut] = Field(default_factory=list)
    created_at: dt.datetime


class DoseEventOut(ApiModel):
    id: uuid.UUID
    medication_id: uuid.UUID
    medication_schedule_id: uuid.UUID
    senior_profile_id: uuid.UUID
    scheduled_at_utc: dt.datetime
    scheduled_local_time: str
    scheduled_timezone: str
    status: DoseStatus
    recorded_at: dt.datetime | None = None
    recorded_by_user_id: uuid.UUID | None = None
    source: DoseSource | None = None
    note: str | None = None
    medication_name: str | None = None
    dose_quantity: str | None = None


class DoseOutcomeIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    source: DoseSource = DoseSource.FAMILY_APP
