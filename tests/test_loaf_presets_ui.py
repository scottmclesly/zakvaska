"""The "fill a tin" chips, on both forms that ask for a total flour weight.

You rarely know the flour when you sit down to plan: you know which tin you
are filling. A bread maker is sold by the pound its pan takes, so each chip
works that dough weight back through the recipe's percentages and fills in
the flour it needs.

Both forms draw the row from `partials/loaf_presets.html`, and each tells it
which fields a chip fills — the bake form records the machine setting as the
text the machine prints, the planner times the program from a number in
pounds. These check that the row only appears when it has an answer, that
it is pointed at the right fields on each page, and that on the planner it
arrives and acts without a trip through "Work it out".
"""

from __future__ import annotations

import re

from app.models.enums import IngredientRole, RecipeCategory
from app.services import measures
from app.services import recipes as recipe_service
from app.services import scaling
from app.services.recipes import IngredientSpec, StageSpec


def _recipe(session):
    lines = [
        IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
        IngredientSpec("Water", IngredientRole.WATER, 75.0),
        IngredientSpec("Salt", IngredientRole.SALT, 2.0),
    ]
    recipe = recipe_service.create_recipe(
        session, name="Borodinsky", category=RecipeCategory.RYE,
        ingredients=lines, stages=[StageSpec("bake", duration_min=60)],
    )
    session.commit()
    return recipe


def _bake_form(recipe) -> str:
    version = recipe.latest_version
    return f"/bakes/new?recipe_id={recipe.id}&version={version.version}"


def _row(page: str) -> str:
    """The chip row's markup, or "" when the page did not draw one."""
    found = re.search(r'<div class="loafrow".*?</div>', page, re.S)
    return found.group(0) if found else ""


def _chips(row: str) -> list[str]:
    return re.findall(r'data-size="([^"]+)"', row)


# --- The three sizes ------------------------------------------------------


class TestTheSizesOffered:
    def test_two_two_and_a_half_and_three_pounds(self, client, session):
        recipe = _recipe(session)
        version = recipe.latest_version

        page = client.get(f"/plan?version={version.id}").text

        assert _chips(_row(page)) == ["2 lb", "2.5 lb", "3 lb"]

    def test_they_are_the_sizes_the_scaler_knows(self, client, session):
        """One list, so the chips cannot drift from what they compute."""
        assert scaling.LOAF_SIZES_LB == (2.0, 2.5, 3.0)

    def test_each_chip_carries_the_flour_that_fills_that_tin(
        self, client, session
    ):
        recipe = _recipe(session)
        version = recipe.latest_version
        expected = scaling.loaf_presets(version.ingredients)

        row = _row(client.get(f"/plan?version={version.id}").text)
        grams = [float(one) for one in re.findall(r'data-flour="([^"]+)"', row)]

        assert grams == [round(one.flour_g, 1) for one in expected]

    def test_a_bigger_tin_wants_more_flour(self, client, session):
        recipe = _recipe(session)
        row = _row(client.get(f"/plan?version={recipe.latest_version.id}").text)
        grams = [float(one) for one in re.findall(r'data-flour="([^"]+)"', row)]

        assert grams == sorted(grams)


# --- Only when there is an answer ----------------------------------------


class TestItOnlyShowsWhenItCan:
    def test_no_row_before_a_recipe_is_picked(self, client, session):
        """Nothing to work the percentages back through yet."""
        _recipe(session)

        assert _row(client.get("/plan").text) == ""

    def test_no_row_for_a_version_that_does_not_exist(self, client, session):
        """A stale link in the query string leaves the page without a recipe."""
        _recipe(session)

        assert _row(client.get("/plan?version=9999").text) == ""


# --- Each form is pointed at its own fields -------------------------------


class TestTheFieldsEachFormFills:
    def test_the_planner_fills_its_flour_box_and_its_loaf_size(
        self, client, session
    ):
        recipe = _recipe(session)

        row = _row(client.get(f"/plan?version={recipe.latest_version.id}").text)

        assert 'data-flour-field="flour"' in row
        assert 'data-pounds-field="loaf"' in row

    def test_the_planner_chips_carry_a_number_of_pounds(self, client, session):
        """Its loaf field times the machine's program, so it wants 2.5."""
        recipe = _recipe(session)

        row = _row(client.get(f"/plan?version={recipe.latest_version.id}").text)

        # Written as it would be typed, since it rides in the plan's URL.
        assert re.findall(r'data-pounds="([^"]+)"', row) == ["2", "2.5", "3"]

    def test_both_fields_the_planner_names_are_on_the_planner(
        self, client, session
    ):
        recipe = _recipe(session)

        page = client.get(f"/plan?version={recipe.latest_version.id}").text

        assert 'name="flour"' in page
        assert 'name="loaf"' in page

    def test_the_bake_form_fills_its_own_two(self, client, session):
        recipe = _recipe(session)

        row = _row(client.get(_bake_form(recipe)).text)

        assert 'data-flour-field="total_flour_g"' in row
        assert 'data-size-field="loaf_size"' in row

    def test_the_bake_form_chips_carry_the_printed_label(
        self, client, session
    ):
        """Its loaf field is the text the machine prints on its panel."""
        recipe = _recipe(session)

        row = _row(client.get(_bake_form(recipe)).text)

        assert 'data-size="2.5 lb"' in row

    def test_both_forms_draw_the_same_row(self, client, session):
        """One partial: the chips cannot drift apart."""
        recipe = _recipe(session)
        version_id = recipe.latest_version.id

        planner = _chips(_row(client.get(f"/plan?version={version_id}").text))
        bake = _chips(_row(client.get(_bake_form(recipe)).text))

        assert planner == bake


