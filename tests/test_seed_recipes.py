"""The seeded recipes themselves: the manual's, the demo, and the classics.

test_seeding.py covers the safety rules. This file covers the data —
whether what goes in is the formula the source actually gives, whether
every recipe says where it came from, and whether a machine recipe
arrives knowing which program it wants.
"""

from __future__ import annotations

import html
import re

import pytest

from app.data import westbend
from app.data.classic_recipes import SKIPPED
from app.data.classic_recipes import RECIPES as CLASSICS
from app.data.demo_recipes import RECIPES as DEMO
from app.data.recipes import RECIPES
from app.data.westbend_recipes import RECIPES as WESTBEND
from app.models.enums import IngredientRole, RecipeCategory
from app.models.recipe import Recipe, RecipeVersion
from app.services import seeding
from app.services.units import f_to_c
from tests.test_recipe_routes import BORODINSKY


class TestTheDataIsWellFormed:
    def test_it_is_the_three_sets_and_nothing_else(self):
        assert len(RECIPES) == len(WESTBEND) + len(DEMO) + len(CLASSICS)
        assert len(RECIPES) == 33

    def test_every_name_is_unique(self):
        names = [spec["name"] for spec in RECIPES]
        assert len(set(names)) == len(names)

    def test_flour_sums_to_a_hundred_percent(self):
        """The whole point of baker's percentages. A tenth either way is rounding."""
        for spec in RECIPES:
            flour = sum(
                item["pct"] for item in spec["ingredients"]
                if item["role"] == "flour"
            )
            assert 99.4 < flour < 100.6, f"{spec['name']}: flour is {flour}%"

    def test_every_recipe_has_flour_and_water(self):
        for spec in RECIPES:
            roles = {item["role"] for item in spec["ingredients"]}
            assert "flour" in roles, spec["name"]
            assert "water" in roles, spec["name"]

    def test_every_bread_is_salted(self):
        """Pasta dough is the one exception, and the manual means it."""
        for spec in RECIPES:
            roles = {item["role"] for item in spec["ingredients"]}
            if spec["name"] == "Basic Pasta Dough":
                assert "salt" not in roles, "the manual's pasta has none"
                continue
            assert "salt" in roles, spec["name"]

    def test_the_roles_and_categories_are_real_enum_values(self):
        for spec in RECIPES:
            RecipeCategory(spec["category"])
            for item in spec["ingredients"]:
                IngredientRole(item["role"])

    def test_every_recipe_says_where_it_came_from(self):
        for spec in RECIPES:
            assert spec["source"], spec["name"]
            assert spec["source_ref"], spec["name"]

    def test_every_recipe_is_marked_untested(self):
        """None of this has been baked in this kitchen. Say so."""
        for spec in RECIPES:
            assert "reference v1 — untested" in spec["notes"], spec["name"]

    def test_no_percentage_is_absurd(self):
        for spec in RECIPES:
            for item in spec["ingredients"]:
                assert 0 < item["pct"] <= 210, (spec["name"], item["name"])

    def test_stage_durations_and_temps_are_sane(self):
        for spec in RECIPES:
            for stage in spec["stages"]:
                if stage.get("min") is not None:
                    assert 0 < stage["min"] <= 3000, (spec["name"], stage["name"])
                if stage.get("temp_c") is not None:
                    assert 0 < stage["temp_c"] <= 260, (spec["name"], stage["name"])


class TestTheManualsRecipes:
    def test_all_eighteen_are_there(self):
        assert len(WESTBEND) == 18

    def test_they_all_credit_the_manual_with_a_page(self):
        for spec in WESTBEND:
            assert spec["source"] == "West Bend L5951 manual"
            assert re.fullmatch(r"p\. \d+", spec["source_ref"]), spec["name"]

    def test_they_all_name_a_program_the_machine_actually_has(self):
        known = {program["name"] for program in westbend.PROGRAMS}
        for spec in WESTBEND:
            assert spec["program"] in known, spec["name"]

    def test_they_keep_the_manuals_own_wording(self):
        """The cups are the authority; the percentage is derived from them."""
        for spec in WESTBEND:
            wording = [item["notes"] for item in spec["ingredients"]]
            assert all(wording), spec["name"]
            assert any(
                "cup" in (note or "") or "tbsp" in (note or "") or "tsp" in (note or "")
                for note in wording
            ), spec["name"]

    def test_a_machine_loaf_carries_no_stages(self):
        """The program is the schedule — copying its segments here would go stale."""
        loaf = next(s for s in WESTBEND if s["name"] == "Old Fashioned White Bread")
        assert loaf["stages"] == []
        assert loaf["loaf_size"] == "2 lb"

    def test_the_two_that_leave_the_machine_carry_the_stages(self):
        for name in ("Pizza Dough", "Basic Dinner Rolls / Bread Sticks"):
            spec = next(s for s in WESTBEND if s["name"] == name)
            assert spec["stages"], name
            assert spec["program"] == "Dough"


