"""The worker loop.

Responsibilities, in the order they matter:

1. Never run one job twice at once — that is the queue's ``claim``.
2. Never lose a job because a process died — leases expire and are recovered.
3. Never wedge on one slow job — each job gets its own task, its own session
   and its own lease heartbeat.
4. Shut down without abandoning work — on a signal it stops claiming, lets
   in-flight jobs finish, and hands back anything it had not started.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import get_logger, request_id_var
from app.jobs.queue import (
    DatabaseJobQueue,
    JobRecord,
    JobResult,
    PermanentJobError,
    RetryableJobError,
)
from app.jobs.registry import (
    CURRENT_SCHEMA_VERSION,
    JobContext,
    get_handler,
    load_handlers,
)
from app.jobs.scheduler import enqueue_due_maintenance

logger = get_logger("app.worker")


def default_worker_id() -> str:
    """Host and pid, so a log line points at a machine you can go and look at."""
    return f"{socket.gethostname()[:32]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


class Worker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        settings: Settings | None = None,
        worker_id: str | None = None,
        queue: DatabaseJobQueue | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sessionmaker = sessionmaker
        self.worker_id = worker_id or default_worker_id()
        self.queue = queue or DatabaseJobQueue(sessionmaker, settings=self.settings)
        self._stopping = asyncio.Event()
        self._in_flight: set[asyncio.Task[None]] = set()
        self._last_scheduler_tick = 0.0
        self.processed = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def request_stop(self) -> None:
        if not self._stopping.is_set():
            logger.info("worker_stop_requested", extra={"worker_id": self.worker_id})
        self._stopping.set()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    async def run(self) -> None:
        load_handlers()
        logger.info(
            "worker_started",
            extra={
                "worker_id": self.worker_id,
                "concurrency": self.settings.worker_concurrency,
                "lease_seconds": self.settings.worker_lease_seconds,
                "scheduler": self.settings.worker_run_scheduler,
            },
        )
        # Anything a previous worker was holding when it died is ours to take.
        await self.queue.recover_expired_leases()

        try:
            while not self.stopping:
                worked = await self.tick()
                if self.stopping:
                    break
                if not worked:
                    await self._sleep(self.settings.worker_poll_interval_seconds)
        finally:
            await self._drain()
            logger.info(
                "worker_stopped",
                extra={"worker_id": self.worker_id, "processed": self.processed},
            )

    async def tick(self) -> bool:
        """One pass: maintenance, lease recovery, claim, dispatch.

        Returns True when it found work, so the caller can poll immediately
        rather than sleeping.
        """
        await self._maybe_schedule()
        capacity = self.settings.worker_concurrency - len(self._in_flight)
        if capacity <= 0:
            await self._await_one()
            return True

        limit = min(capacity, self.settings.worker_batch_size)
        jobs = await self.queue.claim(
            worker_id=self.worker_id,
            limit=limit,
            lease_seconds=self.settings.worker_lease_seconds,
        )
        if not jobs:
            return False

        for job in jobs:
            task = asyncio.create_task(self._run_job(job), name=f"job-{job.id}")
            self._in_flight.add(task)
            task.add_done_callback(self._in_flight.discard)
        return True

    async def run_once(self) -> int:
        """Claim and finish everything currently ready. Used by tests and CLI."""
        load_handlers()
        total = 0
        while True:
            jobs = await self.queue.claim(
                worker_id=self.worker_id,
                limit=self.settings.worker_batch_size,
                lease_seconds=self.settings.worker_lease_seconds,
            )
            if not jobs:
                return total
            for job in jobs:
                await self._run_job(job)
                total += 1

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    async def _run_job(self, job: JobRecord) -> None:
        # Every log line and audit row this job writes carries the request id of
        # whatever caused it, so an API failure and its background consequence
        # sit under one id.
        token = request_id_var.set(job.request_id or f"job:{job.id}")
        started = time.perf_counter()
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        log_fields: dict[str, Any] = {
            "job_id": str(job.id),
            "job_type": job.job_type,
            "attempt": job.attempt_count,
            "worker_id": self.worker_id,
        }
        try:
            result = await self._invoke(job)
            await self.queue.complete(job.id, result=result)
            self.processed += 1
            logger.info(
                "job_succeeded",
                extra={
                    **log_fields,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    **(result.metrics if result else {}),
                },
            )
        except PermanentJobError as exc:
            await self.queue.fail(job.id, error_code=exc.code, retryable=False)
            logger.error(
                "job_failed_permanently",
                extra={**log_fields, "error_code": exc.code},
            )
        except RetryableJobError as exc:
            await self.queue.fail(
                job.id,
                error_code=exc.code,
                retryable=True,
                retry_after_seconds=exc.retry_after_seconds,
            )
            logger.warning("job_failed", extra={**log_fields, "error_code": exc.code})
        except asyncio.CancelledError:
            await self.queue.release(job.id)
            raise
        except Exception as exc:
            # The message may contain anything the failing library chose to put
            # in it, so it goes to the log with a traceback and never into the
            # stored error code.
            logger.exception(
                "job_errored", extra={**log_fields, "error": type(exc).__name__}
            )
            await self.queue.fail(job.id, error_code="unhandled_error", retryable=True)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            request_id_var.reset(token)

    async def _invoke(self, job: JobRecord) -> JobResult | None:
        if job.schema_version > CURRENT_SCHEMA_VERSION:
            raise PermanentJobError(
                "schema_version_unsupported",
                f"Job schema v{job.schema_version} is newer than this worker.",
            )
        func = get_handler(job.job_type)
        async with self.sessionmaker() as session:
            context = JobContext(
                job=job, session=session, queue=self.queue, settings=self.settings
            )
            try:
                result = await func(context)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            return result

    async def _heartbeat(self, job_id: uuid.UUID) -> None:
        """Keep the lease alive while the handler is still working.

        Renewed at a third of the lease so two consecutive missed renewals do
        not hand the job to another worker while this one is mid-write.
        """
        interval = max(1.0, self.settings.worker_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            held = await self.queue.heartbeat(
                job_id,
                worker_id=self.worker_id,
                lease_seconds=self.settings.worker_lease_seconds,
            )
            if not held:
                logger.warning("job_lease_lost", extra={"job_id": str(job_id)})
                return

    # ------------------------------------------------------------------ #
    # Housekeeping
    # ------------------------------------------------------------------ #

    async def _maybe_schedule(self) -> None:
        if not self.settings.worker_run_scheduler:
            return
        now = time.monotonic()
        interval = self.settings.worker_scheduler_interval_seconds
        if now - self._last_scheduler_tick < interval:
            return
        self._last_scheduler_tick = now
        await self.queue.recover_expired_leases()
        await enqueue_due_maintenance(self.queue, settings=self.settings)

    async def _await_one(self) -> None:
        if not self._in_flight:
            return
        await asyncio.wait(self._in_flight, return_when=asyncio.FIRST_COMPLETED)

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately if a shutdown is requested."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    async def _drain(self) -> None:
        if not self._in_flight:
            return
        logger.info("worker_draining", extra={"in_flight": len(self._in_flight)})
        done, pending = await asyncio.wait(
            self._in_flight, timeout=self.settings.worker_shutdown_grace_seconds
        )
        for task in pending:
            # Past the grace period the job is cancelled, which releases its
            # lease immediately rather than making the next worker wait it out.
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5)
        logger.info(
            "worker_drained", extra={"finished": len(done), "cancelled": len(pending)}
        )


__all__ = ["Worker", "default_worker_id"]
