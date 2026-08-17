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
  function the ordinary endpoint uses, and always behind a confirmation.

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
    # Whether a person must confirm before this runs. Every mutation does;
    # so does anything that opens a dialer or an emergency flow.
    requires_confirmation: bool = False
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
    "prepare_sos": ToolSpec(
        name="prepare_sos",
        kind="client",
        description=(
            "Open the real SOS confirmation screen so the person can press it "
            "themselves. This does NOT raise an alert. You must never claim "
            "that help has been called."
        ),
        parameters=_object(),
        requires_confirmation=True,
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
            "Record that one scheduled dose was taken. Requires the person to "
            "confirm first. Never use this to change what a medicine is or how "
            "much of it to take."
        ),
        parameters=_object({"dose_event_id": _UUID}, required=["dose_event_id"]),
        requires_confirmation=True,
    ),
    "mark_dose_skipped": ToolSpec(
        name="mark_dose_skipped",
        kind="mutation",
        description=(
            "Record that one scheduled dose was skipped. Requires the person "
            "to confirm first."
        ),
        parameters=_object({"dose_event_id": _UUID}, required=["dose_event_id"]),
        requires_confirmation=True,
    ),
    "complete_reminder": ToolSpec(
        name="complete_reminder",
        kind="mutation",
        description="Mark one reminder as done. Requires the person to confirm first.",
        parameters=_object({"reminder_id": _UUID}, required=["reminder_id"]),
        requires_confirmation=True,
        # Completing somebody else's reminder is a care action; doing your own
        # is not. The policy engine applies this the same way it does for doses.
        min_role=None,
    ),
}

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
    "ToolKind",
    "ToolSpec",
    "get_tool",
    "snapshot_names",
    "tool_snapshot",
]
