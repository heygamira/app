"""The job queue: one interface, one database-backed implementation.

The interface is deliberately narrower than what a database can do, because
the whole point is that it can be re-implemented on Cloud Tasks later without
touching a single handler. ``enqueue`` is a dispatch request; ``claim`` is a
lease; ``complete``/``fail`` close the lease. Nothing else about how the work
is stored leaks out.

Claiming has two implementations of the same guarantee — no two workers ever
run one job at once:

* PostgreSQL uses ``SELECT ... FOR UPDATE SKIP LOCKED``, which is the real
  production path and the only one that stays correct under concurrent
  workers hitting the same rows.
* Everything else (SQLite, for the local test suite) uses a compare-and-swap
  update per row and keeps only the rows it actually won.

Both paths are exercised by the test suite; the PostgreSQL one has its own
test that skips when no server is configured.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import current_request_id, get_logger
from app.db.base import utcnow
from app.models.enums import LIVE_JOB_STATUSES, JobStatus
from app.models.jobs import BackgroundJob

logger = get_logger(__name__)

DEFAULT_PRIORITY = 100
# Reserved for work a person is waiting on, or an emergency.
URGENT_PRIORITY = 10


@dataclass(frozen=True)
class JobRecord:
    """A claimed job, detached from the session that produced it.

    Handlers receive this rather than the ORM row so they cannot quietly mutate
    queue bookkeeping while doing their own work.
    """

    id: uuid.UUID
    job_type: str
    schema_version: int
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    family_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None
    dedupe_key: str | None = None
    request_id: str | None = None
    priority: int = DEFAULT_PRIORITY

    @property
    def is_final_attempt(self) -> bool:
        return self.attempt_count >= self.max_attempts


@dataclass
class JobResult:
    """What a handler produced: a reference, never the content itself."""

    reference: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


class PermanentJobError(Exception):
    """Raised by a handler when retrying cannot possibly help.

    A malformed payload, a deleted senior, a permission that no longer exists:
    all of these fail the same way every time, so the job goes straight to
    ``failed`` instead of burning five attempts.
    """

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class RetryableJobError(Exception):
    """Raised by a handler when the same work may succeed later."""

    def __init__(
        self, code: str, message: str = "", retry_after_seconds: float | None = None
    ) -> None:
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message or code)


class JobQueue(Protocol):
    """What the worker needs from a queue. Nothing database-specific."""

    async def enqueue(
        self,
        job_type: str,
        *,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        priority: int = DEFAULT_PRIORITY,
        run_after: dt.datetime | None = None,
        family_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        max_attempts: int | None = None,
        schema_version: int = 1,
        request_id: str | None = None,
    ) -> uuid.UUID | None: ...

    async def claim(
        self, *, worker_id: str, limit: int, lease_seconds: int
    ) -> list[JobRecord]: ...

    async def heartbeat(
        self, job_id: uuid.UUID, *, worker_id: str, lease_seconds: int
    ) -> bool: ...

    async def complete(
        self, job_id: uuid.UUID, *, result: JobResult | None = None
    ) -> None: ...

    async def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> None: ...

    async def recover_expired_leases(self) -> int: ...

    async def release(self, job_id: uuid.UUID) -> None: ...


# --------------------------------------------------------------------------- #
# Enqueue inside a caller's transaction
# --------------------------------------------------------------------------- #


async def enqueue_job(
    session: AsyncSession,
    job_type: str,
    *,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    priority: int = DEFAULT_PRIORITY,
    run_after: dt.datetime | None = None,
    family_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    max_attempts: int | None = None,
    schema_version: int = 1,
    request_id: str | None = None,
) -> BackgroundJob | None:
    """Add a job to the caller's own transaction.

    API routes use this so the job and the state change that justifies it
    commit together: an SOS alert and its escalation check are either both
    durable or neither is. Returns ``None`` when an identical live job already
    exists.
    """
    settings = get_settings()
    if dedupe_key is not None:
        existing = await session.execute(
            select(BackgroundJob.id).where(
                BackgroundJob.dedupe_key == dedupe_key,
                BackgroundJob.status.in_(list(LIVE_JOB_STATUSES)),
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

    job = BackgroundJob(
        job_type=job_type,
        schema_version=schema_version,
        payload=payload or {},
        dedupe_key=dedupe_key,
        priority=priority,
        run_after=run_after or utcnow(),
        family_id=family_id,
        actor_user_id=actor_user_id,
        max_attempts=max_attempts or settings.job_max_attempts,
        request_id=(
            request_id if request_id is not None else (current_request_id() or None)
        ),
    )
    session.add(job)
    await session.flush()
    logger.info(
        "job_enqueued",
        extra={
            "job_id": str(job.id),
            "job_type": job_type,
            "dedupe_key": dedupe_key,
            "run_after": job.run_after.isoformat(),
        },
    )
    return job


def postgres_claim_statement(
    *, worker_id: str, limit: int, lease_seconds: int, now: dt.datetime
):
    """The production claim, as one statement.

    Built by a module-level function rather than inline so a test can compile it
    against the PostgreSQL dialect and assert that ``FOR UPDATE SKIP LOCKED`` is
    really in there — worth checking on a machine with no server, because that
    clause is the entire mutual-exclusion guarantee.
    """
    expires = now + dt.timedelta(seconds=lease_seconds)
    candidates = (
        select(BackgroundJob.id)
        .where(
            BackgroundJob.status == JobStatus.QUEUED,
            BackgroundJob.run_after <= now,
        )
        .order_by(BackgroundJob.priority, BackgroundJob.run_after)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return (
        update(BackgroundJob)
        .where(BackgroundJob.id.in_(candidates.scalar_subquery()))
        .values(
            status=JobStatus.RUNNING,
            locked_by=worker_id,
            lock_expires_at=expires,
            attempt_count=BackgroundJob.attempt_count + 1,
            started_at=now,
        )
        .returning(BackgroundJob)
        .execution_options(synchronize_session=False)
    )


# --------------------------------------------------------------------------- #
# Database-backed queue
# --------------------------------------------------------------------------- #


class DatabaseJobQueue:
    """``JobQueue`` on the same PostgreSQL the API writes to.

    One database means a job and the rows it depends on can never disagree, and
    it keeps the deployment to two processes rather than two processes plus a
    broker. The interface above is what a Cloud Tasks implementation would
    replace.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings or get_settings()

    @property
    def dialect(self) -> str:
        return "postgresql" if not self._settings.is_sqlite else "sqlite"

    async def enqueue(
        self,
        job_type: str,
        *,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        priority: int = DEFAULT_PRIORITY,
        run_after: dt.datetime | None = None,
        family_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        max_attempts: int | None = None,
        schema_version: int = 1,
        request_id: str | None = None,
    ) -> uuid.UUID | None:
        async with self._sessionmaker() as session:
            try:
                job = await enqueue_job(
                    session,
                    job_type,
                    payload=payload,
                    dedupe_key=dedupe_key,
                    priority=priority,
                    run_after=run_after,
                    family_id=family_id,
                    actor_user_id=actor_user_id,
                    max_attempts=max_attempts,
                    schema_version=schema_version,
                    request_id=request_id,
                )
                await session.commit()
            except IntegrityError:
                # Two processes raced past the existence check. The unique
                # index is the authority, and losing the race is a success:
                # the job the caller wanted is queued.
                await session.rollback()
                return None
            return job.id if job is not None else None

    async def claim(
        self, *, worker_id: str, limit: int, lease_seconds: int
    ) -> list[JobRecord]:
        if self.dialect == "postgresql":
            return await self._claim_postgres(
                worker_id=worker_id, limit=limit, lease_seconds=lease_seconds
            )
        return await self._claim_compare_and_swap(
            worker_id=worker_id, limit=limit, lease_seconds=lease_seconds
        )

    async def _claim_postgres(
        self, *, worker_id: str, limit: int, lease_seconds: int
    ) -> list[JobRecord]:
        """One statement, one lease. SKIP LOCKED does the mutual exclusion.

        Concurrent workers running this at the same instant take disjoint sets
        of rows: a row another transaction has locked is skipped rather than
        waited for, so no worker blocks and none double-claims.
        """
        now = utcnow()
        statement = postgres_claim_statement(
            worker_id=worker_id, limit=limit, lease_seconds=lease_seconds, now=now
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(statement)).scalars().all()
            await session.commit()
            return [_to_record(row) for row in rows]

    async def _claim_compare_and_swap(
        self, *, worker_id: str, limit: int, lease_seconds: int
    ) -> list[JobRecord]:
        """Read candidates, then win each one with a conditional update.

        SQLite has no ``SKIP LOCKED``. The update's ``status = 'queued'``
        predicate is the mutual exclusion instead: exactly one writer sees a
        row-count of 1, and a loser simply moves to the next candidate.
        """
        now = utcnow()
        expires = now + dt.timedelta(seconds=lease_seconds)
        claimed: list[JobRecord] = []
        async with self._sessionmaker() as session:
            candidates = (
                await session.execute(
                    select(BackgroundJob.id)
                    .where(
                        BackgroundJob.status == JobStatus.QUEUED,
                        BackgroundJob.run_after <= now,
                    )
                    .order_by(BackgroundJob.priority, BackgroundJob.run_after)
                    .limit(limit)
                )
            ).scalars().all()

            for job_id in candidates:
                result = await session.execute(
                    update(BackgroundJob)
                    .where(
                        BackgroundJob.id == job_id,
                        BackgroundJob.status == JobStatus.QUEUED,
                    )
                    .values(
                        status=JobStatus.RUNNING,
                        locked_by=worker_id,
                        lock_expires_at=expires,
                        attempt_count=BackgroundJob.attempt_count + 1,
                        started_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    continue
                row = await session.get(BackgroundJob, job_id)
                if row is not None:
                    claimed.append(_to_record(row))
            await session.commit()
        return claimed

    async def heartbeat(
        self, job_id: uuid.UUID, *, worker_id: str, lease_seconds: int
    ) -> bool:
        """Extend a lease we still hold. False means somebody else took it."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.id == job_id,
                    BackgroundJob.locked_by == worker_id,
                    BackgroundJob.status == JobStatus.RUNNING,
                )
                .values(lock_expires_at=utcnow() + dt.timedelta(seconds=lease_seconds))
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            return result.rowcount == 1

    async def complete(
        self, job_id: uuid.UUID, *, result: JobResult | None = None
    ) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status=JobStatus.SUCCEEDED,
                    completed_at=utcnow(),
                    locked_by=None,
                    lock_expires_at=None,
                    last_error_code=None,
                    result_reference=(result.reference if result else None),
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()

    async def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Retry with bounded backoff, or bury the job once attempts run out."""
        async with self._sessionmaker() as session:
            job = await session.get(BackgroundJob, job_id)
            if job is None:  # pragma: no cover - the row was deleted under us
                return
            exhausted = job.attempt_count >= job.max_attempts
            if not retryable or exhausted:
                job.status = JobStatus.FAILED
                job.completed_at = utcnow()
                job.locked_by = None
                job.lock_expires_at = None
                job.last_error_code = error_code[:64]
                logger.error(
                    "job_dead",
                    extra={
                        "job_id": str(job_id),
                        "job_type": job.job_type,
                        "error_code": error_code,
                        "attempt_count": job.attempt_count,
                        "retryable": retryable,
                    },
                )
            else:
                delay = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else backoff_seconds(job.attempt_count, self._settings)
                )
                job.status = JobStatus.QUEUED
                job.run_after = utcnow() + dt.timedelta(seconds=delay)
                job.locked_by = None
                job.lock_expires_at = None
                job.last_error_code = error_code[:64]
                logger.warning(
                    "job_retry_scheduled",
                    extra={
                        "job_id": str(job_id),
                        "job_type": job.job_type,
                        "error_code": error_code,
                        "attempt_count": job.attempt_count,
                        "retry_in_seconds": round(delay, 2),
                    },
                )
            await session.commit()

    async def recover_expired_leases(self) -> int:
        """Requeue work whose worker died.

        The attempt was already counted at claim time, so a job that reliably
        kills its worker still reaches ``max_attempts`` and stops instead of
        cycling forever.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.status == JobStatus.RUNNING,
                    BackgroundJob.lock_expires_at.is_not(None),
                    BackgroundJob.lock_expires_at < utcnow(),
                )
                .values(
                    status=JobStatus.QUEUED,
                    locked_by=None,
                    lock_expires_at=None,
                    last_error_code="lease_expired",
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            recovered = int(result.rowcount or 0)
        if recovered:
            logger.warning("job_leases_recovered", extra={"count": recovered})
        return recovered

    async def release(self, job_id: uuid.UUID) -> None:
        """Hand a claimed job straight back, unchanged, on shutdown."""
        async with self._sessionmaker() as session:
            await session.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.id == job_id, BackgroundJob.status == JobStatus.RUNNING
                )
                .values(status=JobStatus.QUEUED, locked_by=None, lock_expires_at=None)
                .execution_options(synchronize_session=False)
            )
            await session.commit()

    async def cancel(self, job_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.id == job_id, BackgroundJob.status == JobStatus.QUEUED
                )
                .values(status=JobStatus.CANCELLED, completed_at=utcnow())
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            return result.rowcount == 1

    async def get(self, job_id: uuid.UUID) -> BackgroundJob | None:
        async with self._sessionmaker() as session:
            return await session.get(BackgroundJob, job_id)


def backoff_seconds(attempt: int, settings: Settings | None = None) -> float:
    """Exponential backoff, capped, with jitter.

    Jitter matters here: without it, a hundred notification jobs failed by one
    provider outage would all retry in the same millisecond and fail again
    together.
    """
    settings = settings or get_settings()
    base = settings.job_retry_base_seconds
    cap = settings.job_retry_max_seconds
    raw = min(base * (2 ** max(0, attempt - 1)), cap)
    return raw * (0.5 + random.random() * 0.5)


def _to_record(row: BackgroundJob) -> JobRecord:
    return JobRecord(
        id=row.id,
        job_type=row.job_type,
        schema_version=row.schema_version,
        payload=dict(row.payload or {}),
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        family_id=row.family_id,
        actor_user_id=row.actor_user_id,
        dedupe_key=row.dedupe_key,
        request_id=row.request_id,
        priority=row.priority,
    )


def to_records(rows: Sequence[BackgroundJob]) -> list[JobRecord]:
    return [_to_record(row) for row in rows]


__all__ = [
    "DEFAULT_PRIORITY",
    "URGENT_PRIORITY",
    "DatabaseJobQueue",
    "JobQueue",
    "JobRecord",
    "JobResult",
    "PermanentJobError",
    "RetryableJobError",
    "backoff_seconds",
    "enqueue_job",
    "postgres_claim_statement",
]
