"""An SOS press must reach the rest of the family, and nobody else."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.identity import SeniorProfile, User
from tests.conftest import auth


async def _family(client, owner: str = "owner-a") -> tuple[str, str]:
    family = await client.post(
        "/api/v1/families", json={"name": "Family A"}, headers=auth(owner)
    )
    family_id = family.json()["id"]
    senior = await client.post(
        f"/api/v1/families/{family_id}/seniors",
        json={"preferred_name": "Vikram", "timezone": "Asia/Kolkata"},
        headers=auth(owner),
    )
    return family_id, senior.json()["id"]


async def _join(client, family_id: str, subject: str, role: str, owner: str = "owner-a"):
    invitation = await client.post(
        f"/api/v1/families/{family_id}/invitations",
        json={"role": role},
        headers=auth(owner),
    )
    token = invitation.json()["token"]
    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth(subject))


async def _link(session, senior_id: str, subject: str) -> None:
    """Link a signed-in account to the senior profile, as assisted setup does."""
    user = (
        await session.execute(
            select(User).where(User.external_auth_id == f"dev|{subject}")
        )
    ).scalar_one()
    senior = await session.get(SeniorProfile, uuid.UUID(senior_id))
    senior.user_id = user.id
    await session.commit()


async def test_a_senior_raises_their_own_sos_and_the_family_is_notified(client, session):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "the-senior", "viewer")
    await _join(client, family_id, "daughter", "family")
    await _link(session, senior_id, "the-senior")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/sos",
        json={"source": "parent_app"},
        headers=auth("the-senior"),
    )

    assert response.status_code == 201
    body = response.json()
    # The response never claims more than Gamira does: an in-app alert.
    assert body["delivery"] == "in_app_only"
    assert len(body["notified_user_ids"]) == 2  # owner and daughter, not the raiser

    for member in ("owner-a", "daughter"):
        alerts = (await client.get("/api/v1/notifications", headers=auth(member))).json()
        assert [alert["type"] for alert in alerts] == ["sos"]
        assert alerts[0]["related_entity_id"] == body["id"]

    own = (await client.get("/api/v1/notifications", headers=auth("the-senior"))).json()
    assert own == []

    timeline = (
        await client.get(f"/api/v1/seniors/{senior_id}/timeline", headers=auth("owner-a"))
    ).json()
    assert timeline[0]["type"] == "sos_triggered"


async def test_a_watch_press_is_recorded_with_its_source(client, session):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "the-senior", "viewer")
    await _link(session, senior_id, "the-senior")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/sos",
        json={"source": "watch", "note": "Fell in the kitchen"},
        headers=auth("the-senior"),
    )

    assert response.status_code == 201
    assert response.json()["source"] == "watch"
    alerts = (await client.get("/api/v1/notifications", headers=auth("owner-a"))).json()
    assert alerts[0]["body"] == "Fell in the kitchen"


async def test_two_presses_raise_two_separate_alerts(client, session):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "the-senior", "viewer")
    await _link(session, senior_id, "the-senior")

    first = await client.post(
        f"/api/v1/seniors/{senior_id}/sos", json={}, headers=auth("the-senior")
    )
    second = await client.post(
        f"/api/v1/seniors/{senior_id}/sos", json={}, headers=auth("the-senior")
    )

    assert first.json()["id"] != second.json()["id"]
    alerts = (await client.get("/api/v1/notifications", headers=auth("owner-a"))).json()
    assert len(alerts) == 2


async def test_another_family_cannot_raise_an_sos(client):
    _, senior_id = await _family(client, owner="owner-a")
    await _family(client, owner="owner-b")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/sos", json={}, headers=auth("owner-b")
    )

    # 404, not 403: an outsider must not learn that this person exists.
    assert response.status_code == 404


async def test_a_viewer_who_is_not_the_person_cannot_raise_an_sos(client):
    family_id, senior_id = await _family(client)
    await _join(client, family_id, "viewer-a", "viewer")

    response = await client.post(
        f"/api/v1/seniors/{senior_id}/sos", json={}, headers=auth("viewer-a")
    )

    assert response.status_code == 403
