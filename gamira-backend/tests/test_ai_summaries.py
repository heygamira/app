"""The weekly care summary.

The point of these tests is the division of labour: the backend counts, the
model words. A figure the model produced that the backend did not count would
be a bug, and a model outage must cost the wording and nothing else.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.ai.provider import AIInvalidResponse, AIUnavailable
from app.db.base import utcnow
from app.jobs.types import JobType
from app.models.ai import AiSummary, AiUsage
from app.models.enums import JobStatus, ReviewState
from app.models.jobs import BackgroundJob
from tests.conftest import auth
from tests.factories import add_medication, create_family, join, list_doses


async def _request(client, family, actor: str | None = None, **body):
    response = await client.post(
        "/api/v1/ai/summaries",
        json={"senior_id": family.senior_id, **body},
        headers=family.headers(actor),
    )
    return response


async def test_the_figures_exist_before_any_model_runs(client, session, ai_provider):
    family = await create_family(client)
    response = await _request(client, family)

    assert response.status_code == 202
    body = response.json()
    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))

    # Counted synchronously; the job has not run yet.
    assert summary is not None
    assert summary.facts["senior_name"] == "Vikram"
    assert summary.content is None
    assert ai_provider.calls == []


async def test_the_summary_reports_the_counted_dose_figures(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    await add_medication(client, family)
    await run_worker()
    dose = (await list_doses(client, family))[0]
    await client.post(
        f"/api/v1/dose-events/{dose['id']}/taken", json={}, headers=family.headers()
    )

    body = (
        await _request(client, family, period_start=_today(), period_end=_today())
    ).json()
    await run_worker()

    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))
    await session.refresh(summary)

    assert summary.facts["doses"]["taken"] == 1
    assert summary.content is not None
    # The fake provider builds its wording from the figures it was given, so
    # this is a real assertion about the pipeline rather than a canned string.
    assert "1 of" in summary.content


async def test_a_summary_records_its_full_provenance(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    body = (await _request(client, family)).json()
    await run_worker()

    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))
    await session.refresh(summary)

    assert summary.period_start < summary.period_end
    assert summary.source_data_version
    assert summary.source_reference["tables"]
    assert summary.model == ai_provider.model
    assert summary.provider == "fake"
    assert summary.prompt_version == "weekly_care_summary@1"
    assert summary.output_schema_version == "1"
    assert summary.generated_at is not None
    # Nothing Gamira generates starts out reviewed.
    assert summary.review_state is ReviewState.UNREVIEWED


async def test_a_thin_week_carries_a_freshness_warning(client, session, run_worker):
    family = await create_family(client)
    body = (await _request(client, family)).json()

    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))
    warning = summary.data_freshness_warning
    assert warning is not None
    assert "No health readings" in warning
    assert "No medication schedule" in warning

    await run_worker()
    await session.refresh(summary)
    # The warning survives generation: the model cannot word it away.
    assert summary.data_freshness_warning == warning


async def test_the_prompt_carries_the_warning_the_model_must_repeat(
    client, run_worker, ai_provider
):
    family = await create_family(client)
    await _request(client, family)
    await run_worker()

    assert len(ai_provider.calls) == 1
    rendered = ai_provider.calls[0].rendered
    assert "Data note that must appear in your answer" in rendered


async def test_a_provider_outage_leaves_a_retryable_job_and_the_figures(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    body = (await _request(client, family)).json()
    ai_provider.fail_with = AIUnavailable("the model is down")

    await run_worker()

    job = await session.get(BackgroundJob, uuid.UUID(body["job_id"]))
    await session.refresh(job)
    assert job.status is JobStatus.QUEUED
    assert job.last_error_code == "ai_unavailable"

    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))
    await session.refresh(summary)
    # The figures are still there. That is the whole design.
    assert summary.facts["senior_name"] == "Vikram"
    assert summary.content is None

    usage = (await session.execute(select(AiUsage))).scalars().all()
    assert usage, "a failed call is still a call worth accounting for"
    assert all(row.outcome == "failed" for row in usage)
    # A code, not the provider's message — that could carry the prompt.
    assert {row.error_code for row in usage} == {"ai_unavailable"}
    assert all("the model is down" not in str(row.error_code) for row in usage)


async def test_the_retry_succeeds_once_the_provider_returns(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    body = (await _request(client, family)).json()
    ai_provider.fail_with = AIUnavailable("temporary")
    await run_worker()

    job = await session.get(BackgroundJob, uuid.UUID(body["job_id"]))
    await session.refresh(job)
    assert job.status is JobStatus.QUEUED

    ai_provider.fail_with = None
    job.run_after = utcnow()
    await session.commit()

    await run_worker()

    await session.refresh(job)
    assert job.status is JobStatus.SUCCEEDED
    assert job.result_reference == {"type": "ai_summary", "id": body["summary_id"]}

    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))
    await session.refresh(summary)
    assert summary.content is not None


async def test_a_schema_violation_is_not_retried(
    client, session, run_worker, ai_provider
):
    """A reply that will not validate will not validate on the fifth attempt."""
    family = await create_family(client)
    body = (await _request(client, family)).json()
    ai_provider.fail_with = AIInvalidResponse("wrong shape")

    await run_worker()

    job = await session.get(BackgroundJob, uuid.UUID(body["job_id"]))
    await session.refresh(job)
    assert job.status is JobStatus.FAILED
    assert job.attempt_count == 1
    assert job.last_error_code == "ai_invalid_response"


async def test_requesting_the_same_period_twice_reuses_one_summary(
    client, session, run_worker
):
    family = await create_family(client)
    first = (await _request(client, family)).json()
    second = (await _request(client, family)).json()

    assert first["summary_id"] == second["summary_id"]
    count = await session.scalar(select(func.count()).select_from(AiSummary))
    assert count == 1


async def test_another_family_cannot_request_or_read_a_summary(client):
    family = await create_family(client, owner="owner-a")
    await create_family(client, owner="owner-b", name="Other")
    body = (await _request(client, family)).json()

    requested = await _request(client, family, actor="owner-b")
    # 404, not 403: an outsider must not learn this person exists.
    assert requested.status_code == 404

    read = await client.get(
        f"/api/v1/ai/summaries/{body['summary_id']}", headers=auth("owner-b")
    )
    assert read.status_code in (403, 404)


async def test_a_viewer_may_read_the_summary_of_their_own_family(client):
    family = await create_family(client)
    await join(client, family, subject="a-viewer", role="viewer")
    body = (await _request(client, family)).json()

    read = await client.get(
        f"/api/v1/ai/summaries/{body['summary_id']}", headers=auth("a-viewer")
    )
    assert read.status_code == 200


async def test_the_job_endpoint_reports_a_safe_error_code(
    client, session, run_worker, ai_provider
):
    family = await create_family(client)
    body = (await _request(client, family)).json()
    ai_provider.fail_with = AIUnavailable("connection refused to 10.0.0.4:443")

    await run_worker()

    job = (
        await client.get(f"/api/v1/ai/jobs/{body['job_id']}", headers=family.headers())
    ).json()

    assert job["status"] == "queued"
    assert job["last_error_code"] == "ai_unavailable"
    # Nothing about the provider's internals reaches the client.
    assert "10.0.0.4" not in str(job)


async def test_another_family_cannot_read_a_job(client):
    family = await create_family(client, owner="owner-a")
    await create_family(client, owner="owner-b", name="Other")
    body = (await _request(client, family)).json()

    response = await client.get(
        f"/api/v1/ai/jobs/{body['job_id']}", headers=auth("owner-b")
    )
    assert response.status_code in (403, 404)


async def test_an_impossible_period_is_rejected(client):
    family = await create_family(client)
    response = await _request(
        client, family, period_start="2026-08-10", period_end="2026-08-01"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_period"


async def test_a_too_long_period_is_rejected(client):
    family = await create_family(client)
    response = await _request(
        client, family, period_start="2020-01-01", period_end="2026-01-01"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "period_too_long"


async def test_the_facts_never_contain_a_health_value(client, session):
    """Freshness and counts only. A summary is not a chart of somebody's blood."""
    family = await create_family(client)
    await client.post(
        f"/api/v1/seniors/{family.senior_id}/health-readings",
        json={
            "metric": "heart_rate",
            "value": 137,
            "unit": "bpm",
            "source": "manual_family",
            "measured_at": utcnow().isoformat(),
        },
        headers=family.headers(),
    )

    body = (
        await _request(client, family, period_start=_today(), period_end=_today())
    ).json()
    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))

    assert summary.facts["health"]["total_readings"] == 1
    assert "137" not in str(summary.facts["health"])


async def test_upcoming_doses_are_not_counted_as_missing_responses(
    client, session, run_worker
):
    family = await create_family(client)
    await add_medication(client, family, local_time="23:59")
    await run_worker()

    body = (
        await _request(client, family, period_start=_today(), period_end=_today())
    ).json()
    summary = await session.get(AiSummary, uuid.UUID(body["summary_id"]))
    doses = summary.facts["doses"]

    # A dose still ahead of now this evening is upcoming, not unanswered.
    assert doses["upcoming"] >= 1
    assert doses["missed"] == 0
    assert doses["late"] == 0


async def test_the_scheduler_registers_the_live_session_expiry_sweep(
    client, session, run_worker
):
    await run_worker(JobType.LIVE_SESSION_EXPIRY)
    job = (
        await session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job_type == JobType.LIVE_SESSION_EXPIRY
            )
        )
    ).scalars().one()
    assert job.status is JobStatus.SUCCEEDED


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()
