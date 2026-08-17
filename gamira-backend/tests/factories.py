"""Shared setup for the newer test modules.

Everything goes through the API rather than the ORM wherever it can, so a test
exercises the same authorization path a real client does. The two exceptions —
linking a senior to a signed-in account, and revoking a membership mid-test —
are states no endpoint produces on demand.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.models.enums import MembershipStatus
from app.models.identity import FamilyMembership, SeniorProfile, User
from tests.conftest import auth


@dataclass
class Family:
    family_id: str
    senior_id: str
    owner: str

    def headers(self, subject: str | None = None) -> dict[str, str]:
        return auth(subject or self.owner)


async def create_family(
    client,
    *,
    owner: str = "owner-a",
    name: str = "Sharma",
    senior_name: str = "Vikram",
    timezone: str = "Asia/Kolkata",
) -> Family:
    family = await client.post(
        "/api/v1/families", json={"name": name}, headers=auth(owner)
    )
    family_id = family.json()["id"]
    senior = await client.post(
        f"/api/v1/families/{family_id}/seniors",
        json={"preferred_name": senior_name, "timezone": timezone},
        headers=auth(owner),
    )
    return Family(family_id=family_id, senior_id=senior.json()["id"], owner=owner)


async def join(
    client, family: Family, *, subject: str, role: str = "family"
) -> str:
    invitation = await client.post(
        f"/api/v1/families/{family.family_id}/invitations",
        json={"role": role},
        headers=auth(family.owner),
    )
    token = invitation.json()["token"]
    await client.post(f"/api/v1/invitations/{token}/accept", headers=auth(subject))
    return token


async def link_senior_account(session, senior_id: str, subject: str) -> User:
    """Point the senior profile at a signed-in account, as assisted setup does."""
    user = (
        await session.execute(
            select(User).where(User.external_auth_id == f"dev|{subject}")
        )
    ).scalar_one()
    senior = await session.get(SeniorProfile, uuid.UUID(senior_id))
    senior.user_id = user.id
    await session.commit()
    return user


async def revoke_membership(session, *, family_id: str, subject: str) -> None:
    """Revoke a membership behind the caller's back, mid-session."""
    user = (
        await session.execute(
            select(User).where(User.external_auth_id == f"dev|{subject}")
        )
    ).scalar_one()
    membership = (
        await session.execute(
            select(FamilyMembership).where(
                FamilyMembership.user_id == user.id,
                FamilyMembership.family_id == uuid.UUID(family_id),
            )
        )
    ).scalar_one()
    membership.status = MembershipStatus.REVOKED
    membership.revoked_at = dt.datetime.now(dt.UTC)
    await session.commit()


async def add_medication(
    client,
    family: Family,
    *,
    name: str = "Metformin",
    local_time: str = "08:00",
    dose_quantity: str = "1 tablet",
    late_after_minutes: int = 30,
    missed_after_minutes: int = 120,
    actor: str | None = None,
) -> dict:
    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/medications",
        json={
            "name": name,
            "schedules": [
                {
                    "local_time": local_time,
                    "dose_quantity": dose_quantity,
                    "late_after_minutes": late_after_minutes,
                    "missed_after_minutes": missed_after_minutes,
                }
            ],
        },
        headers=family.headers(actor),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def list_doses(client, family: Family, *, actor: str | None = None) -> list[dict]:
    response = await client.get(
        f"/api/v1/seniors/{family.senior_id}/doses", headers=family.headers(actor)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def start_live_session(
    client, *, subject: str, senior_id: str | None = None
) -> dict:
    body: dict = {}
    if senior_id is not None:
        body["senior_id"] = senior_id
    response = await client.post(
        "/api/v1/ai/live-sessions", json=body, headers=auth(subject)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def call_tools(
    client, *, session_id: str, subject: str, calls: list[dict]
) -> dict:
    response = await client.post(
        f"/api/v1/ai/live-sessions/{session_id}/tool-calls",
        json={"calls": calls},
        headers=auth(subject),
    )
    assert response.status_code == 200, response.text
    return response.json()


def call(name: str, call_id: str = "call-1", **arguments) -> dict:
    return {"id": call_id, "name": name, "arguments": arguments}
