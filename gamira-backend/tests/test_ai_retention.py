"""Transcripts do not live forever.

`retention_policy="transcript_only"` has been written onto every conversation
since voice existed, and until transcripts were actually stored it described
nothing. Now that it describes something, it has to be true — a voice companion
in somebody's home must not quietly accumulate an indefinite record of their
private talk.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.ai import Conversation, ConversationMessage, SeniorMemory
from app.models.enums import MemoryKind
from app.services import memories as memory_service
from tests.conftest import auth
from tests.factories import call, call_tools, create_family, start_live_session

TURNS = [
    {"role": "user", "text": "did I take the morning one"},
    {"role": "assistant", "text": "Yes, at ten past eight."},
]


async def _talk(client, subject, session, *, days_ago: int):
    """A conversation with a transcript, started `days_ago` days back."""
    live = await start_live_session(client, subject=subject)
    await client.post(
        f"/api/v1/ai/live-sessions/{live['session_id']}/transcript",
        json={"turns": TURNS},
        headers=auth(subject),
    )
    conversation = await session.get(
        Conversation, uuid.UUID(live["conversation_id"])
    )
    conversation.started_at = utcnow() - dt.timedelta(days=days_ago)
    await session.commit()
    return live


async def test_a_transcript_past_its_window_is_deleted(
    client, session, run_worker, worker_settings
):
    family = await create_family(client)
    await _talk(
        client,
        family.owner,
        session,
        days_ago=worker_settings.conversation_retention_days + 1,
    )

    await run_worker(JobType.CONVERSATION_RETENTION)

    left = await session.scalar(
        select(func.count()).select_from(ConversationMessage)
    )
    assert left == 0
    # The conversation itself survives: one that was held and then cleared is a
    # different thing from one that never happened.
    conversation = (await session.execute(select(Conversation))).scalar_one()
    await session.refresh(conversation)
    assert conversation.retention_policy == "deleted"


async def test_a_recent_conversation_is_untouched(
    client, session, run_worker, worker_settings
):
    family = await create_family(client)
    await _talk(client, family.owner, session, days_ago=1)

    await run_worker(JobType.CONVERSATION_RETENTION)

    left = await session.scalar(
        select(func.count()).select_from(ConversationMessage)
    )
    assert left == 2


async def test_the_sweep_does_not_reconsider_what_it_cleared(
    client, session, run_worker, worker_settings
):
    """Once marked `deleted` a conversation drops out of the query, so the
    sweep stays cheap however much history accumulates."""
    family = await create_family(client)
    await _talk(
        client,
        family.owner,
        session,
        days_ago=worker_settings.conversation_retention_days + 1,
    )
    await run_worker(JobType.CONVERSATION_RETENTION)

    await run_worker(JobType.CONVERSATION_RETENTION)

    conversation = (await session.execute(select(Conversation))).scalar_one()
    await session.refresh(conversation)
    assert conversation.retention_policy == "deleted"


async def test_what_gamira_remembered_survives_the_deletion(
    client, session, run_worker, worker_settings
):
    """A memory is a sentence about somebody's life, not a copy of what they
    said. It has its own visibility and its own delete, on this person's own
    phone, and retention of the transcript is a separate question."""
    family = await create_family(client)
    live = await _talk(
        client,
        family.owner,
        session,
        days_ago=worker_settings.conversation_retention_days + 1,
    )
    await call_tools(
        client,
        session_id=live["session_id"],
        subject=family.owner,
        calls=[
            call(
                "remember_this",
                "fc-1",
                kind="person",
                content="Her granddaughter Anya visits on Sundays",
            )
        ],
    )

    await run_worker(JobType.CONVERSATION_RETENTION)

    kept = list((await session.execute(select(SeniorMemory))).scalars())
    assert len(kept) == 1
    assert kept[0].kind is MemoryKind.PERSON
    # And it is still what reaches the next conversation.
    recalled = await memory_service.recall_for_prompt(
        session, senior_profile_id=kept[0].senior_profile_id
    )
    assert recalled == [
        {"kind": "person", "about": "Her granddaughter Anya visits on Sundays"}
    ]
