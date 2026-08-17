"""SOS alerts and their append-only history.

Before this existed an SOS was a timeline row and some notifications: there was
no record that *somebody* had responded, and nothing to escalate. An alert is
now a thing with a life — raised, delivered to whoever it reached,
acknowledged by a named person at a named time, escalated when nobody came,
resolved by a human.

Two rules are enforced in the service layer and stated here because they are
the reason this table exists:

* **The AI cannot end an alert.** Acknowledgement, resolution and cancellation
  all require a human actor. ``ActorType.AI`` is rejected on those transitions.
* **Nothing here contacts emergency services.** Gamira reaches the family
  inside the app and, on the phone, offers to dial a saved contact. The
  ``delivery`` wording on every response says so.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, Timestamps, UUIDPrimaryKey, utcnow
from app.db.types import UtcDateTime
from app.models.enums import (
    ActorType,
    AlertEventType,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AlertType,
)


class Alert(UUIDPrimaryKey, Timestamps, Base):
    """One emergency, from the press to whatever ended it."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_senior_status", "senior_profile_id", "status"),
        Index("ix_alerts_open", "status", "raised_at"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, native_enum=False, length=16), default=AlertType.SOS
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity, native_enum=False, length=16), default=AlertSeverity.CRITICAL
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, native_enum=False, length=16), default=AlertStatus.RAISED
    )
    source: Mapped[AlertSource] = mapped_column(
        Enum(AlertSource, native_enum=False, length=24), default=AlertSource.PARENT_APP
    )
    source_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registered_devices.id", ondelete="SET NULL")
    )

    raised_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    raised_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text())

    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id")
    )
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    escalation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_escalated_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    # When the escalation job should next look at this alert. Cleared on
    # acknowledgement so a responded-to alert stops nagging the family.
    next_escalation_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime(), index=True
    )

    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    resolution: Mapped[str | None] = mapped_column(String(400))

    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    cancel_reason: Mapped[str | None] = mapped_column(String(400))

    notified_user_count: Mapped[int] = mapped_column(Integer, default=0)
    timeline_event_id: Mapped[uuid.UUID | None] = mapped_column()

    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="alert",
        order_by="AlertEvent.occurred_at",
        cascade="all, delete-orphan",
    )

    @property
    def is_open(self) -> bool:
        return self.status in (
            AlertStatus.RAISED,
            AlertStatus.ESCALATED,
            AlertStatus.ACKNOWLEDGED,
        )

    @property
    def is_answered(self) -> bool:
        """Has a person taken responsibility for this alert?"""
        return self.acknowledged_at is not None or self.status in (
            AlertStatus.RESOLVED,
            AlertStatus.CANCELLED,
        )


class AlertEvent(UUIDPrimaryKey, Base):
    """One line of an alert's history. Written once, never updated or deleted.

    ``detail`` holds safe structured metadata — a count of who was notified, an
    escalation number, a delivery channel. Never a token, never a phone number,
    never a health value.
    """

    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_occurred", "alert_id", "occurred_at"),)

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[AlertEventType] = mapped_column(
        Enum(AlertEventType, native_enum=False, length=24)
    )
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, native_enum=False, length=16), default=ActorType.SYSTEM
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    detail: Mapped[dict | None] = mapped_column(JSON())
    occurred_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)

    alert: Mapped[Alert] = relationship(back_populates="events")


__all__ = ["Alert", "AlertEvent"]
