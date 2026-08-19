"""The Live tool catalogue.

This file is the entire surface a voice model can reach. There is no generic
HTTP tool, no URL tool, no SQL tool, no "call endpoint" tool and no way to add
one from a conversation: a name that is not in ``CATALOGUE`` is rejected before
anything is looked up.

Three kinds of tool, and the difference decides where each one runs:

* ``read`` — the backend answers from rows the caller may already see.
* ``client`` — the app does something to itself (navigate, open a detail, open
  the real SOS or dialer confirmation). These never reach the backend; the
  browser dispatches them through an allowlist of its own.
* ``mutation`` — the backend changes something, always through the same service
  function the ordinary endpoint uses.

Whether a mutation is confirmed first is a property of the tool, not of the
model's mood. Anything that opens an emergency flow or a dialer always is —
those are irreversible enough, or public enough, that a person asking out loud
is not by itself enough of a gate. Everything else is confirmed only when
*Gamira* is the one proposing it: a person telling her directly that they took
a dose, set a reminder, or want their family told something *is* the
confirmation, and putting a second dialog in front of what they just said is a
hurdle, not a safeguard — worst for the person least able to clear it. See
``needs_confirmation`` at the bottom of this file, which is where that rule
lives, in code, rather than in a prompt.

Every schema sets ``additionalProperties: false``. A model that invents an
argument gets ``invalid_arguments``, not a silently ignored field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.models.enums import MembershipRole

ToolKind = Literal["read", "client", "mutation"]

# The screens a voice command may open. An allowlist, because "navigate to
# whatever the model says" is a redirect vulnerability with extra steps.
NAVIGABLE_SCREENS: tuple[str, ...] = (
    "home",
    "health",
    "reminders",
    "family",
    "settings",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: ToolKind
    description: str
    parameters: dict[str, Any]
    # Whether a person must confirm before this runs, always and regardless of
    # how it came up: anything clinical, and anything that opens a dialer or an
    # emergency flow.
    requires_confirmation: bool = False
    # Confirm only when Gamira proposed it herself. For an everyday, reversible
    # action, a person asking for it out loud *is* the confirmation — putting a
    # dialog in front of what they just requested is a second hurdle, and worst
    # for the person least able to clear it. A suggestion is different: nobody
    # asked, so it gets confirmed like anything else.
    confirm_when_unasked: bool = False
    # The minimum family role. ``None`` means any active member, which is what
    # read tools use — the senior themselves holds a viewer role.
    min_role: MembershipRole | None = None
    # Whether the cared-for person may use this on their own record even
    # without a write role. Confirming your own dose is the whole product.
    self_allowed: bool = True

    def declaration(self) -> dict[str, Any]:
        """The shape a Live session declares to the model."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _object(
    properties: dict[str, Any] | None = None, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        # Strict, everywhere. This is the line that makes an unexpected
        # argument an error rather than a shrug.
        "additionalProperties": False,
    }


_UUID = {
    "type": "string",
    "format": "uuid",
    "description": "An id returned by an earlier tool result.",
}

# Who wanted this. Required on the tools that skip their dialog when the person
# asked for it themselves, so the model has to state which case it is rather
# than have it inferred from the shape of the conversation.
_PROPOSED_BY = {
    "type": "string",
    "enum": ["them", "gamira"],
    "description": (
        "'them' when this person asked for this in their own words just now. "
        "'gamira' when you are the one suggesting it and they have not agreed "
        "yet. Answer honestly: 'them' means it happens straight away."
    ),
}


