"""Request and response models for the AI endpoints.

Two absences are deliberate and load-bearing:

* No request model accepts a ``family_id``, a ``role`` or an entitlement. Those
  come from the caller's membership rows, never from the body.
* No response model carries a permanent key, a system prompt or a raw token
  beyond the one-use ephemeral credential ``LiveSessionOut`` exists to deliver.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    ConfirmationState,
    DecisionStatus,
    JobStatus,
    MemoryKind,
    PolicyResult,
    ReviewState,
    SummaryKind,
)
from app.schemas.common import ApiModel

# --------------------------------------------------------------------------- #
# Summaries and jobs
# --------------------------------------------------------------------------- #


class SummaryRequest(BaseModel):
    senior_id: uuid.UUID
    # Omit both for the seven days ending yesterday, in that person's timezone.
    period_start: dt.date | None = None
    period_end: dt.date | None = None


class AiJobOut(ApiModel):
    """A queued AI job. Polled by the client until it reaches a terminal state."""

    id: uuid.UUID
    job_type: str
    status: JobStatus
    attempt_count: int
    max_attempts: int
    # A stable code, never a provider message or a traceback.
    last_error_code: str | None = None
    result_reference: dict[str, Any] | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class SummaryAccepted(BaseModel):
    """What ``POST /ai/summaries`` returns immediately.

    The figures are already counted and already stored, so ``summary_id`` is
    usable before the job finishes — a family sees the counts while the wording
    is still being written, and keeps the counts if it never is.
    """

    job_id: uuid.UUID | None
    summary_id: uuid.UUID
    status: JobStatus = JobStatus.QUEUED


class AiSummaryOut(ApiModel):
    id: uuid.UUID
    kind: SummaryKind
    senior_profile_id: uuid.UUID | None = None
    period_start: dt.date
    period_end: dt.date
    # The figures the backend counted. Present whether or not a model ever ran.
    facts: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    source_data_version: str
    data_freshness_warning: str | None = None
    content: str | None = None
    model: str | None = None
    provider: str | None = None
    prompt_version: str | None = None
    output_schema_version: str | None = None
    generated_at: dt.datetime | None = None
    review_state: ReviewState
    created_at: dt.datetime


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #


class SeniorMemoryOut(ApiModel):
    """One thing Gamira remembers, as both apps show it.

    The provenance travels with it. Somebody reading "she prefers not to be
    rung before nine" and wondering where that came from can see the
    conversation, the model and the prompt version that produced it, which is
    the difference between a memory and an unattributable claim about a person.
    """

    id: uuid.UUID
    kind: MemoryKind
    content: str
    source_conversation_id: uuid.UUID | None = None
    confidence: float | None = None
    model: str | None = None
    prompt_version: str | None = None
    created_at: dt.datetime


class FamilyNoticeOut(ApiModel):
    """Something Gamira told this person's family about them.

    Shown to the person themselves. The persona promises "if something
    genuinely needs a family member, say so to them first, openly" — and open
    means afterwards as well as at the time. Somebody should be able to check
    what was said about them without asking anyone.
    """

    id: uuid.UUID
    title: str
    body: str
    created_at: dt.datetime
    # How many family members it reached. Not who: a notice is one message, and
    # turning it into a list of who has read it is a different feature with
    # different consent.
    recipients: int = 1


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #


class ChatRequest(BaseModel):
    senior_id: uuid.UUID
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    reply: str
    model: str
    provider: str
    prompt_version: str
    refused: bool = False
    refusal_code: str | None = None


# --------------------------------------------------------------------------- #
# Live sessions
# --------------------------------------------------------------------------- #


class LiveSessionRequest(BaseModel):
    # Which cared-for person this session is about. Checked against the
    # caller's memberships; a senior in another family is a 404.
    senior_id: uuid.UUID | None = None
    # Opened on a wake word the detector is not yet sure about, so the socket is
    # ready if it turns out to be one. Expires in a couple of minutes and costs
    # no hourly quota unless promoted.
    provisional: bool = False


class LiveToolDeclaration(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class LiveSessionOut(BaseModel):
    """Everything the browser needs, and nothing it must not hold.

    ``token`` is a one-use ephemeral credential with the model, modalities,
    system instruction and tool catalogue already pinned into it. The permanent
    Gemini key is not here, is not derivable from here, and never leaves the
    backend.
    """

    session_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    token: str
    model: str
    api_version: str
    expires_at: dt.datetime
    # After this, the token can no longer *open* a session — much sooner than
    # the session's own expiry.
    connect_before: dt.datetime
    senior_id: uuid.UUID
    senior_name: str
    tools: list[str]
    # True while this session is only a guess. It must be promoted before it is
    # spoken into, or it expires on its own.
    provisional: bool = False


class ToolCallIn(BaseModel):
    """One ``functionCall`` forwarded from a Live message."""

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class TranscriptTurnIn(BaseModel):
    """One thing that was said out loud, as the browser heard it.

    Untrusted content, like every other thing a conversation contains: it is
    stored and shown, and it is never treated as an instruction.
    """

    # Only the two halves of a spoken conversation. `system` and `tool` rows are
    # written by the backend itself and must not be forgeable from a client.
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4000)


class TranscriptBatchIn(BaseModel):
    """A few seconds of conversation, batched to keep the audio path quiet."""

    turns: list[TranscriptTurnIn] = Field(min_length=1, max_length=50)


class TranscriptBatchOut(BaseModel):
    conversation_id: uuid.UUID
    stored: int


class ToolCallBatchIn(BaseModel):
    """A whole Live message's worth of calls.

    A model may emit several at once, and each one's id has to survive the
    round trip intact — a response matched to the wrong call is worse than no
    response at all.
    """

    calls: list[ToolCallIn] = Field(min_length=1, max_length=8)


class ToolCallResult(BaseModel):
    id: str
    name: str
    ok: bool
    # Handed straight to `sendToolResponse` as the function response.
    response: dict[str, Any]
    decision_id: uuid.UUID | None = None
    requires_confirmation: bool = False
    confirmation_prompt: str | None = None


class ToolCallBatchOut(BaseModel):
    session_id: uuid.UUID
    results: list[ToolCallResult]


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #


class AiDecisionOut(ApiModel):
    id: uuid.UUID
    tool_name: str
    arguments: dict[str, Any]
    policy_result: PolicyResult
    policy_reason_code: str | None = None
    confirmation_state: ConfirmationState
    confirmation_prompt: str | None = None
    status: DecisionStatus
    result_entity_type: str | None = None
    result_entity_id: uuid.UUID | None = None
    error_code: str | None = None
    expires_at: dt.datetime | None = None
    executed_at: dt.datetime | None = None
    created_at: dt.datetime


class DecisionOutcome(BaseModel):
    decision: AiDecisionOut
    # The same structured object the tool would have returned, so the client
    # can send it to Gemini as the function response after a confirmation.
    tool_response: dict[str, Any] | None = None
    function_call_id: str | None = None
    tool_name: str | None = None


__all__ = [
    "AiDecisionOut",
    "AiJobOut",
    "AiSummaryOut",
    "ChatRequest",
    "ChatResponse",
    "DecisionOutcome",
    "LiveSessionOut",
    "LiveSessionRequest",
    "LiveToolDeclaration",
    "SummaryAccepted",
    "SummaryRequest",
    "ToolCallBatchIn",
    "ToolCallBatchOut",
    "ToolCallIn",
    "ToolCallResult",
]
