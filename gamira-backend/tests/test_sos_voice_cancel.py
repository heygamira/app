"""Withdrawing your own emergency by saying so.

This is the one place ``ActorType.AI`` is accepted on a cancellation, and it
was opened deliberately: somebody who pressed SOS by accident, or whose
countdown ran out while they were fetching their glasses, had no way to take it
back from their own phone. Acknowledge and resolve stay shut.

So these tests are mostly about the walls around it. What it can reach, what it
cannot, what survives it, and who finds out.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, PermissionDenied
from app.models.alerts import Alert, AlertEvent
from app.models.care import NotificationDelivery
from app.models.enums import (
    ActorType,
    AlertEventType,
    AlertStatus,
    DecisionStatus,
    NotificationType,
)
from app.models.identity import SeniorProfile
from app.services import alerts as alert_service
from tests.conftest import auth
from tests.factories import (
    call,
    call_tools,
    create_family,
    join,
    link_senior_account,
    start_live_session,
)


async def _senior_with_open_sos(client, session, *, subject: str = "the-senior"):
    family = await create_family(client)
    await join(client, family, subject=subject, role="viewer")
    await join(client, family, subject="daughter", role="family")
    await link_senior_account(session, family.senior_id, subject)
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos",
        json={"source": "parent_app"},
        headers=auth(subject),
    )
    assert response.status_code == 201, response.text
    alert = await session.get(Alert, uuid.UUID(response.json()["id"]))
    return family, subject, alert


# --------------------------------------------------------------------------- #
# The narrow path itself
# --------------------------------------------------------------------------- #


async def test_saying_you_are_alright_cancels_your_own_alert(client, session):
    family, subject, alert = await _senior_with_open_sos(client, session)
    live = await start_live_session(client, subject=subject)

    opened = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("cancel_my_sos", "fc-1")],
    )
    # It is confirmed first: an alert their family has already seen is not
    # something to withdraw on a half-heard sentence.
    first = opened["results"][0]
    assert first["requires_confirmation"] is True
    assert "cancel the alert" in first["confirmation_prompt"]
    # And the wording says what they are agreeing to, both halves of it.
    assert "see that you cancelled it" in first["confirmation_prompt"]

    await session.refresh(alert)
    assert alert.status is AlertStatus.RAISED, "nothing happens before the yes"

    answered = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("confirm_pending_action", "fc-2", decision_id=first["decision_id"])],
    )
    assert answered["results"][0]["ok"] is True

    await session.refresh(alert)
    assert alert.status is AlertStatus.CANCELLED
    assert alert.cancelled_at is not None
    assert alert.next_escalation_at is None


async def test_the_alert_survives_being_cancelled(client, session):
    """It is withdrawn, not erased. A family that saw it can still find it."""
    family, subject, alert = await _senior_with_open_sos(client, session)

    await alert_service.cancel_own_by_voice(
        session,
        alert=alert,
        senior=await session.get(SeniorProfile, alert.senior_profile_id),
        actor_user_id=alert.raised_by_user_id,
    )

    await session.refresh(alert)
    assert alert.status is AlertStatus.CANCELLED
    assert alert.raised_at is not None
    assert alert.cancel_reason
    # The history says who carried it out, which is the point of having an AI
    # actor type at all.
    events = (
        await session.execute(
            select(AlertEvent).where(
                AlertEvent.alert_id == alert.id,
                AlertEvent.type == AlertEventType.CANCELLED,
            )
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].actor_type is ActorType.AI
    assert events[0].actor_user_id == alert.raised_by_user_id
    assert events[0].detail["via"] == "live_voice"


async def test_the_family_is_told_it_was_cancelled(client, session):
    """A red alert that silently vanishes is worse than one that never fired."""
    family, subject, alert = await _senior_with_open_sos(client, session)

    await alert_service.cancel_own_by_voice(
        session,
        alert=alert,
        senior=await session.get(SeniorProfile, alert.senior_profile_id),
        actor_user_id=alert.raised_by_user_id,
    )

    rows = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.related_entity_id == alert.id,
                NotificationDelivery.type == NotificationType.FAMILY_UPDATE,
            )
        )
    ).scalars().all()
    assert rows, "the family heard about the alert; they hear about this too"
    assert "alright" in rows[0].body
    # Not the person themselves: they are the one who said it.
    assert alert.raised_by_user_id not in {row.user_id for row in rows}


# --------------------------------------------------------------------------- #
# The walls
# --------------------------------------------------------------------------- #


async def test_a_voice_cannot_cancel_somebody_elses_alert(client, session):
    """Scoped to the speaker's own record, at the service layer."""
    family, subject, alert = await _senior_with_open_sos(client, session)
    other = await create_family(client, owner="owner-b", name="Other")
    other_senior = await session.get(SeniorProfile, uuid.UUID(other.senior_id))

    with pytest.raises(PermissionDenied) as caught:
        await alert_service.cancel_own_by_voice(
            session,
            alert=alert,
            senior=other_senior,
            actor_user_id=alert.raised_by_user_id,
        )
    assert caught.value.code == "alert_not_yours"

    await session.refresh(alert)
    assert alert.status is AlertStatus.RAISED


