"""Structured input and output schemas for every model call.

Nothing reaches a model as free text and comes back as free text. A call takes
a validated input model and must return a validated output model, so a reply
that omitted a field, invented a status or wrapped itself in prose is a
validation error rather than something a screen renders.

Versions are explicit. ``OUTPUT_SCHEMA_VERSION`` is stored beside every
generated summary, so a stored paragraph can always be read back against the
shape it was written for.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OUTPUT_SCHEMA_VERSION = "1"


class StrictModel(BaseModel):
    """Refuses unexpected fields.

    A model that adds a ``recommendation`` key we never asked for should fail
    loudly here rather than pass silently through to a family's screen.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Deterministic facts — the backend counts these, the model never touches them
# --------------------------------------------------------------------------- #


class DoseFacts(StrictModel):
    scheduled: int = 0
    taken: int = 0
    skipped: int = 0
    missed: int = 0
    late: int = 0
    # Doses still ahead of now in the period, which are not "missing responses".
    upcoming: int = 0

    @property
    def answered(self) -> int:
        return self.taken + self.skipped

    @property
    def unanswered(self) -> int:
        return self.missed + self.late


class ReminderFacts(StrictModel):
    active: int = 0
    completed: int = 0


class MetricFreshness(StrictModel):
    metric: str
    readings: int
    latest_at: dt.datetime | None = None
    hours_since_latest: float | None = None


class HealthFacts(StrictModel):
    total_readings: int = 0
    metrics: list[MetricFreshness] = Field(default_factory=list)
    # Never a value, never a range, never a judgement — only how much data
    # there is and how old it is.
    latest_reading_at: dt.datetime | None = None


class DeviceFacts(StrictModel):
    registered_devices: int = 0
    last_device_reading_at: dt.datetime | None = None
    hours_since_device_sync: float | None = None


class AppointmentFact(StrictModel):
    title: str
    starts_at: dt.datetime
    clinician: str | None = None


class FamilyActivityFacts(StrictModel):
    timeline_events: int = 0
    notes_added: int = 0
    sos_alerts: int = 0
    sos_alerts_acknowledged: int = 0


class CareFacts(StrictModel):
    """Everything the backend counted, and nothing it inferred."""

    senior_name: str
    period_start: dt.date
    period_end: dt.date
    timezone: str
    doses: DoseFacts = Field(default_factory=DoseFacts)
    reminders: ReminderFacts = Field(default_factory=ReminderFacts)
    health: HealthFacts = Field(default_factory=HealthFacts)
    devices: DeviceFacts = Field(default_factory=DeviceFacts)
    upcoming_appointments: list[AppointmentFact] = Field(default_factory=list)
    family_activity: FamilyActivityFacts = Field(default_factory=FamilyActivityFacts)
    # Set when the figures rest on thin or stale data. Shown wherever the
    # summary is shown, never paraphrased away by the model.
    data_freshness_warning: str | None = None


# --------------------------------------------------------------------------- #
# Model outputs
# --------------------------------------------------------------------------- #


class WeeklySummaryOut(StrictModel):
    """What the model is allowed to return for a weekly care summary.

    Note what is absent: no scores, no risk level, no recommendation, no
    assessment of any reading. The model is turning counted figures into
    sentences a family can read, and the schema is what stops it doing more.
    """

    schema_version: Literal["1"] = "1"
    headline: str = Field(min_length=1, max_length=140)
    body: str = Field(min_length=1, max_length=1200)
    # Short, factual lines, each one restating a figure from CareFacts.
    highlights: list[str] = Field(default_factory=list, max_length=6)


class ChatReplyOut(StrictModel):
    schema_version: Literal["1"] = "1"
    reply: str = Field(min_length=1, max_length=2000)
    # True when the assistant declined because the request was outside what it
    # may do. Recorded so refusals can be counted rather than guessed at.
    refused: bool = False
    refusal_code: str | None = Field(default=None, max_length=64)


__all__ = [
    "OUTPUT_SCHEMA_VERSION",
    "AppointmentFact",
    "CareFacts",
    "ChatReplyOut",
    "DeviceFacts",
    "DoseFacts",
    "FamilyActivityFacts",
    "HealthFacts",
    "MetricFreshness",
    "ReminderFacts",
    "StrictModel",
    "WeeklySummaryOut",
]
