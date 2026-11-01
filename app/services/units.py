"""Unit handling.

Grams and Celsius in the database; the display unit is a user setting that
defaults to Fahrenheit (CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta

TEMP_UNITS = ("C", "F")


def c_to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def temp_in(celsius: float | None, unit: str) -> float | None:
    """Convert a stored Celsius value into the display unit."""
    if celsius is None:
        return None
    return c_to_f(celsius) if unit.upper() == "F" else celsius


def temp_to_celsius(value: float | None, unit: str) -> float | None:
    """Convert a value the user typed, in their unit, back to Celsius."""
    if value is None:
        return None
    return f_to_c(value) if unit.upper() == "F" else value


def format_temp(celsius: float | None, unit: str) -> str:
    converted = temp_in(celsius, unit)
    if converted is None:
        return "—"
    return f"{converted:.0f}°{unit.upper()}"


def humanize_delta(delta: timedelta, *, suffix: str = "") -> str:
    """'3h 20m', '2d 4h', 'just now' — short enough for a dashboard card."""
    seconds = int(abs(delta).total_seconds())
    if seconds < 60:
        return "just now" if not suffix else f"moments {suffix}"

    minutes, _ = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    if days:
        text = f"{days}d {hours}h" if hours else f"{days}d"
    elif hours:
        text = f"{hours}h {minutes}m" if minutes else f"{hours}h"
    else:
        text = f"{minutes}m"

    return f"{text} {suffix}".strip()


def humanize_since(moment: datetime, now: datetime) -> str:
    return humanize_delta(now - moment, suffix="ago")


def humanize_until(moment: datetime, now: datetime) -> str:
    if moment <= now:
        return humanize_delta(now - moment, suffix="overdue")
    return f"in {humanize_delta(moment - now)}"