async def test_a_voice_cannot_undo_somebody_elses_conclusion(client, session):
    """Once a person has resolved it, it is theirs and not the speaker's."""
    family, subject, alert = await _senior_with_open_sos(client, session)
    senior = await session.get(SeniorProfile, alert.senior_profile_id)
    await alert_service.resolve(
        session, alert=alert, actor_user_id=alert.raised_by_user_id
    )

    with pytest.raises(Conflict) as caught:
        await alert_service.cancel_own_by_voice(
            session, alert=alert, senior=senior, actor_user_id=alert.raised_by_user_id
        )
    assert caught.value.code == "alert_already_resolved"


async def test_acknowledge_and_resolve_still_refuse_the_assistant(client, session):
    """The exception is cancellation and nothing else.

    Worth stating as its own test: the reason cancelling is safe to allow is
    that it is the *person themselves* withdrawing their own call for help.
    Acknowledging is somebody promising to go and look, and resolving is
    somebody saying it is over. Neither is a thing an assistant can be.
    """
    family, subject, alert = await _senior_with_open_sos(client, session)

    for action in ("acknowledge", "resolve"):
        with pytest.raises(PermissionDenied) as caught:
            await getattr(alert_service, action)(
                session,
                alert=alert,
                actor_user_id=alert.raised_by_user_id,
                actor_type=ActorType.AI,
            )
        assert caught.value.code == "ai_cannot_change_alert"

    await session.refresh(alert)
    assert alert.status is AlertStatus.RAISED


async def test_nothing_open_says_so_rather_than_inventing_one(client, session):
    """"Cancel" with nothing running is answered, not guessed at."""
    family = await create_family(client)
    subject = "the-senior"
    await join(client, family, subject=subject, role="viewer")
    await link_senior_account(session, family.senior_id, subject)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("cancel_my_sos", "fc-1")],
    )
    result = body["results"][0]
    assert result["ok"] is False
    assert "nothing to cancel" in result["response"]["message"]

    # No alert was created by asking about one, and no decision was executed.
    assert (await session.execute(select(Alert))).scalars().first() is None


async def test_a_refused_cancellation_leaves_the_escalation_running(client, session):
    """The dangerous failure is a cancel that half-works."""
    family, subject, alert = await _senior_with_open_sos(client, session)
    before = alert.next_escalation_at
    other = await create_family(client, owner="owner-b", name="Other")

    with pytest.raises(PermissionDenied):
        await alert_service.cancel_own_by_voice(
            session,
            alert=alert,
            senior=await session.get(SeniorProfile, uuid.UUID(other.senior_id)),
            actor_user_id=alert.raised_by_user_id,
        )

    await session.refresh(alert)
    assert alert.next_escalation_at == before
    assert alert.cancelled_at is None


async def test_the_decision_is_recorded_as_the_assistants_doing(client, session):
    """Every AI-executed change is distinguishable in the trail."""
    from app.models.ai import AiDecision

    family, subject, alert = await _senior_with_open_sos(client, session)
    live = await start_live_session(client, subject=subject)
    opened = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("cancel_my_sos", "fc-1")],
    )
    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "confirm_pending_action",
                "fc-2",
                decision_id=opened["results"][0]["decision_id"],
            )
        ],
    )

    decision = (
        await session.execute(
            select(AiDecision).where(AiDecision.tool_name == "cancel_my_sos")
        )
    ).scalar_one()
    assert decision.status is DecisionStatus.EXECUTED
    assert decision.result_entity_type == "alert"
    assert decision.result_entity_id == alert.id
