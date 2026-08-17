"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata``, which is what
Alembic autogenerate and the test bootstrap rely on.
"""

from app.models.ai import (
    AiDecision,
    AiSummary,
    AiUsage,
    Conversation,
    ConversationMessage,
    LiveSession,
)
from app.models.alerts import Alert, AlertEvent
from app.models.audit import AuditLog
from app.models.care import (
    Appointment,
    EmergencyContact,
    FamilyNote,
    HealthReading,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    Reminder,
    TimelineEvent,
)
from app.models.devices import RegisteredDevice
from app.models.identity import (
    Family,
    FamilyInvitation,
    FamilyMembership,
    SeniorProfile,
    User,
)
from app.models.jobs import BackgroundJob
from app.models.medication import DoseEvent, Medication, MedicationSchedule

__all__ = [
    "AiDecision",
    "AiSummary",
    "AiUsage",
    "Alert",
    "AlertEvent",
    "Appointment",
    "AuditLog",
    "BackgroundJob",
    "Conversation",
    "ConversationMessage",
    "DoseEvent",
    "EmergencyContact",
    "Family",
    "FamilyInvitation",
    "FamilyMembership",
    "FamilyNote",
    "HealthReading",
    "LiveSession",
    "Medication",
    "MedicationSchedule",
    "NotificationDelivery",
    "NotificationDeliveryAttempt",
    "RegisteredDevice",
    "Reminder",
    "SeniorProfile",
    "TimelineEvent",
    "User",
]
