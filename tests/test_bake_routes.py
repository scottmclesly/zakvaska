"""The bake pages, driven the way a browser drives them."""

from __future__ import annotations

import re

from app.models.enums import BakeStatus, IngredientRole, JarOrigin, RecipeCategory
from app.services import bakes as bake_service
from app.services import jars as jar_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec


def seed_recipe(session, *, name="Borodinsky"):
    recipe = recipe_service.create_recipe(
        session,
        name=name,
        category=RecipeCategory.RYE,
        ingredients=[
            IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 80.0),
            IngredientSpec("Rye levain", IngredientRole.LEVAIN, 30.0),
            IngredientSpec("Salt", IngredientRole.SALT, 2.0),
        ],
        stages=[
            StageSpec("scald (zavarka)", duration_min=240, temp_c=65.0),
            StageSpec("sponge", duration_min=240),
            StageSpec("final dough", duration_min=30),
            StageSpec("proof", duration_min=120),
            StageSpec("bake", duration_min=60, temp_c=200.0),
        ],
    )
    session.commit()
    return recipe


def seed_jar(session, *, name="Homemade rye"):
    jar = jar_service.create_jar(session, name=name, origin=JarOrigin.HOMEMADE)
    session.commit()
    return jar


def start(client, recipe, **over) -> int:
    data = {
        "recipe_id": recipe.id,
        "version": recipe.latest_version.version,
        "method": "oven",
        "total_flour_g": "500",
    }
    data.update(over)
    response = client.post("/bakes/new", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    match = re.match(r"/bakes/(\d+)$", response.headers["location"])
    assert match, response.headers["location"]
    return int(match.group(1))


class TestStarting:
    def test_the_form_renders_from_a_recipe_version(self, client, session):
        recipe = seed_recipe(session)
        page = client.get(f"/bakes/new?recipe_id={recipe.id}&version=1")
        assert page.status_code == 200
        assert "Borodinsky v1" in page.text
        assert "5 stages" in page.text

    def test_a_missing_version_is_a_404(self, client, session):
        recipe = seed_recipe(session)
        assert client.get(
            f"/bakes/new?recipe_id={recipe.id}&version=9"
        ).status_code == 404

    def test_the_recipe_page_offers_to_bake_it(self, client, session):
        recipe = seed_recipe(session)
        page = client.get(f"/recipes/{recipe.id}/v/1")
        assert f"/bakes/new?recipe_id={recipe.id}&amp;version=1" in page.text

    def test_starting_lands_on_the_running_sheet(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        page = client.get(f"/bakes/{bake_id}")
        assert page.status_code == 200
        assert "Running sheet" in page.text
        assert "Start scald (zavarka)" in page.text

    def test_the_stages_arrive_as_the_plan(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        bake = bake_service.get_bake(session, bake_id)
        assert [log.name for log in bake.stage_logs][0] == "scald (zavarka)"
        assert len(bake.stage_logs) == 5

    def test_the_grams_to_weigh_are_shown(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe, total_flour_g="500")
        page = client.get(f"/bakes/{bake_id}")
        assert "Weigh out" in page.text
        for grams in ["500 g", "400 g", "150 g", "10 g"]:
            assert grams in page.text, grams

    def test_oven_temperature_is_typed_in_the_display_unit(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe, oven_temp="400", bake_min="60")
        page = client.get(f"/bakes/{bake_id}")
        assert "400°F" in page.text

    def test_start_now_puts_it_in_progress(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe, start_now="1")
        bake = bake_service.get_bake(session, bake_id)
        assert bake.status is BakeStatus.IN_PROGRESS
        assert bake.started_at is not None

    def test_without_a_time_it_is_only_planned(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        bake = bake_service.get_bake(session, bake_id)
        assert bake.status is BakeStatus.PLANNED
        assert bake.started_at is None

    def test_it_records_the_jar(self, client, session):
        recipe = seed_recipe(session)
        jar = seed_jar(session)
        bake_id = start(client, recipe, jar_id=str(jar.id))
        assert bake_service.get_bake(session, bake_id).jar_id == jar.id

    def test_a_bad_flour_total_is_reported(self, client, session):
        recipe = seed_recipe(session)
        response = client.post(
            "/bakes/new",
            data={
                "recipe_id": recipe.id, "version": 1,
                "method": "oven", "total_flour_g": "a bag",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        # The quotes come back HTML-escaped, so match around them.
        assert "Total flour" in response.text
        assert "could not read" in response.text

    def test_a_negative_flour_total_is_refused(self, client, session):
        recipe = seed_recipe(session)
        response = client.post(
            "/bakes/new",
            data={
                "recipe_id": recipe.id, "version": 1,
                "method": "oven", "total_flour_g": "-500",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "cannot be negative" in response.text

    def test_an_error_keeps_what_was_typed(self, client, session):
        recipe = seed_recipe(session)
        response = client.post(
            "/bakes/new",
            data={
                "recipe_id": recipe.id, "version": 1, "method": "oven",
                "total_flour_g": "nope", "crust_setting": "dark",
                "loaf_size": "2 lb",
            },
            follow_redirects=False,
        )
        assert 'value="dark"' in response.text
        assert 'value="2 lb"' in response.text


class TestRunningIt:
    def _bake(self, client, session, **over):
        recipe = seed_recipe(session)
        return seed_recipe and start(client, recipe, **over)

    def test_tapping_a_stage_started(self, client, session):
        bake_id = self._bake(client, session)
        bake = bake_service.get_bake(session, bake_id)
        first = bake.stage_logs[0].id

        response = client.post(
            f"/bakes/{bake_id}/stages/{first}/start", follow_redirects=False
        )
        assert response.status_code == 303

        page = client.get(f"/bakes/{bake_id}")
        assert "Done with scald (zavarka)" in page.text
        assert "In progress" in page.text

    def test_tapping_it_done_records_the_minutes(self, client, session):
        bake_id = self._bake(client, session)
        bake = bake_service.get_bake(session, bake_id)
        first = bake.stage_logs[0].id

        client.post(f"/bakes/{bake_id}/stages/{first}/start")
        client.post(f"/bakes/{bake_id}/stages/{first}/end")

        session.expire_all()
        log = bake_service.get_bake(session, bake_id).stage_logs[0]
        assert log.is_done
        assert log.actual_min is not None

        page = client.get(f"/bakes/{bake_id}")
        assert "1 of 5" in page.text

    def test_undo_clears_the_tap(self, client, session):
        bake_id = self._bake(client, session)
        first = bake_service.get_bake(session, bake_id).stage_logs[0].id

        client.post(f"/bakes/{bake_id}/stages/{first}/start")
        client.post(f"/bakes/{bake_id}/stages/{first}/clear")

        session.expire_all()
        log = bake_service.get_bake(session, bake_id).stage_logs[0]
        assert log.actual_start is None

    def test_a_stage_note_sticks(self, client, session):
        bake_id = self._bake(client, session)
        first = bake_service.get_bake(session, bake_id).stage_logs[0].id

        client.post(
            f"/bakes/{bake_id}/stages/{first}/note",
            data={"notes": "malt smelled right this time"},
        )
        page = client.get(f"/bakes/{bake_id}")
        assert "malt smelled right this time" in page.text

    def test_a_stage_from_another_bake_is_a_404(self, client, session):
        first_bake = self._bake(client, session)
        recipe = seed_recipe(session, name="Other")
        other_bake = start(client, recipe)
        stolen = bake_service.get_bake(session, other_bake).stage_logs[0].id

        assert client.post(
            f"/bakes/{first_bake}/stages/{stolen}/start"
        ).status_code == 404

    def test_finishing_it(self, client, session):
        bake_id = self._bake(client, session)
        response = client.post(
            f"/bakes/{bake_id}/finish", data={"status": "done"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        session.expire_all()
        bake = bake_service.get_bake(session, bake_id)
        assert bake.status is BakeStatus.DONE
        assert bake.finished_at is not None

    def test_marking_it_failed(self, client, session):
        bake_id = self._bake(client, session)
        client.post(f"/bakes/{bake_id}/finish", data={"status": "failed"})

        session.expire_all()
        assert bake_service.get_bake(session, bake_id).status is BakeStatus.FAILED

    def test_reopening_a_finished_bake(self, client, session):
        bake_id = self._bake(client, session)
        client.post(f"/bakes/{bake_id}/finish", data={"status": "done"})
        client.post(f"/bakes/{bake_id}/finish", data={"status": "in_progress"})

        session.expire_all()
        bake = bake_service.get_bake(session, bake_id)
        assert bake.status is BakeStatus.IN_PROGRESS
        assert bake.finished_at is None

    def test_a_missing_bake_is_a_404(self, client):
        assert client.get("/bakes/999").status_code == 404


class TestTheResult:
    def _bake(self, client, session):
        return start(client, seed_recipe(session))

    def test_the_form_renders(self, client, session):
        bake_id = self._bake(client, session)
        page = client.get(f"/bakes/{bake_id}/result")
        assert page.status_code == 200
        assert "Next time" in page.text

    def test_saving_a_result(self, client, session):
        bake_id = self._bake(client, session)
        response = client.post(
            f"/bakes/{bake_id}/result",
            data={
                "rating": "4", "crust": "thick", "crumb": "dense",
                "taste": "malty", "rise": "modest",
                "next_time": "less water, longer scald",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get(f"/bakes/{bake_id}")
        assert "less water, longer scald" in page.text
        assert "malty" in page.text

    def test_saving_a_result_finishes_the_bake(self, client, session):
        bake_id = self._bake(client, session)
        client.post(f"/bakes/{bake_id}/result", data={"rating": "4"})

        session.expire_all()
        assert bake_service.get_bake(session, bake_id).status is BakeStatus.DONE

    def test_a_rating_outside_one_to_five_is_refused(self, client, session):
        bake_id = self._bake(client, session)
        response = client.post(
            f"/bakes/{bake_id}/result", data={"rating": "9"},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Rating goes from 1 to 5." in response.text

    def test_a_result_with_no_rating_is_allowed(self, client, session):
        bake_id = self._bake(client, session)
        response = client.post(
            f"/bakes/{bake_id}/result",
            data={"rating": "", "next_time": "write this down properly"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "write this down properly" in client.get(f"/bakes/{bake_id}").text

    def test_the_form_comes_back_prefilled_for_an_edit(self, client, session):
        bake_id = self._bake(client, session)
        client.post(
            f"/bakes/{bake_id}/result",
            data={"rating": "4", "crust": "thick", "next_time": "more malt"},
        )
        page = client.get(f"/bakes/{bake_id}/result")
        assert 'value="thick"' in page.text
        assert "more malt" in page.text

    def test_editing_replaces_rather_than_adding(self, client, session):
        bake_id = self._bake(client, session)
        client.post(f"/bakes/{bake_id}/result", data={"rating": "2"})
        client.post(f"/bakes/{bake_id}/result", data={"rating": "5"})

        session.expire_all()
        bake = bake_service.get_bake(session, bake_id)
        assert bake.result.rating == 5


class TestTheList:
    def test_empty(self, client):
        page = client.get("/bakes")
        assert page.status_code == 200
        assert "No bakes yet" in page.text

    def test_it_lists_bakes(self, client, session):
        recipe = seed_recipe(session)
        start(client, recipe)
        page = client.get("/bakes")
        assert "Borodinsky v1" in page.text

    def test_filter_by_recipe(self, client, session):
        first = seed_recipe(session)
        second = seed_recipe(session, name="Plain sourdough")
        wanted = start(client, second)
        start(client, first)

        page = client.get(f"/bakes?recipe={second.id}")
        # Counted on the rows: every recipe still appears in the filter select.
        assert page.text.count('class="card bake-row"') == 1
        assert f'href="/bakes/{wanted}"' in page.text

    def test_filter_by_jar(self, client, session):
        recipe = seed_recipe(session)
        jar = seed_jar(session)
        other = seed_jar(session, name="Soviet culture")
        start(client, recipe, jar_id=str(jar.id))
        wanted = start(client, recipe, jar_id=str(other.id))

        page = client.get(f"/bakes?jar={other.id}")
        assert page.text.count('class="card bake-row"') == 1
        assert f'href="/bakes/{wanted}"' in page.text

    def test_filter_by_rating(self, client, session):
        recipe = seed_recipe(session)
        good = start(client, recipe)
        start(client, recipe)
        client.post(f"/bakes/{good}/result", data={"rating": "5"})

        page = client.get("/bakes?rating=4")
        assert page.text.count('class="card bake-row"') == 1

    def test_filter_by_status(self, client, session):
        recipe = seed_recipe(session)
        start(client, recipe)
        running = start(client, recipe, start_now="1")

        page = client.get("/bakes?status=in_progress")
        assert page.text.count('class="card bake-row"') == 1
        assert f'/bakes/{running}"' in page.text

    def test_a_filter_that_matches_nothing_says_so(self, client, session):
        seed_recipe(session)
        page = client.get("/bakes?rating=5")
        assert "Nothing matches that" in page.text

    def test_clear_appears_only_when_filtering(self, client, session):
        seed_recipe(session)
        assert "Clear" not in client.get("/bakes").text
        assert "Clear" in client.get("/bakes?rating=5").text


class TestWhereBakesShowUp:
    def test_on_the_recipe_version_page(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        page = client.get(f"/recipes/{recipe.id}/v/1")
        assert "Bakes from v1" in page.text
        assert f'href="/bakes/{bake_id}"' in page.text

    def test_on_the_jar_page(self, client, session):
        recipe = seed_recipe(session)
        jar = seed_jar(session)
        bake_id = start(client, recipe, jar_id=str(jar.id))
        page = client.get(f"/jars/{jar.id}")
        assert "Bakes it raised" in page.text
        assert f'href="/bakes/{bake_id}"' in page.text

    def test_a_jar_with_no_bakes_says_nothing_about_them(self, client, session):
        jar = seed_jar(session)
        assert "Bakes it raised" not in client.get(f"/jars/{jar.id}").text

    def test_archived_bakes_drop_off_the_recipe_page(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        client.post(f"/bakes/{bake_id}/archive", data={"archived": "1"})

        page = client.get(f"/recipes/{recipe.id}/v/1")
        assert "Nothing baked from this version yet" in page.text
        # Still reachable by its own link.
        assert client.get(f"/bakes/{bake_id}").status_code == 200

    def test_every_page_links_to_bakes(self, client, session):
        seed_recipe(session)
        for url in ["/", "/recipes", "/bakes", "/equipment"]:
            assert 'href="/bakes"' in client.get(url).text, url


class TestTheListsDoNotRepeatThemselves:
    def test_a_versions_own_page_leaves_the_version_out(self, client, session):
        recipe = seed_recipe(session)
        jar = seed_jar(session)
        start(client, recipe, jar_id=str(jar.id))

        page = client.get(f"/recipes/{recipe.id}/v/1")
        rows = page.text.split("Bakes from v1")[1]
        assert "Homemade rye" in rows
        assert "Oven · Homemade rye" in rows

    def test_a_jars_own_page_leaves_the_jar_out(self, client, session):
        recipe = seed_recipe(session)
        jar = seed_jar(session)
        start(client, recipe, jar_id=str(jar.id))

        page = client.get(f"/jars/{jar.id}")
        rows = page.text.split("Bakes it raised")[1]
        assert "v1 · Oven" in rows
        # The jar's own name is the page title; no need to say it again.
        assert "v1 · Oven · Homemade rye" not in rows

    def test_the_planned_total_says_its_unit(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe, start_now="1")
        assert "planned 690 min" in client.get(f"/bakes/{bake_id}").text


class TestLoafButtons:
    """A bread maker is sold by loaf size, not by flour weight."""

    def test_the_form_offers_the_three_machine_sizes(self, client, session):
        recipe = seed_recipe(session)

        page = client.get(f"/bakes/new?recipe_id={recipe.id}&version=1")

        assert "2 lb" in page.text
        assert "2.5 lb" in page.text
        assert "3 lb" in page.text

    def test_each_button_carries_the_flour_it_needs(self, client, session):
        recipe = seed_recipe(session)

        page = client.get(f"/bakes/new?recipe_id={recipe.id}&version=1")

        # The seeded recipe is 212% of flour, so a 2 lb (907 g) pan wants
        # about 428 g. The button hands that to the JS as data-flour.
        assert re.search(r'data-flour="4[0-9]{2}(\.\d)?"', page.text), page.text

    def test_a_flour_weight_typed_in_is_still_what_gets_saved(
        self, client, session
    ):
        """The buttons only fill the field; the form still decides."""
        recipe = seed_recipe(session)
        bake_id = start(client, recipe, total_flour_g="497", loaf_size="2.5 lb")

        page = client.get(f"/bakes/{bake_id}").text
        assert "497 g" in page


class TestTheRecipesDefaults:
    """A seeded bread-maker recipe opens the start form ready to go."""

    def _recipe_with_defaults(self, session):
        from app.services import seeding

        seeding.seed_all(session)
        session.commit()
        program = seeding.find_program(session, "West Bend L5951", "Basic")
        recipe = recipe_service.create_recipe(
            session,
            name="Old-fashioned white",
            category=RecipeCategory.WHEAT,
            ingredients=[
                IngredientSpec("Bread flour", IngredientRole.FLOUR, 100.0),
                IngredientSpec("Water", IngredientRole.WATER, 62.0),
            ],
        )
        version = recipe.latest_version
        version.default_program_id = program.id
        version.default_loaf_size = "2.5 lb"
        version.default_crust = "medium"
        session.commit()
        return recipe, version, program

    def test_the_form_opens_with_the_program_chosen(self, client, session):
        recipe, version, program = self._recipe_with_defaults(session)

        page = client.get(
            f"/bakes/new?recipe_id={recipe.id}&version={version.version}"
        ).text

        assert re.search(rf'value="{program.id}"\s+selected', page)

    def test_the_loaf_size_and_crust_are_filled_in(self, client, session):
        recipe, version, _ = self._recipe_with_defaults(session)

        page = client.get(
            f"/bakes/new?recipe_id={recipe.id}&version={version.version}"
        ).text

        assert 'name="loaf_size" value="2.5 lb"' in page
        assert 'name="crust_setting" value="medium"' in page

    def test_the_method_starts_on_bread_maker(self, client, session):
        recipe, version, _ = self._recipe_with_defaults(session)

        page = client.get(
            f"/bakes/new?recipe_id={recipe.id}&version={version.version}"
        ).text

        assert re.search(r'value="bread_maker"\s+selected', page)

    def test_a_recipe_without_defaults_opens_blank(self, client, session):
        recipe = recipe_service.create_recipe(
            session, name="Plain rye", category=RecipeCategory.RYE,
            ingredients=[IngredientSpec("Rye", IngredientRole.FLOUR, 100.0)],
        )
        session.commit()

        page = client.get(
            f"/bakes/new?recipe_id={recipe.id}&version=1"
        ).text

        assert 'name="loaf_size" value=""' in page
        assert 'name="crust_setting" value=""' in page

    def test_what_the_baker_typed_survives_a_validation_error(self, client, session):
        """The recipe's defaults must not overwrite a rejected form."""
        recipe, version, program = self._recipe_with_defaults(session)

        response = client.post(
            "/bakes/new",
            data={
                "recipe_id": recipe.id,
                "version": version.version,
                "method": "bread_maker",
                "loaf_size": "3 lb",
                "crust_setting": "dark",
                "total_flour_g": "not a number",
            },
        )

        assert response.status_code == 400
        assert 'name="loaf_size" value="3 lb"' in response.text
        assert 'name="crust_setting" value="dark"' in response.text


def test_a_recipe_has_one_button_for_baking_it_and_the_planner_is_a_step_on(
    client, session
):
    """"Plan a bake" and "Bake this" side by side were two buttons for one
    intention. The recipe offers Bake this; the start page offers the
    planner for a loaf that has to be ready at a set time."""
    recipe = seed_recipe(session)
    version_id = recipe.latest_version.id
    recipe_id = recipe.id
    session.rollback()

    page = client.get(f"/recipes/{recipe_id}/v/1").text
    header = page.split('<nav class="topnav"')[1].split("</nav>")[0]
    assert "Bake this" in header
    assert "Plan a bake" not in header and "/plan" not in header

    start = client.get(f"/bakes/new?recipe_id={recipe_id}&version=1").text
    assert f'href="/plan?version={version_id}"' in start
