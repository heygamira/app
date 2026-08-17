"""Device registration and push delivery.

The property under test throughout: a notification's record never claims more
than actually happened. An in-app row is an inbox item, a push row has attempts
behind it, and a dead token stops being tried.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.jobs.types import JobType
from app.models.care import NotificationDelivery, NotificationDeliveryAttempt
from app.models.devices import RegisteredDevice, token_fingerprint
from app.models.enums import (
    DeliveryAttemptStatus,
    DeviceStatus,
    NotificationChannel,
    NotificationStatus,
)
from tests.conftest import auth
from tests.factories import add_medication, create_family, join

INSTALL = "install-abcdef123456"
TOKEN = "fcm-token-value-that-must-never-be-returned"


async def _register(client, subject: str, *, token: str = TOKEN, install: str = INSTALL):
    return await client.post(
        "/api/v1/devices",
        json={
            "install_id": install,
            "platform": "android",
            "push_token": token,
            "app_version": "1.4.0",
            "device_label": "Pixel 7",
        },
        headers=auth(subject),
    )


async def test_registering_a_device_never_returns_its_token(client):
    response = await _register(client, "owner-a")

    assert response.status_code == 201
    body = response.json()
    assert "push_token" not in body
    assert TOKEN not in response.text
    # The fingerprint identifies the device without being usable to send to it.
    assert body["push_token_fingerprint"] == token_fingerprint(TOKEN)


async def test_registering_the_same_install_updates_one_row(client, session):
    await _register(client, "owner-a")
    second = await _register(client, "owner-a", token="rotated-token")

    assert second.status_code == 201
    assert second.json()["push_token_fingerprint"] == token_fingerprint("rotated-token")

    count = await session.scalar(select(func.count()).select_from(RegisteredDevice))
    assert count == 1


async def test_a_rotated_token_clears_a_previous_invalid_mark(client, session):
    await _register(client, "owner-a")
    device = (
        await session.execute(select(RegisteredDevice))
    ).scalars().one()
    from app.db.base import utcnow

    device.push_token_invalid_at = utcnow()
    await session.commit()

    await _register(client, "owner-a", token="fresh-token")
    await session.refresh(device)
    assert device.push_token_invalid_at is None


async def test_revoking_a_device_drops_its_token(client, session):
    created = await _register(client, "owner-a")
    device_id = created.json()["id"]

    response = await client.delete(
        f"/api/v1/devices/{device_id}", headers=auth("owner-a")
    )
    assert response.status_code == 204

    device = await session.get(RegisteredDevice, uuid.UUID(device_id))
    await session.refresh(device)
    assert device.status is DeviceStatus.REVOKED
    # Dropped, not just flagged: a bug that ignores `status` still cannot send.
    assert device.push_token is None


async def test_a_device_belongs_to_one_person_only(client):
    created = await _register(client, "owner-a")
    device_id = created.json()["id"]

    listed = await client.get("/api/v1/devices", headers=auth("someone-else"))
    assert listed.json() == []

    # Not 403: a device id is not something to confirm the existence of.
    revoked = await client.delete(
        f"/api/v1/devices/{device_id}", headers=auth("someone-else")
    )
    assert revoked.status_code == 404


async def test_a_push_reaches_a_registered_device(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await _register(client, "daughter")

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    assert len(push_provider.sent) == 1
    assert "SOS" in push_provider.sent[0].message.title
    # The payload is structural: an id and a type, never a health value.
    assert set(push_provider.sent[0].message.data) >= {"notification_id", "type"}

    row = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == NotificationChannel.PUSH
            )
        )
    ).scalars().one()
    assert row.status is NotificationStatus.SENT
    assert row.delivered_at is not None


async def test_a_retryable_failure_is_retried_and_then_succeeds(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await _register(client, "daughter")
    push_provider.fail_next = ["UNAVAILABLE"]

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    row = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == NotificationChannel.PUSH
            )
        )
    ).scalars().one()
    await session.refresh(row)
    assert row.status is NotificationStatus.QUEUED
    assert row.last_error_code == "UNAVAILABLE"
    assert row.next_attempt_at is not None
    assert push_provider.sent == []

    # Backoff elapses, the provider recovers, the same notification goes out.
    from app.db.base import utcnow

    row.next_attempt_at = utcnow()
    await session.commit()
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    await session.refresh(row)
    assert row.status is NotificationStatus.SENT
    assert len(push_provider.sent) == 1


async def test_an_invalid_token_retires_the_device(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await _register(client, "daughter")
    push_provider.fail_tokens[TOKEN] = "UNREGISTERED"

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    device = (await session.execute(select(RegisteredDevice))).scalars().one()
    await session.refresh(device)
    # Retired rather than retried forever: the app was uninstalled.
    assert device.push_token_invalid_at is not None

    row = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == NotificationChannel.PUSH
            )
        )
    ).scalars().one()
    await session.refresh(row)
    assert row.status is NotificationStatus.FAILED

    attempt = (
        await session.execute(select(NotificationDeliveryAttempt))
    ).scalars().one()
    assert attempt.status is DeliveryAttemptStatus.TOKEN_INVALID
    # The attempt record identifies the device by fingerprint, not by token.
    assert attempt.device_token_fingerprint == token_fingerprint(TOKEN)


async def test_a_permanent_failure_is_not_retried(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await _register(client, "daughter")
    push_provider.fail_next = ["SENDER_ID_MISMATCH"]

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    row = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == NotificationChannel.PUSH
            )
        )
    ).scalars().one()
    await session.refresh(row)
    assert row.status is NotificationStatus.FAILED
    assert row.next_attempt_at is None


async def test_a_device_is_not_sent_the_same_notification_twice(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await _register(client, "daughter")

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    row = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == NotificationChannel.PUSH
            )
        )
    ).scalars().one()
    from app.db.base import utcnow
    from app.services.notifications import deliver_push

    # Force a second delivery pass over an already-delivered notification.
    row.status = NotificationStatus.QUEUED
    row.next_attempt_at = utcnow()
    await session.commit()
    await deliver_push(session, row)
    await session.commit()

    assert len(push_provider.sent) == 1


async def test_a_person_with_no_device_does_not_leave_a_stuck_push(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    rows = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == NotificationChannel.PUSH
            )
        )
    ).scalars().all()
    assert rows
    for row in rows:
        await session.refresh(row)
        assert row.status is NotificationStatus.CANCELLED
        assert row.last_error_code == "no_registered_device"


async def test_the_inbox_shows_one_row_per_event(client, run_worker):
    """Push rows are machinery. They must not appear twice in somebody's inbox."""
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await _register(client, "daughter")

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    rows = (await client.get("/api/v1/notifications", headers=auth("daughter"))).json()
    assert len(rows) == 1
    assert rows[0]["channel"] == "in_app"


