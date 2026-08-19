"""Pub/sub for the events a Family Dashboard needs the instant they happen:
an SOS raised, an alert escalated, a device flag opened.

Deliberately a thin invalidation signal, not a payload push: a subscriber is
told only *what kind of thing* changed for *which family*, and re-fetches the
authoritative row through the ordinary, already-authorized read endpoints
(``GET /notifications`` and friends). That means this module never has to
duplicate notification-shaping logic, and never has to decide per-connection
what a payload is safe to contain — only whether this family's connections
should be told to look again, which family membership already gated at
subscribe time.

Two delivery paths, selected by ``settings.is_sqlite`` — the same switch
``app/jobs/queue.py`` already uses for its own dual-path claiming:

* **SQLite (local/test).** A plain in-memory ``dict`` of ``family_id`` to the
  ``asyncio.Queue``s currently subscribed, in this process. Delivery is
  synchronous and immediate. This is the whole story for local dev, where the
  API is one process.
* **PostgreSQL (staging/production).** The API and the worker already run as
  separate OS processes even locally, and a worker-raised event (most
  importantly, SOS escalation — ``alert_service.escalate`` runs from the
  worker's own sweep) can never reach an API-process ``asyncio.Queue`` no
  matter how many replicas exist. ``publish_family_event`` instead does
  ``pg_notify`` **inside the caller's own transaction**, so a subscriber is
  never told to refetch a row that isn't committed yet, and a rolled-back
  request tells nobody anything. Every API process keeps one dedicated
  ``asyncpg`` connection ``LISTEN``-ing on a single shared channel (started in
  ``app.main``'s lifespan) and re-delivers into the same local
  ``_subscribers`` map — so ``app/api/v1/events.py`` needs no changes at all,
  Postgres or not. One channel with the family id in the JSON payload is
  enough; a ``NOTIFY`` payload is capped at 8000 bytes and this one is a few
  dozen.

The listener reconnects with the same jittered backoff ``app/jobs/queue.py``
uses for job retries, logging loudly on every drop. It does not need to be
bulletproof: the Family Dashboard's Home screen already polls every 60
seconds independently of SSE, so a dropped notification is delayed, not lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

CHANNEL = "gamira_family_events"

_subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}
_listener_task: asyncio.Task[None] | None = None


def subscribe(family_id: uuid.UUID) -> asyncio.Queue:
    """Register a new listener for this family's events.

    Bounded, so a subscriber that stops reading (a dead connection the
    server hasn't noticed yet) cannot grow without limit — it just starts
    missing events, which is what `publish_family_event` already treats as
    acceptable: a client that falls behind reconnects and re-fetches.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    _subscribers.setdefault(family_id, set()).add(queue)
    return queue


def unsubscribe(family_id: uuid.UUID, queue: asyncio.Queue) -> None:
    subscribers = _subscribers.get(family_id)
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        _subscribers.pop(family_id, None)


def _deliver_local(family_id: uuid.UUID, event: dict[str, Any]) -> None:
    subscribers = _subscribers.get(family_id)
    if not subscribers:
        return
    for queue in list(subscribers):
        # A full queue means this subscriber has fallen behind. Dropping the
        # event is the right call: it will reconnect and re-fetch, and
        # blocking here would turn a slow dashboard tab into a slow SOS write
        # for everyone else in the family.
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)


async def publish_family_event(
    session: AsyncSession,
    family_id: uuid.UUID,
    kind: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> None:
    """Tell every connection currently subscribed to this family that
    something changed. Best-effort: a dashboard with nobody watching costs
    nothing, and a slow or dead subscriber must never hold up the request
    that raised the event — an SOS write does not wait on this.

    Must be called with the same session as the change it announces, before
    that session commits — on Postgres this is what makes delivery
    commit-gated rather than a race against the writer's own transaction.
    """
    settings = settings or get_settings()
    event: dict[str, Any] = {
        "family_id": str(family_id),
        "kind": kind,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
    }
    if settings.is_sqlite:
        _deliver_local(family_id, event)
        return
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": CHANNEL, "payload": json.dumps(event)},
    )


def _pg_dsn(database_url: str) -> str:
    """asyncpg.connect() wants a plain ``postgresql://`` DSN; the
    ``+asyncpg`` driver suffix is a SQLAlchemy-only convention."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _on_notify(
    _connection: object, _pid: int, _channel: str, payload: str
) -> None:
    try:
        event = json.loads(payload)
        family_id = uuid.UUID(event["family_id"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.error(
            "realtime_listener_bad_payload",
            extra={"error": str(exc), "payload": payload[:200]},
        )
        return
    _deliver_local(family_id, event)


async def _listen_forever(dsn: str, settings: Settings) -> None:
    import asyncpg

    from app.jobs.queue import backoff_seconds

    attempt = 0
    while True:
        try:
            conn = await asyncpg.connect(dsn)
        except Exception as exc:
            attempt += 1
            delay = backoff_seconds(attempt, settings)
            logger.error(
                "realtime_listener_connect_failed",
                extra={"error": str(exc), "retry_in_seconds": round(delay, 1)},
            )
            await asyncio.sleep(delay)
            continue

        attempt = 0
        closed = asyncio.Event()
        conn.add_termination_listener(lambda _conn, _e=closed: _e.set())
        try:
            await conn.add_listener(CHANNEL, _on_notify)
            logger.info("realtime_listener_connected")
            await closed.wait()
            logger.error("realtime_listener_disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("realtime_listener_error", extra={"error": str(exc)})
        finally:
            with contextlib.suppress(Exception):
                await conn.close()


def start_listener(settings: Settings | None = None) -> asyncio.Task[None] | None:
    """Start the per-process LISTEN connection. A no-op on SQLite, where
    delivery is already in-process and immediate."""
    global _listener_task
    settings = settings or get_settings()
    if settings.is_sqlite:
        return None
    _listener_task = asyncio.create_task(
        _listen_forever(_pg_dsn(settings.database_url), settings)
    )
    return _listener_task


async def stop_listener() -> None:
    global _listener_task
    if _listener_task is None:
        return
    _listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _listener_task
    _listener_task = None
