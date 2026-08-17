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

from app.ai import summaries as summary_service
from app.ai.provider import AIError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.jobs.queue import JobResult, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext, handler
from app.jobs.types import JobType
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


@handler(JobType.LIVE_SESSION_EXPIRY)
async def expire_live_sessions(ctx: JobContext) -> JobResult:
    """Close Live sessions whose token has run out.

    A browser that vanished without saying goodbye would otherwise hold a
    concurrency slot until somebody noticed.
    """
    from app.ai.live import expire_stale_sessions

    expired = await expire_stale_sessions(ctx.session)
    return JobResult(metrics={"live_sessions_expired": expired})


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


__all__ = ["expire_live_sessions", "generate_weekly_summary"]
