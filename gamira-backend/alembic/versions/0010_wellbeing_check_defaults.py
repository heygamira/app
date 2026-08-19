"""Give ``wellbeing_checks`` the timestamp defaults it should have had.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-18

``0009`` created this table with ``created_at`` / ``updated_at`` NOT NULL and no
``server_default``. The ``Timestamps`` mixin declares both with a server default
and *no* Python-side default, so SQLAlchemy leaves them out of the INSERT
entirely and reads them back with RETURNING — every insert failed on NOT NULL,
and every watch flag with it.

``0009`` was corrected in place, which fixes a database built from scratch and
does nothing at all for one that had already run it. Alembic does not re-run an
applied revision, so the only way the fix reaches a live database is a new one.
That is this.

The table is rebuilt rather than altered because SQLite cannot add a DEFAULT to
an existing column. ``copy_from`` hands batch mode the full definition — every
column, every foreign key and every index — because a rebuild only keeps what it
is told about, and reflection is not enough: the five indexes came back empty on
the first attempt, including the one the escalation sweep runs on. Rows are
copied; there will not be any, since none could ever be written.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("(CURRENT_TIMESTAMP)")

_STATUS = sa.Enum(
    "PENDING",
    "ALRIGHT",
    "NOT_ALRIGHT",
    "NO_ANSWER",
    "UNREACHABLE",
    name="wellbeingcheckstatus",
    native_enum=False,
    length=16,
)


def _table(*, with_defaults: bool) -> sa.Table:
    """The table as it stands, so batch mode rebuilds it exactly."""
    default = NOW if with_defaults else None
    return sa.Table(
        "wellbeing_checks",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=default,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=default,
            nullable=False,
        ),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=False),
        sa.Column("status", _STATUS, nullable=False),
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
        # Declared here for the same reason as the columns: batch mode rebuilds
        # the table from *this* definition, and an index it was not told about
        # is an index the rebuilt table does not have. Dropping the sweep's
        # index on `escalate_at` would be a silent full scan every minute.
        sa.Index("ix_wellbeing_checks_family_id", "family_id"),
        sa.Index("ix_wellbeing_checks_senior_profile_id", "senior_profile_id"),
        sa.Index("ix_wellbeing_checks_escalate_at", "escalate_at"),
        sa.Index("ix_wellbeing_checks_senior_status", "senior_profile_id", "status"),
        sa.Index("ix_wellbeing_checks_open", "status", "escalate_at"),
    )


def _move(*, to_defaults: bool) -> None:
    existing = _table(with_defaults=not to_defaults)
    default = NOW if to_defaults else None
    with op.batch_alter_table(
        "wellbeing_checks", schema=None, copy_from=existing
    ) as batch_op:
        for column in ("created_at", "updated_at"):
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=default,
            )


def upgrade() -> None:
    _move(to_defaults=True)


def downgrade() -> None:
    _move(to_defaults=False)
