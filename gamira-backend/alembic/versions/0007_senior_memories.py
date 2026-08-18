"""What Gamira remembers between conversations.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18

A voice companion that forgets everything the moment a call ends is a search
box you talk to. This table is the small set of ordinary things it may keep —
who visits on Sundays, that they would rather not be rung before nine — written
only by Gamira, always attributed to the conversation it came from, and always
visible to the person it is about.

Deliberately its own table. ``senior_profiles.notes`` and ``family_notes`` are
written by people, and merging model output into them would destroy the "who
said this" property the rest of the schema is careful about.

``deleted_at`` rather than a delete: the row leaves every prompt immediately,
and the record that Gamira once believed it survives for anyone looking into
why she said something.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "senior_memories",
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "PERSON",
                "PREFERENCE",
                "ROUTINE",
                "INTEREST",
                "EVENT",
                "MOOD",
                "CONCERN",
                name="memorykind",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.String(length=400), nullable=False),
        sa.Column("source_conversation_id", sa.Uuid(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("output_schema_version", sa.String(length=32), nullable=True),
        sa.Column(
            "review_state",
            sa.Enum(
                "UNREVIEWED",
                "REVIEWED",
                "REJECTED",
                name="reviewstate",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
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
            ["deleted_by_user_id"],
            ["users.id"],
            name=op.f("fk_senior_memories_deleted_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_senior_memories_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_senior_memories_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["conversations.id"],
            name=op.f("fk_senior_memories_source_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["senior_memories.id"],
            name=op.f("fk_senior_memories_superseded_by_id_senior_memories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_senior_memories")),
    )
    with op.batch_alter_table("senior_memories", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_senior_memories_family_id"), ["family_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_senior_memories_senior_profile_id"),
            ["senior_profile_id"],
            unique=False,
        )
        # Retrieval is always "this person's, newest first, capped" — the shape
        # the prompt builder and both memory screens use.
        batch_op.create_index(
            "ix_senior_memories_senior_created",
            ["senior_profile_id", "created_at"],
            unique=False,
        )
        batch_op.create_index("uq_senior_memories_dedupe", ["dedupe_key"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("senior_memories", schema=None) as batch_op:
        batch_op.drop_index("uq_senior_memories_dedupe")
        batch_op.drop_index("ix_senior_memories_senior_created")
        batch_op.drop_index(batch_op.f("ix_senior_memories_senior_profile_id"))
        batch_op.drop_index(batch_op.f("ix_senior_memories_family_id"))

    op.drop_table("senior_memories")
