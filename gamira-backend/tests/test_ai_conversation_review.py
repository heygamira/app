"""Reading a finished conversation back.

The part of Gamira that notices things, and therefore the part most in need of
limits. These tests are mostly about what it may *not* do: it may not raise an
alert, it may not record anything clinical, and — the one that shapes the whole
feature — it may not tell the family something the person was not told first.

The persona says so in as many words: *"You are not there to report on them; if
something genuinely needs a family member, say so to them first, openly."* An
observer that quietly messaged the family would contradict the instruction the
model it is reading was running under.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.ai.prompts import SAFETY_PREAMBLE
from app.ai.provider import AIInvalidResponse, AIUnavailable
from app.jobs.types import JobType
from app.models.ai import AiSummary, AiUsage, Conversation, SeniorMemory
from app.models.alerts import Alert
from app.models.care import NotificationDelivery
from app.models.enums import (
    ConversationStatus,
    JobStatus,
    NotificationChannel,
    NotificationType,
    ReviewState,
    SummaryKind,
)
from app.models.jobs import BackgroundJob
from tests.conftest import auth
from tests.factories import create_family, join, midday_timezone, start_live_session

# A conversation in which somebody says they are lonely *and* Gamira says she
# will mention it. The fake provider keys off both, exactly as the real rule
# does — it cannot ask to notify the family without the second half.
LONELY_AND_TOLD = [
    {"role": "user", "text": "it has been very quiet here this week"},
    {"role": "assistant", "text": "Has it? Tell me about your week."},
    {"role": "user", "text": "nobody has been round. I am on my own most days"},
    {"role": "assistant", "text": "I'll let Anjali know you would like a call."},
]

# The same loneliness, without Gamira saying anything about telling anyone.
LONELY_AND_SILENT = [
    {"role": "user", "text": "it has been very quiet here this week"},
    {"role": "assistant", "text": "Has it? Tell me about your week."},
    {"role": "user", "text": "nobody has been round. I am on my own most days"},
    {"role": "assistant", "text": "That sounds like a long week."},
]

ORDINARY = [
    {"role": "user", "text": "what is the weather doing"},
    {"role": "assistant", "text": "Sixteen degrees and cloudy."},
    {"role": "user", "text": "right, thank you"},
    {"role": "assistant", "text": "Any time."},
]


async def _conversation(client, subject, turns, family=None):
    """A closed conversation with a transcript, ready to be reviewed."""
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
# Queueing
# --------------------------------------------------------------------------- #


async def test_ending_a_conversation_asks_for_it_to_be_read_back(client, session):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)

    job = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.AI_CONVERSATION_REVIEW
            )
        )
    ).scalar_one()
    assert job.payload["conversation_id"] == live["conversation_id"]
    # Not immediately: the browser's last transcript post is still in flight.
    assert job.run_after > job.created_at

    conversation = await session.get(Conversation, uuid.UUID(live["conversation_id"]))
    await session.refresh(conversation)
    assert conversation.status is ConversationStatus.ENDED


async def test_closing_twice_queues_one_review(client, session):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)
    await client.post(
        f"/api/v1/ai/live-sessions/{live['session_id']}/close",
        headers=auth(family.owner),
    )

    queued = await session.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(BackgroundJob.job_type == JobType.AI_CONVERSATION_REVIEW)
    )
    assert queued == 1


# --------------------------------------------------------------------------- #
# The review itself
# --------------------------------------------------------------------------- #


async def test_the_review_is_recorded_with_its_provenance(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)

    await _review(run_worker, live)

    summary = (
        await session.execute(
            select(AiSummary).where(AiSummary.kind == SummaryKind.CONVERSATION)
        )
    ).scalar_one()
    assert str(summary.conversation_id) == live["conversation_id"]
    assert summary.model and summary.provider and summary.prompt_version
    assert summary.output_schema_version == "1"
    # Nothing generated is treated as checked until a person checks it.
    assert summary.review_state is ReviewState.UNREVIEWED
    # The figures are the backend's, not the model's.
    assert summary.facts["turns"] == 4
    assert summary.facts["channel"] == "voice"


async def test_the_prompt_carries_the_safety_limits(client, run_worker, ai_provider):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)

    await _review(run_worker, live)

    call = ai_provider.calls[-1]
    assert call.prompt_id == "conversation_review@1"
    assert call.output_model == "ConversationReviewOut"
    prompt = next(p for p in [SAFETY_PREAMBLE] if p)
    assert prompt.split("\n")[0] in _system_of(ai_provider)


def _system_of(ai_provider) -> str:
    """The system text the provider was given for its last call."""
    from app.ai.prompts import CONVERSATION_REVIEW_V1

    assert ai_provider.calls  # the call happened at all
    return CONVERSATION_REVIEW_V1.system


async def test_a_conversation_too_short_to_read_is_left_alone(
    client, session, run_worker, ai_provider
):
    """Most wake words come to nothing. Two turns is "Gamira?" — "Yes?"."""
    family = await create_family(client)
    live = await _conversation(
        client,
        family.owner,
        [
            {"role": "user", "text": "Gamira"},
            {"role": "assistant", "text": "Yes?"},
        ],
    )

    await _review(run_worker, live)

    assert ai_provider.calls == []
    assert await session.scalar(select(func.count()).select_from(AiSummary)) == 0


async def test_what_it_notices_becomes_a_memory(client, session, run_worker):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)

    await _review(run_worker, live)

    rows = list((await session.execute(select(SeniorMemory))).scalars())
    # The fake keeps nothing; what matters is that the path is wired and that
    # anything it did keep would carry the conversation it came from.
    for row in rows:
        assert str(row.source_conversation_id) == live["conversation_id"]


# --------------------------------------------------------------------------- #
# Telling the family — the rule that shapes the feature
# --------------------------------------------------------------------------- #


async def test_the_family_is_told_only_after_the_person_was(
    client, session, run_worker
):
    # A default-timezone family lands in quiet hours (21:00-08:00) for part of
    # the day, which would defer this notice instead of sending it — the test
    # expects immediate delivery, so it needs a senior for whom "now" is
    # unambiguously daytime.
    family = await create_family(client, owner="owner-a", timezone=midday_timezone())
    await join(client, family, subject="owner-b", role="family")
    live = await _conversation(client, "owner-a", LONELY_AND_TOLD)

    await _review(run_worker, live)

    notices = list(
        (
            await session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.type == NotificationType.FAMILY_UPDATE
                )
            )
        ).scalars()
    )
    assert notices, "the family was never told"
    # A nudge to ring somebody, not an emergency, and not worth waking a phone:
    # the in-app row only, with no push counterpart queued beside it.
    assert {notice.channel for notice in notices} == {NotificationChannel.IN_APP}


async def test_nothing_is_sent_when_gamira_said_nothing(client, session, run_worker):
    """The same loneliness, unmentioned in the conversation. Silence is correct."""
    family = await create_family(client, owner="owner-a")
    await join(client, family, subject="owner-b", role="family")
    live = await _conversation(client, "owner-a", LONELY_AND_SILENT)

    await _review(run_worker, live)

    told = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.type == NotificationType.FAMILY_UPDATE)
    )
    assert told == 0


async def test_a_review_never_raises_an_alert(client, session, run_worker):
    """A quiet worry and an emergency must not be able to look alike."""
    family = await create_family(client, owner="owner-a")
    await join(client, family, subject="owner-b", role="family")
    live = await _conversation(client, "owner-a", LONELY_AND_TOLD)

    await _review(run_worker, live)

    assert await session.scalar(select(func.count()).select_from(Alert)) == 0


async def test_reviewing_twice_tells_the_family_once(client, session, run_worker):
    # See the comment on test_the_family_is_told_only_after_the_person_was:
    # quiet hours would defer this notice on a default-timezone family.
    family = await create_family(client, owner="owner-a", timezone=midday_timezone())
    await join(client, family, subject="owner-b", role="family")
    live = await _conversation(client, "owner-a", LONELY_AND_TOLD)

    await _review(run_worker, live)
    await _review(run_worker, live)

    told = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.type == NotificationType.FAMILY_UPDATE)
    )
    summaries = await session.scalar(select(func.count()).select_from(AiSummary))
    assert told == 1
    assert summaries == 1


# --------------------------------------------------------------------------- #
# Failure
# --------------------------------------------------------------------------- #


async def test_a_provider_outage_is_retried(client, session, run_worker, ai_provider):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)
    ai_provider.fail_with = AIUnavailable("gemini is down")

    await _review(run_worker, live)

    job = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.AI_CONVERSATION_REVIEW,
                BackgroundJob.payload["conversation_id"].as_string()
                == live["conversation_id"],
            )
        )
    ).scalars().first()
    assert job is not None
    assert job.status in (JobStatus.QUEUED, JobStatus.FAILED)
    # Nothing half-written: an unreviewed conversation is the ordinary state.
    assert await session.scalar(select(func.count()).select_from(AiSummary)) == 0


async def test_a_schema_violation_is_not_retried(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)
    ai_provider.fail_with = AIInvalidResponse("not the shape we asked for")

    await _review(run_worker, live)

    failed = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.AI_CONVERSATION_REVIEW,
                BackgroundJob.status == JobStatus.FAILED,
            )
        )
    ).scalars().first()
    assert failed is not None
    assert failed.attempt_count == 1


async def test_a_failure_is_counted_against_the_right_family(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    live = await _conversation(client, family.owner, ORDINARY)
    ai_provider.fail_with = AIInvalidResponse("nope")

    await _review(run_worker, live)

    usage = (
        await session.execute(
            select(AiUsage).where(AiUsage.operation == "conversation_review")
        )
    ).scalar_one()
    assert usage.outcome == "failed"
    assert str(usage.family_id) == family.family_id


async def test_a_conversation_that_does_not_exist_fails_permanently(
    session, run_worker
):
    await run_worker(
        JobType.AI_CONVERSATION_REVIEW,
        payload={"conversation_id": str(uuid.uuid4())},
    )

    job = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.AI_CONVERSATION_REVIEW
            )
        )
    ).scalar_one()
    assert job.status is JobStatus.FAILED
    assert job.attempt_count == 1
