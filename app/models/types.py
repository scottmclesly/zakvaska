"""Custom column types.

SQLite has no native timestamp type: SQLAlchemy's DateTime(timezone=True)
happily *stores* an aware datetime but hands back a naive one, so a later
.astimezone() would silently read it as local time. CLAUDE.md requires UTC
storage, so the conversion is enforced here instead of trusted to callers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """A datetime that is always stored as UTC and always loaded as aware UTC.

    Naive values are rejected rather than guessed at: in a lab notebook a
    timestamp that is quietly five hours out is worse than an error.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime passed to a UtcDateTime column; "
                "use app.models.base.utcnow() or attach a timezone"
            )
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
