"""The deterministic care worker.

The behaviour these tests protect is the product's whole reason for existing: a
dose becomes missed because time passed, not because somebody opened a screen,
and the family is told once.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.care import NotificationDelivery, Reminder, TimelineEvent
from app.models.enums import (
    DoseStatus,
    NotificationChannel,
    NotificationType,
    TimelineEventType,
)
from app.models.medication import DoseEvent, MedicationSchedule
from tests.conftest import auth
from tests.factories import (
    add_medication,
    create_family,
    join,
    link_senior_account,
    list_doses,
)


async def _shift_dose_into_the_past(session, senior_id: str, minutes: int) -> DoseEvent:
    """Move the one dose event back in time, and its windows with it.

    Rewriting the row rather than patching a clock keeps the test honest about
    what the handler reads: it looks at ``scheduled_at_utc`` and the schedule's
    own late/missed minutes, and nothing else.
    """
    event = (
        await session.execute(
            select(DoseEvent).where(
                DoseEvent.senior_profile_id == uuid.UUID(senior_id)
            )
        )
    ).scalars().first()
    assert event is not None
    event.scheduled_at_utc = utcnow() - dt.timedelta(minutes=minutes)
    await session.commit()
    return event


async def test_a_get_does_not_create_dose_events(client, session):
    """The regression this whole phase exists to prevent."""
    family = await create_family(client)
    await add_medication(client, family)

    # Deliberately no worker run.
    doses = await list_doses(client, family)
    assert doses == []

    count = await session.scalar(select(func.count()).select_from(DoseEvent))
    assert count == 0


async def test_the_worker_materialises_the_rolling_window(client, session, run_worker):
    family = await create_family(client)
    await add_medication(client, family, local_time="08:00")
    await run_worker()

    events = (
        await session.execute(
            select(DoseEvent).where(
                DoseEvent.senior_profile_id == uuid.UUID(family.senior_id)
            )
        )
    ).scalars().all()

    # Today plus the configured days ahead, and the backfill window behind.
    assert len(events) >= 3
    assert all(event.status is DoseStatus.DUE for event in events)


async def test_materialising_twice_creates_nothing_new(client, session, run_worker):
    family = await create_family(client)
    await add_medication(client, family)
    await run_worker()
    before = await session.scalar(select(func.count()).select_from(DoseEvent))

    await run_worker(JobType.DOSE_MATERIALIZE)
    after = await session.scalar(select(func.count()).select_from(DoseEvent))

    assert after == before


async def test_a_get_reflects_the_status_the_worker_derived(client, session, run_worker):
    family = await create_family(client)
    await add_medication(client, family, late_after_minutes=30, missed_after_minutes=120)
    await run_worker()
    await _shift_dose_into_the_past(session, family.senior_id, minutes=45)

    await run_worker(JobType.DOSE_ADVANCE_STATUS)

    doses = await list_doses(client, family)
    assert [dose["status"] for dose in doses] == ["late"]


async def test_a_missed_dose_produces_exactly_one_timeline_event(
    client, session, run_worker
):
    family = await create_family(client)
    await add_medication(client, family, missed_after_minutes=60)
    await run_worker()
    await _shift_dose_into_the_past(session, family.senior_id, minutes=180)

    # Three sweeps. The dedupe key has to hold across all of them.
    for _ in range(3):
        await run_worker(JobType.DOSE_ADVANCE_STATUS)

    missed = (
        await session.execute(
            select(TimelineEvent).where(
                TimelineEvent.type == TimelineEventType.MEDICATION_MISSED
            )
        )
    ).scalars().all()
    assert len(missed) == 1
    assert missed[0].dedupe_key is not None


async def test_a_missed_dose_notifies_each_member_exactly_once(
    client, session, run_worker
):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    await add_medication(client, family, missed_after_minutes=60)
    await run_worker()
    await _shift_dose_into_the_past(session, family.senior_id, minutes=180)

    for _ in range(3):
        await run_worker(JobType.DOSE_ADVANCE_STATUS)

    for member in ("owner-a", "daughter"):
        rows = (
            await client.get("/api/v1/notifications", headers=auth(member))
        ).json()
        missed = [row for row in rows if row["type"] == "missed_dose"]
        assert len(missed) == 1, member


async def test_a_recorded_dose_is_never_turned_into_a_missed_one(
    client, session, run_worker
):
    family = await create_family(client)
    await add_medication(client, family, missed_after_minutes=60)
    await run_worker()
    dose = (await list_doses(client, family))[0]
    await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken", json={}, headers=family.headers()
    )
    await _shift_dose_into_the_past(session, family.senior_id, minutes=300)

    await run_worker(JobType.DOSE_ADVANCE_STATUS)

    doses = await list_doses(client, family)
    assert doses[0]["status"] == "taken"
    missed = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(TimelineEvent.type == TimelineEventType.MEDICATION_MISSED)
    )
    assert missed == 0


async def test_a_due_dose_reminds_the_person_once(client, session, run_worker):
    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    await link_senior_account(session, family.senior_id, "the-senior")
    await add_medication(client, family)
    await run_worker()
    await _shift_dose_into_the_past(session, family.senior_id, minutes=2)

    for _ in range(3):
        await run_worker(JobType.MEDICATION_REMINDERS)

    rows = (
        await client.get("/api/v1/notifications", headers=auth("the-senior"))
    ).json()
    reminders = [row for row in rows if row["type"] == "medication_reminder"]
    assert len(reminders) == 1
    assert "Metformin" in reminders[0]["title"]

    # The family is told about a *missed* dose, not about every due one.
    family_rows = (
        await client.get("/api/v1/notifications", headers=auth("owner-a"))
    ).json()
    assert [row for row in family_rows if row["type"] == "medication_reminder"] == []


async def test_a_reminded_dose_is_not_reminded_again(client, session, run_worker):
    family = await create_family(client)
    await add_medication(client, family)
    await run_worker()
    event = await _shift_dose_into_the_past(session, family.senior_id, minutes=1)

    await run_worker(JobType.MEDICATION_REMINDERS)
    await session.refresh(event)
    assert event.status is DoseStatus.REMINDED


async def test_a_general_reminder_fires_once_per_occurrence(
    client, session, run_worker
):
    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    await link_senior_account(session, family.senior_id, "the-senior")

    created = await client.post(
        f"/api/v1/seniors/{family.senior_id}/reminders",
        json={"title": "Drink water", "type": "hydration", "local_time": "09:00"},
        headers=family.headers(),
    )
    assert created.status_code == 201

    # Point the reminder at the current local minute so this occurrence is due.
    reminder = await session.get(Reminder, uuid.UUID(created.json()["id"]))
    from app.services.scheduling import load_timezone

    local_now = utcnow().astimezone(load_timezone(reminder.timezone))
    reminder.local_time = local_now.strftime("%H:%M")
    await session.commit()

    for _ in range(3):
        await run_worker(JobType.REMINDER_OCCURRENCES)

    rows = (
        await client.get("/api/v1/notifications", headers=auth("the-senior"))
    ).json()
    assert len([row for row in rows if row["type"] == "reminder"]) == 1


async def test_an_appointment_is_announced_once(client, session, run_worker):
    family = await create_family(client)
    await join(client, family, subject="daughter", role="family")
    starts_at = utcnow() + dt.timedelta(hours=6)
    created = await client.post(
        f"/api/v1/seniors/{family.senior_id}/appointments",
        json={"title": "Cardiology", "starts_at": starts_at.isoformat()},
        headers=family.headers(),
    )
    assert created.status_code == 201

    for _ in range(2):
        await run_worker(JobType.APPOINTMENT_REMINDERS)

    rows = (
        await client.get("/api/v1/notifications", headers=auth("daughter"))
    ).json()
    assert len([row for row in rows if row["type"] == "appointment"]) == 1


async def test_an_archived_medication_stops_producing_doses(
    client, session, run_worker
):
    family = await create_family(client)
    medication = await add_medication(client, family)
    await run_worker()

    await client.post(
        f"/api/v1/medications/{medication['id']}/archive", headers=family.headers()
    )
    before = await session.scalar(select(func.count()).select_from(DoseEvent))
    await run_worker(JobType.DOSE_MATERIALIZE)
    after = await session.scalar(select(func.count()).select_from(DoseEvent))

    assert after == before


async def test_a_paused_schedule_stops_producing_doses(client, session, run_worker):
    family = await create_family(client)
    medication = await add_medication(client, family)
    schedule_id = medication["schedules"][0]["id"]

    schedule = await session.get(MedicationSchedule, uuid.UUID(schedule_id))
    from app.models.enums import ScheduleStatus

    schedule.status = ScheduleStatus.PAUSED
    await session.commit()

    await run_worker(JobType.DOSE_MATERIALIZE)
    assert await session.scalar(select(func.count()).select_from(DoseEvent)) == 0


async def test_every_notification_has_an_explicit_channel(
    client, session, run_worker
):
    """No row is allowed to be ambiguous about what reached whom."""
    family = await create_family(client)
    await add_medication(client, family, missed_after_minutes=60)
    await run_worker()
    await _shift_dose_into_the_past(session, family.senior_id, minutes=180)
    await run_worker(JobType.DOSE_ADVANCE_STATUS)

    rows = (
        await session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.type == NotificationType.MISSED_DOSE
            )
        )
    ).scalars().all()

    channels = {row.channel for row in rows}
    assert channels == {NotificationChannel.IN_APP, NotificationChannel.PUSH}
    for row in rows:
        if row.channel is NotificationChannel.IN_APP:
            # Visible in the app, and not claiming to be anything more.
            assert row.sent_at is not None
            assert row.delivered_at is None
