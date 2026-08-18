"""AI conversations, decisions, usage and Live sessions.

What is deliberately *not* here:

* Raw audio. Voice is transcribed by the provider and only the text the user
  and the assistant exchanged is ever considered for storage.
* Prompts containing secrets. A prompt is rebuilt from a versioned template
  plus permission-scoped facts at call time; the stored record keeps the
  template version, not a bearer token.
* Anything the model asserted as fact. ``AiSummary.facts`` holds figures the
  backend counted; the model's contribution is the wording in ``content``.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, Timestamps, UUIDPrimaryKey, utcnow
from app.db.types import UtcDateTime
from app.models.enums import (
    ConfirmationState,
    ConversationChannel,
    ConversationStatus,
    DecisionStatus,
    LiveSessionStatus,
    MemoryKind,
    MessageRole,
    PolicyResult,
    ReviewState,
    SummaryKind,
)


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    """One exchange between a person and Gamira, text or voice."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_started", "user_id", "started_at"),)

    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    senior_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        Enum(ConversationChannel, native_enum=False, length=16),
        default=ConversationChannel.TEXT,
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, native_enum=False, length=16),
        default=ConversationStatus.ACTIVE,
    )
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)
    ended_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    # What the retention rules were when this started, so changing the policy
    # later does not retroactively change what a person agreed to.
    retention_policy: Mapped[str] = mapped_column(String(32), default="transcript_only")
    consent_snapshot: Mapped[dict | None] = mapped_column(JSON())


