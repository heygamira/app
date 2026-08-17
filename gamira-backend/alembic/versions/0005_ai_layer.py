"""Conversations, summaries, decisions, usage and Live sessions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17

No table here stores audio, a Gemini key or a Live token. ``live_sessions``
keeps only a fingerprint of the token it minted, which is enough to correlate
an audit line with a session and useless for opening one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=True),
        sa.Column(
            "channel",
            sa.Enum(
                "TEXT", "VOICE", name="conversationchannel", native_enum=False, length=16
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "ENDED",
                "EXPIRED",
                name="conversationstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_policy", sa.String(length=32), nullable=False),
        sa.Column("consent_snapshot", sa.JSON(), nullable=True),
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
            ["family_id"],
            ["families.id"],
            name=op.f("fk_conversations_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_conversations_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_conversations_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_conversations_family_id"), ["family_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conversations_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "ix_conversations_user_started", ["user_id", "started_at"], unique=False
        )

    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "USER",
                "ASSISTANT",
                "SYSTEM",
                "TOOL",
                name="messagerole",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    with op.batch_alter_table("conversation_messages", schema=None) as batch_op:
        batch_op.create_index(
            "ix_conversation_messages_conversation",
            ["conversation_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "ai_summaries",
        sa.Column(
            "kind",
            sa.Enum(
                "CONVERSATION",
                "WEEKLY_CARE",
                name="summarykind",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("source_reference", sa.JSON(), nullable=True),
        sa.Column("source_data_version", sa.String(length=32), nullable=False),
        sa.Column("data_freshness_warning", sa.String(length=400), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("output_schema_version", sa.String(length=32), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_ai_summaries_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_ai_summaries_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_ai_summaries_requested_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_ai_summaries_reviewed_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_ai_summaries_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_summaries")),
    )
    with op.batch_alter_table("ai_summaries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ai_summaries_family_id"), ["family_id"], unique=False
        )
        batch_op.create_index(
            "ix_ai_summaries_senior_period",
            ["senior_profile_id", "period_start"],
            unique=False,
        )
        batch_op.create_index("uq_ai_summaries_dedupe", ["dedupe_key"], unique=True)

    op.create_table(
        "live_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("membership_role", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "CLOSED",
                "EXPIRED",
                "REVOKED",
                name="livesessionstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("api_version", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("tool_snapshot", sa.JSON(), nullable=False),
        sa.Column("token_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
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
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_live_sessions_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_live_sessions_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_live_sessions_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_live_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_live_sessions")),
    )
    with op.batch_alter_table("live_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_live_sessions_expires_at"), ["expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_live_sessions_family_id"), ["family_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_live_sessions_senior_profile_id"),
            ["senior_profile_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_live_sessions_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "ix_live_sessions_user_status", ["user_id", "status"], unique=False
        )

    op.create_table(
        "ai_decisions",
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("live_session_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("senior_profile_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("function_call_id", sa.String(length=128), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("decision_schema_version", sa.String(length=16), nullable=False),
        sa.Column(
            "policy_result",
            sa.Enum(
                "ALLOWED",
                "CONFIRMATION_REQUIRED",
                "DENIED",
                name="policyresult",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("policy_reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "confirmation_state",
            sa.Enum(
                "NOT_REQUIRED",
                "PENDING",
                "CONFIRMED",
                "REJECTED",
                "EXPIRED",
                name="confirmationstate",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("confirmation_prompt", sa.String(length=400), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("confirmation_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PROPOSED",
                "EXECUTED",
                "REJECTED",
                "FAILED",
                "EXPIRED",
                name="decisionstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("result_entity_type", sa.String(length=48), nullable=True),
        sa.Column("result_entity_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
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
            ["confirmed_by_user_id"],
            ["users.id"],
            name=op.f("fk_ai_decisions_confirmed_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_ai_decisions_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["families.id"],
            name=op.f("fk_ai_decisions_family_id_families"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["live_session_id"],
            ["live_sessions.id"],
            name=op.f("fk_ai_decisions_live_session_id_live_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["senior_profile_id"],
            ["senior_profiles.id"],
            name=op.f("fk_ai_decisions_senior_profile_id_senior_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_decisions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_decisions")),
    )
    with op.batch_alter_table("ai_decisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ai_decisions_tool_name"), ["tool_name"], unique=False
        )
        batch_op.create_index(
            "ix_ai_decisions_user_created", ["user_id", "created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ai_decisions_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            "uq_ai_decisions_idempotency", ["idempotency_key"], unique=True
        )

    op.create_table(
        "ai_usage",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=48), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("live_session_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("response_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage")),
    )
    with op.batch_alter_table("ai_usage", schema=None) as batch_op:
        batch_op.create_index(
            "ix_ai_usage_created", ["provider", "created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_usage", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_usage_created")
    op.drop_table("ai_usage")

    with op.batch_alter_table("ai_decisions", schema=None) as batch_op:
        batch_op.drop_index("uq_ai_decisions_idempotency")
        batch_op.drop_index(batch_op.f("ix_ai_decisions_user_id"))
        batch_op.drop_index("ix_ai_decisions_user_created")
        batch_op.drop_index(batch_op.f("ix_ai_decisions_tool_name"))
    op.drop_table("ai_decisions")

    with op.batch_alter_table("live_sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_live_sessions_user_status")
        batch_op.drop_index(batch_op.f("ix_live_sessions_user_id"))
        batch_op.drop_index(batch_op.f("ix_live_sessions_senior_profile_id"))
        batch_op.drop_index(batch_op.f("ix_live_sessions_family_id"))
        batch_op.drop_index(batch_op.f("ix_live_sessions_expires_at"))
    op.drop_table("live_sessions")

    with op.batch_alter_table("ai_summaries", schema=None) as batch_op:
        batch_op.drop_index("uq_ai_summaries_dedupe")
        batch_op.drop_index("ix_ai_summaries_senior_period")
        batch_op.drop_index(batch_op.f("ix_ai_summaries_family_id"))
    op.drop_table("ai_summaries")

    with op.batch_alter_table("conversation_messages", schema=None) as batch_op:
        batch_op.drop_index("ix_conversation_messages_conversation")
    op.drop_table("conversation_messages")

    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_index("ix_conversations_user_started")
        batch_op.drop_index(batch_op.f("ix_conversations_user_id"))
        batch_op.drop_index(batch_op.f("ix_conversations_family_id"))
    op.drop_table("conversations")
