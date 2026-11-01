"""Celsius is stored; the display unit defaults to Fahrenheit (CLAUDE.md)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.units import (
    c_to_f,
    f_to_c,
    format_temp,
    humanize_delta,
    humanize_since,
    humanize_until,
    temp_in,
    temp_to_celsius,
)


@pytest.mark.parametrize(
    ("celsius", "fahrenheit"),
    [(0, 32), (100, 212), (-40, -40), (24, 75.2), (37, 98.6)],
)
def test_celsius_fahrenheit_conversion(celsius, fahrenheit):
    assert c_to_f(celsius) == pytest.approx(fahrenheit)
    assert f_to_c(fahrenheit) == pytest.approx(celsius)


def test_a_typed_fahrenheit_value_survives_the_round_trip():
    # What the user types in the form must come back out of the database
    # unchanged, or logged temperatures drift every time they are edited.
    assert temp_in(temp_to_celsius(72, "F"), "F") == pytest.approx(72)


def test_celsius_users_are_not_converted():
    assert temp_to_celsius(24, "C") == 24
    assert temp_in(24, "C") == 24


def test_format_temp_rounds_and_labels():
    assert format_temp(24, "F") == "75°F"
    assert format_temp(24, "C") == "24°C"
    assert format_temp(None, "F") == "—"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=30), "just now"),
        (timedelta(minutes=45), "45m"),
        (timedelta(hours=3), "3h"),
        (timedelta(hours=3, minutes=20), "3h 20m"),
        (timedelta(days=2), "2d"),
        (timedelta(days=2, hours=4), "2d 4h"),
    ],
)
def test_humanize_delta(delta, expected):
    assert humanize_delta(delta) == expected


def test_since_and_until_read_naturally(frozen_now):
    earlier = frozen_now - timedelta(hours=5)
    later = frozen_now + timedelta(hours=2)

    assert humanize_since(earlier, frozen_now) == "5h ago"
    assert humanize_until(later, frozen_now) == "in 2h"
    assert humanize_until(earlier, frozen_now) == "5h overdue"