CATALOGUE: dict[str, ToolSpec] = {
    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #
    "get_today_doses": ToolSpec(
        name="get_today_doses",
        kind="read",
        description=(
            "The medicines scheduled for this person today, with the time of "
            "each and whether it has been taken, skipped or missed."
        ),
        parameters=_object(),
    ),
    "get_today_schedule": ToolSpec(
        name="get_today_schedule",
        kind="read",
        description=(
            "Everything on this person's day in time order: medicine doses and "
            "other reminders together."
        ),
        parameters=_object(),
    ),
    "get_reminders": ToolSpec(
        name="get_reminders",
        kind="read",
        description="This person's active non-medication reminders.",
        parameters=_object(),
    ),
    "get_latest_health_readings": ToolSpec(
        name="get_latest_health_readings",
        kind="read",
        description=(
            "The most recent recorded value for each health metric, with when "
            "it was measured and what recorded it. Values only — Gamira does "
            "not say whether a reading is good or bad."
        ),
        parameters=_object(
            {
                "metric": {
                    "type": "string",
                    "description": "Restrict to one metric, or omit for all.",
                    "enum": [
                        "heart_rate",
                        "blood_pressure_systolic",
                        "blood_pressure_diastolic",
                        "oxygen_saturation",
                        "blood_glucose",
                        "body_temperature",
                        "weight",
                        "steps",
                        "sleep_duration",
                    ],
                }
            }
        ),
    ),
    "get_upcoming_appointments": ToolSpec(
        name="get_upcoming_appointments",
        kind="read",
        description="This person's next scheduled appointments.",
        parameters=_object(),
    ),
    "get_emergency_contacts": ToolSpec(
        name="get_emergency_contacts",
        kind="read",
        description=(
            "The people this person has saved as emergency contacts, in the "
            "order they should be tried."
        ),
        parameters=_object(),
    ),
    "get_notification_summary": ToolSpec(
        name="get_notification_summary",
        kind="read",
        description="How many unread Gamira notifications there are, and their kinds.",
        parameters=_object(),
    ),
    # ------------------------------------------------------------------ #
    # Client UI
    # ------------------------------------------------------------------ #
    "navigate_to_screen": ToolSpec(
        name="navigate_to_screen",
        kind="client",
        description="Open one of Gamira's own screens.",
        parameters=_object(
            {
                "screen": {
                    "type": "string",
                    "enum": list(NAVIGABLE_SCREENS),
                    "description": "Which Gamira screen to open.",
                }
            },
            required=["screen"],
        ),
    ),
    "open_dose_details": ToolSpec(
        name="open_dose_details",
        kind="client",
        description="Show the details of one scheduled dose on screen.",
        parameters=_object({"dose_event_id": _UUID}, required=["dose_event_id"]),
    ),
    "open_reminder_details": ToolSpec(
        name="open_reminder_details",
        kind="client",
        description="Show the details of one reminder on screen.",
        parameters=_object({"reminder_id": _UUID}, required=["reminder_id"]),
    ),
    "get_current_time": ToolSpec(
        name="get_current_time",
        kind="client",
        description=(
            "The current time and date where this person is. Use this whenever "
            "the answer depends on 'now' — what time it is, what day it is, or "
            "how long until something on their schedule."
        ),
        parameters=_object(),
    ),
    "get_weather": ToolSpec(
        name="get_weather",
        kind="client",
        description=(
            "The weather outside right now, from this device's own location. "
            "Report only what it returns. Never turn it into advice about "
            "whether to go out, and never connect it to how somebody feels."
        ),
        parameters=_object(),
    ),
    "end_conversation": ToolSpec(
        name="end_conversation",
        kind="client",
        description=(
            "Close the voice session and stop listening. Use this as soon as "
            "the person signals they are finished — 'bye', 'goodbye', 'thank "
            "you, that is all', 'stop', 'go to sleep'. Say a short goodbye "
            "first, then call this. Do not call it while anything is still "
            "waiting on them."
        ),
        parameters=_object(),
    ),
    "prepare_sos": ToolSpec(
        name="prepare_sos",
        kind="client",
        description=(
            "Open the SOS screen when this person needs help. It starts a short "
            "countdown they can cancel, then raises an in-app alert their "
            "family sees. It does NOT call emergency services and does not "
            "contact anybody outside the app — you must never say that help is "
            "on the way, or that anybody has been called."
        ),
        parameters=_object(),
        requires_confirmation=True,
    ),
    "cancel_sos_countdown": ToolSpec(
        name="cancel_sos_countdown",
        kind="client",
        description=(
            "Stop the SOS countdown that is running on their screen, because "
            "they have said they are alright. Use this the moment they say "
            "cancel, stop, no, or that they are fine. Nothing has been sent to "
            "anybody yet, so nothing is being undone and nobody needs to "
            "confirm it. If the countdown has already finished, this will tell "
            "you so — then use cancel_my_sos instead."
        ),
        parameters=_object(),
    ),
    "prepare_call_contact": ToolSpec(
        name="prepare_call_contact",
        kind="client",
        description=(
            "Open the phone dialer for one saved emergency contact. This does "
            "not place the call; the person still presses dial."
        ),
        parameters=_object({"contact_id": _UUID}, required=["contact_id"]),
        requires_confirmation=True,
    ),
    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #
    "mark_dose_taken": ToolSpec(
        name="mark_dose_taken",
        kind="mutation",
        description=(
            "Record that one scheduled dose was taken. If they told you they "
            "have taken it, mark it and say so — that is the whole product. If "
            "you are the one asking whether they have, they are asked to "
            "confirm first. Never use this to change what a medicine is or how "
            "much of it to take."
        ),
        parameters=_object(
            {"proposed_by": _PROPOSED_BY, "dose_event_id": _UUID},
            required=["proposed_by", "dose_event_id"],
        ),
        confirm_when_unasked=True,
    ),
    "mark_dose_skipped": ToolSpec(
        name="mark_dose_skipped",
        kind="mutation",
        description=(
            "Record that one scheduled dose was skipped. If they told you they "
            "are skipping it, mark it and say so. If you are the one asking "
            "whether they have, they are asked to confirm first."
        ),
        parameters=_object(
            {"proposed_by": _PROPOSED_BY, "dose_event_id": _UUID},
            required=["proposed_by", "dose_event_id"],
        ),
        confirm_when_unasked=True,
    ),
    "create_reminder": ToolSpec(
        name="create_reminder",
        kind="mutation",
        description=(
            "Add a reminder for this person — either a daily routine like "
            "drinking water, a walk or watering the plants, or a one-off like "
            "'remind me in ten minutes' or 'tell me at four'. If they asked for "
            "it, it is added straight away and you simply tell them you have. "
            "If you are suggesting it, they are asked to confirm first. "
            "This is NOT for medicines: you cannot add, change or schedule a "
            "medication or a dose, and asking for one this way does not make it "
            "allowed. If they want a medicine added, say that a family member "
            "has to do it in the Gamira dashboard."
        ),
        parameters=_object(
            {
                "proposed_by": _PROPOSED_BY,
                "title": {
                    "type": "string",
                    "maxLength": 120,
                    "description": "What the reminder is for, in their own words.",
                },
                "repeat": {
                    "type": "string",
                    "enum": ["daily", "once"],
                    "description": (
                        "'once' for a single reminder today — 'in ten minutes', "
                        "'at four this afternoon'. 'daily' for something they "
                        "want every day at the same time. Ask if it is not "
                        "clear; do not assume they want it every day forever."
                    ),
                },
                "in_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 720,
                    "description": (
                        "How many minutes from now, when they say it that way — "
                        "'in five minutes', 'in an hour'. Do not work out the "
                        "clock time yourself; give the number of minutes and it "
                        "is worked out for you, in their timezone. Always 'once'."
                    ),
                },
                "local_time": {
                    "type": "string",
                    "pattern": r"^([01][0-9]|2[0-3]):[0-5][0-9]$",
                    "description": (
                        "Time of day as 24-hour HH:MM in their timezone, when "
                        "they name a time. Give this or in_minutes, never both."
                    ),
                },
                "instructions": {
                    "type": "string",
                    "maxLength": 300,
                    "description": "Anything else they said about it. Optional.",
                },
            },
            required=["proposed_by", "title", "repeat"],
        ),
        confirm_when_unasked=True,
    ),
    "complete_reminder": ToolSpec(
        name="complete_reminder",
        kind="mutation",
        description=(
            "Mark one everyday reminder as done. If they told you they have "
            "done it, mark it and say so. If you are the one asking whether "
            "they have, they are asked to confirm first."
        ),
        parameters=_object(
            {"proposed_by": _PROPOSED_BY, "reminder_id": _UUID},
            required=["proposed_by", "reminder_id"],
        ),
        confirm_when_unasked=True,
        # Completing somebody else's reminder is a care action; doing your own
        # is not. The policy engine applies this the same way it does for doses.
        min_role=None,
    ),
    "tell_family": ToolSpec(
        name="tell_family",
        kind="mutation",
        description=(
            "Pass a message to this person's family, in their Gamira app, "
            "because this person wants them to know something. Use it whenever "
            "they say they are unwell, in pain, worried, lonely or not "
            "themselves, and whenever they ask you to tell their family "
            "anything at all. Say what they told you, in their own terms and "
            "in one or two plain sentences — what they said, not what you "
            "concluded, and never a cause, a diagnosis or a suggestion of what "
            "anybody should do about it. "
            "This is not an emergency and does not read as one: their family "
            "sees a quiet note and can ring them. If they are asking for help "
            "right now, that is prepare_sos, not this. "
            "Tell them you are doing it, in your own words, and never send a "
            "message you have not said out loud to them first."
        ),
        parameters=_object(
            {
                "proposed_by": _PROPOSED_BY,
                "message": {
                    "type": "string",
                    "maxLength": 300,
                    "description": (
                        "What to tell their family, written about this person "
                        "in the third person: \"Vikram said he has had a "
                        "headache since this morning.\" Their own words where "
                        "you have them."
                    ),
                },
            },
            required=["proposed_by", "message"],
        ),
        # Nobody asked for a note the person did not want sent, so a suggestion
        # is confirmed like any other. Them asking is the confirmation: being
        # made to clear a dialog to tell your own family you feel unwell is
        # exactly the hurdle this exists to remove.
        confirm_when_unasked=True,
    ),
    "remember_this": ToolSpec(
        name="remember_this",
        kind="mutation",
        description=(
            "Keep one small, ordinary thing about this person so you still know "
            "it next time you speak — who visits them, what they like being "
            "called, that they walk before breakfast, that their grandson's "
            "exams are in June. Tell them you will remember it, then call this. "
            "One thing per call, in a short sentence of your own. "
            "Never use this for anything medical: no symptoms, no readings, no "
            "medicines, no diagnoses, and nothing about how they seem to be "
            "feeling. Never store a phone number, an address, a password or an "
            "id. They can see everything you keep and can delete any of it, so "
            "only keep what you would be glad to have them read."
        ),
        parameters=_object(
            {
                "kind": {
                    "type": "string",
                    "enum": ["person", "preference", "routine", "interest", "event"],
                    "description": "Which sort of thing this is.",
                },
                "content": {
                    "type": "string",
                    "maxLength": 300,
                    "description": (
                        "The thing itself, in one short sentence about them."
                    ),
                },
            },
            required=["kind", "content"],
        ),
    ),
    # ------------------------------------------------------------------ #
    # Answering a confirmation
    # ------------------------------------------------------------------ #
    #
    # These exist so a spoken "yes" is worth as much as a tap. Neither one
    # decides anything: the action, its arguments and its wording were all
    # settled when the confirmation was raised, and these two only carry the
    # answer back to the decision already sitting in the database.
    "cancel_my_sos": ToolSpec(
        name="cancel_my_sos",
        kind="mutation",
        description=(
            "Withdraw an emergency alert that has already gone to this "
            "person's family, because they have told you they are alright. "
            "Only ever their own, only when they have said so themselves, and "
            "never because it seems likely. Their family is told it was "
            "cancelled, and the alert stays in their record — you are not "
            "making it disappear. You still cannot acknowledge or close an "
            "alert in any other way."
        ),
        parameters=_object(),
        requires_confirmation=True,
    ),
    "answer_wellbeing_check": ToolSpec(
        name="answer_wellbeing_check",
        kind="mutation",
        description=(
            "Report what this person said when you asked how they were after "
            "their watch flagged a reading. Say what they actually said: "
            "'alright' if they told you they are fine, 'not_alright' if they "
            "told you they are not. If they did not answer, or you are not "
            "sure, do not call this at all — silence is handled without you "
            "and guessing at it would be worse than leaving it."
        ),
        parameters=_object(
            {
                "they_are": {
                    "type": "string",
                    "enum": ["alright", "not_alright"],
                    "description": (
                        "What they told you. Not what you concluded from how "
                        "they sounded, and not what the reading suggests."
                    ),
                }
            },
            required=["they_are"],
        ),
    ),
    "confirm_pending_action": ToolSpec(
        name="confirm_pending_action",
        kind="mutation",
        description=(
            "They said yes to the confirmation you just read out. Call this "
            "with the decision_id that confirmation gave you, and say what it "
            "returns — it is the only way to know the action really happened. "
            "Only ever use an id from this conversation, and only after a clear "
            "yes. If you are not sure what they meant, ask again instead."
        ),
        parameters=_object({"decision_id": _UUID}, required=["decision_id"]),
    ),
    "cancel_pending_action": ToolSpec(
        name="cancel_pending_action",
        kind="mutation",
        description=(
            "They said no to the confirmation you just read out, or changed "
            "their mind. Call this with its decision_id. Nothing is changed, "
            "and that is a perfectly good outcome — do not talk them into it."
        ),
        parameters=_object({"decision_id": _UUID}, required=["decision_id"]),
    ),
}

