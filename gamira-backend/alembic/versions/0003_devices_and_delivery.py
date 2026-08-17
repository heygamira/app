"""Registered devices, delivery channels and per-device delivery attempts.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-17

``notification_deliveries.channel`` defaults to ``in_app`` for existing rows,
which is what they were: records the app shows when it asks, not pushes
anybody received.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHANNEL = sa.Enum(
    "IN_APP", "PUSH", name="notificationchannel", native_enum=False, length=16
)


def upgrade() -> None:
    op.create_table(
        "registered_devices",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("install_id", sa.String(length=128), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "ANDROID",
                "IOS",
                "WEB",
                "WATCH",
                name="deviceplatform",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("device_label", sa.String(length=120), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("push_token", sa.Text(), nullable=True),
        sa.Column("push_token_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("push_token_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("push_token_invalid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE", "REVOKED", name="devicestatus", native_enum=False, length=16
            ),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"], ["users.id"], name=op.f("fk_registered_devices_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registered_devices")),
    )
    with op.batch_alter_table("registered_devices", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_registered_devices_push_token_fingerprint"),
            ["push_token_fingerprint"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_registered_devices_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "ix_registered_devices_user_status", ["user_id", "status"], unique=False
        )
        batch_op.create_index(
            "uq_registered_devices_user_install", ["user_id", "install_id"], unique=True
        )

    with op.batch_alter_table("notification_deliveries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "channel", CHANNEL, nullable=False, server_default="in_app"
            )
        )
        batch_op.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5")
        )
        batch_op.add_column(
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_notification_deliveries_pending",
            ["status", "channel", "next_attempt_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_notification_deliveries_user_created",
            ["user_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "notification_delivery_attempts",
        sa.Column("notification_delivery_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("channel", CHANNEL, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SUCCEEDED",
                "RETRYABLE",
                "PERMANENT",
                "TOKEN_INVALID",
                "SKIPPED",
                name="deliveryattemptstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("device_token_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["registered_devices.id"],
            name=op.f("fk_notification_delivery_attempts_device_id_registered_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["notification_delivery_id"],
            ["notification_deliveries.id"],
            name=op.f(
                "fk_notification_delivery_attempts_notification_delivery_id_"
                "notification_deliveries"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_delivery_attempts")),
    )
    with op.batch_alter_table("notification_delivery_attempts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_notification_delivery_attempts_notification",
            ["notification_delivery_id", "attempted_at"],
            unique=False,
        )

    with op.batch_alter_table("timeline_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dedupe_key", sa.String(length=160), nullable=True))
        batch_op.create_unique_constraint(
            batch_op.f("uq_timeline_events_dedupe_key"), ["dedupe_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("timeline_events", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("uq_timeline_events_dedupe_key"), type_="unique"
        )
        batch_op.drop_column("dedupe_key")

    with op.batch_alter_table("notification_delivery_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_notification_delivery_attempts_notification")
    op.drop_table("notification_delivery_attempts")

    with op.batch_alter_table("notification_deliveries", schema=None) as batch_op:
        batch_op.drop_index("ix_notification_deliveries_user_created")
        batch_op.drop_index("ix_notification_deliveries_pending")
        batch_op.drop_column("delivered_at")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("channel")

    with op.batch_alter_table("registered_devices", schema=None) as batch_op:
        batch_op.drop_index("uq_registered_devices_user_install")
        batch_op.drop_index("ix_registered_devices_user_status")
        batch_op.drop_index(batch_op.f("ix_registered_devices_user_id"))
        batch_op.drop_index(batch_op.f("ix_registered_devices_push_token_fingerprint"))
    op.drop_table("registered_devices")
