"""Durable background work.

``app.jobs.queue`` is the contract, ``app.jobs.handlers`` is the work, and
``app.worker`` is the process. FastAPI's ``BackgroundTasks`` is deliberately
not used anywhere: it runs in the API process and vanishes with it, which is
the wrong shape for a medication reminder.
"""

from app.jobs.queue import (
    DEFAULT_PRIORITY,
    URGENT_PRIORITY,
    DatabaseJobQueue,
    JobQueue,
    JobRecord,
    JobResult,
    PermanentJobError,
    RetryableJobError,
    enqueue_job,
)
from app.jobs.registry import JobContext, handler, load_handlers, registered_job_types
from app.jobs.types import JobType

__all__ = [
    "DEFAULT_PRIORITY",
    "URGENT_PRIORITY",
    "DatabaseJobQueue",
    "JobContext",
    "JobQueue",
    "JobRecord",
    "JobResult",
    "JobType",
    "PermanentJobError",
    "RetryableJobError",
    "enqueue_job",
    "handler",
    "load_handlers",
    "registered_job_types",
]
