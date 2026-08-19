"""A device flagged a number, so somebody asked — and somebody noticed the silence.

The chain is split on purpose, and the split is the safety property:

* the **watch** decides a reading left its band, in its own words;
* **Gamira** asks the person whether they are alright, and reports the answer;
* a **rule here** decides what happens when the answer is bad or never comes.

No model chooses to escalate, and none can: the catalogue gives it
``answer_wellbeing_check`` and nothing else. That matters because the failure
this exists to catch is *silence*, and a model asked to interpret silence will
interpret it — a rule about elapsed time will not.

Nothing in this module forms a clinical opinion. The device's ``reason`` is
carried verbatim and never rewritten, no threshold is defined here, and the
alert that can follow reports that nobody answered rather than that anything is
wrong. Those are different claims and only one of them is true.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.jobs.queue import URGENT_PRIORITY, enqueue_job
from app.jobs.types import JobType
from app.models.alerts import Alert
from app.models.care import WellbeingCheck
from app.models.enums import (
    ActorType,
    AlertSource,
    AlertType,
    WellbeingCheckStatus,
)
from app.models.identity import SeniorProfile
from app.services import alerts as alert_service
from app.services.timeline import record_audit

logger = get_logger(__name__)

# The device's own words, not ours, and truncated at the column width rather
# than summarised: a paraphrase of somebody else's claim is a new claim.
MAX_REASON = 300


async def open_check(
    session: AsyncSession,
    *,
    senior: SeniorProfile,
    reason: str,
    metric: str,
    value: float | None = None,
    unit: str | None = None,
    source_device: str | None = None,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> WellbeingCheck:
    """Record that a question is owed, and set the clock running on it.

    The escalation job is enqueued in the **caller's transaction**, so a flag
    and the promise to follow it up are either both durable or neither is.

    An open check for the same metric is reused rather than duplicated. A watch
    that keeps flagging the same racing heart rate is reporting one thing, and
    asking somebody the same question four times is how a companion becomes a
    nuisance.
    """
    settings = settings or get_settings()
    now = now or utcnow()

    existing = await session.scalar(
        select(WellbeingCheck).where(
            WellbeingCheck.senior_profile_id == senior.id,
            WellbeingCheck.metric == metric,
            WellbeingCheck.status == WellbeingCheckStatus.PENDING,
        )
    )
    if existing is not None:
        return existing

    check = WellbeingCheck(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        status=WellbeingCheckStatus.PENDING,
        reason=reason.strip()[:MAX_REASON],
        metric=metric,
        value=value,
        unit=unit,
        source_device=source_device,
        escalate_at=now + dt.timedelta(minutes=settings.wellbeing_check_grace_minutes),
    )
    session.add(check)
    await session.flush()

    await enqueue_job(
        session,
        JobType.WELLBEING_CHECK_ESCALATE,
        payload={"check_id": str(check.id)},
        dedupe_key=f"wellbeing:{check.id}",
        priority=URGENT_PRIORITY,
        run_after=check.escalate_at,
        family_id=senior.family_id,
    )
    logger.info(
        "wellbeing_check_opened",
        extra={
            "check_id": str(check.id),
            "metric": metric,
            "escalate_at": check.escalate_at.isoformat(),
        },
    )
    return check


async def pending_for_senior(
    session: AsyncSession, senior_profile_id: uuid.UUID, *, limit: int = 5
) -> list[WellbeingCheck]:
    rows = await session.execute(
        select(WellbeingCheck)
        .where(
            WellbeingCheck.senior_profile_id == senior_profile_id,
            WellbeingCheck.status == WellbeingCheckStatus.PENDING,
        )
        .order_by(WellbeingCheck.created_at)
        .limit(limit)
    )
    return list(rows.scalars())


async def mark_asked(
    session: AsyncSession,
    *,
    check: WellbeingCheck,
    conversation_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> WellbeingCheck:
    """Gamira has actually put the question. Only the first time counts."""
    if check.asked_at is None:
        check.asked_at = now or utcnow()
    if conversation_id is not None:
        check.conversation_id = conversation_id
    await session.flush()
    return check


async def record_answer(
    session: AsyncSession,
    *,
    check: WellbeingCheck,
    alright: bool,
    actor_user_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> WellbeingCheck:
    """Write down what they said. Nothing here decides what it means.

    ``alright`` closes the check and the escalation finds nothing to do.
    ``not_alright`` closes it too — the question has been answered — but leaves
    it in a state the rule escalates from, and the caller re-enqueues that rule
    to run now rather than in ten minutes' time.
    """
    now = now or utcnow()
    if check.status is not WellbeingCheckStatus.PENDING:
        return check

    check.status = (
        WellbeingCheckStatus.ALRIGHT if alright else WellbeingCheckStatus.NOT_ALRIGHT
    )
    check.answered_at = now
    if check.asked_at is None:
        check.asked_at = now
    if conversation_id is not None:
        check.conversation_id = conversation_id
    await record_audit(
        session,
        action="ai.wellbeing_check.answered",
        actor_user_id=actor_user_id,
        actor_type=ActorType.AI,
        target_type="wellbeing_check",
        target_id=check.id,
        family_id=check.family_id,
        metadata={"answer": check.status.value, "metric": check.metric},
    )
    await session.flush()
    logger.info(
        "wellbeing_check_answered",
        extra={"check_id": str(check.id), "answer": check.status.value},
    )
    return check


async def checks_due(
    session: AsyncSession, *, limit: int = 50, now: dt.datetime | None = None
) -> list[WellbeingCheck]:
    now = now or utcnow()
    rows = await session.execute(
        select(WellbeingCheck)
        .where(
            WellbeingCheck.status == WellbeingCheckStatus.PENDING,
            WellbeingCheck.escalate_at.is_not(None),
            WellbeingCheck.escalate_at <= now,
        )
        .order_by(WellbeingCheck.escalate_at)
        .limit(limit)
    )
    return list(rows.scalars())


def _note_for(check: WellbeingCheck) -> str:
    """What the family is told, in the order they need it.

    The device's claim first, because it is the only concrete thing anybody
    knows, then what happened when somebody tried to ask. "Nobody was there to
    ask" and "she asked and got nothing back" are different facts and a family
    reads them differently — the first is a phone that was put down, the second
    is a person who did not answer a direct question.
    """
    if check.status is WellbeingCheckStatus.NOT_ALRIGHT:
        tail = "Gamira asked, and they said they were not alright."
    elif check.asked_at is None:
        tail = "Gamira could not reach them to ask — their app was not open."
    else:
        tail = "Gamira asked how they were and got no answer."
    return f"{check.reason} {tail}"[:400]


async def escalate_check(
    session: AsyncSession,
    *,
    check: WellbeingCheck,
    senior: SeniorProfile,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> Alert | None:
    """Nobody answered, so tell the family — as its own kind of alert.

    Not an SOS. Nobody pressed anything, nobody said they were in trouble, and
    a watch on a bedside table leaves its band all night. Wearing the red
    treatment here would cost the red treatment its meaning, which is the one
    thing this product cannot afford to spend.
    """
    now = now or utcnow()
    if check.status not in (
        WellbeingCheckStatus.PENDING,
        WellbeingCheckStatus.NOT_ALRIGHT,
    ):
        return None
    if check.alert_id is not None:
        return None

    if check.status is WellbeingCheckStatus.PENDING:
        check.status = (
            WellbeingCheckStatus.NO_ANSWER
            if check.asked_at is not None
            else WellbeingCheckStatus.UNREACHABLE
        )

    alert, _notified = await alert_service.raise_alert(
        session,
        senior=senior,
        # Nobody raised this. Attributing it to the person would put their name
        # on something they did not do.
        raised_by_user_id=None,
        source=AlertSource.WATCH,
        note=_note_for(check),
        type=AlertType.WELLBEING_CHECK,
        settings=settings,
        now=now,
    )
    check.alert_id = alert.id
    check.escalate_at = None
    await session.flush()
    logger.warning(
        "wellbeing_check_escalated",
        extra={
            "check_id": str(check.id),
            "outcome": check.status.value,
            "alert_id": str(alert.id),
        },
    )
    return alert


__all__ = [
    "checks_due",
    "escalate_check",
    "mark_asked",
    "open_check",
    "pending_for_senior",
    "record_answer",
]
