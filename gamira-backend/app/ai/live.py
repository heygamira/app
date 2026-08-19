"""Authenticated Gemini Live sessions.

What moved here from the standalone token server, and why each piece had to:

* **Authentication.** The dev server minted a token for anyone who could reach
  the port. This mints one for a verified Gamira user and nobody else.
* **Scope.** The dev server had no idea who was talking. Here the family and
  the senior come from the caller's membership rows, and are written onto the
  session — so a tool call arriving twenty minutes later is checked against
  that, not against anything the conversation claims.
* **Limits.** Entitlement, a per-hour rate limit and a concurrent-session cap,
  all enforced before a token exists.
* **Tools.** The catalogue is pinned into the token's connect constraints and
  snapshotted onto the session row.

The permanent Gemini key never leaves this process. The ephemeral token is
returned once, in the response body, and only its fingerprint is stored — so a
database read cannot open a voice session.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.persona import PERSONA_VERSION, build_system_instruction, resolve_model
from app.ai.tools import PARENT_APP_TOOLS, tool_snapshot
from app.core.config import Settings, get_settings
from app.core.errors import ApiError, DependencyUnavailable
from app.core.logging import current_request_id, get_logger
from app.db.base import utcnow
from app.jobs.queue import enqueue_job
from app.jobs.types import JobType
from app.models.ai import Conversation, LiveSession
from app.models.enums import (
    ConversationChannel,
    ConversationStatus,
    LiveSessionStatus,
    MembershipStatus,
    UserStatus,
)
from app.models.identity import FamilyMembership, SeniorProfile, User
from app.services import memories as memory_service

logger = get_logger(__name__)

# How long after a conversation ends before it is read back. Long enough for
# the browser's final `keepalive` transcript post to land.
REVIEW_DELAY_SECONDS = 30


class RateLimited(ApiError):
    status_code = 429
    code = "rate_limited"
    message = "Too many voice sessions. Wait a moment and try again."


@dataclass(frozen=True)
class MintedToken:
    """The ephemeral credential, and nothing that could be used to remint it."""

    token: str
    model: str
    api_version: str
    expires_at: dt.datetime
    # How long the token may be used to *open* a session, which is much shorter
    # than how long the session may then run.
    open_before: dt.datetime

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]


class LiveTokenMinter(Protocol):
    name: str

    async def mint(
        self,
        *,
        model: str,
        api_version: str,
        tools: list[dict[str, Any]],
        settings: Settings,
        system_instruction: str,
    ) -> MintedToken: ...


class FakeLiveTokenMinter:
    """A token-shaped string with no power. The only minter tests use.

    It records the constraints it was asked for, so a test can assert that the
    tool catalogue and system instruction were pinned without any network call.
    """

    name = "fake"

    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None

    async def mint(
        self,
        *,
        model: str,
        api_version: str,
        tools: list[dict[str, Any]],
        settings: Settings,
        system_instruction: str,
    ) -> MintedToken:
        if self.fail_with is not None:
            failure, self.fail_with = self.fail_with, None
            raise failure
        now = utcnow()
        self.minted.append(
            {
                "model": model,
                "api_version": api_version,
                "tools": [tool["name"] for tool in tools],
                "system_instruction": system_instruction,
            }
        )
        return MintedToken(
            # Deliberately not a real credential and obviously so.
            token=f"fake-ephemeral-{uuid.uuid4().hex}",
            model=model,
            api_version=api_version,
            expires_at=now + dt.timedelta(minutes=settings.live_session_ttl_minutes),
            open_before=now
            + dt.timedelta(minutes=settings.live_session_open_window_minutes),
        )

    def reset(self) -> None:
        self.minted.clear()
        self.fail_with = None


class GeminiLiveTokenMinter:
    """Mints a one-use ephemeral token with the model and config pinned.

    The constraints matter as much as the expiry: a leaked token cannot be
    repurposed onto another model, given different tools, or stripped of the
    system instruction, because all three are baked in at mint time.
    """

    name = "gemini"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.gemini_api_key:
            raise RuntimeError("Live sessions require GEMINI_API_KEY.")
        self._clients: dict[str, Any] = {}

    def _client(self, api_version: str) -> Any:
        # One client per API surface, kept for the life of the process: a
        # client built per request is closed when it goes out of scope and the
        # next call fails with "the client has been closed".
        if api_version not in self._clients:
            from google import genai

            self._clients[api_version] = genai.Client(
                api_key=self._settings.gemini_api_key,
                http_options={"api_version": api_version},
            )
        return self._clients[api_version]

    async def mint(
        self,
        *,
        model: str,
        api_version: str,
        tools: list[dict[str, Any]],
        settings: Settings,
        system_instruction: str,
    ) -> MintedToken:
        from google.genai import types

        now = utcnow()
        expires_at = now + dt.timedelta(minutes=settings.live_session_ttl_minutes)
        open_before = now + dt.timedelta(
            minutes=settings.live_session_open_window_minutes
        )
        declarations = [_declaration(types, tool) for tool in tools]
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text=system_instruction)]
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Both halves of the conversation, not just Gamira's. Without this
            # the person's own words are never transcribed at all — which left
            # `retention_policy="transcript_only"` describing something that did
            # not exist, and left nothing for Gamira to remember them by.
            #
            # Pinned into the ephemeral token like everything else here, so the
            # browser cannot turn it on, off, or up.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[types.Tool(function_declarations=declarations)] if tools else None,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=500,
                    # Older speakers often start softly, so lean towards hearing
                    # the start of speech rather than clipping it.
                    start_of_speech_sensitivity=(
                        types.StartSensitivity.START_SENSITIVITY_HIGH
                    ),
                    prefix_padding_ms=200,
                )
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=104857,
                sliding_window=types.SlidingWindow(target_tokens=52428),
            ),
        )
        try:
            token = await self._client(api_version).aio.auth_tokens.create(
                config=types.CreateAuthTokenConfig(
                    uses=1,
                    expire_time=expires_at,
                    new_session_expire_time=open_before,
                    live_connect_constraints=types.LiveConnectConstraints(
                        model=model, config=config
                    ),
                    http_options=types.HttpOptions(api_version=api_version),
                )
            )
        except Exception as exc:
            # The provider's message can contain the request it choked on, so
            # only its type reaches the log and only a code reaches the client.
            logger.error(
                "live_token_mint_failed",
                extra={"error": type(exc).__name__, "model": model},
            )
            raise DependencyUnavailable(
                "Voice is unavailable at the moment. Everything else still works."
            ) from exc

        return MintedToken(
            token=str(token.name),
            model=model,
            api_version=api_version,
            expires_at=expires_at,
            open_before=open_before,
        )


def _declaration(types: Any, tool: dict[str, Any]) -> Any:
    """One tool declaration, in the form the Live API actually accepts.

    ``parameters`` is the SDK's own ``Schema`` type, and it has no
    ``additionalProperties`` field — sending one is a 400 from the Live setup,
    verified against the real API. ``parameters_json_schema`` takes a raw JSON
    Schema and does accept it, which is what lets the strict catalogue be
    declared to the model rather than only enforced behind it.

    If a future SDK drops that field, the declaration falls back to ``Schema``
    with the key removed. Strictness is not lost when that happens: the backend
    validator rejects an unexpected argument regardless of what the model was
    told, and it is the validator that is authoritative.
    """
    if "parameters_json_schema" in types.FunctionDeclaration.model_fields:
        return types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters_json_schema=tool["parameters"],
        )
    parameters = {
        key: value
        for key, value in tool["parameters"].items()
        if key != "additionalProperties"
    }
    logger.warning(
        "live_tool_schema_downgraded",
        extra={"tool": tool["name"], "detail": "parameters_json_schema unavailable"},
    )
    return types.FunctionDeclaration(
        name=tool["name"], description=tool["description"], parameters=parameters
    )


_minter: LiveTokenMinter | None = None


def get_token_minter(settings: Settings | None = None) -> LiveTokenMinter:
    global _minter
    if _minter is None:
        settings = settings or get_settings()
        _minter = (
            GeminiLiveTokenMinter(settings)
            if settings.ai_provider == "gemini"
            else FakeLiveTokenMinter()
        )
    return _minter


def set_token_minter(minter: LiveTokenMinter | None) -> None:
    global _minter
    _minter = minter


# --------------------------------------------------------------------------- #
# Session creation
# --------------------------------------------------------------------------- #


@dataclass
class CreatedLiveSession:
    session: LiveSession
    token: MintedToken


async def create_live_session(
    db: AsyncSession,
    *,
    user: User,
    senior: SeniorProfile,
    membership: FamilyMembership,
    settings: Settings | None = None,
    minter: LiveTokenMinter | None = None,
    now: dt.datetime | None = None,
    provisional: bool = False,
) -> CreatedLiveSession:
    """Authorise, limit, mint and record. In that order.

    The token is minted last, after every check has passed, so a rejected
    request never costs a token — and never creates a session row that a
    failed mint would then have to clean up.

    ``provisional`` opens the session speculatively. The Parent App's wake-word
    detector pre-connects while the score says "probably", so the socket is
    already up by the time it says "definitely" — which is the difference
    between answering immediately and answering after a second and a half of
    silence. Most of those guesses are wrong, so a provisional session is
    cheap to abandon: it expires in a couple of minutes on its own and does not
    spend the caller's hourly allowance until :func:`promote_live_session`.
    """
    settings = settings or get_settings()
    minter = minter or get_token_minter(settings)
    now = now or utcnow()

    if user.status is not UserStatus.ACTIVE:
        raise RateLimited(
            "This account cannot start a voice session.",
            code="user_suspended",
            status_code=403,
        )
    if membership.status is not MembershipStatus.ACTIVE:
        raise RateLimited(
            "You no longer have access to this person's record.",
            code="membership_revoked",
            status_code=403,
        )

    await expire_stale_sessions(db, now=now)
    await _enforce_limits(
        db, user_id=user.id, settings=settings, now=now, provisional=provisional
    )

    model, _spec = resolve_model(settings.gemini_live_model)
    api_version = settings.gemini_live_api_version or _spec["api_version"]
    snapshot = tool_snapshot(PARENT_APP_TOOLS)
    # What Gamira remembers about this person, pinned into the token alongside
    # the persona and the tools. It has to be here rather than sent later: the
    # instruction is part of the connect constraints, so the browser cannot add
    # to it, remove from it, or open a session without it.
    instruction = build_system_instruction(
        await memory_service.recall_for_prompt(db, senior_profile_id=senior.id)
    )

    try:
        token = await minter.mint(
            model=model,
            api_version=api_version,
            tools=snapshot,
            settings=settings,
            system_instruction=instruction,
        )
    except Exception as exc:
        # One message for every way minting can fail, and it says what is still
        # working — a voice outage must not read like a total one. The cause is
        # logged by type only: a provider's text can echo the request.
        logger.error(
            "live_session_mint_failed",
            extra={"error": type(exc).__name__, "model": model},
        )
        raise DependencyUnavailable(
            "Voice is unavailable right now. Reminders, medicines and SOS still work.",
            code="dependency_unavailable",
        ) from exc

    conversation = Conversation(
        family_id=senior.family_id,
        user_id=user.id,
        senior_profile_id=senior.id,
        channel=ConversationChannel.VOICE,
        status=ConversationStatus.ACTIVE,
        started_at=now,
        # Audio is never stored. Only the transcription the provider returns is
        # eligible, and only while the conversation is retained.
        retention_policy="transcript_only",
        consent_snapshot={"senior_consent": senior.consent_status.value},
    )
    db.add(conversation)
    await db.flush()

    live_session = LiveSession(
        user_id=user.id,
        family_id=senior.family_id,
        senior_profile_id=senior.id,
        conversation_id=conversation.id,
        membership_role=membership.role.value,
        status=LiveSessionStatus.ACTIVE,
        model=model,
        api_version=api_version,
        provider=minter.name,
        prompt_version=PERSONA_VERSION,
        tool_snapshot=snapshot,
        # The fingerprint, never the token.
        token_fingerprint=token.fingerprint,
        # The backend session dies with the Live token, not after it — except
        # while provisional, when it dies much sooner so an abandoned guess
        # releases its slot without anyone having to clean up after it.
        expires_at=(
            min(token.expires_at,
                now + dt.timedelta(seconds=settings.live_provisional_ttl_seconds))
            if provisional
            else token.expires_at
        ),
        provisional=provisional,
        request_id=current_request_id() or None,
    )
    db.add(live_session)
    await db.flush()

    logger.info(
        "live_session_created",
        extra={
            "live_session_id": str(live_session.id),
            "model": model,
            "api_version": api_version,
            "tools": len(snapshot),
            "expires_at": live_session.expires_at.isoformat(),
            "provisional": provisional,
            # Identifies the token in an audit trail without being one.
            "token": token.fingerprint,
        },
    )
    return CreatedLiveSession(session=live_session, token=token)


async def promote_live_session(
    db: AsyncSession,
    *,
    live_session: LiveSession,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> LiveSession:
    """A speculative session turned out to be real. Charge for it and extend it.

    The hourly limit is applied *here* rather than at creation, so the quota
    tracks conversations a person actually had. Checking it now also means a
    caller cannot dodge the limit by always pre-connecting: the check simply
    happens a few hundred milliseconds later.

    Idempotent — a retried promote on an already-real session is a no-op, not a
    second charge.
    """
    settings = settings or get_settings()
    now = now or utcnow()

    if not live_session.provisional:
        return live_session
    if not live_session.is_live(now):
        raise RateLimited(
            "That voice session expired before it could be used.",
            code="live_session_expired",
            status_code=409,
        )

    await _enforce_hourly_limit(
        db, user_id=live_session.user_id, settings=settings, now=now
    )

    live_session.provisional = False
    live_session.expires_at = now + dt.timedelta(
        minutes=settings.live_session_ttl_minutes
    )
    live_session.last_seen_at = now
    await db.flush()

    logger.info(
        "live_session_promoted",
        extra={
            "live_session_id": str(live_session.id),
            "expires_at": live_session.expires_at.isoformat(),
        },
    )
    return live_session


async def _enforce_hourly_limit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    settings: Settings,
    now: dt.datetime,
    provisional: bool = False,
    limit: int | None = None,
) -> None:
    """How many sessions of one kind this person has opened in the last hour.

    Counted separately for real ones and for guesses, because they mean
    different things: a real session is a conversation somebody had, and a
    guess is the detector being wrong. Both cost a minted token, so both are
    capped — the guesses far more loosely, since one of them is what makes a
    real "Gamira" answer immediately.
    """
    recent = int(
        await db.scalar(
            select(func.count())
            .select_from(LiveSession)
            .where(
                LiveSession.user_id == user_id,
                LiveSession.created_at >= now - dt.timedelta(hours=1),
                LiveSession.provisional.is_(provisional),
            )
        )
        or 0
    )
    ceiling = settings.live_sessions_per_hour if limit is None else limit
    if recent >= ceiling:
        if provisional:
            # Not the person's fault and not something they can act on, so the
            # wording is about listening rather than about talking.
            raise RateLimited(
                "Gamira has been mishearing her name too often; "
                "hands-free listening is paused for a little while."
            )
        raise RateLimited("Too many voice sessions in the last hour.")


async def _enforce_limits(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    settings: Settings,
    now: dt.datetime,
    provisional: bool = False,
) -> None:
    concurrent = int(
        await db.scalar(
            select(func.count())
            .select_from(LiveSession)
            .where(
                LiveSession.user_id == user_id,
                LiveSession.status == LiveSessionStatus.ACTIVE,
                LiveSession.expires_at > now,
                LiveSession.provisional.is_(provisional),
            )
        )
        or 0
    )
    # Provisional sessions have their own, separate cap. Sharing the real one
    # would mean a single unconfirmed guess locks the person out of starting a
    # conversation by hand — the exact opposite of what pre-connecting is for.
    cap = (
        settings.live_provisional_max_concurrent
        if provisional
        else settings.live_session_max_concurrent
    )
    if concurrent >= cap:
        raise RateLimited(
            "Still opening a voice session — try again in a moment."
            if provisional
            else "A voice session is already open on another device.",
            code="too_many_live_sessions",
        )

    if provisional:
        # A guess does not spend the *conversation* allowance — `promote_live_
        # session` charges for it if it becomes one — but it is not free
        # either: it mints a real token. It had no server-side ceiling at all,
        # which meant the only thing standing between a noisy room and an
        # unbounded number of billed calls was a constant in browser
        # JavaScript. A limit that ships in the client is not a limit.
        await _enforce_hourly_limit(
            db,
            user_id=user_id,
            settings=settings,
            now=now,
            provisional=True,
            limit=settings.live_provisional_per_hour,
        )
    if not provisional:
        await _enforce_hourly_limit(db, user_id=user_id, settings=settings, now=now)


async def expire_stale_sessions(
    db: AsyncSession, *, now: dt.datetime | None = None
) -> int:
    """Close every session whose token has run out.

    Run before the concurrency check so a phone that was closed without saying
    goodbye does not hold a slot until somebody notices.

    The conversations behind them are ended here too. Somebody who puts the
    phone down mid-sentence is the common case, not the exception, and their
    conversation would otherwise stay ``active`` forever — never read back,
    never remembered, and never retained or deleted by any rule.
    """
    now = now or utcnow()
    stale = list(
        (
            await db.execute(
                select(LiveSession).where(
                    LiveSession.status == LiveSessionStatus.ACTIVE,
                    LiveSession.expires_at <= now,
                )
            )
        ).scalars()
    )
    if not stale:
        return 0

    for live_session in stale:
        live_session.status = LiveSessionStatus.EXPIRED
        live_session.closed_at = now
        if not live_session.conversation_id:
            continue
        conversation = await db.get(Conversation, live_session.conversation_id)
        if conversation is None or conversation.status is not ConversationStatus.ACTIVE:
            continue
        conversation.status = ConversationStatus.ENDED
        conversation.ended_at = now
        # A provisional session is a wake word that came to nothing; there is
        # no conversation to read back, and `gather` would refuse it anyway.
        if not live_session.provisional:
            await _queue_review(db, conversation=conversation, now=now)
    await db.flush()
    return len(stale)


async def close_live_session(
    db: AsyncSession,
    *,
    live_session: LiveSession,
    status: LiveSessionStatus = LiveSessionStatus.CLOSED,
    now: dt.datetime | None = None,
) -> LiveSession:
    now = now or utcnow()
    if live_session.status is LiveSessionStatus.ACTIVE:
        live_session.status = status
        live_session.closed_at = now
        if live_session.conversation_id:
            conversation = await db.get(Conversation, live_session.conversation_id)
            if conversation is not None:
                conversation.status = ConversationStatus.ENDED
                conversation.ended_at = now
                # The same guard `expire_stale_sessions` has, and it was missing
                # here — which is the path an *abandoned* guess actually takes.
                # So every wake word that came to nothing queued a job to read
                # back a conversation in which nobody had said anything: a row,
                # a worker wake-up and a log line, hundreds of times an hour.
                if not live_session.provisional:
                    await _queue_review(db, conversation=conversation, now=now)
        await db.flush()
    return live_session


async def _queue_review(
    db: AsyncSession, *, conversation: Conversation, now: dt.datetime
) -> None:
    """Ask for this conversation to be read back, shortly.

    Not immediately: the browser posts its last transcript batch with
    ``keepalive`` at the same moment it closes the session, and a review that
    started this instant would read an exchange missing its final turns — which
    are usually the ones worth reading.

    Deduped on the conversation, so a session closed by hand and then swept as
    expired queues one review, not two. Enqueued in the caller's transaction,
    so a conversation that did not really end does not leave a job behind.
    """
    await enqueue_job(
        db,
        JobType.AI_CONVERSATION_REVIEW,
        payload={"conversation_id": str(conversation.id)},
        dedupe_key=f"conversation-review:{conversation.id}",
        family_id=conversation.family_id,
        run_after=now + dt.timedelta(seconds=REVIEW_DELAY_SECONDS),
        request_id=current_request_id() or None,
    )


__all__ = [
    "CreatedLiveSession",
    "FakeLiveTokenMinter",
    "GeminiLiveTokenMinter",
    "LiveTokenMinter",
    "MintedToken",
    "RateLimited",
    "close_live_session",
    "create_live_session",
    "expire_stale_sessions",
    "get_token_minter",
    "promote_live_session",
    "set_token_minter",
]
