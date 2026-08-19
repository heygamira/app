"""Index reminders on (status, local_time).

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-19

``process_reminder_occurrences`` (the worker sweep that fires non-medication
reminders) has always filtered on ``status`` and read ``local_time`` for every
row that matches, but ``reminders`` was only ever indexed on ``family_id`` and
``senior_profile_id`` — confirmed absent since ``0001_initial_schema``. At one
family this cost nothing. At many families running the same 60-second sweep,
every tick is a full table scan of every reminder ever created, active or not,
across every family, growing without bound as families sign up.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.create_index(
            "ix_reminders_status_local_time", ["status", "local_time"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.drop_index("ix_reminders_status_local_time")
