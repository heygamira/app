"""Derived timeline entries and the audit trail."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import current_request_id
from app.db.base import utcnow
from app.models.audit import AuditLog
from app.models.care import TimelineEvent
from app.models.enums import ActorType, TimelineEventType


async def record_timeline_event(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    senior_profile_id: uuid.UUID,
    type: TimelineEventType,
    title: str,
    description: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    occurred_at: dt.datetime | None = None,
    dedupe_key: str | None = None,
) -> TimelineEvent:
    """Add one derived event to the timeline.

    A caller that must not produce two rows however many times its job runs
    passes ``dedupe_key``; the existing row is then returned instead of a
    second one being written. Callers where repetition is meaningful — a person
    correcting a dose they had marked taken — leave it unset.
    """
    if dedupe_key is not None:
        existing = await session.execute(
            select(TimelineEvent).where(TimelineEvent.dedupe_key == dedupe_key)
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            return found

    event = TimelineEvent(
        family_id=family_id,
        senior_profile_id=senior_profile_id,
        type=type,
        title=title,
        description=description,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at or utcnow(),
        dedupe_key=dedupe_key[:160] if dedupe_key else None,
    )
    session.add(event)
    await session.flush()
    return event


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_user_id: uuid.UUID | None,
    actor_type: ActorType = ActorType.USER,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    family_id: uuid.UUID | None = None,
    result: str = "success",
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one audit row.

    Callers pass only non-sensitive metadata: never tokens, invitation secrets
    or full health values.

    ``actor_type`` defaults to ``user`` because almost everything is, but it is
    not decoration: ``docs/AI_SAFETY.md`` promises that an AI-originated action
    is always distinguishable in the audit trail, and a column nobody ever sets
    keeps that promise only by accident.
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_type=actor_type.value,
        action=action,
        target_type=target_type,
        target_id=target_id,
        family_id=family_id,
        request_id=current_request_id() or None,
        result=result,
        metadata_json=metadata or {},
    )
    session.add(entry)
    await session.flush()
    return entry
