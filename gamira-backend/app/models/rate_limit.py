"""Rate-limit tracking for the handful of endpoints with no other defense.

Not in-memory: the API and worker already run as separate processes, and a
per-process counter that resets on every restart or is invisible to a
sibling replica does not actually bound anything past one instance — the same
reasoning behind ``app.services.realtime``'s move to Postgres. A DB row per
allowed request is cheap enough at this scale that it is the *lightweight*
option here, not a heavy one; a message broker would be disproportionate for
three low-frequency endpoints.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey, utcnow
from app.db.types import UtcDateTime


class RateLimitEvent(UUIDPrimaryKey, Base):
    """One allowed occurrence of a rate-limited action.

    Append-only and short-lived — deliberately not using the ``Timestamps``
    mixin, since a row here is never updated, only counted and eventually
    swept (``app.jobs.handlers.care.clean_up_rate_limit_events``). Only
    *allowed* requests are recorded: a rejected one raises before this row
    would be inserted, so the count already reflects exactly how many
    requests this subject has been let through.
    """

    __tablename__ = "rate_limit_events"
    __table_args__ = (
        Index(
            "ix_rate_limit_events_bucket_subject_time",
            "bucket",
            "subject",
            "occurred_at",
        ),
    )

    # A fixed identifier per limited action ("sos_raise", "invitation_create"),
    # not a free-form label — see app.core.rate_limit.
    bucket: Mapped[str] = mapped_column(String(64))
    # str(user_id) today; every caller is already authenticated, so there is
    # no pre-auth/IP case to key on.
    subject: Mapped[str] = mapped_column(String(200))
    occurred_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


__all__ = ["RateLimitEvent"]
