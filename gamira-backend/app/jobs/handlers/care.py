"""The deterministic care handlers.

Nothing in this module may depend on an AI provider, a push provider or any
network call. If Gemini is unreachable and FCM is refusing connections, doses
are still materialised, still moved to late and missed, and the family still
sees every one of those events in the app. That is the property the whole
design is for, and ``test_ai_outage.py`` asserts it.

Each handler is a *sweep*: it looks at the current state of the world and makes
it right, rather than replaying a stream of instructions. Running one twice
changes nothing the second time, because every row it writes carries a dedupe
key derived from the thing it describes.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.base import utcnow
from app.jobs.queue import JobResult, PermanentJobError
from app.jobs.registry import JobContext, handler
from app.jobs.types import JobType
from app.models.alerts import Alert
from app.models.care import Appointment, Reminder
from app.models.enums import (
    TERMINAL_DOSE_STATUSES,
    AppointmentStatus,
    DoseStatus,
    MembershipStatus,
    NotificationStatus,
    NotificationType,
    ReminderStatus,
    TimelineEventType,
)
from app.models.identity import FamilyMembership, SeniorProfile
from app.models.medication import DoseEvent
from app.services import alerts as alert_service
from app.services import doses as dose_service
from app.services.notifications import (
    NotificationRequest,
    create_notification,
    deliver_push,
    notify_family,
    pending_push_notifications,
)
from app.services.scheduling import load_timezone, parse_days_of_week, parse_local_time
from app.services.timeline import record_timeline_event

logger = get_logger(__name__)

# How far either side of "now" a reminder sweep looks. Wide enough that a
# worker that missed a couple of ticks still catches the occurrence, narrow
# enough that a worker started after a week's downtime does not send a week of
# reminders at once.
REMINDER_LOOKBACK = dt.timedelta(minutes=10)
REMINDER_LOOKAHEAD = dt.timedelta(minutes=2)


# --------------------------------------------------------------------------- #
# Doses
# --------------------------------------------------------------------------- #


@handler(JobType.DOSE_MATERIALIZE)
async def materialize_doses(ctx: JobContext) -> JobResult:
    """Create dose events for a rolling window ahead of now.

    This is what lets ``GET /doses`` be a read. The window starts slightly in
    the past so a medication added this morning still produces this morning's
    dose, and runs days ahead so a worker outage does not cost anybody a
    reminder.
    """
    now = utcnow()
    window_start = now - dt.timedelta(
        hours=ctx.settings.dose_materialization_backfill_hours
    )
    window_end = now + dt.timedelta(days=ctx.settings.dose_materialization_days)

    seniors = await _target_seniors(ctx)
    created = 0
    for senior in seniors:
        events = await dose_service.generate_dose_events(
            ctx.session,
            senior=senior,
            window_start=window_start,
            window_end=window_end,
        )
        created += len(events)
    return JobResult(metrics={"seniors": len(seniors), "dose_events_created": created})


@handler(JobType.DOSE_ADVANCE_STATUS)
async def advance_dose_statuses(ctx: JobContext) -> JobResult:
    """Move unacknowledged doses to late, then missed.

    The missed transition is the one with consequences: it writes exactly one
    timeline event and notifies the family exactly once, both keyed on the dose
    event id, so a retried job cannot tell a family twice that their mother
    missed her tablet.
    """
    now = utcnow()
    # Only look back far enough to catch a worker outage; older doses were
    # already resolved by an earlier sweep.
    horizon = now - dt.timedelta(days=7)

    rows = await ctx.session.execute(
        select(DoseEvent)
        .where(
            DoseEvent.scheduled_at_utc >= horizon,
            DoseEvent.scheduled_at_utc <= now,
            DoseEvent.status.notin_(list(TERMINAL_DOSE_STATUSES)),
        )
        .order_by(DoseEvent.scheduled_at_utc)
        .limit(500)
    )
    events = list(rows.scalars().unique())

    became_late = 0
    became_missed = 0
    for event in events:
        previous = event.status
        if not dose_service.apply_time_derived_status(event, now=now):
            continue
        if event.status is DoseStatus.LATE:
            became_late += 1
        elif event.status is DoseStatus.MISSED and previous is not DoseStatus.MISSED:
            became_missed += 1
            await _record_missed_dose(ctx, event, now=now)

    await ctx.session.flush()
    return JobResult(
        metrics={
            "examined": len(events),
            "became_late": became_late,
            "became_missed": became_missed,
        }
    )


async def _record_missed_dose(
    ctx: JobContext, event: DoseEvent, *, now: dt.datetime
) -> None:
    senior = await ctx.session.get(SeniorProfile, event.senior_profile_id)
    if senior is None:  # pragma: no cover - cascade would have removed the dose
        return
    medication_name = event.medication.name if event.medication else "A medicine"

    await record_timeline_event(
        ctx.session,
        family_id=event.family_id,
        senior_profile_id=event.senior_profile_id,
        type=TimelineEventType.MEDICATION_MISSED,
        title=f"{medication_name} missed",
        description=(
            f"Scheduled for {event.scheduled_local_time} and not recorded as "
            "taken or skipped."
        ),
        related_entity_type="dose_event",
        related_entity_id=event.id,
        occurred_at=now,
        # The exactly-once key. One dose event, one missed entry, forever.
        dedupe_key=f"missed-dose:{event.id}",
    )

    await notify_family(
        ctx.session,
        family_id=event.family_id,
        dedupe_prefix=f"missed-dose:{event.id}",
        template=NotificationRequest(
            user_id=uuid.uuid4(),
            type=NotificationType.MISSED_DOSE,
            title=f"{senior.preferred_name} missed {medication_name}",
            body=(
                f"Scheduled for {event.scheduled_local_time}. Nobody recorded it "
                "as taken or skipped."
            ),
            senior_profile_id=senior.id,
            related_entity_type="dose_event",
            related_entity_id=event.id,
        ),
    )


@handler(JobType.MEDICATION_REMINDERS)
async def queue_medication_reminders(ctx: JobContext) -> JobResult:
    """Remind the person whose medicine it is, once per dose.

    The reminder goes to the senior's own account. Their family is told when a
    dose is *missed*, not when one is due — a phone buzzing at every relative
    four times a day is how a family stops looking at notifications.
    """
    now = utcnow()
    lead = dt.timedelta(minutes=ctx.settings.medication_reminder_lead_minutes)
    window_start = now - REMINDER_LOOKBACK
    window_end = now + lead + REMINDER_LOOKAHEAD

    rows = await ctx.session.execute(
        select(DoseEvent)
        .where(
            DoseEvent.scheduled_at_utc >= window_start,
            DoseEvent.scheduled_at_utc <= window_end,
            DoseEvent.status == DoseStatus.DUE,
        )
        .order_by(DoseEvent.scheduled_at_utc)
        .limit(500)
    )

    reminded = 0
    for event in rows.scalars().unique():
        senior = await ctx.session.get(SeniorProfile, event.senior_profile_id)
        if senior is None:  # pragma: no cover
            continue
        medication_name = event.medication.name if event.medication else "your medicine"
        quantity = event.schedule.dose_quantity if event.schedule else None

        recipients = await _reminder_recipients(ctx.session, senior)
        for user_id in recipients:
            await create_notification(
                ctx.session,
                NotificationRequest(
                    user_id=user_id,
                    type=NotificationType.MEDICATION_REMINDER,
                    title=f"Time for {medication_name}",
                    body=(
                        f"{quantity}, scheduled for {event.scheduled_local_time}."
                        if quantity
                        else f"Scheduled for {event.scheduled_local_time}."
                    ),
                    family_id=event.family_id,
                    senior_profile_id=senior.id,
                    related_entity_type="dose_event",
                    related_entity_id=event.id,
                    # One reminder per dose per person, whatever happens to
                    # this job.
                    dedupe_key=f"dose-reminder:{event.id}:{user_id}",
                ),
                settings=ctx.settings,
            )
        # `reminded` is a state, not a notification count: it says this dose has
        # been announced, so the next sweep leaves it alone.
        event.status = DoseStatus.REMINDED
        reminded += 1

    await ctx.session.flush()
    return JobResult(metrics={"doses_reminded": reminded})


async def _reminder_recipients(
    session: AsyncSession, senior: SeniorProfile
) -> list[uuid.UUID]:
    """Who hears about a due dose: the person themselves, if they have an account."""
    if senior.user_id is not None:
        return [senior.user_id]
    # Nobody is signed in as this person — an assisted setup. The family
    # members who administer their care get it instead.
    rows = await session.execute(
        select(FamilyMembership.user_id).where(
            FamilyMembership.family_id == senior.family_id,
            FamilyMembership.status == MembershipStatus.ACTIVE,
        )
    )
    return list(rows.scalars())


# --------------------------------------------------------------------------- #
# General reminders
# --------------------------------------------------------------------------- #


@handler(JobType.REMINDER_OCCURRENCES)
async def process_reminder_occurrences(ctx: JobContext) -> JobResult:
    """Fire non-medication recurring reminders as their local time comes round.

    A reminder has no per-occurrence row, so the occurrence's own local
    date-time is the dedupe key: hydration at 11:00 on 2026-08-17 can only
    notify once, no matter how often this sweep runs.
    """
    now = utcnow()
    rows = await ctx.session.execute(
        select(Reminder).where(
            Reminder.status == ReminderStatus.ACTIVE,
            Reminder.local_time.is_not(None),
        )
    )
    fired = 0
    for reminder in rows.scalars():
        occurrence = _current_occurrence(reminder, now)
        if occurrence is None:
            continue
        senior = await ctx.session.get(SeniorProfile, reminder.senior_profile_id)
        if senior is None:  # pragma: no cover
            continue
        recipients = await _reminder_recipients(ctx.session, senior)
        for user_id in recipients:
            await create_notification(
                ctx.session,
                NotificationRequest(
                    user_id=user_id,
                    type=NotificationType.REMINDER,
                    title=reminder.title,
                    body=reminder.instructions,
                    family_id=reminder.family_id,
                    senior_profile_id=reminder.senior_profile_id,
                    related_entity_type="reminder",
                    related_entity_id=reminder.id,
                    dedupe_key=f"reminder:{reminder.id}:{occurrence}:{user_id}",
                ),
                settings=ctx.settings,
            )
        fired += 1
    await ctx.session.flush()
    return JobResult(metrics={"reminders_fired": fired})


def _current_occurrence(reminder: Reminder, now: dt.datetime) -> str | None:
    """The local-date key for this reminder's occurrence, if it is due now.

    Returns ``None`` when today is not one of its days, when it is outside its
    effective dates, or when its time has not arrived (or is long past).
    """
    if not reminder.local_time:
        return None
    try:
        tz = load_timezone(reminder.timezone)
        at = parse_local_time(reminder.local_time)
        days = parse_days_of_week(reminder.days_of_week)
    except Exception:
        # A malformed stored reminder must not stop every other reminder from
        # firing; it is logged and skipped.
        logger.warning(
            "reminder_schedule_unreadable", extra={"reminder_id": str(reminder.id)}
        )
        return None

    local_now = now.astimezone(tz)
    today = local_now.date()
    if today.isoweekday() not in days:
        return None
    if reminder.effective_from and today < reminder.effective_from:
        return None
    if reminder.effective_to and today > reminder.effective_to:
        return None

    due_local = dt.datetime.combine(today, at, tzinfo=tz)
    due_utc = due_local.astimezone(dt.UTC)
    if not (now - REMINDER_LOOKBACK <= due_utc <= now + REMINDER_LOOKAHEAD):
        return None
    return f"{today.isoformat()}T{reminder.local_time}"


# --------------------------------------------------------------------------- #
# Appointments
# --------------------------------------------------------------------------- #


@handler(JobType.APPOINTMENT_REMINDERS)
async def queue_appointment_reminders(ctx: JobContext) -> JobResult:
    """Tell the family about an appointment a day out, once."""
    now = utcnow()
    lead = dt.timedelta(hours=ctx.settings.appointment_reminder_lead_hours)
    rows = await ctx.session.execute(
        select(Appointment)
        .where(
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.starts_at > now,
            Appointment.starts_at <= now + lead,
        )
        .limit(200)
    )
    queued = 0
    for appointment in rows.scalars():
        senior = await ctx.session.get(SeniorProfile, appointment.senior_profile_id)
        if senior is None:  # pragma: no cover
            continue
        local = appointment.starts_at.astimezone(load_timezone(appointment.timezone))
        await notify_family(
            ctx.session,
            family_id=appointment.family_id,
            dedupe_prefix=f"appointment:{appointment.id}",
            template=NotificationRequest(
                user_id=uuid.uuid4(),
                type=NotificationType.APPOINTMENT,
                title=f"{senior.preferred_name}: {appointment.title}",
                body=(
                    f"{local.strftime('%A %d %B, %H:%M')}"
                    + (f" with {appointment.clinician}" if appointment.clinician else "")
                    + (f" at {appointment.location}" if appointment.location else "")
                ),
                senior_profile_id=senior.id,
                related_entity_type="appointment",
                related_entity_id=appointment.id,
            ),
        )
        queued += 1
    return JobResult(metrics={"appointments_reminded": queued})


# --------------------------------------------------------------------------- #
# Push delivery
# --------------------------------------------------------------------------- #


@handler(JobType.NOTIFICATION_DELIVER)
async def deliver_notification(ctx: JobContext) -> JobResult:
    """Deliver one push notification, named in the payload."""
    from app.models.care import NotificationDelivery

    raw_id = ctx.payload.get("notification_id")
    if not raw_id:
        raise PermanentJobError("missing_notification_id")
    try:
        notification_id = uuid.UUID(str(raw_id))
    except ValueError:
        raise PermanentJobError("invalid_notification_id") from None

    notification = await ctx.session.get(NotificationDelivery, notification_id)
    if notification is None:
        raise PermanentJobError("notification_not_found")
    if notification.status in (
        NotificationStatus.SENT,
        NotificationStatus.OPENED,
        NotificationStatus.CANCELLED,
    ):
        return JobResult(metrics={"skipped": notification.status.value})

    status = await deliver_push(ctx.session, notification, settings=ctx.settings)
    return JobResult(
        reference={"type": "notification_delivery", "id": str(notification.id)},
        metrics={"outcome": status.value},
    )


@handler(JobType.NOTIFICATION_RETRY_SWEEP)
async def retry_pending_deliveries(ctx: JobContext) -> JobResult:
    """Retry every push whose backoff has elapsed.

    A sweep rather than one job per notification: a provider outage that failed
    two hundred sends should not leave two hundred jobs behind, each waking the
    worker separately.
    """
    now = utcnow()
    pending = await pending_push_notifications(ctx.session, limit=100, now=now)
    outcomes: dict[str, int] = {}
    for notification in pending:
        status = await deliver_push(
            ctx.session, notification, settings=ctx.settings, now=now
        )
        outcomes[status.value] = outcomes.get(status.value, 0) + 1
    return JobResult(metrics={"attempted": len(pending), **outcomes})


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #


@handler(JobType.ALERT_ESCALATION_CHECK)
async def check_alert_escalations(ctx: JobContext) -> JobResult:
    """Re-notify the family about any SOS nobody has acknowledged.

    An alert named in the payload is checked on its own; otherwise every alert
    whose escalation time has passed is swept. Both paths go through the same
    service function, so the rules cannot differ between them.
    """
    now = utcnow()
    raw_id = ctx.payload.get("alert_id")
    if raw_id:
        try:
            alert = await ctx.session.get(Alert, uuid.UUID(str(raw_id)))
        except ValueError:
            raise PermanentJobError("invalid_alert_id") from None
        candidates = [alert] if alert is not None else []
    else:
        candidates = await alert_service.alerts_due_for_escalation(ctx.session, now=now)

    escalated = 0
    for alert in candidates:
        if alert is None or alert.is_answered or alert.next_escalation_at is None:
            continue
        if alert.next_escalation_at > now:
            continue
        senior = await ctx.session.get(SeniorProfile, alert.senior_profile_id)
        if senior is None:  # pragma: no cover
            continue
        await alert_service.escalate(
            ctx.session, alert=alert, senior=senior, settings=ctx.settings, now=now
        )
        escalated += 1
    return JobResult(metrics={"alerts_escalated": escalated})


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #


async def _target_seniors(ctx: JobContext) -> list[SeniorProfile]:
    """The seniors this job covers: one named in the payload, or all of them."""
    raw_id = ctx.payload.get("senior_profile_id")
    if raw_id:
        try:
            senior_id = uuid.UUID(str(raw_id))
        except ValueError:
            raise PermanentJobError("invalid_senior_profile_id") from None
        senior = await ctx.session.get(SeniorProfile, senior_id)
        if senior is None:
            raise PermanentJobError("senior_not_found")
        return [senior]

    rows = await ctx.session.execute(
        select(SeniorProfile).where(SeniorProfile.archived_at.is_(None))
    )
    return list(rows.scalars())


__all__ = [
    "advance_dose_statuses",
    "check_alert_escalations",
    "deliver_notification",
    "materialize_doses",
    "process_reminder_occurrences",
    "queue_appointment_reminders",
    "queue_medication_reminders",
    "retry_pending_deliveries",
]
