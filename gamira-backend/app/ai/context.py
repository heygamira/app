"""Permission-scoped retrieval: what the model is allowed to be told.

Every function here takes an :class:`ActorContext` — a user, a senior and a
*verified* active membership — rather than ids. That is what makes the scoping
structural instead of remembered: there is no way to call these with a senior
the caller has not already been authorised for, because the authorisation is
the argument.

Two habits run through all of it:

* **Least data.** A model that needs to say "your blood pressure this morning
  was one twenty over eighty" needs one reading per metric, not a month of
  them. A model that needs to offer to ring somebody needs a name and an id,
  not a phone number.
* **No judgements.** Readings come back as values, units and timestamps.
  Nothing in this module labels one normal, high or concerning, because
  nothing in Gamira is entitled to.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.policy import ActorContext
from app.db.base import utcnow
from app.models.care import (
    Appointment,
    EmergencyContact,
    HealthReading,
    NotificationDelivery,
    Reminder,
)
from app.models.enums import (
    AppointmentStatus,
    DoseStatus,
    NotificationChannel,
    ReminderStatus,
)
from app.models.medication import DoseEvent
from app.services import memories as memory_service
from app.services.scheduling import load_timezone

# Enough for a spoken answer, small enough that a Live turn is not carrying a
# medical history around.
MAX_DOSES = 24
MAX_REMINDERS = 20
MAX_APPOINTMENTS = 5
MAX_CONTACTS = 10

# What the model is told a dose status means, in words it can speak.
DOSE_WORDS: dict[DoseStatus, str] = {
    DoseStatus.DUE: "not taken yet",
    DoseStatus.REMINDED: "not taken yet",
    DoseStatus.TAKEN: "taken",
    DoseStatus.SKIPPED: "skipped",
    DoseStatus.LATE: "late",
    DoseStatus.MISSED: "missed",
    DoseStatus.CANCELLED: "cancelled",
}


def local_day_bounds(
    timezone_name: str, now: dt.datetime | None = None
) -> tuple[dt.datetime, dt.datetime, dt.date]:
    tz = load_timezone(timezone_name)
    local_now = (now or utcnow()).astimezone(tz)
    today = local_now.date()
    start = dt.datetime.combine(today, dt.time.min, tzinfo=tz).astimezone(dt.UTC)
    return start, start + dt.timedelta(days=1), today


async def today_doses(
    session: AsyncSession, actor: ActorContext, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Today's doses for this person, in time order."""
    start, end, today = local_day_bounds(actor.senior.timezone, now)
    rows = await session.execute(
        select(DoseEvent)
        .options(
            selectinload(DoseEvent.medication), selectinload(DoseEvent.schedule)
        )
        .where(
            DoseEvent.senior_profile_id == actor.senior.id,
            DoseEvent.scheduled_at_utc >= start,
            DoseEvent.scheduled_at_utc < end,
            DoseEvent.status != DoseStatus.CANCELLED,
        )
        .order_by(DoseEvent.scheduled_at_utc)
        .limit(MAX_DOSES)
    )
    doses = [
        {
            "dose_event_id": str(event.id),
            "medication": event.medication.name if event.medication else "Medicine",
            "dose": (event.schedule.dose_quantity if event.schedule else None),
            "time": event.scheduled_local_time,
            "status": DOSE_WORDS.get(event.status, event.status.value),
        }
        for event in rows.scalars().unique()
    ]
    return {"date": today.isoformat(), "timezone": actor.senior.timezone, "doses": doses}


