"""Cross-process realtime delivery, against a real PostgreSQL.

SQLite proves nothing about this path: `realtime.publish_family_event`'s
Postgres branch does not exist on SQLite, and the in-memory path it falls
back to there is single-process by construction. This module runs the real
`pg_notify`/`LISTEN` path, using a second raw connection to stand in for a
second API process — the same relationship `test_jobs_postgres.py` uses for
the locking path.

Skipped unless a server is configured:

    $env:TEST_POSTGRES_URL = 'postgresql+asyncpg://gamira:gamira@localhost:5432/gamira_test'
    python -m pytest tests/test_realtime_postgres.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.services import realtime

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Set TEST_POSTGRES_URL to exercise the PostgreSQL realtime path.",
)


@pytest.fixture
async def pg_sessionmaker():  # type: ignore[no-untyped-def]
    """No schema needed: `pg_notify` touches no table."""
    engine = create_async_engine(POSTGRES_URL, poolclass=None)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - unreachable server
        await engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {type(exc).__name__}")
    yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest.fixture
def pg_settings():  # type: ignore[no-untyped-def]
    return get_settings().model_copy(update={"database_url": POSTGRES_URL})


@pytest.fixture
async def pg_listener():  # type: ignore[no-untyped-def]
    """A second, raw connection LISTEN-ing on the shared channel — standing
    in for a second API process's `realtime.start_listener` connection."""
    conn = await asyncpg.connect(realtime._pg_dsn(POSTGRES_URL))
    received: list[dict] = []
    await conn.add_listener(
        realtime.CHANNEL,
        lambda _c, _pid, _channel, payload: received.append(json.loads(payload)),
    )
    yield received
    await conn.close()


async def _wait_for(
    received: list[dict], count: int, *, timeout_seconds: float = 2.0
) -> None:
    elapsed = 0.0
    step = 0.05
    while len(received) < count and elapsed < timeout_seconds:
        await asyncio.sleep(step)
        elapsed += step


async def test_a_committed_event_reaches_a_separate_connection(
    pg_sessionmaker, pg_settings, pg_listener
):
    family_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    async with pg_sessionmaker() as session:
        await realtime.publish_family_event(
            session,
            family_id,
            "alert_raised",
            entity_type="alert",
            entity_id=entity_id,
            settings=pg_settings,
        )
        await session.commit()

    await _wait_for(pg_listener, 1)

    assert len(pg_listener) == 1
    event = pg_listener[0]
    assert event["family_id"] == str(family_id)
    assert event["kind"] == "alert_raised"
    assert event["entity_type"] == "alert"
    assert event["entity_id"] == str(entity_id)


async def test_a_rolled_back_event_is_never_delivered(
    pg_sessionmaker, pg_settings, pg_listener
):
    family_id = uuid.uuid4()

    async with pg_sessionmaker() as session:
        await realtime.publish_family_event(
            session, family_id, "alert_raised", settings=pg_settings
        )
        await session.rollback()

    # Give a real notification every chance to arrive before concluding it
    # didn't: this is the negative-case counterpart to _wait_for above.
    await asyncio.sleep(0.5)

    assert pg_listener == []


async def test_start_listener_delivers_into_a_local_subscriber(
    pg_sessionmaker, pg_settings
):
    """The actual production path: `start_listener`'s own connection, not a
    hand-rolled one, receiving a NOTIFY and landing it in the same in-memory
    `_subscribers` map `events.py`'s SSE endpoint reads from — proving the
    two processes' worth of plumbing this feature exists for, not just the
    raw `pg_notify`/`LISTEN` primitives underneath it."""
    family_id = uuid.uuid4()
    queue = realtime.subscribe(family_id)
    try:
        task = realtime.start_listener(pg_settings)
        assert task is not None
        try:
            # start_listener's connect-and-LISTEN happens on the task; give it
            # a moment to actually be listening before publishing.
            await asyncio.sleep(0.3)

            async with pg_sessionmaker() as session:
                await realtime.publish_family_event(
                    session,
                    family_id,
                    "device_flag_raised",
                    entity_type="notification",
                    settings=pg_settings,
                )
                await session.commit()

            event = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert event["family_id"] == str(family_id)
            assert event["kind"] == "device_flag_raised"
        finally:
            await realtime.stop_listener()
    finally:
        realtime.unsubscribe(family_id, queue)
