"""Append-only audit trail for sensitive actions."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, UUIDPrimaryKey, utcnow
from app.db.types import UtcDateTime


class AuditLog(UUIDPrimaryKey, Base):
    """Who did what, to which record, in which family, and whether it succeeded.

    Rows are never updated or deleted by application code, and metadata must not
    contain tokens, secrets or unnecessary health detail.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_family_occurred", "family_id", "occurred_at"),)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_type: Mapped[str] = mapped_column(String(24), default="user")
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(48))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    family_id: Mapped[uuid.UUID | None] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="success")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON())
    occurred_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


__all__ = ["AuditLog"]
