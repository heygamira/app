"""Authenticated Live sessions.

What these tests are really guarding: the standalone token server minted a
token for anybody who could reach a port. This endpoint mints one for a
verified user, with the scope, the model, the instruction and the tool
catalogue all decided server-side — and never returns the permanent key.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.ai.persona import PERSONA_VERSION, SYSTEM_INSTRUCTION
from app.ai.tools import PARENT_APP_TOOLS, tool_snapshot
from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.ai import Conversation, LiveSession
from app.models.audit import AuditLog
from app.models.enums import ConversationChannel, LiveSessionStatus
from tests.conftest import auth
from tests.factories import create_family, join, link_senior_account, start_live_session

REAL_KEY = "AIzaSy-this-is-the-permanent-key-and-must-never-ship"


async def test_a_session_requires_authentication(client):
    response = await client.post("/api/v1/ai/live-sessions", json={})
    assert response.status_code == 401


async def test_a_session_is_created_with_a_server_chosen_scope(client, session):
    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    await link_senior_account(session, family.senior_id, "the-senior")

    body = await start_live_session(client, subject="the-senior")

    assert body["senior_id"] == family.senior_id
    assert body["senior_name"] == "Vikram"
    assert body["model"]
    assert body["api_version"]
    assert body["token"].startswith("fake-ephemeral-")
    assert dt.datetime.fromisoformat(body["expires_at"]) > utcnow()
    # The window to *open* a session closes long before the session itself does.
    assert dt.datetime.fromisoformat(body["connect_before"]) < dt.datetime.fromisoformat(
        body["expires_at"]
    )

    row = await session.get(LiveSession, uuid.UUID(body["session_id"]))
    assert row.senior_profile_id == uuid.UUID(family.senior_id)
    assert row.family_id == uuid.UUID(family.family_id)
    assert row.membership_role == "viewer"
    assert row.prompt_version == PERSONA_VERSION


async def test_the_permanent_key_is_never_returned(client, token_minter):
    """The response is the one place a key could realistically leak."""
    family = await create_family(client)
    response = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )

    assert response.status_code == 201
    assert REAL_KEY not in response.text
    assert "AIzaSy" not in response.text
    # Nor the system instruction: the model is told it, the browser is not.
    assert "You are Gamira" not in response.text
    body = response.json()
    assert set(body) == {
        "session_id",
        "conversation_id",
        "token",
        "model",
        "api_version",
        "expires_at",
        "connect_before",
        "senior_id",
        "senior_name",
        "tools",
    }


async def test_only_a_fingerprint_of_the_token_is_stored(client, session):
    family = await create_family(client)
    body = await start_live_session(client, subject=family.owner)

    row = await session.get(LiveSession, uuid.UUID(body["session_id"]))
    assert row.token_fingerprint
    assert row.token_fingerprint not in body["token"]
    assert body["token"] not in str(row.__dict__.values())


async def test_the_audit_line_records_the_session_but_not_the_token(client, session):
    family = await create_family(client)
    body = await start_live_session(client, subject=family.owner)

    entry = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "ai.live_session.create")
        )
    ).scalars().one()
    assert entry.target_id == uuid.UUID(body["session_id"])
    assert entry.metadata_json["model"]
    assert entry.metadata_json["tools"] > 0
    assert body["token"] not in str(entry.metadata_json)


async def test_the_model_instruction_and_tools_are_pinned_into_the_token(
    client, token_minter
):
    family = await create_family(client)
    await start_live_session(client, subject=family.owner)

    assert len(token_minter.minted) == 1
    minted = token_minter.minted[0]
    assert minted["system_instruction"] == SYSTEM_INSTRUCTION
    assert set(minted["tools"]) == set(PARENT_APP_TOOLS)
    assert minted["model"]


async def test_the_tool_snapshot_is_stored_on_the_session(client, session):
    family = await create_family(client)
    body = await start_live_session(client, subject=family.owner)

    row = await session.get(LiveSession, uuid.UUID(body["session_id"]))
    names = {tool["name"] for tool in row.tool_snapshot}
    assert names == set(PARENT_APP_TOOLS)
    for tool in row.tool_snapshot:
        # Strict schemas, everywhere. An invented argument must be an error.
        assert tool["parameters"]["additionalProperties"] is False


async def test_every_declared_tool_has_a_strict_schema():
    from app.ai.tools import CATALOGUE

    for spec in CATALOGUE.values():
        parameters = spec.parameters
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        for field in parameters.get("required", []):
            assert field in parameters["properties"], spec.name


async def test_the_catalogue_exposes_no_general_purpose_tool():
    """The catalogue is the whole attack surface. It must stay small and named."""
    from app.ai.tools import CATALOGUE

    forbidden = (
        "http",
        "fetch",
        "url",
        "sql",
        "query",
        "exec",
        "file",
        "endpoint",
        "shell",
    )
    for name in CATALOGUE:
        assert not any(word in name for word in forbidden), name

    # And nothing that could change a medicine or a dose.
    assert not any(
        "medication" in name and name.startswith(("create", "update", "set"))
        for name in CATALOGUE
    )
    assert "update_medication" not in CATALOGUE
    assert "set_dose_quantity" not in CATALOGUE
    assert "add_health_reading" not in CATALOGUE
    assert "add_emergency_contact" not in CATALOGUE
    assert "raise_sos" not in CATALOGUE


def test_the_gemini_declaration_keeps_the_strict_schema():
    """A regression the fake minter cannot catch.

    ``FunctionDeclaration.parameters`` is the SDK's ``Schema`` type, which has
    no ``additionalProperties`` field — sending one is a 400 from the real Live
    setup. ``parameters_json_schema`` takes a raw JSON Schema and does accept
    it, so that is the field the minter uses and the strict catalogue really
    reaches the model.
    """
    from google.genai import types

    from app.ai.live import _declaration

    tool = tool_snapshot(["mark_dose_taken"])[0]
    declaration = _declaration(types, tool)

    assert declaration.name == "mark_dose_taken"
    schema = declaration.parameters_json_schema
    assert schema is not None, "the strict schema must reach the model"
    assert schema["additionalProperties"] is False
    # And the field the API rejects is not populated.
    assert declaration.parameters is None


async def test_a_conversation_is_created_for_the_session(client, session):
    family = await create_family(client)
    body = await start_live_session(client, subject=family.owner)

    conversation = await session.get(Conversation, uuid.UUID(body["conversation_id"]))
    assert conversation.channel is ConversationChannel.VOICE
    # Audio is never stored; only what the provider transcribed is eligible.
    assert conversation.retention_policy == "transcript_only"


async def test_another_family_cannot_open_a_session_about_this_person(client):
    family = await create_family(client, owner="owner-a")
    await create_family(client, owner="owner-b", name="Other")

    response = await client.post(
        "/api/v1/ai/live-sessions",
        json={"senior_id": family.senior_id},
        headers=auth("owner-b"),
    )
    # 404, not 403: an outsider must not learn this person exists.
    assert response.status_code == 404


async def test_a_suspended_user_is_refused(client, session):
    from app.models.enums import UserStatus
    from app.models.identity import User

    family = await create_family(client)
    await start_live_session(client, subject=family.owner)

    user = (
        await session.execute(
            select(User).where(User.external_auth_id == "dev|owner-a")
        )
    ).scalar_one()
    user.status = UserStatus.SUSPENDED
    await session.commit()

    response = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_suspended"


async def test_a_revoked_member_cannot_open_a_session(client, session):
    from tests.factories import revoke_membership

    family = await create_family(client)
    await join(client, family, subject="ex-carer", role="family")
    await revoke_membership(session, family_id=family.family_id, subject="ex-carer")

    response = await client.post(
        "/api/v1/ai/live-sessions",
        json={"senior_id": family.senior_id},
        headers=auth("ex-carer"),
    )
    assert response.status_code == 404


async def test_the_concurrent_session_limit_is_enforced(client, session):
    family = await create_family(client)
    from app.core.config import get_settings

    limit = get_settings().live_session_max_concurrent
    for _ in range(limit):
        await start_live_session(client, subject=family.owner)

    response = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_live_sessions"


async def test_closing_a_session_frees_its_slot(client, session):
    family = await create_family(client)
    from app.core.config import get_settings

    limit = get_settings().live_session_max_concurrent
    sessions = [
        await start_live_session(client, subject=family.owner) for _ in range(limit)
    ]

    closed = await client.post(
        f"/api/v1/ai/live-sessions/{sessions[0]['session_id']}/close",
        headers=family.headers(),
    )
    assert closed.status_code == 204

    again = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )
    assert again.status_code == 201


async def test_an_expired_session_frees_its_slot(client, session):
    family = await create_family(client)
    from app.core.config import get_settings

    limit = get_settings().live_session_max_concurrent
    for _ in range(limit):
        body = await start_live_session(client, subject=family.owner)
        row = await session.get(LiveSession, uuid.UUID(body["session_id"]))
        row.expires_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    response = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )
    assert response.status_code == 201


async def test_the_expiry_sweep_closes_dead_sessions(client, session, run_worker):
    family = await create_family(client)
    body = await start_live_session(client, subject=family.owner)
    row = await session.get(LiveSession, uuid.UUID(body["session_id"]))
    row.expires_at = utcnow() - dt.timedelta(minutes=1)
    await session.commit()

    await run_worker(JobType.LIVE_SESSION_EXPIRY)

    await session.refresh(row)
    assert row.status is LiveSessionStatus.EXPIRED
    assert row.closed_at is not None


async def test_a_minting_failure_creates_no_session(client, session, token_minter):
    from app.core.errors import DependencyUnavailable

    family = await create_family(client)
    token_minter.fail_with = DependencyUnavailable("Gemini is unreachable.")

    response = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=family.headers()
    )

    assert response.status_code == 503
    # No half-created session, and no conversation left behind.
    assert await session.scalar(select(func.count()).select_from(LiveSession)) == 0
    assert await session.scalar(select(func.count()).select_from(Conversation)) == 0


async def test_the_senior_scope_is_derived_not_supplied(client, session):
    """Two people in one family: the Parent App gets the caller's own record."""
    family = await create_family(client, senior_name="Vikram")
    second = await client.post(
        f"/api/v1/families/{family.family_id}/seniors",
        json={"preferred_name": "Sunita", "timezone": "Asia/Kolkata"},
        headers=family.headers(),
    )
    sunita_id = second.json()["id"]
    await join(client, family, subject="sunita-account", role="viewer")
    await link_senior_account(session, sunita_id, "sunita-account")

    body = await start_live_session(client, subject="sunita-account")

    # Their own profile, not the family's first.
    assert body["senior_id"] == sunita_id
    assert body["senior_name"] == "Sunita"
