"""Telling the family something that is not an emergency.

The gap this closes was the whole of the middle. "I've had a headache all
morning" had two endings: an SOS, which it is not, or nothing until the
after-call review ran — and that only sends anything if the model said out loud
that it would, only after the conversation ends, and only once the worker
reaches it. So the commonest thing anybody would want their family to know
arrived late or never.

What matters in these tests is what it is *not*: not an alert, not urgent, not
something Gamira can send without either being asked or being agreed with.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.ai.tools import get_tool, needs_confirmation
from app.models.alerts import Alert
from app.models.care import NotificationDelivery
from app.models.enums import NotificationChannel, NotificationType
from tests.conftest import auth
from tests.factories import (
    call,
    call_tools,
    create_family,
    join,
    link_senior_account,
    start_live_session,
)


async def _family(client, session, *, subject: str = "the-senior"):
    family = await create_family(client)
    await join(client, family, subject=subject, role="viewer")
    await link_senior_account(session, family.senior_id, subject)
    return family, subject


async def _notifications(session, kind: NotificationType) -> list[NotificationDelivery]:
    rows = await session.execute(
        select(NotificationDelivery).where(NotificationDelivery.type == kind)
    )
    return list(rows.scalars())


async def test_saying_they_are_unwell_reaches_the_family(client, session):
    """The point of the tool, in one call."""
    family, subject = await _family(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "tell_family",
                proposed_by="them",
                message="Vikram said he has had a headache since this morning.",
            )
        ],
    )
    result = body["results"][0]
    assert result["response"]["status"] == "ok", result
    assert result["response"]["told"] >= 1

    sent = await _notifications(session, NotificationType.FAMILY_UPDATE)
    assert len(sent) == 1
    assert "headache" in (sent[0].body or "")
    # In the app, not on anybody's lock screen: the urgent path is an alert,
    # and she cannot raise one.
    assert {row.channel for row in sent} == {NotificationChannel.IN_APP}


async def test_it_raises_no_alert(client, session):
    """A quiet note and an emergency must not be able to become each other."""
    family, subject = await _family(client, session)
    live = await start_live_session(client, subject=subject)

    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "tell_family",
                proposed_by="them",
                message="Vikram said he is feeling low today.",
            )
        ],
    )

    alerts = await session.scalar(select(func.count()).select_from(Alert))
    assert (alerts or 0) == 0


async def test_gamira_suggesting_it_has_to_be_agreed_to(client, session):
    """Nobody asked, so it is confirmed like anything else.

    The rule is in code, not in the prompt: `needs_confirmation` reads
    `proposed_by`, and a message the person has not agreed to sends nothing
    until they do.
    """
    spec = get_tool("tell_family")
    assert spec is not None
    assert needs_confirmation(spec, {"proposed_by": "gamira"}) is True
    assert needs_confirmation(spec, {"proposed_by": "them"}) is False

    family, subject = await _family(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "tell_family",
                proposed_by="gamira",
                message="Vikram sounded tired this evening.",
            )
        ],
    )
    result = body["results"][0]
    assert result["requires_confirmation"] is True
    # The sentence they are asked about is the sentence that would be sent.
    assert "sounded tired this evening" in result["confirmation_prompt"]
    assert not await _notifications(session, NotificationType.FAMILY_UPDATE)


async def test_the_message_is_on_the_family_timeline(client, session):
    """Reachable later, not only as a notification somebody may dismiss."""
    family, subject = await _family(client, session)
    live = await start_live_session(client, subject=subject)

    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "tell_family",
                proposed_by="them",
                message="Vikram said his knee is sore after his walk.",
            )
        ],
    )

    timeline = await client.get(
        f"/api/v1/seniors/{family.senior_id}/timeline", headers=auth(family.owner)
    )
    assert timeline.status_code == 200, timeline.text
    entries = timeline.json()
    assert any("knee is sore" in (entry.get("description") or "") for entry in entries)