class ConversationMessage(UUIDPrimaryKey, Base):
    """One turn. Text only — audio is never persisted by default."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conversation", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False, length=16)
    )
    content: Mapped[str | None] = mapped_column(Text())
    # Set instead of `content` when the turn was a tool call, so a transcript
    # shows what happened without duplicating the decision record.
    tool_name: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


class AiSummary(UUIDPrimaryKey, Timestamps, Base):
    """A generated summary and everything needed to judge whether to trust it.

    The provenance columns are the point. A summary without its date range, its
    source figures, its prompt version and its freshness warning is a paragraph
    of unattributable text about somebody's health.
    """

    __tablename__ = "ai_summaries"
    __table_args__ = (
        Index("ix_ai_summaries_senior_period", "senior_profile_id", "period_start"),
        Index("uq_ai_summaries_dedupe", "dedupe_key", unique=True),
    )

    kind: Mapped[SummaryKind] = mapped_column(
        Enum(SummaryKind, native_enum=False, length=24), default=SummaryKind.WEEKLY_CARE
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))

    period_start: Mapped[dt.date] = mapped_column(Date())
    period_end: Mapped[dt.date] = mapped_column(Date())

    # The figures the backend counted. The model never adds to this.
    facts: Mapped[dict] = mapped_column(JSON(), default=dict)
    # Which rows the figures came from: table names and counts, not contents.
    source_reference: Mapped[dict | None] = mapped_column(JSON())
    source_data_version: Mapped[str] = mapped_column(String(32), default="1")
    # Set when the underlying data is thin or stale — "the watch last synced
    # four days ago" — and shown wherever the summary is shown.
    data_freshness_warning: Mapped[str | None] = mapped_column(String(400))

    content: Mapped[str | None] = mapped_column(Text())
    model: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    output_schema_version: Mapped[str | None] = mapped_column(String(32))
    generated_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    review_state: Mapped[ReviewState] = mapped_column(
        Enum(ReviewState, native_enum=False, length=16), default=ReviewState.UNREVIEWED
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())


class SeniorMemory(UUIDPrimaryKey, Timestamps, Base):
    """One small thing Gamira remembers about somebody between conversations.

    A table of its own rather than a column on ``SeniorProfile``. ``notes`` and
    ``FamilyNote`` are written by people, and mixing model output into them
    would destroy the one property this codebase guards everywhere: you can
    always tell who said a thing. Everything here was written by Gamira, and
    every row carries the conversation it came from and the prompt version that
    produced it, so a memory that reads oddly can be traced to the exchange that
    caused it.

    Shown to the person it is about, on their own device, and to their family.
    Either can delete any of it — which is the other half of being allowed to
    keep it at all. Deleting sets ``deleted_at``; nothing deleted is ever put
    back into a prompt.

    What is *not* here: anything clinical. No symptoms, no readings, no
    diagnoses, no medication. Those have their own tables, their own
    permissions and their own audit trail, and a paragraph of remembered text is
    not a substitute for any of them.
    """

    __tablename__ = "senior_memories"
    __table_args__ = (
        Index("uq_senior_memories_dedupe", "dedupe_key", unique=True),
        Index("ix_senior_memories_senior_created", "senior_profile_id", "created_at"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[MemoryKind] = mapped_column(
        Enum(MemoryKind, native_enum=False, length=16), default=MemoryKind.PREFERENCE
    )
    content: Mapped[str] = mapped_column(String(400))
    # Which conversation this came out of, so it can be read in context.
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    # How sure the model was, 0..1. Recorded and shown; never used to decide
    # anything on its own.
    confidence: Mapped[float | None] = mapped_column(Float())
    # Stops the same thing being remembered once a week forever.
    dedupe_key: Mapped[str | None] = mapped_column(String(200))

    model: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    output_schema_version: Mapped[str | None] = mapped_column(String(32))
    review_state: Mapped[ReviewState] = mapped_column(
        Enum(ReviewState, native_enum=False, length=16), default=ReviewState.UNREVIEWED
    )
    # A later memory that replaces this one, rather than an edit in place: the
    # history of what Gamira believed is worth keeping.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_memories.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    deleted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class AiDecision(UUIDPrimaryKey, Timestamps, Base):
    """One proposed action, its policy verdict, and what actually happened.

    A decision row exists before anything is executed, which is what makes the
    confirm/reject endpoints possible: the arguments a person is shown are the
    arguments that will run, because they are read back from this row rather
    than resent by the client.
    """

    __tablename__ = "ai_decisions"
    __table_args__ = (
        Index("uq_ai_decisions_idempotency", "idempotency_key", unique=True),
        Index("ix_ai_decisions_user_created", "user_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    live_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE")
    )
    senior_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE")
    )

    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    # The model's own call id, kept so a duplicate delivery of the same Live
    # message resolves to this row instead of acting twice.
    function_call_id: Mapped[str | None] = mapped_column(String(128))
    arguments: Mapped[dict] = mapped_column(JSON(), default=dict)
    decision_schema_version: Mapped[str] = mapped_column(String(16), default="1")

    policy_result: Mapped[PolicyResult] = mapped_column(
        Enum(PolicyResult, native_enum=False, length=24)
    )
    policy_reason_code: Mapped[str | None] = mapped_column(String(64))
    confirmation_state: Mapped[ConfirmationState] = mapped_column(
        Enum(ConfirmationState, native_enum=False, length=24),
        default=ConfirmationState.NOT_REQUIRED,
    )
    # Exactly what the person is asked, so the spoken and the visible prompt
    # cannot drift from the action.
    confirmation_prompt: Mapped[str | None] = mapped_column(String(400))
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    confirmation_decided_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    expires_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, native_enum=False, length=16),
        default=DecisionStatus.PROPOSED,
    )
    result_entity_type: Mapped[str | None] = mapped_column(String(48))
    result_entity_id: Mapped[uuid.UUID | None] = mapped_column()
    error_code: Mapped[str | None] = mapped_column(String(64))
    executed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())

    model: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    # The idempotency basis for a state-changing Live call:
    # live:{session_id}:{function_call_id}
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(64))


class AiUsage(UUIDPrimaryKey, Base):
    """One provider call: what it cost, how long it took, how it ended.

    Errors are stored as codes. A provider's exception text can contain the
    prompt it choked on, which here would mean health data in a metrics table.
    """

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_created", "provider", "created_at"),)

    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(48))
    family_id: Mapped[uuid.UUID | None] = mapped_column()
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column()
    job_id: Mapped[uuid.UUID | None] = mapped_column()
    live_session_id: Mapped[uuid.UUID | None] = mapped_column()
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    response_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float())
    outcome: Mapped[str] = mapped_column(String(24), default="succeeded")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow)


class LiveSession(UUIDPrimaryKey, Timestamps, Base):
    """A voice session the backend authorised, minted a token for, and owns.

    The scope columns are set from verified authentication at creation and are
    never re-read from anything the model says. A tool call arriving later is
    checked against *this row*, so a conversation cannot talk its way into
    another family.

    ``tool_snapshot`` is the exact catalogue the session was opened with. A tool
    added to the server afterwards is not callable by a session that never
    declared it, and one removed for safety stops working immediately.
    """

    __tablename__ = "live_sessions"
    __table_args__ = (Index("ix_live_sessions_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE"), index=True
    )
    senior_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("senior_profiles.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    membership_role: Mapped[str] = mapped_column(String(16))
    status: Mapped[LiveSessionStatus] = mapped_column(
        Enum(LiveSessionStatus, native_enum=False, length=16),
        default=LiveSessionStatus.ACTIVE,
    )
    model: Mapped[str] = mapped_column(String(64))
    api_version: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32), default="gemini")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    tool_snapshot: Mapped[list] = mapped_column(JSON(), default=list)
    # Deliberately absent: the ephemeral token itself. It is returned once and
    # never stored, so a database read cannot open a voice session.
    token_fingerprint: Mapped[str | None] = mapped_column(String(32))
    # Opened speculatively and not yet spoken into. The Parent App pre-connects
    # while a wake word is still only *probably* a wake word, so that the socket
    # is up by the time it is confirmed; most of those are never used. A
    # provisional session gets a short expiry and does not spend the caller's
    # hourly quota until `promote_live_session` says it became real.
    provisional: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), index=True)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    closed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime())
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(String(64))

    def is_live(self, now: dt.datetime | None = None) -> bool:
        now = now or utcnow()
        return self.status is LiveSessionStatus.ACTIVE and self.expires_at > now


__all__ = [
    "AiDecision",
    "AiSummary",
    "AiUsage",
    "Conversation",
    "ConversationMessage",
    "LiveSession",
]
