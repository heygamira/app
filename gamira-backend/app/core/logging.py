"""Structured logging with a per-request correlation id.

Every log record carries the request id of the request that produced it, so a
single user-visible failure can be traced across services and jobs.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from typing import Any

from pythonjsonlogger.json import JsonFormatter

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def current_request_id() -> str:
    return request_id_var.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


# Everything the logging module puts on a record by itself. Anything else came
# from a caller's `extra=` and is worth printing.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {
    "request_id",
    "message",
    "asctime",
    "taskName",
    # uvicorn attaches an ANSI-coloured copy of its own message; printing it
    # would double every startup line.
    "color_message",
}


class ConsoleFormatter(logging.Formatter):
    """Human-readable single line, including the caller's ``extra`` fields.

    Without the extras an access line reads only ``request_completed``: the
    method, path, status and duration are all in ``extra``, and dropping them
    makes the local console useless for following what the API is doing.
    """

    default_fmt = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self.default_fmt)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = " ".join(
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        )
        return f"{line} {extras}" if extras else line


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    formatter: logging.Formatter
    if fmt == "json":
        formatter = JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            rename_fields={"asctime": "time", "levelname": "level", "name": "logger"},
        )
    else:
        formatter = ConsoleFormatter()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_context(**fields: Any) -> dict[str, Any]:
    """Wrap extra fields so JSON and console formatters both stay readable."""
    return {"extra": fields}
