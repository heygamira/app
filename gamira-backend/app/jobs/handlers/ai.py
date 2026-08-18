"""AI job handlers.

Everything here is allowed to fail. Nothing in ``app.jobs.handlers.care``
imports this module, and no deterministic care rule waits on one of these jobs
to finish — which is what makes a Gemini outage a degraded summary rather than
a missed dose.

The retry rules follow the provider's own classification: a timeout or an
unreachable endpoint is retried, a reply that will not satisfy the schema is
not, because it will not satisfy it on the fifth attempt either.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import delete, select, update

from app.ai import review as review_service
from app.ai import summaries as summary_service
from app.ai.provider import AIError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.jobs.queue import (
    JobResult,
    PermanentJobError,
    RetryableJobError,
    enqueue_job,
)
from app.jobs.registry import JobContext, handler
from app.jobs.types import JobType
from app.models.ai import Conversation, ConversationMessage
from app.models.identity import SeniorProfile

logger = get_logger(__name__)


@handler(JobType.AI_WEEKLY_SUMMARY)
async def generate_weekly_summary(ctx: JobContext) -> JobResult:
    """Count a person's week, then ask the model to word it.

    The figures are committed before the model is called. If the call fails the
    job is retried and the summary row is already there, holding everything a
    family needs minus the friendly sentence.
    """
    payload = ctx.payload
    senior_id = _uuid(payload.get("senior_profile_id"), "senior_profile_id")
    senior = await ctx.session.get(SeniorProfile, senior_id)
    if senior is None:
        raise PermanentJobError("senior_not_found")

    period_start, period_end = _period(payload, senior.timezone)
    summary, facts, _created = await summary_service.prepare_summary(
        ctx.session,
        senior=senior,
        requested_by_user_id=_optional_uuid(payload.get("requested_by_user_id")),
        period_start=period_start,
        period_end=period_end,
    )
    # Commit the deterministic half now: a provider failure below must not roll
    # back the figures the family can already be shown.
    await ctx.session.commit()

    try:
        await summary_service.generate_summary_text(
            ctx.session, summary=summary, facts=facts, settings=ctx.settings,
            job_id=ctx.job.id,
        )
    except AIError as exc:
        await ctx.session.commit()
        logger.warning(
            "weekly_summary_generation_failed",
            extra={
                "summary_id": str(summary.id),
                "error_code": exc.code,
                "retryable": exc.retryable,
            },
        )
        if exc.retryable:
            raise RetryableJobError(exc.code) from exc
        raise PermanentJobError(exc.code) from exc

    return JobResult(
        reference={"type": "ai_summary", "id": str(summary.id)},
        metrics={
            "doses_scheduled": facts.doses.scheduled,
            "doses_taken": facts.doses.taken,
            "has_freshness_warning": bool(facts.data_freshness_warning),
        },
    )


@handler(JobType.AI_CONVERSATION_REVIEW)
async def review_conversation(ctx: JobContext) -> JobResult:
    """Read one finished conversation back: what to remember, and who to tell.

    Same shape as the summary above. The deterministic half — the transcript
    and what was already remembered — is assembled first and costs nothing if
    the model is unreachable, because an unreviewed conversation is the ordinary
    state of one, not a degraded state.

    A conversation too short to be worth reading is a success with nothing done,
    not a failure. Most of them are: "Gamira?" — "Yes?" — silence.
    """
    conversation_id = _uuid(ctx.payload.get("conversation_id"), "conversation_id")
    conversation = await ctx.session.get(Conversation, conversation_id)
    if conversation is None:
        raise PermanentJobError("conversation_not_found")

    data = await review_service.gather(ctx.session, conversation=conversation)
    if data is None:
        return JobResult(metrics={"reviewed": 0, "reason_too_short": 1})

    try:
        summary, output = await review_service.review(
            ctx.session, data=data, settings=ctx.settings, job_id=ctx.job.id
        )
    except AIError as exc:
        await ctx.session.commit()
        logger.warning(
            "conversation_review_failed",
            extra={
                "conversation_id": str(conversation.id),
                "error_code": exc.code,
                "retryable": exc.retryable,
            },
        )
        if exc.retryable:
            raise RetryableJobError(exc.code) from exc
        raise PermanentJobError(exc.code) from exc

    suggested = await review_service.suggest_reminders(
        ctx.session, data=data, output=output
    )
    notice = await review_service.notify(
        ctx.session, data=data, output=output, summary=summary, settings=ctx.settings
    )
    if notice.hold_until is not None:
        # The middle of the night where they live. Held rather than dropped:
        # the family should still hear about it, in the morning.
        await enqueue_job(
            ctx.session,
            JobType.AI_FAMILY_NOTICE,
            payload={
                "summary_id": str(summary.id),
                "senior_profile_id": str(data.senior.id),
                "family_id": str(data.conversation.family_id),
                "exclude_user_id": str(data.conversation.user_id),
                "message": notice.message,
                "conversation_id": str(data.conversation.id),
            },
            dedupe_key=f"family-notice:{data.conversation.id}",
            family_id=data.conversation.family_id,
            run_after=notice.hold_until,
        )

    return JobResult(
        reference={"type": "ai_summary", "id": str(summary.id)},
        metrics={
            "reviewed": 1,
            "turns": data.turn_count,
            "memories_offered": len(output.memories),
            "reminders_suggested": len(suggested),
            "family_notified": len(notice.sent),
            "notice_held": int(notice.hold_until is not None),
        },
    )


@handler(JobType.AI_FAMILY_NOTICE)
async def send_held_family_notice(ctx: JobContext) -> JobResult:
    """Send a notice that was held over quiet hours.

    Deliberately the same `deliver_notice` the immediate path uses, so a notice
    that waited overnight is not a slightly different notice. Its dedupe keys
    are derived from the conversation, so this cannot double up with anything
    the review already sent.
    """
    payload = ctx.payload
    summary_id = _uuid(payload.get("summary_id"), "summary_id")
    senior_id = _uuid(payload.get("senior_profile_id"), "senior_profile_id")
    family_id = _uuid(payload.get("family_id"), "family_id")
    message = str(payload.get("message") or "").strip()
    senior = await ctx.session.get(SeniorProfile, senior_id)
    if senior is None:
        raise PermanentJobError("senior_not_found")
    if not message:
        return JobResult(metrics={"family_notified": 0})

    sent = await review_service.deliver_notice(
        ctx.session,
        family_id=family_id,
        senior=senior,
        message=message,
        summary_id=summary_id,
        exclude_user_id=_optional_uuid(payload.get("exclude_user_id")),
        dedupe_prefix=f"conversation-review:{payload.get('conversation_id')}",
    )
    return JobResult(metrics={"family_notified": len(sent)})


@handler(JobType.LIVE_SESSION_EXPIRY)
async def expire_live_sessions(ctx: JobContext) -> JobResult:
    """Close Live sessions whose token has run out.

    A browser that vanished without saying goodbye would otherwise hold a
    concurrency slot until somebody noticed.
    """
    from app.ai.live import expire_stale_sessions

    expired = await expire_stale_sessions(ctx.session)
    return JobResult(metrics={"live_sessions_expired": expired})


@handler(JobType.CONVERSATION_RETENTION)
async def delete_old_transcripts(ctx: JobContext) -> JobResult:
    """Delete transcripts past their retention window.

    Every conversation is created with ``retention_policy="transcript_only"``,
    which was an aspiration until transcripts were actually stored and is a
    promise now. This is what keeps it.

    The messages go; the conversation row stays, marked so the deletion is
    visible rather than looking like a conversation nobody ever had. What was
    remembered from it stays too — a memory is a sentence about somebody's life
    that they can see and delete themselves, not a copy of what they said.
    """
    cutoff = utcnow() - dt.timedelta(days=ctx.settings.conversation_retention_days)
    stale = list(
        (
            await ctx.session.execute(
                select(Conversation.id).where(
                    Conversation.started_at < cutoff,
                    # Only the ones still holding a transcript. Once cleared
                    # they are marked `deleted` and stop being selected, so
                    # this stays cheap however much history accumulates.
                    Conversation.retention_policy == "transcript_only",
                )
            )
        ).scalars()
    )
    if not stale:
        return JobResult(metrics={"conversations": 0, "messages_deleted": 0})

    deleted = await ctx.session.execute(
        delete(ConversationMessage).where(
            ConversationMessage.conversation_id.in_(stale)
        )
    )
    count = int(deleted.rowcount or 0)
    if count:
        await ctx.session.execute(
            update(Conversation)
            .where(Conversation.id.in_(stale))
            .values(retention_policy="deleted")
            .execution_options(synchronize_session=False)
        )
    return JobResult(
        metrics={"conversations": len(stale), "messages_deleted": count},
    )


def _period(payload: dict, timezone_name: str) -> tuple[dt.date, dt.date]:
    raw_start = payload.get("period_start")
    raw_end = payload.get("period_end")
    if raw_start and raw_end:
        try:
            return dt.date.fromisoformat(str(raw_start)), dt.date.fromisoformat(
                str(raw_end)
            )
        except ValueError:
            raise PermanentJobError("invalid_period") from None
    return summary_service.default_period(timezone_name, utcnow())


def _uuid(raw: object, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        raise PermanentJobError(f"invalid_{field}") from None


def _optional_uuid(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


__all__ = [
    "delete_old_transcripts",
    "expire_live_sessions",
    "generate_weekly_summary",
    "review_conversation",
    "send_held_family_notice",
]
