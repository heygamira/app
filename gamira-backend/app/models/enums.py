"""Domain enumerations.

These are stored as constrained strings rather than PostgreSQL enum types: a new
value then needs a CHECK-constraint migration instead of an ALTER TYPE that
cannot run inside a transaction.
"""

from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class FamilyStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MembershipRole(StrEnum):
    OWNER = "owner"
    FAMILY = "family"
    CAREGIVER = "caregiver"
    DOCTOR = "doctor"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ConsentStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    GRANTED = "granted"
    ASSISTED = "assisted"
    WITHDRAWN = "withdrawn"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class MedicationStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ScheduleStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class DoseStatus(StrEnum):
    DUE = "due"
    REMINDED = "reminded"
    TAKEN = "taken"
    SKIPPED = "skipped"
    LATE = "late"
    MISSED = "missed"
    CANCELLED = "cancelled"


TERMINAL_DOSE_STATUSES = frozenset(
    {DoseStatus.TAKEN, DoseStatus.SKIPPED, DoseStatus.CANCELLED}
)


class DoseSource(StrEnum):
    PARENT_APP = "parent_app"
    FAMILY_APP = "family_app"
    BACKEND_RULE = "backend_rule"
    IMPORT = "import"


class ReminderType(StrEnum):
    MEDICATION = "medication"
    APPOINTMENT = "appointment"
    ACTIVITY = "activity"
    HYDRATION = "hydration"
    MEAL = "meal"
    OTHER = "other"


class ReminderStatus(StrEnum):
    """Where one reminder stands.

    ``suggested`` is Gamira's, and it is deliberately not ``active``: a routine
    she picked up from a conversation prompts nobody and appears on no
    schedule until a person accepts it. Every query that looks for live
    reminders already filters on ``active``, so a suggestion is inert by
    construction rather than by anyone remembering to exclude it.
    """

    SUGGESTED = "suggested"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TimelineEventType(StrEnum):
    MEDICATION_TAKEN = "medication_taken"
    MEDICATION_SKIPPED = "medication_skipped"
    MEDICATION_MISSED = "medication_missed"
    MEDICATION_ADDED = "medication_added"
    REMINDER_ADDED = "reminder_added"
    REMINDER_COMPLETED = "reminder_completed"
    HEALTH_READING_ADDED = "health_reading_added"
    APPOINTMENT_SCHEDULED = "appointment_scheduled"
    SOS_TRIGGERED = "sos_triggered"
    WELLBEING_CHECK = "wellbeing_check"
    MEMBER_JOINED = "member_joined"
    NOTE_ADDED = "note_added"


class NotificationStatus(StrEnum):
    """Where one notification record has got to.

    ``sent`` means Gamira has done what this channel can do: for ``in_app`` the
    row is visible in the app, for ``push`` a provider accepted the message. It
    never means a person read it.
    """

    QUEUED = "queued"
    SENT = "sent"
    OPENED = "opened"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NotificationChannel(StrEnum):
    """How a notification is meant to reach someone.

    Kept explicit so nothing can call a database row a delivered push. An
    ``in_app`` record is only seen by a member whose app is open; a ``push``
    record has an actual provider attempt behind it.
    """

    IN_APP = "in_app"
    PUSH = "push"


class NotificationType(StrEnum):
    MEDICATION_REMINDER = "medication_reminder"
    MISSED_DOSE = "missed_dose"
    REMINDER = "reminder"
    APPOINTMENT = "appointment"
    SOS = "sos"
    SOS_ESCALATION = "sos_escalation"
    WELLBEING_CHECK = "wellbeing_check"
    FAMILY_UPDATE = "family_update"
    SYSTEM = "system"


class DeliveryAttemptStatus(StrEnum):
    """The outcome of one attempt to hand a notification to one device."""

    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    TOKEN_INVALID = "token_invalid"
    SKIPPED = "skipped"


class DevicePlatform(StrEnum):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    WATCH = "watch"


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


LIVE_JOB_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})


class AlertType(StrEnum):
    """What an alert is about.

    ``wellbeing_check`` is deliberately a separate type rather than a quieter
    SOS. A watch left on a bedside table will leave its band; if that wore the
    same treatment as somebody pressing the button, a family would learn to
    ignore both, and the one that matters is the one they would stop looking at.
    """

    SOS = "sos"
    WELLBEING_CHECK = "wellbeing_check"


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    INFO = "info"


