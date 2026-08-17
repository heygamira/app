"""The AI provider interface, and the two implementations behind it.

Everything above this layer works in terms of "give me an object of this
Pydantic type from this versioned prompt and these validated facts". That is
what makes the fake provider a real test double rather than a stub: it returns
the same shape, is validated the same way, and its output flows through the
same policy checks.

Failures are classified, not propagated. A timeout is retryable; a schema the
model refuses to satisfy twice is not. The distinction is what stops a summary
job burning five attempts on a prompt that will never validate.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.prompts import Prompt
from app.ai.schemas import ChatReplyOut, WeeklySummaryOut
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

OutT = TypeVar("OutT", bound=BaseModel)


class AIError(Exception):
    """Base for anything the provider layer refuses to hand upwards."""

    code = "ai_error"
    retryable = True

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        if code:
            self.code = code
        super().__init__(message or self.code)


class AIUnavailable(AIError):
    """The provider could not be reached, or timed out. Try again later."""

    code = "ai_unavailable"
    retryable = True


class AIInvalidResponse(AIError):
    """The model answered, but not with the shape that was asked for."""

    code = "ai_invalid_response"
    retryable = False


class AIRefused(AIError):
    """The provider declined the request (safety filter, quota policy)."""

    code = "ai_refused"
    retryable = False


@dataclass
class AIResult:
    """A validated output plus everything worth recording about the call."""

    output: BaseModel
    model: str
    provider: str
    prompt_version: str
    prompt_tokens: int = 0
    response_tokens: int = 0
    latency_ms: float = 0.0
    raw_text: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.response_tokens


class AIProvider(Protocol):
    name: str
    model: str

    async def generate(
        self,
        *,
        prompt: Prompt,
        rendered: str,
        output_model: type[BaseModel],
        timeout_seconds: float,
    ) -> AIResult: ...


# --------------------------------------------------------------------------- #
# Fake provider
# --------------------------------------------------------------------------- #


@dataclass
class FakeCall:
    prompt_id: str
    rendered: str
    output_model: str


class FakeAIProvider:
    """Deterministic, offline, and the only provider the test suite uses.

    It composes its answer from the rendered prompt rather than inventing
    anything, which means a test asserting "the summary mentions the counted
    figures" is asserting something real about the pipeline rather than about a
    canned string.

    ``fail_with`` makes every call raise until it is cleared — a *sustained*
    outage, which is what the retry rules have to survive. ``fail_next`` queues
    individual failures for testing recovery on a later attempt.
    """

    name = "fake"
    model = "fake-deterministic-1"

    def __init__(self) -> None:
        self.calls: list[FakeCall] = []
        self.fail_with: AIError | None = None
        self.fail_next: list[AIError] = []
        self.delay_seconds: float = 0.0

    async def generate(
        self,
        *,
        prompt: Prompt,
        rendered: str,
        output_model: type[BaseModel],
        timeout_seconds: float,
    ) -> AIResult:
        self.calls.append(
            FakeCall(
                prompt_id=prompt.id,
                rendered=rendered,
                output_model=output_model.__name__,
            )
        )
        if self.fail_next:
            raise self.fail_next.pop(0)
        if self.fail_with is not None:
            raise self.fail_with
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)

        output = _fake_output(output_model, rendered)
        return AIResult(
            output=output,
            model=self.model,
            provider=self.name,
            prompt_version=prompt.version,
            prompt_tokens=max(1, len(rendered) // 4),
            response_tokens=32,
            latency_ms=0.0,
        )

    def reset(self) -> None:
        self.calls.clear()
        self.fail_with = None
        self.fail_next.clear()
        self.delay_seconds = 0.0


def _fake_output(output_model: type[BaseModel], rendered: str) -> BaseModel:
    """Build a valid instance of whatever was asked for, from the prompt itself."""
    if output_model is WeeklySummaryOut:
        facts = _extract_json_block(rendered)
        doses = facts.get("doses", {}) if isinstance(facts, dict) else {}
        taken = int(doses.get("taken", 0) or 0)
        scheduled = int(doses.get("scheduled", 0) or 0)
        missed = int(doses.get("missed", 0) or 0)
        return WeeklySummaryOut(
            headline=f"{taken} of {scheduled} doses recorded",
            body=(
                f"Over this period {taken} of {scheduled} scheduled doses were "
                f"recorded as taken, and {missed} were missed. These are the "
                "figures Gamira counted; nothing here is a medical assessment."
            ),
            highlights=[
                f"Doses taken: {taken}",
                f"Doses missed: {missed}",
            ],
        )
    if output_model is ChatReplyOut:
        return ChatReplyOut(
            reply=(
                "Here is what Gamira has on record. Anything medical is one for "
                "the doctor."
            )
        )
    # A new output type without a fake is a test-suite bug, not a runtime one.
    raise AIInvalidResponse(
        f"The fake provider has no output for {output_model.__name__}.",
    )


def _extract_json_block(rendered: str) -> dict[str, Any]:
    start = rendered.find("{")
    end = rendered.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(rendered[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# --------------------------------------------------------------------------- #
# Gemini provider
# --------------------------------------------------------------------------- #


class GeminiProvider:
    """Gemini, asked for JSON and held to the schema.

    The response schema is sent to the API, and the result is validated against
    the Pydantic model regardless: a provider that honours a schema most of the
    time is not a guarantee, and the policy engine downstream is entitled to
    assume the object it receives is the shape it asked for.
    """

    name = "gemini"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.gemini_api_key:
            raise RuntimeError("AI_PROVIDER=gemini requires GEMINI_API_KEY.")
        self.model = self._settings.gemini_model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # imported lazily: the API process may not need it

            self._client = genai.Client(api_key=self._settings.gemini_api_key)
        return self._client

    async def generate(
        self,
        *,
        prompt: Prompt,
        rendered: str,
        output_model: type[BaseModel],
        timeout_seconds: float,
    ) -> AIResult:
        from google.genai import types

        started = time.perf_counter()
        config = types.GenerateContentConfig(
            system_instruction=prompt.system,
            response_mime_type="application/json",
            response_schema=output_model,
            temperature=0.2,
        )
        try:
            response = await asyncio.wait_for(
                self._get_client().aio.models.generate_content(
                    model=self.model, contents=rendered, config=config
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise AIUnavailable("The model did not answer in time.") from exc
        except Exception as exc:
            # The exception text can echo the prompt, so only the type is
            # logged and only a code is raised.
            logger.warning(
                "gemini_call_failed",
                extra={"error": type(exc).__name__, "prompt": prompt.id},
            )
            raise AIUnavailable("The model could not be reached.") from exc

        latency = (time.perf_counter() - started) * 1000
        text = getattr(response, "text", None)
        if not text:
            raise AIRefused("The model returned no content.")

        try:
            output = output_model.model_validate_json(text)
        except ValidationError as exc:
            logger.warning(
                "gemini_schema_violation",
                extra={"prompt": prompt.id, "errors": len(exc.errors())},
            )
            raise AIInvalidResponse(
                "The model's reply did not match the schema."
            ) from exc

        usage = getattr(response, "usage_metadata", None)
        return AIResult(
            output=output,
            model=self.model,
            provider=self.name,
            prompt_version=prompt.version,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            response_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            latency_ms=latency,
        )


_provider: AIProvider | None = None


def get_ai_provider(settings: Settings | None = None) -> AIProvider:
    global _provider
    if _provider is None:
        settings = settings or get_settings()
        _provider = (
            GeminiProvider(settings)
            if settings.ai_provider == "gemini"
            else FakeAIProvider()
        )
    return _provider


def set_ai_provider(provider: AIProvider | None) -> None:
    """Override the provider. Tests use this; nothing in production does."""
    global _provider
    _provider = provider


@dataclass
class RetryPolicy:
    """How many times to try, and which failures deserve another go."""

    max_attempts: int = 3
    base_seconds: float = 0.5
    metrics: dict[str, int] = field(default_factory=dict)


async def generate_with_retry(
    provider: AIProvider,
    *,
    prompt: Prompt,
    rendered: str,
    output_model: type[BaseModel],
    settings: Settings,
) -> AIResult:
    """Call the provider, retrying only what retrying can fix."""
    last: AIError = AIUnavailable("The model was never reached.")
    for attempt in range(1, settings.ai_max_attempts + 1):
        try:
            return await provider.generate(
                prompt=prompt,
                rendered=rendered,
                output_model=output_model,
                timeout_seconds=settings.ai_request_timeout_seconds,
            )
        except AIError as exc:
            last = exc
            if not exc.retryable or attempt >= settings.ai_max_attempts:
                raise
            base = settings.ai_retry_base_seconds
            await asyncio.sleep(min(4.0, base * (2 ** (attempt - 1))))
    raise last


__all__ = [
    "AIError",
    "AIInvalidResponse",
    "AIProvider",
    "AIRefused",
    "AIResult",
    "AIUnavailable",
    "FakeAIProvider",
    "GeminiProvider",
    "generate_with_retry",
    "get_ai_provider",
    "set_ai_provider",
]
