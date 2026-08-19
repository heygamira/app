"""A database-backed rate limiter for SOS, invitations and device registration.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-19

Nothing rate-limited these before. An in-memory counter was considered and
rejected for the same reason ``app.services.realtime`` moved off one: the API
and worker already run as separate processes, and a per-replica counter that
resets on restart or is invisible to a sibling replica does not actually
bound anything once there is more than one instance. A row per allowed
request, counted over a rolling window, does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rate_limit_events")),
    )
    with op.batch_alter_table("rate_limit_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_rate_limit_events_bucket_subject_time",
            ["bucket", "subject", "occurred_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("rate_limit_events", schema=None) as batch_op:
        batch_op.drop_index("ix_rate_limit_events_bucket_subject_time")
    op.drop_table("rate_limit_events")