# The two tools above act on an existing decision rather than proposing one, so
# the executor routes them before it writes a decision of its own.
TOOL_CONFIRM_PENDING = "confirm_pending_action"
TOOL_CANCEL_PENDING = "cancel_pending_action"


def needs_confirmation(spec: ToolSpec, arguments: dict[str, Any]) -> bool:
    """Does this particular call have to be confirmed before it runs?

    Deterministic, and the only place the question is answered. ``arguments``
    have already passed the strict schema, so ``proposed_by`` is either one of
    the two allowed strings or absent.

    A model that mislabels a suggestion as something they asked for gets one
    everyday reminder that nobody wanted — visible in both apps, deletable, and
    not clinical. Nothing with a medical record behind it is decided here:
    those specs set ``requires_confirmation`` and never reach the second line.
    """
    if spec.requires_confirmation:
        return True
    return spec.confirm_when_unasked and arguments.get("proposed_by") != "them"


# What the senior-facing Parent App gets. Deliberately the whole catalogue
# *minus* nothing yet — but expressed as an explicit list so narrowing it later
# is a one-line change rather than an audit.
PARENT_APP_TOOLS: tuple[str, ...] = tuple(CATALOGUE)

# Tools a family member's dashboard session would get. Kept separate so the two
# surfaces can diverge without either inheriting the other's reach by accident.
FAMILY_APP_TOOLS: tuple[str, ...] = tuple(
    name for name, spec in CATALOGUE.items() if spec.kind != "client"
)


def get_tool(name: str) -> ToolSpec | None:
    return CATALOGUE.get(name)


def tool_snapshot(names: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    """The declarations pinned into one Live session.

    Stored on the session row, so a tool added to the server tomorrow is not
    callable by a session opened today, and one removed for safety stops
    working immediately for sessions already running.
    """
    return [CATALOGUE[name].declaration() for name in names if name in CATALOGUE]


def snapshot_names(snapshot: list[dict[str, Any]] | None) -> set[str]:
    return {
        str(entry.get("name"))
        for entry in (snapshot or [])
        if isinstance(entry, dict) and entry.get("name")
    }


__all__ = [
    "CATALOGUE",
    "FAMILY_APP_TOOLS",
    "NAVIGABLE_SCREENS",
    "PARENT_APP_TOOLS",
    "TOOL_CANCEL_PENDING",
    "TOOL_CONFIRM_PENDING",
    "ToolKind",
    "ToolSpec",
    "get_tool",
    "needs_confirmation",
    "snapshot_names",
    "tool_snapshot",
]
