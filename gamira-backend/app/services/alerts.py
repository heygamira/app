"""The SOS alert lifecycle.

Every transition is a function here, and each one writes an ``AlertEvent`` so
the history is complete without anybody remembering to log it. Three rules are
enforced rather than documented:

1. **Only a person can end an alert.** ``acknowledge``, ``resolve`` and
   ``cancel`` reject an ``ai`` actor outright. There is no code path by which a
   model can quiet an emergency.
2. **Raising never depends on anything optional.** No AI, no push provider, no
   network beyond the database. If Gemini is down and FCM is down, an SOS is
   still raised, still recorded, and still visible to the family in the app.
3. **Nothing here contacts emergency services.** Gamira reaches the family
   inside Gamira, and the phone offers to dial a saved contact. Every response
   says so in ``delivery``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.alerts import Alert, AlertEvent
from app.models.enums import (
    OPEN_ALERT_STATUSES,
    ActorType,
    AlertEventType,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AlertType,
    NotificationType,
    TimelineEventType,
)
from app.models.identity import SeniorProfile
from app.services.notifications import NotificationRequest, notify_family
from app.services.timeline import record_timeline_event

logger = get_logger(__name__)

SOURCE_LABELS: dict[AlertSource, str] = {
    AlertSource.PARENT_APP: "the Gamira app",
    AlertSource.WATCH: "their watch",
    AlertSource.FAMILY_APP: "the family dashboard",
    AlertSource.APPROVED_DEVICE: "a paired device",
}

# What every SOS response tells the caller, so no screen has to guess.
DELIVERY_STATEMENT = "in_app_only"


def _require_human(actor_type: ActorType, action: str) -> None:
    if actor_type is ActorType.AI:
        # Not a config option, not a role: the model has no path to this at all.
        raise PermissionDenied(
            f"An assistant cannot {action} an emergency alert.",
            code="ai_cannot_change_alert",
        )


async def record_alert_event(
    session: AsyncSession,
    *,
    alert: Alert,
    type: AlertEventType,
    actor_type: ActorType = ActorType.SYSTEM,
    actor_user_id: uuid.UUID | None = None,
    detail: dict | None = None,
    occurred_at: dt.datetime | None = None,
) -> AlertEvent:
    event = AlertEvent(
        alert_id=alert.id,
        type=type,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        detail=detail or {},
        occurred_at=occurred_at or utcnow(),
    )
    session.add(event)
    await session.flush()
    return event


async def raise_alert(
    session: AsyncSession,
    *,
    senior: SeniorProfile,
    raised_by_user_id: uuid.UUID | None,
    source: AlertSource = AlertSource.PARENT_APP,
    note: str | None = None,
    source_device_id: uuid.UUID | None = None,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> tuple[Alert, list[uuid.UUID]]:
    """Persist the press, put it on the timeline, and tell the family.

    Returns the alert and the users who were notified. The alert is durable
    before any notification is attempted, so a delivery failure never loses the
    fact that somebody asked for help.
    """
    settings = settings or get_settings()
    now = now or utcnow()

    alert = Alert(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        type=AlertType.SOS,
        severity=AlertSeverity.CRITICAL,
        status=AlertStatus.RAISED,
        source=source,
        source_device_id=source_device_id,
        raised_by_user_id=raised_by_user_id,
        raised_at=now,
        note=note,
        next_escalation_at=now
        + dt.timedelta(minutes=settings.sos_escalation_after_minutes),
    )
    session.add(alert)
    await session.flush()

    source_label = SOURCE_LABELS.get(source, str(source))
    timeline = await record_timeline_event(
        session,
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        type=TimelineEventType.SOS_TRIGGERED,
        title=f"{senior.preferred_name} pressed SOS",
        description=note or f"Raised from {source_label}.",
        related_entity_type="alert",
        related_entity_id=alert.id,
        actor_user_id=raised_by_user_id,
        occurred_at=now,
        dedupe_key=f"sos:{alert.id}",
    )
    alert.timeline_event_id = timeline.id

    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.RAISED,
        actor_type=ActorType.DEVICE if source is AlertSource.WATCH else ActorType.USER,
        actor_user_id=raised_by_user_id,
        detail={"source": source.value},
        occurred_at=now,
    )

    notified = await notify_family(
        session,
        family_id=senior.family_id,
        exclude_user_ids=[raised_by_user_id] if raised_by_user_id else [],
        dedupe_prefix=f"sos:{alert.id}",
        template=NotificationRequest(
            user_id=uuid.uuid4(),  # replaced per recipient
            type=NotificationType.SOS,
            title=f"SOS from {senior.preferred_name}",
            body=(
                note
                or f"{senior.preferred_name} pressed SOS on {source_label}. "
                "Call them now — Gamira has not contacted anyone else."
            ),
            senior_profile_id=senior.id,
            related_entity_type="alert",
            related_entity_id=alert.id,
            high_priority=True,
        ),
    )
    alert.notified_user_count = len(notified)
    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.DELIVERY_ATTEMPTED,
        detail={"channel": "in_app", "recipients": len(notified)},
        occurred_at=now,
    )
    await session.flush()

    logger.warning(
        "sos_raised",
        extra={
            "alert_id": str(alert.id),
            "senior_profile_id": str(senior.id),
            "source": source.value,
            "recipients": len(notified),
        },
    )
    return alert, notified


async def get_alert(session: AsyncSession, alert_id: uuid.UUID) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFound("The requested alert does not exist.")
    return alert


async def acknowledge(
    session: AsyncSession,
    *,
    alert: Alert,
    actor_user_id: uuid.UUID,
    actor_type: ActorType = ActorType.USER,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> tuple[Alert, bool]:
    """A named person takes responsibility. Idempotent: the first one counts."""
    _require_human(actor_type, "acknowledge")
    now = now or utcnow()

    if alert.status in (AlertStatus.RESOLVED, AlertStatus.CANCELLED):
        raise Conflict(
            "This alert has already been closed.", code="alert_already_closed"
        )
    if alert.acknowledged_at is not None:
        return alert, False

    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by_user_id = actor_user_id
    alert.acknowledged_at = now
    # Somebody is on it, so the family stops being told again.
    alert.next_escalation_at = None
    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.ACKNOWLEDGED,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        detail={"note": note} if note else None,
        occurred_at=now,
    )
    await session.flush()
    return alert, True


async def resolve(
    session: AsyncSession,
    *,
    alert: Alert,
    actor_user_id: uuid.UUID,
    resolution: str | None = None,
    actor_type: ActorType = ActorType.USER,
    now: dt.datetime | None = None,
) -> tuple[Alert, bool]:
    """Close the alert. Only a human, and only after it was raised."""
    _require_human(actor_type, "resolve")
    now = now or utcnow()

    if alert.status is AlertStatus.CANCELLED:
        raise Conflict("This alert was cancelled.", code="alert_cancelled")
    if alert.status is AlertStatus.RESOLVED:
        return alert, False

    # Resolving without acknowledging is normal — the person who answered the
    # phone is the person who resolves it — so record both.
    if alert.acknowledged_at is None:
        alert.acknowledged_by_user_id = actor_user_id
        alert.acknowledged_at = now
        await record_alert_event(
            session,
            alert=alert,
            type=AlertEventType.ACKNOWLEDGED,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            detail={"implied_by": "resolve"},
            occurred_at=now,
        )

    alert.status = AlertStatus.RESOLVED
    alert.resolved_by_user_id = actor_user_id
    alert.resolved_at = now
    alert.resolution = (resolution or "")[:400] or None
    alert.next_escalation_at = None
    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.RESOLVED,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        detail={"resolution": alert.resolution} if alert.resolution else None,
        occurred_at=now,
    )
    await session.flush()
    return alert, True


async def cancel(
    session: AsyncSession,
    *,
    alert: Alert,
    actor_user_id: uuid.UUID,
    reason: str,
    actor_type: ActorType = ActorType.USER,
    now: dt.datetime | None = None,
) -> Alert:
    """Withdraw an alert that should not have been raised.

    Deliberately awkward: it needs a reason, it needs a human, and only the
    person who raised it or someone with write access in the family may do it.
    A pressed-by-accident SOS is real; a *silently* withdrawn one is not
    something the product should make easy.
    """
    _require_human(actor_type, "cancel")
    now = now or utcnow()
    if not reason.strip():
        raise Conflict(
            "Cancelling an alert requires a reason.", code="cancel_reason_required"
        )
    if alert.status is AlertStatus.RESOLVED:
        raise Conflict(
            "A resolved alert cannot be cancelled.", code="alert_already_resolved"
        )
    if alert.status is AlertStatus.CANCELLED:
        return alert

    alert.status = AlertStatus.CANCELLED
    alert.cancelled_by_user_id = actor_user_id
    alert.cancelled_at = now
    alert.cancel_reason = reason.strip()[:400]
    alert.next_escalation_at = None
    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.CANCELLED,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        detail={"reason": alert.cancel_reason},
        occurred_at=now,
    )
    await session.flush()
    return alert


async def escalate(
    session: AsyncSession,
    *,
    alert: Alert,
    senior: SeniorProfile,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> int:
    """Tell the family again, because nobody has answered.

    Escalation is *louder*, not *wider*: it re-notifies the same family members
    rather than reaching outside the family, because Gamira has no consented
    way to contact anybody else.
    """
    settings = settings or get_settings()
    now = now or utcnow()

    alert.escalation_count += 1
    alert.last_escalated_at = now
    alert.status = AlertStatus.ESCALATED

    attempt = alert.escalation_count
    notified = await notify_family(
        session,
        family_id=alert.family_id,
        exclude_user_ids=[alert.raised_by_user_id] if alert.raised_by_user_id else [],
        dedupe_prefix=f"sos-escalation:{alert.id}:{attempt}",
        template=NotificationRequest(
            user_id=uuid.uuid4(),
            type=NotificationType.SOS_ESCALATION,
            title=f"Still no answer: {senior.preferred_name}'s SOS",
            body=(
                f"Nobody has responded to {senior.preferred_name}'s SOS. "
                "Call them now — Gamira has not contacted anyone else."
            ),
            senior_profile_id=senior.id,
            related_entity_type="alert",
            related_entity_id=alert.id,
            high_priority=True,
        ),
    )

    if attempt >= settings.sos_max_escalations:
        # Stop repeating rather than nag forever. The alert stays open and
        # visible; it just stops generating new notifications.
        alert.next_escalation_at = None
    else:
        alert.next_escalation_at = now + dt.timedelta(
            minutes=settings.sos_escalation_after_minutes
        )

    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.ESCALATED,
        detail={"attempt": attempt, "recipients": len(notified)},
        occurred_at=now,
    )
    await session.flush()
    logger.warning(
        "sos_escalated",
        extra={
            "alert_id": str(alert.id),
            "attempt": attempt,
            "recipients": len(notified),
        },
    )
    return len(notified)


async def alerts_due_for_escalation(
    session: AsyncSession, *, limit: int = 50, now: dt.datetime | None = None
) -> list[Alert]:
    now = now or utcnow()
    rows = await session.execute(
        select(Alert)
        .where(
            Alert.status.in_([AlertStatus.RAISED, AlertStatus.ESCALATED]),
            Alert.acknowledged_at.is_(None),
            Alert.next_escalation_at.is_not(None),
            Alert.next_escalation_at <= now,
        )
        .order_by(Alert.next_escalation_at)
        .limit(limit)
    )
    return list(rows.scalars())


async def open_alerts_for_senior(
    session: AsyncSession, senior_profile_id: uuid.UUID
) -> list[Alert]:
    rows = await session.execute(
        select(Alert)
        .where(
            Alert.senior_profile_id == senior_profile_id,
            Alert.status.in_(list(OPEN_ALERT_STATUSES)),
        )
        .order_by(Alert.raised_at.desc())
    )
    return list(rows.scalars())


__all__ = [
    "DELIVERY_STATEMENT",
    "acknowledge",
    "alerts_due_for_escalation",
    "cancel",
    "escalate",
    "get_alert",
    "open_alerts_for_senior",
    "raise_alert",
    "record_alert_event",
    "resolve",
]
