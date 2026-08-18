"""What Gamira remembers, and the rules for keeping it.

The one implementation of reading, writing and forgetting a memory. Both the
in-conversation tool and the after-call review write through here, and both
apps read through here, so there is no second idea of what "remembered" means.

Three properties this module exists to hold:

* **Bounded.** Retrieval is capped and ordered, because everything read here
  ends up in a prompt. A memory list that grows without limit becomes a slow,
  expensive way to tell a model things it does not need.
* **Deletable.** The person it is about, and their family, can remove any of
  it. That is the condition on which keeping it is reasonable at all, so
  deletion is a first-class operation rather than an admin task, and a deleted
  memory leaves the prompt immediately.
* **Attributable.** Every row records the conversation, model and prompt
  version that produced it. "Why does Gamira think that?" has an answer.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.ai import SeniorMemory
from app.models.enums import MemoryKind

# What goes into a prompt. Enough to sound like somebody who has met them
# before; small enough that it is not a dossier.
MAX_RECALLED = 20


async def recent_memories(
    session: AsyncSession,
    *,
    senior_profile_id: uuid.UUID,
    limit: int = MAX_RECALLED,
    kinds: tuple[MemoryKind, ...] | None = None,
) -> list[SeniorMemory]:
    """This person's live memories, newest first.

    Excludes anything deleted or superseded — the two ways a memory stops being
    what Gamira currently believes.
    """
    query = (
        select(SeniorMemory)
        .where(
            SeniorMemory.senior_profile_id == senior_profile_id,
            SeniorMemory.deleted_at.is_(None),
            SeniorMemory.superseded_by_id.is_(None),
        )
        .order_by(SeniorMemory.created_at.desc())
        .limit(limit)
    )
    if kinds:
        query = query.where(SeniorMemory.kind.in_(kinds))
    return list((await session.execute(query)).scalars())


async def recall_for_prompt(
    session: AsyncSession, *, senior_profile_id: uuid.UUID, limit: int = MAX_RECALLED
) -> list[dict[str, str]]:
    """The same memories, flattened to the least a prompt needs.

    Kind and content, nothing else. Not the ids, not the confidence, not which
    conversation it came from: none of that changes what Gamira should say, and
    an id in a prompt is an id a model can repeat back.
    """
    rows = await recent_memories(
        session, senior_profile_id=senior_profile_id, limit=limit
    )
    return [{"kind": row.kind.value, "about": row.content} for row in rows]


async def remember(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    senior_profile_id: uuid.UUID,
    kind: MemoryKind,
    content: str,
    source_conversation_id: uuid.UUID | None = None,
    confidence: float | None = None,
    dedupe_key: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    prompt_version: str | None = None,
    output_schema_version: str | None = None,
) -> tuple[SeniorMemory | None, bool]:
    """Keep one thing. Returns ``(row, created)``.

    ``created`` is false when nothing was written, which happens two ways and
    the difference matters to nobody but is worth naming: the memory was
    already held, or it was held and the person deleted it. A deleted memory is
    never rewritten — somebody who removed something did not ask to be asked
    again, and having it quietly reappear would make deleting it feel broken.

    ``(None, False)`` means there was nothing to keep at all.
    """
    text = " ".join((content or "").split())[:400]
    if not text:
        return None, False

    if dedupe_key:
        existing = (
            await session.execute(
                select(SeniorMemory).where(SeniorMemory.dedupe_key == dedupe_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return (None if existing.deleted_at is not None else existing), False

    memory = SeniorMemory(
        family_id=family_id,
        senior_profile_id=senior_profile_id,
        kind=kind,
        content=text,
        source_conversation_id=source_conversation_id,
        confidence=confidence,
        dedupe_key=dedupe_key,
        model=model,
        provider=provider,
        prompt_version=prompt_version,
        output_schema_version=output_schema_version,
    )
    session.add(memory)
    await session.flush()
    return memory, True


async def forget(
    session: AsyncSession,
    *,
    memory: SeniorMemory,
    user_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> SeniorMemory:
    """Stop using a memory, and record who stopped it.

    Soft, so that "why did Gamira say that?" stays answerable afterwards. It
    leaves every prompt straight away either way: retrieval filters on
    ``deleted_at``, and there is no other path to the table.
    """
    if memory.deleted_at is None:
        memory.deleted_at = now or utcnow()
        memory.deleted_by_user_id = user_id
        await session.flush()
    return memory


__all__ = [
    "MAX_RECALLED",
    "forget",
    "recall_for_prompt",
    "recent_memories",
    "remember",
]
