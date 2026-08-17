"""Reminders, timeline, health readings, notifications and family records."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, utcnow
from app.db.types import UtcDateTime
from app.models.enums import (
    AppointmentStatus,
    DeliveryAttemptStatus,
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


class Reminder(UUIDPrimaryKey, Timestamps, Base):
    """A non-medication recurring prompt (hydration, walk, appointment prep)."""

    __tablename__ = "reminders"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[ReminderType] = mapped_column(
        Enum(ReminderType, native_enum=False, length=16), default=ReminderType.OTHER
    )
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str | None] = mapped_column(Text())
    days_of_week: Mapped[str] = mapped_column(String(32), default="")
    local_time: Mapped[str | None] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(64))
    effective_from: Mapped[dt.date | None] = mapped_column(Date())
    effective_to: Mapped[dt.date | None] = mapped_column(Date())
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus, native_enum=False, length=16), default=ReminderStatus.ACTIVE
    )
    last_completed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class TimelineEvent(UUIDPrimaryKey, Timestamps, Base):
    """A derived, display-safe record of something that already happened.

    Deleting a timeline row must never destroy the underlying dose, alert or
    reading it describes.
    """

    __tablename__ = "timeline_events"
    __table_args__ = (
        Index("ix_timeline_events_senior_occurred", "senior_profile_id", "occurred_at"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )
    type: Mapped[TimelineEventType] = mapped_column(
        Enum(TimelineEventType, native_enum=False, length=32)
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text())
    related_entity_type: Mapped[str | None] = mapped_column(String(48))
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    # Set only by events that must exist exactly once however many times their
    # job runs — "this dose was missed" is written by a retryable worker, while
    # "this dose was taken" can legitimately be written twice if the person
    # corrects themselves. Both PostgreSQL and SQLite allow repeated NULLs in a
    # unique index, so the ordinary events simply leave it unset.
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True)


class HealthReading(UUIDPrimaryKey, Timestamps, Base):
    """One measurement with its unit and provenance.

    The unit is stored alongside the value because comparing readings across
    incompatible units or collection methods would produce misleading trends.
    """

    __tablename__ = "health_readings"
    __table_args__ = (
        Index("ix_health_readings_senior_metric", "senior_profile_id", "metric"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )
    metric: Mapped[HealthMetric] = mapped_column(
        Enum(HealthMetric, native_enum=False, length=32)
    )
    value: Mapped[float] = mapped_column(Float())
    unit: Mapped[str] = mapped_column(String(24))
    source: Mapped[HealthSource] = mapped_column(
        Enum(HealthSource, native_enum=False, length=24)
    )
    source_device: Mapped[str | None] = mapped_column(String(120))
    measured_at: Mapped[dt.datetime] = mapped_column(UtcDateTime())
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text())


class NotificationDelivery(UUIDPrimaryKey, Timestamps, Base):
    """One notification, for one person, on one channel.

    ``channel`` is the field that keeps this honest. An ``in_app`` row is a
    record the app will show when it next asks; calling that "delivered" would
    be a lie, because a phone in a pocket with the app closed has received
    nothing. A ``push`` row has real provider attempts behind it, recorded in
    ``notification_delivery_attempts``.

    ``dedupe_key`` is unique so a retried job cannot notify the same person
    twice about the same event.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_user_created", "user_id", "created_at"),
        Index(
            "ix_notification_deliveries_pending",
            "status",
            "channel",
            "next_attempt_at",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE")
    )
    senior_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=32)
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16),
        default=NotificationChannel.IN_APP,
        server_default="in_app",
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text())
    related_entity_type: Mapped[str | None] = mapped_column(String(48))
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column()
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False, length=16),
        default=NotificationStatus.QUEUED,
    )
    provider_reference: Mapped[str | None] = mapped_column(String(200))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    next_attempt_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    delivered_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    opened_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())


class NotificationDeliveryAttempt(UUIDPrimaryKey, Base):
    """One attempt to hand one notification to one device.

    Append-only. The provider's own message id is kept for support questions;
    the push token never is — only the fingerprint, which identifies the device
    row without being usable to send anything.
    """

    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        Index(
            "ix_notification_delivery_attempts_notification",
            "notification_delivery_id",
            "attempted_at",
        ),
    )

    notification_delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_deliveries.id", ondelete="CASCADE")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registered_devices.id", ondelete="SET NULL")
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=16)
    )
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[DeliveryAttemptStatus] = mapped_column(
        Enum(DeliveryAttemptStatus, native_enum=False, length=16)
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(64))
    device_token_fingerprint: Mapped[str | None] = mapped_column(String(32))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempted_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


class EmergencyContact(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "emergency_contacts"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32))
    relationship_label: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=1)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # A contact is only called after they have agreed to be one.
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())


class Appointment(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "appointments"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    clinician: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text())
    starts_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), index=True)
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=16),
        default=AppointmentStatus.SCHEDULED,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class FamilyNote(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "family_notes"

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )
    category: Mapped[NoteCategory] = mapped_column(
        Enum(NoteCategory, native_enum=False, length=24), default=NoteCategory.NOTE
    )
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text())
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


__all__ = [
    "Appointment",
    "EmergencyContact",
    "FamilyNote",
    "HealthReading",
    "NotificationDelivery",
    "NotificationDeliveryAttempt",
    "Reminder",
    "TimelineEvent",
]
