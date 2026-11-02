"""The drawn jar and the role glyphs.

Pictures are easy to break silently, so these check the few things that
carry meaning: the state, and the level the jar is filled to.
"""

from __future__ import annotations

import re

from app.models.enums import IngredientRole, JarOrigin, JarState, RecipeCategory
from app.services import jars as jar_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec


def make_jar(session, *, name="Homemade rye", state=JarState.ACTIVE):
    jar = jar_service.create_jar(
        session, name=name, origin=JarOrigin.HOMEMADE, state=state
    )
    session.commit()
    return jar


def fill_top(body: str) -> float:
    """The y the contents start at: lower number, fuller jar."""
    match = re.search(r'class="jar-contents" x="10" y="([\d.]+)"', body)
    assert match, body[:400]
    return float(match.group(1))


class TestTheDrawnJar:
    def test_it_is_on_the_dashboard(self, client, session):
        make_jar(session)

        assert 'class="jar-art' in client.get("/").text

    def test_it_is_on_the_jar_page(self, client, session):
        jar = make_jar(session)

        assert "jar-art-lg" in client.get(f"/jars/{jar.id}").text

    def test_it_says_which_state_it_is_in(self, client, session):
        jar = make_jar(session, state=JarState.FRIDGE)

        assert "state-fridge" in client.get(f"/jars/{jar.id}").text

    def test_it_is_labelled_for_a_screen_reader(self, client, session):
        jar = make_jar(session)

        body = client.get(f"/jars/{jar.id}").text
        assert 'aria-label="Homemade rye — active"' in body

    def test_an_active_jar_has_bubbles_and_a_dried_one_does_not(
        self, client, session
    ):
        active = make_jar(session, name="Active one")
        dried = make_jar(session, name="Dried one", state=JarState.DRIED)

        assert "jar-bubble" in client.get(f"/jars/{active.id}").text
        assert "jar-bubble" not in client.get(f"/jars/{dried.id}").text

    def test_a_measured_rise_fills_the_jar(self, client, session):
        """The picture reads the data, rather than decorating it."""
        quiet = make_jar(session, name="Quiet")
        lively = make_jar(session, name="Lively")
        jar_service.log_observation(
            session, quiet, start_height_mm=40, height_mm=48
        )
        jar_service.log_observation(
            session, lively, start_height_mm=40, height_mm=95
        )
        session.commit()

        quiet_top = fill_top(client.get(f"/jars/{quiet.id}").text)
        lively_top = fill_top(client.get(f"/jars/{lively.id}").text)

        assert lively_top < quiet_top

    def test_a_jar_with_no_observations_still_draws(self, client, session):
        jar = make_jar(session)

        assert fill_top(client.get(f"/jars/{jar.id}").text) > 0

    def test_two_jars_on_one_page_get_their_own_clip_paths(self, client, session):
        """A repeated id would clip both jars with the first one's shape."""
        make_jar(session, name="One")
        make_jar(session, name="Two")

        body = client.get("/").text
        ids = re.findall(r'id="(jarbody-\d+)"', body)

        assert len(ids) == 2
        assert len(set(ids)) == 2


class TestRoleGlyphs:
    def test_each_role_draws_something(self, client, session):
        recipe = recipe_service.create_recipe(
            session, name="Everything", category=RecipeCategory.OTHER,
            ingredients=[
                IngredientSpec("Flour", IngredientRole.FLOUR, 100.0),
                IngredientSpec("Water", IngredientRole.WATER, 70.0),
                IngredientSpec("Levain", IngredientRole.LEVAIN, 20.0),
                IngredientSpec("Salt", IngredientRole.SALT, 2.0),
                IngredientSpec("Honey", IngredientRole.SWEETENER, 5.0),
                IngredientSpec("Butter", IngredientRole.FAT, 5.0),
                IngredientSpec("Caraway", IngredientRole.OTHER, 1.0),
            ],
            stages=[StageSpec("bake", duration_min=40)],
        )
        session.commit()

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        for role in IngredientRole:
            assert f"role-icon role-{role.value}" in body, role

    def test_the_glyphs_are_hidden_from_screen_readers(self, client, session):
        """The role is already written next to them in words."""
        recipe = recipe_service.create_recipe(
            session, name="Rye", category=RecipeCategory.RYE,
            ingredients=[IngredientSpec("Flour", IngredientRole.FLOUR, 100.0)],
            stages=[StageSpec("bake", duration_min=40)],
        )
        session.commit()

        body = client.get(f"/recipes/{recipe.id}/v/1").text
        glyph = body[body.index('class="role-icon') - 60:]

        assert 'aria-hidden="true"' in glyph[:300]
