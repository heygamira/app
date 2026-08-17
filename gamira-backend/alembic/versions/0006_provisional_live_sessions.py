"""Speculative Live sessions.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17

The Parent App's wake-word detector opens a Live session while the score still
only says "probably", so the socket is up by the time it says "definitely".
Most of those guesses are wrong, so they need to be distinguishable from real
conversations: a provisional session expires in minutes rather than half an
hour, and does not spend the caller's hourly allowance until it is promoted.

Existing rows are real sessions, so the column defaults to false.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_sessions",
        sa.Column(
            "provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # The concurrency and hourly checks both filter on this alongside user_id,
    # and they run on the path that has to stay fast — they are what the browser
    # waits for before it can even start connecting.
    op.create_index(
        "ix_live_sessions_user_provisional",
        "live_sessions",
        ["user_id", "provisional"],
    )


def downgrade() -> None:
    op.drop_index("ix_live_sessions_user_provisional", table_name="live_sessions")
    op.drop_column("live_sessions", "provisional")
