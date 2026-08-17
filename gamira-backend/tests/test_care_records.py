"""Health readings, reminders and notification ownership."""

from __future__ import annotations

import datetime as dt

from tests.conftest import auth


async def _senior(client) -> str:
    family = await client.post(
        "/api/v1/families", json={"name": "Sharma"}, headers=auth("owner-a")
    )
    senior = await client.post(
        f"/api/v1/families/{family.json()['id']}/seniors",
        json={"preferred_name": "Vikram", "timezone": "Asia/Kolkata"},
        headers=auth("owner-a"),
    )
    return senior.json()["id"]


async def test_a_health_reading_is_stored_with_its_unit(client):
    senior_id = await _senior(client)

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/health-readings",
        json={
            "metric": "heart_rate",
            "value": 72,
            "unit": "bpm",
            "measured_at": dt.datetime.now(dt.UTC).isoformat(),
        },
        headers=auth("owner-a"),
    )

    assert response.status_code == 201
    assert response.json()["unit"] == "bpm"


async def test_a_mismatched_unit_is_refused(client):
    senior_id = await _senior(client)

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/health-readings",
        json={
            "metric": "heart_rate",
            "value": 72,
            "unit": "mmHg",
            "measured_at": dt.datetime.now(dt.UTC).isoformat(),
        },
        headers=auth("owner-a"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_unit"


async def test_an_implausible_value_is_refused(client):
    senior_id = await _senior(client)

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/health-readings",
        json={
            "metric": "oxygen_saturation",
            "value": 140,
            "unit": "%",
            "measured_at": dt.datetime.now(dt.UTC).isoformat(),
        },
        headers=auth("owner-a"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "value_out_of_range"


async def test_a_future_measurement_is_refused(client):
    senior_id = await _senior(client)
    tomorrow = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/health-readings",
        json={
            "metric": "heart_rate",
            "value": 72,
            "unit": "bpm",
            "measured_at": tomorrow.isoformat(),
        },
        headers=auth("owner-a"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "measured_at_in_future"


async def test_completing_a_reminder_writes_a_timeline_entry(client):
    senior_id = await _senior(client)
    reminder = await client.post(
        f"/api/v1/seniors/{senior_id}/reminders",
        json={"title": "Drink water", "type": "hydration", "local_time": "11:00"},
        headers=auth("owner-a"),
    )

    updated = await client.patch(
        f"/api/v1/reminders/{reminder.json()['id']}",
        json={"status": "completed"},
        headers=auth("owner-a"),
    )

    assert updated.json()["last_completed_at"] is not None
    timeline = await client.get(
        f"/api/v1/seniors/{senior_id}/timeline", headers=auth("owner-a")
    )
    assert "reminder_completed" in [event["type"] for event in timeline.json()]


async def test_notifications_are_scoped_to_the_caller(client, session):
    from sqlalchemy import select

    from app.models.care import NotificationDelivery
    from app.models.enums import NotificationType
    from app.models.identity import User

    await _senior(client)
    await client.get("/api/v1/me", headers=auth("someone-else"))

    owner = (
        await session.execute(select(User).where(User.external_auth_id == "dev|owner-a"))
    ).scalar_one()
    session.add(
        NotificationDelivery(
            user_id=owner.id,
            type=NotificationType.FAMILY_UPDATE,
            title="Only for the owner",
            dedupe_key="test-1",
        )
    )
    await session.commit()

    mine = await client.get("/api/v1/notifications", headers=auth("owner-a"))
    theirs = await client.get("/api/v1/notifications", headers=auth("someone-else"))

    assert len(mine.json()) == 1
    assert theirs.json() == []
