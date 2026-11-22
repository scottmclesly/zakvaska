"""Helpers for reading HTML form values.

Browsers send "" for an untouched optional field, and datetime-local inputs
send wall-clock time with no zone. Both need handling in one place rather
than in every route.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.models.enums import IngredientRole
from app.services import measures


def opt_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def opt_float(value: str | None, *, field: str) -> float | None:
    cleaned = opt_str(value)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"{field} must be a number") from None


def req_float(value: str | None, *, field: str) -> float:
    parsed = opt_float(value, field=field)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def opt_weight(
    value: str | None,
    unit: str = measures.METRIC,
    *,
    field: str,
    name: str | None = None,
    role: IngredientRole | str | None = None,
) -> float | None:
    """A weight field, in whatever unit the user is working in, as grams.

    The field takes "250 g", "8 oz", "1 lb 2 oz" or "1 1/2 cups" whatever the
    display unit is; a bare number is read in the unit on display. Grams are
    what gets stored (CLAUDE.md). See measures.parse_quantity.
    """
    try:
        return measures.parse_quantity(value, unit, name=name, role=role)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from None


def req_weight(
    value: str | None,
    unit: str = measures.METRIC,
    *,
    field: str,
    name: str | None = None,
    role: IngredientRole | str | None = None,
) -> float:
    parsed = opt_weight(value, unit, field=field, name=name, role=role)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def opt_total_weight(
    value: str | None, unit: str = measures.METRIC, *, field: str
) -> float | None:
    """A total flour or dough weight — never read as cups. See parse_total."""
    try:
        return measures.parse_total(value, unit)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from None


def opt_int(value: str | None, *, field: str) -> int | None:
    parsed = opt_float(value, field=field)
    return None if parsed is None else int(parsed)


def local_to_utc(value: str | None, tz: ZoneInfo, *, default: datetime) -> datetime:
    """Turn a datetime-local field into an aware UTC datetime.

    The browser sends local wall-clock with no offset, so it is interpreted in
    the configured zone and converted. Storage is always UTC (CLAUDE.md).
    """
    cleaned = opt_str(value)
    if cleaned is None:
        return default
    try:
        naive = datetime.fromisoformat(cleaned)
    except ValueError:
        raise ValueError("Enter a valid date and time") from None
    if naive.tzinfo is not None:
        return naive.astimezone(ZoneInfo("UTC"))
    return naive.replace(tzinfo=tz).astimezone(ZoneInfo("UTC"))


def utc_to_local_input(moment: datetime, tz: ZoneInfo) -> str:
    """Format a UTC datetime for a datetime-local input's value attribute."""
    return moment.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


def checkbox(value: str | None) -> bool:
    # Unchecked boxes are simply absent from the submission.
    return value is not None
