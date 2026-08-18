"""Recurring maintenance ticks.

The worker enqueues these itself in local development. In production Cloud
Scheduler can call the same enqueue with the same dedupe key and the worker's
own ticking is turned off with ``WORKER_RUN_SCHEDULER=false`` — the handlers do
not know or care which one woke them.

Every tick's dedupe key contains a time bucket, so two schedulers firing at the
same moment (or one firing twice after a restart) produce exactly one job for
that bucket.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.jobs.queue import DEFAULT_PRIORITY, URGENT_PRIORITY, JobQueue
from app.jobs.types import JobType


@dataclass(frozen=True)
class Schedule:
    job_type: str
    interval_seconds: int
    priority: int = DEFAULT_PRIORITY
    # A tick is worthless once the next one is due, so it is not worth many
    # attempts: the following tick does the same work.
    max_attempts: int = 2


SCHEDULES: tuple[Schedule, ...] = (
    # Doses are materialised well ahead of time, so this only has to catch up
    # with medications added since the last run.
    Schedule(JobType.DOSE_MATERIALIZE, interval_seconds=300),
    # The one that turns an unanswered dose into a missed one. Frequent, cheap,
    # and the reason the Parent App no longer needs to write on read.
    Schedule(JobType.DOSE_ADVANCE_STATUS, interval_seconds=60, priority=40),
    Schedule(JobType.MEDICATION_REMINDERS, interval_seconds=60, priority=30),
    Schedule(JobType.REMINDER_OCCURRENCES, interval_seconds=60, priority=50),
    Schedule(JobType.APPOINTMENT_REMINDERS, interval_seconds=900),
    Schedule(JobType.NOTIFICATION_RETRY_SWEEP, interval_seconds=120, priority=60),
    # An unacknowledged emergency outranks everything else in this table.
    Schedule(
        JobType.ALERT_ESCALATION_CHECK, interval_seconds=60, priority=URGENT_PRIORITY
    ),
    Schedule(JobType.LIVE_SESSION_EXPIRY, interval_seconds=300),
    # Transcripts do not live forever. Hourly is plenty for a rule measured in
    # days, and cheap when there is nothing past its window.
    Schedule(JobType.CONVERSATION_RETENTION, interval_seconds=3600),
)


def bucket_key(job_type: str, interval_seconds: int, now: dt.datetime) -> str:
    bucket = int(now.timestamp()) // max(1, interval_seconds)
    return f"cron:{job_type}:{bucket}"


async def enqueue_due_maintenance(
    queue: JobQueue,
    *,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> int:
    """Enqueue one job per schedule per time bucket. Safe to call constantly."""
    settings = settings or get_settings()
    now = now or utcnow()
    queued = 0
    for schedule in SCHEDULES:
        job_id = await queue.enqueue(
            schedule.job_type,
            payload={},
            dedupe_key=bucket_key(schedule.job_type, schedule.interval_seconds, now),
            priority=schedule.priority,
            max_attempts=schedule.max_attempts,
        )
        if job_id is not None:
            queued += 1
    return queued


__all__ = ["SCHEDULES", "Schedule", "bucket_key", "enqueue_due_maintenance"]
