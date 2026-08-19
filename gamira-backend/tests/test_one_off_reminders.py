"""«Remind me in five minutes» — the thing a companion is asked for most.

Reminders were daily-only, so this failed in the worst way available: the model
either got an argument rejected and said nothing useful, or — if it worked out a
clock time itself — set a **permanent daily alarm** at that minute. A five-minute
timer that goes off every day forever is worse than one that never goes off.

These tests are mostly about that second failure. Firing once is easy; not
firing again is the point.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.care import NotificationDelivery, Reminder
from app.models.enums import NotificationType, ReminderStatus, ReminderType
from tests.factories import (
    call,
    call_tools,
    create_family,
    join,
    link_senior_account,
    start_live_session,
)


async def _senior(client, session, *, subject: str = "the-senior"):
    family = await create_family(client)
    await join(client, family, subject=subject, role="viewer")
    await link_senior_account(session, family.senior_id, subject)
    return family, subject


async def _ask(client, session, *, subject: str, **arguments):
    live = await start_live_session(client, subject=subject)
    return await call_tools(
        client,
        session_id=live["session_id"],
        subject=subject,
        calls=[call("create_reminder", "fc-1", proposed_by="them", **arguments)],
    )


async def _reminder_notices(session) -> list[NotificationDelivery]:
    """Every reminder notification, across every recipient."""
    return list(
        (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.type == NotificationType.REMINDER
                )
            )
        ).scalars()
    )


async def _live_reminders(session) -> list[Reminder]:
    """The rows the occurrence sweep will look at next time it runs.

    This is the honest way to prove "it never fires again": the sweep selects
    on ``status == ACTIVE``, so a completed one-off is not merely deduplicated
    tomorrow — it is not a candidate at all. Running the sweep three times in
    the same minute would prove nothing, because the dedupe key would stop the
    second and third anyway.
    """
    return list(
        (
            await session.execute(
                select(Reminder).where(Reminder.status == ReminderStatus.ACTIVE)
            )
        ).scalars()
    )


async def _only_reminder(session) -> Reminder:
    rows = (await session.execute(select(Reminder))).scalars().all()
    assert len(rows) == 1, f"expected one reminder, found {len(rows)}"
    return rows[0]


# --------------------------------------------------------------------------- #
# Setting one
# --------------------------------------------------------------------------- #


async def test_in_five_minutes_is_set_for_five_minutes_from_now(client, session):
    family, subject = await _senior(client, session)
    before = utcnow()

    body = await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="once",
        in_minutes=5,
    )
    assert body["results"][0]["ok"] is True
    # They asked for it out loud, so it happens — no dialog in front of what
    # somebody has just requested.
    assert body["results"][0]["requires_confirmation"] is False

    reminder = await _only_reminder(session)
    assert reminder.status is ReminderStatus.ACTIVE
    assert reminder.type is ReminderType.OTHER
    assert reminder.effective_from == reminder.effective_to

    # The backend did the arithmetic, and did it in *their* timezone rather
    # than in UTC — which for the seeded person is five and a half hours out,
    # so a reminder computed in UTC would land in the middle of the night.
    hour, minute = (int(part) for part in reminder.local_time.split(":"))
    expected = (before + dt.timedelta(minutes=5)).astimezone(
        ZoneInfo(reminder.timezone)
    )
    assert abs(hour * 60 + minute - (expected.hour * 60 + expected.minute)) <= 1


async def test_the_model_is_never_asked_to_do_the_clock_arithmetic(client, session):
    """It gives a number of minutes; the backend owns the clock.

    The clock tool runs in the browser, so a reminder that depended on the model
    having called it first would work or not depending on the shape of the
    conversation.
    """
    from app.ai.tools import CATALOGUE

    spec = CATALOGUE["create_reminder"]
    assert "in_minutes" in spec.parameters["properties"]
    assert spec.parameters["properties"]["in_minutes"]["type"] == "integer"
    assert set(spec.parameters["required"]) == {"proposed_by", "title", "repeat"}


async def test_a_daily_reminder_is_still_daily(client, session):
    family, subject = await _senior(client, session)

    await _ask(
        client,
        session,
        subject=subject,
        title="water the plants",
        repeat="daily",
        local_time="09:00",
    )

    reminder = await _only_reminder(session)
    assert reminder.local_time == "09:00"
    assert reminder.effective_from is None
    assert reminder.effective_to is None


# --------------------------------------------------------------------------- #
# Firing once, and only once
# --------------------------------------------------------------------------- #


async def test_a_one_off_fires_and_stays_active_through_its_day(
    client, session, run_worker
):
    """Completing it the instant it fires used to race the Parent App's own
    proactive voice nudge, which decides *only* from ``status == active`` and
    checks on its own schedule. A one-off fired here and completed in the same
    breath was routinely marked done before Gamira's own check next ran, so a
    reminder nobody was ever told about out loud read, from her side, as
    already handled. It stays active — and so still nudgeable — for the rest
    of its day; only once that day is behind it does it complete (see the next
    test).
    """
    family, subject = await _senior(client, session)
    await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="once",
        in_minutes=1,
    )
    reminder = await _only_reminder(session)
    # Bring its moment forward rather than waiting a minute for it.
    reminder.local_time = utcnow().strftime("%H:%M")
    reminder.effective_from = reminder.effective_to = utcnow().date()
    reminder.timezone = "UTC"
    await session.flush()
    await session.commit()

    await run_worker(JobType.REMINDER_OCCURRENCES)

    await session.refresh(reminder)
    assert reminder.status is ReminderStatus.ACTIVE
    assert reminder.last_completed_at is None
    assert await _reminder_notices(session), "it should actually have gone off"

    # Sweeping again later the same day changes nothing — "it already fired
    # once today" is not "its day is over".
    await run_worker(JobType.REMINDER_OCCURRENCES)
    await session.refresh(reminder)
    assert reminder.status is ReminderStatus.ACTIVE


async def test_a_one_off_completes_once_its_day_has_passed(client, session, run_worker):
    family, subject = await _senior(client, session)
    await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="once",
        in_minutes=1,
    )
    reminder = await _only_reminder(session)
    reminder.local_time = utcnow().strftime("%H:%M")
    yesterday = (utcnow() - dt.timedelta(days=1)).date()
    reminder.effective_from = reminder.effective_to = yesterday
    reminder.timezone = "UTC"
    await session.flush()
    await session.commit()

    await run_worker(JobType.REMINDER_OCCURRENCES)

    await session.refresh(reminder)
    assert reminder.status is ReminderStatus.COMPLETED
    assert reminder.last_completed_at is not None


async def test_a_one_off_never_fires_again(client, session, run_worker):
    """The failure this feature exists to avoid."""
    family, subject = await _senior(client, session)
    await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="once",
        in_minutes=1,
    )
    reminder = await _only_reminder(session)
    reminder.local_time = utcnow().strftime("%H:%M")
    reminder.effective_from = reminder.effective_to = utcnow().date()
    reminder.timezone = "UTC"
    await session.flush()
    await session.commit()

    await run_worker(JobType.REMINDER_OCCURRENCES)
    fired = len(await _reminder_notices(session))
    assert fired

    # However often the sweep runs later the same day, it is not fired again —
    # the per-occurrence dedupe key stops it, same as ever.
    await run_worker(JobType.REMINDER_OCCURRENCES)
    await run_worker(JobType.REMINDER_OCCURRENCES)
    assert len(await _reminder_notices(session)) == fired

    # Once its day is behind it, it is done — not a candidate the day after,
    # which a repeated sweep within the same minute could never show.
    reminder.effective_from = reminder.effective_to = (
        utcnow() - dt.timedelta(days=1)
    ).date()
    await session.flush()
    await session.commit()

    await run_worker(JobType.REMINDER_OCCURRENCES)
    assert len(await _reminder_notices(session)) == fired
    assert await _live_reminders(session) == []


async def test_a_daily_reminder_is_not_completed_by_firing(client, session, run_worker):
    family, subject = await _senior(client, session)
    await _ask(
        client,
        session,
        subject=subject,
        title="water the plants",
        repeat="daily",
        local_time="09:00",
    )
    reminder = await _only_reminder(session)
    reminder.local_time = utcnow().strftime("%H:%M")
    reminder.timezone = "UTC"
    await session.flush()
    await session.commit()

    await run_worker(JobType.REMINDER_OCCURRENCES)

    await session.refresh(reminder)
    assert reminder.status is ReminderStatus.ACTIVE
    assert await _live_reminders(session) == [reminder]


# --------------------------------------------------------------------------- #
# Saying when, exactly once
# --------------------------------------------------------------------------- #


async def test_saying_neither_when_is_refused_by_name(client, session):
    family, subject = await _senior(client, session)

    body = await _ask(
        client, session, subject=subject, title="drink some water", repeat="once"
    )
    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["error"] == "invalid_arguments"
    # Named, so the model can fix it and ask again rather than give up.
    assert result["response"]["field"] == "local_time"


async def test_saying_both_whens_is_refused(client, session):
    """Ambiguous about which one they actually said, so neither is guessed."""
    family, subject = await _senior(client, session)

    body = await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="once",
        in_minutes=5,
        local_time="09:00",
    )
    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["field"] == "in_minutes"

    assert (await session.execute(select(Reminder))).scalars().first() is None


async def test_in_minutes_cannot_be_daily(client, session):
    """"In ten minutes, every day" is not a thing anybody means."""
    family, subject = await _senior(client, session)

    body = await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="daily",
        in_minutes=10,
    )
    result = body["results"][0]
    assert result["ok"] is False
    assert result["response"]["field"] == "repeat"


async def test_a_refused_reminder_is_refused_before_anybody_is_asked(client, session):
    """No confirmation for something that was never going to work."""
    family, subject = await _senior(client, session)

    body = await _ask(
        client,
        session,
        subject=subject,
        title="drink some water",
        repeat="once",
        in_minutes=5,
        local_time="09:00",
    )
    assert body["results"][0]["requires_confirmation"] is False
    assert body["results"][0]["decision_id"] is None
