"""The figures a summary is made of, counted by the backend.

This module is the reason the weekly summary is safe to ship. Every number in
a generated paragraph is counted here, from rows, with SQL — the model's only
job is to put those numbers into sentences. If Gemini is unavailable the
figures are still available, still correct, and still worth showing on their
own.

Nothing here forms an opinion. There is no wellness score, no trend
classification, no "readings look stable". Counts, timestamps and freshness.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import (
    AppointmentFact,
    CareFacts,
    ConversationFacts,
    DeviceFacts,
    DoseFacts,
    FamilyActivityFacts,
    HealthFacts,
    MetricFreshness,
    ReminderFacts,
)
from app.db.base import utcnow
from app.models.ai import AiSummary, Conversation
from app.models.alerts import Alert
from app.models.care import (
    Appointment,
    FamilyNote,
    HealthReading,
    Reminder,
    TimelineEvent,
)
from app.models.devices import RegisteredDevice
from app.models.enums import (
    AppointmentStatus,
    DeviceStatus,
    DoseStatus,
    HealthSource,
    ReminderStatus,
    SummaryKind,
)
from app.models.identity import SeniorProfile
from app.models.medication import DoseEvent
from app.services.scheduling import load_timezone

# Bumped when the *meaning* of a counted figure changes, so a stored summary
# can be read against the definitions that produced it.
SOURCE_DATA_VERSION = "1"

# A watch that has not reported for this long is worth saying out loud, because
# "no unusual readings" and "no readings" look identical on a chart.
STALE_DEVICE_HOURS = 36.0
# Below this many readings a week, any statement about health data is thin.
THIN_READING_COUNT = 3


async def build_care_facts(
    session: AsyncSession,
    *,
    senior: SeniorProfile,
    period_start: dt.date,
    period_end: dt.date,
    now: dt.datetime | None = None,
) -> CareFacts:
    """Count one person's week. Read-only, and scoped to that one person.

    The caller is responsible for having already checked that whoever asked may
    see this senior; this function takes the profile, not an id, so it cannot
    be handed something unverified.
    """
    now = now or utcnow()
    tz = load_timezone(senior.timezone)
    window_start = dt.datetime.combine(period_start, dt.time.min, tzinfo=tz).astimezone(
        dt.UTC
    )
    window_end = dt.datetime.combine(
        period_end + dt.timedelta(days=1), dt.time.min, tzinfo=tz
    ).astimezone(dt.UTC)

    doses = await _dose_facts(session, senior.id, window_start, window_end, now)
    reminders = await _reminder_facts(session, senior.id, window_start, window_end)
    health = await _health_facts(session, senior.id, window_start, window_end, now)
    devices = await _device_facts(session, senior.id, now)
    appointments = await _upcoming_appointments(session, senior.id, now)
    activity = await _family_activity(session, senior, window_start, window_end)
    talk = await _conversation_facts(session, senior.id, window_start, window_end)

    facts = CareFacts(
        senior_name=senior.preferred_name,
        period_start=period_start,
        period_end=period_end,
        timezone=senior.timezone,
        doses=doses,
        reminders=reminders,
        health=health,
        devices=devices,
        upcoming_appointments=appointments,
        family_activity=activity,
        conversation=talk,
    )
    facts.data_freshness_warning = freshness_warning(facts)
    return facts


async def _conversation_facts(
    session: AsyncSession,
    senior_id: uuid.UUID,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> ConversationFacts:
    """What the after-call reviews of this period recorded.

    Read back rather than recomputed: the reviews already happened, one per
    conversation, and re-reading their own recorded impression is what keeps
    the weekly digest and the daily one from ever disagreeing.

    `reviewed` is reported alongside `conversations` on purpose. A week with
    nine conversations and one review is not a quiet week — it is a week the
    reviewer could not keep up with, and the difference must be visible rather
    than averaged away.
    """
    conversations = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.senior_profile_id == senior_id,
                Conversation.started_at >= window_start,
                Conversation.started_at < window_end,
            )
        )
        or 0
    )

    rows = list(
        (
            await session.execute(
                select(AiSummary).where(
                    AiSummary.senior_profile_id == senior_id,
                    AiSummary.kind == SummaryKind.CONVERSATION,
                    AiSummary.generated_at >= window_start,
                    AiSummary.generated_at < window_end,
                )
            )
        ).scalars()
    )

    moods: dict[str, int] = {}
    themes: list[str] = []
    for row in rows:
        for line in (row.content or "").splitlines():
            text = line.strip()
            if text.startswith("How it sounded:"):
                word = text.removeprefix("How it sounded:").strip().rstrip(".")
                if word:
                    moods[word] = moods.get(word, 0) + 1
            elif text.startswith("- ") and len(themes) < 5:
                themes.append(text[2:])

    return ConversationFacts(
        conversations=conversations,
        reviewed=len(rows),
        moods=moods,
        themes=themes,
    )

def freshness_warning(facts: CareFacts) -> str | None:
    """Say plainly when the figures rest on very little.

    Returned rather than hidden: a summary of a week with two readings and no
    watch sync should say so, otherwise "nothing unusual" reads as reassurance
    it has not earned.
    """
    notes: list[str] = []
    if facts.doses.scheduled == 0:
        notes.append("No medication schedule was active in this period.")
    if facts.health.total_readings == 0:
        notes.append("No health readings were recorded in this period.")
    elif facts.health.total_readings < THIN_READING_COUNT:
        notes.append(
            f"Only {facts.health.total_readings} health readings were recorded, "
            "which is too few to describe a trend."
        )
    if facts.devices.registered_devices == 0:
        notes.append("No device is registered to send readings.")
    elif (
        facts.devices.hours_since_device_sync is not None
        and facts.devices.hours_since_device_sync > STALE_DEVICE_HOURS
    ):
        notes.append(
            "The paired device last sent a reading "
            f"{int(facts.devices.hours_since_device_sync)} hours ago."
        )
    elif facts.devices.last_device_reading_at is None:
        notes.append("The paired device has never sent a reading.")
    return " ".join(notes)[:400] or None


async def _dose_facts(
    session: AsyncSession,
    senior_id: uuid.UUID,
    start: dt.datetime,
    end: dt.datetime,
    now: dt.datetime,
) -> DoseFacts:
    rows = await session.execute(
        select(DoseEvent.status, DoseEvent.scheduled_at_utc).where(
            DoseEvent.senior_profile_id == senior_id,
            DoseEvent.scheduled_at_utc >= start,
            DoseEvent.scheduled_at_utc < end,
        )
    )
    facts = DoseFacts()
    for status, scheduled_at in rows.all():
        if status is DoseStatus.CANCELLED:
            # A cancelled dose was withdrawn by an archived medication. It was
            # never something anybody was asked to take.
            continue
        facts.scheduled += 1
        if _aware(scheduled_at) > now:
            facts.upcoming += 1
            continue
        if status is DoseStatus.TAKEN:
            facts.taken += 1
        elif status is DoseStatus.SKIPPED:
            facts.skipped += 1
        elif status is DoseStatus.MISSED:
            facts.missed += 1
        elif status is DoseStatus.LATE:
            facts.late += 1
    return facts


async def _reminder_facts(
    session: AsyncSession, senior_id: uuid.UUID, start: dt.datetime, end: dt.datetime
) -> ReminderFacts:
    active = await session.scalar(
        select(func.count())
        .select_from(Reminder)
        .where(
            Reminder.senior_profile_id == senior_id,
            Reminder.status == ReminderStatus.ACTIVE,
        )
    )
    completed = await session.scalar(
        select(func.count())
        .select_from(Reminder)
        .where(
            Reminder.senior_profile_id == senior_id,
            Reminder.last_completed_at.is_not(None),
            Reminder.last_completed_at >= start,
            Reminder.last_completed_at < end,
        )
    )
    return ReminderFacts(active=int(active or 0), completed=int(completed or 0))


async def _health_facts(
    session: AsyncSession,
    senior_id: uuid.UUID,
    start: dt.datetime,
    end: dt.datetime,
    now: dt.datetime,
) -> HealthFacts:
    rows = await session.execute(
        select(
            HealthReading.metric,
            func.count(HealthReading.id),
            func.max(HealthReading.measured_at),
        )
        .where(
            HealthReading.senior_profile_id == senior_id,
            HealthReading.measured_at >= start,
            HealthReading.measured_at < end,
        )
        .group_by(HealthReading.metric)
    )
    metrics: list[MetricFreshness] = []
    total = 0
    latest: dt.datetime | None = None
    for metric, count, most_recent in rows.all():
        aware = _aware(most_recent) if most_recent is not None else None
        total += int(count or 0)
        if aware is not None and (latest is None or aware > latest):
            latest = aware
        metrics.append(
            MetricFreshness(
                metric=str(metric.value if hasattr(metric, "value") else metric),
                readings=int(count or 0),
                latest_at=aware,
                hours_since_latest=_hours_between(aware, now),
            )
        )
    metrics.sort(key=lambda item: item.metric)
    return HealthFacts(total_readings=total, metrics=metrics, latest_reading_at=latest)


async def _device_facts(
    session: AsyncSession, senior_id: uuid.UUID, now: dt.datetime
) -> DeviceFacts:
    senior = await session.get(SeniorProfile, senior_id)
    registered = 0
    if senior is not None and senior.user_id is not None:
        registered = int(
            await session.scalar(
                select(func.count())
                .select_from(RegisteredDevice)
                .where(
                    RegisteredDevice.user_id == senior.user_id,
                    RegisteredDevice.status == DeviceStatus.ACTIVE,
                )
            )
            or 0
        )
    # A watch proves it is alive by sending a reading, which is a better
    # liveness signal than the app's own last-seen timestamp.
    last_sync = await session.scalar(
        select(func.max(HealthReading.measured_at)).where(
            HealthReading.senior_profile_id == senior_id,
            HealthReading.source == HealthSource.DEVICE,
        )
    )
    aware = _aware(last_sync) if last_sync is not None else None
    return DeviceFacts(
        registered_devices=registered,
        last_device_reading_at=aware,
        hours_since_device_sync=_hours_between(aware, now),
    )


async def _upcoming_appointments(
    session: AsyncSession, senior_id: uuid.UUID, now: dt.datetime
) -> list[AppointmentFact]:
    rows = await session.execute(
        select(Appointment)
        .where(
            Appointment.senior_profile_id == senior_id,
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.starts_at >= now,
        )
        .order_by(Appointment.starts_at)
        .limit(5)
    )
    return [
        AppointmentFact(
            title=row.title, starts_at=_aware(row.starts_at), clinician=row.clinician
        )
        for row in rows.scalars()
    ]


async def _family_activity(
    session: AsyncSession,
    senior: SeniorProfile,
    start: dt.datetime,
    end: dt.datetime,
) -> FamilyActivityFacts:
    events = await session.scalar(
        select(func.count())
        .select_from(TimelineEvent)
        .where(
            TimelineEvent.senior_profile_id == senior.id,
            TimelineEvent.occurred_at >= start,
            TimelineEvent.occurred_at < end,
        )
    )
    notes = await session.scalar(
        select(func.count())
        .select_from(FamilyNote)
        .where(
            FamilyNote.senior_profile_id == senior.id,
            FamilyNote.created_at >= start,
            FamilyNote.created_at < end,
        )
    )
    alert_rows = await session.execute(
        select(Alert.acknowledged_at).where(
            Alert.senior_profile_id == senior.id,
            Alert.raised_at >= start,
            Alert.raised_at < end,
        )
    )
    acknowledged = 0
    total_alerts = 0
    for (acknowledged_at,) in alert_rows.all():
        total_alerts += 1
        if acknowledged_at is not None:
            acknowledged += 1
    return FamilyActivityFacts(
        timeline_events=int(events or 0),
        notes_added=int(notes or 0),
        sos_alerts=total_alerts,
        sos_alerts_acknowledged=acknowledged,
    )


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _hours_between(then: dt.datetime | None, now: dt.datetime) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600, 1)


__all__ = ["SOURCE_DATA_VERSION", "build_care_facts", "freshness_warning"]
