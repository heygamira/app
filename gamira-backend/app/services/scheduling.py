"""Turning recurring schedules into concrete dose occurrences.

The senior's local wall-clock time is authoritative. Occurrences are built in
their IANA timezone and then converted to UTC, so an 08:00 dose stays at 08:00
across a daylight-saving transition instead of drifting by an hour.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import ValidationFailed
from app.models.enums import MedicationStatus, ScheduleStatus
from app.models.medication import Medication, MedicationSchedule

# A generation window guard: asking for years of occurrences in one request
# would produce an unbounded write.
MAX_GENERATION_DAYS = 92


def parse_days_of_week(raw: str) -> set[int]:
    """Parse ``"1,3,5"`` into ISO weekday numbers. Empty means every day."""
    if not raw.strip():
        return {1, 2, 3, 4, 5, 6, 7}
    days: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            day = int(part)
        except ValueError:
            raise ValidationFailed(
                "days_of_week must be ISO weekday numbers, 1 (Monday) to 7 (Sunday).",
                code="invalid_days_of_week",
            ) from None
        if not 1 <= day <= 7:
            raise ValidationFailed(
                "days_of_week must be ISO weekday numbers, 1 (Monday) to 7 (Sunday).",
                code="invalid_days_of_week",
            )
        days.add(day)
    return days or {1, 2, 3, 4, 5, 6, 7}


def parse_local_time(raw: str) -> dt.time:
    try:
        hour_str, minute_str = raw.split(":", 1)
        return dt.time(hour=int(hour_str), minute=int(minute_str))
    except (ValueError, TypeError):
        raise ValidationFailed(
            "local_time must be a 24-hour HH:MM value.", code="invalid_local_time"
        ) from None


def load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationFailed(
            f"'{name}' is not a known IANA timezone.", code="invalid_timezone"
        ) from None


def occurrences(
    schedule: MedicationSchedule,
    medication: Medication,
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[dt.datetime]:
    """UTC instants for this schedule inside ``[window_start, window_end)``."""
    if window_end <= window_start:
        return []
    if (window_end - window_start).days > MAX_GENERATION_DAYS:
        raise ValidationFailed(
            f"The requested range exceeds {MAX_GENERATION_DAYS} days.",
            code="range_too_large",
        )
    if schedule.status is not ScheduleStatus.ACTIVE:
        return []
    if medication.status is not MedicationStatus.ACTIVE:
        return []

    tz = load_timezone(schedule.timezone)
    at = parse_local_time(schedule.local_time)
    allowed_days = parse_days_of_week(schedule.days_of_week)

    # Widen the local scan by a day on each side: a UTC window boundary can fall
    # mid-day in the senior's zone.
    first_local_date = window_start.astimezone(tz).date() - dt.timedelta(days=1)
    last_local_date = window_end.astimezone(tz).date() + dt.timedelta(days=1)

    starts_on = _max_date(schedule.effective_from, medication.start_date)
    ends_on = _min_date(schedule.effective_to, medication.end_date)

    results: list[dt.datetime] = []
    current = first_local_date
    while current <= last_local_date:
        if _is_scheduled_on(current, allowed_days, starts_on, ends_on):
            # fold=0 resolves the ambiguous hour of a backwards DST shift to the
            # first occurrence, so the dose is never scheduled twice.
            local_dt = dt.datetime.combine(current, at, tzinfo=tz)
            instant = local_dt.astimezone(dt.UTC)
            if window_start <= instant < window_end:
                results.append(instant)
        current += dt.timedelta(days=1)

    return sorted(results)


def _is_scheduled_on(
    day: dt.date,
    allowed_days: set[int],
    starts_on: dt.date | None,
    ends_on: dt.date | None,
) -> bool:
    if day.isoweekday() not in allowed_days:
        return False
    if starts_on is not None and day < starts_on:
        return False
    return not (ends_on is not None and day > ends_on)


def _max_date(a: dt.date | None, b: dt.date | None) -> dt.date | None:
    if a and b:
        return max(a, b)
    return a or b


def _min_date(a: dt.date | None, b: dt.date | None) -> dt.date | None:
    if a and b:
        return min(a, b)
    return a or b
