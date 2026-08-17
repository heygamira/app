"""Medications, schedules and dose events."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, IdempotencyKey, SessionDep
from app.core.errors import NotFound
from app.db.base import utcnow
from app.jobs.queue import URGENT_PRIORITY, enqueue_job
from app.jobs.types import JobType
from app.models.enums import (
    DoseSource,
    DoseStatus,
    MedicationStatus,
    TimelineEventType,
)
from app.models.medication import DoseEvent, Medication, MedicationSchedule
from app.schemas.medication import (
    DoseEventOut,
    DoseOutcomeIn,
    MedicationCreate,
    MedicationOut,
    MedicationUpdate,
    ScheduleCreate,
    ScheduleOut,
    ScheduleUpdate,
)
from app.services import doses as dose_service
from app.services.authz import (
    require_self_or_write_access,
    require_write_access,
    resolve_senior,
)
from app.services.timeline import record_audit, record_timeline_event

router = APIRouter(tags=["medications"])

# Doses are generated on read for the requested range. A background job will
# later pre-generate the same rows; the unique constraint makes both safe.
DEFAULT_DOSE_WINDOW = dt.timedelta(days=1)


@router.get("/seniors/{senior_id}/medications", response_model=list[MedicationOut])
async def list_medications(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    include_archived: bool = Query(default=False),
) -> list[MedicationOut]:
    await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    statement = (
        select(Medication)
        .options(selectinload(Medication.schedules))
        .where(Medication.senior_profile_id == senior_id)
        .order_by(Medication.created_at.desc())
    )
    if not include_archived:
        statement = statement.where(Medication.status != MedicationStatus.ARCHIVED)
    rows = await session.execute(statement)
    return [MedicationOut.model_validate(row) for row in rows.scalars().unique()]


@router.post(
    "/seniors/{senior_id}/medications",
    response_model=MedicationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_medication(
    senior_id: uuid.UUID,
    payload: MedicationCreate,
    session: SessionDep,
    user: CurrentUser,
) -> MedicationOut:
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=senior_id, write=True
    )
    data = payload.model_dump(exclude={"schedules"})
    medication = Medication(
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
        **data,
    )
    session.add(medication)
    await session.flush()

    for schedule in payload.schedules:
        session.add(_build_schedule(medication.id, schedule, senior.timezone))
    await session.flush()
    await session.refresh(medication, attribute_names=["schedules"])

    # The reads are read-only now, so today's doses have to be asked for. This
    # commits with the medication: either both exist or neither does.
    await _request_materialization(session, senior.id, senior.family_id)

    await record_timeline_event(
        session,
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        type=TimelineEventType.MEDICATION_ADDED,
        title=f"{medication.name} added",
        description=medication.instructions,
        related_entity_type="medication",
        related_entity_id=medication.id,
        actor_user_id=user.id,
    )
    await record_audit(
        session,
        action="medication.create",
        actor_user_id=user.id,
        target_type="medication",
        target_id=medication.id,
        family_id=senior.family_id,
    )
    return MedicationOut.model_validate(medication)


@router.get("/medications/{medication_id}", response_model=MedicationOut)
async def get_medication(
    medication_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> MedicationOut:
    medication = await _load_medication(session, medication_id)
    await resolve_senior(session, user_id=user.id, senior_id=medication.senior_profile_id)
    return MedicationOut.model_validate(medication)


@router.patch("/medications/{medication_id}", response_model=MedicationOut)
async def update_medication(
    medication_id: uuid.UUID,
    payload: MedicationUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> MedicationOut:
    medication = await _load_medication(session, medication_id)
    await require_write_access(session, user_id=user.id, family_id=medication.family_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(medication, field, value)
    medication.updated_by_user_id = user.id
    await session.flush()
    await record_audit(
        session,
        action="medication.update",
        actor_user_id=user.id,
        target_type="medication",
        target_id=medication.id,
        family_id=medication.family_id,
    )
    return MedicationOut.model_validate(medication)


@router.post("/medications/{medication_id}/archive", response_model=MedicationOut)
async def archive_medication(
    medication_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> MedicationOut:
    """Archive a medication. History and past dose events are retained."""
    medication = await _load_medication(session, medication_id)
    await require_write_access(session, user_id=user.id, family_id=medication.family_id)
    medication.status = MedicationStatus.ARCHIVED
    medication.archived_at = utcnow()
    medication.updated_by_user_id = user.id

    # Future doses that nobody has acted on are cancelled; the past is untouched.
    upcoming = await session.execute(
        select(DoseEvent).where(
            DoseEvent.medication_id == medication.id,
            DoseEvent.scheduled_at_utc > utcnow(),
            DoseEvent.status.in_([DoseStatus.DUE, DoseStatus.REMINDED]),
        )
    )
    for event in upcoming.scalars():
        event.status = DoseStatus.CANCELLED
    await session.flush()

    await record_audit(
        session,
        action="medication.archive",
        actor_user_id=user.id,
        target_type="medication",
        target_id=medication.id,
        family_id=medication.family_id,
    )
    return MedicationOut.model_validate(medication)


@router.post(
    "/medications/{medication_id}/schedules",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    medication_id: uuid.UUID,
    payload: ScheduleCreate,
    session: SessionDep,
    user: CurrentUser,
) -> ScheduleOut:
    medication = await _load_medication(session, medication_id)
    senior, _ = await resolve_senior(
        session, user_id=user.id, senior_id=medication.senior_profile_id, write=True
    )
    schedule = _build_schedule(medication.id, payload, senior.timezone)
    session.add(schedule)
    await session.flush()
    await _request_materialization(session, senior.id, senior.family_id)
    return ScheduleOut.model_validate(schedule)


@router.patch("/medication-schedules/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> ScheduleOut:
    schedule = await session.get(MedicationSchedule, schedule_id)
    if schedule is None:
        raise NotFound("The requested schedule does not exist.")
    medication = await _load_medication(session, schedule.medication_id)
    await require_write_access(session, user_id=user.id, family_id=medication.family_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    await session.flush()
    return ScheduleOut.model_validate(schedule)


@router.delete(
    "/medication-schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_schedule(
    schedule_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> None:
    schedule = await session.get(MedicationSchedule, schedule_id)
    if schedule is None:
        raise NotFound("The requested schedule does not exist.")
    medication = await _load_medication(session, schedule.medication_id)
    await require_write_access(session, user_id=user.id, family_id=medication.family_id)
    await session.delete(schedule)
    await session.flush()


@router.get("/seniors/{senior_id}/doses", response_model=list[DoseEventOut])
async def list_doses(
    senior_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    from_: dt.datetime | None = Query(default=None, alias="from"),
    to: dt.datetime | None = Query(default=None),
) -> list[DoseEventOut]:
    """Return dose events in a window. Read-only.

    This used to generate the rows it was about to return, and derive their
    late/missed status on the way past. Both are now the worker's job
    (``doses.materialize`` and ``doses.advance_status``), which is what makes
    the medication loop work when nobody has a screen open — a dose is missed
    because time passed, not because somebody looked.

    Defaults to the senior's current local day so the Parent App can ask for
    "today" without doing timezone arithmetic on the device.
    """
    senior, _ = await resolve_senior(session, user_id=user.id, senior_id=senior_id)
    window_start, window_end = _resolve_window(senior.timezone, from_, to)

    rows = await session.execute(
        select(DoseEvent)
        .options(selectinload(DoseEvent.medication), selectinload(DoseEvent.schedule))
        .where(
            DoseEvent.senior_profile_id == senior.id,
            DoseEvent.scheduled_at_utc >= window_start,
            DoseEvent.scheduled_at_utc < window_end,
        )
        .order_by(DoseEvent.scheduled_at_utc)
    )
    return [_dose_out(event) for event in rows.scalars().unique()]


@router.post("/dose-events/{dose_event_id}/taken", response_model=DoseEventOut)
async def mark_taken(
    dose_event_id: uuid.UUID,
    payload: DoseOutcomeIn,
    session: SessionDep,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
) -> DoseEventOut:
    return await _record_outcome(
        session, user, dose_event_id, DoseStatus.TAKEN, payload, idempotency_key
    )


@router.post("/dose-events/{dose_event_id}/skipped", response_model=DoseEventOut)
async def mark_skipped(
    dose_event_id: uuid.UUID,
    payload: DoseOutcomeIn,
    session: SessionDep,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
) -> DoseEventOut:
    return await _record_outcome(
        session, user, dose_event_id, DoseStatus.SKIPPED, payload, idempotency_key
    )


async def _record_outcome(
    session: SessionDep,
    user: CurrentUser,
    dose_event_id: uuid.UUID,
    outcome: DoseStatus,
    payload: DoseOutcomeIn,
    idempotency_key: str | None,
) -> DoseEventOut:
    event = await dose_service.get_dose_event(session, dose_event_id)
    await require_self_or_write_access(
        session, user_id=user.id, senior_profile_id=event.senior_profile_id
    )

    event, changed = await dose_service.record_dose_outcome(
        session,
        event=event,
        status=outcome,
        actor_user_id=user.id,
        source=payload.source or DoseSource.FAMILY_APP,
        note=payload.note,
        idempotency_key=idempotency_key,
    )
    if changed:
        await record_audit(
            session,
            action=f"dose_event.{outcome.value}",
            actor_user_id=user.id,
            target_type="dose_event",
            target_id=event.id,
            family_id=event.family_id,
        )
    return _dose_out(event)


async def _request_materialization(
    session: SessionDep, senior_id: uuid.UUID, family_id: uuid.UUID
) -> None:
    """Ask the worker to fill in this person's dose events now.

    Enqueued in the same transaction as the change that needs it, and deduped
    per senior so a family adding four medicines in a row produces one job. The
    recurring sweep would find them anyway; this only removes the wait.
    """
    await enqueue_job(
        session,
        JobType.DOSE_MATERIALIZE,
        payload={"senior_profile_id": str(senior_id)},
        dedupe_key=f"materialize:{senior_id}",
        priority=URGENT_PRIORITY,
        family_id=family_id,
    )


def _build_schedule(
    medication_id: uuid.UUID, payload: ScheduleCreate, fallback_timezone: str
) -> MedicationSchedule:
    data = payload.model_dump()
    # A schedule without an explicit zone follows the senior's own timezone.
    data["timezone"] = data.get("timezone") or fallback_timezone
    return MedicationSchedule(medication_id=medication_id, **data)


async def _load_medication(session: SessionDep, medication_id: uuid.UUID) -> Medication:
    medication = await session.get(
        Medication, medication_id, options=[selectinload(Medication.schedules)]
    )
    if medication is None:
        raise NotFound("The requested medication does not exist.")
    return medication


def _resolve_window(
    timezone_name: str, from_: dt.datetime | None, to: dt.datetime | None
) -> tuple[dt.datetime, dt.datetime]:
    from app.services.scheduling import load_timezone

    if from_ and to:
        return _as_utc(from_), _as_utc(to)

    tz = load_timezone(timezone_name)
    today = dt.datetime.now(tz).date()
    start_local = dt.datetime.combine(today, dt.time.min, tzinfo=tz)
    start = _as_utc(from_) if from_ else start_local.astimezone(dt.UTC)
    end = _as_utc(to) if to else start + DEFAULT_DOSE_WINDOW
    return start, end


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _dose_out(event: DoseEvent) -> DoseEventOut:
    out = DoseEventOut.model_validate(event)
    if event.medication is not None:
        out.medication_name = event.medication.name
    if event.schedule is not None:
        out.dose_quantity = event.schedule.dose_quantity
    return out