class AlertStatus(StrEnum):
    """An alert's lifecycle.

    ``cancelled`` is reachable in exactly two ways: a person doing it in an app,
    and the person the alert is *about* withdrawing their own by voice. Nothing
    else — not a device, not a background rule, and not the assistant acting on
    anybody else's alert. Acknowledgement and resolution stay human-only.
    """

    RAISED = "raised"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


OPEN_ALERT_STATUSES = frozenset(
    {AlertStatus.RAISED, AlertStatus.ESCALATED, AlertStatus.ACKNOWLEDGED}
)


class WellbeingCheckStatus(StrEnum):
    """Whether anybody answered when a device flagged something.

    ``not_alright`` is what they said, not a finding: Gamira reports the answer
    and a rule decides what follows. ``unreachable`` and ``no_answer`` are kept
    apart because they are different facts — the app was never open, versus she
    asked and nothing came back — and a family reads them differently.
    """

    PENDING = "pending"
    ALRIGHT = "alright"
    NOT_ALRIGHT = "not_alright"
    NO_ANSWER = "no_answer"
    UNREACHABLE = "unreachable"


OPEN_WELLBEING_CHECK_STATUSES = frozenset({WellbeingCheckStatus.PENDING})


class AlertSource(StrEnum):
    PARENT_APP = "parent_app"
    WATCH = "watch"
    FAMILY_APP = "family_app"
    APPROVED_DEVICE = "approved_device"


class AlertEventType(StrEnum):
    RAISED = "raised"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    NOTE = "note"


class ActorType(StrEnum):
    """Who caused a recorded event.

    ``ai`` exists so an AI-originated action is always distinguishable in the
    audit trail. It is never accepted on an alert acknowledgement or
    resolution, and on a cancellation only through the one narrow path in
    ``services/alerts.py`` where the person is withdrawing their own alert out
    loud — where it is recorded precisely so the trail says the assistant
    carried it out.
    """

    USER = "user"
    SYSTEM = "system"
    DEVICE = "device"
    AI = "ai"


class HealthMetric(StrEnum):
    HEART_RATE = "heart_rate"
    BLOOD_PRESSURE_SYSTOLIC = "blood_pressure_systolic"
    BLOOD_PRESSURE_DIASTOLIC = "blood_pressure_diastolic"
    OXYGEN_SATURATION = "oxygen_saturation"
    BLOOD_GLUCOSE = "blood_glucose"
    BODY_TEMPERATURE = "body_temperature"
    WEIGHT = "weight"
    STEPS = "steps"
    SLEEP_DURATION = "sleep_duration"


class HealthSource(StrEnum):
    MANUAL_SENIOR = "manual_senior"
    MANUAL_FAMILY = "manual_family"
    DEVICE = "device"
    CLINICIAN = "clinician"
    IMPORT = "import"


class AppointmentStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NoteCategory(StrEnum):
    NOTE = "note"
    OBSERVATION = "observation"
    SUPPORT = "support"
    CARE_PLAN = "care_plan"


# --------------------------------------------------------------------------- #
# AI
# --------------------------------------------------------------------------- #


class ConversationChannel(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    EXPIRED = "expired"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class SummaryKind(StrEnum):
    CONVERSATION = "conversation"
    WEEKLY_CARE = "weekly_care"


class MemoryKind(StrEnum):
    """What sort of thing Gamira is holding on to.

    All of it is ordinary life, and all of it is shown to the person it is
    about. There is deliberately no clinical kind: a memory is never a health
    record, a symptom, a diagnosis or anything a doctor would act on, and the
    only tool that writes one says so in as many words.

    ``mood`` and ``concern`` are the two the after-call review may write and
    ``remember_this`` may not — an impression of how somebody sounded is not a
    thing to assert mid-conversation, and it is not a measurement either.
    """

    PERSON = "person"
    PREFERENCE = "preference"
    ROUTINE = "routine"
    INTEREST = "interest"
    EVENT = "event"
    MOOD = "mood"
    CONCERN = "concern"


class ReviewState(StrEnum):
    """Whether a person has checked a generated summary.

    Everything Gamira generates starts ``unreviewed``. Nothing in the product
    treats an unreviewed summary as a clinical record.
    """

    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class PolicyResult(StrEnum):
    ALLOWED = "allowed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DENIED = "denied"


class ConfirmationState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


class LiveSessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"
    REVOKED = "revoked"
