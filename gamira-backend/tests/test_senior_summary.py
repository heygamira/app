"""GET /seniors/{id}/summary: one request standing in for four.

The property under test is exact equivalence with the four endpoints it
replaces (doses, reminders, emergency contacts, pending wellbeing checks) —
this is a fan-in, not a reimplementation, and should never drift from them.
"""

from __future__ import annotations

from tests.factories import add_medication, create_family


async def _reminder(client, family):
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/reminders",
        json={"title": "Drink water", "type": "hydration", "local_time": "11:00"},
        headers=family.headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _contact(client, family):
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/emergency-contacts",
        json={"name": "Priya", "phone": "+919812345678", "is_primary": True},
        headers=family.headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _device_flag(client, family):
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/device-flags",
        json={
            "metric": "heart_rate",
            "value": 138,
            "unit": "bpm",
            "reason": "Above the upper limit of 110 bpm set on the watch.",
            "source_device": "Gamira Watch",
            "measured_at": "2026-01-01T08:00:00Z",
        },
        headers=family.headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_summary_matches_the_four_endpoints_it_replaces(client, run_worker):
    family = await create_family(client)
    await add_medication(client, family)
    await run_worker()
    await _reminder(client, family)
    await _contact(client, family)
    await _device_flag(client, family)

    doses = await client.get(
        f"/api/v1/seniors/{family.senior_id}/doses", headers=family.headers()
    )
    reminders = await client.get(
        f"/api/v1/seniors/{family.senior_id}/reminders", headers=family.headers()
    )
    contacts = await client.get(
        f"/api/v1/seniors/{family.senior_id}/emergency-contacts",
        headers=family.headers(),
    )
    checks = await client.get(
        f"/api/v1/seniors/{family.senior_id}/wellbeing-checks",
        headers=family.headers(),
    )
    summary = await client.get(
        f"/api/v1/seniors/{family.senior_id}/summary", headers=family.headers()
    )

    assert summary.status_code == 200, summary.text
    body = summary.json()
    # Every list is non-empty, so an accidentally-swapped or dropped field
    # would show up as a real mismatch below, not two empty lists agreeing.
    assert doses.json() != []
    assert reminders.json() != []
    assert contacts.json() != []
    assert checks.json() != []

    assert body["doses"] == doses.json()
    assert body["reminders"] == reminders.json()
    assert body["emergency_contacts"] == contacts.json()
    assert body["wellbeing_checks"] == checks.json()


async def test_the_summary_is_scoped_to_its_own_senior(client):
    family_a = await create_family(client, owner="owner-a", senior_name="Vikram")
    family_b = await create_family(client, owner="owner-b", senior_name="Sunita")
    await _reminder(client, family_a)
    await _reminder(client, family_b)

    summary = await client.get(
        f"/api/v1/seniors/{family_a.senior_id}/summary", headers=family_a.headers()
    )
    assert summary.status_code == 200, summary.text
    assert len(summary.json()["reminders"]) == 1


async def test_a_stranger_cannot_read_another_familys_summary(client):
    family = await create_family(client, owner="owner-a")
    other = await create_family(client, owner="owner-b")

    response = await client.get(
        f"/api/v1/seniors/{family.senior_id}/summary", headers=other.headers()
    )
    assert response.status_code == 404
