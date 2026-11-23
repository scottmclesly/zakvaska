"""Choosing the display units, and the pages reading in whichever is chosen."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.bake import Bake
from app.models.feeding import Feeding
from app.models.enums import IngredientRole, JarOrigin, RecipeCategory
from app.models.recipe import Recipe, RecipeVersion
from app.services import jars as jar_service
from app.services import measures
from app.services import recipes as recipe_service
from app.services import settings_store
from app.services.recipes import IngredientSpec, StageSpec


def seed_jar_with_a_feeding(session):
    jar = jar_service.create_jar(
        session, name="Homemade rye", origin=JarOrigin.HOMEMADE,
        flour_type="whole rye",
    )
    session.commit()
    jar_service.log_feeding(
        session, jar, starter_g=40, flour_g=80, water_g=80
    )
    session.commit()
    return jar


def seed_recipe(session):
    recipe = recipe_service.create_recipe(
        session, name="Borodinsky", category=RecipeCategory.RYE,
        ingredients=[
            IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 80.0),
            IngredientSpec("Salt", IngredientRole.SALT, 2.0),
        ],
        stages=[StageSpec("bake", duration_min=60)],
    )
    session.commit()
    return recipe


class TestChoosingTheUnit:
    def test_grams_to_start_with(self, client, session):
        assert settings_store.weight_unit(session) == measures.METRIC

    def test_every_unit_can_be_chosen(self, client, session):
        for unit in measures.UNIT_CYCLE:
            client.post("/settings/units", data={"weight_unit": unit})
            session.expire_all()
            assert settings_store.weight_unit(session) == unit

    def test_a_nonsense_unit_is_refused(self, client, session):
        response = client.post(
            "/settings/units", data={"weight_unit": "furlongs"}
        )

        assert response.status_code == 400
        session.expire_all()
        assert settings_store.weight_unit(session) == measures.METRIC

    def test_the_setting_survives_the_next_request(self, client, session):
        switch_to(client, "us_weight")

        assert "oz" in client.get("/settings").text

    def test_the_temperature_can_be_chosen_too(self, client, session):
        client.post("/settings/units", data={"temp_unit": "C"})
        session.expire_all()
        assert settings_store.temp_unit(session) == "C"

        client.post("/settings/units", data={"temp_unit": "F"})
        session.expire_all()
        assert settings_store.temp_unit(session) == "F"


class TestThePagesFollow:
    def test_a_feeding_reads_in_cups(self, client, session):
        jar = seed_jar_with_a_feeding(session)
        switch_to(client, "us_volume")

        body = client.get(f"/jars/{jar.id}").text

        assert "40 g" not in body
        # 40 g of starter, 80 g of rye, 80 g of water.
        assert "2 ⅔ tbsp" in body
        assert "¾ cup" in body
        assert "⅓ cup" in body

    def test_a_feeding_reads_in_ounces(self, client, session):
        jar = seed_jar_with_a_feeding(session)
        switch_to(client, "us_weight")

        body = client.get(f"/jars/{jar.id}").text

        assert "1.4 oz" in body  # 40 g
        assert "2.8 oz" in body  # 80 g

    def test_a_scaled_recipe_reads_in_cups(self, client, session):
        recipe = seed_recipe(session)
        switch_to(client, "us_volume")

        # The unit is written out, because a bare total is read as ounces
        # once the switch has left grams — see test_a_total_is_a_weight.
        body = client.get(
            f"/recipes/{recipe.id}/v/1", params={"flour": "500 g"}
        ).text

        assert "4 ⅞ cups" in body  # 500 g rye flour
        assert "Cups" in body  # the column header follows too

    def test_a_total_stays_a_weight_even_in_cups(self, client, session):
        recipe = seed_recipe(session)
        switch_to(client, "us_volume")

        body = client.get(
            f"/recipes/{recipe.id}/v/1", params={"flour": "500 g"}
        ).text

        # Total dough is 910 g, which is pounds, never cups.
        assert "2 lb" in body

    def test_grams_are_what_you_get_without_touching_anything(
        self, client, session
    ):
        jar = seed_jar_with_a_feeding(session)

        body = client.get(f"/jars/{jar.id}").text

        assert "40 g starter" in body
        assert "80 g flour" in body
        assert "cup flour" not in body


def create_jar(client, name="Rye") -> int:
    """A jar through the form, which is how the unit switch gets involved."""
    response = client.post(
        "/jars/new",
        data={
            "name": name, "origin": "homemade", "flour_type": "whole rye",
            "state": "active", "feed_interval_room_h": "12",
            "feed_interval_fridge_h": "168",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


def last_feeding(session) -> Feeding:
    return session.scalars(select(Feeding).order_by(Feeding.id.desc())).first()


def switch_to(client, unit: str) -> None:
    client.post("/settings/units", data={"weight_unit": unit})


def recipe_form(amounts: list[str], percents: list[str] | None = None) -> dict:
    """A three-line recipe as the form submits it: parallel arrays."""
    return {
        "name": "Cup loaf",
        "category": "wheat",
        "ingredient_name": ["Bread flour", "Water", "Salt"],
        "ingredient_role": ["flour", "water", "salt"],
        "ingredient_amount": amounts,
        "ingredient_pct": percents or ["", "", ""],
        "ingredient_notes": ["", "", ""],
    }


class TestTypingAFeedingInAnyUnit:
    """Grams are stored; the field takes whatever the baker is working in."""

    def test_cups_are_stored_as_grams(self, client, session):
        jar_id = create_jar(client, "Rye")
        switch_to(client, measures.US_VOLUME)

        client.post(
            f"/jars/{jar_id}/feed",
            data={
                "starter_g": "2 tbsp", "flour_g": "3/4 cup",
                "water_g": "1/3 cup", "flour_type": "whole rye",
            },
            follow_redirects=False,
        )

        feeding = last_feeding(session)
        # 2 tbsp of starter at 240 g/cup, 3/4 cup of rye at 103, 1/3 of water.
        assert feeding.starter_g == pytest.approx(30.0)
        assert feeding.flour_g == pytest.approx(77.25)
        assert feeding.water_g == pytest.approx(78.67, abs=0.01)

    def test_ounces_are_stored_as_grams(self, client, session):
        jar_id = create_jar(client, "Rye")
        switch_to(client, measures.US_WEIGHT)

        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "1.5", "flour_g": "3 oz", "water_g": "3"},
            follow_redirects=False,
        )

        feeding = last_feeding(session)
        assert feeding.starter_g == pytest.approx(42.52, abs=0.01)
        assert feeding.flour_g == pytest.approx(85.05, abs=0.01)

    def test_a_written_unit_wins_over_the_switch(self, client, session):
        jar_id = create_jar(client, "Rye")
        switch_to(client, measures.US_VOLUME)

        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "40 g", "flour_g": "80 g", "water_g": "80 g"},
            follow_redirects=False,
        )

        feeding = last_feeding(session)
        assert (feeding.starter_g, feeding.flour_g) == (40.0, 80.0)

    def test_the_form_opens_in_the_unit_on_display(self, client, session):
        jar = seed_jar_with_a_feeding(session)
        switch_to(client, measures.US_VOLUME)

        body = client.get(f"/jars/{jar.id}/feed").text

        # Last feeding was 40 g starter, 80 g rye, 80 g water.
        assert 'value="2 ⅔ tbsp"' in body
        assert 'value="¾ cup"' in body
        assert "Cups" in body

    def test_nonsense_is_still_refused(self, client):
        jar_id = create_jar(client, "Rye")
        switch_to(client, measures.US_VOLUME)

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "a dollop", "flour_g": "1 cup", "water_g": "1 cup"},
        )

        assert response.status_code == 400
        assert "could not read" in response.text


class TestTypingARecipeInCups:
    """Most of Scott's recipes are written in cups, so they go in that way."""

    def test_amounts_become_percentages(self, client, session):
        response = client.post(
            "/recipes/new",
            data=recipe_form(["3 cups", "1 1/4 cups", "2 tsp"]),
            follow_redirects=False,
        )
        assert response.status_code == 303

        version = session.scalars(
            select(RecipeVersion).order_by(RecipeVersion.id.desc())
        ).first()
        # 3 cups of bread flour is 360 g, and that is the 100%.
        assert version.batch_flour_g == pytest.approx(360.0)
        assert [i.baker_pct for i in version.ingredients] == [100.0, 81.9, 3.3]

    def test_the_unit_on_display_is_the_one_typed_in(self, client, session):
        switch_to(client, measures.US_WEIGHT)

        assert client.post(
            "/recipes/new",
            data=recipe_form(["16", "10", "0.4"]),
            follow_redirects=False,
        ).status_code == 303

        version = session.scalars(
            select(RecipeVersion).order_by(RecipeVersion.id.desc())
        ).first()
        # 16 oz of flour, read as ounces because that is what the switch says.
        assert version.batch_flour_g == pytest.approx(453.59, abs=0.01)
        assert version.ingredients[1].baker_pct == pytest.approx(62.5)

    def test_percentages_still_work_on_their_own(self, client, session):
        assert client.post(
            "/recipes/new",
            data=recipe_form(["", "", ""], percents=["100", "80", "2"]),
            follow_redirects=False,
        ).status_code == 303

        version = session.scalars(
            select(RecipeVersion).order_by(RecipeVersion.id.desc())
        ).first()
        assert version.batch_flour_g is None
        assert [i.baker_pct for i in version.ingredients] == [100.0, 80.0, 2.0]

    def test_amounts_with_no_flour_amount_are_refused(self, client):
        response = client.post(
            "/recipes/new",
            data=recipe_form(["", "1 1/4 cups", "2 tsp"], percents=["100", "", ""]),
        )

        assert response.status_code == 400
        assert "at least one ingredient whose role is flour" in response.text

    def test_a_recipe_written_in_cups_reads_in_cups(self, client, session):
        assert client.post(
            "/recipes/new",
            data=recipe_form(["3 cups", "1 1/4 cups", "2 tsp"]),
            follow_redirects=False,
        ).status_code == 303
        recipe_id = session.scalars(select(Recipe).order_by(Recipe.id.desc())).first().id
        switch_to(client, measures.US_VOLUME)

        # No scaling asked for: the batch it was written at is enough.
        body = client.get(f"/recipes/{recipe_id}/v/1").text

        assert "3 cups" in body
        assert "1 ¼ cups" in body
        assert "the batch the recipe was written at" in body

    def test_the_edit_form_hands_back_the_amounts(self, client, session):
        assert client.post(
            "/recipes/new",
            data=recipe_form(["3 cups", "1 1/4 cups", "2 tsp"]),
            follow_redirects=False,
        ).status_code == 303
        recipe_id = session.scalars(select(Recipe).order_by(Recipe.id.desc())).first().id
        switch_to(client, measures.US_VOLUME)

        body = client.get(f"/recipes/{recipe_id}/edit").text

        assert 'value="3 cups"' in body
        assert 'value="1 ¼ cups"' in body

    def test_a_percentages_only_recipe_has_no_amounts_to_hand_back(
        self, client, session
    ):
        recipe = seed_recipe(session)

        body = client.get(f"/recipes/{recipe.id}/edit").text

        assert 'name="ingredient_amount"' in body
        assert 'value="3 cups"' not in body


class TestScalingAndBakingInAnyUnit:
    def test_a_recipe_scales_from_a_weight_in_pounds(self, client, session):
        recipe = seed_recipe(session)
        switch_to(client, measures.US_WEIGHT)

        body = client.get(
            f"/recipes/{recipe.id}/v/1", params={"flour": "1 lb"}
        ).text

        # 1 lb of flour at 80% water is 12.8 oz of water.
        assert "1 lb" in body
        assert "12.8 oz" in body

    def test_a_bake_takes_its_flour_total_in_ounces(self, client, session):
        recipe = seed_recipe(session)
        switch_to(client, measures.US_WEIGHT)

        response = client.post(
            "/bakes/new",
            data={
                "recipe_id": recipe.id, "version": 1, "method": "oven",
                "total_flour_g": "1 lb 2 oz",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        bake = session.scalars(select(Bake).order_by(Bake.id.desc())).first()
        assert bake.total_flour_g == pytest.approx(510.29, abs=0.01)