# --- It reads in whichever unit is on display -----------------------------


class TestItFollowsTheUnitOnDisplay:
    def test_the_text_a_chip_types_is_grams_by_default(self, client, session):
        recipe = _recipe(session)

        row = _row(client.get(f"/plan?version={recipe.latest_version.id}").text)
        typed = re.findall(r'data-flour-text="([^"]+)"', row)

        assert typed and all("g" not in one for one in typed)
        assert all(one.replace(".", "").isdigit() for one in typed)

    def test_in_pounds_a_chip_types_pounds(self, client, session):
        recipe = _recipe(session)
        client.post("/settings/units", data={"weight_unit": measures.US_WEIGHT})

        row = _row(client.get(f"/plan?version={recipe.latest_version.id}").text)
        typed = re.findall(r'data-flour-text="([^"]+)"', row)

        assert typed
        assert any("lb" in one or "oz" in one for one in typed)

    def test_the_grams_behind_it_do_not_move(self, client, session):
        """The text follows the display unit; the fallback stays grams."""
        recipe = _recipe(session)
        version_id = recipe.latest_version.id
        before = re.findall(
            r'data-flour="([^"]+)"', _row(client.get(f"/plan?version={version_id}").text)
        )

        client.post("/settings/units", data={"weight_unit": measures.US_VOLUME})
        after = re.findall(
            r'data-flour="([^"]+)"', _row(client.get(f"/plan?version={version_id}").text)
        )

        assert before == after


# --- Live on the planner --------------------------------------------------


class TestItArrivesWhenTheRecipeDoes:
    """The chips come from the recipe, so picking one should bring them.

    Before this they only appeared after submitting the form, which is the
    one moment you do not have: you are looking for the flour to put in it.
    """

    def test_the_box_is_there_before_the_chips_are(self, client, session):
        """HTMX needs something to swap, even with no recipe chosen."""
        _recipe(session)

        page = client.get("/plan").text

        assert 'id="loaf-row"' in page
        assert _row(page) == ""

    def test_the_recipe_select_fetches_the_row(self, client, session):
        _recipe(session)
        page = client.get("/plan").text
        select = page[page.index('<select name="version"'):]
        select = select[: select.index(">")]

        assert 'hx-get="/plan/tin"' in select
        assert 'hx-target="#loaf-row"' in select
        assert 'hx-swap="outerHTML"' in select
        assert 'hx-trigger="change"' in select

    def test_the_row_on_its_own_carries_its_own_box(self, client, session):
        """It is swapped by outerHTML, so it has to replace like for like."""
        recipe = _recipe(session)

        part = client.get(f"/plan/tin?version={recipe.latest_version.id}").text

        assert part.strip().startswith('<div id="loaf-row">')
        assert _chips(_row(part)) == ["2 lb", "2.5 lb", "3 lb"]

    def test_the_row_on_its_own_is_empty_without_a_recipe(self, client):
        part = client.get("/plan/tin").text

        assert 'id="loaf-row"' in part
        assert _row(part) == ""

    def test_the_swapped_row_matches_the_one_on_the_page(self, client, session):
        """Same partial either way, so picking a recipe cannot change them."""
        recipe = _recipe(session)
        version_id = recipe.latest_version.id

        whole = _row(client.get(f"/plan?version={version_id}").text)
        swapped = _row(client.get(f"/plan/tin?version={version_id}").text)

        assert _chips(whole) == _chips(swapped)
        assert 'data-flour-field="flour"' in swapped
        assert 'data-pounds-field="loaf"' in swapped


class TestClickingAChipRedrawsThePlan:
    def test_the_plan_listens_for_a_chosen_loaf(self, client, session):
        _recipe(session)
        page = client.get("/plan").text
        form = page[page.index('hx-get="/plan/steps"'):]
        form = form[: form.index(">")]

        assert "loaf-chosen from:body" in form

    def test_and_the_script_says_so_after_filling_the_fields(self, client):
        """In that order: the swap sends the form, so it must be filled."""
        script = client.get("/static/js/app.js").text
        handler = script[script.index("[data-loaf]"):]

        assert "loaf-chosen" in handler
        assert handler.index("field.value = value") < handler.index("loaf-chosen")

    def test_the_bake_form_has_nothing_listening_and_does_not_mind(
        self, client, session
    ):
        """The same chips are on both forms; only one redraws anything."""
        recipe = _recipe(session)

        page = client.get(_bake_form(recipe)).text

        assert _chips(_row(page)) == ["2 lb", "2.5 lb", "3 lb"]
        assert "loaf-chosen" not in page
