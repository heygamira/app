"""The production locking path, against a real PostgreSQL.

SQLite proves the *contract* — one claim per job — with a compare-and-swap. It
cannot prove the statement the production path actually runs, because it has no
``FOR UPDATE SKIP LOCKED``. This module runs the real thing.

Skipped unless a server is configured:

    $env:TEST_POSTGRES_URL = 'postgresql+asyncpg://gamira:gamira@localhost:5432/gamira_test'
    python -m pytest tests/test_jobs_postgres.py

``docker compose up -d postgres`` at the repo root brings one up.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base, utcnow
from app.jobs.queue import DatabaseJobQueue
from app.models.enums import JobStatus
from app.models.jobs import BackgroundJob

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Set TEST_POSTGRES_URL to exercise the PostgreSQL locking path.",
)


@pytest.fixture
async def pg_sessionmaker():  # type: ignore[no-untyped-def]
    """A clean schema on the configured PostgreSQL, dropped afterwards."""
    engine = create_async_engine(POSTGRES_URL, poolclass=None)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - unreachable server
        await engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {type(exc).__name__}")
    yield async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def pg_settings():  # type: ignore[no-untyped-def]
    # is_sqlite is False for this URL, which is what selects the SKIP LOCKED
    # implementation inside DatabaseJobQueue.
    return get_settings().model_copy(update={"database_url": POSTGRES_URL})


async def test_the_dialect_selects_the_skip_locked_path(pg_sessionmaker, pg_settings):
    queue = DatabaseJobQueue(pg_sessionmaker, settings=pg_settings)
    assert queue.dialect == "postgresql"


async def test_concurrent_workers_take_disjoint_batches(pg_sessionmaker, pg_settings):
    """The property that matters: no job is claimed twice, none is lost."""
    queue = DatabaseJobQueue(pg_sessionmaker, settings=pg_settings)
    total = 40
    for index in range(total):
        await queue.enqueue("test.counts", payload={"index": index})

    batches = await asyncio.gather(
        *[
            DatabaseJobQueue(pg_sessionmaker, settings=pg_settings).claim(
                worker_id=f"worker-{worker}", limit=10, lease_seconds=30
            )
            for worker in range(6)
        ]
    )

    claimed = [job.id for batch in batches for job in batch]
    assert len(claimed) == len(set(claimed)), "a job was claimed by two workers"
    assert len(claimed) == min(total, 60)

    async with pg_sessionmaker() as session:
        running = await session.execute(
            select(BackgroundJob.locked_by).where(
                BackgroundJob.status == JobStatus.RUNNING
            )
        )
        holders = list(running.scalars())
    assert len(holders) == len(claimed)


async def test_a_dedupe_key_is_unique_only_while_live(pg_sessionmaker, pg_settings):
    """The partial unique index, on the database that will actually enforce it."""
    queue = DatabaseJobQueue(pg_sessionmaker, settings=pg_settings)
    first = await queue.enqueue("test.counts", dedupe_key="cron:tick:1")
    duplicate = await queue.enqueue("test.counts", dedupe_key="cron:tick:1")
    assert first is not None
    assert duplicate is None

    await queue.claim(worker_id="w1", limit=1, lease_seconds=30)
    await queue.complete(first)

    reused = await queue.enqueue("test.counts", dedupe_key="cron:tick:1")
    assert reused is not None


async def test_the_partial_index_rejects_two_live_rows_directly(
    pg_sessionmaker, pg_settings
):
    """Bypass the service check and confirm the database is the real authority."""
    from sqlalchemy.exc import IntegrityError

    async with pg_sessionmaker() as session:
        session.add(
            BackgroundJob(
                job_type="test.counts",
                payload={},
                dedupe_key="racy",
                run_after=utcnow(),
                max_attempts=1,
            )
        )
        await session.commit()

    async with pg_sessionmaker() as session:
        session.add(
            BackgroundJob(
                job_type="test.counts",
                payload={},
                dedupe_key="racy",
                run_after=utcnow(),
                max_attempts=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_expired_leases_are_recovered_on_postgres(pg_sessionmaker, pg_settings):
    queue = DatabaseJobQueue(pg_sessionmaker, settings=pg_settings)
    job_id = await queue.enqueue("test.counts")
    await queue.claim(worker_id="doomed", limit=1, lease_seconds=30)

    async with pg_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE background_jobs SET lock_expires_at = :past WHERE id = :id"
            ),
            {"past": utcnow() - dt.timedelta(seconds=5), "id": job_id},
        )
        await session.commit()

    assert await queue.recover_expired_leases() == 1
    reclaimed = await queue.claim(worker_id="fresh", limit=1, lease_seconds=30)
    assert [job.id for job in reclaimed] == [job_id]
    # The attempt from the dead worker still counts, so a job that kills workers
    # cannot cycle forever.
    assert reclaimed[0].attempt_count == 2
