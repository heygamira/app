"""The handler registry and the context a handler is given.

A handler is an async function that receives one ``JobContext`` and returns an
optional ``JobResult``. It gets a database session and the queue — nothing
else. In particular it does not get a request, a user or an authorization
decision: a job runs on behalf of the system, and any permission it needs is
re-derived from persisted rows at execution time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.jobs.queue import JobQueue, JobRecord, JobResult, PermanentJobError

# The payload shape a handler understands. A job carrying a newer version than
# the worker knows is failed permanently rather than misread.
CURRENT_SCHEMA_VERSION = 1


@dataclass
class JobContext:
    job: JobRecord
    session: AsyncSession
    queue: JobQueue
    settings: Settings

    @property
    def payload(self) -> dict:
        return self.job.payload


JobHandler = Callable[[JobContext], Awaitable[JobResult | None]]

_HANDLERS: dict[str, JobHandler] = {}


def handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    """Register an async function as the handler for one job type."""

    def decorate(func: JobHandler) -> JobHandler:
        if job_type in _HANDLERS and _HANDLERS[job_type] is not func:
            raise RuntimeError(f"Two handlers registered for job type {job_type!r}.")
        _HANDLERS[job_type] = func
        return func

    return decorate


def get_handler(job_type: str) -> JobHandler:
    try:
        return _HANDLERS[job_type]
    except KeyError:
        raise PermanentJobError(
            "unknown_job_type", f"No handler is registered for {job_type!r}."
        ) from None


def registered_job_types() -> list[str]:
    return sorted(_HANDLERS)


def load_handlers() -> None:
    """Import the modules that register handlers.

    Kept as an explicit call rather than an import-time side effect so the API
    process does not drag the worker's dependencies into every request.
    """
    from app.jobs import handlers

    if hasattr(handlers, "__all__"):  # pragma: no cover - defensive
        pass


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "JobContext",
    "JobHandler",
    "get_handler",
    "handler",
    "load_handlers",
    "registered_job_types",
]
