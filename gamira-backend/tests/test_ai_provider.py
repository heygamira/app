"""The Gemini provider's request shape, and how its failures are classified.

These exist because the provider was wrong for a long time in a way nothing
could see. Every output type inherits ``StrictModel``, whose ``extra="forbid"``
becomes ``additionalProperties`` in the generated JSON Schema — and
``additionalProperties`` is a flat 400 from ``generate_content``, the same way
it is a 400 from the Live setup for tool declarations. The provider then caught
that 400, called it "the model could not be reached", and retried it three
times, so a permanently malformed request looked exactly like a flaky provider.

Nothing here needs the network. What is being asserted is the request the
provider builds and how it reacts to a refusal, both of which are decided
locally.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.ai.prompts import CHAT_REPLY_V1
from app.ai.provider import (
    AIRefused,
    AIUnavailable,
    GeminiProvider,
    _is_retryable_api_error,
    _response_schema,
    generate_with_retry,
)
from app.ai.schemas import ChatReplyOut, WeeklySummaryOut
from app.core.config import get_settings

OUTPUT_MODELS = [ChatReplyOut, WeeklySummaryOut]


def _walk(node: Any):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


@pytest.mark.parametrize("output_model", OUTPUT_MODELS)
def test_the_schema_never_carries_additional_properties(output_model):
    """The single reason every Gemini call used to 400."""
    schema = _response_schema(output_model)
    assert any(isinstance(n, dict) for n in _walk(schema))
    for node in _walk(schema):
        if isinstance(node, dict):
            assert "additionalProperties" not in node

    # And the unmodified Pydantic schema really does contain it, so this test
    # is guarding something rather than asserting a coincidence.
    assert "additionalProperties" in output_model.model_json_schema()


@pytest.mark.parametrize("output_model", OUTPUT_MODELS)
def test_the_model_is_not_asked_for_the_schema_version(output_model):
    """A constant this codebase owns is not the model's to produce.

    Told to emit a field whose schema says ``const: "1"``, Gemini returns
    "1.0" — which then fails validation against ``Literal["1"]`` and is
    classified non-retryable. The field is simply not asked for.
    """
    schema = _response_schema(output_model)
    assert "schema_version" not in schema["properties"]
    assert "schema_version" not in schema.get("required", [])


def test_a_reply_without_a_schema_version_still_validates():
    """Because the default supplies it, which is the point of leaving it out."""
    reply = ChatReplyOut.model_validate_json('{"reply": "Metformin is due at 14:00."}')
    assert reply.schema_version == "1"
    assert reply.refused is False


def test_the_schema_still_describes_what_the_answer_must_contain():
    """Dropping fields must not turn the schema into a free-for-all."""
    schema = _response_schema(ChatReplyOut)
    assert schema["type"] == "object"
    assert "reply" in schema["properties"]
    assert schema["required"] == ["reply"]


class _Boom(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (400, False),  # a malformed request is malformed every time
        (404, False),  # a retired model stays retired
        (403, False),
        (429, True),  # rate limiting is exactly what backing off is for
        (500, True),
        (503, True),
    ],
)
def test_failures_are_classified_by_whether_retrying_could_help(status, retryable):
    assert _is_retryable_api_error(_Boom(status)) is retryable


def test_a_transport_failure_with_no_status_is_retried():
    """A dropped connection says nothing about the request."""
    assert _is_retryable_api_error(OSError("connection reset")) is True


class _StubClient:
    """Just enough of the genai client to fail in a specific way."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0
        self.aio = self

    @property
    def models(self):
        return self

    async def generate_content(self, **_kwargs: Any):
        self.calls += 1
        raise self.error


def _provider(error: Exception) -> tuple[GeminiProvider, _StubClient]:
    settings = get_settings().model_copy(update={"gemini_api_key": "test-key"})
    provider = GeminiProvider(settings)
    client = _StubClient(error)
    provider._client = client
    return provider, client


async def _generate(
    provider: GeminiProvider, output_model: type[BaseModel] = ChatReplyOut
):
    settings = get_settings().model_copy(
        update={"ai_max_attempts": 3, "ai_retry_base_seconds": 0.0}
    )
    return await generate_with_retry(
        provider,
        prompt=CHAT_REPLY_V1,
        rendered="anything",
        output_model=output_model,
        settings=settings,
    )


async def test_a_rejected_request_fails_once_instead_of_three_times():
    """The behaviour that hid the schema bug: a 400 reported as an outage.

    Three attempts at a request the API will never accept is three times the
    latency, three times the cost, and an error message pointing at the network
    rather than at the code.
    """
    provider, client = _provider(_Boom(400))

    with pytest.raises(AIRefused):
        await _generate(provider)

    assert client.calls == 1


async def test_rate_limiting_is_still_retried():
    provider, client = _provider(_Boom(429))

    with pytest.raises(AIUnavailable):
        await _generate(provider)

    assert client.calls == 3


async def test_the_request_carries_a_schema_the_api_accepts():
    """End to end through `generate`: capture what would go over the wire."""
    captured: dict[str, Any] = {}

    class _Capturing(_StubClient):
        async def generate_content(self, **kwargs: Any):
            captured.update(kwargs)
            raise _Boom(400)  # stop before we need a real response

    settings = get_settings().model_copy(update={"gemini_api_key": "test-key"})
    provider = GeminiProvider(settings)
    provider._client = _Capturing(_Boom(400))

    with pytest.raises(AIRefused):
        await provider.generate(
            prompt=CHAT_REPLY_V1,
            rendered="what is due today?",
            output_model=ChatReplyOut,
            timeout_seconds=5,
        )

    config = captured["config"]
    schema = config.response_json_schema or config.response_schema
    assert schema is not None
    for node in _walk(schema):
        if isinstance(node, dict):
            assert "additionalProperties" not in node
    # The safety rules travel with every call, not just the first.
    assert "not a clinician" in config.system_instruction
    assert config.response_mime_type == "application/json"


def test_the_configured_model_is_a_flash_lite_that_still_exists():
    """2.5-flash-lite is closed to new keys; the 404 names its replacement.

    Pinning a retired model is a 404 on every call, which the classifier above
    correctly refuses to retry — but it is better not to ship it at all.
    """
    model = get_settings().gemini_model
    assert "flash-lite" in model
    assert model != "gemini-2.5-flash-lite"
