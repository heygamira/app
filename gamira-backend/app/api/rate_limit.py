"""A small, DB-backed rate limiter for the endpoints with no other defense.

See ``app.models.rate_limit.RateLimitEvent`` for why this is a database
counter and not an in-memory one. Lives beside ``app.api.deps`` rather than in
``app.core`` because it composes ``CurrentUser``/``SessionDep`` — API-layer
dependency wiring, not a foundational utility ``app.core`` modules could
depend on without inverting the usual direction.

Usage:

    @router.post("/seniors/{senior_id}/sos")
    async def raise_sos(
        ...,
        _rate_limit: Annotated[
            None, rate_limit("sos_raise", limit=10, window_seconds=3600)
        ],
    ) -> ...:
        ...

Keyed per authenticated user — every route this guards already requires a
bearer token (``app.api.deps.get_current_user``), so there is no anonymous
surface to key on by IP instead.
"""

from __future__ import annotations

import datetime as dt

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import RateLimited
from app.db.base import utcnow
from app.models.rate_limit import RateLimitEvent


def rate_limit(bucket: str, *, limit: int, window_seconds: int):
    """Build a FastAPI dependency enforcing ``limit`` calls to ``bucket`` per
    ``window_seconds``, per signed-in user."""

    async def _check(session: SessionDep, user: CurrentUser) -> None:
        await _enforce(
            session,
            bucket=bucket,
            subject=str(user.id),
            limit=limit,
            window_seconds=window_seconds,
        )

    return Depends(_check)


async def _enforce(
    session: AsyncSession,
    *,
    bucket: str,
    subject: str,
    limit: int,
    window_seconds: int,
    now: dt.datetime | None = None,
) -> None:
    now = now or utcnow()
    window_start = now - dt.timedelta(seconds=window_seconds)
    count = await session.scalar(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(
            RateLimitEvent.bucket == bucket,
            RateLimitEvent.subject == subject,
            RateLimitEvent.occurred_at >= window_start,
        )
    )
    if count is not None and count >= limit:
        raise RateLimited()
    # Only a request that is actually let through gets recorded. Recording
    # first and rolling the row back on rejection would work too, but there is
    # no reason to pay for an insert that a rejection immediately discards —
    # get_session() rolls the whole request's session back when a dependency
    # raises, so a row added here before raising would never survive anyway.
    session.add(RateLimitEvent(bucket=bucket, subject=subject, occurred_at=now))
    # Autoflush is off project-wide (app/db/session.py), so without this the
    # count query above would not see this row on a second call sharing the
    # same session — which matters within one request only if this dependency
    # ran twice, but matters a great deal to a test exercising the limit by
    # calling this repeatedly against one session.
    await session.flush()


__all__ = ["rate_limit"]
