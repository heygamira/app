"""A device flag reaches the family — as a notice, never as an emergency."""

from __future__ import annotations

from tests.conftest import auth
from tests.test_sos import _family, _join, _link

FLAG = {
    "metric": "heart_rate",
    "value": 138,
    "unit": "bpm",
    "reason": "Above the upper limit of 110 bpm set on the watch.",
    "source_device": "Gamira Watch",
    "measured_at": "2026-01-01T08:00:00Z",
}


async def test_a_watch_flag_notifies_the_rest_of_the_family(client, session):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "the-senior", "viewer")
    await _join(client, family_id, "daughter", "family")
    await _link(session, senior_id, "the-senior")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/device-flags",
        json=FLAG,
        headers=auth("the-senior"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["delivery"] == "in_app_only"
    assert len(body["notified_user_ids"]) == 2

    alerts = (await client.get("/api/v1/notifications", headers=auth("owner-a"))).json()
    # A notice, not an alarm: an SOS is the only thing allowed to be an SOS.
    assert [alert["type"] for alert in alerts] == ["family_update"]
    assert "Gamira Watch flagged a reading" in alerts[0]["title"]
    assert "Gamira has not assessed this reading." in alerts[0]["body"]

    own = (await client.get("/api/v1/notifications", headers=auth("the-senior"))).json()
    assert own == []


async def test_a_flag_does_not_appear_on_the_timeline(client, session):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "the-senior", "viewer")
    await _link(session, senior_id, "the-senior")

    await client.post(
        f"/api/v1/seniors/{senior_id}/device-flags",
        json=FLAG,
        headers=auth("the-senior"),
    )

    timeline = (
        await client.get(f"/api/v1/seniors/{senior_id}/timeline", headers=auth("owner-a"))
    ).json()
    assert [event["type"] for event in timeline] == ["member_joined"]


async def test_another_family_cannot_flag_a_reading(client):
    _, senior_id = await _family(client, owner="owner-a")
    await _family(client, owner="owner-b")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/device-flags", json=FLAG, headers=auth("owner-b")
    )

    assert response.status_code == 404


async def test_a_viewer_who_is_not_the_person_cannot_flag_a_reading(client):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "viewer-a", "viewer")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/device-flags", json=FLAG, headers=auth("viewer-a")
    )

    assert response.status_code == 403
