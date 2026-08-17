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

from app.db.base import utcnow
from app.models.ai import AiDecision
from app.models.care import TimelineEvent
from app.models.enums import (
    ConfirmationState,
    DecisionStatus,
    DoseStatus,
    LiveSessionStatus,
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
            calls=[call("complete_reminder", "fc-1", reminder_id=reminder_id)],
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
