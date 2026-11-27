"""Recipe and equipment pages, driven the way a browser drives them."""

from __future__ import annotations

import re

from app.models.enums import RecipeCategory
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec
from app.models.enums import IngredientRole

BORODINSKY = {
    "name": "Borodinsky",
    "category": "rye",
    "notes": "first attempt",
    "ingredient_name": [
        "Whole rye flour", "Water", "Rye levain", "Red rye malt",
        "Molasses", "Salt", "Coriander",
    ],
    "ingredient_role": [
        "flour", "water", "levain", "other", "sweetener", "salt", "other",
    ],
    "ingredient_pct": ["100", "80", "30", "5", "5", "2", "1"],
    "ingredient_notes": ["", "", "100% hydration", "", "", "", "ground"],
    "stage_name": [
        "scald (zavarka)", "sponge", "final dough", "proof", "bake",
    ],
    "stage_duration": ["240", "240", "30", "120", "60"],
    "stage_temp": ["150", "84", "", "82", "400"],
    "stage_notes": ["malt, flour and boiling water", "", "", "", "steam first"],
}


def create(client, **over) -> int:
    """Post the new-recipe form and return the recipe id."""
    data = dict(BORODINSKY)
    data.update(over)
    response = client.post("/recipes/new", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    match = re.match(r"/recipes/(\d+)$", response.headers["location"])
    assert match, response.headers["location"]
    return int(match.group(1))


class TestListAndCreate:
    def test_empty_list_invites_a_first_recipe(self, client):
        page = client.get("/recipes")
        assert page.status_code == 200
        assert "No recipes yet" in page.text

    def test_the_new_form_renders(self, client):
        page = client.get("/recipes/new")
        assert page.status_code == 200
        assert 'name="ingredient_pct"' in page.text
        assert 'name="stage_name"' in page.text
        # Borodinsky's own stage names are offered as suggestions.
        assert "scald (zavarka)" in page.text

    def test_creating_a_recipe_lands_on_its_latest_version(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}", follow_redirects=False)
        assert page.status_code == 303
        assert page.headers["location"] == f"/recipes/{recipe_id}/v/1"

    def test_the_new_recipe_shows_up_on_the_list(self, client):
        create(client)
        page = client.get("/recipes")
        assert "Borodinsky" in page.text
        assert "No recipes yet" not in page.text

    def test_a_recipe_needs_a_name(self, client):
        response = client.post(
            "/recipes/new", data={**BORODINSKY, "name": "  "},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "A recipe needs a name." in response.text

    def test_a_bad_percentage_is_reported_not_swallowed(self, client):
        response = client.post(
            "/recipes/new",
            data={**BORODINSKY, "ingredient_pct": ["lots", "80", "30", "5", "5", "2", "1"]},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Percentage for Whole rye flour" in response.text

    def test_a_negative_percentage_is_refused(self, client):
        response = client.post(
            "/recipes/new",
            data={**BORODINSKY, "ingredient_pct": ["-100", "80", "30", "5", "5", "2", "1"]},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "cannot be a negative percentage" in response.text

    def test_an_error_page_keeps_what_you_typed(self, client):
        response = client.post(
            "/recipes/new",
            data={**BORODINSKY, "name": "", "ingredient_pct": ["100", "82", "30", "5", "5", "2", "1"]},
            follow_redirects=False,
        )
        assert response.status_code == 400
        # The rows come back, so nothing has to be retyped.
        assert "Whole rye flour" in response.text
        assert 'value="82"' in response.text

    def test_blank_rows_are_dropped(self, client):
        """The form always ships a spare row; an unused one is not an error."""
        recipe_id = create(
            client,
            ingredient_name=BORODINSKY["ingredient_name"] + [""],
            ingredient_role=BORODINSKY["ingredient_role"] + ["other"],
            ingredient_pct=BORODINSKY["ingredient_pct"] + [""],
            ingredient_notes=BORODINSKY["ingredient_notes"] + [""],
            stage_name=BORODINSKY["stage_name"] + [""],
            stage_duration=BORODINSKY["stage_duration"] + [""],
            stage_temp=BORODINSKY["stage_temp"] + [""],
            stage_notes=BORODINSKY["stage_notes"] + [""],
        )
        page = client.get(f"/recipes/{recipe_id}/v/1")
        assert page.text.count('class="badge badge-role') == 7


class TestVersionPage:
    def test_it_shows_the_percentages(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/v/1")
        assert page.status_code == 200
        assert "100.0%" in page.text
        assert "Coriander" in page.text

    def test_the_stages_are_in_order(self, client):
        recipe_id = create(client)
        text = client.get(f"/recipes/{recipe_id}/v/1").text
        # Matched on the heading, not the bare name: "bake" also appears in
        # the /bakes links on this page. A stage's glyph comes before its
        # name inside the heading, so the name is found by what closes it.
        positions = [
            text.index(f">{name}</h3>")
            for name in ["scald (zavarka)", "sponge", "final dough", "proof", "bake"]
        ]
        assert positions == sorted(positions)

    def test_stage_temperatures_round_trip_through_the_display_unit(self, client):
        """Typed as °F by default, stored as °C, shown as °F again."""
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/v/1")
        assert "400°F" in page.text
        assert "150°F" in page.text

    def test_scaling_to_flour_shows_the_grams(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/v/1?flour=500")
        assert page.status_code == 200
        for grams in ["500 g", "400 g", "150 g", "25 g", "10 g", "5 g"]:
            assert grams in page.text, grams
        assert "1115 g" in page.text  # total dough

    def test_scaling_to_a_dough_weight_shows_the_grams(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/v/1?dough=1115")
        assert page.status_code == 200
        assert "500 g" in page.text
        assert "400 g" in page.text

    def test_without_a_target_there_are_no_grams(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/v/1")
        assert "Grams" not in page.text

    def test_a_missing_version_is_a_404(self, client):
        recipe_id = create(client)
        assert client.get(f"/recipes/{recipe_id}/v/9").status_code == 404

    def test_a_missing_recipe_is_a_404(self, client):
        assert client.get("/recipes/999").status_code == 404


class TestEditingMakesANewVersion:
    def test_an_edit_redirects_to_version_two(self, client):
        recipe_id = create(client)
        response = client.post(
            f"/recipes/{recipe_id}/edit",
            data={
                **BORODINSKY,
                "notes": "more malt, longer scald",
                "ingredient_pct": ["100", "82", "30", "8", "5", "2", "1"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"/recipes/{recipe_id}/v/2"

    def test_version_one_still_reads_as_it_was(self, client):
        recipe_id = create(client)
        client.post(
            f"/recipes/{recipe_id}/edit",
            data={**BORODINSKY, "ingredient_pct": ["100", "82", "30", "8", "5", "2", "1"]},
        )
        v1 = client.get(f"/recipes/{recipe_id}/v/1")
        assert "80.0%" in v1.text
        assert "read-only" in v1.text

    def test_the_edit_form_comes_prefilled(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/edit")
        assert page.status_code == 200
        assert 'value="Whole rye flour"' in page.text
        assert 'value="80"' in page.text
        # Temperatures come back in the display unit, not raw Celsius.
        assert 'value="400"' in page.text

    def test_the_edit_form_says_which_version_it_will_write(self, client):
        recipe_id = create(client)
        page = client.get(f"/recipes/{recipe_id}/edit")
        assert "v2" in page.text

    def test_renaming_does_not_add_a_version(self, client, session):
        recipe_id = create(client)
        client.post(
            f"/recipes/{recipe_id}/edit",
            data={**BORODINSKY, "name": "Borodinsky (rye)"},
        )
        recipe = recipe_service.get_recipe(session, recipe_id)
        assert recipe.name == "Borodinsky (rye)"
        # The ingredients were resubmitted unchanged, but an edit is an edit:
        # it still writes a version, which is what keeps bakes honest.
        assert len(recipe.versions) == 2


class TestDiffPage:
    def _edited(self, client) -> int:
        recipe_id = create(client)
        client.post(
            f"/recipes/{recipe_id}/edit",
            data={
                **BORODINSKY,
                "notes": "more malt",
                "ingredient_pct": ["100", "82", "30", "8", "5", "2", "1"],
                "stage_duration": ["300", "240", "30", "120", "60"],
            },
        )
        return recipe_id

    def test_it_defaults_to_the_two_newest_versions(self, client):
        recipe_id = self._edited(client)
        page = client.get(f"/recipes/{recipe_id}/diff")
        assert page.status_code == 200
        assert "v1" in page.text and "v2" in page.text

    def test_it_names_the_changed_lines(self, client):
        recipe_id = self._edited(client)
        text = client.get(f"/recipes/{recipe_id}/diff").text
        assert "Water" in text
        assert "Red rye malt" in text
        assert "scald (zavarka)" in text

    def test_a_temperature_change_is_shown_in_the_display_unit(self, client):
        """Stored in Celsius, but the page must not suddenly start speaking it."""
        recipe_id = create(client)
        client.post(
            f"/recipes/{recipe_id}/edit",
            data={**BORODINSKY, "stage_temp": ["150", "84", "", "82", "425"]},
        )
        text = client.get(f"/recipes/{recipe_id}/diff").text
        assert "temperature" in text
        assert "400°F" in text and "425°F" in text

    def test_field_names_read_as_english(self, client):
        recipe_id = self._edited(client)
        text = client.get(f"/recipes/{recipe_id}/diff").text
        assert "baker&#39;s %" in text or "baker's %" in text
        assert "baker_pct" not in text

    def test_explicit_versions_can_be_picked(self, client):
        recipe_id = self._edited(client)
        page = client.get(
            f"/recipes/{recipe_id}/diff?from_version=1&to_version=2"
        )
        assert page.status_code == 200

    def test_one_version_has_nothing_to_compare(self, client):
        recipe_id = create(client)
        assert client.get(f"/recipes/{recipe_id}/diff").status_code == 404

    def test_identical_versions_say_so(self, client):
        recipe_id = create(client)
        client.post(f"/recipes/{recipe_id}/edit", data=BORODINSKY)
        page = client.get(f"/recipes/{recipe_id}/diff")
        assert "No differences" in page.text


class TestArchiving:
    def test_archiving_moves_it_off_the_main_list(self, client):
        recipe_id = create(client)
        response = client.post(
            f"/recipes/{recipe_id}/archive", data={"archived": "1"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get("/recipes")
        assert "Archived" in page.text
        # Still reachable: a bake may point at one of its versions.
        assert client.get(f"/recipes/{recipe_id}/v/1").status_code == 200

    def test_unarchiving_brings_it_back(self, client):
        recipe_id = create(client)
        client.post(f"/recipes/{recipe_id}/archive", data={"archived": "1"})
        client.post(f"/recipes/{recipe_id}/archive", data={"archived": "0"})
        page = client.get("/recipes")
        assert "Archived" not in page.text


class TestEquipmentPrograms:
    def test_the_page_renders_empty(self, client):
        page = client.get("/equipment")
        assert page.status_code == 200
        assert "Nothing entered yet" in page.text

    def test_adding_a_program(self, client):
        response = client.post(
            "/equipment/new",
            data={
                "name": "Whole Wheat", "device": "West Bend 41300",
                "total_min": "230", "notes": "3 rises, 60 min bake",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get("/equipment")
        assert "Whole Wheat" in page.text
        assert "West Bend 41300" in page.text
        assert 'value="230"' in page.text

    def test_a_program_needs_a_name(self, client):
        response = client.post(
            "/equipment/new", data={"name": "", "device": "West Bend"},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "A program needs a name." in response.text

    def test_bad_minutes_are_reported(self, client):
        response = client.post(
            "/equipment/new", data={"name": "Basic", "total_min": "about four hours"},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Total minutes" in response.text

    def test_editing_a_program(self, client, session):
        client.post("/equipment/new", data={"name": "Basic", "total_min": "180"})
        program = recipe_service.list_programs(session)[0]
        response = client.post(
            f"/equipment/{program.id}/edit",
            data={"name": "Basic", "device": "West Bend 41300",
                  "total_min": "190", "notes": ""},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "190" in client.get("/equipment").text

    def test_archiving_a_program_keeps_it(self, client, session):
        client.post("/equipment/new", data={"name": "Basic"})
        program = recipe_service.list_programs(session)[0]
        client.post(f"/equipment/{program.id}/archive", data={"archived": "1"})

        page = client.get("/equipment")
        assert "Nothing entered yet" in page.text
        assert "Archived" in page.text

    def test_a_missing_program_is_a_404(self, client):
        assert client.post(
            "/equipment/999/archive", data={"archived": "1"}
        ).status_code == 404


class TestNavigation:
    def test_every_page_links_to_recipes_and_on_to_equipment(self, client, session):
        """Recipes is in the header. Equipment is a tab of Settings now, so
        it is two steps from anywhere: Settings is on every page, and the
        Equipment tab is on Settings."""
        recipe_service.create_recipe(
            session, name="Borodinsky", category=RecipeCategory.RYE,
            ingredients=[IngredientSpec("Rye", IngredientRole.FLOUR, 100.0)],
            stages=[StageSpec("bake", duration_min=60)],
        )
        session.commit()
        for url in ["/", "/recipes", "/equipment", "/recipes/1/v/1"]:
            text = client.get(url).text
            assert 'href="/recipes"' in text, url
            assert 'href="/settings"' in text, url
        assert 'href="/equipment"' in client.get("/settings").text
