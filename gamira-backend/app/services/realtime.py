"""In-process pub/sub for the events a Family Dashboard needs the instant
they happen: an SOS raised, an alert escalated, a device flag opened.

Deliberately a thin invalidation signal, not a payload push: a subscriber is
told only *what kind of thing* changed for *which family*, and re-fetches the
authoritative row through the ordinary, already-authorized read endpoints
(``GET /notifications`` and friends). That means this module never has to
duplicate notification-shaping logic, and never has to decide per-connection
what a payload is safe to contain — only whether this family's connections
should be told to look again, which family membership already gated at
subscribe time.

IMPORTANT — single-process only. This is a plain in-memory mapping of
``family_id`` to the queues currently subscribed to it, in this process. An
SOS raised on one Cloud Run replica does not reach a dashboard whose SSE
connection happens to be held open by a different replica — there is no
guarantee they are the same one once more than one is running. That is fine
today: this app runs as one API instance. It stops being fine the moment it
is deployed with more than one. The fix at that point is Postgres
``LISTEN``/``NOTIFY`` — Postgres is already the mandated production database
and ``asyncpg`` is already a dependency, so it needs no new infrastructure,
just a subscriber that listens on a channel instead of an in-memory queue and
a publisher that does ``NOTIFY`` instead of ``queue.put_nowait``. One shared
channel with the family id in the payload is enough; a ``NOTIFY`` payload is
capped at 8000 bytes and this one is a few dozen. Do that upgrade *before*
scaling this API past one replica, not after — a silently dropped SOS
notification is a worse failure than the one this whole phase exists to fix.
"""

from __future__ import annotations

import asyncio
import uuid

_subscribers: dict[uuid.UUID, set[asyncio.Queue]] = {}


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


def publish_family_event(
    family_id: uuid.UUID,
    kind: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> None:
    """Tell every connection currently subscribed to this family that
    something changed. Best-effort and synchronous: a dashboard with nobody
    watching costs nothing, and a slow or dead subscriber must never hold up
    the request that raised the event — an SOS write does not wait on this.
    """
    subscribers = _subscribers.get(family_id)
    if not subscribers:
        return
    event = {
        "kind": kind,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
    }
    for queue in list(subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # This subscriber has fallen behind. Dropping the event is the
            # right call: it will reconnect and re-fetch, and blocking here
            # would turn a slow dashboard tab into a slow SOS write for
            # everyone else in the family.
            pass
