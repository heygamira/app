"""What Gamira remembers between conversations.

The feature is only defensible because of three properties, and these are the
tests for them: what she keeps is visible to the person it is about, they can
delete any of it, and a deleted memory really does stop reaching the model.

The fourth property is negative and tested here too — there is no way for
anything remembered to become a medical record, and no endpoint by which a
person can write one, because a note somebody wrote has an author and belongs
in `family_notes` where the author is recorded.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.ai.persona import SYSTEM_INSTRUCTION
from app.models.ai import SeniorMemory
from app.models.enums import MemoryKind
from tests.conftest import auth
from tests.factories import call, call_tools, create_family, join, start_live_session


async def _remember(client, session_id, subject, content, kind="preference", cid="fc-1"):
    body = await call_tools(
        client,
        session_id=session_id,
        subject=subject,
        calls=[call("remember_this", cid, kind=kind, content=content)],
    )
    return body["results"][0]


async def _memories(client, family, actor=None):
    response = await client.get(
        f"/api/v1/ai/seniors/{family.senior_id}/memories",
        headers=family.headers(actor),
    )
    assert response.status_code == 200
    return response.json()


async def test_remembering_something_happens_immediately(client, session):
    """No dialog. "I'll remember that" has to be true when it is said."""
    family = await create_family(client)
    live = await start_live_session(client, subject=family.owner)

    result = await _remember(
        client, live["session_id"], family.owner, "Her granddaughter Anya visits Sundays"
    )

    assert result["ok"] is True
    assert result["requires_confirmation"] is False
    assert result["response"]["remembered"] is True

    row = (await session.execute(select(SeniorMemory))).scalar_one()
    assert row.content == "Her granddaughter Anya visits Sundays"
    assert row.kind is MemoryKind.PREFERENCE
    # Provenance travels with it: which conversation, which model, which prompt.
    assert str(row.source_conversation_id) == live["conversation_id"]
    assert row.prompt_version is not None


async def test_the_same_thing_twice_is_one_memory(client, session):
    family = await create_family(client)
    live = await start_live_session(client, subject=family.owner)

    await _remember(
        client, live["session_id"], family.owner, "She walks before breakfast"
    )
    second = await _remember(
        client,
        live["session_id"],
        family.owner,
        "  she WALKS   before breakfast ",
        cid="fc-2",
    )

    assert second["response"]["remembered"] is False
    assert await session.scalar(select(func.count()).select_from(SeniorMemory)) == 1


async def test_a_memory_reaches_the_next_conversation(client, token_minter):
    """The whole point. Pinned into the token, so the browser cannot strip it."""
    family = await create_family(client)
    first = await start_live_session(client, subject=family.owner)
    await _remember(
        client,
        first["session_id"],
        family.owner,
        "She would rather not be rung before nine",
    )

    token_minter.reset()
    await start_live_session(client, subject=family.owner)

    instruction = token_minter.minted[-1]["system_instruction"]
    assert "rather not be rung before nine" in instruction
    # Fenced and labelled as notes, not as anything that could redefine her.
    assert "WHAT YOU ALREADY KNOW ABOUT THEM" in instruction
    assert instruction.startswith(SYSTEM_INSTRUCTION)


async def test_a_session_with_nothing_remembered_is_the_persona_exactly(
    client, token_minter
):
    family = await create_family(client)
    await start_live_session(client, subject=family.owner)
    assert token_minter.minted[-1]["system_instruction"] == SYSTEM_INSTRUCTION


async def test_deleting_a_memory_stops_it_reaching_the_model(
    client, session, token_minter
):
    family = await create_family(client)
    live = await start_live_session(client, subject=family.owner)
    await _remember(client, live["session_id"], family.owner, "She dislikes the radio on")

    listed = await _memories(client, family)
    assert len(listed) == 1

    deleted = await client.delete(
        f"/api/v1/ai/memories/{listed[0]['id']}", headers=family.headers()
    )
    assert deleted.status_code == 204

    assert await _memories(client, family) == []
    token_minter.reset()
    await start_live_session(client, subject=family.owner)
    assert token_minter.minted[-1]["system_instruction"] == SYSTEM_INSTRUCTION


async def test_a_deleted_memory_does_not_come_back_on_its_own(client, session):
    """Somebody who deleted a memory did not ask to be asked again.

    Without this, the next time the same thing came up in conversation it would
    be written straight back, and deleting it would feel like it had not worked.
    """
    family = await create_family(client)
    live = await start_live_session(client, subject=family.owner)
    await _remember(client, live["session_id"], family.owner, "She dislikes the radio on")
    listed = await _memories(client, family)
    await client.delete(
        f"/api/v1/ai/memories/{listed[0]['id']}", headers=family.headers()
    )

    again = await _remember(
        client, live["session_id"], family.owner, "She dislikes the radio on", cid="fc-2"
    )

    assert again["response"]["remembered"] is False
    assert await _memories(client, family) == []


async def test_the_cared_for_person_can_delete_their_own_memory(client, session):
    """A viewer role, on their own record. Forgetting yourself is not a care action."""
    family = await create_family(client)
    await join(client, family, subject="the-senior", role="viewer")
    live = await start_live_session(client, subject=family.owner)
    await _remember(client, live["session_id"], family.owner, "She sings in a choir")

    listed = await _memories(client, family, actor="the-senior")
    response = await client.delete(
        f"/api/v1/ai/memories/{listed[0]['id']}", headers=auth("the-senior")
    )

    assert response.status_code == 204


async def test_another_family_can_neither_read_nor_delete(client, session):
    family = await create_family(client, owner="owner-a")
    await create_family(client, owner="owner-b", name="Other")
    live = await start_live_session(client, subject="owner-a")
    await _remember(client, live["session_id"], "owner-a", "She sings in a choir")
    listed = await _memories(client, family)

    read = await client.get(
        f"/api/v1/ai/seniors/{family.senior_id}/memories", headers=auth("owner-b")
    )
    delete = await client.delete(
        f"/api/v1/ai/memories/{listed[0]['id']}", headers=auth("owner-b")
    )

    # 404 both times: an outsider must not learn either exists.
    assert read.status_code == 404
    assert delete.status_code == 404
    assert len(await _memories(client, family)) == 1


async def test_there_is_no_medical_kind_to_remember_something_as(client):
    """Structural. The enum the tool accepts has no clinical member at all."""
    family = await create_family(client)
    live = await start_live_session(client, subject=family.owner)

    for bad in ("symptom", "medication", "reading", "diagnosis", "mood", "concern"):
        result = await _remember(
            client,
            live["session_id"],
            family.owner,
            "something",
            kind=bad,
            cid=f"fc-{bad}",
        )
        assert result["ok"] is False, f"{bad!r} was accepted"
        assert result["response"]["error"] == "invalid_arguments"


async def test_a_memory_cannot_be_written_through_the_api(client):
    """Memories are Gamira's. A note a person wrote has an author, and belongs
    in `family_notes` where the author is recorded."""
    family = await create_family(client)
    response = await client.post(
        f"/api/v1/ai/seniors/{family.senior_id}/memories",
        json={"kind": "preference", "content": "anything"},
        headers=family.headers(),
    )
    assert response.status_code == 405


async def test_an_unknown_memory_is_not_found(client):
    family = await create_family(client)
    response = await client.delete(
        f"/api/v1/ai/memories/{uuid.uuid4()}", headers=family.headers()
    )
    assert response.status_code == 404
