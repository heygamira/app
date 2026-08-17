"""Test fixtures.

Each test gets its own SQLite database file so the suite runs without Docker.
The schema is created from ``Base.metadata``; ``test_migrations.py`` separately
proves the Alembic migration produces the same tables.

Two things every test gets for free, and both matter:

* ``run_worker`` — a real :class:`app.jobs.runner.Worker` against the same
  database, so a test drives the actual queue, the actual claim path and the
  actual handlers rather than calling a service function directly.
* Fake providers for AI, Live tokens and push. No test in this suite reaches a
  paid service, and the fakes are installed before any app code can build a
  real one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_MODE", "dev")
os.environ.setdefault("LOG_FORMAT", "console")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Belt and braces: the fixtures below install fakes anyway, but a stray import
# order must not be able to reach for a real provider.
os.environ.setdefault("AI_PROVIDER", "fake")
os.environ.setdefault("FCM_PROVIDER", "fake")
# The retry *rules* are what the suite tests, not the waiting.
os.environ.setdefault("AI_RETRY_BASE_SECONDS", "0")

from app.ai.live import FakeLiveTokenMinter, set_token_minter
from app.ai.provider import FakeAIProvider, set_ai_provider
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_session
from app.jobs.queue import DatabaseJobQueue
from app.jobs.runner import Worker
from app.main import create_app
from app.notifications.provider import FakePushProvider, set_push_provider


@pytest.fixture
async def engine(tmp_path):  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
async def sessionmaker(engine) -> async_sessionmaker[AsyncSession]:  # type: ignore[no-untyped-def]
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(sessionmaker) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        yield session
        await session.commit()


@pytest.fixture
def ai_provider() -> AsyncIterator[FakeAIProvider]:  # type: ignore[misc]
    """The deterministic AI provider, installed for the whole test."""
    provider = FakeAIProvider()
    set_ai_provider(provider)
    yield provider
    set_ai_provider(None)


@pytest.fixture
def token_minter() -> AsyncIterator[FakeLiveTokenMinter]:  # type: ignore[misc]
    minter = FakeLiveTokenMinter()
    set_token_minter(minter)
    yield minter
    set_token_minter(None)


@pytest.fixture
def push_provider() -> AsyncIterator[FakePushProvider]:  # type: ignore[misc]
    provider = FakePushProvider()
    set_push_provider(provider)
    yield provider
    set_push_provider(None)


@pytest.fixture(autouse=True)
def fake_providers(ai_provider, token_minter, push_provider):  # type: ignore[no-untyped-def]
    """Every test runs against fakes. Nothing here calls a paid service."""
    return {
        "ai": ai_provider,
        "live": token_minter,
        "push": push_provider,
    }


@pytest.fixture
async def client(sessionmaker) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    app = create_app(get_settings())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client


@pytest.fixture
def worker_settings():  # type: ignore[no-untyped-def]
    """Worker configuration for tests: no scheduler, short leases, no sleeping."""
    return get_settings().model_copy(
        update={
            "worker_run_scheduler": False,
            "worker_lease_seconds": 30,
            "worker_batch_size": 20,
            "job_retry_base_seconds": 0.01,
            "job_retry_max_seconds": 0.05,
        }
    )


@pytest.fixture
async def job_queue(sessionmaker, worker_settings) -> DatabaseJobQueue:  # type: ignore[no-untyped-def]
    return DatabaseJobQueue(sessionmaker, settings=worker_settings)


@pytest.fixture
async def run_worker(sessionmaker, worker_settings, job_queue):  # type: ignore[no-untyped-def]
    """Drain the queue with a real worker.

    Called with no arguments it runs whatever the API enqueued, which is how
    most tests should use it — the enqueue is part of what is being tested.
    Named job types are enqueued first, for the recurring sweeps that a
    scheduler would otherwise have queued.
    """
    worker = Worker(
        sessionmaker,
        settings=worker_settings,
        worker_id="test-worker",
        queue=job_queue,
    )

    async def _run(*job_types: str, payload: dict | None = None) -> int:
        for job_type in job_types:
            await job_queue.enqueue(job_type, payload=payload or {})
        return await worker.run_once()

    _run.worker = worker  # type: ignore[attr-defined]
    _run.queue = job_queue  # type: ignore[attr-defined]
    return _run


def auth(subject: str) -> dict[str, str]:
    """Bearer header for a local development identity."""
    return {"Authorization": f"Bearer dev:{subject}"}
