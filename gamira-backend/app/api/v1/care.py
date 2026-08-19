"""Reminders, timeline, health readings, notifications, contacts and notes."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TypeVar

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import NotFound, ValidationFailed
from app.db.base import Base, utcnow
from app.jobs.queue import URGENT_PRIORITY, enqueue_job
from app.jobs.types import JobType
from app.models.care import (
    Appointment,
    EmergencyContact,
    FamilyNote,
    HealthReading,
    NotificationDelivery,
    Reminder,
    TimelineEvent,
    WellbeingCheck,
)
from app.models.enums import (
    HealthSource,
    NotificationChannel,
    NotificationStatus,
    ReminderStatus,
    TimelineEventType,
    WellbeingCheckStatus,
)
from app.models.identity import SeniorProfile
from app.schemas.care import (
    METRIC_UNITS,
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
    EmergencyContactCreate,
    EmergencyContactOut,
    EmergencyContactUpdate,
    FamilyNoteCreate,
    FamilyNoteOut,
    HealthReadingBulkCreate,
    HealthReadingCreate,
    HealthReadingOut,
    NotificationOut,
    ReminderCreate,
    ReminderOut,
    ReminderUpdate,
    TimelineEventOut,
    WellbeingCheckAnswer,
    WellbeingCheckOut,
)
from app.services import wellbeing as wellbeing_service
from app.services.authz import (
    require_membership,
    require_self_or_write_access,
    require_write_access,
    resolve_senior,
)
from app.services.timeline import record_audit, record_timeline_event

router = APIRouter(tags=["care"])

MAX_PAGE_SIZE = 200

ModelT = TypeVar("ModelT", bound=Base)


# --------------------------------------------------------------------------- #
# Reminders
# --------------------------------------------------------------------------- #


@router.get("/seniors/{senior_id}/reminders", response_model=list[ReminderOut])
async def list_reminders(
    senior_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[ReminderOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    rows = await session.execute(
        select(Reminder)
        .where(
            Reminder.senior_profile_id == senior_id,
            Reminder.status != ReminderStatus.ARCHIVED,
        )
        .order_by(Reminder.local_time.nulls_last(), Reminder.created_at)
    )
    return [ReminderOut.model_validate(row) for row in rows.scalars()]


@router.post(
    "/seniors/{senior_id}/reminders",
    response_model=ReminderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_reminder(
    senior_id: uuid.UUID,
    payload: ReminderCreate,
    session: SessionDep,
    user: CurrentUser,
) -> ReminderOut:
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=senior_id, write=True
    )
    data = payload.model_dump()
    data["timezone"] = data.get("timezone") or senior.timezone
    reminder = Reminder(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        created_by_user_id=user.id,
        **data,
    )
    session.add(reminder)
    await session.flush()
    return ReminderOut.model_validate(reminder)


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: uuid.UUID,
    payload: ReminderUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> ReminderOut:
    reminder = await _load(session, Reminder, reminder_id, "reminder")
    await require_write_access(session, user_id=user.id, family_id=reminder.family_id)

    changes = payload.model_dump(exclude_unset=True)
    completing = changes.get("status") is ReminderStatus.COMPLETED
    for field, value in changes.items():
        setattr(reminder, field, value)
    if completing:
        reminder.last_completed_at = utcnow()
        await record_timeline_event(
            session,
            family_id=reminder.family_id,
            senior_profile_id=reminder.senior_profile_id,
            type=TimelineEventType.REMINDER_COMPLETED,
            title=f"{reminder.title} completed",
            related_entity_type="reminder",
            related_entity_id=reminder.id,
            actor_user_id=user.id,
        )
    await session.flush()
    return ReminderOut.model_validate(reminder)


# response_model=None is required on 204 routes: `from __future__ import
# annotations` turns the `-> None` return hint into NoneType, which FastAPI
# would otherwise treat as a response body.
@router.delete(
    "/reminders/{reminder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_reminder(
    reminder_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    reminder = await _load(session, Reminder, reminder_id, "reminder")
    await require_write_access(session, user_id=user.id, family_id=reminder.family_id)
    reminder.status = ReminderStatus.ARCHIVED
    await session.flush()


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


@router.get("/seniors/{senior_id}/timeline", response_model=list[TimelineEventOut])
async def list_timeline(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    before: dt.datetime | None = Query(default=None),
) -> list[TimelineEventOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    statement = (
        select(TimelineEvent)
        .where(TimelineEvent.senior_profile_id == senior_id)
        .order_by(TimelineEvent.occurred_at.desc())
        .limit(limit)
    )
    if before is not None:
        statement = statement.where(TimelineEvent.occurred_at < before)
    rows = await session.execute(statement)
    return [TimelineEventOut.model_validate(row) for row in rows.scalars()]


# --------------------------------------------------------------------------- #
# Health readings
# --------------------------------------------------------------------------- #


@router.get("/seniors/{senior_id}/health-readings", response_model=list[HealthReadingOut])
async def list_health_readings(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    metric: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
) -> list[HealthReadingOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    statement = (
        select(HealthReading)
        .where(HealthReading.senior_profile_id == senior_id)
        .order_by(HealthReading.measured_at.desc())
        .limit(limit)
    )
    if metric:
        statement = statement.where(HealthReading.metric == metric)
    rows = await session.execute(statement)
    return [HealthReadingOut.model_validate(row) for row in rows.scalars()]


async def _create_reading(
    session: SessionDep,
    senior: SeniorProfile,
    user: CurrentUser,
    payload: HealthReadingCreate,
) -> HealthReading:
    """Validate and store one measurement — the body the single and bulk
    routes below both call, so their rules cannot drift apart.

    The unit must match the one Gamira stores for that metric, and the value
    must be physically plausible. Neither check is a clinical judgement: the
    backend never labels a reading as healthy or unhealthy.
    """
    expected_unit, minimum, maximum = METRIC_UNITS[payload.metric]
    if payload.unit != expected_unit:
        raise ValidationFailed(
            f"{payload.metric.value} must be recorded in {expected_unit}.",
            code="unsupported_unit",
            details={"expected_unit": expected_unit, "received_unit": payload.unit},
        )
    if not minimum <= payload.value <= maximum:
        raise ValidationFailed(
            f"{payload.metric.value} must be between {minimum} and {maximum} "
            f"{expected_unit}.",
            code="value_out_of_range",
        )
    if payload.measured_at > utcnow() + dt.timedelta(minutes=5):
        raise ValidationFailed(
            "A reading cannot be measured in the future.", code="measured_at_in_future"
        )

    reading = HealthReading(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        recorded_by_user_id=user.id,
        **payload.model_dump(),
    )
    session.add(reading)
    await session.flush()

    # A person entering a measurement is an event in the family's day and
    # belongs on the timeline. A paired device sending one every few seconds is
    # a stream: it belongs in the trend, and putting it on the timeline would
    # bury the doses and alerts the timeline exists to show.
    if payload.source != HealthSource.DEVICE:
        await record_timeline_event(
            session,
            family_id=senior.family_id,
            senior_profile_id=senior.id,
            type=TimelineEventType.HEALTH_READING_ADDED,
            title=f"{payload.metric.value.replace('_', ' ')} recorded",
            related_entity_type="health_reading",
            related_entity_id=reading.id,
            actor_user_id=user.id,
            occurred_at=payload.measured_at,
        )
    return reading


@router.post(
    "/seniors/{senior_id}/health-readings",
    response_model=HealthReadingOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_health_reading(
    senior_id: uuid.UUID,
    payload: HealthReadingCreate,
    session: SessionDep,
    user: CurrentUser,
) -> HealthReadingOut:
    """Store one measurement.

    A person may always record their own measurement — from the Parent App or
    from a watch paired to their own account. Recording someone else's still
    needs a write role, so a doctor or viewer cannot add readings to another
    person's record.
    """
    await require_self_or_write_access(
        session, user_id=user.id, senior_profile_id=senior_id
    )
    senior = await session.get(SeniorProfile, senior_id)
    if senior is None:  # pragma: no cover - the helper above already raised
        raise NotFound("The requested person does not exist.")
    reading = await _create_reading(session, senior, user, payload)
    return HealthReadingOut.model_validate(reading)


@router.post(
    "/seniors/{senior_id}/health-readings/bulk",
    response_model=list[HealthReadingOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_health_readings_bulk(
    senior_id: uuid.UUID,
    payload: HealthReadingBulkCreate,
    session: SessionDep,
    user: CurrentUser,
) -> list[HealthReadingOut]:
    """The same store, for a batch — a paired watch's relay flushing several
    metrics at once rather than one request per metric.

    Access is resolved once for the whole batch, not once per reading: the
    point of a bulk endpoint is fewer round trips, and re-checking membership
    fifty times inside one request would give most of that back.
    """
    await require_self_or_write_access(
        session, user_id=user.id, senior_profile_id=senior_id
    )
    senior = await session.get(SeniorProfile, senior_id)
    if senior is None:  # pragma: no cover - the helper above already raised
        raise NotFound("The requested person does not exist.")
    readings = [
        await _create_reading(session, senior, user, item) for item in payload.readings
    ]
    return [HealthReadingOut.model_validate(reading) for reading in readings]


# --------------------------------------------------------------------------- #
# Wellbeing checks
# --------------------------------------------------------------------------- #


@router.get(
    "/seniors/{senior_id}/wellbeing-checks",
    response_model=list[WellbeingCheckOut],
)
async def list_wellbeing_checks(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    pending_only: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
) -> list[WellbeingCheckOut]:
    """Questions a device flagging a reading has left owed.

    The Parent App polls this so Gamira can ask; the family can read it too,
    because "your watch flagged something and we asked" is about them and they
    are entitled to see it without asking anybody.
    """
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    statement = (
        select(WellbeingCheck)
        .where(WellbeingCheck.senior_profile_id == senior_id)
        .order_by(WellbeingCheck.created_at.desc())
        .limit(limit)
    )
    if pending_only:
        statement = statement.where(
            WellbeingCheck.status == WellbeingCheckStatus.PENDING
        )
    rows = await session.execute(statement)
    return [_wellbeing_out(row) for row in rows.scalars()]


@router.post(
    "/wellbeing-checks/{check_id}/answer",
    response_model=WellbeingCheckOut,
)
async def answer_wellbeing_check(
    check_id: uuid.UUID,
    payload: WellbeingCheckAnswer,
    session: SessionDep,
    user: CurrentUser,
) -> WellbeingCheckOut:
    """Answer by tapping, for somebody who cannot answer by speaking.

    Voice is the intended path and the reason this feature exists, but a person
    whose microphone is broken, or who simply does not want to talk, must still
    be able to say they are fine. Without this the only way to stop the alert
    would be to not have the problem.
    """
    check = await session.get(WellbeingCheck, check_id)
    if check is None:
        raise NotFound("The requested check does not exist.")
    await require_self_or_write_access(
        session, user_id=user.id, senior_profile_id=check.senior_profile_id
    )
    await wellbeing_service.record_answer(
        session, check=check, alright=payload.alright, actor_user_id=user.id
    )
    if not payload.alright:
        # They said they are not alright, so the rule runs now rather than at
        # the end of the grace period. It is still the rule that decides.
        await enqueue_job(
            session,
            JobType.WELLBEING_CHECK_ESCALATE,
            payload={"check_id": str(check.id)},
            dedupe_key=f"wellbeing-now:{check.id}",
            priority=URGENT_PRIORITY,
            family_id=check.family_id,
        )
    return _wellbeing_out(check)


def _wellbeing_out(check: WellbeingCheck) -> WellbeingCheckOut:
    return WellbeingCheckOut(
        id=check.id,
        senior_profile_id=check.senior_profile_id,
        status=check.status,
        reason=check.reason,
        metric=check.metric,
        value=check.value,
        unit=check.unit,
        source_device=check.source_device,
        asked=check.asked_at is not None,
        created_at=check.created_at,
        answered_at=check.answered_at,
    )


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    session: SessionDep,
    user: CurrentUser,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
) -> list[NotificationOut]:
    """Only the caller's own notifications, never another member's.

    This is the in-app inbox, so it returns the ``in_app`` rows. The ``push``
    rows beside them are delivery jobs with their own attempt history, not
    things to show twice.
    """
    statement = (
        select(NotificationDelivery)
        .where(
            NotificationDelivery.user_id == user.id,
            NotificationDelivery.channel == NotificationChannel.IN_APP,
        )
        .order_by(NotificationDelivery.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        statement = statement.where(NotificationDelivery.opened_at.is_(None))
    rows = await session.execute(statement)
    return [NotificationOut.model_validate(row) for row in rows.scalars()]


@router.post("/notifications/{notification_id}/opened", response_model=NotificationOut)
async def mark_notification_opened(
    notification_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> NotificationOut:
    notification = await session.get(NotificationDelivery, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFound("The requested notification does not exist.")
    if notification.opened_at is None:
        notification.opened_at = utcnow()
        notification.status = NotificationStatus.OPENED
        await session.flush()
    return NotificationOut.model_validate(notification)


# --------------------------------------------------------------------------- #
# Emergency contacts
# --------------------------------------------------------------------------- #


@router.get(
    "/seniors/{senior_id}/emergency-contacts",
    response_model=list[EmergencyContactOut],
)
async def list_emergency_contacts(
    senior_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[EmergencyContactOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    rows = await session.execute(
        select(EmergencyContact)
        .where(EmergencyContact.senior_profile_id == senior_id)
        .order_by(EmergencyContact.priority, EmergencyContact.created_at)
    )
    return [EmergencyContactOut.model_validate(row) for row in rows.scalars()]


@router.post(
    "/seniors/{senior_id}/emergency-contacts",
    response_model=EmergencyContactOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_emergency_contact(
    senior_id: uuid.UUID,
    payload: EmergencyContactCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EmergencyContactOut:
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=senior_id, write=True
    )
    contact = EmergencyContact(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        **payload.model_dump(),
    )
    session.add(contact)
    await session.flush()
    await record_audit(
        session,
        action="emergency_contact.create",
        actor_user_id=user.id,
        target_type="emergency_contact",
        target_id=contact.id,
        family_id=senior.family_id,
    )
    return EmergencyContactOut.model_validate(contact)


@router.patch("/emergency-contacts/{contact_id}", response_model=EmergencyContactOut)
async def update_emergency_contact(
    contact_id: uuid.UUID,
    payload: EmergencyContactUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EmergencyContactOut:
    contact = await _load(session, EmergencyContact, contact_id, "contact")
    await require_write_access(session, user_id=user.id, family_id=contact.family_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    await session.flush()
    return EmergencyContactOut.model_validate(contact)


@router.delete(
    "/emergency-contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_emergency_contact(
    contact_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    contact = await _load(session, EmergencyContact, contact_id, "contact")
    await require_write_access(session, user_id=user.id, family_id=contact.family_id)
    await session.delete(contact)
    await session.flush()
    await record_audit(
        session,
        action="emergency_contact.delete",
        actor_user_id=user.id,
        target_type="emergency_contact",
        target_id=contact_id,
        family_id=contact.family_id,
    )


# --------------------------------------------------------------------------- #
# Appointments
# --------------------------------------------------------------------------- #


@router.get("/seniors/{senior_id}/appointments", response_model=list[AppointmentOut])
async def list_appointments(
    senior_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[AppointmentOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    rows = await session.execute(
        select(Appointment)
        .where(Appointment.senior_profile_id == senior_id)
        .order_by(Appointment.starts_at.desc())
    )
    return [AppointmentOut.model_validate(row) for row in rows.scalars()]


@router.post(
    "/seniors/{senior_id}/appointments",
    response_model=AppointmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_appointment(
    senior_id: uuid.UUID,
    payload: AppointmentCreate,
    session: SessionDep,
    user: CurrentUser,
) -> AppointmentOut:
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=senior_id, write=True
    )
    data = payload.model_dump()
    data["timezone"] = data.get("timezone") or senior.timezone
    appointment = Appointment(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        created_by_user_id=user.id,
        **data,
    )
    session.add(appointment)
    await session.flush()
    await record_timeline_event(
        session,
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        type=TimelineEventType.APPOINTMENT_SCHEDULED,
        title=f"{appointment.title} scheduled",
        related_entity_type="appointment",
        related_entity_id=appointment.id,
        actor_user_id=user.id,
        occurred_at=appointment.starts_at,
    )
    return AppointmentOut.model_validate(appointment)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
async def update_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> AppointmentOut:
    appointment = await _load(session, Appointment, appointment_id, "appointment")
    await require_write_access(session, user_id=user.id, family_id=appointment.family_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(appointment, field, value)
    await session.flush()
    return AppointmentOut.model_validate(appointment)


# --------------------------------------------------------------------------- #
# Family notes
# --------------------------------------------------------------------------- #


@router.get("/families/{family_id}/notes", response_model=list[FamilyNoteOut])
async def list_notes(
    family_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    senior_id: uuid.UUID | None = Query(default=None),
) -> list[FamilyNoteOut]:
    await require_membership(session, user_id=user.id, family_id=family_id)
    statement = (
        select(FamilyNote)
        .where(FamilyNote.family_id == family_id)
        .order_by(FamilyNote.created_at.desc())
    )
    if senior_id is not None:
        statement = statement.where(FamilyNote.senior_profile_id == senior_id)
    rows = await session.execute(statement)
    return [FamilyNoteOut.model_validate(row) for row in rows.scalars()]


@router.post(
    "/families/{family_id}/notes",
    response_model=FamilyNoteOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    family_id: uuid.UUID,
    payload: FamilyNoteCreate,
    session: SessionDep,
    user: CurrentUser,
) -> FamilyNoteOut:
    await require_write_access(session, user_id=user.id, family_id=family_id)
    if payload.senior_profile_id is not None:
        # Prevent attaching a note to a senior in a different family.
        await resolve_senior(
            session, user_id=user.id, senior_id=payload.senior_profile_id, write=True
        )
    note = FamilyNote(family_id=family_id, author_user_id=user.id, **payload.model_dump())
    session.add(note)
    await session.flush()
    return FamilyNoteOut.model_validate(note)


async def _load(
    session: SessionDep, model: type[ModelT], entity_id: uuid.UUID, label: str
) -> ModelT:
    entity = await session.get(model, entity_id)
    if entity is None:
        raise NotFound(f"The requested {label} does not exist.")
    return entity
