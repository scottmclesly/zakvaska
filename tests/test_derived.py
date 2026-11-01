"""The derived values Phase 1's acceptance check calls out by name."""

from __future__ import annotations

import pytest

from app.services.derived import feeding_ratio, hydration_pct, rise_pct


class TestFeedingRatio:
    @pytest.mark.parametrize(
        ("starter", "flour", "water", "expected"),
        [
            (20, 40, 40, "1:2:2"),        # the textbook 1:2:2
            (50, 50, 50, "1:1:1"),        # equal parts
            (10, 50, 50, "1:5:5"),        # a big build
            (20, 30, 30, "1:1.5:1.5"),    # halves survive
            (50, 50, 40, "1:1:0.8"),      # stiffer than 100%
            (30, 10, 10, "1:0.33:0.33"),  # mostly starter, 2 dp
        ],
    )
    def test_normalises_to_one_part_starter(self, starter, flour, water, expected):
        assert feeding_ratio(starter, flour, water) == expected

    def test_trailing_zeros_are_trimmed(self):
        assert feeding_ratio(10, 20, 20) == "1:2:2"  # not "1:2.00:2.00"

    @pytest.mark.parametrize("starter", [0, -5])
    def test_no_ratio_without_starter(self, starter):
        # A build from scratch has nothing to normalise against.
        assert feeding_ratio(starter, 50, 50) is None


class TestHydration:
    @pytest.mark.parametrize(
        ("flour", "water", "expected"),
        [
            (100, 100, 100.0),   # the usual 100% feed
            (100, 80, 80.0),     # stiff
            (100, 125, 125.0),   # slack rye, as Borodinsky tends to be
            (40, 40, 100.0),     # scale-independent
        ],
    )
    def test_water_as_a_percentage_of_flour(self, flour, water, expected):
        assert hydration_pct(flour, water) == pytest.approx(expected)

    def test_is_scale_independent(self):
        assert hydration_pct(40, 40) == hydration_pct(400, 400)

    @pytest.mark.parametrize("flour", [0, -1])
    def test_no_hydration_without_flour(self, flour):
        assert hydration_pct(flour, 50) is None


class TestRise:
    @pytest.mark.parametrize(
        ("start", "now", "expected"),
        [
            (20, 50, 150.0),   # tripled
            (20, 40, 100.0),   # doubled
            (20, 20, 0.0),     # went nowhere
            (40, 30, -25.0),   # collapsed back
        ],
    )
    def test_percentage_of_starting_height(self, start, now, expected):
        assert rise_pct(start, now) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("start", "now"),
        [(None, 50), (20, None), (None, None), (0, 50)],
    )
    def test_needs_both_heights_and_a_real_baseline(self, start, now):
        assert rise_pct(start, now) is None
