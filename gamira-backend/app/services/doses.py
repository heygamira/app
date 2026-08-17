"""Dose-event generation and acknowledgement.

Two properties matter here and are tested directly:

1. Generation is retry-safe. Running it twice over the same window produces the
   same rows, because ``(schedule, scheduled_at_utc)`` is unique.
2. Acknowledgement is idempotent. A duplicated notification tap, an offline
   replay or a retried request returns the existing canonical event rather than
   recording a second dose.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.models.enums import (
    TERMINAL_DOSE_STATUSES,
    DoseSource,
    DoseStatus,
    MedicationStatus,
    TimelineEventType,
)
from app.models.identity import SeniorProfile
from app.models.medication import DoseEvent, Medication, MedicationSchedule
from app.services import scheduling
from app.services.timeline import record_timeline_event


async def generate_dose_events(
    session: AsyncSession,
    *,
    senior: SeniorProfile,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[DoseEvent]:
    """Materialise every missing dose event for a senior in the window."""
    result = await session.execute(
        select(Medication)
        .options(selectinload(Medication.schedules))
        .where(
            Medication.senior_profile_id == senior.id,
            Medication.status == MedicationStatus.ACTIVE,
        )
    )
    medications = result.scalars().unique().all()

    existing_result = await session.execute(
        select(DoseEvent.medication_schedule_id, DoseEvent.scheduled_at_utc).where(
            DoseEvent.senior_profile_id == senior.id,
            DoseEvent.scheduled_at_utc >= window_start,
            DoseEvent.scheduled_at_utc < window_end,
        )
    )
    existing: set[tuple[uuid.UUID, dt.datetime]] = {
        (schedule_id, _as_utc(instant)) for schedule_id, instant in existing_result.all()
    }

    created: list[DoseEvent] = []
    for medication in medications:
        for schedule in medication.schedules:
            for instant in scheduling.occurrences(
                schedule,
                medication,
                window_start=window_start,
                window_end=window_end,
            ):
                if (schedule.id, instant) in existing:
                    continue
                event = DoseEvent(
                    medication_schedule_id=schedule.id,
                    medication_id=medication.id,
                    family_id=medication.family_id,
                    senior_profile_id=senior.id,
                    scheduled_at_utc=instant,
                    scheduled_local_time=schedule.local_time,
                    scheduled_timezone=schedule.timezone,
                    status=DoseStatus.DUE,
                )
                session.add(event)
                created.append(event)
                existing.add((schedule.id, instant))

    if created:
        await session.flush()
    return created


def apply_time_derived_status(
    event: DoseEvent, *, now: dt.datetime | None = None
) -> bool:
    """Move an unacknowledged dose to late or missed as its windows elapse.

    Returns True when the stored status changed. A dose that a person has
    already acted on is never re-derived.
    """
    if event.status in TERMINAL_DOSE_STATUSES:
        return False

    now = now or utcnow()
    scheduled = _as_utc(event.scheduled_at_utc)
    schedule = event.schedule
    late_after = dt.timedelta(minutes=schedule.late_after_minutes if schedule else 30)
    missed_after = dt.timedelta(
        minutes=schedule.missed_after_minutes if schedule else 120
    )

    if now >= scheduled + missed_after:
        target = DoseStatus.MISSED
    elif now >= scheduled + late_after:
        target = DoseStatus.LATE
    else:
        return False

    if event.status is target:
        return False
    event.status = target
    return True


async def get_dose_event(session: AsyncSession, dose_event_id: uuid.UUID) -> DoseEvent:
    event = await session.get(
        DoseEvent,
        dose_event_id,
        options=[selectinload(DoseEvent.schedule), selectinload(DoseEvent.medication)],
    )
    if event is None:
        raise NotFound("The requested dose event does not exist.")
    return event


async def record_dose_outcome(
    session: AsyncSession,
    *,
    event: DoseEvent,
    status: DoseStatus,
    actor_user_id: uuid.UUID | None,
    source: DoseSource,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[DoseEvent, bool]:
    """Record taken or skipped. Returns the event and whether it changed.

    Replaying the same request is a no-op. Changing an already-recorded outcome
    is allowed as a correction, but only to another explicit outcome, and it is
    written to the timeline so the family can see the change.
    """
    if status not in (DoseStatus.TAKEN, DoseStatus.SKIPPED):
        raise Conflict(
            "A dose can only be recorded as taken or skipped.",
            code="unsupported_dose_status",
        )
    if event.status is DoseStatus.CANCELLED:
        raise Conflict(
            "This dose was cancelled and can no longer be recorded.",
            code="dose_event_cancelled",
        )

    replayed_key = (
        idempotency_key is not None and event.idempotency_key == idempotency_key
    )
    if replayed_key or event.status is status:
        return event, False

    event.status = status
    event.recorded_at = utcnow()
    event.recorded_by_user_id = actor_user_id
    event.source = source
    event.idempotency_key = idempotency_key
    if note:
        event.note = note
    await session.flush()

    medication_name = event.medication.name if event.medication else "Medication"
    await record_timeline_event(
        session,
        family_id=event.family_id,
        senior_profile_id=event.senior_profile_id,
        type=(
            TimelineEventType.MEDICATION_TAKEN
            if status is DoseStatus.TAKEN
            else TimelineEventType.MEDICATION_SKIPPED
        ),
        title=(
            f"{medication_name} taken"
            if status is DoseStatus.TAKEN
            else f"{medication_name} skipped"
        ),
        description=note,
        related_entity_type="dose_event",
        related_entity_id=event.id,
        actor_user_id=actor_user_id,
        occurred_at=event.recorded_at,
    )
    return event, True


async def schedules_for_medication(
    session: AsyncSession, medication_id: uuid.UUID
) -> list[MedicationSchedule]:
    result = await session.execute(
        select(MedicationSchedule).where(
            MedicationSchedule.medication_id == medication_id
        )
    )
    return list(result.scalars().all())


def _as_utc(value: dt.datetime) -> dt.datetime:
    """Normalise to aware UTC.

    SQLite returns naive datetimes even for timezone-aware columns, so stored
    values are re-tagged before they are compared with generated instants.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)
