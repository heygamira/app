"""The first working milestone, end to end.

A family member creates a medication schedule, the worker materialises the
day's doses, the dose is recorded as taken, and the Family Dashboard's timeline
shows it.

``GET /doses`` no longer generates anything — that is the worker's job now — so
every test here runs the worker after creating a medication, exactly as the
running system does.
"""

from __future__ import annotations

import datetime as dt

from tests.conftest import auth


async def _setup(client, timezone: str = "Asia/Kolkata") -> tuple[str, str]:
    family = await client.post(
        "/api/v1/families", json={"name": "Sharma"}, headers=auth("owner-a")
    )
    family_id = family.json()["id"]
    senior = await client.post(
        f"/api/v1/families/{family_id}/seniors",
        json={"preferred_name": "Vikram", "timezone": timezone},
        headers=auth("owner-a"),
    )
    return family_id, senior.json()["id"]


async def test_the_full_medication_care_loop(client, run_worker):
    _, senior_id = await _setup(client)

    created = await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={
            "name": "Amlodipine",
            "strength": "5 mg",
            "schedules": [{"local_time": "08:00", "dose_quantity": "1 tablet"}],
        },
        headers=auth("owner-a"),
    )
    assert created.status_code == 201
    medication = created.json()
    # Creating a medication asks the worker for this person's doses. Nothing
    # exists until it has run.
    assert await run_worker() >= 1
    assert len(medication["schedules"]) == 1
    # A schedule without an explicit zone inherits the senior's.
    assert medication["schedules"][0]["timezone"] == "Asia/Kolkata"

    doses = await client.get(
        f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a")
    )
    assert doses.status_code == 200
    assert len(doses.json()) == 1
    dose = doses.json()[0]
    assert dose["medication_name"] == "Amlodipine"
    assert dose["scheduled_local_time"] == "08:00"

    taken = await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken",
        json={"source": "parent_app"},
        headers=auth("owner-a"),
    )
    assert taken.status_code == 200
    assert taken.json()["status"] == "taken"
    assert taken.json()["recorded_at"] is not None

    timeline = await client.get(
        f"/api/v1/seniors/{senior_id}/timeline", headers=auth("owner-a")
    )
    types = [event["type"] for event in timeline.json()]
    assert "medication_taken" in types


async def test_listing_doses_twice_does_not_duplicate_them(client, run_worker):
    _, senior_id = await _setup(client)
    await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={
            "name": "Amlodipine",
            "schedules": [{"local_time": "08:00"}, {"local_time": "20:00"}],
        },
        headers=auth("owner-a"),
    )
    await run_worker()

    first = await client.get(
        f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a")
    )
    second = await client.get(
        f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a")
    )

    assert len(first.json()) == 2
    assert [d["id"] for d in first.json()] == [d["id"] for d in second.json()]


async def test_recording_the_same_dose_twice_is_idempotent(client, run_worker):
    _, senior_id = await _setup(client)
    await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={"name": "Amlodipine", "schedules": [{"local_time": "08:00"}]},
        headers=auth("owner-a"),
    )
    await run_worker()
    dose = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a"))
    ).json()[0]

    headers = {**auth("owner-a"), "Idempotency-Key": "tap-12345"}
    first = await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken", json={}, headers=headers
    )
    second = await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken", json={}, headers=headers
    )

    assert first.json()["recorded_at"] == second.json()["recorded_at"]

    timeline = await client.get(
        f"/api/v1/seniors/{senior_id}/timeline", headers=auth("owner-a")
    )
    taken_events = [e for e in timeline.json() if e["type"] == "medication_taken"]
    assert len(taken_events) == 1


async def test_a_recorded_dose_is_not_re_derived_as_missed(
    client, session, run_worker
):
    """A dose the senior confirmed stays confirmed once its window elapses."""
    from app.services.doses import apply_time_derived_status

    _, senior_id = await _setup(client)
    await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={"name": "Amlodipine", "schedules": [{"local_time": "08:00"}]},
        headers=auth("owner-a"),
    )
    await run_worker()
    dose = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a"))
    ).json()[0]
    await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken", json={}, headers=auth("owner-a")
    )

    import uuid as uuid_module

    from app.services.doses import get_dose_event

    event = await get_dose_event(session, uuid_module.UUID(dose["id"]))
    changed = apply_time_derived_status(
        event, now=event.scheduled_at_utc.replace(tzinfo=dt.UTC) + dt.timedelta(days=1)
    )

    assert changed is False
    assert event.status.value == "taken"


async def test_an_unacknowledged_dose_becomes_late_then_missed(
    client, session, run_worker
):
    import uuid as uuid_module

    from app.services.doses import apply_time_derived_status, get_dose_event

    _, senior_id = await _setup(client)
    await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={
            "name": "Amlodipine",
            "schedules": [
                {
                    "local_time": "08:00",
                    "late_after_minutes": 30,
                    "missed_after_minutes": 120,
                }
            ],
        },
        headers=auth("owner-a"),
    )
    await run_worker()
    dose = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a"))
    ).json()[0]
    event = await get_dose_event(session, uuid_module.UUID(dose["id"]))
    scheduled = event.scheduled_at_utc.replace(tzinfo=dt.UTC)

    apply_time_derived_status(event, now=scheduled + dt.timedelta(minutes=45))
    assert event.status.value == "late"

    apply_time_derived_status(event, now=scheduled + dt.timedelta(minutes=180))
    assert event.status.value == "missed"


async def test_archiving_a_medication_cancels_only_future_doses(client, run_worker):
    _, senior_id = await _setup(client)
    medication = (
        await client.post(
            f"/api/v1/seniors/{senior_id}/medications",
            json={
                "name": "Amlodipine",
                "schedules": [{"local_time": "00:30"}, {"local_time": "23:30"}],
            },
            headers=auth("owner-a"),
        )
    ).json()
    await run_worker()
    doses_before = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a"))
    ).json()
    assert len(doses_before) == 2

    archived = await client.post(
        f"/api/v1/medications/{medication['id']}/archive", headers=auth("owner-a")
    )
    assert archived.json()["status"] == "archived"

    after = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("owner-a"))
    ).json()
    # Past occurrences keep their recorded status; only future ones are cancelled.
    now = dt.datetime.now(dt.UTC)
    for dose in after:
        scheduled = dt.datetime.fromisoformat(dose["scheduled_at_utc"])
        if scheduled > now:
            assert dose["status"] == "cancelled"
