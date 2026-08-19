"""What Gamira may do off her own bat, and what she may only propose.

Three separate limits meet in this file, and each one is a rule rather than a
prompt:

* A routine she picked up from a conversation is written ``suggested``, which
  every query for live reminders already excludes. It prompts nobody until a
  person accepts it.
* Nothing she volunteers arrives in the middle of the night. Nothing she
  volunteers is urgent — the urgent path is an alert, which she cannot raise —
  so a notice that would land at 3am waits until the morning.
* Whatever she tells the family about somebody, that person can read.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.ai import review as review_service
from app.core.config import Settings
from app.jobs.types import JobType
from app.models.audit import AuditLog
from app.models.care import NotificationDelivery, Reminder
from app.models.enums import NotificationType, ReminderStatus, ReminderType
from app.models.jobs import BackgroundJob
from tests.conftest import auth
from tests.factories import create_family, join, midday_timezone, start_live_session

# The fake provider proposes a reminder when the plants come up, and asks for
# the family only when Gamira said she would mention it. Both triggers are in
# `app/ai/provider.py`, so these transcripts exercise the real branches.
PLANTS = [
    {"role": "user", "text": "the plants are looking very dry again"},
    {"role": "assistant", "text": "Have they? When did you last water them?"},
    {"role": "user", "text": "I keep forgetting, it gets to the evening and I have not"},
    {"role": "assistant", "text": "That happens to everybody."},
]

LONELY_AND_TOLD = [
    {"role": "user", "text": "it has been very quiet here this week"},
    {"role": "assistant", "text": "Has it? Tell me about your week."},
    {"role": "user", "text": "nobody has been round. I am on my own most days"},
    {"role": "assistant", "text": "I'll let Anjali know you would like a call."},
]


async def _conversation(client, subject, turns):
    live = await start_live_session(client, subject=subject)
    await client.post(
        f"/api/v1/ai/live-sessions/{live['session_id']}/transcript",
        json={"turns": turns},
        headers=auth(subject),
    )
    await client.post(
        f"/api/v1/ai/live-sessions/{live['session_id']}/close", headers=auth(subject)
    )
    return live


async def _review(run_worker, live):
    return await run_worker(
        JobType.AI_CONVERSATION_REVIEW,
        payload={"conversation_id": live["conversation_id"]},
    )


# --------------------------------------------------------------------------- #
# Suggesting a reminder
# --------------------------------------------------------------------------- #


async def test_a_suggested_reminder_prompts_nobody_until_it_is_accepted(
    client, session, run_worker
):
    family = await create_family(client)
    live = await _conversation(client, family.owner, PLANTS)

    await _review(run_worker, live)

    reminder = (await session.execute(select(Reminder))).scalar_one()
    assert reminder.status is ReminderStatus.SUGGESTED
    assert reminder.title == "Water the plants"
    # Never a medication, and never attributed to a person who did not write it.
    assert reminder.type is ReminderType.OTHER
    assert reminder.created_by_user_id is None
    # Why she thought of it, and where she heard it — both checkable.
    assert reminder.suggestion_reason
    assert str(reminder.suggested_from_conversation_id) == live["conversation_id"]

    # The occurrences worker looks for active reminders; a suggestion is not one.
    await run_worker(JobType.REMINDER_OCCURRENCES)
    queued = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.type == NotificationType.REMINDER)
    )
    assert queued == 0


async def test_a_suggestion_is_recorded_as_the_assistant_s_doing(
    client, session, run_worker
):
    """`ActorType.AI` in the audit trail, so it is never mistaken for a person."""
    family = await create_family(client)
    live = await _conversation(client, family.owner, PLANTS)

    await _review(run_worker, live)

    entry = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "ai.reminder.suggested")
        )
    ).scalar_one()
    assert entry.actor_type == "ai"
    assert entry.actor_user_id is None


async def test_accepting_a_suggestion_makes_it_a_real_reminder(
    client, session, run_worker
):
    family = await create_family(client)
    live = await _conversation(client, family.owner, PLANTS)
    await _review(run_worker, live)
    listed = (
        await client.get(
            f"/api/v1/seniors/{family.senior_id}/reminders", headers=family.headers()
        )
    ).json()
    suggestion = next(row for row in listed if row["status"] == "suggested")
    assert suggestion["suggestion_reason"]

    accepted = await client.patch(
        f"/api/v1/reminders/{suggestion['id']}",
        json={"status": "active"},
        headers=family.headers(),
    )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"


async def test_dismissing_a_suggestion_leaves_nothing_behind(
    client, session, run_worker
):
    family = await create_family(client)
    live = await _conversation(client, family.owner, PLANTS)
    await _review(run_worker, live)
    listed = (
        await client.get(
            f"/api/v1/seniors/{family.senior_id}/reminders", headers=family.headers()
        )
    ).json()
    suggestion = next(row for row in listed if row["status"] == "suggested")

    await client.delete(
        f"/api/v1/reminders/{suggestion['id']}", headers=family.headers()
    )

    remaining = (
        await client.get(
            f"/api/v1/seniors/{family.senior_id}/reminders", headers=family.headers()
        )
    ).json()
    assert remaining == []


async def test_the_same_suggestion_twice_is_one_suggestion(
    client, session, run_worker
):
    """Mentioning the plants again next week should not add a second one."""
    family = await create_family(client)
    for _ in range(2):
        live = await _conversation(client, family.owner, PLANTS)
        await _review(run_worker, live)

    count = await session.scalar(select(func.count()).select_from(Reminder))
    assert count == 1


async def test_a_viewer_cannot_accept_a_suggestion(client, session, run_worker):
    """Accepting is a care action, and the policy for it is unchanged."""
    family = await create_family(client)
    await join(client, family, subject="a-viewer", role="viewer")
    live = await _conversation(client, family.owner, PLANTS)
    await _review(run_worker, live)
    reminder = (await session.execute(select(Reminder))).scalar_one()

    response = await client.patch(
        f"/api/v1/reminders/{reminder.id}",
        json={"status": "active"},
        headers=auth("a-viewer"),
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Quiet hours
# --------------------------------------------------------------------------- #


def _at(hour: int, tz: str = "Asia/Kolkata") -> dt.datetime:
    """A UTC instant that is `hour` o'clock where this person lives."""
    zone = ZoneInfo(tz)
    local = dt.datetime.now(zone).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return local.astimezone(dt.UTC)


