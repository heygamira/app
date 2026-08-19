"""The SOS alert lifecycle.

Every transition is a function here, and each one writes an ``AlertEvent`` so
the history is complete without anybody remembering to log it. Three rules are
enforced rather than documented:

1. **Only a person can end an alert.** ``acknowledge`` and ``resolve`` reject
   an ``ai`` actor outright — there is no code path by which a model can decide
   an emergency is over. ``cancel`` has exactly one narrow exception,
   :func:`cancel_own_by_voice`, for the person the alert is *about* withdrawing
   their *own* alert out loud. It cannot reach anybody else's alert, it cannot
   reach a resolved one, the row survives, and the family is told. Everything
   about it is written down in ``docs/AI_SAFETY.md``.
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
from dataclasses import dataclass

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
from app.services.realtime import publish_family_event
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


@dataclass(frozen=True)
class _Wording:
    """Everything about an alert that a person reads, in one place.

    Kept as data rather than as branches inside the lifecycle functions, so the
    difference between an SOS and a wellbeing check is a table anybody can read
    at a glance — and so adding a third kind cannot quietly inherit the SOS
    copy, which is the mistake that would matter.
    """

    key: str
    severity: AlertSeverity
    timeline_type: TimelineEventType
    notification_type: NotificationType
    escalation_type: NotificationType
    high_priority: bool

    def timeline_title(self, name: str) -> str:
        if self.key == "sos":
            return f"{name} pressed SOS"
        return f"{name}'s watch flagged something and nobody answered"

    def notification_title(self, name: str) -> str:
        if self.key == "sos":
            return f"SOS from {name}"
        return f"Please check on {name}"

    def notification_body(self, name: str, source_label: str, note: str | None) -> str:
        if self.key == "sos":
            # A note on an SOS is the person's own words about their own
            # emergency, and replaces the generic sentence rather than being
            # appended to it.
            return note or (
                f"{name} pressed SOS on {source_label}. "
                "Call them now — Gamira has not contacted anyone else."
            )
        # A note here is the *device's* claim, so it is quoted and then
        # qualified — never allowed to stand alone as though Gamira agreed
        # with it. The disclaimer is not optional wording; it is the whole
        # difference between reporting a reading and endorsing one.
        opening = note or f"{name}'s watch flagged a reading."
        return (
            f"{opening} It might be worth a call. Gamira has not assessed the "
            "reading and has not contacted anyone else."
        )

    def escalation_title(self, name: str) -> str:
        if self.key == "sos":
            return f"Still no answer: {name}'s SOS"
        return f"Still no answer from {name}"

    def escalation_body(self, name: str) -> str:
        if self.key == "sos":
            return (
                f"Nobody has responded to {name}'s SOS. "
                "Call them now — Gamira has not contacted anyone else."
            )
        return (
            f"Nobody in the family has looked at {name}'s flagged reading yet. "
            "Gamira has not contacted anyone else."
        )


ALERT_WORDING: dict[AlertType, _Wording] = {
    AlertType.SOS: _Wording(
        key="sos",
        severity=AlertSeverity.CRITICAL,
        timeline_type=TimelineEventType.SOS_TRIGGERED,
        notification_type=NotificationType.SOS,
        escalation_type=NotificationType.SOS_ESCALATION,
        high_priority=True,
    ),
    AlertType.WELLBEING_CHECK: _Wording(
        key="wellbeing",
        severity=AlertSeverity.HIGH,
        timeline_type=TimelineEventType.WELLBEING_CHECK,
        notification_type=NotificationType.WELLBEING_CHECK,
        escalation_type=NotificationType.WELLBEING_CHECK,
        # Not high priority: a watch leaving its band is worth a look, not a
        # siren. Treating it as one would teach a family to mute both.
        high_priority=False,
    ),
}


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
    type: AlertType = AlertType.SOS,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> tuple[Alert, list[uuid.UUID]]:
    """Persist the press, put it on the timeline, and tell the family.

    Returns the alert and the users who were notified. The alert is durable
    before any notification is attempted, so a delivery failure never loses the
    fact that somebody asked for help.

    ``type`` decides the severity and every word the family reads. A wellbeing
    check is *not* a quieter SOS with the same copy: it says a device flagged a
    number and nobody answered, which is what actually happened, and the
    dashboard gives it a different colour for the same reason.
    """
    settings = settings or get_settings()
    now = now or utcnow()
    wording = ALERT_WORDING[type]

    alert = Alert(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        type=type,
        severity=wording.severity,
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
        type=wording.timeline_type,
        title=wording.timeline_title(senior.preferred_name),
        description=note or f"Raised from {source_label}.",
        related_entity_type="alert",
        related_entity_id=alert.id,
        actor_user_id=raised_by_user_id,
        occurred_at=now,
        dedupe_key=f"{wording.key}:{alert.id}",
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
        dedupe_prefix=f"{wording.key}:{alert.id}",
        template=NotificationRequest(
            user_id=uuid.uuid4(),  # replaced per recipient
            type=wording.notification_type,
            title=wording.notification_title(senior.preferred_name),
            body=wording.notification_body(senior.preferred_name, source_label, note),
            senior_profile_id=senior.id,
            related_entity_type="alert",
            related_entity_id=alert.id,
            high_priority=wording.high_priority,
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
            "alert_type": type.value,
            "senior_profile_id": str(senior.id),
            "source": source.value,
            "recipients": len(notified),
        },
    )
    await publish_family_event(
        session,
        senior.family_id,
        "alert_raised",
        entity_type="alert",
        entity_id=alert.id,
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


async def cancel_own_by_voice(
    session: AsyncSession,
    *,
    alert: Alert,
    senior: SeniorProfile,
    actor_user_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> tuple[Alert, list[uuid.UUID]]:
    """The person the alert is about withdraws it, out loud.

    This is the one place ``ActorType.AI`` is accepted on a cancellation, and
    every restriction on it is here rather than in a caller:

    * only an alert that is **still open** — a resolved one is somebody else's
      conclusion and is not the speaker's to undo;
    * only an alert **about this person**, so a voice can withdraw its own
      emergency and no other;
    * the row is **kept**, with the reason on it and an ``AlertEvent`` recording
      that the assistant carried it out;
    * the family is **told**, because a red alert that silently disappears is
      worse than one that never fired — they would be left wondering whether
      they had imagined it, or whether it was cancelled by whatever is wrong.

    What it does *not* do is decide anything. Somebody said they were alright
    and this writes that down. It cannot acknowledge, it cannot resolve, and it
    cannot touch an alert raised for anybody else.
    """
    now = now or utcnow()

    if alert.senior_profile_id != senior.id:
        raise PermissionDenied(
            "This alert is not about you.", code="alert_not_yours"
        )
    if alert.status is AlertStatus.RESOLVED:
        raise Conflict(
            "Somebody has already closed this alert.", code="alert_already_resolved"
        )
    if alert.status is AlertStatus.CANCELLED:
        return alert, []

    alert.status = AlertStatus.CANCELLED
    alert.cancelled_by_user_id = actor_user_id
    alert.cancelled_at = now
    alert.cancel_reason = "They said out loud that they are alright."
    alert.next_escalation_at = None
    await record_alert_event(
        session,
        alert=alert,
        type=AlertEventType.CANCELLED,
        # The person decided; the assistant carried it out. Both are true, and
        # the trail says both rather than choosing the flattering one.
        actor_type=ActorType.AI,
        actor_user_id=actor_user_id,
        detail={"reason": alert.cancel_reason, "via": "live_voice"},
        occurred_at=now,
    )

    wording = ALERT_WORDING[alert.type]
    notified = await notify_family(
        session,
        family_id=alert.family_id,
        exclude_user_ids=[actor_user_id],
        dedupe_prefix=f"{wording.key}-cancelled:{alert.id}",
        template=NotificationRequest(
            user_id=uuid.uuid4(),
            type=NotificationType.FAMILY_UPDATE,
            title=f"{senior.preferred_name} cancelled their alert",
            body=(
                f"{senior.preferred_name} told Gamira they are alright, and the "
                "alert has been cancelled. It is still in their timeline."
            ),
            senior_profile_id=senior.id,
            related_entity_type="alert",
            related_entity_id=alert.id,
        ),
    )
    await session.flush()
    logger.warning(
        "sos_cancelled_by_voice",
        extra={
            "alert_id": str(alert.id),
            "alert_type": alert.type.value,
            "recipients": len(notified),
        },
    )
    return alert, notified


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
    wording = ALERT_WORDING[alert.type]
    notified = await notify_family(
        session,
        family_id=alert.family_id,
        exclude_user_ids=[alert.raised_by_user_id] if alert.raised_by_user_id else [],
        dedupe_prefix=f"{wording.key}-escalation:{alert.id}:{attempt}",
        template=NotificationRequest(
            user_id=uuid.uuid4(),
            type=wording.escalation_type,
            title=wording.escalation_title(senior.preferred_name),
            body=wording.escalation_body(senior.preferred_name),
            senior_profile_id=senior.id,
            related_entity_type="alert",
            related_entity_id=alert.id,
            high_priority=wording.high_priority,
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
    await publish_family_event(
        session,
        alert.family_id,
        "alert_escalated",
        entity_type="alert",
        entity_id=alert.id,
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
