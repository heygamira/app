"""Job type names, in one place.

They are strings in the database, so renaming one strands every queued row
that still carries the old name. Treat these as a wire format.
"""

from __future__ import annotations

from typing import Final


class JobType:
    # Deterministic care. None of these may depend on an AI provider.
    DOSE_MATERIALIZE: Final = "doses.materialize"
    DOSE_ADVANCE_STATUS: Final = "doses.advance_status"
    MEDICATION_REMINDERS: Final = "medications.queue_reminders"
    REMINDER_OCCURRENCES: Final = "reminders.process_occurrences"
    APPOINTMENT_REMINDERS: Final = "appointments.queue_reminders"
    NOTIFICATION_DELIVER: Final = "notifications.deliver"
    NOTIFICATION_RETRY_SWEEP: Final = "notifications.retry_sweep"
    ALERT_ESCALATION_CHECK: Final = "alerts.escalation_check"

    # AI. Every one of these may fail without affecting the list above.
    AI_WEEKLY_SUMMARY: Final = "ai.weekly_summary"
    AI_CONVERSATION_REVIEW: Final = "ai.conversation_review"
    AI_FAMILY_NOTICE: Final = "ai.family_notice"
    LIVE_SESSION_EXPIRY: Final = "ai.live_sessions.expire"
    CONVERSATION_RETENTION: Final = "ai.conversations.retention"


__all__ = ["JobType"]
