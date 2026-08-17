"""Recording what AI calls cost and how they ended.

Every provider call writes one row, successful or not. Errors are stored as
codes: a provider's exception text can contain the prompt it choked on, and a
metrics table is not a place to put somebody's medication list.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import AIResult
from app.models.ai import AiUsage


async def record_usage(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    operation: str,
    outcome: str = "succeeded",
    error_code: str | None = None,
    prompt_version: str | None = None,
    prompt_tokens: int = 0,
    response_tokens: int = 0,
    latency_ms: float | None = None,
    family_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    live_session_id: uuid.UUID | None = None,
) -> AiUsage:
    row = AiUsage(
        provider=provider,
        model=model,
        operation=operation,
        outcome=outcome,
        error_code=error_code[:64] if error_code else None,
        prompt_version=prompt_version,
        prompt_tokens=prompt_tokens,
        response_tokens=response_tokens,
        total_tokens=prompt_tokens + response_tokens,
        latency_ms=latency_ms,
        family_id=family_id,
        user_id=user_id,
        conversation_id=conversation_id,
        job_id=job_id,
        live_session_id=live_session_id,
    )
    session.add(row)
    await session.flush()
    return row


async def record_result(
    session: AsyncSession,
    result: AIResult,
    *,
    operation: str,
    family_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    live_session_id: uuid.UUID | None = None,
) -> AiUsage:
    return await record_usage(
        session,
        provider=result.provider,
        model=result.model,
        operation=operation,
        prompt_version=result.prompt_version,
        prompt_tokens=result.prompt_tokens,
        response_tokens=result.response_tokens,
        latency_ms=result.latency_ms,
        family_id=family_id,
        user_id=user_id,
        conversation_id=conversation_id,
        job_id=job_id,
        live_session_id=live_session_id,
    )


__all__ = ["record_result", "record_usage"]
