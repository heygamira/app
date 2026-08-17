"""Medications, recurring schedules and the dose events they generate.

Gamira records what a clinician prescribed. It never derives, adjusts or
substitutes a drug or a dose.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import UtcDateTime
from app.models.enums import (
    DoseSource,
    DoseStatus,
    MedicationStatus,
    ScheduleStatus,
)


class Medication(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "medications"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    form: Mapped[str | None] = mapped_column(String(64))
    strength: Mapped[str | None] = mapped_column(String(64))
    instructions: Mapped[str | None] = mapped_column(Text())
    prescriber: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[dt.date | None] = mapped_column(Date())
    end_date: Mapped[dt.date | None] = mapped_column(Date())
    status: Mapped[MedicationStatus] = mapped_column(
        Enum(MedicationStatus, native_enum=False, length=16),
        default=MedicationStatus.ACTIVE,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    schedules: Mapped[list[MedicationSchedule]] = relationship(
        back_populates="medication", lazy="selectin", cascade="all, delete-orphan"
    )


class MedicationSchedule(UUIDPrimaryKey, Timestamps, Base):
    """A recurring dose time expressed in the senior's own timezone.

    The local time plus the IANA zone is authoritative; UTC occurrence times are
    computed from them so a daylight-saving shift moves the reminder with the
    wall clock rather than away from it.
    """

    __tablename__ = "medication_schedules"

    medication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medications.id", ondelete="CASCADE"), index=True
    )
    # Comma-separated ISO weekday numbers (1=Monday). Empty means every day.
    days_of_week: Mapped[str] = mapped_column(String(32), default="")
    local_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    timezone: Mapped[str] = mapped_column(String(64))
    dose_quantity: Mapped[str | None] = mapped_column(String(64))
    dose_instructions: Mapped[str | None] = mapped_column(Text())
    # Minutes after the scheduled time before a dose is late, then missed.
    late_after_minutes: Mapped[int] = mapped_column(Integer, default=30)
    missed_after_minutes: Mapped[int] = mapped_column(Integer, default=120)
    effective_from: Mapped[dt.date | None] = mapped_column(Date())
    effective_to: Mapped[dt.date | None] = mapped_column(Date())
    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus, native_enum=False, length=16), default=ScheduleStatus.ACTIVE
    )

    medication: Mapped[Medication] = relationship(back_populates="schedules")


class DoseEvent(UUIDPrimaryKey, Timestamps, Base):
    """One scheduled occurrence and its outcome.

    ``(medication_schedule_id, scheduled_at_utc)`` is unique so a retried
    generation job, a duplicated notification or a double tap in either app all
    resolve to the same row instead of inventing a second dose.
    """

    __tablename__ = "dose_events"
    __table_args__ = (
        UniqueConstraint(
            "medication_schedule_id",
            "scheduled_at_utc",
            name="uq_dose_events_schedule_occurrence",
        ),
    )

    medication_schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medication_schedules.id", ondelete="CASCADE"), index=True
    )
    medication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medications.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    scheduled_at_utc: Mapped[dt.datetime] = mapped_column(UtcDateTime(), index=True)
    # Snapshot of how the time was displayed when the event was created, kept so
    # history stays readable after a senior changes timezone.
    scheduled_local_time: Mapped[str] = mapped_column(String(5))
    scheduled_timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[DoseStatus] = mapped_column(
        Enum(DoseStatus, native_enum=False, length=16), default=DoseStatus.DUE
    )
    recorded_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[DoseSource | None] = mapped_column(
        Enum(DoseSource, native_enum=False, length=16)
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text())

    medication: Mapped[Medication] = relationship(lazy="joined")
    schedule: Mapped[MedicationSchedule] = relationship(lazy="joined")


__all__ = ["DoseEvent", "Medication", "MedicationSchedule"]
