"""Reading a finished conversation back.

This is the part of Gamira that notices things. It runs after a conversation
ends, never during one: the person is not kept waiting on it, a failure costs
nothing they were relying on, and it can read the whole exchange rather than
guessing from the middle of it.

Three outputs, in descending order of how much they are allowed to do:

1. **Memories** — small, ordinary, durable facts, written to the same table the
   ``remember_this`` tool writes to, visible to the person and deletable by
   them.
2. **A conversation summary** — an ``AiSummary`` row with ``kind=conversation``,
   so it lands in the same place as every other generated text, with the same
   provenance columns and the same "unreviewed" starting state.
3. **A family notice** — an ordinary ``family_update`` notification, and only
   when Gamira said in the conversation that she would mention it.

That last condition is the whole ethical shape of this feature. The persona
says: *"You are not there to report on them; if something genuinely needs a
family member, say so to them first, openly."* A reviewer that quietly messaged
the family would contradict the instruction the model is running under. So the
model must report ``told_them``, and this module refuses to notify without it.

What this module may never do, structurally: raise an alert. A quiet worry and
an emergency must not be able to look alike, and ``services/alerts.py`` refuses
an AI actor anyway.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import usage as usage_service
from app.ai.prompts import CONVERSATION_REVIEW_V1
from app.ai.provider import AIError, AIProvider, generate_with_retry, get_ai_provider
from app.ai.schemas import ConversationReviewOut
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.ai import AiSummary, Conversation, ConversationMessage
from app.models.care import Reminder
from app.models.enums import (
    ActorType,
    MemoryKind,
    MessageRole,
    NotificationType,
    ReminderStatus,
    ReminderType,
    ReviewState,
    SummaryKind,
)
from app.models.identity import SeniorProfile
from app.services import memories as memory_service
from app.services.notifications import NotificationRequest, notify_family
from app.services.scheduling import load_timezone
from app.services.timeline import record_audit

logger = get_logger(__name__)

# Enough of an exchange to judge it by. A conversation longer than this is
# reviewed from its most recent turns, which are the ones that mattered.
MAX_TURNS = 60
# Below this there is nothing to read. Two turns is "Gamira?" — "Yes?".
MIN_TURNS = 4

_ROLE_WORDS = {
    MessageRole.USER: "Them",
    MessageRole.ASSISTANT: "Gamira",
}


@dataclass
class ReviewInput:
    """The deterministic half: what was said, and what was already known."""

    conversation: Conversation
    senior: SeniorProfile
    transcript: list[tuple[str, str]]
    memories: list[dict[str, str]]

    @property
    def turn_count(self) -> int:
        return len(self.transcript)


async def gather(
    session: AsyncSession, *, conversation: Conversation
) -> ReviewInput | None:
    """Load the conversation and its context. None when there is nothing to read.

    Counted and assembled before any model is involved, so the handler can
    commit the part that is certainly true and treat the model as the part that
    may fail.
    """
    if conversation.senior_profile_id is None:
        return None
    senior = await session.get(SeniorProfile, conversation.senior_profile_id)
    if senior is None:
        return None

    rows = (
        await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(MAX_TURNS)
        )
    ).scalars()
    turns = [
        (_ROLE_WORDS[row.role], row.content)
        for row in reversed(list(rows))
        if row.role in _ROLE_WORDS and (row.content or "").strip()
    ]
    if len(turns) < MIN_TURNS:
        return None

    return ReviewInput(
        conversation=conversation,
        senior=senior,
        transcript=turns,
        memories=await memory_service.recall_for_prompt(
            session, senior_profile_id=senior.id
        ),
    )


async def review(
    session: AsyncSession,
    *,
    data: ReviewInput,
    provider: AIProvider | None = None,
    settings: Settings | None = None,
    job_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> tuple[AiSummary, ConversationReviewOut]:
    """Ask the model what it made of this, then apply what it may.

    Raises ``AIError`` if the model cannot be reached or will not answer in the
    schema. Nothing is written in that case, which is the right outcome: an
    unreviewed conversation is the normal state of every conversation until this
    runs, and never a degraded one.
    """
    settings = settings or get_settings()
    provider = provider or get_ai_provider(settings)
    now = now or utcnow()
    prompt = CONVERSATION_REVIEW_V1
    tz = load_timezone(data.senior.timezone)

    rendered = prompt.render(
        senior_name=data.senior.preferred_name,
        when=(data.conversation.started_at or now).astimezone(tz).strftime("%A %d %B"),
        timezone=data.senior.timezone,
        memories_json=json.dumps(data.memories, indent=2),
        transcript="\n".join(f"{who}: {text}" for who, text in data.transcript),
    )

    try:
        result = await generate_with_retry(
            provider,
            prompt=prompt,
            rendered=rendered,
            output_model=ConversationReviewOut,
            settings=settings,
        )
    except AIError as exc:
        await usage_service.record_usage(
            session,
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "model", "unknown"),
            operation="conversation_review",
            outcome="failed",
            error_code=exc.code,
            prompt_version=prompt.version,
            family_id=data.conversation.family_id,
            user_id=data.conversation.user_id,
            job_id=job_id,
        )
        raise

    output = result.output
    assert isinstance(output, ConversationReviewOut)
    prompt_version = f"{prompt.name}@{prompt.version}"

    summary = await _record_summary(
        session,
        data=data,
        output=output,
        model=result.model,
        provider_name=result.provider,
        prompt_version=prompt_version,
        now=now,
    )
    await _record_memories(
        session,
        data=data,
        output=output,
        model=result.model,
        provider_name=result.provider,
        prompt_version=prompt_version,
    )
    await usage_service.record_usage(
        session,
        provider=result.provider,
        model=result.model,
        operation="conversation_review",
        outcome="succeeded",
        prompt_version=prompt.version,
        family_id=data.conversation.family_id,
        user_id=data.conversation.user_id,
        job_id=job_id,
        prompt_tokens=result.prompt_tokens,
        response_tokens=result.response_tokens,
    )
    return summary, output


@dataclass
class Notice:
    """What became of the family notice: sent to whom, or held until when."""

    sent: list[uuid.UUID]
    message: str
    hold_until: dt.datetime | None


async def notify(
    session: AsyncSession,
    *,
    data: ReviewInput,
    output: ConversationReviewOut,
    summary: AiSummary,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> Notice:
    """Tell the family, if and only if the person was told first.

    Three gates, all of them here rather than in the prompt, because a prompt is
    a request and this is a rule:

    * the model asked for it,
    * it reported that Gamira said so in the conversation,
    * and there is something to say.

    A ``family_update`` notification, never an alert. This is "she might like a
    call", not "something has happened", and the two must not arrive looking
    alike. Push is left off: a nudge to ring somebody is not worth waking a
    phone for, and it will be waiting in the app.

    And not in the middle of the night. Nothing Gamira volunteers is urgent by
    definition — the urgent path is an alert, which she cannot raise — so a
    notice that would land at three in the morning is held until the morning
    instead. See :func:`held_until`.
    """
    if not (output.notify_family and output.told_them):
        return Notice(sent=[], message="", hold_until=None)
    message = output.family_message.strip()
    if not message or data.conversation.family_id is None:
        return Notice(sent=[], message="", hold_until=None)

    settings = settings or get_settings()
    hold = held_until(data.senior.timezone, settings, now)
    if hold is not None:
        # Nothing is written yet. The caller enqueues it for the morning, and
        # `deliver_notice` below does the sending then — the same function, so
        # a notice that waited overnight is not a slightly different notice.
        return Notice(sent=[], message=message, hold_until=hold)

    sent = await deliver_notice(
        session,
        family_id=data.conversation.family_id,
        senior=data.senior,
        message=message,
        summary_id=summary.id,
        exclude_user_id=data.conversation.user_id,
        dedupe_prefix=f"conversation-review:{data.conversation.id}",
    )
    return Notice(sent=sent, message=message, hold_until=None)


async def deliver_notice(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    senior: SeniorProfile,
    message: str,
    summary_id: uuid.UUID,
    exclude_user_id: uuid.UUID | None,
    dedupe_prefix: str,
) -> list[uuid.UUID]:
    """Put the notice in front of the family. One implementation, two callers."""
    return await notify_family(
        session,
        family_id=family_id,
        template=NotificationRequest(
            user_id=exclude_user_id or uuid.uuid4(),  # replaced per recipient
            type=NotificationType.FAMILY_UPDATE,
            title=f"{senior.preferred_name} might like a call",
            body=message[:300],
            senior_profile_id=senior.id,
            related_entity_type="ai_summary",
            related_entity_id=summary_id,
            push=False,
        ),
        # The person whose conversation it was does not need telling about
        # their own conversation.
        exclude_user_ids=[exclude_user_id] if exclude_user_id else [],
        dedupe_prefix=dedupe_prefix,
    )


async def _record_summary(
    session: AsyncSession,
    *,
    data: ReviewInput,
    output: ConversationReviewOut,
    model: str,
    provider_name: str,
    prompt_version: str,
    now: dt.datetime,
) -> AiSummary:
    """One ``AiSummary`` row, so a review lives where every other generated
    text lives — same provenance columns, same unreviewed starting state, same
    place the console reads from.

    ``facts`` holds what the backend counted, not what the model said: how many
    turns there were, and how long it ran. The model's contribution is the
    wording in ``content`` and the impression in ``mood``, and the two are kept
    apart here as everywhere else.
    """
    tz = load_timezone(data.senior.timezone)
    day = (data.conversation.started_at or now).astimezone(tz).date()
    dedupe_key = f"conversation-review:{data.conversation.id}"

    summary = (
        await session.execute(
            select(AiSummary).where(AiSummary.dedupe_key == dedupe_key)
        )
    ).scalar_one_or_none()
    if summary is None:
        summary = AiSummary(
            kind=SummaryKind.CONVERSATION,
            family_id=data.conversation.family_id,
            senior_profile_id=data.senior.id,
            conversation_id=data.conversation.id,
            dedupe_key=dedupe_key,
            period_start=day,
            period_end=day,
        )
        session.add(summary)

    summary.facts = {
        "turns": data.turn_count,
        "channel": data.conversation.channel.value,
    }
    summary.source_reference = {"conversation_messages": data.turn_count}
    summary.content = _render_content(output)
    summary.model = model
    summary.provider = provider_name
    summary.prompt_version = prompt_version
    summary.output_schema_version = output.schema_version
    summary.generated_at = now
    summary.review_state = ReviewState.UNREVIEWED
    await session.flush()
    return summary


def _render_content(output: ConversationReviewOut) -> str:
    parts = [output.summary.strip()] if output.summary.strip() else []
    parts.append(f"How it sounded: {output.mood}.")
    parts.extend(f"- {concern}" for concern in output.concerns)
    for suggestion in output.suggested_reminders:
        parts.append(
            f"- Might suit a reminder: {suggestion.title} at "
            f"{suggestion.local_time} ({suggestion.because})"
        )
    return "\n".join(parts)


async def _record_memories(
    session: AsyncSession,
    *,
    data: ReviewInput,
    output: ConversationReviewOut,
    model: str,
    provider_name: str,
    prompt_version: str,
) -> int:
    """Keep what the review thought was worth keeping.

    Through the same service and the same dedupe rule the in-conversation tool
    uses, so a thing said out loud and noticed again afterwards is one memory,
    and one the person has already deleted stays deleted.
    """
    kept = 0
    for fact in output.memories:
        fingerprint = hashlib.sha256(
            " ".join(fact.content.lower().split()).encode("utf-8")
        ).hexdigest()[:32]
        _memory, created = await memory_service.remember(
            session,
            family_id=data.senior.family_id,
            senior_profile_id=data.senior.id,
            kind=MemoryKind(fact.kind),
            content=fact.content,
            source_conversation_id=data.conversation.id,
            confidence=fact.confidence,
            dedupe_key=f"memory:{data.senior.id}:{fingerprint}",
            model=model,
            provider=provider_name,
            prompt_version=prompt_version,
        )
        if created:
            kept += 1
    return kept


async def suggest_reminders(
    session: AsyncSession,
    *,
    data: ReviewInput,
    output: ConversationReviewOut,
) -> list[Reminder]:
    """Write what she heard as a *suggestion*, never as a live reminder.

    This is the furthest Gamira is allowed to act on her own, and every limit
    is structural rather than a matter of prompting:

    * ``status=SUGGESTED`` — every query for live reminders filters on
      ``ACTIVE``, so a suggestion prompts nobody and appears on no schedule
      until a family member accepts it.
    * ``type=OTHER``, fixed here and absent from the schema, so no path leads
      to a medication.
    * ``created_by_user_id=None`` plus an audit line with ``ActorType.AI``: it
      can never be mistaken for something a person wrote.
    * The reason and the conversation travel with it, so a family can check
      what she heard against what was actually said.

    Deduped on title and time against both suggested and active reminders,
    because somebody who mentions the plants twice in a week should not
    accumulate two identical suggestions to dismiss.
    """
    if not output.suggested_reminders:
        return []

    existing = {
        ((row.title or "").strip().lower(), row.local_time)
        for row in (
            await session.execute(
                select(Reminder).where(
                    Reminder.senior_profile_id == data.senior.id,
                    Reminder.status.in_(
                        [ReminderStatus.SUGGESTED, ReminderStatus.ACTIVE]
                    ),
                )
            )
        ).scalars()
    }

    created: list[Reminder] = []
    for suggestion in output.suggested_reminders:
        title = " ".join(suggestion.title.split())[:200]
        if not title or (title.lower(), suggestion.local_time) in existing:
            continue
        reminder = Reminder(
            family_id=data.senior.family_id,
            senior_profile_id=data.senior.id,
            type=ReminderType.OTHER,
            title=title,
            days_of_week="",
            local_time=suggestion.local_time,
            timezone=data.senior.timezone,
            status=ReminderStatus.SUGGESTED,
            created_by_user_id=None,
            suggestion_reason=" ".join(suggestion.because.split())[:200],
            suggested_from_conversation_id=data.conversation.id,
        )
        session.add(reminder)
        await session.flush()
        existing.add((title.lower(), suggestion.local_time))
        created.append(reminder)

        await record_audit(
            session,
            action="ai.reminder.suggested",
            actor_user_id=None,
            actor_type=ActorType.AI,
            target_type="reminder",
            target_id=reminder.id,
            family_id=reminder.family_id,
            metadata={"conversation_id": str(data.conversation.id)},
        )
    return created


def held_until(
    timezone_name: str,
    settings: Settings,
    now: dt.datetime | None = None,
) -> dt.datetime | None:
    """When a volunteered notice may be sent, or None if it may go now.

    Quiet hours are read in *this person's* timezone, not the server's or the
    reader's: "don't tell the family at 3am" is about the hour it happened, and
    a family scattered across timezones has no single night.

    Nothing Gamira volunteers is urgent — the urgent path is an alert, which she
    cannot raise — so holding one until the morning costs nothing. An emergency
    never travels this way.
    """
    start = settings.family_notice_quiet_start_hour
    end = settings.family_notice_quiet_end_hour
    if start == end:
        return None  # quiet hours switched off

    tz = load_timezone(timezone_name)
    local = (now or utcnow()).astimezone(tz)
    # A window that crosses midnight (21:00 to 08:00) is the normal case, so
    # both wrapping and non-wrapping windows are handled rather than assumed.
    quiet = (
        local.hour >= start or local.hour < end
        if start > end
        else start <= local.hour < end
    )
    if not quiet:
        return None

    morning = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if morning <= local:
        morning += dt.timedelta(days=1)
    return morning.astimezone(dt.UTC)


__all__ = [
    "MAX_TURNS",
    "MIN_TURNS",
    "Notice",
    "ReviewInput",
    "deliver_notice",
    "gather",
    "held_until",
    "notify",
    "review",
    "suggest_reminders",
]
