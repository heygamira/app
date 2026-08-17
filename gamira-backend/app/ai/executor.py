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
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import context as ai_context
from app.ai.policy import (
    DENY_UNKNOWN_TOOL,
    ActorContext,
    PolicyDecision,
    confirmation_deadline,
    evaluate,
    load_actor_context,
)
from app.ai.tools import CATALOGUE, ToolSpec, get_tool, snapshot_names
from app.ai.validation import ArgumentError, validate_arguments
from app.core.config import Settings, get_settings
from app.core.logging import current_request_id, get_logger
from app.db.base import utcnow
from app.models.ai import AiDecision, LiveSession
from app.models.care import Reminder
from app.models.enums import (
    ConfirmationState,
    DecisionStatus,
    DoseSource,
    DoseStatus,
    LiveSessionStatus,
    PolicyResult,
    ReminderStatus,
    TimelineEventType,
)
from app.models.medication import DoseEvent
from app.services import doses as dose_service
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

    decision_policy = evaluate(
        spec=spec,
        actor=actor,
        in_session_snapshot=in_snapshot,
        confirmation_prompt=(
            _confirmation_prompt(spec, entity) if spec.requires_confirmation else None
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
            entity=entity,
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
    if name == "complete_reminder":
        return await _complete_reminder(session, actor=actor, reminder=entity)

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


def _confirmation_prompt(spec: ToolSpec, entity: Any) -> str:
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
