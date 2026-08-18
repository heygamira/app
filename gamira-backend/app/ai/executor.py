"""Executing a Live tool call.

The ordered checks a call passes before anything happens, each with its own
stable error code:

1. Is the session live, owned by this caller, and unexpired?
2. Is the tool a real one, and was it in *this session's* snapshot?
3. Do the arguments match the tool's strict schema?
4. Is the caller still a member of the family, still active, still permitted?
   (Re-checked here, not at session creation — a revocation lands mid-call.)
5. Does every id in the arguments belong to this session's senior?
6. Has this exact call id already run?
7. Does it need confirming first?

Only then does anything execute, and it executes by calling the same service
function the ordinary REST endpoint calls. There is no second implementation of
"mark a dose taken" for the voice path to drift away from.

What comes back to the model is small, structured and free of internals. Never
a traceback, never a database error, never a row it did not ask for.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import context as ai_context
from app.ai.policy import (
    DENY_TOOL_NOT_IN_SESSION,
    DENY_UNKNOWN_TOOL,
    ActorContext,
    PolicyDecision,
    confirmation_deadline,
    evaluate,
    load_actor_context,
)
from app.ai.tools import (
    CATALOGUE,
    TOOL_CANCEL_PENDING,
    TOOL_CONFIRM_PENDING,
    ToolSpec,
    get_tool,
    needs_confirmation,
    snapshot_names,
)
from app.ai.validation import ArgumentError, validate_arguments
from app.core.config import Settings, get_settings
from app.core.logging import current_request_id, get_logger
from app.db.base import utcnow
from app.models.ai import AiDecision, LiveSession
from app.models.care import Reminder
from app.models.enums import (
    ActorType,
    ConfirmationState,
    DecisionStatus,
    DoseSource,
    DoseStatus,
    LiveSessionStatus,
    MemoryKind,
    PolicyResult,
    ReminderStatus,
    ReminderType,
    TimelineEventType,
)
from app.models.medication import DoseEvent
from app.services import doses as dose_service
from app.services import memories as memory_service
from app.services.timeline import record_audit, record_timeline_event

logger = get_logger(__name__)

# The complete set of failures a tool call can report. Anything not in here is
# a bug, and is reported as ``action_failed`` rather than leaking its cause.
ERROR_PERMISSION_DENIED = "permission_denied"
ERROR_CONFIRMATION_REQUIRED = "confirmation_required"
ERROR_NOT_FOUND = "not_found"
ERROR_INVALID_ARGUMENTS = "invalid_arguments"
ERROR_DUPLICATE_CALL = "duplicate_call"
ERROR_DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
ERROR_ACTION_FAILED = "action_failed"
ERROR_SESSION_EXPIRED = "session_expired"
ERROR_UNKNOWN_TOOL = "unknown_tool"
# A navigation or "open this screen" tool arrived here. Those run in the app, so
# this is a client bug rather than anything the model did wrong — but it gets a
# named answer instead of a generic failure.
ERROR_CLIENT_TOOL = "client_tool"


@dataclass(frozen=True)
class ToolCall:
    """One ``functionCall`` from a Live message, as the client forwarded it."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolOutcome:
    """What goes back to the model, plus what the client needs to act on it."""

    call_id: str
    name: str
    ok: bool
    response: dict[str, Any]
    decision_id: uuid.UUID | None = None
    requires_confirmation: bool = False
    confirmation_prompt: str | None = None

    def as_function_response(self) -> dict[str, Any]:
        """The exact object to hand to ``session.sendToolResponse``.

        The id and name are echoed unchanged. A response whose id does not
        match its call is worse than no response: the model attributes an
        answer to the wrong question.
        """
        return {"id": self.call_id, "name": self.name, "response": self.response}