async def today_schedule(
    session: AsyncSession, actor: ActorContext, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Doses and reminders together, in the order the day happens."""
    doses = await today_doses(session, actor, now=now)
    reminders = await active_reminders(session, actor)
    items: list[dict[str, Any]] = [
        {
            "kind": "dose",
            "time": dose["time"],
            "title": dose["medication"],
            "detail": dose["dose"],
            "status": dose["status"],
            "id": dose["dose_event_id"],
        }
        for dose in doses["doses"]
    ]
    items.extend(
        {
            "kind": "reminder",
            "time": reminder["time"],
            "title": reminder["title"],
            "detail": reminder["instructions"],
            "status": "not done yet",
            "id": reminder["reminder_id"],
        }
        for reminder in reminders["reminders"]
        if reminder["time"]
    )
    items.sort(key=lambda item: str(item["time"] or "99:99"))
    return {"date": doses["date"], "timezone": doses["timezone"], "items": items}


async def active_reminders(
    session: AsyncSession, actor: ActorContext
) -> dict[str, Any]:
    rows = await session.execute(
        select(Reminder)
        .where(
            Reminder.senior_profile_id == actor.senior.id,
            Reminder.status == ReminderStatus.ACTIVE,
        )
        .order_by(Reminder.local_time.nulls_last(), Reminder.created_at)
        .limit(MAX_REMINDERS)
    )
    return {
        "reminders": [
            {
                "reminder_id": str(row.id),
                "title": row.title,
                "instructions": row.instructions,
                "time": row.local_time,
                "type": row.type.value,
            }
            for row in rows.scalars()
        ]
    }


async def latest_health_readings(
    session: AsyncSession,
    actor: ActorContext,
    *,
    metric: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """The most recent value per metric — values, never assessments."""
    now = now or utcnow()
    statement = (
        select(HealthReading)
        .where(HealthReading.senior_profile_id == actor.senior.id)
        .order_by(HealthReading.measured_at.desc())
        .limit(200)
    )
    if metric:
        statement = statement.where(HealthReading.metric == metric)
    rows = await session.execute(statement)

    latest: dict[str, dict[str, Any]] = {}
    for reading in rows.scalars():
        key = reading.metric.value
        if key in latest:
            continue
        measured = (
            reading.measured_at
            if reading.measured_at.tzinfo
            else reading.measured_at.replace(tzinfo=dt.UTC)
        )
        latest[key] = {
            "metric": key,
            "value": reading.value,
            "unit": reading.unit,
            "measured_at": measured.isoformat(),
            "hours_ago": round((now - measured).total_seconds() / 3600, 1),
            "source": reading.source.value,
        }
    return {
        "readings": [latest[key] for key in sorted(latest)],
        # Repeated in the payload so the model has no excuse: it is looking at
        # numbers, and it is not qualified to say what they mean.
        "note": "Values only. Gamira does not assess whether a reading is safe.",
    }


async def upcoming_appointments(
    session: AsyncSession, actor: ActorContext, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    now = now or utcnow()
    tz = load_timezone(actor.senior.timezone)
    rows = await session.execute(
        select(Appointment)
        .where(
            Appointment.senior_profile_id == actor.senior.id,
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.starts_at >= now,
        )
        .order_by(Appointment.starts_at)
        .limit(MAX_APPOINTMENTS)
    )
    return {
        "appointments": [
            {
                "appointment_id": str(row.id),
                "title": row.title,
                "clinician": row.clinician,
                "location": row.location,
                "local_time": row.starts_at.astimezone(tz).strftime("%A %d %B, %H:%M"),
            }
            for row in rows.scalars()
        ]
    }


async def emergency_contacts(
    session: AsyncSession, actor: ActorContext
) -> dict[str, Any]:
    """Who could be rung, and their id. Never the number itself.

    The model only ever needs to say "shall I get Priya's number up?" — the
    dialer is opened by the app from the contact id. Putting the digits in a
    conversation would put them in a transcript for no benefit.
    """
    rows = await session.execute(
        select(EmergencyContact)
        .where(EmergencyContact.senior_profile_id == actor.senior.id)
        .order_by(EmergencyContact.priority, EmergencyContact.created_at)
        .limit(MAX_CONTACTS)
    )
    return {
        "contacts": [
            {
                "contact_id": str(row.id),
                "name": row.name,
                "relationship": row.relationship_label,
                "priority": row.priority,
                "is_primary": row.is_primary,
                "phone_ending": row.phone[-4:] if row.phone else None,
            }
            for row in rows.scalars()
        ]
    }


async def notification_summary(
    session: AsyncSession, actor: ActorContext
) -> dict[str, Any]:
    """How much is waiting for the caller, by kind. The caller's own only."""
    rows = await session.execute(
        select(NotificationDelivery.type, func.count(NotificationDelivery.id))
        .where(
            NotificationDelivery.user_id == actor.user.id,
            NotificationDelivery.channel == NotificationChannel.IN_APP,
            NotificationDelivery.opened_at.is_(None),
        )
        .group_by(NotificationDelivery.type)
    )
    by_type = {
        str(kind.value if hasattr(kind, "value") else kind): int(count)
        for kind, count in rows.all()
    }
    return {"unread_total": sum(by_type.values()), "unread_by_type": by_type}


async def chat_context(
    session: AsyncSession, actor: ActorContext, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    """The compact bundle a text chat gets. Same scoping, same limits."""
    return {
        "schedule": await today_schedule(session, actor, now=now),
        "health": await latest_health_readings(session, actor, now=now),
        "appointments": await upcoming_appointments(session, actor, now=now),
        "notifications": await notification_summary(session, actor),
        # What Gamira has picked up in earlier conversations. Kind and wording
        # only — the same least-data rule as everything above, and capped by
        # `services/memories.py` rather than here.
        "memories": await memory_service.recall_for_prompt(
            session, senior_profile_id=actor.senior.id
        ),
    }


__all__ = [
    "DOSE_WORDS",
    "active_reminders",
    "chat_context",
    "emergency_contacts",
    "latest_health_readings",
    "local_day_bounds",
    "notification_summary",
    "today_doses",
    "today_schedule",
    "upcoming_appointments",
]
