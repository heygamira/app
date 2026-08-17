"""What still works when the assistant does not.

This is the deterministic core from ``docs/AI_SAFETY.md``, asserted rather than
asserted-in-prose. With the AI provider raising on every call and the Live token
minter refusing to mint, a person must still be able to see today's medicines,
record one, and raise an emergency — and the family must still be told.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.ai.provider import AIUnavailable
from app.core.errors import DependencyUnavailable
from app.jobs.types import JobType
from app.models.alerts import Alert
from app.models.care import TimelineEvent
from app.models.enums import AlertStatus, DoseStatus, TimelineEventType
from app.models.medication import DoseEvent
from tests.conftest import auth
from tests.factories import (
    add_medication,
    create_family,
    join,
    link_senior_account,
    list_doses,
)


async def _total_outage(ai_provider, token_minter) -> None:
    """Everything model-shaped is down, for the whole test."""
    ai_provider.fail_with = AIUnavailable("the provider is unreachable")
    token_minter.fail_with = DependencyUnavailable("voice is unavailable")


async def test_the_medication_loop_works_with_the_ai_down(
    client, session, run_worker, ai_provider, token_minter
):
    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    await link_senior_account(session, family.senior_id, "the-senior")
    await add_medication(client, family)

    # The worker materialises the day. No AI handler is involved.
    assert await run_worker() >= 1
    doses = await list_doses(client, family, actor="the-senior")
    assert len(doses) == 1

    taken = await client.post(
        f"/api/v1/dose-events/{doses[0]['id']}/taken",
        json={"source": "parent_app"},
        headers=auth("the-senior"),
    )
    assert taken.status_code == 200
    assert taken.json()["status"] == "taken"

    timeline = (
        await client.get(
            f"/api/v1/seniors/{family.senior_id}/timeline", headers=family.headers()
        )
    ).json()
    assert "medication_taken" in [event["type"] for event in timeline]


async def test_a_dose_still_becomes_missed_with_the_ai_down(
    client, session, run_worker, ai_provider, token_minter
):
    import datetime as dt

    from app.db.base import utcnow

    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await add_medication(client, family, missed_after_minutes=60)
    await run_worker()

    event = (
        await session.execute(
            select(DoseEvent).where(
                DoseEvent.senior_profile_id == uuid.UUID(family.senior_id)
            )
        )
    ).scalars().first()
    event.scheduled_at_utc = utcnow() - dt.timedelta(minutes=180)
    await session.commit()

    await run_worker(JobType.DOSE_ADVANCE_STATUS)

    await session.refresh(event)
    assert event.status is DoseStatus.MISSED

    missed = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(TimelineEvent.type == TimelineEventType.MEDICATION_MISSED)
    )
    assert missed == 1

    rows = (await client.get("/api/v1/notifications", headers=auth("daughter"))).json()
    missed_rows = [row for row in rows if row["type"] == "missed_dose"]
    assert len(missed_rows) == 1


async def test_a_manual_sos_works_with_the_ai_down(
    client, session, run_worker, ai_provider, token_minter
):
    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    await join(client, family, subject="daughter", role="family")
    await link_senior_account(session, family.senior_id, "the-senior")

    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos",
        json={"source": "parent_app"},
        headers=auth("the-senior"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["delivery"] == "in_app_only"
    assert len(body["notified_user_ids"]) == 2

    alert = await session.get(Alert, uuid.UUID(body["id"]))
    assert alert.status is AlertStatus.RAISED

    for member in ("owner-a", "daughter"):
        rows = (await client.get("/api/v1/notifications", headers=auth(member))).json()
        assert "sos" in [row["type"] for row in rows]


async def test_an_sos_still_escalates_with_the_ai_down(
    client, session, run_worker, ai_provider, token_minter
):
    import datetime as dt

    from app.db.base import utcnow

    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = (
        await client.post(
            f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
        )
    ).json()

    alert = await session.get(Alert, uuid.UUID(body["id"]))
    alert.next_escalation_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    await run_worker(JobType.ALERT_ESCALATION_CHECK)

    await session.refresh(alert)
    assert alert.escalation_count == 1
    assert alert.status is AlertStatus.ESCALATED


async def test_an_sos_can_still_be_acknowledged_and_resolved_with_the_ai_down(
    client, session, ai_provider, token_minter
):
    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = (
        await client.post(
            f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
        )
    ).json()

    acknowledged = await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("daughter")
    )
    resolved = await client.post(
        f"/api/v1/alerts/{body['id']}/resolve",
        json={"resolution": "Spoke to her, she is fine"},
        headers=auth("daughter"),
    )

    assert acknowledged.status_code == 200
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


async def test_voice_fails_safely_and_says_so(client, ai_provider, token_minter):
    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    response = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    # And it says what still works, rather than looking like a total outage.
    assert "still work" in response.json()["error"]["message"]


async def test_chat_fails_safely_and_says_so(client, ai_provider, token_minter):
    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    response = await client.post(
        "/api/v1/ai/chat",
        json={"senior_id": family.senior_id, "message": "What do I take today?"},
        headers=family.headers(),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"
    assert "still work" in response.json()["error"]["message"]


async def test_reads_and_writes_across_the_api_are_unaffected(
    client, session, run_worker, ai_provider, token_minter
):
    """A broad sweep: nothing outside /ai should notice the provider at all."""
    await _total_outage(ai_provider, token_minter)

    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await add_medication(client, family)
    await run_worker()

    paths = [
        "/api/v1/me",
        f"/api/v1/families/{family.family_id}/members",
        f"/api/v1/seniors/{family.senior_id}",
        f"/api/v1/seniors/{family.senior_id}/medications",
        f"/api/v1/seniors/{family.senior_id}/doses",
        f"/api/v1/seniors/{family.senior_id}/reminders",
        f"/api/v1/seniors/{family.senior_id}/timeline",
        f"/api/v1/seniors/{family.senior_id}/health-readings",
        f"/api/v1/seniors/{family.senior_id}/emergency-contacts",
        f"/api/v1/seniors/{family.senior_id}/appointments",
        "/api/v1/notifications",
        "/api/v1/devices",
        "/health",
    ]
    for path in paths:
        response = await client.get(path, headers=family.headers())
        assert response.status_code == 200, path

    created = await client.post(
        f"/api/v1/seniors/{family.senior_id}/reminders",
        json={"title": "Walk", "local_time": "17:00"},
        headers=family.headers(),
    )
    assert created.status_code == 201
