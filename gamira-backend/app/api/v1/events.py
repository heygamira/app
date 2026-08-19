"""Server-sent events: "something changed for this family," pushed the
moment it happens, instead of a dashboard polling every few seconds to find
out. See app.services.realtime for what this does and does not guarantee.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, SessionDep
from app.services import realtime
from app.services.authz import require_membership

router = APIRouter(tags=["events"])

# How often a silent connection gets a comment line, so a proxy or the
# browser's own timeout never mistakes "nothing has happened" for "the
# connection is dead."
HEARTBEAT_SECONDS = 15


@router.get("/families/{family_id}/events")
async def family_events(
    family_id: uuid.UUID, request: Request, session: SessionDep, user: CurrentUser
) -> StreamingResponse:
    # Authorized once, at subscribe time — the same membership check every
    # other family-scoped read already uses. What a subscriber receives after
    # this is only ever "something changed," never a payload, so there is
    # nothing further to authorize per event.
    await require_membership(session, user_id=user.id, family_id=family_id)

    async def stream():
        queue = realtime.subscribe(family_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            realtime.unsubscribe(family_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx and similar proxies buffer a streaming response by
            # default, which would turn "pushed the instant it happens" into
            # "pushed once the buffer fills." Harmless to send when there is
            # no such proxy in front, as in local dev.
            "X-Accel-Buffering": "no",
        },
    )
