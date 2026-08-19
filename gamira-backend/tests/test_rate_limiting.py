"""The database-backed rate limiter: unit coverage of the counting logic,
plus one full HTTP round trip proving the FastAPI wiring actually returns 429.

SOS, invitation creation/acceptance and device registration had no defense
before this — see app.api.rate_limit for why a DB counter, not an in-memory
one.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from app.api.rate_limit import _enforce
from app.core.errors import RateLimited
from app.db.base import utcnow
from app.models.rate_limit import RateLimitEvent
from tests.factories import create_family


async def test_requests_under_the_limit_are_allowed(session):
    for _ in range(5):
        await _enforce(
            session, bucket="widget_press", subject="user-a", limit=5, window_seconds=60
        )
    # The fifth call above is the fifth row: count was 4 (< 5) when it ran.
    stored = await session.scalar(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(
            RateLimitEvent.bucket == "widget_press",
            RateLimitEvent.subject == "user-a",
        )
    )
    assert stored == 5


async def test_the_call_that_reaches_the_limit_is_rejected(session):
    for _ in range(5):
        await _enforce(
            session, bucket="widget_press", subject="user-b", limit=5, window_seconds=60
        )
    try:
        await _enforce(
            session, bucket="widget_press", subject="user-b", limit=5, window_seconds=60
        )
        raise AssertionError("expected RateLimited")
    except RateLimited:
        pass


async def test_buckets_and_subjects_are_isolated(session):
    """A limit on one action, or one user, never bleeds into another."""
    for _ in range(5):
        await _enforce(
            session, bucket="bucket_a", subject="user-c", limit=5, window_seconds=60
        )
    # A different bucket, same subject: fresh budget.
    await _enforce(
        session, bucket="bucket_b", subject="user-c", limit=5, window_seconds=60
    )
    # The same bucket, a different subject: also a fresh budget.
    await _enforce(
        session, bucket="bucket_a", subject="user-d", limit=5, window_seconds=60
    )


async def test_a_call_outside_the_window_does_not_count(session):
    old = utcnow() - dt.timedelta(seconds=120)
    for _ in range(5):
        await _enforce(
            session,
            bucket="widget_press",
            subject="user-e",
            limit=5,
            window_seconds=60,
            now=old,
        )
    # All five events are 120s old; a 60s window starting now sees none of
    # them, so this call is allowed rather than rejected.
    await _enforce(
        session, bucket="widget_press", subject="user-e", limit=5, window_seconds=60
    )


async def test_sos_returns_429_over_http_once_the_limit_is_reached(client):
    """One full round trip through the actual route, not just the helper —
    proving the dependency is wired, and that ApiError maps to a real 429."""
    family = await create_family(client)
    for _ in range(10):
        response = await client.post(
            f"/api/v1/seniors/{family.senior_id}/sos",
            json={},
            headers=family.headers(),
        )
        assert response.status_code == 201, response.text

    response = await client.post(
        f"/api/v1/seniors/{family.senior_id}/sos",
        json={},
        headers=family.headers(),
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