def error_response(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """A refusal the model can speak aloud without knowing anything internal."""
    return {"status": "error", "error": code, "message": message, **extra}


def ok_response(**payload: Any) -> dict[str, Any]:
    return {"status": "ok", **payload}


async def execute_tool_call(
    session: AsyncSession,
    *,
    live_session: LiveSession,
    call: ToolCall,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> ToolOutcome:
    """Run one tool call through every check, then execute or refuse."""
    settings = settings or get_settings()
    now = now or utcnow()

    spec = get_tool(call.name)
    if spec is None:
        return _refuse(
            call,
            ERROR_UNKNOWN_TOOL,
            "I do not have a tool by that name.",
            reason=DENY_UNKNOWN_TOOL,
        )

    if spec.kind == "client":
        # Client tools change this app, not the record: navigation, opening a
        # detail, opening the real SOS or dialer confirmation. The browser
        # dispatches them through its own allowlist and never forwards them, so
        # reaching the backend means something is misrouted.
        logger.warning(
            "client_tool_forwarded_to_backend",
            extra={"tool": call.name, "live_session_id": str(live_session.id)},
        )
        return _refuse(
            call,
            ERROR_CLIENT_TOOL,
            "That one happens on their screen, not on the server.",
        )

    in_snapshot = call.name in snapshot_names(live_session.tool_snapshot)

    try:
        arguments = validate_arguments(spec.parameters, call.arguments)
    except ArgumentError as exc:
        # The field and the reason, never the value the model sent.
        return _refuse(
            call,
            ERROR_INVALID_ARGUMENTS,
            "Those details were not in the form I can use.",
            field=exc.field,
            reason=exc.reason,
        )

    if call.name in (TOOL_CONFIRM_PENDING, TOOL_CANCEL_PENDING):
        # An answer to a question already asked. It proposes nothing of its own,
        # so it gets no decision row of its own — it carries a yes or a no to
        # the one already waiting, and that row's own checks run again there.
        if not in_snapshot:
            return _refuse(
                call,
                ERROR_PERMISSION_DENIED,
                _denial_message(DENY_TOOL_NOT_IN_SESSION),
                reason=DENY_TOOL_NOT_IN_SESSION,
            )
        return await _answer_confirmation(
            session,
            live_session=live_session,
            call=call,
            arguments=arguments,
            now=now,
        )

    actor = await load_actor_context(
        session,
        user_id=live_session.user_id,
        senior_profile_id=live_session.senior_profile_id,
    )

    entity = None
    if actor is not None:
        entity, ownership_error = await _resolve_entity(session, spec, arguments, actor)
        if ownership_error is not None:
            return _refuse(call, ownership_error, "I could not find that here.")

    # Worked out here, from the spec and the validated arguments, and handed to
    # the policy engine — which stays ignorant of both the arguments and the
    # model that produced them.
    confirm_first = needs_confirmation(spec, arguments)
    decision_policy = evaluate(
        spec=spec,
        actor=actor,
        in_session_snapshot=in_snapshot,
        requires_confirmation=confirm_first,
        confirmation_prompt=(
            _confirmation_prompt(spec, entity, arguments) if confirm_first else None
        ),
    )
    if decision_policy.result is PolicyResult.DENIED:
        return _refuse(
            call,
            ERROR_PERMISSION_DENIED,
            _denial_message(decision_policy.reason_code),
            reason=decision_policy.reason_code,
        )

    assert actor is not None  # a denial above is the only path with no actor

    idempotency_key = f"live:{live_session.id}:{call.id}"
    existing = (
        await session.execute(
            select(AiDecision).where(AiDecision.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _replay(call, existing)

    if confirm_first:
        open_already = await _open_confirmation(
            session, live_session=live_session, call=call, arguments=arguments, now=now
        )
        if open_already is not None:
            # The same request again while the first one is still on screen —
            # a model that asked, heard nothing, and tried once more. It gets a
            # new call id, so the idempotency key above does not catch it, and
            # without this the person would be answering two dialogs for one
            # thing. They see one, and it is the one already waiting.
            return _replay(call, open_already)

    decision = AiDecision(
        conversation_id=live_session.conversation_id,
        live_session_id=live_session.id,
        user_id=actor.user.id,
        family_id=actor.senior.family_id,
        senior_profile_id=actor.senior.id,
        tool_name=call.name,
        function_call_id=call.id[:128],
        arguments=arguments,
        policy_result=decision_policy.result,
        policy_reason_code=decision_policy.reason_code,
        model=live_session.model,
        provider=live_session.provider,
        prompt_version=live_session.prompt_version,
        idempotency_key=idempotency_key,
        request_id=current_request_id() or None,
    )
    session.add(decision)
    live_session.tool_call_count += 1
    live_session.last_seen_at = now

    if decision_policy.needs_confirmation:
        decision.confirmation_state = ConfirmationState.PENDING
        decision.confirmation_prompt = decision_policy.confirmation_prompt
        decision.status = DecisionStatus.PROPOSED
        decision.expires_at = confirmation_deadline(
            settings.ai_confirmation_ttl_seconds, now
        )
        await session.flush()
        return ToolOutcome(
            call_id=call.id,
            name=call.name,
            ok=False,
            requires_confirmation=True,
            confirmation_prompt=decision_policy.confirmation_prompt,
            decision_id=decision.id,
            response=error_response(
                ERROR_CONFIRMATION_REQUIRED,
                "Ask them to confirm before this happens.",
                confirmation_prompt=decision_policy.confirmation_prompt,
                decision_id=str(decision.id),
            ),
        )

    decision.confirmation_state = ConfirmationState.NOT_REQUIRED
    await session.flush()
    return await _perform(
        session, spec=spec, call=call, decision=decision, actor=actor, entity=entity
    )


async def confirm_decision(
    session: AsyncSession,
    *,
    decision: AiDecision,
    user_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> ToolOutcome:
    """Execute a decision a person has just approved.

    Everything is re-checked. The gap between showing a dialog and tapping it
    is small, but it is a gap, and a membership can be revoked inside it.
    """
    now = now or utcnow()
    call = ToolCall(
        id=decision.function_call_id or str(decision.id),
        name=decision.tool_name,
        arguments=dict(decision.arguments or {}),
    )
    spec = get_tool(decision.tool_name)
    if spec is None:  # pragma: no cover - a tool removed between call and confirm
        decision.status = DecisionStatus.FAILED
        decision.error_code = ERROR_UNKNOWN_TOOL
        return _refuse(call, ERROR_UNKNOWN_TOOL, "That action is no longer available.")

    if decision.confirmation_state is ConfirmationState.CONFIRMED:
        return _replay(call, decision)
    if decision.confirmation_state is not ConfirmationState.PENDING:
        return _refuse(
            call, ERROR_ACTION_FAILED, "That confirmation is no longer open."
        )
    if decision.expires_at is not None and decision.expires_at <= now:
        decision.confirmation_state = ConfirmationState.EXPIRED
        decision.status = DecisionStatus.EXPIRED
        await session.flush()
        return _refuse(
            call, ERROR_ACTION_FAILED, "That confirmation timed out. Ask me again."
        )

    actor = await load_actor_context(
        session,
        user_id=user_id,
        senior_profile_id=decision.senior_profile_id or uuid.uuid4(),
    )
    verdict: PolicyDecision = evaluate(
        spec=spec, actor=actor, in_session_snapshot=True
    )
    if verdict.result is PolicyResult.DENIED:
        decision.status = DecisionStatus.FAILED
        decision.error_code = verdict.reason_code
        await session.flush()
        return _refuse(
            call,
            ERROR_PERMISSION_DENIED,
            _denial_message(verdict.reason_code),
            reason=verdict.reason_code,
        )
    assert actor is not None

    entity, ownership_error = await _resolve_entity(
        session, spec, dict(decision.arguments or {}), actor
    )
    if ownership_error is not None:
        decision.status = DecisionStatus.FAILED
        decision.error_code = ownership_error
        await session.flush()
        return _refuse(call, ownership_error, "I could not find that here.")

    decision.confirmation_state = ConfirmationState.CONFIRMED
    decision.confirmed_by_user_id = user_id
    decision.confirmation_decided_at = now
    return await _perform(
        session, spec=spec, call=call, decision=decision, actor=actor, entity=entity
    )


async def reject_decision(
    session: AsyncSession,
    *,
    decision: AiDecision,
    user_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> AiDecision:
    """Decline a proposed action. Nothing is written but the refusal itself."""
    now = now or utcnow()
    if decision.confirmation_state is ConfirmationState.PENDING:
        decision.confirmation_state = ConfirmationState.REJECTED
        decision.confirmed_by_user_id = user_id
        decision.confirmation_decided_at = now
        decision.status = DecisionStatus.REJECTED
        await session.flush()
    return decision


async def _answer_confirmation(
    session: AsyncSession,
    *,
    live_session: LiveSession,
    call: ToolCall,
    arguments: dict[str, Any],
    now: dt.datetime,
) -> ToolOutcome:
    """Carry a spoken yes or no to a confirmation already waiting.

    This is what makes saying "yes" worth as much as tapping Yes, and it is
    deliberately the thinnest possible thing: it decides nothing. The action,
    its arguments and the exact sentence the person heard were all settled when
    the confirmation was raised. All that arrives here is which way they
    answered, and it goes to the same ``confirm_decision`` the button calls —
    which re-reads membership, role, ownership and expiry before anything runs.

    A decision id from any other session is not found, even a real one
    belonging to this same person. The model may only answer a question it was
    asked in this conversation, moments ago.
    """
    live_session.tool_call_count += 1
    live_session.last_seen_at = now

    decision = None
    try:
        decision_id = uuid.UUID(str(arguments.get("decision_id")))
    except (ValueError, TypeError, AttributeError):
        decision_id = None
    if decision_id is not None:
        decision = await session.get(AiDecision, decision_id)
    if decision is None or decision.live_session_id != live_session.id:
        return _refuse(
            call, ERROR_NOT_FOUND, "I have not asked them to confirm anything."
        )

    if call.name == TOOL_CANCEL_PENDING:
        was_open = decision.confirmation_state is ConfirmationState.PENDING
        await reject_decision(
            session, decision=decision, user_id=live_session.user_id, now=now
        )
        return ToolOutcome(
            call_id=call.id,
            name=call.name,
            ok=True,
            decision_id=decision.id,
            response=ok_response(
                resolved_decision_id=str(decision.id),
                outcome="cancelled" if was_open else "already_closed",
                message="Nothing was changed.",
            ),
        )

    outcome = await confirm_decision(
        session, decision=decision, user_id=live_session.user_id, now=now
    )
    # The persisted result of the underlying action, reported under the name of
    # the call that asked for it — so the model can only say a dose was
    # recorded once a dose really was.
    return ToolOutcome(
        call_id=call.id,
        name=call.name,
        ok=outcome.ok,
        decision_id=decision.id,
        response={**outcome.response, "resolved_decision_id": str(decision.id)},
    )


async def _open_confirmation(
    session: AsyncSession,
    *,
    live_session: LiveSession,
    call: ToolCall,
    arguments: dict[str, Any],
    now: dt.datetime,
) -> AiDecision | None:
    """The identical request already waiting on this person, if there is one."""
    rows = (
        await session.execute(
            select(AiDecision).where(
                AiDecision.live_session_id == live_session.id,
                AiDecision.tool_name == call.name,
                AiDecision.confirmation_state == ConfirmationState.PENDING,
            )
        )
    ).scalars()
    for candidate in rows:
        if candidate.expires_at is not None and candidate.expires_at <= now:
            continue
        if dict(candidate.arguments or {}) == arguments:
            return candidate
    return None


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


async def _perform(
    session: AsyncSession,
    *,
    spec: ToolSpec,
    call: ToolCall,
    decision: AiDecision,
    actor: ActorContext,
    entity: Any,
) -> ToolOutcome:
    try:
        response, reference = await _run_tool(
            session, spec=spec, arguments=dict(decision.arguments or {}), actor=actor,
            entity=entity, decision=decision,
        )
    except Exception:
        # The cause is logged with the decision id and never returned: a
        # database message is not something to hand a language model.
        logger.exception(
            "tool_call_failed",
            extra={"decision_id": str(decision.id), "tool": spec.name},
        )
        decision.status = DecisionStatus.FAILED
        decision.error_code = ERROR_ACTION_FAILED
        await session.flush()
        return _refuse(call, ERROR_ACTION_FAILED, "That did not work. Nothing changed.")

    decision.status = DecisionStatus.EXECUTED
    decision.executed_at = utcnow()
    if reference is not None:
        decision.result_entity_type, decision.result_entity_id = reference
    await session.flush()

    if spec.kind == "mutation":
        await record_audit(
            session,
            action=f"ai.tool.{spec.name}",
            actor_user_id=actor.user.id,
            # The person authorised it; the assistant carried it out. Both are
            # true and the trail records both, so an AI-originated change is
            # never indistinguishable from one somebody typed.
            actor_type=ActorType.AI,
            target_type=decision.result_entity_type,
            target_id=decision.result_entity_id,
            family_id=actor.senior.family_id,
            metadata={"decision_id": str(decision.id), "via": "live_voice"},
        )

    return ToolOutcome(
        call_id=call.id,
        name=call.name,
        ok=True,
        response=ok_response(**response),
        decision_id=decision.id,
    )


async def _run_tool(
    session: AsyncSession,
    *,
    spec: ToolSpec,
    arguments: dict[str, Any],
    actor: ActorContext,
    entity: Any,
    decision: AiDecision,
) -> tuple[dict[str, Any], tuple[str, uuid.UUID] | None]:
    """Dispatch to the one implementation of this tool."""
    name = spec.name

    if name == "get_today_doses":
        return await ai_context.today_doses(session, actor), None
    if name == "get_today_schedule":
        return await ai_context.today_schedule(session, actor), None
    if name == "get_reminders":
        return await ai_context.active_reminders(session, actor), None
    if name == "get_latest_health_readings":
        return (
            await ai_context.latest_health_readings(
                session, actor, metric=arguments.get("metric")
            ),
            None,
        )
    if name == "get_upcoming_appointments":
        return await ai_context.upcoming_appointments(session, actor), None
    if name == "get_emergency_contacts":
        return await ai_context.emergency_contacts(session, actor), None
    if name == "get_notification_summary":
        return await ai_context.notification_summary(session, actor), None

    if name in ("mark_dose_taken", "mark_dose_skipped"):
        return await _record_dose(
            session,
            actor=actor,
            event=entity,
            status=(
                DoseStatus.TAKEN if name == "mark_dose_taken" else DoseStatus.SKIPPED
            ),
        )
    if name == "create_reminder":
        return await _create_reminder(session, actor=actor, arguments=arguments)
    if name == "complete_reminder":
        return await _complete_reminder(session, actor=actor, reminder=entity)
    if name == "remember_this":
        return await _remember_this(
            session, actor=actor, arguments=arguments, decision=decision
        )

    # Client tools are dispatched in the browser and must never arrive here.
    raise ValueError(f"Tool {name!r} has no backend implementation.")


async def _record_dose(
    session: AsyncSession,
    *,
    actor: ActorContext,
    event: DoseEvent,
    status: DoseStatus,
) -> tuple[dict[str, Any], tuple[str, uuid.UUID]]:
    """Record a dose through the same service the REST endpoint uses.

    The idempotency key is the tool name plus the dose, so a second voice
    attempt on the same dose returns the existing canonical event rather than
    recording a second one — the same guarantee a double tap gets.
    """
    updated, changed = await dose_service.record_dose_outcome(
        session,
        event=event,
        status=status,
        actor_user_id=actor.user.id,
        source=DoseSource.PARENT_APP,
        idempotency_key=f"voice:{status.value}:{event.id}",
    )
    medication = updated.medication.name if updated.medication else "the medicine"
    return (
        {
            "dose_event_id": str(updated.id),
            "medication": medication,
            "time": updated.scheduled_local_time,
            "recorded_status": updated.status.value,
            "changed": changed,
            "message": (
                f"{medication} at {updated.scheduled_local_time} is recorded as "
                f"{updated.status.value}."
            ),
        },
        ("dose_event", updated.id),
    )


async def _create_reminder(
    session: AsyncSession, *, actor: ActorContext, arguments: dict[str, Any]
) -> tuple[dict[str, Any], tuple[str, uuid.UUID]]:
    """Add an everyday reminder, spoken aloud.

    Deliberately fixed here rather than taken from the model:

    * ``type`` is never ``MEDICATION``. There is no tool for scheduling a
      medicine and this must not become one by the back door — a reminder that
      merely *says* "take your tablet" is a note, and a real dose schedule with
      a record behind it is a different thing entirely.
    * ``senior_profile_id`` and ``family_id`` come from the verified actor, not
      from anything said in the conversation.
    * ``timezone`` is the person's own, so "half four" means half four where
      they are.
    """
    title = arguments["title"].strip()
    reminder = Reminder(
        family_id=actor.senior.family_id,
        senior_profile_id=actor.senior.id,
        type=ReminderType.OTHER,
        title=title[:200],
        instructions=(arguments.get("instructions") or "").strip() or None,
        # Empty means every day, which is what somebody asking out loud means.
        days_of_week="",
        local_time=arguments["local_time"],
        timezone=actor.senior.timezone,
        status=ReminderStatus.ACTIVE,
        created_by_user_id=actor.user.id,
    )
    session.add(reminder)
    await session.flush()

    await record_timeline_event(
        session,
        family_id=reminder.family_id,
        senior_profile_id=reminder.senior_profile_id,
        type=TimelineEventType.REMINDER_ADDED,
        title=f"{reminder.title} added",
        related_entity_type="reminder",
        related_entity_id=reminder.id,
        actor_user_id=actor.user.id,
        dedupe_key=f"reminder-created:{reminder.id}",
    )
    await session.flush()

    return (
        {
            "reminder_id": str(reminder.id),
            "title": reminder.title,
            "local_time": reminder.local_time,
            "message": f"{reminder.title} is set for {reminder.local_time} every day.",
        },
        ("reminder", reminder.id),
    )


async def _remember_this(
    session: AsyncSession,
    *,
    actor: ActorContext,
    arguments: dict[str, Any],
    decision: AiDecision,
) -> tuple[dict[str, Any], tuple[str, uuid.UUID] | None]:
    """Keep one ordinary thing about this person between conversations.

    No confirmation, deliberately. "I'll remember that" has to be true the
    moment it is said, and a dialog in the middle of somebody telling you about
    their granddaughter is worse than the risk — which is one wrong sentence,
    on a list they can read and delete, in a table nothing clinical reads from.

    The person, the family and the provenance all come from the verified
    session. The model supplies two things: which kind it is, from a fixed list
    that has no medical member, and the sentence itself.
    """
    kind = MemoryKind(arguments["kind"])
    content = arguments["content"]
    # The same thing said twice, a week apart, is one memory. Keyed on the
    # normalised words rather than the row, so it survives rephrasing of
    # whitespace and case but not of meaning.
    fingerprint = hashlib.sha256(
        " ".join(content.lower().split()).encode("utf-8")
    ).hexdigest()[:32]
    memory, created = await memory_service.remember(
        session,
        family_id=actor.senior.family_id,
        senior_profile_id=actor.senior.id,
        kind=kind,
        content=content,
        source_conversation_id=decision.conversation_id,
        model=decision.model,
        provider=decision.provider,
        prompt_version=decision.prompt_version,
        dedupe_key=f"memory:{actor.senior.id}:{fingerprint}",
    )
    if not created:
        # Already held, or held and deleted by them. Neither is an error and
        # neither writes anything — but the model must not say "I'll remember
        # that" as though it were new, and must not be told which case it was.
        return {"remembered": False, "message": "I already knew that one."}, None
    assert memory is not None
    return (
        {
            "remembered": True,
            "kind": memory.kind.value,
            "message": "I will remember that.",
        },
        ("senior_memory", memory.id),
    )


async def _complete_reminder(
    session: AsyncSession, *, actor: ActorContext, reminder: Reminder
) -> tuple[dict[str, Any], tuple[str, uuid.UUID]]:
    changed = reminder.status is not ReminderStatus.COMPLETED
    if changed:
        reminder.status = ReminderStatus.COMPLETED
        reminder.last_completed_at = utcnow()
        await record_timeline_event(
            session,
            family_id=reminder.family_id,
            senior_profile_id=reminder.senior_profile_id,
            type=TimelineEventType.REMINDER_COMPLETED,
            title=f"{reminder.title} completed",
            related_entity_type="reminder",
            related_entity_id=reminder.id,
            actor_user_id=actor.user.id,
            dedupe_key=f"reminder-completed:{reminder.id}:{utcnow().date().isoformat()}",
        )
        await session.flush()
    return (
        {
            "reminder_id": str(reminder.id),
            "title": reminder.title,
            "changed": changed,
            "message": f"{reminder.title} is marked done.",
        },
        ("reminder", reminder.id),
    )


# --------------------------------------------------------------------------- #
# Entity ownership
# --------------------------------------------------------------------------- #


async def _resolve_entity(
    session: AsyncSession,
    spec: ToolSpec,
    arguments: dict[str, Any],
    actor: ActorContext,
) -> tuple[Any, str | None]:
    """Load the row an argument names, and refuse it if it is not this person's.

    A well-formed uuid from another family looks exactly like a well-formed
    uuid from this one, which is why this check is by ownership rather than by
    existence — and why a foreign id gets the same "not found" as an invented
    one.
    """
    dose_id = arguments.get("dose_event_id")
    if dose_id:
        event = await session.get(DoseEvent, uuid.UUID(str(dose_id)))
        if event is None or event.senior_profile_id != actor.senior.id:
            return None, ERROR_NOT_FOUND
        # Reload with the relationships the executor and prompt need.
        return await dose_service.get_dose_event(session, event.id), None

    reminder_id = arguments.get("reminder_id")
    if reminder_id:
        reminder = await session.get(Reminder, uuid.UUID(str(reminder_id)))
        if reminder is None or reminder.senior_profile_id != actor.senior.id:
            return None, ERROR_NOT_FOUND
        return reminder, None

    contact_id = arguments.get("contact_id")
    if contact_id:
        from app.models.care import EmergencyContact

        contact = await session.get(EmergencyContact, uuid.UUID(str(contact_id)))
        if contact is None or contact.senior_profile_id != actor.senior.id:
            return None, ERROR_NOT_FOUND
        return contact, None

    return None, None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _confirmation_prompt(
    spec: ToolSpec, entity: Any, arguments: dict[str, Any] | None = None
) -> str:
    """The exact sentence a person is shown and hears.

    Built from the loaded row, so it names the real medicine at the real time —
    "Mark Metformin scheduled for 8:00 AM as taken?" — and cannot describe
    something other than what will run.
    """
    if spec.name in ("mark_dose_taken", "mark_dose_skipped"):
        if isinstance(entity, DoseEvent):
            medication = entity.medication.name if entity.medication else "this medicine"
            verb = "taken" if spec.name == "mark_dose_taken" else "skipped"
            return (
                f"Mark {medication} scheduled for "
                f"{_spoken_time(entity.scheduled_local_time)} as {verb}?"
            )
        return "Record this dose?"
    if spec.name == "create_reminder":
        # There is no row yet, so this is built from the validated arguments —
        # the same values that will be written, not a paraphrase of them.
        args = arguments or {}
        title = args.get("title") or "a reminder"
        return f"Add a reminder to {title} at {_spoken_time(args.get('local_time', ''))}?"
    if spec.name == "complete_reminder":
        title = entity.title if isinstance(entity, Reminder) else "this reminder"
        return f"Mark {title} as done?"
    if spec.name == "prepare_sos":
        return "Open the emergency SOS screen?"
    if spec.name == "prepare_call_contact":
        name = getattr(entity, "name", None)
        return f"Open the dialer to call {name}?" if name else "Open the dialer?"
    return f"Go ahead with {spec.name.replace('_', ' ')}?"  # pragma: no cover


def _spoken_time(local_time: str) -> str:
    """``08:00`` as ``8:00 AM`` — a confirmation is read aloud, not parsed."""
    try:
        hour, minute = (int(part) for part in local_time.split(":", 1))
    except (ValueError, AttributeError):  # pragma: no cover - column is validated
        return local_time
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def _denial_message(reason_code: str | None) -> str:
    return {
        "membership_revoked": "I no longer have access to that person's record.",
        "user_suspended": "This account cannot do that at the moment.",
        "role_insufficient": "They are not allowed to change that from here.",
        "tool_not_in_session": "That is not something I can do in this session.",
    }.get(reason_code or "", "I am not allowed to do that.")


def _refuse(call: ToolCall, code: str, message: str, **extra: Any) -> ToolOutcome:
    return ToolOutcome(
        call_id=call.id,
        name=call.name,
        ok=False,
        response=error_response(code, message, **extra),
    )


def _replay(call: ToolCall, decision: AiDecision) -> ToolOutcome:
    """Answer a repeated call id without doing anything a second time."""
    if decision.confirmation_state is ConfirmationState.PENDING:
        # Not a duplicate — the confirmation is simply still open.
        return ToolOutcome(
            call_id=call.id,
            name=call.name,
            ok=False,
            requires_confirmation=True,
            confirmation_prompt=decision.confirmation_prompt,
            decision_id=decision.id,
            response=error_response(
                ERROR_CONFIRMATION_REQUIRED,
                "Ask them to confirm before this happens.",
                confirmation_prompt=decision.confirmation_prompt,
                decision_id=str(decision.id),
            ),
        )
    return ToolOutcome(
        call_id=call.id,
        name=call.name,
        ok=False,
        decision_id=decision.id,
        response=error_response(
            ERROR_DUPLICATE_CALL,
            "That was already handled — nothing was done twice.",
            previous_status=decision.status.value,
        ),
    )


def catalogue_names() -> list[str]:
    return sorted(CATALOGUE)


def is_expired(live_session: LiveSession, now: dt.datetime | None = None) -> bool:
    now = now or utcnow()
    return (
        live_session.status is not LiveSessionStatus.ACTIVE
        or live_session.expires_at <= now
    )


__all__ = [
    "ERROR_ACTION_FAILED",
    "ERROR_CLIENT_TOOL",
    "ERROR_CONFIRMATION_REQUIRED",
    "ERROR_DEPENDENCY_UNAVAILABLE",
    "ERROR_DUPLICATE_CALL",
    "ERROR_INVALID_ARGUMENTS",
    "ERROR_NOT_FOUND",
    "ERROR_PERMISSION_DENIED",
    "ERROR_SESSION_EXPIRED",
    "ERROR_UNKNOWN_TOOL",
    "ToolCall",
    "ToolOutcome",
    "catalogue_names",
    "confirm_decision",
    "execute_tool_call",
    "is_expired",
    "reject_decision",
]
