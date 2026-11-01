"""Baker's percentages into grams.

The arithmetic is the whole point of a recipe page, so it is pinned down
here against a real Borodinsky rather than toy numbers.
"""

from __future__ import annotations

import pytest

from app.models.enums import IngredientRole
from app.services import scaling
from app.services.recipes import IngredientSpec


class Row:
    """A stand-in for RecipeIngredient: scaling only reads these attributes."""

    def __init__(self, name: str, role: IngredientRole, baker_pct: float):
        self.name = name
        self.role = role
        self.baker_pct = baker_pct
        self.notes = None


def borodinsky() -> list[Row]:
    return [
        Row("Whole rye flour", IngredientRole.FLOUR, 100.0),
        Row("Water", IngredientRole.WATER, 80.0),
        Row("Rye levain", IngredientRole.LEVAIN, 30.0),
        Row("Red rye malt", IngredientRole.OTHER, 5.0),
        Row("Molasses", IngredientRole.SWEETENER, 5.0),
        Row("Salt", IngredientRole.SALT, 2.0),
        Row("Coriander", IngredientRole.OTHER, 1.0),
    ]


class TestScaleToFlour:
    def test_borodinsky_at_500g_flour(self):
        """Phase 3 acceptance: 500 g flour gives these exact grams."""
        scaled = scaling.scale_to_flour(borodinsky(), 500)

        assert [round(i.grams, 4) for i in scaled.ingredients] == [
            500.0,  # 100% flour
            400.0,  # 80% water
            150.0,  # 30% levain
            25.0,  # 5% malt
            25.0,  # 5% molasses
            10.0,  # 2% salt
            5.0,  # 1% coriander
        ]
        assert scaled.total_flour_g == pytest.approx(500.0)
        assert scaled.total_dough_g == pytest.approx(1115.0)
        assert scaled.warnings == []

    def test_hydration_is_added_water_over_flour(self):
        scaled = scaling.scale_to_flour(borodinsky(), 500)
        # Levain is not decomposed, so this is added water only.
        assert scaled.hydration_pct == pytest.approx(80.0)

    def test_percentages_are_kept_alongside_the_grams(self):
        scaled = scaling.scale_to_flour(borodinsky(), 500)
        assert scaled.flour_pct == pytest.approx(100.0)
        assert scaled.total_pct == pytest.approx(223.0)

    def test_order_is_preserved(self):
        scaled = scaling.scale_to_flour(borodinsky(), 500)
        assert [i.name for i in scaled.ingredients] == [
            r.name for r in borodinsky()
        ]

    def test_two_flours_split_the_hundred_percent(self):
        rows = [
            Row("Whole rye", IngredientRole.FLOUR, 70.0),
            Row("Bread flour", IngredientRole.FLOUR, 30.0),
            Row("Water", IngredientRole.WATER, 75.0),
        ]
        scaled = scaling.scale_to_flour(rows, 1000)
        assert [i.grams for i in scaled.ingredients] == [700.0, 300.0, 750.0]
        assert scaled.total_flour_g == pytest.approx(1000.0)
        assert scaled.warnings == []

    def test_negative_flour_is_refused(self):
        with pytest.raises(ValueError):
            scaling.scale_to_flour(borodinsky(), -1)

    def test_zero_flour_gives_zero_grams_not_an_error(self):
        scaled = scaling.scale_to_flour(borodinsky(), 0)
        assert all(i.grams == 0 for i in scaled.ingredients)


class TestScaleToDoughWeight:
    def test_round_trips_with_scale_to_flour(self):
        """1115 g of dough is exactly the 500 g flour recipe."""
        scaled = scaling.scale_to_dough_weight(borodinsky(), 1115)
        assert scaled.total_flour_g == pytest.approx(500.0)
        assert scaled.total_dough_g == pytest.approx(1115.0)
        assert [round(i.grams, 4) for i in scaled.ingredients] == [
            500.0, 400.0, 150.0, 25.0, 25.0, 10.0, 5.0
        ]

    def test_a_target_the_bread_maker_pan_can_hold(self):
        scaled = scaling.scale_to_dough_weight(borodinsky(), 900)
        assert scaled.total_dough_g == pytest.approx(900.0)
        # Everything still in proportion.
        assert scaled.ingredients[1].grams == pytest.approx(
            scaled.total_flour_g * 0.8
        )

    def test_negative_target_is_refused(self):
        with pytest.raises(ValueError):
            scaling.scale_to_dough_weight(borodinsky(), -5)


class TestWarnings:
    def test_flour_not_adding_to_a_hundred_warns_but_still_scales(self):
        rows = [
            Row("Whole rye", IngredientRole.FLOUR, 90.0),
            Row("Water", IngredientRole.WATER, 80.0),
        ]
        scaled = scaling.scale_to_flour(rows, 500)
        assert scaled.warnings
        assert "90%" in scaled.warnings[0]
        # A half-written recipe is still shown, not blocked.
        assert scaled.ingredients[0].grams == pytest.approx(450.0)

    def test_no_flour_at_all_warns(self):
        rows = [Row("Water", IngredientRole.WATER, 80.0)]
        scaled = scaling.scale_to_flour(rows, 500)
        assert scaled.warnings
        assert scaled.hydration_pct is None

    def test_empty_recipe_warns(self):
        scaled = scaling.scale_to_flour([], 500)
        assert scaled.warnings == ["This version has no ingredients yet."]


class TestPercentageHelpers:
    def test_flour_percentage_counts_only_flour(self):
        assert scaling.flour_percentage(borodinsky()) == pytest.approx(100.0)

    def test_total_percentage_counts_everything(self):
        assert scaling.total_percentage(borodinsky()) == pytest.approx(223.0)

    def test_specs_work_too(self):
        """IngredientSpec has the same shape, so the form can preview."""
        specs = [
            IngredientSpec("Rye", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 80.0),
        ]
        assert scaling.flour_percentage(specs) == pytest.approx(100.0)
        scaled = scaling.scale_to_flour(specs, 200)
        assert [i.grams for i in scaled.ingredients] == [200.0, 160.0]
