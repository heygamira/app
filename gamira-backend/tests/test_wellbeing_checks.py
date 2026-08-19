"""A watch flagged a reading, so somebody asked — and somebody noticed the silence.

The behaviour under test is a chain with a deliberate seam in it: the *device*
decides a number left its band, *Gamira* asks whether they are alright, and a
*rule* decides what follows. These tests are mostly about the seam. The model
must be able to report an answer and must not be able to raise anything, and
the escalation must happen with the model absent entirely.

The other thing being pinned down here is that this is not an SOS. Nobody
pressed anything. A watch on a bedside table leaves its band all night, and if
that wore the red treatment the red treatment would stop meaning anything.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.alerts import Alert
from app.models.audit import AuditLog
from app.models.care import NotificationDelivery, WellbeingCheck
from app.models.enums import (
    ActorType,
    AlertSeverity,
    AlertStatus,
    AlertType,
    NotificationType,
    WellbeingCheckStatus,
)
from tests.conftest import auth
from tests.factories import (
    call,
    call_tools,
    create_family,
    join,
    link_senior_account,
    start_live_session,
)


async def _flag(client, family, *, subject: str, value: float = 142.0):
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/device-flags",
        json={
            "metric": "heart_rate",
            "value": value,
            "unit": "bpm",
            "reason": "Above the range set on this watch.",
            "source_device": "Gamira Watch (sim)",
            "measured_at": utcnow().isoformat(),
        },
        headers=auth(subject),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _wearer(client, session, *, subject: str = "the-senior"):
    family = await create_family(client)
    await join(client, family, subject=subject, role="viewer")
    await join(client, family, subject="daughter", role="family")
    await link_senior_account(session, family.senior_id, subject)
    return family, subject


async def _only_check(session) -> WellbeingCheck:
    rows = (await session.execute(select(WellbeingCheck))).scalars().all()
    assert len(rows) == 1, f"expected one check, found {len(rows)}"
    return rows[0]


# --------------------------------------------------------------------------- #
# Opening the question
# --------------------------------------------------------------------------- #


async def test_a_flag_leaves_a_question_owed(client, session):
    family, subject = await _wearer(client, session)

    await _flag(client, family, subject=subject)

    check = await _only_check(session)
    assert check.status is WellbeingCheckStatus.PENDING
    assert check.metric == "heart_rate"
    # The device's own sentence, carried through rather than rewritten.
    assert "Above the range set on this watch." in check.reason
    assert check.asked_at is None
    assert check.escalate_at is not None


async def test_the_same_flag_repeated_asks_once(client, session):
    """A watch that keeps reporting one racing heart is reporting one thing."""
    family, subject = await _wearer(client, session)

    await _flag(client, family, subject=subject)
    await _flag(client, family, subject=subject, value=145.0)
    await _flag(client, family, subject=subject, value=139.0)

    await _only_check(session)


async def test_the_flag_still_reaches_the_family_as_a_notice_not_an_alert(
    client, session
):
    """The old behaviour is unchanged: a banner, not an emergency."""
    family, subject = await _wearer(client, session)

    await _flag(client, family, subject=subject)

    notices = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.type == NotificationType.FAMILY_UPDATE
            )
        )
    ).scalars().all()
    assert notices
    assert "Gamira has not assessed this reading." in notices[0].body
    assert (await session.execute(select(Alert))).scalars().first() is None


# --------------------------------------------------------------------------- #
# Answering it
# --------------------------------------------------------------------------- #


async def test_saying_you_are_alright_closes_it(client, session, run_worker):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("answer_wellbeing_check", "fc-1", they_are="alright")],
    )
    # No dialog: being asked to confirm that you said you were fine is absurd.
    assert body["results"][0]["requires_confirmation"] is False
    assert body["results"][0]["ok"] is True

    check = await _only_check(session)
    assert check.status is WellbeingCheckStatus.ALRIGHT
    assert check.answered_at is not None

    # And the rule, run afterwards, finds nothing to do.
    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)
    assert (await session.execute(select(Alert))).scalars().first() is None


async def test_the_answer_is_recorded_as_the_assistants_doing(client, session):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    live = await start_live_session(client, subject=subject)

    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("answer_wellbeing_check", "fc-1", they_are="alright")],
    )

    rows = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "ai.wellbeing_check.answered")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor_type == ActorType.AI.value


async def test_saying_you_are_not_alright_escalates_at_once(
    client, session, run_worker
):
    """Answered badly is not the same as unanswered, and does not wait."""
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    live = await start_live_session(client, subject=subject)

    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("answer_wellbeing_check", "fc-1", they_are="not_alright")],
    )
    check = await _only_check(session)
    assert check.status is WellbeingCheckStatus.NOT_ALRIGHT

    await run_worker()

    alert = (await session.execute(select(Alert))).scalars().one()
    assert alert.type is AlertType.WELLBEING_CHECK
    assert "they were not alright" in (alert.note or "")


async def test_a_tap_answers_it_too(client, session):
    """Voice is the point, but a broken microphone must not raise an alert."""
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    check = await _only_check(session)

    response = await client.post(
        f"/api/v1/wellbeing-checks/{check.id}/answer",
        json={"alright": True},
        headers=auth(subject),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "alright"


# --------------------------------------------------------------------------- #
# Nobody answering
# --------------------------------------------------------------------------- #


async def _age_out(session, check: WellbeingCheck) -> None:
    check.escalate_at = utcnow() - dt.timedelta(minutes=1)
    await session.flush()
    await session.commit()


async def test_nobody_answering_raises_a_softer_alert_not_an_sos(
    client, session, run_worker
):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    await _age_out(session, await _only_check(session))

    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)

    alert = (await session.execute(select(Alert))).scalars().one()
    assert alert.type is AlertType.WELLBEING_CHECK
    assert alert.type is not AlertType.SOS
    assert alert.severity is AlertSeverity.HIGH
    assert alert.severity is not AlertSeverity.CRITICAL
    # Nobody raised this, so nobody's name is on it.
    assert alert.raised_by_user_id is None
    assert alert.status is AlertStatus.RAISED


async def test_unreachable_and_unanswered_are_told_apart(client, session, run_worker):
    """Different facts, worded differently — a family reads them differently."""
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    check = await _only_check(session)
    await _age_out(session, check)

    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)

    await session.refresh(check)
    assert check.status is WellbeingCheckStatus.UNREACHABLE
    alert = (await session.execute(select(Alert))).scalars().one()
    assert "could not reach them" in (alert.note or "")


async def test_asked_but_silent_says_so(client, session, run_worker):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    check = await _only_check(session)
    check.asked_at = utcnow()
    await _age_out(session, check)

    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)

    await session.refresh(check)
    assert check.status is WellbeingCheckStatus.NO_ANSWER
    alert = (await session.execute(select(Alert))).scalars().one()
    assert "got no answer" in (alert.note or "")


async def test_the_alert_never_claims_anything_about_the_reading(
    client, session, run_worker
):
    """It reports the silence, which is a fact. Not the number, which is not."""
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    await _age_out(session, await _only_check(session))

    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)

    notices = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.type == NotificationType.WELLBEING_CHECK
            )
        )
    ).scalars().all()
    assert notices
    body = notices[0].body
    assert "has not assessed the reading" in body
    for word in ("dangerous", "high", "low", "abnormal", "urgent", "emergency"):
        assert word not in body.lower()


async def test_it_escalates_only_once(client, session, run_worker):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    await _age_out(session, await _only_check(session))

    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)
    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)

    assert len((await session.execute(select(Alert))).scalars().all()) == 1


async def test_the_grace_period_is_respected(client, session, run_worker):
    """A sweep that arrives early does nothing rather than cutting it short."""
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)

    await run_worker(JobType.WELLBEING_CHECK_ESCALATE)

    assert (await session.execute(select(Alert))).scalars().first() is None
    check = await _only_check(session)
    assert check.status is WellbeingCheckStatus.PENDING


# --------------------------------------------------------------------------- #
# What the model cannot do
# --------------------------------------------------------------------------- #


async def test_the_catalogue_has_no_way_to_raise_this(client):
    """The escalation is a rule. There is no tool for it, refusing or otherwise."""
    from app.ai.tools import CATALOGUE

    for name in CATALOGUE:
        assert "raise" not in name
        assert "escalate" not in name
    # The only wellbeing tool reports an answer, and takes no id to aim it with.
    spec = CATALOGUE["answer_wellbeing_check"]
    assert spec.kind == "mutation"
    assert set(spec.parameters["properties"]) == {"they_are"}
    assert spec.parameters["properties"]["they_are"]["enum"] == [
        "alright",
        "not_alright",
    ]


async def test_a_voice_cannot_answer_for_another_family(client, session):
    """The check is resolved from the session's own person, not from arguments."""
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)

    other = await create_family(client, owner="owner-b", name="Other")
    await join(client, other, subject="other-senior", role="viewer")
    await link_senior_account(session, other.senior_id, "other-senior")
    live = await start_live_session(client, subject="other-senior")

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject="other-senior",
        calls=[call("answer_wellbeing_check", "fc-1", they_are="alright")],
    )
    assert body["results"][0]["ok"] is False
    assert "nothing waiting" in body["results"][0]["response"]["message"]

    check = await _only_check(session)
    assert check.status is WellbeingCheckStatus.PENDING


async def test_a_stranger_cannot_read_the_checks(client, session):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)
    await create_family(client, owner="owner-b", name="Other")

    response = await client.get(
        f"/api/v1/seniors/{family.senior_id}/wellbeing-checks",
        headers=auth("owner-b"),
    )
    assert response.status_code == 404


async def test_the_person_can_read_the_questions_asked_about_them(client, session):
    family, subject = await _wearer(client, session)
    await _flag(client, family, subject=subject)

    response = await client.get(
        f"/api/v1/seniors/{family.senior_id}/wellbeing-checks",
        headers=auth(subject),
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["asked"] is False
    assert rows[0]["status"] == "pending"
    assert uuid.UUID(rows[0]["id"])
