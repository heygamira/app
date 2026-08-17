"""The durable background job table.

Everything Gamira must still do after a request has returned — materialising
dose events, moving an unacknowledged dose to missed, delivering a
notification, escalating an SOS, generating a summary — is a row here first and
work second. A process that dies mid-job loses its lease, not the job.

Two rules shape the columns:

1. **The payload holds references, not health data.** A job says which dose
   event to look at, never what the medicine is. The worker re-reads the
   authoritative row when it runs, so a job that sat in the queue for an hour
   cannot act on a stale copy of somebody's care record.
2. **Failure is recorded as a code, never as a traceback.** ``last_error_code``
   is a short stable string; the detail belongs in the logs, keyed by job id.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, Timestamps, UUIDPrimaryKey, utcnow
from app.db.types import UtcDateTime
from app.models.enums import JobStatus


class BackgroundJob(UUIDPrimaryKey, Timestamps, Base):
    """One unit of durable work.

    ``dedupe_key`` is unique *while the job is live* (queued or running). That
    is the useful rule: two schedulers racing to enqueue the same tick produce
    one job, but the same logical key can be used again next hour. Exactly-once
    *effects* are the handler's job, enforced by the unique keys on the rows it
    writes — not by never running twice.
    """

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index(
            "uq_background_jobs_dedupe_live",
            "dedupe_key",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        # The claim query's access path: ready work, most urgent first.
        Index("ix_background_jobs_claim", "status", "run_after", "priority"),
        Index("ix_background_jobs_lease", "status", "lock_expires_at"),
    )

    job_type: Mapped[str] = mapped_column(String(64), index=True)
    # Bumped when a payload's shape changes. A worker refuses a version it does
    # not understand rather than guessing at a field that moved.
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=16),
        default=JobStatus.QUEUED,
        index=True,
    )

    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    payload: Mapped[dict] = mapped_column(JSON(), default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))

    # Lower runs first. An SOS escalation must not queue behind a week of
    # summary generation.
    priority: Mapped[int] = mapped_column(Integer, default=100)
    run_after: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)

    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)

    locked_by: Mapped[str | None] = mapped_column(String(64))
    lock_expires_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    # What the job produced, as a reference: {"type": "ai_summary", "id": ...}.
    # Never the generated content itself.
    result_reference: Mapped[dict | None] = mapped_column(JSON())
    last_error_code: Mapped[str | None] = mapped_column(String(64))

    started_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    completed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    # The request that caused this job, so one user-visible failure can be
    # followed from the API log into the worker log.
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)


__all__ = ["BackgroundJob"]
