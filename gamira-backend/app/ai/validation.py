"""A small, strict validator for tool arguments.

Written rather than pulled in because the surface is deliberately tiny — the
tool schemas use objects, strings, enums, uuids and booleans and nothing else —
and because the failure needs to become one of *our* error codes, not a library
exception whose message could carry the rejected value back to the model.

Rejected values never appear in the returned message. A tool call is model
output, and echoing it back is how a prompt injection gets a second chance.
"""

from __future__ import annotations

import re
import uuid
from typing import Any


class ArgumentError(Exception):
    """One reason a tool call's arguments were refused, without the value."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def validate_arguments(schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """Check ``arguments`` against a tool's JSON schema. Returns them coerced.

    Only the shapes the catalogue actually uses are supported; anything else in
    a schema is a programming error and raises loudly at call time rather than
    passing unchecked.
    """
    if schema.get("type") != "object":  # pragma: no cover - catalogue is all objects
        raise ArgumentError("arguments", "unsupported_schema")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ArgumentError("arguments", "expected_object")

    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise ArgumentError(unexpected[0], "unexpected_property")

    for field in required:
        if field not in arguments or arguments[field] is None:
            raise ArgumentError(field, "required")

    cleaned: dict[str, Any] = {}
    for field, value in arguments.items():
        if value is None:
            continue
        cleaned[field] = _validate_value(field, properties[field], value)
    return cleaned


def _validate_value(field: str, spec: dict[str, Any], value: Any) -> Any:
    expected = spec.get("type")

    if expected == "string":
        if not isinstance(value, str):
            raise ArgumentError(field, "expected_string")
        if spec.get("format") == "uuid":
            try:
                return str(uuid.UUID(value))
            except (ValueError, AttributeError):
                raise ArgumentError(field, "expected_uuid") from None
        allowed = spec.get("enum")
        if allowed is not None and value not in allowed:
            raise ArgumentError(field, "not_in_enum")
        minimum = spec.get("minLength")
        maximum = spec.get("maxLength", 500)
        if minimum is not None and len(value) < minimum:
            raise ArgumentError(field, "too_short")
        if len(value) > maximum:
            raise ArgumentError(field, "too_long")
        # Checked after the length bounds, so a pathological string is rejected
        # for its size before any regex runs over it.
        pattern = spec.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise ArgumentError(field, "bad_format")
        return value

    if expected == "boolean":
        if not isinstance(value, bool):
            raise ArgumentError(field, "expected_boolean")
        return value

    if expected in ("integer", "number"):
        # bool is an int in Python, and "taken: true" is not a quantity.
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ArgumentError(field, "expected_number")
        if expected == "integer" and not float(value).is_integer():
            raise ArgumentError(field, "expected_integer")
        minimum, maximum = spec.get("minimum"), spec.get("maximum")
        if minimum is not None and value < minimum:
            raise ArgumentError(field, "below_minimum")
        if maximum is not None and value > maximum:
            raise ArgumentError(field, "above_maximum")
        return int(value) if expected == "integer" else float(value)

    raise ArgumentError(field, "unsupported_type")  # pragma: no cover


__all__ = ["ArgumentError", "validate_arguments"]
