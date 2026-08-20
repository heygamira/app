"""The push provider interface, and the two implementations behind it.

The interface exists so the delivery handler never knows whether a message went
to Firebase or into a list in memory. That is what lets the whole notification
path — retries, invalid-token revocation, per-device attempt records — be
tested without a network, a project or a bill.

Nothing in this module logs a push token. Every log line and every stored row
carries the token's fingerprint instead: enough to say *which device*, useless
to anyone who wants to send to it.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.devices import token_fingerprint
from app.models.enums import DeliveryAttemptStatus

logger = get_logger(__name__)

FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@dataclass(frozen=True)
class PushMessage:
    """What a device is asked to show, plus the data it needs to act on a tap.

    ``data`` is deliberately small and structural — a notification type and an
    entity id, so the app can open the right screen. It never carries a value
    from a health reading or the text of a family note.
    """

    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    # Lets a provider drop an older undelivered message about the same thing.
    collapse_key: str | None = None
    high_priority: bool = False
    # FCM auto-displays any message that carries a "notification" block once
    # the app is backgrounded or killed, before our own code ever runs. SOS
    # alerts need to reach native code in every app state so it can raise a
    # full-screen, sound-playing alarm itself — that only happens for a
    # data-only message.
    data_only: bool = False


@dataclass(frozen=True)
class PushResult:
    status: DeliveryAttemptStatus
    message_id: str | None = None
    error_code: str | None = None
    latency_ms: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is DeliveryAttemptStatus.SUCCEEDED


class PushProvider(Protocol):
    name: str

    async def send(self, *, token: str, message: PushMessage) -> PushResult: ...


# --------------------------------------------------------------------------- #
# Error classification
# --------------------------------------------------------------------------- #

# A token the provider says is dead. The device row is marked invalid and stops
# being tried, which is the only way a queue does not slowly fill with sends to
# uninstalled apps.
INVALID_TOKEN_CODES = frozenset(
    {
        "UNREGISTERED",
        "NOT_FOUND",
        "INVALID_ARGUMENT",
        "REGISTRATION_TOKEN_NOT_REGISTERED",
    }
)
# The provider is busy or broken. The same message may well work in a minute.
RETRYABLE_CODES = frozenset(
    {
        "UNAVAILABLE",
        "INTERNAL",
        "QUOTA_EXCEEDED",
        "RESOURCE_EXHAUSTED",
        "DEADLINE_EXCEEDED",
    }
)
# Our configuration is wrong. Retrying is pointless until a human changes it.
PERMANENT_CODES = frozenset(
    {
        "SENDER_ID_MISMATCH",
        "THIRD_PARTY_AUTH_ERROR",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
    }
)


def classify(
    error_code: str | None, status_code: int | None = None
) -> DeliveryAttemptStatus:
    """Turn a provider error into one of our four outcomes."""
    code = (error_code or "").upper()
    if code in INVALID_TOKEN_CODES:
        return DeliveryAttemptStatus.TOKEN_INVALID
    if code in PERMANENT_CODES:
        return DeliveryAttemptStatus.PERMANENT
    if code in RETRYABLE_CODES:
        return DeliveryAttemptStatus.RETRYABLE
    if status_code is not None:
        if status_code == 404:
            return DeliveryAttemptStatus.TOKEN_INVALID
        if status_code in (401, 403):
            return DeliveryAttemptStatus.PERMANENT
        if status_code == 429 or status_code >= 500:
            return DeliveryAttemptStatus.RETRYABLE
        if 400 <= status_code < 500:
            return DeliveryAttemptStatus.PERMANENT
    # An unrecognised failure is treated as retryable: giving up on a
    # medication reminder because of an unfamiliar error string is worse than
    # trying it again in a minute.
    return DeliveryAttemptStatus.RETRYABLE


# --------------------------------------------------------------------------- #
# Fake provider
# --------------------------------------------------------------------------- #


@dataclass
class SentPush:
    token_fingerprint: str
    message: PushMessage


class FakePushProvider:
    """Records what would have been sent. The only provider tests ever use.

    ``fail_next`` and ``fail_tokens`` let a test drive the retry and
    invalid-token paths deterministically, without waiting on a real provider
    to misbehave.
    """

    name = "fake"

    def __init__(self) -> None:
        self.sent: list[SentPush] = []
        self.fail_next: list[str] = []
        self.fail_tokens: dict[str, str] = {}

    async def send(self, *, token: str, message: PushMessage) -> PushResult:
        fingerprint = token_fingerprint(token)
        error_code: str | None = None
        if self.fail_next:
            error_code = self.fail_next.pop(0)
        elif token in self.fail_tokens:
            error_code = self.fail_tokens[token]

        if error_code:
            return PushResult(
                status=classify(error_code), error_code=error_code, latency_ms=0
            )

        self.sent.append(SentPush(token_fingerprint=fingerprint, message=message))
        return PushResult(
            status=DeliveryAttemptStatus.SUCCEEDED,
            message_id=f"fake/{len(self.sent)}",
            latency_ms=0,
        )

    def reset(self) -> None:
        self.sent.clear()
        self.fail_next.clear()
        self.fail_tokens.clear()


# --------------------------------------------------------------------------- #
# Firebase provider
# --------------------------------------------------------------------------- #


class FirebasePushProvider:
    """FCM HTTP v1, authenticated with a service account.

    The service-account file is read by the worker process and never leaves it.
    Access tokens are refreshed by ``google.auth`` and are not logged.
    """

    name = "firebase"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.fcm_project_id:
            raise RuntimeError("FCM_PROJECT_ID is required for the firebase provider.")
        self._credentials: Any = None
        self._lock = asyncio.Lock()

    async def _access_token(self) -> str:
        # Refreshing is blocking and shared, so it happens once at a time and
        # off the event loop.
        async with self._lock:
            if self._credentials is None:
                self._credentials = await asyncio.to_thread(self._load_credentials)
            if not self._credentials.valid:
                await asyncio.to_thread(self._refresh, self._credentials)
            return str(self._credentials.token)

    def _load_credentials(self) -> Any:
        from google.oauth2 import service_account  # imported lazily

        if not self._settings.fcm_credentials_file:
            import google.auth

            credentials, _ = google.auth.default(scopes=[FCM_SCOPE])
            return credentials
        return service_account.Credentials.from_service_account_file(
            self._settings.fcm_credentials_file, scopes=[FCM_SCOPE]
        )

    @staticmethod
    def _refresh(credentials: Any) -> None:
        from google.auth.transport.requests import Request

        credentials.refresh(Request())

    async def send(self, *, token: str, message: PushMessage) -> PushResult:
        started = time.perf_counter()
        fingerprint = token_fingerprint(token)
        try:
            access_token = await self._access_token()
        except Exception as exc:
            logger.error(
                "fcm_auth_failed",
                extra={"error": type(exc).__name__, "device": fingerprint},
            )
            return PushResult(
                status=DeliveryAttemptStatus.RETRYABLE, error_code="auth_failed"
            )

        payload: dict[str, Any] = {
            "message": {
                "token": token,
                **(
                    {}
                    if message.data_only
                    else {"notification": {"title": message.title, "body": message.body}}
                ),
                "data": dict(message.data),
                "android": {
                    "priority": "high" if message.high_priority else "normal",
                    **(
                        {"collapse_key": message.collapse_key}
                        if message.collapse_key
                        else {}
                    ),
                },
                "apns": {
                    "headers": {
                        "apns-priority": "10" if message.high_priority else "5",
                        **(
                            {"apns-collapse-id": message.collapse_key}
                            if message.collapse_key
                            else {}
                        ),
                    }
                },
            }
        }
        url = FCM_ENDPOINT.format(project_id=self._settings.fcm_project_id)
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.fcm_timeout_seconds
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "fcm_transport_error",
                extra={"error": type(exc).__name__, "device": fingerprint},
            )
            return PushResult(
                status=DeliveryAttemptStatus.RETRYABLE,
                error_code="transport_error",
                latency_ms=_ms(started),
            )

        latency = _ms(started)
        if response.status_code == 200:
            body = _safe_json(response.text)
            return PushResult(
                status=DeliveryAttemptStatus.SUCCEEDED,
                message_id=str(body.get("name") or "")[:200] or None,
                latency_ms=latency,
            )

        error_code = _fcm_error_code(response.text)
        status = classify(error_code, response.status_code)
        # The response body can echo the token back, so only the code is kept.
        logger.warning(
            "fcm_send_failed",
            extra={
                "device": fingerprint,
                "status_code": response.status_code,
                "error_code": error_code,
                "outcome": status.value,
            },
        )
        return PushResult(status=status, error_code=error_code, latency_ms=latency)


def _fcm_error_code(body: str) -> str:
    payload = _safe_json(body)
    error = payload.get("error") or {}
    for detail in error.get("details") or []:
        code = detail.get("errorCode")
        if code:
            return str(code)[:64]
    return str(error.get("status") or error.get("message") or "unknown")[:64]


def _safe_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


_provider: PushProvider | None = None


def get_push_provider(settings: Settings | None = None) -> PushProvider:
    """One provider per process, chosen by configuration."""
    global _provider
    if _provider is None:
        settings = settings or get_settings()
        _provider = (
            FirebasePushProvider(settings)
            if settings.fcm_provider == "firebase"
            else FakePushProvider()
        )
    return _provider


def set_push_provider(provider: PushProvider | None) -> None:
    """Override the provider. Tests use this; nothing in production does."""
    global _provider
    _provider = provider


__all__ = [
    "FakePushProvider",
    "FirebasePushProvider",
    "PushMessage",
    "PushProvider",
    "PushResult",
    "SentPush",
    "classify",
    "get_push_provider",
    "set_push_provider",
]