def test_the_middle_of_the_night_is_quiet():
    settings = Settings()
    assert review_service.held_until("Asia/Kolkata", settings, _at(3)) is not None
    assert review_service.held_until("Asia/Kolkata", settings, _at(23)) is not None
    assert review_service.held_until("Asia/Kolkata", settings, _at(21)) is not None


def test_the_daytime_is_not():
    settings = Settings()
    for hour in (8, 12, 17, 20):
        assert review_service.held_until("Asia/Kolkata", settings, _at(hour)) is None


def test_a_held_notice_waits_for_the_morning_where_they_are():
    settings = Settings()
    zone = ZoneInfo("Asia/Kolkata")
    when = review_service.held_until("Asia/Kolkata", settings, _at(3))
    assert when is not None
    local = when.astimezone(zone)
    assert local.hour == settings.family_notice_quiet_end_hour
    # The same morning, not the next one: 3am and 8am are the same night.
    assert local.date() == _at(3).astimezone(zone).date()


def test_quiet_hours_can_be_switched_off():
    settings = Settings(
        family_notice_quiet_start_hour=0, family_notice_quiet_end_hour=0
    )
    assert review_service.held_until("Asia/Kolkata", settings, _at(3)) is None


def _quiet_right_now(worker_settings: Settings) -> None:
    """Force quiet hours to cover this exact moment, whatever it is.

    A previous version of this helper set start=0, end=23 to mean "their
    whole day," but held_until's window is half-open (start <= hour < end),
    so hour 23 itself was always excluded — and start == end is special-cased
    to mean quiet hours are *off* (`held_until`), so no fixed pair of hours
    can cover all 24 without a gap. This failed for real whenever a test
    happened to run at 23:00 in the family's timezone. Building the window
    around the current hour instead of trying to be exhaustive is exact by
    construction rather than exact for all but one hour a day.
    """
    now_hour = dt.datetime.now(ZoneInfo("Asia/Kolkata")).hour
    worker_settings.family_notice_quiet_start_hour = now_hour
    worker_settings.family_notice_quiet_end_hour = (now_hour + 1) % 24