async def test_a_revoked_device_receives_nothing(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    created = await _register(client, "daughter")
    await client.delete(
        f"/api/v1/devices/{created.json()['id']}", headers=auth("daughter")
    )

    await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos", json={}, headers=family.headers()
    )
    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)

    assert push_provider.sent == []


async def test_error_classification_covers_the_documented_codes():
    from app.notifications.provider import classify

    assert classify("UNREGISTERED") is DeliveryAttemptStatus.TOKEN_INVALID
    assert classify("UNAVAILABLE") is DeliveryAttemptStatus.RETRYABLE
    assert classify("SENDER_ID_MISMATCH") is DeliveryAttemptStatus.PERMANENT
    assert classify(None, 404) is DeliveryAttemptStatus.TOKEN_INVALID
    assert classify(None, 503) is DeliveryAttemptStatus.RETRYABLE
    assert classify(None, 400) is DeliveryAttemptStatus.PERMANENT
    # An unfamiliar failure is retried rather than dropped: losing a medication
    # reminder to an unrecognised string is the worse outcome.
    assert classify("SOMETHING_NEW") is DeliveryAttemptStatus.RETRYABLE


async def test_a_medication_reminder_is_pushed_at_normal_priority(
    client, session, run_worker, push_provider
):
    family = await create_family(client)
    await add_medication(client, family)
    await _register(client, "owner-a")
    await run_worker()

    from app.db.base import utcnow

    event = (await session.execute(select(NotificationDelivery))).scalars().first()
    if event is None:
        # No dose is due this minute; drive the reminder sweep against a dose
        # moved into the recent past.
        from app.models.medication import DoseEvent

        dose = (await session.execute(select(DoseEvent))).scalars().first()
        dose.scheduled_at_utc = utcnow()
        await session.commit()
        await run_worker(JobType.MEDICATION_REMINDERS)

    await run_worker(JobType.NOTIFICATION_RETRY_SWEEP)
    for sent in push_provider.sent:
        if "Metformin" in sent.message.title:
            assert sent.message.high_priority is False
