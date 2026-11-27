"""The cards on the two browsing pages: recipes and bakes."""

from __future__ import annotations

import io

from PIL import Image

from app.models.enums import (
    BakeStatus, IngredientRole, PhotoOwner, RecipeCategory,
)
from app.services import bakes as bake_service
from app.services import browse, demo
from app.services import photos as photo_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec


def _recipe(session, name, category=RecipeCategory.WHEAT, water=70.0, stages=(60,)):
    return recipe_service.create_recipe(
        session,
        name=name,
        category=category,
        ingredients=[
            IngredientSpec(name="Flour", role=IngredientRole.FLOUR, baker_pct=100.0),
            IngredientSpec(name="Water", role=IngredientRole.WATER, baker_pct=water),
        ],
        stages=[StageSpec(name=f"stage {n}", duration_min=m) for n, m in enumerate(stages)],
    )


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 40)).save(out, "JPEG")
    return out.getvalue()


def _baked(session, recipe, when, rating=None, photo=False):
    bake = bake_service.start_bake(
        session, recipe.latest_version, started_at=when,
        status=BakeStatus.IN_PROGRESS,
    )
    if rating:
        bake_service.save_result(session, bake, rating=rating, now=when)
    if photo:
        photo_service.attach(
            session, owner_type=PhotoOwner.BAKE, owner_id=bake.id,
            data=_jpeg(), now=when,
        )
    return bake


class TestShape:
    def test_the_family_decides_by_default(self, session):
        assert browse.loaf_shape(_recipe(session, "Country loaf")) == "wheat"
        rye = _recipe(session, "Borodinsky", RecipeCategory.RYE)
        assert browse.loaf_shape(rye) == "rye"

    def test_a_name_that_is_a_shape_wins(self, session):
        assert browse.loaf_shape(_recipe(session, "Baguette with poolish")) == "baguette"
        assert browse.loaf_shape(_recipe(session, "Focaccia")) == "flat"
        assert browse.loaf_shape(_recipe(session, "Basic Dinner Rolls")) == "rolls"
        ring = _recipe(session, "Finnish ruisleipä (ring rye)", RecipeCategory.RYE)
        assert browse.loaf_shape(ring) == "ring"

    def test_every_shape_has_words_for_a_screen_reader(self):
        for shape in ("rye", "wheat", "enriched", "other", "tin",
                      "baguette", "flat", "rolls", "ring"):
            assert browse.SHAPE_LABELS[shape]

    def test_the_library_is_not_all_one_loaf(self, session):
        """Thirty cards with the same drawing is what this was written to end."""
        demo.load_library(session)
        shapes = {browse.loaf_shape(r) for r in recipe_service.list_recipes(session)}
        assert len(shapes) >= 6


class TestRecipeCards:
    def test_the_numbers_a_baker_reads(self, session):
        recipe = _recipe(session, "Plain", water=72.0, stages=(240, 60, 45))
        (card,) = browse.recipe_cards(session, [recipe])
        assert card.hydration == 72
        assert card.total_min == 345
        assert card.baked == 0 and card.cover is None and card.best_rating is None

    def test_water_that_is_not_what_wets_the_dough_is_not_quoted(self, session):
        brioche = _recipe(session, "Brioche", RecipeCategory.ENRICHED, water=9.0)
        (card,) = browse.recipe_cards(session, [brioche])
        assert card.hydration is None

    def test_the_best_photographed_loaf_is_the_cover(self, session, frozen_now):
        from datetime import timedelta

        recipe = _recipe(session, "Plain")
        _baked(session, recipe, frozen_now - timedelta(days=3), rating=2, photo=True)
        best = _baked(session, recipe, frozen_now - timedelta(days=2), rating=5, photo=True)
        _baked(session, recipe, frozen_now - timedelta(days=1), rating=5)  # no photo
        (card,) = browse.recipe_cards(session, [recipe])
        assert card.baked == 3
        assert card.best_rating == 5
        assert card.cover.owner_id == best.id

    def test_a_planned_bake_is_not_a_loaf_yet(self, session):
        recipe = _recipe(session, "Plain")
        bake_service.start_bake(session, recipe.latest_version)
        (card,) = browse.recipe_cards(session, [recipe])
        assert card.baked == 0

    def test_time_as_people_say_it(self):
        assert browse.time_label(None) is None
        assert browse.time_label(45) == "45 min"
        assert browse.time_label(210) == "3.5 h"
        assert browse.time_label(180) == "3 h"
        assert browse.time_label(16 * 60 + 10) == "16 h"
        assert browse.time_label(51 * 60) == "2 days"