async def test_a_notice_raised_at_night_is_held_rather_than_dropped(
    client, session, run_worker, worker_settings
):
    """Held, not dropped. The family should still hear about it, in the morning."""
    family = await create_family(client, owner="owner-a")
    await join(client, family, subject="owner-b", role="family")
    live = await _conversation(client, "owner-a", LONELY_AND_TOLD)
    _quiet_right_now(worker_settings)

    await _review(run_worker, live)

    sent = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.type == NotificationType.FAMILY_UPDATE)
    )
    assert sent == 0

    held = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.AI_FAMILY_NOTICE
            )
        )
    ).scalar_one()
    assert held.run_after > held.created_at
    assert held.payload["message"]


async def test_the_held_notice_sends_the_same_message_later(
    client, session, run_worker, worker_settings
):
    family = await create_family(client, owner="owner-a")
    await join(client, family, subject="owner-b", role="family")
    live = await _conversation(client, "owner-a", LONELY_AND_TOLD)
    _quiet_right_now(worker_settings)
    await _review(run_worker, live)
    held = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.AI_FAMILY_NOTICE
            )
        )
    ).scalar_one()

    await run_worker(JobType.AI_FAMILY_NOTICE, payload=dict(held.payload))

    notices = list(
        (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.type == NotificationType.FAMILY_UPDATE
                )
            )
        ).scalars()
    )
    assert notices
    assert all("call" in notice.title for notice in notices)


# --------------------------------------------------------------------------- #
# The person can read what was said about them
# --------------------------------------------------------------------------- #


async def test_the_person_can_read_what_was_sent_to_their_family(
    client, session, run_worker
):
    """"Openly" has to survive the conversation ending."""
    # Quiet hours (21:00-08:00) would defer this notice on a default-timezone
    # family; the test expects immediate delivery.
    family = await create_family(client, owner="owner-a", timezone=midday_timezone())
    await join(client, family, subject="owner-b", role="family")
    await join(client, family, subject="the-senior", role="viewer")
    live = await _conversation(client, "owner-a", LONELY_AND_TOLD)
    await _review(run_worker, live)

    response = await client.get(
        f"/api/v1/ai/seniors/{family.senior_id}/family-notices",
        headers=auth("the-senior"),
    )

    assert response.status_code == 200
    notices = response.json()
    assert len(notices) == 1
    assert "call" in notices[0]["title"]
    # One notice, however many people it reached — grouped back into the one
    # thing that was actually said.
    assert notices[0]["recipients"] >= 1


async def test_another_family_cannot_read_those_notices(client, run_worker):
    family = await create_family(client, owner="owner-a")
    await create_family(client, owner="outsider", name="Other")

    response = await client.get(
        f"/api/v1/ai/seniors/{family.senior_id}/family-notices",
        headers=auth("outsider"),
    )

    assert response.status_code == 404


async def test_nothing_sent_means_nothing_to_read(client):
    family = await create_family(client)
    response = await client.get(
        f"/api/v1/ai/seniors/{family.senior_id}/family-notices",
        headers=family.headers(),
    )
    assert response.json() == []


async def test_an_unknown_person_has_no_notices(client):
    family = await create_family(client)
    response = await client.get(
        f"/api/v1/ai/seniors/{uuid.uuid4()}/family-notices", headers=family.headers()
    )
    assert response.status_code == 404
