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
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TimelineEventType(StrEnum):
    MEDICATION_TAKEN = "medication_taken"
    MEDICATION_SKIPPED = "medication_skipped"
    MEDICATION_MISSED = "medication_missed"
    MEDICATION_ADDED = "medication_added"
    REMINDER_COMPLETED = "reminder_completed"
    HEALTH_READING_ADDED = "health_reading_added"
    APPOINTMENT_SCHEDULED = "appointment_scheduled"
    SOS_TRIGGERED = "sos_triggered"
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
    SOS = "sos"


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    INFO = "info"


class AlertStatus(StrEnum):
    """An SOS alert's lifecycle.

    ``cancelled`` is only reachable through an explicit human flow and is never
    available to the AI, a device or a background rule.
    """

    RAISED = "raised"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


OPEN_ALERT_STATUSES = frozenset(
    {AlertStatus.RAISED, AlertStatus.ESCALATED, AlertStatus.ACKNOWLEDGED}
)


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
    audit trail. It is never accepted on an alert acknowledgement, resolution
    or cancellation.
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
