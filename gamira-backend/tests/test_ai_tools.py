"""Live function calling, end to end through the API.

Every test here is one of the ways a voice tool call can be wrong: a name that
does not exist, an argument that does not fit, an id from another family, a
call id already handled, a membership revoked since the session opened, a
mutation nobody confirmed. All of them have to fail as a structured result the
model can speak, not as an exception that ends the conversation.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.ai.tools import get_tool, needs_confirmation
from app.db.base import utcnow
from app.models.ai import AiDecision
from app.models.care import Reminder, TimelineEvent
from app.models.enums import (
    ConfirmationState,
    DecisionStatus,
    DoseStatus,
    LiveSessionStatus,
    ReminderStatus,
    ReminderType,
    TimelineEventType,
)
from app.models.medication import DoseEvent
from tests.conftest import auth
from tests.factories import (
    add_medication,
    call,
    call_tools,
    create_family,
    join,
    link_senior_account,
    list_doses,
    revoke_membership,
    start_live_session,
)


async def _senior_session(client, session, *, subject: str = "the-senior"):
    """A family, a linked senior account, one medicine, and an open session."""
    family = await create_family(client)
    await join(client, family, subject=subject, role="viewer")
    await link_senior_account(session, family.senior_id, subject)
    await add_medication(client, family)
    return family, subject


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #


async def test_a_read_tool_answers_from_the_backend(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await run_worker()
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-1")],
    )

    result = body["results"][0]
    assert result["ok"] is True
    # The id and the name come back unchanged: a response matched to the wrong
    # call makes the model attribute an answer to the wrong question.
    assert result["id"] == "fc-1"
    assert result["name"] == "get_today_doses"
    doses = result["response"]["doses"]
    assert len(doses) == 1
    assert doses[0]["medication"] == "Metformin"
    assert doses[0]["status"] == "not taken yet"


async def test_health_readings_come_back_without_a_judgement(client, session):
    family, subject = await _senior_session(client, session)
    await client.post(
        f"/api/v1/seniors/{family.senior_id}/health-readings",
        json={
            "metric": "blood_pressure_systolic",
            "value": 148,
            "unit": "mmHg",
            "source": "manual_family",
            "measured_at": utcnow().isoformat(),
        },
        headers=family.headers(),
    )
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_latest_health_readings", "fc-1")],
    )

    response = body["results"][0]["response"]
    assert response["readings"][0]["value"] == 148
    # The payload itself tells the model it is not qualified to interpret this.
    assert "does not assess" in response["note"]


async def test_emergency_contacts_come_back_without_phone_numbers(client, session):
    family, subject = await _senior_session(client, session)
    await client.post(
        f"/api/v1/seniors/{family.senior_id}/emergency-contacts",
        json={"name": "Priya", "phone": "+919812345678", "is_primary": True},
        headers=family.headers(),
    )
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_emergency_contacts", "fc-1")],
    )

    contact = body["results"][0]["response"]["contacts"][0]
    assert contact["name"] == "Priya"
    # Enough to confirm who, never enough to transcribe a number.
    assert contact["phone_ending"] == "5678"
    assert "+919812345678" not in str(body)


async def test_the_schedule_tool_merges_doses_and_reminders(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await client.post(
        f"/api/v1/seniors/{family.senior_id}/reminders",
        json={"title": "Walk", "local_time": "17:00"},
        headers=family.headers(),
    )
    await run_worker()
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_schedule", "fc-1")],
    )

    items = body["results"][0]["response"]["items"]
    kinds = {item["kind"] for item in items}
    assert kinds == {"dose", "reminder"}
    # In the order the day happens.
    assert [item["time"] for item in items] == sorted(item["time"] for item in items)


# --------------------------------------------------------------------------- #
# Rejections
# --------------------------------------------------------------------------- #


async def test_an_unknown_tool_is_refused(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("delete_all_medications", "fc-1")],
    )

    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "unknown_tool"
    assert result["id"] == "fc-1"


async def test_a_tool_outside_this_sessions_snapshot_is_refused(client, session):
    """A tool added to the server later is not callable by an older session."""
    from app.models.ai import LiveSession

    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    row = await session.get(LiveSession, uuid.UUID(live["session_id"]))
    row.tool_snapshot = [
        tool for tool in row.tool_snapshot if tool["name"] != "get_today_doses"
    ]
    await session.commit()

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-1")],
    )

    result = body["results"][0]
    assert result["response"]["error"] == "permission_denied"
    assert result["response"]["reason"] == "tool_not_in_session"


async def test_invalid_arguments_are_refused_without_echoing_them(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call("mark_dose_taken", "fc-1", dose_event_id="not-a-uuid"),
            call("get_latest_health_readings", "fc-2", metric="blood-type"),
            call("get_today_doses", "fc-3", unexpected="value"),
        ],
    )

    by_id = {result["id"]: result for result in body["results"]}
    assert by_id["fc-1"]["response"]["error"] == "invalid_arguments"
    assert by_id["fc-1"]["response"]["reason"] == "expected_uuid"
    assert by_id["fc-2"]["response"]["reason"] == "not_in_enum"
    assert by_id["fc-3"]["response"]["reason"] == "unexpected_property"
    # The rejected value never comes back: a tool call is model output, and
    # echoing it gives a prompt injection a second chance.
    assert "blood-type" not in str(body)
    assert "not-a-uuid" not in str(body)


async def test_a_missing_required_argument_is_refused(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("mark_dose_taken", "fc-1")],
    )

    assert body["results"][0]["response"]["reason"] == "required"


async def test_a_fabricated_entity_id_is_not_found(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("mark_dose_taken", "fc-1", dose_event_id=str(uuid.uuid4()))],
    )

    assert body["results"][0]["response"]["error"] == "not_found"


async def test_another_familys_dose_id_is_not_found(client, session, run_worker):
    """A well-formed uuid from another family looks exactly like a real one."""
    other = await create_family(client, owner="owner-b", name="Other")
    await add_medication(client, other)
    await run_worker()
    foreign_dose = (await list_doses(client, other))[0]

    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("mark_dose_taken", "fc-1", dose_event_id=foreign_dose["id"])],
    )

    # Ownership, not existence: the same answer as an invented id.
    assert body["results"][0]["response"]["error"] == "not_found"

    event = await session.get(DoseEvent, uuid.UUID(foreign_dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE


async def test_a_session_cannot_be_driven_by_another_user(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    response = await client.post(
        f"/api/v1/ai/live-sessions/{live['session_id']}/tool-calls",
        json={"calls": [call("get_today_doses", "fc-1")]},
        headers=auth("someone-else"),
    )
    assert response.status_code == 404


async def test_an_expired_session_refuses_tool_calls(client, session):
    from app.models.ai import LiveSession

    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)
    row = await session.get(LiveSession, uuid.UUID(live["session_id"]))
    row.expires_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    response = await client.post(
        f"/api/v1/ai/live-sessions/{live['session_id']}/tool-calls",
        json={"calls": [call("get_today_doses", "fc-1")]},
        headers=auth(subject),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_expired"
    # No decision row was created, so nothing is left half-done.
    assert await session.scalar(select(func.count()).select_from(AiDecision)) == 0


async def test_a_membership_revoked_mid_session_stops_the_next_tool_call(
    client, session, run_worker
):
    """The authorisation is re-checked at execution time, not at session start."""
    family = await create_family(client)
    await join(client, family, subject="carer", role="caregiver")
    await add_medication(client, family)
    await run_worker()
    live = await start_live_session(
        client, subject="carer", senior_id=family.senior_id
    )

    first = await call_tools(
        client,
        session_id=live["session_id"],
        subject="carer",
        calls=[call("get_today_doses", "fc-1")],
    )
    assert first["results"][0]["ok"] is True

    await revoke_membership(session, family_id=family.family_id, subject="carer")

    second = await call_tools(
        client,
        session_id=live["session_id"],
        subject="carer",
        calls=[call("get_today_doses", "fc-2")],
    )
    result = second["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "permission_denied"
    assert result["response"]["reason"] == "membership_revoked"


async def test_a_viewer_who_is_not_the_person_cannot_record_their_dose(
    client, session, run_worker
):
    family = await create_family(client)
    await join(client, family, subject="a-viewer", role="viewer")
    await add_medication(client, family)
    await run_worker()
    dose = (await list_doses(client, family))[0]
    live = await start_live_session(
        client, subject="a-viewer", senior_id=family.senior_id
    )

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject="a-viewer",
        calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
    )

    result = body["results"][0]
    assert result["response"]["error"] == "permission_denied"
    assert result["response"]["reason"] == "role_insufficient"


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #


async def test_a_mutation_asks_for_confirmation_naming_the_target(
    client, session, run_worker
):
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
    )

    result = body["results"][0]
    assert result["ok"] is False
    assert result["requires_confirmation"] is True
    assert result["response"]["error"] == "confirmation_required"
    # The exact action and target, in words a person hears and reads.
    assert (
        result["confirmation_prompt"]
        == "Mark Metformin scheduled for 8:00 AM as taken?"
    )
    assert result["decision_id"]

    # Nothing has changed yet.
    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE


async def test_confirming_records_one_dose_and_one_timeline_event(
    client, session, run_worker
):
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]

    confirmed = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth(subject)
    )

    assert confirmed.status_code == 200
    outcome = confirmed.json()
    assert outcome["decision"]["status"] == DecisionStatus.EXECUTED.value
    assert outcome["decision"]["confirmation_state"] == ConfirmationState.CONFIRMED.value
    # The client hands this straight back to Gemini, with the original id.
    assert outcome["function_call_id"] == "fc-1"
    assert outcome["tool_name"] == "mark_dose_taken"
    assert outcome["tool_response"]["status"] == "ok"
    assert outcome["tool_response"]["recorded_status"] == "taken"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.TAKEN

    taken = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(TimelineEvent.type == TimelineEventType.MEDICATION_TAKEN)
    )
    assert taken == 1


async def test_rejecting_a_confirmation_changes_nothing(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]

    rejected = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/reject", headers=auth(subject)
    )

    assert rejected.status_code == 200
    assert rejected.json()["decision"]["status"] == DecisionStatus.REJECTED.value
    assert rejected.json()["tool_response"]["error"] == "rejected_by_user"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE
    assert (
        await session.scalar(
            select(func.count())
            .select_from(TimelineEvent)
            .where(TimelineEvent.type == TimelineEventType.MEDICATION_TAKEN)
        )
        == 0
    )


async def test_a_rejected_decision_cannot_then_be_confirmed(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]
    await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/reject", headers=auth(subject)
    )

    confirmed = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth(subject)
    )
    assert confirmed.json()["tool_response"]["status"] == "error"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE


async def test_an_expired_confirmation_does_not_execute(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]

    decision = await session.get(AiDecision, uuid.UUID(proposed["decision_id"]))
    decision.expires_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    confirmed = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth(subject)
    )
    assert confirmed.json()["tool_response"]["status"] == "error"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE


async def test_a_revocation_between_prompt_and_confirmation_blocks_it(
    client, session, run_worker
):
    """The gap between showing a dialog and tapping it is still a gap."""
    family = await create_family(client)
    await join(client, family, subject="carer", role="caregiver")
    await add_medication(client, family)
    await run_worker()
    dose = (await list_doses(client, family))[0]
    live = await start_live_session(client, subject="carer", senior_id=family.senior_id)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject="carer",
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]

    await revoke_membership(session, family_id=family.family_id, subject="carer")

    confirmed = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth("carer")
    )
    assert confirmed.json()["tool_response"]["error"] == "permission_denied"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE


async def test_another_person_cannot_confirm_somebody_elses_decision(
    client, session, run_worker
):
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]

    response = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm",
        headers=auth("owner-a"),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


async def test_a_duplicate_call_id_does_not_act_twice(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await run_worker()
    live = await start_live_session(client, subject=subject)

    first = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-1")],
    )
    second = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-1")],
    )

    assert first["results"][0]["ok"] is True
    assert second["results"][0]["response"]["error"] == "duplicate_call"
    # Still the right id and name, so the model can match the answer up.
    assert second["results"][0]["id"] == "fc-1"
    assert second["results"][0]["name"] == "get_today_doses"


async def test_repeating_a_confirmed_mutation_does_not_mutate_twice(
    client, session, run_worker
):
    """The same dose, a second time, through a second call id."""
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)

    for call_id in ("fc-1", "fc-2"):
        proposed = (
            await call_tools(
                client,
                session_id=live["session_id"],
                subject=subject,
                calls=[call("mark_dose_taken", call_id, dose_event_id=dose["id"])],
            )
        )["results"][0]
        await client.post(
            f"/api/v1/ai/actions/{proposed['decision_id']}/confirm",
            headers=auth(subject),
        )

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.TAKEN

    # One dose, one timeline event, whatever the model asked for.
    taken = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(TimelineEvent.type == TimelineEventType.MEDICATION_TAKEN)
    )
    assert taken == 1


async def test_the_idempotency_key_is_the_documented_shape(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    await run_worker()
    live = await start_live_session(client, subject=subject)
    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-1")],
    )

    decision = (await session.execute(select(AiDecision))).scalars().one()
    assert decision.idempotency_key == f"live:{live['session_id']}:fc-1"


# --------------------------------------------------------------------------- #
# Batches and failures
# --------------------------------------------------------------------------- #


async def test_several_calls_in_one_message_each_keep_their_id(
    client, session, run_worker
):
    family, subject = await _senior_session(client, session)
    await run_worker()
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call("get_today_doses", "fc-a"),
            call("get_reminders", "fc-b"),
            call("get_notification_summary", "fc-c"),
        ],
    )

    results = body["results"]
    assert [result["id"] for result in results] == ["fc-a", "fc-b", "fc-c"]
    assert [result["name"] for result in results] == [
        "get_today_doses",
        "get_reminders",
        "get_notification_summary",
    ]
    assert all(result["ok"] for result in results)


async def test_one_failing_call_does_not_fail_the_batch_or_the_session(
    client, session, run_worker
):
    family, subject = await _senior_session(client, session)
    await run_worker()
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call("get_today_doses", "fc-good"),
            call("no_such_tool", "fc-bad"),
            call("get_reminders", "fc-also-good"),
        ],
    )

    by_id = {result["id"]: result for result in body["results"]}
    assert by_id["fc-good"]["ok"] is True
    assert by_id["fc-bad"]["ok"] is False
    assert by_id["fc-also-good"]["ok"] is True

    # And the session is still usable afterwards.
    from app.models.ai import LiveSession

    row = await session.get(LiveSession, uuid.UUID(live["session_id"]))
    await session.refresh(row)
    assert row.status is LiveSessionStatus.ACTIVE

    after = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-later")],
    )
    assert after["results"][0]["ok"] is True


async def test_no_error_response_carries_a_traceback_or_internals(
    client, session, run_worker
):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call("no_such_tool", "fc-1"),
            call("mark_dose_taken", "fc-2", dose_event_id=str(uuid.uuid4())),
        ],
    )

    text = str(body)
    for leak in ("Traceback", "sqlalchemy", "SELECT ", "app/ai/", "Exception"):
        assert leak not in text


async def test_a_completed_reminder_is_recorded_once(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    created = await client.post(
        f"/api/v1/seniors/{family.senior_id}/reminders",
        json={"title": "Drink water", "local_time": "11:00"},
        headers=family.headers(),
    )
    reminder_id = created.json()["id"]
    live = await start_live_session(client, subject=subject)

    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[
                call(
                    "complete_reminder",
                    "fc-1",
                    proposed_by="gamira",
                    reminder_id=reminder_id,
                )
            ],
        )
    )["results"][0]
    assert proposed["confirmation_prompt"] == "Mark Drink water as done?"

    confirmed = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth(subject)
    )
    assert confirmed.json()["tool_response"]["changed"] is True

    completed = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(TimelineEvent.type == TimelineEventType.REMINDER_COMPLETED)
    )
    assert completed == 1


async def test_the_backend_will_not_run_a_client_tool(client, session):
    """prepare_sos opens a screen. There is no server path by which it acts.

    The app dispatches client tools through its own allowlist and never
    forwards them, so one arriving here is misrouted — and gets a named answer
    rather than executing anything.
    """
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call("prepare_sos", "fc-1"),
            call("navigate_to_screen", "fc-2", screen="health"),
            call("prepare_call_contact", "fc-3", contact_id=str(uuid.uuid4())),
        ],
    )

    for result in body["results"]:
        assert result["ok"] is False
        assert result["response"]["error"] == "client_tool", result["name"]

    # No alert exists, and none can be created this way.
    from app.models.alerts import Alert

    assert await session.scalar(select(func.count()).select_from(Alert)) == 0


async def test_the_sos_confirmation_prompt_is_server_authored():
    """The wording a person is shown comes from the backend, not the model."""
    from app.ai.executor import _confirmation_prompt
    from app.ai.tools import CATALOGUE

    assert (
        _confirmation_prompt(CATALOGUE["prepare_sos"], None)
        == "Open the emergency SOS screen?"
    )


async def test_a_mutation_by_voice_is_audited(client, session, run_worker):
    from app.models.audit import AuditLog

    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]
    await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth(subject)
    )

    entry = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "ai.tool.mark_dose_taken")
        )
    ).scalars().one()
    assert entry.metadata_json["via"] == "live_voice"
    assert entry.target_id == uuid.UUID(dose["id"])


async def test_the_session_counts_its_tool_calls(client, session, run_worker):
    from app.models.ai import LiveSession

    family, subject = await _senior_session(client, session)
    await run_worker()
    live = await start_live_session(client, subject=subject)
    await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("get_today_doses", "fc-1"), call("get_reminders", "fc-2")],
    )

    row = await session.get(LiveSession, uuid.UUID(live["session_id"]))
    await session.refresh(row)
    assert row.tool_call_count == 2
    assert row.last_seen_at is not None


# --------------------------------------------------------------------------- #
# Adding a reminder by voice
#
# The line this has to hold: a reminder is an everyday routine, and a medication
# is not. `docs/AI_SAFETY.md` lists adding or editing a medication among the
# things there is deliberately no tool for, and adding one by talking to the
# assistant must not become the exception.
#
# The second line, newer: asking for an everyday routine out loud *is* the
# consent for it. A dialog in front of what somebody just asked for is a hurdle
# in front of their own request, and the person least able to clear it is the
# one this app is for. So `proposed_by` decides — and it decides nothing about
# medicines, which are confirmed either way.
# --------------------------------------------------------------------------- #


async def test_a_reminder_they_asked_for_is_simply_added(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "create_reminder",
                "fc-1",
                proposed_by="them",
                title="water the plants",
                local_time="16:30",
            )
        ],
    )

    result = body["results"][0]
    assert result["ok"] is True
    assert result["requires_confirmation"] is False
    reminder = (await session.execute(select(Reminder))).scalar_one()
    assert reminder.title == "water the plants"
    assert reminder.local_time == "16:30"
    # And the model is told what really exists, so it can say so.
    assert result["response"]["reminder_id"] == str(reminder.id)


async def test_a_reminder_gamira_suggested_asks_first_and_names_it(client, session):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "create_reminder",
                "fc-1",
                proposed_by="gamira",
                title="water the plants",
                local_time="16:30",
            )
        ],
    )

    result = body["results"][0]
    assert result["requires_confirmation"] is True
    assert result["confirmation_prompt"] == (
        "Add a reminder to water the plants at 4:30 PM?"
    )
    # Nothing exists until a person says yes.
    assert await session.scalar(select(func.count()).select_from(Reminder)) == 0


async def test_an_unstated_proposer_is_treated_as_a_suggestion(client, session):
    """Absent, or anything but "them", confirms. The default is the cautious one."""
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    spec = get_tool("create_reminder")
    assert needs_confirmation(spec, {}) is True
    assert needs_confirmation(spec, {"proposed_by": "gamira"}) is True
    assert needs_confirmation(spec, {"proposed_by": "them"}) is False

    # And it is a required argument, so the model cannot quietly leave it out.
    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("create_reminder", "fc-1", title="tea", local_time="16:00")],
    )
    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "invalid_arguments"
    assert await session.scalar(select(func.count()).select_from(Reminder)) == 0


async def test_confirming_writes_the_reminder_against_the_verified_person(
    client, session
):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[
                call(
                    "create_reminder",
                    "fc-1",
                    proposed_by="gamira",
                    title="walk to the park",
                    local_time="07:15",
                    instructions="the short way round",
                )
            ],
        )
    )["results"][0]

    confirmed = await client.post(
        f"/api/v1/ai/actions/{proposed['decision_id']}/confirm", headers=auth(subject)
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["tool_response"]["status"] == "ok"

    reminder = (await session.execute(select(Reminder))).scalar_one()
    assert reminder.title == "walk to the park"
    assert reminder.local_time == "07:15"
    assert reminder.instructions == "the short way round"
    assert reminder.status is ReminderStatus.ACTIVE
    # From the session's verified scope, never from anything that was said.
    assert str(reminder.senior_profile_id) == family.senior_id
    assert reminder.timezone == "Asia/Kolkata"
    # Never a medication, whatever it was called.
    assert reminder.type is ReminderType.OTHER


async def test_a_reminder_cannot_smuggle_in_a_medication_type(client, session):
    """`type` is not an argument at all, so there is nothing to smuggle it in."""
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call(
                "create_reminder",
                "fc-1",
                proposed_by="them",
                title="Metformin",
                local_time="08:00",
                type="medication",
            )
        ],
    )

    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "invalid_arguments"
    assert result["response"]["reason"] == "unexpected_property"


async def test_a_time_that_is_not_a_time_is_refused(client, session):
    """Without a pattern check this reached the database as a 500-char string."""
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    for bad in ("half four", "25:00", "7:15", "07:15:00", ""):
        body = await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[
                call(
                    "create_reminder",
                    f"fc-{bad}",
                    proposed_by="them",
                    title="tea",
                    local_time=bad,
                )
            ],
        )
        result = body["results"][0]
        assert result["ok"] is False, f"{bad!r} was accepted"
        assert result["response"]["error"] == "invalid_arguments"
        # The rejected value never comes back — it is model output.
        assert bad not in str(result["response"]) or bad == ""

    assert await session.scalar(select(func.count()).select_from(Reminder)) == 0


async def test_a_viewer_who_is_not_the_person_cannot_add_a_reminder(client, session):
    """Same rule as recording somebody else's dose.

    Note the ``proposed_by="them"`` — the path that skips the dialog. Skipping
    the *confirmation* never skips the *permission*: the policy engine runs
    first either way, and it is the only thing deciding who may write.
    """
    family = await create_family(client)
    await join(client, family, subject="a-viewer", role="viewer")
    live = await client.post(
        "/api/v1/ai/live-sessions",
        json={"senior_id": family.senior_id},
        headers=auth("a-viewer"),
    )
    assert live.status_code == 201

    body = await call_tools(
        client,
        session_id=live.json()["session_id"],
        subject="a-viewer",
        calls=[
            call(
                "create_reminder",
                "fc-1",
                proposed_by="them",
                title="tea",
                local_time="16:00",
            )
        ],
    )

    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "permission_denied"
    assert await session.scalar(select(func.count()).select_from(Reminder)) == 0


# --------------------------------------------------------------------------- #
# Answering a confirmation out loud
#
# The dialog stays — `docs/AI_SAFETY.md` promises a visible, tappable one, and
# it is also the fallback when speech is not understood. What these two tools
# add is that "yes" is worth as much as a tap, for somebody who cannot reliably
# reach a phone. They decide nothing themselves: the action and its wording were
# settled when the confirmation was raised.
# --------------------------------------------------------------------------- #


async def _pending_dose_confirmation(client, session, run_worker):
    """A dose confirmation waiting on an answer, in an open session."""
    family, subject = await _senior_session(client, session)
    await run_worker()
    dose = (await list_doses(client, family, actor=subject))[0]
    live = await start_live_session(client, subject=subject)
    proposed = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("mark_dose_taken", "fc-1", dose_event_id=dose["id"])],
        )
    )["results"][0]
    assert proposed["requires_confirmation"] is True
    return family, subject, live, dose, proposed["decision_id"]


async def test_saying_yes_runs_the_action_that_was_read_out(
    client, session, run_worker
):
    family, subject, live, dose, decision_id = await _pending_dose_confirmation(
        client, session, run_worker
    )

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("confirm_pending_action", "fc-2", decision_id=decision_id)],
    )

    result = body["results"][0]
    assert result["ok"] is True
    # The persisted outcome of the *underlying* action, so the model can only
    # say a dose was recorded once a dose really was.
    assert result["response"]["recorded_status"] == "taken"
    assert result["response"]["resolved_decision_id"] == decision_id

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.TAKEN

    decision = await session.get(AiDecision, uuid.UUID(decision_id))
    await session.refresh(decision)
    assert decision.confirmation_state is ConfirmationState.CONFIRMED
    assert decision.status is DecisionStatus.EXECUTED


async def test_saying_no_changes_nothing(client, session, run_worker):
    family, subject, live, dose, decision_id = await _pending_dose_confirmation(
        client, session, run_worker
    )

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("cancel_pending_action", "fc-2", decision_id=decision_id)],
    )

    assert body["results"][0]["response"]["outcome"] == "cancelled"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE

    decision = await session.get(AiDecision, uuid.UUID(decision_id))
    await session.refresh(decision)
    assert decision.confirmation_state is ConfirmationState.REJECTED
    assert decision.status is DecisionStatus.REJECTED


async def test_saying_yes_twice_records_one_dose(client, session, run_worker):
    """Spoken and tapped can race. Whichever lands second must do nothing."""
    family, subject, live, dose, decision_id = await _pending_dose_confirmation(
        client, session, run_worker
    )

    for call_id in ("fc-2", "fc-3"):
        body = await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("confirm_pending_action", call_id, decision_id=decision_id)],
        )
        assert body["results"][0]["response"].get("error") != "action_failed"

    taken = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(TimelineEvent.type == TimelineEventType.MEDICATION_TAKEN)
    )
    assert taken == 1


async def test_a_decision_from_another_session_cannot_be_confirmed(
    client, session, run_worker
):
    """Even this person's own, from a conversation that has ended.

    The model may only answer a question it was asked in *this* conversation.
    An id it kept, guessed, or was read out to it goes nowhere.
    """
    family, subject, first, dose, decision_id = await _pending_dose_confirmation(
        client, session, run_worker
    )
    second = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=second["session_id"],
        subject=subject,
        calls=[call("confirm_pending_action", "fc-2", decision_id=decision_id)],
    )

    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "not_found"

    event = await session.get(DoseEvent, uuid.UUID(dose["id"]))
    await session.refresh(event)
    assert event.status is DoseStatus.DUE


async def test_an_invented_decision_id_confirms_nothing(client, session, run_worker):
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)

    body = await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[
            call("confirm_pending_action", "fc-1", decision_id=str(uuid.uuid4())),
            call("confirm_pending_action", "fc-2", decision_id="not-a-uuid"),
        ],
    )

    assert body["results"][0]["response"]["error"] == "not_found"
    assert body["results"][1]["response"]["error"] == "invalid_arguments"


async def test_asking_twice_while_it_is_still_on_screen_shows_one_dialog(
    client, session, run_worker
):
    """A model that asked, heard nothing, and tried again with a new call id.

    Without this the person answers two dialogs for one thing — and the second
    would still be sitting there, unanswerable, after they dealt with the first.
    """
    family, subject = await _senior_session(client, session)
    live = await start_live_session(client, subject=subject)
    arguments = {
        "proposed_by": "gamira",
        "title": "water the plants",
        "local_time": "16:30",
    }

    first = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("create_reminder", "fc-1", **arguments)],
        )
    )["results"][0]
    second = (
        await call_tools(
            client,
            session_id=live["session_id"],
            subject=subject,
            calls=[call("create_reminder", "fc-2", **arguments)],
        )
    )["results"][0]

    assert second["requires_confirmation"] is True
    assert second["decision_id"] == first["decision_id"]
    pending = await session.scalar(
        select(func.count())
        .select_from(AiDecision)
        .where(AiDecision.confirmation_state == ConfirmationState.PENDING)
    )
    assert pending == 1
