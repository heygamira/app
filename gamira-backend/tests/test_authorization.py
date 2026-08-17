"""Cross-family access must fail, and read-only roles must not write."""

from __future__ import annotations

import uuid

from tests.conftest import auth


async def _family_with_senior(client, subject: str, name: str) -> tuple[str, str]:
    family = await client.post(
        "/api/v1/families", json={"name": name}, headers=auth(subject)
    )
    family_id = family.json()["id"]
    senior = await client.post(
        f"/api/v1/families/{family_id}/seniors",
        json={"preferred_name": f"{name} senior", "timezone": "Asia/Kolkata"},
        headers=auth(subject),
    )
    return family_id, senior.json()["id"]


async def test_first_user_becomes_owner_of_their_family(client):
    response = await client.post(
        "/api/v1/families", json={"name": "Sharma"}, headers=auth("owner-a")
    )
    assert response.status_code == 201

    me = await client.get("/api/v1/me", headers=auth("owner-a"))
    body = me.json()
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["role"] == "owner"


async def test_another_family_cannot_read_a_senior(client):
    _, senior_id = await _family_with_senior(client, "owner-a", "Family A")
    await _family_with_senior(client, "owner-b", "Family B")

    response = await client.get(f"/api/v1/seniors/{senior_id}", headers=auth("owner-b"))

    # 404, not 403: an outsider must not learn that this id exists.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_another_family_cannot_write_medications(client):
    _, senior_id = await _family_with_senior(client, "owner-a", "Family A")
    await _family_with_senior(client, "owner-b", "Family B")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={"name": "Amlodipine"},
        headers=auth("owner-b"),
    )

    assert response.status_code == 404


async def test_me_only_lists_the_callers_own_families(client):
    await _family_with_senior(client, "owner-a", "Family A")
    await _family_with_senior(client, "owner-b", "Family B")

    body = (await client.get("/api/v1/me", headers=auth("owner-a"))).json()

    assert [family["name"] for family in body["families"]] == ["Family A"]
    assert len(body["seniors"]) == 1


async def test_invited_viewer_can_read_but_not_write(client):
    family_id, senior_id = await _family_with_senior(client, "owner-a", "Family A")

    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "viewer"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]
    accepted = await client.post(
        f"/api/v1/invitations/{token}/accept", headers=auth("viewer-a")
    )
    assert accepted.status_code == 200

    readable = await client.get(
        f"/api/v1/seniors/{senior_id}/medications", headers=auth("viewer-a")
    )
    assert readable.status_code == 200

    write = await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={"name": "Amlodipine"},
        headers=auth("viewer-a"),
    )
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "permission_denied"


async def test_a_senior_can_confirm_their_own_dose_while_read_only(
    client, session, run_worker
):
    """The cared-for person must always be able to record their own dose.

    A senior is a viewer in their family — they do not administer other
    people's care — but the Parent App is their own device.
    """
    from sqlalchemy import select

    from app.models.identity import SeniorProfile, User

    family_id, senior_id = await _family_with_senior(client, "owner-a", "Family A")

    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "viewer"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]
    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth("the-senior"))

    # Link the viewer to the senior profile, as an assisted setup would.
    senior_user = (
        await session.execute(
            select(User).where(User.external_auth_id == "dev|the-senior")
        )
    ).scalar_one()
    senior = await session.get(SeniorProfile, uuid.UUID(senior_id))
    senior.user_id = senior_user.id
    await session.commit()

    await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={"name": "Amlodipine", "schedules": [{"local_time": "08:00"}]},
        headers=auth("owner-a"),
    )
    await run_worker()
    dose = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("the-senior"))
    ).json()[0]

    response = await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken",
        json={"source": "parent_app"},
        headers=auth("the-senior"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "taken"


async def test_an_unrelated_viewer_still_cannot_record_a_dose(client, run_worker):
    family_id, senior_id = await _family_with_senior(client, "owner-a", "Family A")
    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "viewer"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]
    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth("viewer-a"))

    await client.post(
        f"/api/v1/seniors/{senior_id}/medications",
        json={"name": "Amlodipine", "schedules": [{"local_time": "08:00"}]},
        headers=auth("owner-a"),
    )
    await run_worker()
    dose = (
        await client.get(f"/api/v1/seniors/{senior_id}/doses", headers=auth("viewer-a"))
    ).json()[0]

    response = await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken", json={}, headers=auth("viewer-a")
    )

    assert response.status_code == 403


async def test_a_senior_can_record_their_own_health_reading(client, session):
    """A watch paired to the wearer's own account may record the wearer.

    Same reasoning as the dose above: the device belongs to the person it is
    measuring. Recording somebody else still needs a write role.
    """
    from sqlalchemy import select

    from app.models.identity import SeniorProfile, User

    family_id, senior_id = await _family_with_senior(client, "owner-a", "Family A")
    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "viewer"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]
    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth("the-senior"))

    senior_user = (
        await session.execute(
            select(User).where(User.external_auth_id == "dev|the-senior")
        )
    ).scalar_one()
    senior = await session.get(SeniorProfile, uuid.UUID(senior_id))
    senior.user_id = senior_user.id
    await session.commit()

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/health-readings",
        json={
            "metric": "heart_rate",
            "value": 132,
            "unit": "bpm",
            "source": "device",
            "source_device": "Gamira Watch",
            "measured_at": "2026-01-01T08:00:00Z",
        },
        headers=auth("the-senior"),
    )

    assert response.status_code == 201
    # Recorded exactly as measured. The backend does not label 132 bpm.
    assert response.json()["value"] == 132

    # A device stream stays out of the timeline, which is for the family's day.
    timeline = (
        await client.get(f"/api/v1/seniors/{senior_id}/timeline", headers=auth("owner-a"))
    ).json()
    assert "health_reading_added" not in [event["type"] for event in timeline]


async def test_an_unrelated_viewer_cannot_record_a_health_reading(client):
    family_id, senior_id = await _family_with_senior(client, "owner-a", "Family A")
    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "viewer"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]
    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth("viewer-a"))

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/health-readings",
        json={
            "metric": "heart_rate",
            "value": 72,
            "unit": "bpm",
            "measured_at": "2026-01-01T08:00:00Z",
        },
        headers=auth("viewer-a"),
    )

    assert response.status_code == 403


async def test_an_invitation_cannot_be_accepted_twice(client):
    family_id, _ = await _family_with_senior(client, "owner-a", "Family A")
    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "family"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]

    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth("member-a"))
    replay = await client.post(
        f"/api/v1/invitations/{token}/accept", headers=auth("member-b")
    )

    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "invitation_not_pending"


async def test_the_raw_invitation_token_is_not_stored(client, session):
    from sqlalchemy import select

    from app.models.identity import FamilyInvitation

    family_id, _ = await _family_with_senior(client, "owner-a", "Family A")
    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": "family"},
        headers=auth("owner-a"),
    )
    token = invitation.json()["token"]

    stored = (await session.execute(select(FamilyInvitation))).scalars().all()

    assert len(stored) == 1
    assert stored[0].token_hash != token
    assert token not in stored[0].token_hash
