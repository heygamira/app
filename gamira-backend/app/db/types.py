"""Column types that behave identically on PostgreSQL and SQLite."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[dt.datetime]):
    """A timestamp that is always stored and returned as aware UTC.

    PostgreSQL returns timezone-aware values from a ``timestamptz`` column;
    SQLite returns naive ones. Comparing the two raises ``TypeError``, so
    normalising here keeps date arithmetic correct on both, and means no caller
    has to remember which database it is talking to.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # A naive value from a client is interpreted as UTC rather than as
            # the server's local time, which would vary by deployment.
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)

    def process_result_value(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)

    def compare_against_backend(self, dialect: Dialect, conn_type: Any) -> bool:
        return isinstance(conn_type, DateTime)
