"""Reminders Gamira suggested, waiting on a person.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-18

The after-call review can now propose an everyday routine it heard about — "the
plants have been dry", "she keeps forgetting her afternoon walk". A proposal is
not a decision: the row is written with status ``suggested``, which every query
that looks for live reminders already excludes, so it prompts nobody and
appears on no schedule until a family member accepts it.

``suggestion_reason`` is why she thought of it, in her words, and
``suggested_from_conversation_id`` is the exchange it came out of — so the
reason can be checked against what was actually said rather than taken on
trust. A suggestion whose reasoning is invisible is one a family can only guess
at, and guessing is not consent.

No change to the status column itself: the enum is stored as a plain VARCHAR
with no CHECK constraint, so a new member needs no DDL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("suggestion_reason", sa.String(length=200), nullable=True)
        )
        batch_op.add_column(
            sa.Column("suggested_from_conversation_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_reminders_suggested_from_conversation_id_conversations"),
            "conversations",
            ["suggested_from_conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_reminders_suggested_from_conversation_id_conversations"),
            type_="foreignkey",
        )
        batch_op.drop_column("suggested_from_conversation_id")
        batch_op.drop_column("suggestion_reason")
