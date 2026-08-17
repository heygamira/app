"""The weekly care summary — the first complete AI feature.

The order is the safety property:

1. Count the week deterministically (:mod:`app.ai.facts`).
2. Persist those figures, with their period, their source version and their
   freshness warning, *before* any model is called.
3. Ask the model to turn the figures into sentences, against a versioned prompt
   and a strict output schema.
4. Store the wording beside the figures, with the model, provider, prompt
   version and output schema version that produced it.

If step 3 fails, steps 1 and 2 have already happened. The summary row exists,
the figures are readable, and the job reports a retryable failure — a family
gets the numbers with a note that the wording is not ready, rather than
nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import usage as usage_service
from app.ai.facts import SOURCE_DATA_VERSION, build_care_facts
from app.ai.prompts import WEEKLY_SUMMARY_V1
from app.ai.provider import AIError, AIProvider, generate_with_retry, get_ai_provider
from app.ai.schemas import OUTPUT_SCHEMA_VERSION, CareFacts, WeeklySummaryOut
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.ai import AiSummary
from app.models.enums import ReviewState, SummaryKind
from app.models.identity import SeniorProfile
from app.services.scheduling import load_timezone

logger = get_logger(__name__)

DEFAULT_PERIOD_DAYS = 7


def default_period(
    timezone_name: str, now: dt.datetime | None = None
) -> tuple[dt.date, dt.date]:
    """The seven days ending yesterday, in the senior's own timezone.

    Ending yesterday rather than today because a summary of a day still in
    progress reads as though the person missed everything they have not done
    yet.
    """
    tz = load_timezone(timezone_name)
    today = (now or utcnow()).astimezone(tz).date()
    end = today - dt.timedelta(days=1)
    return end - dt.timedelta(days=DEFAULT_PERIOD_DAYS - 1), end


def summary_dedupe_key(
    senior_id: uuid.UUID, period_start: dt.date, period_end: dt.date
) -> str:
    return f"weekly:{senior_id}:{period_start.isoformat()}:{period_end.isoformat()}"


async def prepare_summary(
    session: AsyncSession,
    *,
    senior: SeniorProfile,
    requested_by_user_id: uuid.UUID | None,
    period_start: dt.date,
    period_end: dt.date,
    now: dt.datetime | None = None,
) -> tuple[AiSummary, CareFacts, bool]:
    """Count the period and persist the figures. No model is involved.

    Returns the row, the facts and whether it was newly created. Calling this
    twice for one period returns the same row: the dedupe key is the period.
    """
    now = now or utcnow()
    key = summary_dedupe_key(senior.id, period_start, period_end)
    existing = (
        await session.execute(select(AiSummary).where(AiSummary.dedupe_key == key))
    ).scalar_one_or_none()

    facts = await build_care_facts(
        session,
        senior=senior,
        period_start=period_start,
        period_end=period_end,
        now=now,
    )
    payload = json.loads(facts.model_dump_json())

    if existing is not None:
        # Refresh the figures — a week's counts can still change if somebody
        # records a late dose — but keep the row, its id and any review state.
        existing.facts = payload
        existing.data_freshness_warning = facts.data_freshness_warning
        return existing, facts, False

    summary = AiSummary(
        kind=SummaryKind.WEEKLY_CARE,
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        requested_by_user_id=requested_by_user_id,
        dedupe_key=key,
        period_start=period_start,
        period_end=period_end,
        facts=payload,
        source_reference={
            "tables": [
                "dose_events",
                "reminders",
                "health_readings",
                "appointments",
                "timeline_events",
                "alerts",
            ],
            "counted_at": now.isoformat(),
        },
        source_data_version=SOURCE_DATA_VERSION,
        data_freshness_warning=facts.data_freshness_warning,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        review_state=ReviewState.UNREVIEWED,
    )
    session.add(summary)
    await session.flush()
    return summary, facts, True


async def generate_summary_text(
    session: AsyncSession,
    *,
    summary: AiSummary,
    facts: CareFacts,
    provider: AIProvider | None = None,
    settings: Settings | None = None,
    job_id: uuid.UUID | None = None,
) -> AiSummary:
    """Ask the model for the wording. Raises ``AIError`` if it cannot.

    The caller decides what a failure means. The summary row and its figures
    are already durable either way.
    """
    settings = settings or get_settings()
    provider = provider or get_ai_provider(settings)
    prompt = WEEKLY_SUMMARY_V1

    rendered = prompt.render(
        senior_name=facts.senior_name,
        period_start=facts.period_start.isoformat(),
        period_end=facts.period_end.isoformat(),
        timezone=facts.timezone,
        facts_json=json.dumps(json.loads(facts.model_dump_json()), indent=2),
        freshness_note=(
            f"Data note that must appear in your answer: {facts.data_freshness_warning}"
            if facts.data_freshness_warning
            else "The data for this period is complete."
        ),
    )

    try:
        result = await generate_with_retry(
            provider,
            prompt=prompt,
            rendered=rendered,
            output_model=WeeklySummaryOut,
            settings=settings,
        )
    except AIError as exc:
        await usage_service.record_usage(
            session,
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "model", "unknown"),
            operation="weekly_summary",
            outcome="failed",
            error_code=exc.code,
            prompt_version=prompt.version,
            family_id=summary.family_id,
            user_id=summary.requested_by_user_id,
            job_id=job_id,
        )
        raise

    output = result.output
    assert isinstance(output, WeeklySummaryOut)
    summary.content = _render_content(output)
    summary.model = result.model
    summary.provider = result.provider
    summary.prompt_version = f"{prompt.name}@{prompt.version}"
    summary.output_schema_version = output.schema_version
    summary.generated_at = utcnow()
    await session.flush()

    await usage_service.record_result(
        session,
        result,
        operation="weekly_summary",
        family_id=summary.family_id,
        user_id=summary.requested_by_user_id,
        job_id=job_id,
    )
    return summary


def _render_content(output: WeeklySummaryOut) -> str:
    """Flatten the structured reply into the paragraph a screen shows."""
    parts = [output.headline.strip(), output.body.strip()]
    parts.extend(f"• {line.strip()}" for line in output.highlights if line.strip())
    return "\n\n".join(part for part in parts if part)


__all__ = [
    "DEFAULT_PERIOD_DAYS",
    "default_period",
    "generate_summary_text",
    "prepare_summary",
    "summary_dedupe_key",
]
