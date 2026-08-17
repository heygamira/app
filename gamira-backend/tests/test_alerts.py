"""The SOS alert lifecycle.

Before this existed, an SOS was a timeline row: nothing recorded that somebody
had responded, and nothing escalated when nobody did. These tests are about
those two gaps, plus the rule that closes the door on the assistant.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.core.errors import PermissionDenied
from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.alerts import Alert, AlertEvent
from app.models.enums import (
    ActorType,
    AlertEventType,
    AlertStatus,
    JobStatus,
    NotificationType,
)
from app.models.jobs import BackgroundJob
from tests.conftest import auth
from tests.factories import create_family, join, link_senior_account


async def _raise_sos(client, family, *, actor: str | None = None, **body):
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos",
        json=body or {},
        headers=family.headers(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_raising_an_sos_creates_a_persistent_alert(client, session):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")

    body = await _raise_sos(client, family, source="parent_app")

    assert body["status"] == "raised"
    # The response says exactly what Gamira did, and nothing more.
    assert body["delivery"] == "in_app_only"

    alert = await session.get(Alert, uuid.UUID(body["id"]))
    assert alert is not None
    assert alert.status is AlertStatus.RAISED
    assert alert.raised_at is not None
    assert alert.next_escalation_at is not None
    assert alert.notified_user_count == 1


async def test_the_history_starts_with_raised_and_a_delivery_attempt(client):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)

    events = (
        await client.get(f"/api/v1/alerts/{body['id']}/events", headers=family.headers())
    ).json()

    assert [event["type"] for event in events] == ["raised", "delivery_attempted"]
    assert events[1]["detail"]["recipients"] == 1


async def test_a_watch_press_records_its_source(client, session):
    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    await link_senior_account(session, family.senior_id, "the-senior")

    body = await _raise_sos(
        client, family, actor="the-senior", source="watch", note="Fell in the kitchen"
    )

    assert body["source"] == "watch"
    alert = await session.get(Alert, uuid.UUID(body["id"]))
    assert alert.note == "Fell in the kitchen"

    events = (
        await client.get(
            f"/api/v1/alerts/{body['id']}/events", headers=auth("the-senior")
        )
    ).json()
    # Attributed to the device, not to a person tapping a screen.
    assert events[0]["actor_type"] == ActorType.DEVICE.value


async def test_acknowledging_names_a_person_and_stops_the_escalation(client, session):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)

    response = await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge",
        json={"note": "Calling her now"},
        headers=auth("daughter"),
    )

    assert response.status_code == 200
    acknowledged = response.json()
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_at"] is not None
    assert acknowledged["acknowledged_by_user_id"] is not None
    # Somebody is on it, so the family is not told again.
    assert acknowledged["next_escalation_at"] is None


async def test_the_first_acknowledgement_wins(client):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await join(client, family, subject="son", role="family")
    body = await _raise_sos(client, family)

    first = await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("daughter")
    )
    second = await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("son")
    )

    assert first.json()["acknowledged_by_user_id"] == (
        second.json()["acknowledged_by_user_id"]
    )
    assert first.json()["acknowledged_at"] == second.json()["acknowledged_at"]


async def test_a_viewer_may_acknowledge_an_emergency(client, session):
    """Answering an emergency is not an administrative privilege."""
    family = await create_family(client)
    await join(client, family, subject="a-viewer", role="viewer")
    body = await _raise_sos(client, family)

    response = await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("a-viewer")
    )
    assert response.status_code == 200


async def test_an_unacknowledged_alert_escalates_to_the_same_family(
    client, session, run_worker
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)

    alert = await session.get(Alert, uuid.UUID(body["id"]))
    alert.next_escalation_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    await run_worker(JobType.ALERT_ESCALATION_CHECK)

    await session.refresh(alert)
    assert alert.status is AlertStatus.ESCALATED
    assert alert.escalation_count == 1

    rows = (await client.get("/api/v1/notifications", headers=auth("daughter"))).json()
    kinds = [row["type"] for row in rows]
    assert NotificationType.SOS_ESCALATION.value in kinds
    # Escalation is louder, not wider: nobody outside the family is contacted.
    assert all(row["senior_profile_id"] == family.senior_id for row in rows)


async def test_escalation_stops_at_the_configured_limit(client, session, run_worker):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)
    alert = await session.get(Alert, uuid.UUID(body["id"]))

    from app.core.config import get_settings

    limit = get_settings().sos_max_escalations
    for _ in range(limit + 2):
        if alert.next_escalation_at is None:
            break
        alert.next_escalation_at = utcnow() - dt.timedelta(seconds=1)
        await session.commit()
        await run_worker(JobType.ALERT_ESCALATION_CHECK)
        await session.refresh(alert)

    assert alert.escalation_count == limit
    # The alert stays open and visible; it simply stops generating new noise.
    assert alert.next_escalation_at is None
    assert alert.status is AlertStatus.ESCALATED


async def test_an_acknowledged_alert_is_never_escalated(client, session, run_worker):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)
    await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("daughter")
    )

    alert = await session.get(Alert, uuid.UUID(body["id"]))
    alert.next_escalation_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    await run_worker(JobType.ALERT_ESCALATION_CHECK)
    await session.refresh(alert)
    assert alert.escalation_count == 0


async def test_resolving_records_who_and_when(client, session):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)

    response = await client.post(
        f"/api/v1/alerts/{body['id']}/resolve",
        json={"resolution": "She is fine, she pressed it by mistake"},
        headers=auth("daughter"),
    )

    assert response.status_code == 200
    resolved = response.json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by_user_id"] is not None
    assert resolved["resolved_at"] is not None
    # Resolving without a separate acknowledgement still records both.
    assert resolved["acknowledged_at"] is not None

    events = (
        await client.get(f"/api/v1/alerts/{body['id']}/events", headers=auth("daughter"))
    ).json()
    assert [event["type"] for event in events][-1] == AlertEventType.RESOLVED.value


async def test_resolving_twice_is_idempotent(client):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)

    first = await client.post(
        f"/api/v1/alerts/{body['id']}/resolve", json={}, headers=auth("daughter")
    )
    second = await client.post(
        f"/api/v1/alerts/{body['id']}/resolve", json={}, headers=auth("daughter")
    )

    assert first.json()["resolved_at"] == second.json()["resolved_at"]


async def test_cancelling_requires_a_reason(client, session):
    family = await create_family(client)
    body = await _raise_sos(client, family)

    empty = await client.post(
        f"/api/v1/alerts/{body['id']}/cancel", json={"reason": ""},
        headers=family.headers(),
    )
    assert empty.status_code == 422

    cancelled = await client.post(
        f"/api/v1/alerts/{body['id']}/cancel",
        json={"reason": "Pressed while cleaning the phone"},
        headers=family.headers(),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"]


async def test_a_resolved_alert_cannot_be_cancelled(client):
    family = await create_family(client)
    body = await _raise_sos(client, family)
    await client.post(
        f"/api/v1/alerts/{body['id']}/resolve", json={}, headers=family.headers()
    )

    response = await client.post(
        f"/api/v1/alerts/{body['id']}/cancel",
        json={"reason": "changed my mind"},
        headers=family.headers(),
    )
    assert response.status_code == 409


async def test_a_viewer_who_did_not_raise_it_cannot_cancel(client, session):
    family = await create_family(client)
    await join(client, family, subject="a-viewer", role="viewer")
    body = await _raise_sos(client, family)

    response = await client.post(
        f"/api/v1/alerts/{body['id']}/cancel",
        json={"reason": "not mine to cancel"},
        headers=auth("a-viewer"),
    )
    assert response.status_code == 403


async def test_an_assistant_can_never_end_an_alert(client, session):
    """Not a configuration choice: the service refuses an AI actor outright."""
    from app.services import alerts as alert_service

    family = await create_family(client)
    body = await _raise_sos(client, family)
    alert = await session.get(Alert, uuid.UUID(body["id"]))
    actor_user_id = alert.raised_by_user_id
    assert actor_user_id is not None

    for action in ("acknowledge", "resolve"):
        with pytest.raises(PermissionDenied) as caught:
            await getattr(alert_service, action)(
                session,
                alert=alert,
                actor_user_id=actor_user_id,
                actor_type=ActorType.AI,
            )
        assert caught.value.code == "ai_cannot_change_alert"

    with pytest.raises(PermissionDenied):
        await alert_service.cancel(
            session,
            alert=alert,
            actor_user_id=actor_user_id,
            reason="the model decided",
            actor_type=ActorType.AI,
        )

    await session.refresh(alert)
    assert alert.status is AlertStatus.RAISED


async def test_another_family_cannot_see_or_touch_an_alert(client):
    family = await create_family(client, owner="owner-a")
    await create_family(client, owner="owner-b", name="Other")
    body = await _raise_sos(client, family)

    for path in ("", "/events"):
        response = await client.get(
            f"/api/v1/alerts/{body['id']}{path}", headers=auth("owner-b")
        )
        # 404, not 403: an outsider must not learn that this alert exists.
        assert response.status_code == 404

    acknowledged = await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("owner-b")
    )
    assert acknowledged.status_code == 404


async def test_the_escalation_job_is_queued_with_the_alert(client, session):
    family = await create_family(client)
    body = await _raise_sos(client, family)

    job = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.ALERT_ESCALATION_CHECK
            )
        )
    ).scalars().one()
    assert job.payload["alert_id"] == body["id"]
    assert job.status is JobStatus.QUEUED
    # Urgent: an unanswered emergency must not queue behind a week of summaries.
    assert job.priority <= 10


async def test_two_presses_are_two_alerts(client, session):
    family = await create_family(client)
    first = await _raise_sos(client, family)
    second = await _raise_sos(client, family)

    assert first["id"] != second["id"]
    count = await session.scalar(select(func.count()).select_from(Alert))
    assert count == 2


async def test_the_history_is_append_only(client, session):
    """Every transition leaves a line nobody has to remember to write."""
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)
    await client.post(
        f"/api/v1/alerts/{body['id']}/acknowledge", json={}, headers=auth("daughter")
    )
    await client.post(
        f"/api/v1/alerts/{body['id']}/resolve", json={}, headers=auth("daughter")
    )

    events = (
        await session.execute(
            select(AlertEvent)
            .where(AlertEvent.alert_id == uuid.UUID(body["id"]))
            .order_by(AlertEvent.occurred_at)
        )
    ).scalars().all()

    assert [event.type for event in events] == [
        AlertEventType.RAISED,
        AlertEventType.DELIVERY_ATTEMPTED,
        AlertEventType.ACKNOWLEDGED,
        AlertEventType.RESOLVED,
    ]
    assert all(event.actor_type is not ActorType.AI for event in events)


async def test_an_sos_notification_points_at_the_alert(client, session):
    """A contract the Family Dashboard depends on.

    Its banner acknowledges the *alert* from the notification it is showing, so
    the notification has to carry the alert's id — otherwise tapping the banner
    would only mark one person's copy read and the escalation would continue.
    """
    from app.models.care import NotificationDelivery

    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)

    rows = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.type == NotificationType.SOS
            )
        )
    ).scalars().all()
    assert rows
    for row in rows:
        assert row.related_entity_type == "alert"
        assert row.related_entity_id == uuid.UUID(body["id"])

    inbox = (await client.get("/api/v1/notifications", headers=auth("daughter"))).json()
    assert inbox[0]["related_entity_id"] == body["id"]
    assert inbox[0]["related_entity_type"] == "alert"


async def test_an_escalation_notification_also_points_at_the_alert(
    client, session, run_worker
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    body = await _raise_sos(client, family)
    alert = await session.get(Alert, uuid.UUID(body["id"]))
    alert.next_escalation_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    await run_worker(JobType.ALERT_ESCALATION_CHECK)

    inbox = (await client.get("/api/v1/notifications", headers=auth("daughter"))).json()
    escalations = [
        row for row in inbox if row["type"] == NotificationType.SOS_ESCALATION.value
    ]
    assert escalations
    assert escalations[0]["related_entity_id"] == body["id"]
    assert escalations[0]["related_entity_type"] == "alert"


async def test_the_sos_timeline_entry_is_written_once(client, session):
    from app.models.care import TimelineEvent
    from app.models.enums import TimelineEventType

    family = await create_family(client)
    body = await _raise_sos(client, family)

    rows = (
        await session.execute(
            select(TimelineEvent).where(
                TimelineEvent.type == TimelineEventType.SOS_TRIGGERED
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].related_entity_id == uuid.UUID(body["id"])
