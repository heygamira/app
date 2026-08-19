"""What a wake word that came to nothing is allowed to cost.

The detector pre-connects on a *maybe* so that a real "Gamira" is answered
immediately rather than after a second of silence. That is worth doing, and it
means most sessions this backend opens are guesses that will be thrown away.

Which is fine as long as a guess is cheap. It was not. Each one mints a real
ephemeral token, and each abandoned one queued a background job to read back a
conversation in which nobody had said a word — while the only ceiling on how
many could be opened was a constant in browser JavaScript.

These tests are about the ceiling being on this side of the wire.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.jobs.types import JobType
from app.models.ai import LiveSession
from app.models.enums import JobStatus
from app.models.jobs import BackgroundJob
from tests.conftest import auth
from tests.factories import create_family, join, link_senior_account


async def _senior(client, session, *, subject: str = "the-senior"):
    family = await create_family(client)
    await join(client, family, subject=subject, role="viewer")
    await link_senior_account(session, family.senior_id, subject)
    return family, subject


async def _guess(client, subject: str):
    return await client.post(
        "/api/v1/ai/live-sessions",
        json={"provisional": True},
        headers=auth(subject),
    )


async def _reviews(session) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.job_type == JobType.AI_CONVERSATION_REVIEW,
                BackgroundJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        or 0
    )


async def test_an_abandoned_guess_asks_nobody_to_read_it_back(client, session):
    """Nothing was said, so there is nothing to read back.

    `expire_stale_sessions` always knew this; `close_live_session` did not, and
    that is the path an abandoned guess actually takes — so every wake word the
    detector got wrong queued a job to review an empty conversation.
    """
    family, subject = await _senior(client, session)

    opened = await _guess(client, subject)
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["session_id"]

    closed = await client.post(
        f"/api/v1/ai/live-sessions/{session_id}/close", headers=auth(subject)
    )
    assert closed.status_code in (200, 204), closed.text

    assert await _reviews(session) == 0


async def test_a_real_conversation_is_still_read_back(client, session):
    """The guard is about guesses and must not quieten anything else."""
    family, subject = await _senior(client, session)

    opened = await client.post(
        "/api/v1/ai/live-sessions", json={}, headers=auth(subject)
    )
    session_id = opened.json()["session_id"]
    await client.post(
        f"/api/v1/ai/live-sessions/{session_id}/close", headers=auth(subject)
    )

    assert await _reviews(session) == 1


async def test_guesses_are_capped_on_the_server(client, session, monkeypatch):
    """A limit that ships in the client is not a limit.

    The client throttles itself, and should. But the browser is the one thing
    here that a person can change, reload or run twenty copies of, and every
    guess mints a token from a paid API.
    """
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "live_provisional_per_hour", 3, raising=False)

    family, subject = await _senior(client, session)

    for attempt in range(3):
        response = await _guess(client, subject)
        assert response.status_code == 201, f"guess {attempt}: {response.text}"
        await client.post(
            f"/api/v1/ai/live-sessions/{response.json()['session_id']}/close",
            headers=auth(subject),
        )

    refused = await _guess(client, subject)
    assert refused.status_code == 429, refused.text
    # Worded about listening, because it is not something the person did.
    assert "listening" in refused.text.lower()


async def test_guesses_do_not_spend_the_conversation_allowance(
    client, session, monkeypatch
):
    """Being mis-heard must never stop somebody actually talking to her."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "live_sessions_per_hour", 2, raising=False)
    monkeypatch.setattr(settings, "live_provisional_per_hour", 50, raising=False)

    family, subject = await _senior(client, session)

    for _ in range(5):
        response = await _guess(client, subject)
        assert response.status_code == 201
        await client.post(
            f"/api/v1/ai/live-sessions/{response.json()['session_id']}/close",
            headers=auth(subject),
        )

    real = await client.post("/api/v1/ai/live-sessions", json={}, headers=auth(subject))
    assert real.status_code == 201, real.text

    guesses = int(
        await session.scalar(
            select(func.count())
            .select_from(LiveSession)
            .where(LiveSession.provisional.is_(True))
        )
        or 0
    )
    assert guesses == 5
