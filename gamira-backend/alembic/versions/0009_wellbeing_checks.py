"""A question asked when a device flagged something, and whether it was answered.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-18

A watch flag used to be a notification and nothing else: ``POST
/seniors/{id}/device-flags`` raised a notice for the family and kept no row. So
nothing could ask the person about it, and — far more importantly — nothing
could notice that nobody had answered. The silence was invisible.

This table stores the device's own claim and the person's own answer, and
nothing in between. ``reason`` is the device's wording, kept verbatim; the
backend never labels a reading and neither does Gamira. ``asked_at`` null means
the app was never open to put the question, which is a different fact from
being ignored, and the alert that follows says which one it was.

``escalate_at`` is indexed because a background rule sweeps it. The rule is the
only thing that escalates: the model reports an answer and never decides what
happens next.

Both timestamp columns carry ``server_default``, because ``Timestamps`` gives
them a server default and no Python one — so they never appear in an INSERT and
the DDL is the only thing that can fill them. This shipped without it once, and
every watch flag raised an ``IntegrityError`` until it was found by running the
app rather than by the tests, which build their schema from the models.

The new ``AlertType`` member needs no DDL — the column is a plain VARCHAR with
no CHECK constraint.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wellbeing_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        # `server_default` is not decoration. The `Timestamps` mixin declares
        # these with a server default and *no* Python-side default, so
        # SQLAlchemy leaves them out of the INSERT entirely and reads them back
        # with RETURNING. Without a DEFAULT in the DDL every insert fails on
        # NOT NULL — which is exactly what happened, and what the model-built
        # test schema could never show.
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
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=False),
        # An Enum, not a bare String, to match the model exactly. It emits the
        # same VARCHAR(16) the model does — `create_constraint` is off by
        # default, so neither side has a CHECK — and declaring it this way keeps
        # the two definitions readable as the same thing.
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "ALRIGHT",
                "NOT_ALRIGHT",
                "NO_ANSWER",
                "UNREACHABLE",
                name="wellbeingcheckstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("source_device", sa.String(length=120), nullable=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_wellbeing_checks_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_wellbeing_checks_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_wellbeing_checks_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name=op.f("fk_wellbeing_checks_alert_id_alerts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wellbeing_checks")),
    )
    with op.batch_alter_table("wellbeing_checks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_wellbeing_checks_family_id"), ["family_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_wellbeing_checks_senior_profile_id"),
            ["senior_profile_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_wellbeing_checks_escalate_at"),
            ["escalate_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_wellbeing_checks_senior_status",
            ["senior_profile_id", "status"],
            unique=False,
        )
        batch_op.create_index(
            "ix_wellbeing_checks_open", ["status", "escalate_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("wellbeing_checks", schema=None) as batch_op:
        batch_op.drop_index("ix_wellbeing_checks_open")
        batch_op.drop_index("ix_wellbeing_checks_senior_status")
        batch_op.drop_index(batch_op.f("ix_wellbeing_checks_escalate_at"))
        batch_op.drop_index(batch_op.f("ix_wellbeing_checks_senior_profile_id"))
        batch_op.drop_index(batch_op.f("ix_wellbeing_checks_family_id"))
    op.drop_table("wellbeing_checks")
