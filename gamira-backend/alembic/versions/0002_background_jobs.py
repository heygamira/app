"""Durable background jobs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-17

The queue table. ``uq_background_jobs_dedupe_live`` is a *partial* unique index
on purpose: a dedupe key is unique only while its job is queued or running, so
two schedulers racing produce one job, while the same logical key stays usable
for the next tick.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIVE = "status IN ('queued', 'running')"


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                name="jobstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_reference", sa.JSON(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_background_jobs_actor_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_background_jobs_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_jobs")),
    )
    with op.batch_alter_table("background_jobs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_background_jobs_claim", ["status", "run_after", "priority"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_background_jobs_job_type"), ["job_type"], unique=False
        )
        batch_op.create_index(
            "ix_background_jobs_lease", ["status", "lock_expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_background_jobs_request_id"), ["request_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_background_jobs_status"), ["status"], unique=False
        )
        batch_op.create_index(
            "uq_background_jobs_dedupe_live",
            ["dedupe_key"],
            unique=True,
            sqlite_where=sa.text(LIVE),
            postgresql_where=sa.text(LIVE),
        )


def downgrade() -> None:
    with op.batch_alter_table("background_jobs", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_background_jobs_dedupe_live",
            sqlite_where=sa.text(LIVE),
            postgresql_where=sa.text(LIVE),
        )
        batch_op.drop_index(batch_op.f("ix_background_jobs_status"))
        batch_op.drop_index(batch_op.f("ix_background_jobs_request_id"))
        batch_op.drop_index("ix_background_jobs_lease")
        batch_op.drop_index(batch_op.f("ix_background_jobs_job_type"))
        batch_op.drop_index("ix_background_jobs_claim")
    op.drop_table("background_jobs")
