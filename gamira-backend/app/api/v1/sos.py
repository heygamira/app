"""Emergency alerts.

What this does: records the press as a durable alert with a life of its own —
raised, delivered, acknowledged by a named person, escalated when nobody
answers, resolved by a human — and raises it in the app for every other active
member of the family.

What it deliberately does not do: call anyone, send SMS, share location, or
contact emergency services. Escalation is *louder*, not *wider*: it tells the
same family again, because Gamira has no consented way to reach anybody else.
Every response says so in ``delivery``.

An assistant can open this screen. It cannot press the button, and it cannot
acknowledge, resolve or cancel what the button produced.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.api.rate_limit import rate_limit
from app.core.errors import NotFound, PermissionDenied
from app.jobs.queue import URGENT_PRIORITY, enqueue_job
from app.jobs.types import JobType
from app.models.alerts import Alert, AlertEvent
from app.models.enums import ActorType, AlertSource, AlertStatus
from app.models.identity import SeniorProfile
from app.schemas.alerts import (
    AlertAcknowledgeIn,
    AlertCancelIn,
    AlertEventOut,
    AlertOut,
    AlertResolveIn,
    SosAlertCreate,
    SosAlertOut,
)
from app.services import alerts as alert_service
from app.services.authz import (
    require_self_or_write_access,
    require_write_access,
    resolve_senior,
)
from app.services.timeline import record_audit

router = APIRouter(tags=["sos"])


@router.post(
    "/seniors/{senior_id}/sos",
    response_model=SosAlertOut,
    status_code=status.HTTP_201_CREATED,
)
async def raise_sos(
    senior_id: uuid.UUID,
    payload: SosAlertCreate,
    session: SessionDep,
    user: CurrentUser,
    _rate_limit: Annotated[
        None, rate_limit("sos_raise", limit=10, window_seconds=3600)
    ],
) -> SosAlertOut:
    """Raise an emergency alert for one person.

    The cared-for person may always raise their own — the Parent App and the
    watch are their own devices, and this is the one thing that must never be
    blocked by a read-only role. Anyone else needs write access, and a caller
    outside the family gets the same 404 as a caller naming a person who does
    not exist.

    Nothing in this path touches an AI provider or a network service. It writes
    rows, and it works when everything else is down.

    Rate-limited loosely (10/hour) purely to blunt an accidental retry storm
    or a compromised token — this must never meaningfully block a real
    emergency, so the limit is deliberately far above any plausible real use.
    """
    await require_self_or_write_access(
        session, user_id=user.id, senior_profile_id=senior_id
    )
    senior = await session.get(SeniorProfile, senior_id)
    if senior is None:  # pragma: no cover - the helper above already raised
        raise NotFound("The requested person does not exist.")

    alert, notified = await alert_service.raise_alert(
        session,
        senior=senior,
        raised_by_user_id=user.id,
        source=AlertSource(payload.source),
        note=payload.note,
    )

    # The escalation check is queued with the alert, in the same transaction.
    # If it fails to enqueue, the alert is not written either — better than an
    # alert nobody will ever be reminded about.
    await enqueue_job(
        session,
        JobType.ALERT_ESCALATION_CHECK,
        payload={"alert_id": str(alert.id)},
        dedupe_key=f"alert-escalation:{alert.id}",
        priority=URGENT_PRIORITY,
        run_after=alert.next_escalation_at,
        family_id=senior.family_id,
    )

    await record_audit(
        session,
        action="sos.raised",
        actor_user_id=user.id,
        target_type="alert",
        target_id=alert.id,
        family_id=senior.family_id,
        metadata={"source": payload.source, "notified": len(notified)},
    )
    return _sos_out(alert, senior, notified)


@router.get("/seniors/{senior_id}/alerts", response_model=list[AlertOut])
async def list_alerts(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    open_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AlertOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    statement = (
        select(Alert)
        .where(Alert.senior_profile_id == senior_id)
        .order_by(Alert.raised_at.desc())
        .limit(limit)
    )
    if open_only:
        statement = statement.where(
            Alert.status.in_(
                [AlertStatus.RAISED, AlertStatus.ESCALATED, AlertStatus.ACKNOWLEDGED]
            )
        )
    rows = await session.execute(statement)
    return [AlertOut.model_validate(row) for row in rows.scalars()]


@router.get("/alerts/{alert_id}", response_model=AlertOut)
async def get_alert(
    alert_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> AlertOut:
    alert = await _authorized_alert(session, user_id=user.id, alert_id=alert_id)
    return AlertOut.model_validate(alert)


@router.get("/alerts/{alert_id}/events", response_model=list[AlertEventOut])
async def list_alert_events(
    alert_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[AlertEventOut]:
    """The alert's full history. Append-only, so this is the whole story."""
    await _authorized_alert(session, user_id=user.id, alert_id=alert_id)
    rows = await session.execute(
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert_id)
        .order_by(AlertEvent.occurred_at)
    )
    return [AlertEventOut.model_validate(row) for row in rows.scalars()]


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertAcknowledgeIn,
    session: SessionDep,
    user: CurrentUser,
) -> AlertOut:
    """Say that you have seen this and are dealing with it.

    Any member of the family may acknowledge, including a viewer: answering an
    emergency is not an administrative privilege. The first acknowledgement
    wins and stops the escalation.
    """
    alert = await _authorized_alert(session, user_id=user.id, alert_id=alert_id)
    alert, changed = await alert_service.acknowledge(
        session, alert=alert, actor_user_id=user.id, note=payload.note
    )
    if changed:
        await record_audit(
            session,
            action="alert.acknowledge",
            actor_user_id=user.id,
            target_type="alert",
            target_id=alert.id,
            family_id=alert.family_id,
        )
    return AlertOut.model_validate(alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(
    alert_id: uuid.UUID,
    payload: AlertResolveIn,
    session: SessionDep,
    user: CurrentUser,
) -> AlertOut:
    """Close the alert, naming who closed it and when."""
    alert = await _authorized_alert(session, user_id=user.id, alert_id=alert_id)
    alert, changed = await alert_service.resolve(
        session, alert=alert, actor_user_id=user.id, resolution=payload.resolution
    )
    if changed:
        await record_audit(
            session,
            action="alert.resolve",
            actor_user_id=user.id,
            target_type="alert",
            target_id=alert.id,
            family_id=alert.family_id,
        )
    return AlertOut.model_validate(alert)


@router.post("/alerts/{alert_id}/cancel", response_model=AlertOut)
async def cancel_alert(
    alert_id: uuid.UUID,
    payload: AlertCancelIn,
    session: SessionDep,
    user: CurrentUser,
) -> AlertOut:
    """Withdraw an alert that should not have been raised.

    Deliberately the narrowest door in this module: a reason is required, and
    only the person who raised it or someone with write access in the family
    may use it. A pressed-by-accident SOS is real; a silently withdrawn one is
    not something the product should make easy.
    """
    alert = await _authorized_alert(session, user_id=user.id, alert_id=alert_id)
    if alert.raised_by_user_id != user.id:
        await require_write_access(session, user_id=user.id, family_id=alert.family_id)
    alert = await alert_service.cancel(
        session,
        alert=alert,
        actor_user_id=user.id,
        reason=payload.reason,
        actor_type=ActorType.USER,
    )
    await record_audit(
        session,
        action="alert.cancel",
        actor_user_id=user.id,
        target_type="alert",
        target_id=alert.id,
        family_id=alert.family_id,
        metadata={"reason": alert.cancel_reason},
    )
    return AlertOut.model_validate(alert)


async def _authorized_alert(
    session: SessionDep, *, user_id: uuid.UUID, alert_id: uuid.UUID
) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise NotFound("The requested alert does not exist.")
    try:
        await resolve_senior(
            session, user_id=user_id, senior_id=alert.senior_profile_id
        )
    except PermissionDenied:  # pragma: no cover - membership implies visibility
        raise NotFound("The requested alert does not exist.") from None
    return alert


def _sos_out(
    alert: Alert, senior: SeniorProfile, notified: list[uuid.UUID]
) -> SosAlertOut:
    return SosAlertOut(
        id=alert.id,
        senior_profile_id=senior.id,
        senior_name=senior.preferred_name,
        raised_at=alert.raised_at,
        raised_by_user_id=alert.raised_by_user_id,
        source=alert.source.value,
        note=alert.note,
        status=alert.status,
        notified_user_ids=notified,
    )
