"""The queue's guarantees, tested as guarantees rather than as code paths.

Each test here corresponds to something that would go wrong in production if it
were not true: two workers running one job, a dead worker taking a medication
reminder with it, a retry storm, a job that fails forever.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.jobs.queue import (
    DatabaseJobQueue,
    PermanentJobError,
    RetryableJobError,
    backoff_seconds,
)
from app.jobs.registry import JobContext, handler
from app.jobs.runner import Worker
from app.jobs.scheduler import SCHEDULES, bucket_key, enqueue_due_maintenance
from app.models.enums import JobStatus
from app.models.jobs import BackgroundJob

# Handlers used only by this module. Registered once at import; the registry
# refuses a second registration of the same name, which is itself the guard
# against two features quietly claiming one job type.
CALLS: dict[str, int] = {}


@handler("test.counts")
async def _counting_handler(ctx: JobContext) -> None:
    key = str(ctx.payload.get("key", "default"))
    CALLS[key] = CALLS.get(key, 0) + 1


@handler("test.always_fails")
async def _always_fails(ctx: JobContext) -> None:
    raise RetryableJobError("provider_down")


@handler("test.permanently_broken")
async def _permanently_broken(ctx: JobContext) -> None:
    raise PermanentJobError("payload_unreadable")


@handler("test.explodes")
async def _explodes(ctx: JobContext) -> None:
    raise RuntimeError("secret detail that must not be stored: token=abc123")


@pytest.fixture(autouse=True)
def _reset_calls():
    CALLS.clear()
    yield
    CALLS.clear()


async def test_a_dedupe_key_produces_one_job(job_queue):
    first = await job_queue.enqueue("test.counts", dedupe_key="tick:1")
    second = await job_queue.enqueue("test.counts", dedupe_key="tick:1")
    third = await job_queue.enqueue("test.counts", dedupe_key="tick:2")

    assert first is not None
    # The second call is not an error. The job the caller wanted is queued.
    assert second is None
    assert third is not None


async def test_a_dedupe_key_is_reusable_once_its_job_finished(job_queue, run_worker):
    await job_queue.enqueue("test.counts", dedupe_key="tick:1")
    await run_worker()

    # Uniqueness is scoped to live jobs, so the next hour's identical tick is
    # allowed through rather than silently dropped forever.
    again = await job_queue.enqueue("test.counts", dedupe_key="tick:1")
    assert again is not None


async def test_the_partial_index_rejects_two_live_rows_directly(session):
    """Bypass the service check and confirm the database is the real authority.

    Mirrors ``test_jobs_postgres.py``'s test of the same name — added after
    that PostgreSQL-only test caught the predicate matching nothing on either
    dialect (see migration ``0013``). Nothing before this distinguished
    SQLite from PostgreSQL here, so nothing did either.
    """
    from sqlalchemy.exc import IntegrityError

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
    # The `session` fixture commits again on teardown; leaving the session in
    # its post-failure state would turn that into a second, unrelated error.
    await session.rollback()


async def test_only_one_worker_claims_a_job(sessionmaker, worker_settings):
    """Two workers, one job, one claim. The other gets nothing."""
    queue_a = DatabaseJobQueue(sessionmaker, settings=worker_settings)
    queue_b = DatabaseJobQueue(sessionmaker, settings=worker_settings)
    await queue_a.enqueue("test.counts", payload={"key": "contended"})

    first, second = await asyncio.gather(
        queue_a.claim(worker_id="a", limit=5, lease_seconds=30),
        queue_b.claim(worker_id="b", limit=5, lease_seconds=30),
    )

    claimed = [job for batch in (first, second) for job in batch]
    assert len(claimed) == 1


async def test_a_claim_counts_the_attempt_and_takes_a_lease(job_queue, session):
    job_id = await job_queue.enqueue("test.counts")
    claimed = await job_queue.claim(worker_id="w1", limit=5, lease_seconds=30)

    assert [job.id for job in claimed] == [job_id]
    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.RUNNING
    assert row.attempt_count == 1
    assert row.locked_by == "w1"
    assert row.lock_expires_at is not None


async def test_a_failure_is_retried_with_a_later_run_after(
    sessionmaker, worker_settings, session
):
    # A realistic backoff here rather than the suite's millisecond one, because
    # what is being asserted is that the retry is deferred at all.
    queue = DatabaseJobQueue(
        sessionmaker,
        settings=worker_settings.model_copy(
            update={"job_retry_base_seconds": 30.0, "job_retry_max_seconds": 300.0}
        ),
    )
    job_id = await queue.enqueue("test.always_fails", max_attempts=3)
    await queue.claim(worker_id="w1", limit=1, lease_seconds=30)
    await queue.fail(job_id, error_code="provider_down")

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.QUEUED
    assert row.last_error_code == "provider_down"
    assert row.run_after > utcnow() + dt.timedelta(seconds=10)
    assert row.locked_by is None


async def test_a_job_dies_after_its_last_attempt(job_queue, session, run_worker):
    job_id = await job_queue.enqueue("test.always_fails", max_attempts=2)

    # Two attempts, each retried with a backoff of milliseconds in tests.
    for _ in range(3):
        await run_worker()
        row = await session.get(BackgroundJob, job_id)
        await session.refresh(row)
        if row.status is JobStatus.FAILED:
            break
        await asyncio.sleep(0.06)

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.FAILED
    assert row.attempt_count == 2
    assert row.last_error_code == "provider_down"
    assert row.completed_at is not None


async def test_a_permanent_failure_skips_the_remaining_attempts(
    job_queue, session, run_worker
):
    job_id = await job_queue.enqueue("test.permanently_broken", max_attempts=5)
    await run_worker()

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.FAILED
    # One attempt, not five: retrying an unreadable payload cannot help.
    assert row.attempt_count == 1
    assert row.last_error_code == "payload_unreadable"


async def test_an_unexpected_exception_is_not_stored_in_the_error_code(
    job_queue, session, run_worker
):
    """A traceback can contain anything. Only a fixed code reaches the row."""
    job_id = await job_queue.enqueue("test.explodes", max_attempts=1)
    await run_worker()

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.FAILED
    assert row.last_error_code == "unhandled_error"
    assert "token=abc123" not in (row.last_error_code or "")


async def test_an_expired_lease_is_recovered(job_queue, session):
    """A worker that died holding a job must not take the job with it."""
    job_id = await job_queue.enqueue("test.counts")
    await job_queue.claim(worker_id="doomed", limit=1, lease_seconds=30)

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    row.lock_expires_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    recovered = await job_queue.recover_expired_leases()
    assert recovered == 1

    await session.refresh(row)
    assert row.status is JobStatus.QUEUED
    assert row.locked_by is None
    assert row.last_error_code == "lease_expired"


async def test_a_restarted_worker_finishes_what_the_dead_one_held(
    sessionmaker, worker_settings, job_queue, session
):
    """The whole point of leases: a restart loses time, not work."""
    await job_queue.enqueue("test.counts", payload={"key": "orphaned"})
    claimed = await job_queue.claim(worker_id="dead-worker", limit=1, lease_seconds=30)
    assert len(claimed) == 1
    assert CALLS.get("orphaned") is None

    row = await session.get(BackgroundJob, claimed[0].id)
    await session.refresh(row)
    row.lock_expires_at = utcnow() - dt.timedelta(seconds=1)
    await session.commit()

    replacement = Worker(
        sessionmaker, settings=worker_settings, worker_id="fresh-worker",
        queue=job_queue,
    )
    await replacement.queue.recover_expired_leases()
    await replacement.run_once()

    assert CALLS.get("orphaned") == 1
    await session.refresh(row)
    assert row.status is JobStatus.SUCCEEDED


async def test_a_lease_can_only_be_extended_by_its_holder(job_queue):
    job_id = await job_queue.enqueue("test.counts")
    await job_queue.claim(worker_id="owner", limit=1, lease_seconds=30)

    assert await job_queue.heartbeat(job_id, worker_id="owner", lease_seconds=30) is True
    assert (
        await job_queue.heartbeat(job_id, worker_id="impostor", lease_seconds=30) is False
    )


async def test_a_released_job_is_claimable_again(job_queue, session):
    """Graceful shutdown hands work back rather than sitting on it."""
    job_id = await job_queue.enqueue("test.counts")
    await job_queue.claim(worker_id="stopping", limit=1, lease_seconds=300)
    await job_queue.release(job_id)

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.QUEUED
    assert row.locked_by is None


async def test_priority_decides_what_runs_first(job_queue):
    await job_queue.enqueue("test.counts", payload={"key": "routine"}, priority=100)
    await job_queue.enqueue("test.counts", payload={"key": "emergency"}, priority=1)

    claimed = await job_queue.claim(worker_id="w1", limit=1, lease_seconds=30)
    assert claimed[0].payload["key"] == "emergency"


async def test_a_future_job_is_not_claimed_yet(job_queue):
    await job_queue.enqueue(
        "test.counts", run_after=utcnow() + dt.timedelta(minutes=5)
    )
    assert await job_queue.claim(worker_id="w1", limit=5, lease_seconds=30) == []


async def test_backoff_grows_and_is_capped(worker_settings):
    settings = worker_settings.model_copy(
        update={"job_retry_base_seconds": 10.0, "job_retry_max_seconds": 100.0}
    )
    first = backoff_seconds(1, settings)
    later = backoff_seconds(9, settings)

    # Jittered, so the assertions are on the band rather than an exact value.
    assert 5.0 <= first <= 10.0
    assert 50.0 <= later <= 100.0


async def test_maintenance_ticks_are_deduped_within_their_bucket(job_queue):
    now = utcnow()
    first = await enqueue_due_maintenance(job_queue, now=now)
    second = await enqueue_due_maintenance(job_queue, now=now)

    assert first == len(SCHEDULES)
    # The same bucket produces nothing new, which is what makes it safe for the
    # worker to call this on every pass.
    assert second == 0


async def test_a_later_bucket_queues_the_tick_again(job_queue, run_worker):
    now = utcnow()
    await enqueue_due_maintenance(job_queue, now=now)
    await run_worker()
    later = await enqueue_due_maintenance(job_queue, now=now + dt.timedelta(hours=1))

    assert later == len(SCHEDULES)


def test_a_bucket_key_is_stable_within_its_interval():
    base = dt.datetime(2026, 8, 17, 10, 0, 0, tzinfo=dt.UTC)
    within = base + dt.timedelta(seconds=299)
    after = base + dt.timedelta(seconds=301)
    assert bucket_key("x", 300, base) == bucket_key("x", 300, within)
    assert bucket_key("x", 300, base) != bucket_key("x", 300, after)


async def test_a_job_newer_than_the_worker_is_refused_permanently(
    job_queue, session, run_worker
):
    """A rolling deploy must not let an old worker misread a new payload."""
    job_id = await job_queue.enqueue("test.counts", schema_version=99)
    await run_worker()

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.FAILED
    assert row.last_error_code == "schema_version_unsupported"


async def test_an_unregistered_job_type_fails_permanently(job_queue, session, run_worker):
    job_id = await job_queue.enqueue("test.no_such_handler")
    await run_worker()

    row = await session.get(BackgroundJob, job_id)
    await session.refresh(row)
    assert row.status is JobStatus.FAILED
    assert row.last_error_code == "unknown_job_type"


async def test_a_job_carries_its_request_id(client, session, run_worker):
    """One user-visible failure has to be followable into the worker's logs."""
    from tests.factories import add_medication, create_family

    family = await create_family(client)
    await add_medication(client, family)

    job = (
        await session.execute(
            select(BackgroundJob).where(BackgroundJob.job_type == "doses.materialize")
        )
    ).scalars().first()
    assert job is not None
    assert job.request_id


def test_the_production_claim_really_uses_skip_locked():
    """Compile the PostgreSQL statement without needing a server.

    ``FOR UPDATE SKIP LOCKED`` is the entire mutual-exclusion guarantee on the
    production path, and SQLite cannot express it — so on a machine with no
    PostgreSQL this is the check that the clause has not quietly been lost.
    ``test_jobs_postgres.py`` runs the statement for real when a server is
    configured.
    """
    from sqlalchemy.dialects import postgresql

    from app.jobs.queue import postgres_claim_statement

    statement = postgres_claim_statement(
        worker_id="w1", limit=5, lease_seconds=60, now=utcnow()
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "RETURNING" in sql
    assert "UPDATE background_jobs" in sql
    # The attempt is counted by the same statement that takes the lease, so a
    # worker cannot claim a job without recording that it tried.
    assert "attempt_count" in sql


async def test_the_worker_stops_without_abandoning_work(sessionmaker, worker_settings):
    worker = Worker(sessionmaker, settings=worker_settings, worker_id="graceful")
    worker.request_stop()

    # A worker asked to stop before it starts must return, not block forever.
    await asyncio.wait_for(worker.run(), timeout=5)
    assert worker.stopping