class TestTheDemoBorodinsky:
    def test_it_is_the_fixture_recipe_under_its_own_name(self):
        spec = DEMO[0]
        assert spec["name"] == "Borodinsky (demo)"
        assert spec["category"] == BORODINSKY["category"]
        assert "first attempt" in spec["notes"]

    def test_the_ingredients_match_the_fixture_line_for_line(self):
        spec = DEMO[0]
        assert [item["name"] for item in spec["ingredients"]] == (
            BORODINSKY["ingredient_name"]
        )
        assert [item["role"] for item in spec["ingredients"]] == (
            BORODINSKY["ingredient_role"]
        )
        assert [item["pct"] for item in spec["ingredients"]] == [
            float(pct) for pct in BORODINSKY["ingredient_pct"]
        ]
        assert [item["notes"] or "" for item in spec["ingredients"]] == (
            BORODINSKY["ingredient_notes"]
        )

    def test_the_stages_match_the_fixture_with_the_temps_converted(self):
        """The fixture types Fahrenheit into a form; the database stores Celsius."""
        spec = DEMO[0]
        assert [stage["name"] for stage in spec["stages"]] == (
            BORODINSKY["stage_name"]
        )
        assert [stage["min"] for stage in spec["stages"]] == [
            int(minutes) for minutes in BORODINSKY["stage_duration"]
        ]
        assert [stage["temp_c"] for stage in spec["stages"]] == [
            round(f_to_c(float(temp)), 2) if temp else None
            for temp in BORODINSKY["stage_temp"]
        ]

    def test_the_scald_is_held_at_sixty_five_not_a_hundred_and_fifty(self):
        scald = DEMO[0]["stages"][0]
        assert scald["name"] == "scald (zavarka)"
        assert scald["temp_c"] == 65.56


class TestTheClassics:
    def test_fourteen_made_the_cut(self):
        assert len(CLASSICS) == 14

    def test_every_one_cites_a_book_or_a_page_not_a_vibe(self):
        for spec in CLASSICS:
            ref = spec["source_ref"]
            assert "." in ref and len(ref) > 12, spec["name"]

    def test_every_one_has_stages_with_a_bake(self):
        for spec in CLASSICS:
            assert spec["stages"], spec["name"]
            assert any("bake" in stage["name"] for stage in spec["stages"]), (
                spec["name"]
            )

    def test_every_one_says_what_it_is_baked_in_and_what_leavens_it(self):
        for spec in CLASSICS:
            notes = spec["notes"]
            assert "Oven" in notes or "Cast-iron pot" in notes, spec["name"]
            assert "starter" in notes or "levain" in notes or "yeast" in notes, (
                spec["name"]
            )

    def test_the_rye_breads_want_the_rye_starter(self):
        for name in (
            "Borodinsky (traditional scald)",
            "Latvian rupjmaize (coarse rye)",
            "Danish rugbrød",
        ):
            spec = next(s for s in CLASSICS if s["name"] == name)
            assert "rye starter" in spec["notes"]
            assert spec["category"] == "rye"

    def test_the_traditional_borodinsky_is_not_the_demo_one(self):
        """Two Borodinskys on purpose: round numbers, and Auerman's actual ones."""
        traditional = next(
            s for s in CLASSICS if s["name"] == "Borodinsky (traditional scald)"
        )
        assert traditional["source"] != DEMO[0]["source"]
        pcts = {item["name"]: item["pct"] for item in traditional["ingredients"]}
        assert pcts["Whole rye flour"] == 63.6, "not the demo's round 100%"
        assert "Medium rye flour" in pcts

    def test_the_tangzhong_note_points_at_the_baton(self):
        """Why it is in the list at all: it is the trick for a fluffier baton."""
        spec = next(s for s in CLASSICS if "milk bread" in s["name"])
        assert "baton" in spec["notes"]

    def test_the_skipped_ones_are_named_with_a_reason(self):
        """Asked for, not found, not invented."""
        assert len(SKIPPED) == 5
        names = {name for name, _ in SKIPPED}
        assert "Darnitsky" in names
        assert "Russian white baton (nareznoy)" in names
        for name, why in SKIPPED:
            assert len(why) > 40, name

    def test_nothing_skipped_was_quietly_seeded_anyway(self):
        seeded = {spec["name"] for spec in RECIPES}
        for name, _ in SKIPPED:
            assert name not in seeded