class TestBakeCards:
    def test_cover_count_and_summary(self, session, frozen_now):
        recipe = _recipe(session, "Plain")
        with_photo = _baked(session, recipe, frozen_now, rating=4, photo=True)
        photo_service.attach(
            session, owner_type=PhotoOwner.BAKE, owner_id=with_photo.id,
            data=_jpeg(), now=frozen_now,
        )
        _baked(session, recipe, frozen_now, rating=2)
        cards = browse.bake_cards(session, bake_service.list_bakes(session))
        by_id = {c.bake.id: c for c in cards}
        assert by_id[with_photo.id].photos == 2
        assert by_id[with_photo.id].cover is not None
        summary = browse.bake_summary(cards)
        assert (summary.loaves, summary.photographed, summary.rated) == (2, 1, 2)
        assert summary.average == 3.0

    def test_nothing_rated_has_no_average(self, session, frozen_now):
        _baked(session, _recipe(session, "Plain"), frozen_now)
        cards = browse.bake_cards(session, bake_service.list_bakes(session))
        assert browse.bake_summary(cards).average is None


class TestPages:
    def test_a_photographed_loaf_leads_its_card_and_its_recipe(
        self, client, session, frozen_now
    ):
        recipe = _recipe(session, "Plain")
        bake = _baked(session, recipe, frozen_now, rating=4, photo=True)
        session.commit()

        bakes = client.get("/bakes").text
        assert 'class="bake-shot has-photo"' in bakes
        assert "data-featured" in bakes
        assert f'href="/bakes/{bake.id}"' in bakes
        assert "<strong>1</strong> loaf" in bakes

        recipes = client.get("/recipes").text
        assert 'class="recipe-loaf has-photo"' in recipes
        assert "Baked 1&times;" in recipes

    def test_filtering_hangs_nothing_larger(self, client, session, frozen_now):
        recipe = _recipe(session, "Plain")
        _baked(session, recipe, frozen_now, rating=4, photo=True)
        session.commit()
        assert "data-featured" not in client.get(f"/bakes?recipe={recipe.id}").text

    def test_an_unphotographed_loaf_is_drawn(self, client, session, frozen_now):
        _baked(session, _recipe(session, "Baguette"), frozen_now)
        session.commit()
        page = client.get("/bakes").text
        assert 'class="bake-shot"' in page
        assert 'aria-label="a baguette"' in page


class TestShelves:
    def test_what_you_have_baked_comes_first_best_loaf_first(self, session, frozen_now):
        plain = _recipe(session, "Plain")
        better = _recipe(session, "Better")
        _recipe(session, "Untried")
        _baked(session, plain, frozen_now, rating=3)
        _baked(session, better, frozen_now, rating=5)
        cards = browse.recipe_cards(session, recipe_service.list_recipes(session))

        shelves = browse.recipe_shelves(cards)

        assert shelves[0].key == "baked"
        assert [c.recipe.name for c in shelves[0].cards] == ["Better", "Plain"]

    def test_then_a_shelf_for_each_family_that_has_any(self, session):
        _recipe(session, "Boule")
        _recipe(session, "Borodinsky", RecipeCategory.RYE)
        cards = browse.recipe_cards(session, recipe_service.list_recipes(session))

        shelves = browse.recipe_shelves(cards)

        # Nothing baked, so no shelf for it; and no empty shelves.
        assert [shelf.key for shelf in shelves] == ["rye", "wheat"]
        assert all(shelf.cards and shelf.label and shelf.blurb for shelf in shelves)

    def test_a_baked_recipe_is_also_on_its_own_family_s_shelf(self, session, frozen_now):
        recipe = _recipe(session, "Boule")
        _baked(session, recipe, frozen_now, rating=4)
        cards = browse.recipe_cards(session, [recipe])
        shelves = {shelf.key: shelf for shelf in browse.recipe_shelves(cards)}
        assert [c.recipe.name for c in shelves["baked"].cards] == ["Boule"]
        assert [c.recipe.name for c in shelves["wheat"].cards] == ["Boule"]

    def test_the_page_is_shelves_with_arrows_and_a_row_each(self, client, session):
        demo.load_library(session)
        session.commit()
        page = client.get("/recipes").text

        shelves = page.count('<section class="recipe-shelf"')
        assert shelves >= 3
        assert page.count("data-shelf-row") == shelves
        assert page.count('data-shelf-step="1"') == shelves
        # The drawn loaf stands on a board, and a loaf from a tin shows its crumb.
        assert 'class="recipe-board"' in page
        assert 'class="loaf-crumb"' in page
