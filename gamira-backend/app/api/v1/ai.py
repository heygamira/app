"""The AI endpoints.

Every route here begins the same way: resolve the senior through
``resolve_senior``, which refuses anyone without an active membership in that
family and returns the same 404 to an outsider as to somebody naming a person
who does not exist. Nothing downstream re-derives permission from a request
body.

Chat and summaries degrade rather than fail: the figures behind a summary are
counted and stored before any model is called, so a provider outage costs the
wording and nothing else.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.ai import context as ai_context
from app.ai import live as live_service
from app.ai import summaries as summary_service
from app.ai import usage as usage_service
from app.ai.executor import (
    ToolCall,
    confirm_decision,
    execute_tool_call,
    is_expired,
    reject_decision,
)
from app.ai.policy import load_actor_context
from app.ai.prompts import CHAT_REPLY_V1
from app.ai.provider import AIError, generate_with_retry, get_ai_provider
from app.ai.schemas import ChatReplyOut
from app.ai.tools import snapshot_names
from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.core.errors import Conflict, DependencyUnavailable, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.db.base import utcnow
from app.jobs.queue import enqueue_job
from app.jobs.types import JobType
from app.models.ai import (
    AiDecision,
    AiSummary,
    Conversation,
    ConversationMessage,
    LiveSession,
)
from app.models.enums import (
    ConfirmationState,
    ConversationChannel,
    ConversationStatus,
    MessageRole,
)
from app.models.jobs import BackgroundJob
from app.schemas.ai import (
    AiDecisionOut,
    AiJobOut,
    AiSummaryOut,
    ChatRequest,
    ChatResponse,
    DecisionOutcome,
    LiveSessionOut,
    LiveSessionRequest,
    SummaryAccepted,
    SummaryRequest,
    ToolCallBatchIn,
    ToolCallBatchOut,
    ToolCallResult,
)
from app.services.authz import active_memberships, require_membership, resolve_senior
from app.services.timeline import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #


@router.post(
    "/summaries", response_model=SummaryAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def request_summary(
    payload: SummaryRequest, session: SessionDep, user: CurrentUser
) -> SummaryAccepted:
    """Count the period now, and queue the wording.

    Returns 202 with a ``summary_id`` that already resolves: the figures are
    persisted synchronously, so a client can show them immediately and does not
    depend on the model to have anything worth reading.
    """
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=payload.senior_id
    )
    period_start, period_end = _resolve_period(senior.timezone, payload)

    summary, _facts, _created = await summary_service.prepare_summary(
        session,
        senior=senior,
        requested_by_user_id=user.id,
        period_start=period_start,
        period_end=period_end,
    )
    job = await enqueue_job(
        session,
        JobType.AI_WEEKLY_SUMMARY,
        payload={
            "senior_profile_id": str(senior.id),
            "requested_by_user_id": str(user.id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
        dedupe_key=f"weekly-summary:{summary.id}",
        family_id=senior.family_id,
        actor_user_id=user.id,
    )
    await record_audit(
        session,
        action="ai.summary.request",
        actor_user_id=user.id,
        target_type="ai_summary",
        target_id=summary.id,
        family_id=senior.family_id,
    )
    return SummaryAccepted(job_id=job.id if job else None, summary_id=summary.id)


@router.get("/summaries/{summary_id}", response_model=AiSummaryOut)
async def get_summary(
    summary_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> AiSummaryOut:
    summary = await session.get(AiSummary, summary_id)
    if summary is None:
        raise NotFound("The requested summary does not exist.")
    await require_membership(session, user_id=user.id, family_id=summary.family_id)
    return AiSummaryOut.model_validate(summary)


@router.get("/seniors/{senior_id}/summaries", response_model=list[AiSummaryOut])
async def list_summaries(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[AiSummaryOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    rows = await session.execute(
        select(AiSummary)
        .where(AiSummary.senior_profile_id == senior_id)
        .order_by(AiSummary.period_start.desc())
        .limit(limit)
    )
    return [AiSummaryOut.model_validate(row) for row in rows.scalars()]


@router.get("/jobs/{job_id}", response_model=AiJobOut)
async def get_job(
    job_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> AiJobOut:
    """The state of one queued AI job.

    Visible to members of the family the job belongs to, and to whoever asked
    for it. A job with neither is not something to show anybody.
    """
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        raise NotFound("The requested job does not exist.")
    if job.family_id is not None:
        await require_membership(session, user_id=user.id, family_id=job.family_id)
    elif job.actor_user_id != user.id:
        raise NotFound("The requested job does not exist.")
    return AiJobOut.model_validate(job)


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest, session: SessionDep, user: CurrentUser, settings: SettingsDep
) -> ChatResponse:
    """A permission-scoped text question.

    The context is built from the caller's verified membership, not from
    anything in the message. The message itself is untrusted content: it is
    passed as data, and the prompt says so.
    """
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=payload.senior_id
    )
    actor = await load_actor_context(
        session, user_id=user.id, senior_profile_id=senior.id
    )
    if actor is None:  # pragma: no cover - resolve_senior already required this
        raise PermissionDenied("You do not have access to this person's record.")

    conversation = await _conversation_for(
        session, payload, user_id=user.id, senior=senior
    )
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=payload.message[:2000],
        )
    )

    context = await ai_context.chat_context(session, actor)
    prompt = CHAT_REPLY_V1
    rendered = prompt.render(
        senior_name=senior.preferred_name,
        today=utcnow().date().isoformat(),
        timezone=senior.timezone,
        context_json=json.dumps(context, indent=2, default=str),
        question=payload.message,
    )

    provider = get_ai_provider(settings)
    try:
        result = await generate_with_retry(
            provider,
            prompt=prompt,
            rendered=rendered,
            output_model=ChatReplyOut,
            settings=settings,
        )
    except AIError as exc:
        await usage_service.record_usage(
            session,
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "model", "unknown"),
            operation="chat",
            outcome="failed",
            error_code=exc.code,
            prompt_version=prompt.version,
            family_id=senior.family_id,
            user_id=user.id,
            conversation_id=conversation.id,
        )
        # A 503 with a stable code, so the app can say "the assistant is
        # unavailable" and keep every other screen working.
        raise DependencyUnavailable(
            "Gamira's assistant is unavailable right now. Everything else still works.",
            code=exc.code,
        ) from exc

    reply = result.output
    assert isinstance(reply, ChatReplyOut)
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=reply.reply,
            model=result.model,
            provider=result.provider,
            prompt_version=f"{prompt.name}@{prompt.version}",
        )
    )
    await usage_service.record_result(
        session,
        result,
        operation="chat",
        family_id=senior.family_id,
        user_id=user.id,
        conversation_id=conversation.id,
    )
    return ChatResponse(
        conversation_id=conversation.id,
        reply=reply.reply,
        model=result.model,
        provider=result.provider,
        prompt_version=f"{prompt.name}@{prompt.version}",
        refused=reply.refused,
        refusal_code=reply.refusal_code,
    )


async def _conversation_for(
    session: SessionDep, payload: ChatRequest, *, user_id: uuid.UUID, senior
) -> Conversation:
    if payload.conversation_id is not None:
        conversation = await session.get(Conversation, payload.conversation_id)
        # Somebody else's conversation is not found, not forbidden.
        if conversation is None or conversation.user_id != user_id:
            raise NotFound("The requested conversation does not exist.")
        return conversation
    conversation = Conversation(
        family_id=senior.family_id,
        user_id=user_id,
        senior_profile_id=senior.id,
        channel=ConversationChannel.TEXT,
        status=ConversationStatus.ACTIVE,
    )
    session.add(conversation)
    await session.flush()
    return conversation


# --------------------------------------------------------------------------- #
# Live sessions
# --------------------------------------------------------------------------- #


@router.post(
    "/live-sessions", response_model=LiveSessionOut, status_code=status.HTTP_201_CREATED
)
async def create_live_session(
    payload: LiveSessionRequest,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> LiveSessionOut:
    """Start an authenticated voice session and mint its ephemeral token.

    The senior is resolved from the caller's memberships. Omitting
    ``senior_id`` picks the profile linked to the signed-in user, which is what
    the Parent App does — the person's own device, their own record.
    """
    senior, membership = await _live_scope(session, user=user, payload=payload)

    created = await live_service.create_live_session(
        session, user=user, senior=senior, membership=membership, settings=settings
    )
    await record_audit(
        session,
        action="ai.live_session.create",
        actor_user_id=user.id,
        target_type="live_session",
        target_id=created.session.id,
        family_id=senior.family_id,
        # The fingerprint identifies the session's token in an audit trail. The
        # token itself is never recorded, here or anywhere.
        metadata={
            "model": created.session.model,
            "tools": len(created.session.tool_snapshot or []),
            "token": created.token.fingerprint,
        },
    )
    return LiveSessionOut(
        session_id=created.session.id,
        conversation_id=created.session.conversation_id,
        token=created.token.token,
        model=created.token.model,
        api_version=created.token.api_version,
        expires_at=created.token.expires_at,
        connect_before=created.token.open_before,
        senior_id=senior.id,
        senior_name=senior.preferred_name,
        tools=sorted(snapshot_names(created.session.tool_snapshot)),
    )


@router.post(
    "/live-sessions/{session_id}/tool-calls", response_model=ToolCallBatchOut
)
async def handle_tool_calls(
    session_id: uuid.UUID,
    payload: ToolCallBatchIn,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ToolCallBatchOut:
    """Run the tool calls from one Live message.

    A model may emit several at once, so this takes a batch and returns one
    result per call, each carrying back its own id and name unchanged. One
    call failing never fails the batch — a tool error is a structured result
    the model can speak, not an exception that ends the conversation.
    """
    live_session = await _owned_live_session(session, session_id=session_id, user=user)

    results: list[ToolCallResult] = []
    for call in payload.calls:
        outcome = await execute_tool_call(
            session,
            live_session=live_session,
            call=ToolCall(id=call.id, name=call.name, arguments=call.arguments),
            settings=settings,
        )
        results.append(
            ToolCallResult(
                id=outcome.call_id,
                name=outcome.name,
                ok=outcome.ok,
                response=outcome.response,
                decision_id=outcome.decision_id,
                requires_confirmation=outcome.requires_confirmation,
                confirmation_prompt=outcome.confirmation_prompt,
            )
        )
    return ToolCallBatchOut(session_id=live_session.id, results=results)


@router.post("/live-sessions/{session_id}/close", response_model=None, status_code=204)
async def close_live_session(
    session_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    """End a session early. Idempotent."""
    live_session = await session.get(LiveSession, session_id)
    if live_session is None or live_session.user_id != user.id:
        raise NotFound("The requested session does not exist.")
    await live_service.close_live_session(session, live_session=live_session)


# --------------------------------------------------------------------------- #
# Confirmations
# --------------------------------------------------------------------------- #


@router.post("/actions/{decision_id}/confirm", response_model=DecisionOutcome)
async def confirm_action(
    decision_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DecisionOutcome:
    """Approve a proposed action and run it.

    Everything is re-checked at this point, not carried over from when the
    dialog was shown: the arguments come from the stored decision, and the
    permission from the database as it is now.
    """
    decision = await _owned_decision(session, decision_id=decision_id, user=user)
    outcome = await confirm_decision(session, decision=decision, user_id=user.id)
    return DecisionOutcome(
        decision=AiDecisionOut.model_validate(decision),
        tool_response=outcome.response,
        function_call_id=outcome.call_id,
        tool_name=outcome.name,
    )


@router.post("/actions/{decision_id}/reject", response_model=DecisionOutcome)
async def reject_action(
    decision_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DecisionOutcome:
    """Decline a proposed action. Nothing is written but the refusal."""
    decision = await _owned_decision(session, decision_id=decision_id, user=user)
    await reject_decision(session, decision=decision, user_id=user.id)
    return DecisionOutcome(
        decision=AiDecisionOut.model_validate(decision),
        tool_response={
            "status": "error",
            "error": "rejected_by_user",
            "message": "They said no, so nothing was changed.",
        },
        function_call_id=decision.function_call_id,
        tool_name=decision.tool_name,
    )


@router.get("/actions/{decision_id}", response_model=AiDecisionOut)
async def get_action(
    decision_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> AiDecisionOut:
    decision = await _owned_decision(session, decision_id=decision_id, user=user)
    return AiDecisionOut.model_validate(decision)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _live_scope(
    session: SessionDep, *, user: CurrentUser, payload: LiveSessionRequest
):
    """The senior and membership a Live session is scoped to.

    Derived here and written onto the session row. Nothing the model later says
    can widen it.
    """
    if payload.senior_id is not None:
        return await resolve_senior(
            session, user_id=user.id, senior_id=payload.senior_id
        )

    from app.models.identity import SeniorProfile

    memberships = await active_memberships(session, user.id)
    if not memberships:
        raise NotFound("There is nobody here for Gamira to talk about.")
    family_ids = [membership.family_id for membership in memberships]
    rows = await session.execute(
        select(SeniorProfile)
        .where(
            SeniorProfile.family_id.in_(family_ids),
            SeniorProfile.archived_at.is_(None),
        )
        .order_by(SeniorProfile.created_at)
    )
    seniors = list(rows.scalars())
    # The Parent App is one person's own device, so their own profile wins.
    own = next((s for s in seniors if s.user_id == user.id), None)
    chosen = own or (seniors[0] if seniors else None)
    if chosen is None:
        raise NotFound("There is nobody here for Gamira to talk about.")
    return await resolve_senior(session, user_id=user.id, senior_id=chosen.id)


async def _owned_live_session(
    session: SessionDep, *, session_id: uuid.UUID, user: CurrentUser
) -> LiveSession:
    live_session = await session.get(LiveSession, session_id)
    if live_session is None or live_session.user_id != user.id:
        # Another person's session is not found, not forbidden: a session id is
        # not something to confirm the existence of.
        raise NotFound("The requested session does not exist.")
    if is_expired(live_session):
        # Deliberately no write here: this request is about to fail, and the
        # session's transaction rolls back with it. Marking the row is the
        # expiry sweep's job (``ai.live_sessions.expire``), which is also what
        # frees the concurrency slot.
        raise Conflict("This voice session has ended.", code="session_expired")
    return live_session


async def _owned_decision(
    session: SessionDep, *, decision_id: uuid.UUID, user: CurrentUser
) -> AiDecision:
    decision = await session.get(AiDecision, decision_id)
    if decision is None or decision.user_id != user.id:
        raise NotFound("The requested action does not exist.")
    if (
        decision.confirmation_state is ConfirmationState.PENDING
        and decision.expires_at is not None
        and decision.expires_at <= utcnow()
    ):
        decision.confirmation_state = ConfirmationState.EXPIRED
        await session.flush()
    return decision


def _resolve_period(
    timezone_name: str, payload: SummaryRequest
) -> tuple[dt.date, dt.date]:
    if payload.period_start and payload.period_end:
        if payload.period_end < payload.period_start:
            raise Conflict(
                "The end of the period is before its start.", code="invalid_period"
            )
        if (payload.period_end - payload.period_start).days > 92:
            raise Conflict(
                "That period is too long to summarise.", code="period_too_long"
            )
        return payload.period_start, payload.period_end
    return summary_service.default_period(timezone_name)
