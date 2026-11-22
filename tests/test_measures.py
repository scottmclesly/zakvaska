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


class TestParsingWhatWasTyped:
    """The other direction: cups and ounces in, grams out."""

    def test_a_bare_number_is_read_in_the_unit_on_display(self):
        assert measures.parse_quantity("250", measures.METRIC) == 250.0
        assert measures.parse_quantity("8", measures.US_WEIGHT) == pytest.approx(
            226.796, abs=0.01
        )
        assert measures.parse_quantity(
            "3", measures.US_VOLUME, name="whole rye flour"
        ) == pytest.approx(309.0)

    def test_a_written_unit_beats_the_display_unit(self):
        """"250 g" is grams even while the app is showing cups."""
        assert measures.parse_quantity("250 g", measures.US_VOLUME) == 250.0
        assert measures.parse_quantity(
            "1 cup", measures.METRIC, name="water"
        ) == pytest.approx(236.0)

    def test_a_unit_sticks_to_its_number(self):
        assert measures.parse_quantity("250g") == 250.0
        assert measures.parse_quantity("1.5kg") == 1500.0

    def test_amounts_in_a_row_add_up(self):
        """How a scale says it, and how a manual says it."""
        assert measures.parse_quantity("1 lb 4 oz") == pytest.approx(566.99, abs=0.01)
        assert measures.parse_quantity(
            "2 tbsp + 2 tsp", name="butter"
        ) == pytest.approx(227 * (2 / 16 + 2 / 48))

    def test_fractions_however_they_are_written(self):
        expected = pytest.approx(354.0)
        for text in ("1 1/2 cups", "1½ cups", "1 ½ cups", "1-1/2 cups", "1.5 cups"):
            assert measures.parse_quantity(text, name="water") == expected, text

    def test_a_fraction_on_its_own(self):
        assert measures.parse_quantity("3/4 cup", name="water") == pytest.approx(177.0)
        assert measures.parse_quantity("¼ tsp", name="salt") == pytest.approx(1.5)

    def test_a_unit_with_no_number_is_one_of_them(self):
        assert measures.parse_quantity("a cup", name="water") == pytest.approx(236.0)

    def test_the_manuals_punctuation_and_filler_is_ignored(self):
        assert measures.parse_quantity("about 2 tbsp.", name="water") == pytest.approx(
            29.5
        )
        assert measures.parse_quantity("1,200 g") == 1200.0

    def test_millilitres_go_through_the_density(self):
        assert measures.parse_quantity("500 ml", name="water") == pytest.approx(
            498.76, abs=0.01
        )

    def test_a_blank_field_is_not_an_error(self):
        assert measures.parse_quantity("") is None
        assert measures.parse_quantity("   ") is None
        assert measures.parse_quantity(None) is None

    def test_a_unit_it_does_not_know_says_so(self):
        with pytest.raises(measures.QuantityError) as caught:
            measures.parse_quantity("2 cupz")
        assert "cupz" in str(caught.value)

    def test_nonsense_is_an_error_not_a_zero(self):
        with pytest.raises(measures.QuantityError):
            measures.parse_quantity("lots")

    def test_a_minus_sign_is_not_a_mixed_number_separator(self):
        """"-500" must not come back as 500. "1-1/2" still has to work."""
        with pytest.raises(measures.QuantityError):
            measures.parse_quantity("-500")
        assert measures.parse_quantity("1-1/2 cups", name="water") == pytest.approx(
            354.0
        )

    def test_a_total_is_never_read_as_cups(self):
        """Cups of mixed dough would be a made-up number. See parse_total."""
        assert measures.parse_total("8", measures.US_VOLUME) == pytest.approx(
            226.796, abs=0.01
        )
        assert measures.parse_total("500", measures.METRIC) == 500.0
        # Writing the unit still wins.
        assert measures.parse_total("500 g", measures.US_WEIGHT) == 500.0


class TestFillingAFieldIn:
    """A stored weight has to come back as something that can be typed."""

    def test_grams_stay_bare(self):
        assert measures.input_text(250, measures.METRIC) == "250"
        assert measures.input_text(40.5, measures.METRIC) == "40.5"
        assert measures.input_text(None, measures.METRIC) == ""

    def test_ounces_and_pounds_carry_their_unit(self):
        assert measures.input_text(40, measures.US_WEIGHT) == "1.41 oz"
        # Small amounts get a third decimal, because two of them are a
        # quarter of a gram and 12 g of salt would not survive the trip.
        assert measures.input_text(12, measures.US_WEIGHT) == "0.423 oz"
        assert measures.input_text(453.59237, measures.US_WEIGHT) == "1 lb"
        assert measures.input_text(1000, measures.US_WEIGHT) == "2 lb 3.3 oz"

    def test_a_volume_field_never_says_a_pinch(self):
        """Lovely on a page, untypable in a field."""
        page = measures.measure(0.3, measures.US_VOLUME, name="salt")
        assert page.text == "a pinch"
        assert measures.input_text(0.3, measures.US_VOLUME, name="salt") == "0.05 tsp"

    def test_what_comes_back_can_be_typed_back_in(self):
        for grams in (1.2, 12, 40, 250, 453.6, 1000):
            for unit in (measures.METRIC, measures.US_WEIGHT, measures.US_VOLUME):
                text = measures.input_text(grams, unit, name="bread flour")
                again = measures.parse_quantity(text, unit, name="bread flour")
                # Cups snap to the nearest spoon, which is the deal with
                # volume measurement; grams and ounces are exact.
                tolerance = (
                    0.05 * grams
                    if unit == measures.US_VOLUME
                    else max(0.05, 0.001 * grams)
                )
                assert again == pytest.approx(grams, abs=tolerance), (
                    grams, unit, text,
                )
