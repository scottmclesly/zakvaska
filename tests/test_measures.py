"""Reading a stored weight in grams, cups or pounds.

Grams are what we store (CLAUDE.md). These are only readings, and the
volume ones are approximate by nature — a cup of flour depends on how hard
you pack it. The tests pin the arithmetic, not the baking.
"""

from __future__ import annotations

import pytest

from app.models.enums import IngredientRole
from app.services import measures


class TestDensities:
    def test_the_longest_matching_name_wins(self):
        # "whole rye flour" must not be read as plain "flour".
        assert measures.grams_per_cup("Whole rye flour") == 103.0
        assert measures.grams_per_cup("Bread flour") == 120.0

    def test_a_feeding_writes_the_flour_type_the_short_way(self):
        """A jar's flour_type is "whole rye", not "whole rye flour"."""
        assert measures.grams_per_cup("whole rye") == 103.0
        assert measures.grams_per_cup("rye") == 103.0

    def test_matching_ignores_case_and_padding(self):
        assert measures.grams_per_cup("  WATER  ") == 236.0

    def test_an_unknown_name_falls_back_to_the_role(self):
        assert measures.grams_per_cup(
            "Grandma's secret powder", IngredientRole.SALT
        ) == 288.0

    def test_an_unknown_name_and_no_role_still_answers(self):
        assert measures.grams_per_cup("mystery") == measures.FALLBACK_DENSITY

    def test_a_role_can_arrive_as_a_string(self):
        """Templates can only pass strings."""
        assert measures.grams_per_cup("mystery", "water") == 236.0
        assert measures.as_role("flour") is IngredientRole.FLOUR
        assert measures.as_role("not a role") is None


class TestGrams:
    def test_it_trims_pointless_decimals(self):
        assert measures.measure(500.0).text == "500 g"
        assert measures.measure(12.5).text == "12.5 g"

    def test_none_is_not_a_weight(self):
        assert measures.measure(None) is None


class TestUsWeight:
    @pytest.mark.parametrize(
        "grams,expected",
        [
            (453.59237, "1 lb"),
            (907.18474, "2 lb"),
            (1360.77711, "3 lb"),
            (28.349523125, "1 oz"),
            (500, "1 lb 1.6 oz"),
            (10, "0.35 oz"),
        ],
    )
    def test_ounces_and_pounds(self, grams, expected):
        assert measures.measure(grams, measures.US_WEIGHT).text == expected

    def test_it_never_prints_sixteen_ounces(self):
        """15.97 oz must round to 1 lb, not to "0 lb 16 oz"."""
        for grams in range(440, 470):
            text = measures.measure(grams, measures.US_WEIGHT).text
            assert "16 oz" not in text, (grams, text)

    def test_small_amounts_keep_two_decimals(self):
        assert measures.measure(2.5, measures.US_WEIGHT).text == "0.09 oz"


class TestUsVolume:
    def test_a_cup_of_water(self):
        assert measures.measure(236, measures.US_VOLUME, name="water").text == "1 cup"

    def test_cups_are_plural_above_one(self):
        shown = measures.measure(500, measures.US_VOLUME, name="whole rye flour")
        assert shown.text == "4 ⅞ cups"

    def test_a_fraction_of_a_cup_is_singular(self):
        assert measures.measure(
            150, measures.US_VOLUME, name="rye levain"
        ).text == "⅔ cup"

    def test_it_drops_to_tablespoons(self):
        assert measures.measure(
            25, measures.US_VOLUME, name="molasses"
        ).text == "1 ¼ tbsp"

    def test_it_drops_to_teaspoons(self):
        assert measures.measure(10, measures.US_VOLUME, name="salt").text == "1 ⅔ tsp"

    def test_a_trace_is_a_pinch(self):
        assert measures.measure(
            0.1, measures.US_VOLUME, name="salt"
        ).text == "a pinch"

    def test_volume_readings_are_flagged_approximate(self):
        assert measures.measure(236, measures.US_VOLUME, name="water").approximate
        assert not measures.measure(236).approximate
        assert not measures.measure(236, measures.US_WEIGHT).approximate

    def test_the_grams_are_kept_whatever_is_shown(self):
        """The reading changes; the stored number never does."""
        for unit in measures.UNIT_CYCLE:
            assert measures.measure(237.4, unit, name="water").grams == 237.4


class TestTotals:
    def test_a_total_never_goes_to_cups(self):
        """Cups of mixed dough would be a made-up number."""
        assert measures.measure_total(
            1115, measures.US_VOLUME
        ).text == measures.measure_total(1115, measures.US_WEIGHT).text

    def test_a_total_in_grams_is_still_grams(self):
        assert measures.measure_total(1115, measures.METRIC).text == "1115 g"

    def test_none(self):
        assert measures.measure_total(None, measures.METRIC) is None


class TestCycling:
    def test_it_goes_round(self):
        unit = measures.METRIC
        seen = [unit]
        for _ in range(len(measures.UNIT_CYCLE)):
            unit = measures.next_unit(unit)
            seen.append(unit)

        assert seen[:-1] == list(measures.UNIT_CYCLE)
        assert seen[-1] == measures.METRIC

    def test_an_unknown_unit_lands_back_on_grams(self):
        assert measures.next_unit("furlongs") == measures.METRIC

    def test_every_unit_has_a_label(self):
        assert set(measures.UNIT_LABELS) == set(measures.UNIT_CYCLE)
