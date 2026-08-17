"""Timezone and daylight-saving behaviour of schedule expansion."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.errors import ValidationFailed
from app.models.enums import MedicationStatus, ScheduleStatus
from app.models.medication import Medication, MedicationSchedule
from app.services import scheduling


def _schedule(**overrides) -> MedicationSchedule:  # type: ignore[no-untyped-def]
    # Column defaults are applied at INSERT, so an in-memory object used
    # directly by the expansion code must state its status explicitly.
    defaults = {
        "local_time": "08:00",
        "timezone": "Asia/Kolkata",
        "days_of_week": "",
        "late_after_minutes": 30,
        "missed_after_minutes": 120,
        "status": ScheduleStatus.ACTIVE,
    }
    return MedicationSchedule(**{**defaults, **overrides})


def _medication(**overrides) -> Medication:  # type: ignore[no-untyped-def]
    defaults = {"name": "Amlodipine", "status": MedicationStatus.ACTIVE}
    return Medication(**{**defaults, **overrides})


def test_a_daily_schedule_produces_one_occurrence_per_day():
    start = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
    end = start + dt.timedelta(days=7)

    results = scheduling.occurrences(
        _schedule(), _medication(), window_start=start, window_end=end
    )

    assert len(results) == 7


def test_selected_weekdays_are_honoured():
    start = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)  # a Monday
    end = start + dt.timedelta(days=7)

    results = scheduling.occurrences(
        _schedule(days_of_week="1,3,5"),
        _medication(),
        window_start=start,
        window_end=end,
    )

    assert len(results) == 3


def test_the_local_dose_time_survives_a_daylight_saving_change():
    """An 08:00 dose in New York stays at 08:00 across the March DST shift.

    Before the shift 08:00 EST is 13:00 UTC; after it 08:00 EDT is 12:00 UTC.
    A schedule stored in UTC would silently move the reminder by an hour.
    """
    tz = "America/New_York"
    start = dt.datetime(2026, 3, 6, tzinfo=dt.UTC)
    end = dt.datetime(2026, 3, 12, tzinfo=dt.UTC)

    results = scheduling.occurrences(
        _schedule(timezone=tz), _medication(), window_start=start, window_end=end
    )

    from zoneinfo import ZoneInfo

    local_times = {
        instant.astimezone(ZoneInfo(tz)).strftime("%H:%M") for instant in results
    }
    assert local_times == {"08:00"}

    utc_hours = {instant.hour for instant in results}
    # The UTC hour genuinely changes; the wall-clock time does not.
    assert utc_hours == {12, 13}


def test_a_paused_schedule_produces_nothing():
    start = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)

    results = scheduling.occurrences(
        _schedule(status=ScheduleStatus.PAUSED),
        _medication(),
        window_start=start,
        window_end=start + dt.timedelta(days=7),
    )

    assert results == []


def test_effective_dates_bound_the_expansion():
    start = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)

    results = scheduling.occurrences(
        _schedule(effective_from=dt.date(2026, 3, 3), effective_to=dt.date(2026, 3, 5)),
        _medication(),
        window_start=start,
        window_end=start + dt.timedelta(days=10),
    )

    assert len(results) == 3


def test_an_unreasonably_large_window_is_refused():
    start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    with pytest.raises(ValidationFailed) as excinfo:
        scheduling.occurrences(
            _schedule(),
            _medication(),
            window_start=start,
            window_end=start + dt.timedelta(days=400),
        )

    assert excinfo.value.code == "range_too_large"


def test_an_unknown_timezone_is_rejected():
    with pytest.raises(ValidationFailed) as excinfo:
        scheduling.load_timezone("Mars/Olympus_Mons")

    assert excinfo.value.code == "invalid_timezone"
