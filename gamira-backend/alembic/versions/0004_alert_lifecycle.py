"""Persistent SOS alerts and their append-only history.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("SOS", name="alerttype", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "CRITICAL",
                "HIGH",
                "INFO",
                name="alertseverity",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "RAISED",
                "ACKNOWLEDGED",
                "ESCALATED",
                "RESOLVED",
                "CANCELLED",
                name="alertstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "PARENT_APP",
                "WATCH",
                "FAMILY_APP",
                "APPROVED_DEVICE",
                name="alertsource",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("source_device_id", sa.Uuid(), nullable=True),
        sa.Column("raised_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_count", sa.Integer(), nullable=False),
        sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_escalation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=400), nullable=True),
        sa.Column("cancelled_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=400), nullable=True),
        sa.Column("notified_user_count", sa.Integer(), nullable=False),
        sa.Column("timeline_event_id", sa.Uuid(), nullable=True),
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
            ["acknowledged_by_user_id"],
            ["users.id"],
            name=op.f("fk_alerts_acknowledged_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_user_id"],
            ["users.id"],
            name=op.f("fk_alerts_cancelled_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_alerts_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raised_by_user_id"],
            ["users.id"],
            name=op.f("fk_alerts_raised_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name=op.f("fk_alerts_resolved_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_alerts_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_device_id"],
            ["registered_devices.id"],
            name=op.f("fk_alerts_source_device_id_registered_devices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_alerts_family_id"), ["family_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_alerts_next_escalation_at"),
            ["next_escalation_at"],
            unique=False,
        )
        batch_op.create_index("ix_alerts_open", ["status", "raised_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_alerts_senior_profile_id"), ["senior_profile_id"], unique=False
        )
        batch_op.create_index(
            "ix_alerts_senior_status", ["senior_profile_id", "status"], unique=False
        )

    op.create_table(
        "alert_events",
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "RAISED",
                "DELIVERY_ATTEMPTED",
                "DELIVERED",
                "ACKNOWLEDGED",
                "ESCALATED",
                "RESOLVED",
                "CANCELLED",
                "NOTE",
                name="alerteventtype",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum(
                "USER",
                "SYSTEM",
                "DEVICE",
                "AI",
                name="actortype",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_alert_events_actor_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name=op.f("fk_alert_events_alert_id_alerts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_events")),
    )
    with op.batch_alter_table("alert_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_alert_events_alert_id"), ["alert_id"], unique=False
        )
        batch_op.create_index(
            "ix_alert_events_alert_occurred", ["alert_id", "occurred_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("alert_events", schema=None) as batch_op:
        batch_op.drop_index("ix_alert_events_alert_occurred")
        batch_op.drop_index(batch_op.f("ix_alert_events_alert_id"))
    op.drop_table("alert_events")

    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_index("ix_alerts_senior_status")
        batch_op.drop_index(batch_op.f("ix_alerts_senior_profile_id"))
        batch_op.drop_index("ix_alerts_open")
        batch_op.drop_index(batch_op.f("ix_alerts_next_escalation_at"))
        batch_op.drop_index(batch_op.f("ix_alerts_family_id"))
    op.drop_table("alerts")