class TestWhatSeedingActuallyWrites:
    def test_every_recipe_arrives_with_one_version(self, session):
        seeding.seed_all(session)
        session.commit()
        assert session.query(Recipe).count() == len(RECIPES)
        for recipe in session.query(Recipe).all():
            assert len(recipe.versions) == 1
            assert recipe.latest_version.ingredients

    def test_the_sources_are_written_to_the_rows(self, session):
        seeding.seed_all(session)
        session.commit()
        recipe = seeding.find_recipe(
            session, "Classic Rye Bread", "West Bend L5951 manual"
        )
        assert recipe is not None
        assert recipe.source == "West Bend L5951 manual"
        assert recipe.source_ref.startswith("p. ")

    def test_a_machine_recipe_knows_its_program_and_size(self, session):
        seeding.seed_all(session)
        session.commit()
        recipe = seeding.find_recipe(
            session, "100% Whole Wheat Bread", "West Bend L5951 manual"
        )
        version = recipe.latest_version
        assert version.default_program is not None
        assert version.default_program.name == "Whole Wheat"
        assert version.default_program.device == "West Bend L5951"
        assert version.default_loaf_size == "2 lb"

    def test_a_manual_recipe_keeps_the_batch_it_was_written_at(self, session):
        """The manual writes cups, so the recipe can show cups unprompted."""
        seeding.seed_all(session)
        session.commit()
        recipe = seeding.find_recipe(
            session, "Classic Rye Bread", "West Bend L5951 manual"
        )
        version = recipe.latest_version
        assert version.batch_flour_g is not None
        # A 2 lb machine loaf: a few cups of flour, not a bakery's sack.
        assert 300 < version.batch_flour_g < 800
        # And the batch really is the 100% the percentages are against.
        flour = sum(
            i.baker_pct
            for i in version.ingredients
            if i.role.value == "flour"
        )
        assert flour == pytest.approx(100.0, abs=0.2)

    def test_a_recipe_given_as_percentages_has_no_batch(self, session):
        seeding.seed_all(session)
        session.commit()
        recipe = seeding.find_recipe(
            session, "Latvian rupjmaize (coarse rye)", "Stanley Ginsberg, The Rye Baker"
        )
        assert recipe.latest_version.batch_flour_g is None

    def test_an_oven_recipe_has_no_program(self, session):
        seeding.seed_all(session)
        session.commit()
        recipe = seeding.find_recipe(
            session, "Latvian rupjmaize (coarse rye)", "Stanley Ginsberg, The Rye Baker"
        )
        assert recipe.latest_version.default_program_id is None

    def test_the_stages_keep_their_order(self, session):
        seeding.seed_all(session)
        session.commit()
        recipe = seeding.find_recipe(
            session, "Borodinsky (demo)", "zakvaska"
        )
        stages = recipe.latest_version.stages
        assert [stage.name for stage in stages] == BORODINSKY["stage_name"]
        assert [stage.seq for stage in stages] == [0, 1, 2, 3, 4]

    def test_twenty_versions_carry_a_program(self, session):
        """The 18 machine recipes, plus challah and milk bread for the kneading."""
        seeding.seed_all(session)
        session.commit()
        with_program = (
            session.query(RecipeVersion)
            .filter(RecipeVersion.default_program_id.isnot(None))
            .count()
        )
        assert with_program == 20


class TestTheRecipesPage:
    def test_it_lists_everything_that_was_seeded(self, client, session):
        seeding.seed_all(session)
        session.commit()
        # Unescaped, because Jinja turns the apostrophe in "Wheat 'N Yogurt"
        # into an entity on the way out.
        page = html.unescape(client.get("/recipes").text)
        for spec in RECIPES:
            assert spec["name"] in page, spec["name"]

    def test_it_shows_where_each_formula_came_from(self, client, session):
        seeding.seed_all(session)
        session.commit()
        page = client.get("/recipes").text
        assert "West Bend L5951 manual" in page
        assert "Stanley Ginsberg, The Rye Baker" in page
        assert "King Arthur Baking" in page

    def test_it_shows_the_bread_maker_defaults(self, client, session):
        seeding.seed_all(session)
        session.commit()
        page = client.get("/recipes").text
        assert re.search(r"Bread maker:\s*Whole Wheat,\s*2 lb", page)
