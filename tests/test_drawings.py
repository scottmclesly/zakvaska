"""The drawn jars, the shelf they stand on, and the role glyphs.

Pictures are easy to break silently, so these check the things that carry
meaning: the label, the state, and the level the jar is filled to.
"""

from __future__ import annotations

import re
from datetime import timedelta

from app.models.enums import IngredientRole, JarOrigin, JarState, RecipeCategory
from app.models.recipe import EquipmentCycle
from app.services import jars as jar_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec


def make_jar(session, *, name="Homemade rye", state=JarState.ACTIVE, **kwargs):
    jar = jar_service.create_jar(
        session, name=name, origin=JarOrigin.HOMEMADE, state=state, **kwargs
    )
    session.commit()
    return jar


def fill_top(body: str) -> float:
    """The y the contents start at: lower number, fuller jar.

    The drawing publishes it as data-fill so this does not have to read it
    back out of path geometry.
    """
    match = re.search(r'data-fill="([\d.]+)"', body)
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

    def test_the_label_carries_the_jar_name(self, client, session):
        """The whole point of drawing a jar is telling it from the other one."""
        jar = make_jar(session, name="Rye jar")

        body = client.get(f"/jars/{jar.id}").text

        assert ">Rye jar</text>" in body

    def test_a_long_name_is_cut_rather_than_shrunk_past_reading(
        self, client, session
    ):
        """Pen on tape has to stay readable, so the name gives way first."""
        short = make_jar(session, name="Rye")
        long = make_jar(session, name="Soviet rye culture, second split")

        def label(jar):
            body = client.get(f"/jars/{jar.id}").text
            match = re.search(
                r'class="jar-label-name"[^>]*font-size="([\d.]+)"[^>]*>([^<]*)<',
                body,
            )
            assert match, body[:400]
            return float(match.group(1)), match.group(2)

        short_size, short_text = label(short)
        long_size, long_text = label(long)

        assert short_text == "Rye"
        assert len(long_text) <= 10
        assert long_text.startswith("Soviet")
        assert long_size < short_size
        # However long the name, the writing stays big enough to read.
        assert long_size >= 6.2

    def test_the_label_says_control_on_the_control_jar(self, client, session):
        jar = make_jar(session, name="Soviet", is_control=True)

        body = client.get(f"/jars/{jar.id}").text

        assert "jar-label-sub is-control" in body
        assert ">control</text>" in body

    def test_the_label_otherwise_names_the_flour(self, client, session):
        jar = make_jar(session, name="Homemade", flour_type="whole rye")

        body = client.get(f"/jars/{jar.id}").text

        assert ">whole rye</text>" in body

    def test_a_dried_jar_draws_flakes_rather_than_a_pourable_mass(
        self, client, session
    ):
        dried = make_jar(session, name="Dried", state=JarState.DRIED)
        active = make_jar(session, name="Active")

        assert "jar-flake" in client.get(f"/jars/{dried.id}").text
        assert "jar-flake" not in client.get(f"/jars/{active.id}").text

    def test_a_dormant_jar_throws_hooch(self, client, session):
        dormant = make_jar(session, name="Dormant", state=JarState.DORMANT)
        active = make_jar(session, name="Active")

        assert "jar-hooch" in client.get(f"/jars/{dormant.id}").text
        assert "jar-hooch" not in client.get(f"/jars/{active.id}").text

    def test_a_jar_in_the_cold_frosts_up(self, client, session):
        cold = make_jar(session, name="Cold", state=JarState.FRIDGE)
        active = make_jar(session, name="Active")

        assert "jar-frost" in client.get(f"/jars/{cold.id}").text
        assert "jar-frost" not in client.get(f"/jars/{active.id}").text


class TestTheShelf:
    def test_the_jars_stand_on_a_shelf_on_the_dashboard(self, client, session):
        make_jar(session)

        body = client.get("/").text

        assert 'class="shelf"' in body
        assert "shelf-plank" in body
        assert "jar-art-shelf" in body

    def test_each_jar_on_the_shelf_links_to_its_page(self, client, session):
        jar = make_jar(session)

        body = client.get("/").text

        assert f'class="shelf-jar" href="/jars/{jar.id}"' in body

    def test_a_shelf_jar_fills_to_its_own_measured_rise(self, client, session):
        """Two jars side by side is the experiment; the shelf has to show it."""
        quiet = make_jar(session, name="Quiet")
        lively = make_jar(session, name="Lively")
        jar_service.log_observation(
            session, quiet, start_height_mm=40, height_mm=46
        )
        jar_service.log_observation(
            session, lively, start_height_mm=40, height_mm=96
        )
        session.commit()

        body = client.get("/").text
        fills = [float(f) for f in re.findall(r'data-fill="([\d.]+)"', body)]

        assert len(fills) == 2
        assert min(fills) < max(fills)

    def test_an_overdue_jar_wears_a_tag(self, client, session):
        jar = make_jar(session)
        jar.feed_interval_room_h = 1
        jar_service.log_feeding(
            session, jar, starter_g=20, flour_g=40, water_g=40
        )
        session.commit()
        jar.feedings[0].fed_at = jar.feedings[0].fed_at.replace(year=2020)
        session.commit()

        body = client.get("/").text

        assert "shelf-tag" in body
        assert "feed me" in body

    def test_an_empty_shelf_stands_there_before_the_first_jar(self, client):
        body = client.get("/").text

        assert "shelf-bare" in body
        assert "jar-ghost" in body

    def test_the_jar_on_its_own_page_stands_on_a_plank_too(
        self, client, session
    ):
        jar = make_jar(session)

        assert "shelf-plank-sm" in client.get(f"/jars/{jar.id}").text


class TestTheShelfOfPutAwayJars:
    """Jars are archived, never deleted, so they get a shelf of their own."""

    def put_away(self, session, name="Old starter"):
        jar = make_jar(session, name=name)
        jar_service.set_archived(session, jar, True)
        session.commit()
        return jar

    def test_an_archived_jar_stands_on_the_shelf_below(self, client, session):
        jar = self.put_away(session)

        body = client.get("/").text

        assert "shelf-put-away" in body
        assert "jar-art-put-away" in body
        assert f'class="shelf-jar" href="/jars/{jar.id}"' in body

    def test_a_put_away_jar_is_drawn_dusty_and_a_live_one_is_not(
        self, client, session
    ):
        make_jar(session, name="Still going")
        live_only = client.get("/").text

        self.put_away(session)
        both = client.get("/").text

        assert "jar-dust" not in live_only
        assert "jar-dust" in both

    def test_it_is_still_labelled_with_its_name(self, client, session):
        self.put_away(session, name="Old rye")

        assert ">Old rye</text>" in client.get("/").text

    def test_an_archived_jar_is_not_also_on_the_live_shelf(
        self, client, session
    ):
        """Once, on the lower shelf — a second copy would read as two jars."""
        jar = self.put_away(session)

        body = client.get("/").text

        assert body.count(f'id="jarbody-{jar.id}"') == 1

    def test_there_is_no_lower_shelf_when_nothing_is_archived(
        self, client, session
    ):
        make_jar(session)

        assert "shelf-put-away" not in client.get("/").text


class TestCozyFurniture:
    def test_the_brand_mark_is_drawn_not_an_emoji(self, client):
        body = client.get("/").text

        assert "brand-art" in body
        assert "🫙" not in body

    def test_there_is_a_sprig_of_wheat_in_the_footer(self, client):
        assert "sprig-footer" in client.get("/").text

    def test_the_decoration_is_hidden_from_screen_readers(self, client):
        """A screen reader should hear the jars, not the furniture."""
        body = client.get("/").text
        for mark in ("brand-art", "sprig "):
            glyph = body[body.index(mark) - 120:]
            assert 'aria-hidden="true"' in glyph[:260], mark

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


def make_recipe(session, *, name="Rye loaf", category=RecipeCategory.RYE,
                ingredients=None, stages=None):
    recipe = recipe_service.create_recipe(
        session,
        name=name,
        category=category,
        ingredients=ingredients
        or [
            IngredientSpec("Whole rye", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 78.0),
        ],
        stages=stages or [StageSpec("bake", duration_min=50)],
    )
    session.commit()
    return recipe


class TestTheDrawnLoaf:
    def test_every_category_gets_its_own_loaf(self, client, session):
        for category in RecipeCategory:
            make_recipe(session, name=f"A {category.value}", category=category)

        body = client.get("/recipes").text

        for category in RecipeCategory:
            assert f"loaf-art loaf-{category.value}" in body, category

    def test_a_rye_is_drawn_as_a_rye_and_not_as_a_boule(self, client, session):
        make_recipe(session, category=RecipeCategory.RYE)

        body = client.get("/recipes").text

        assert "loaf-rye" in body
        assert "loaf-wheat" not in body

    def test_the_recipe_page_puts_a_big_one_on_a_plank(self, client, session):
        recipe = make_recipe(session)

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        assert "loaf-art-lg" in body
        assert "shelf-plank-sm" in body

    def test_it_says_in_words_what_it_is(self, client, session):
        make_recipe(session, category=RecipeCategory.WHEAT)

        assert 'aria-label="a scored round loaf"' in client.get("/recipes").text


class TestBakersPercentBars:
    def test_each_ingredient_gets_a_bar_the_width_of_its_share(
        self, client, session
    ):
        recipe = make_recipe(
            session,
            ingredients=[
                IngredientSpec("Bread flour", IngredientRole.FLOUR, 100.0),
                IngredientSpec("Water", IngredientRole.WATER, 64.0),
            ],
        )

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        assert 'class="pctbar-fill role-flour"\n                  style="width: 100.0%"' in body
        assert 'class="pctbar-fill role-water"\n                  style="width: 64.0%"' in body

    def test_a_line_over_a_hundred_percent_stops_at_the_full_bar(
        self, client, session
    ):
        recipe = make_recipe(
            session,
            ingredients=[
                IngredientSpec("Rye", IngredientRole.FLOUR, 100.0),
                IngredientSpec("Scald water", IngredientRole.WATER, 140.0),
            ],
        )

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        assert "140.0%" not in body.split("pctbar")[1][:200]
        assert "140.0%" in body  # still written out in the figures

    def test_the_bars_are_hidden_from_screen_readers(self, client, session):
        """The percentage is right next to them in figures."""
        recipe = make_recipe(session)

        body = client.get(f"/recipes/{recipe.id}/v/1").text
        bar = body[body.index('class="pctbar"') - 40:]

        assert 'aria-hidden="true"' in bar[:120]


class TestTheStageRibbon:
    def test_stages_are_laid_out_in_proportion_to_their_minutes(
        self, client, session
    ):
        recipe = make_recipe(
            session,
            stages=[
                StageSpec("bulk ferment", duration_min=180),
                StageSpec("bake", duration_min=60),
            ],
        )

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        assert "stage-ribbon" in body
        assert "flex-grow: 75.0" in body
        assert "flex-grow: 25.0" in body

    def test_a_stage_is_coloured_by_what_it_is(self, client, session):
        recipe = make_recipe(
            session,
            stages=[
                StageSpec("scald (zavarka)", duration_min=840),
                StageSpec("bulk ferment", duration_min=120),
                StageSpec("bake", duration_min=60),
            ],
        )

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        for key in ("seg-scald", "seg-rise", "seg-bake"):
            assert key in body, key

    def test_an_untimed_stage_is_drawn_to_no_scale_and_says_so(
        self, client, session
    ):
        recipe = make_recipe(
            session,
            stages=[
                StageSpec("bulk ferment", duration_min=120),
                StageSpec("shape"),
            ],
        )

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        assert "is-unknown" in body
        assert "drawn to no scale" in body

    def test_stages_with_no_times_at_all_draw_no_ribbon(self, client, session):
        recipe = make_recipe(session, stages=[StageSpec("mix"), StageSpec("bake")])

        body = client.get(f"/recipes/{recipe.id}/v/1").text

        assert "stage-ribbon" not in body
        assert "mix" in body  # the list of stages is still there


class TestTheBreadMaker:
    def test_it_is_drawn_on_the_equipment_page(self, client, session):
        body = client.get("/equipment").text

        assert "machine-art" in body
        assert 'aria-label="A bread maker with its lid down"' in body

    def test_a_programs_cycle_is_drawn_to_scale(self, client, session):
        program = recipe_service.create_program(
            session, name="Basic", device="West Bend", total_min=180
        )
        session.add(
            EquipmentCycle(
                program_id=program.id, loaf_lb=2.0, knead1_min=10, rest_min=25,
                knead2_min=15, rise2_min=20, stir_down_sec=30, rise3_min=41,
                bake_min=69, total_min=180,
            )
        )
        session.commit()

        body = client.get("/equipment").text

        assert "timebar-track" in body
        for key in ("seg-knead", "seg-rest", "seg-rise", "seg-stir", "seg-bake"):
            assert key in body, key

    def test_the_bar_shows_the_manuals_own_total(self, client, session):
        """The manual's figure is not always its own segments added up."""
        program = recipe_service.create_program(
            session, name="Cake", total_min=100
        )
        session.add(
            EquipmentCycle(
                program_id=program.id, loaf_lb=2.0, knead1_min=15,
                bake_min=75, total_min=100,
            )
        )
        session.commit()

        body = client.get("/equipment").text

        assert "1:40" in body
        assert "Not broken down" in body

    def test_a_program_the_manual_does_not_break_down_draws_no_bar(
        self, client, session
    ):
        program = recipe_service.create_program(
            session, name="Custom", total_min=185
        )
        session.add(
            EquipmentCycle(
                program_id=program.id, stir_down_sec=30, total_min=185
            )
        )
        session.commit()

        body = client.get("/equipment").text

        assert "timebar-track" not in body

    def test_the_bar_reads_out_as_words(self, client, session):
        program = recipe_service.create_program(session, name="Dough", total_min=110)
        session.add(
            EquipmentCycle(
                program_id=program.id, knead1_min=12, rest_min=20, knead2_min=8,
                rise2_min=25, rise3_min=45, total_min=110,
            )
        )
        session.commit()

        body = client.get("/equipment").text

        assert "Knead 1 12 min, Rest 20 min" in body


class TestTheRiseChart:
    def test_two_observations_put_a_chart_on_the_jars_page(
        self, client, session, frozen_now
    ):
        jar = make_jar(session)
        for hours, height in ((0, 40.0), (6, 70.0)):
            jar_service.log_observation(
                session, jar,
                observed_at=frozen_now - timedelta(hours=12 - hours),
                start_height_mm=35.0, height_mm=height,
            )
        session.commit()

        body = client.get(f"/jars/{jar.id}").text

        assert "HOW IT RISES".lower() in body.lower()
        assert "chart-path" in body

    def test_one_observation_is_not_a_chart(self, client, session, frozen_now):
        jar = make_jar(session)
        jar_service.log_observation(
            session, jar, observed_at=frozen_now,
            start_height_mm=35.0, height_mm=70.0,
        )
        session.commit()

        assert "chart-path" not in client.get(f"/jars/{jar.id}").text

    def test_an_observation_with_no_measurements_does_not_plot(
        self, client, session, frozen_now
    ):
        jar = make_jar(session)
        for _ in range(3):
            jar_service.log_observation(
                session, jar, observed_at=frozen_now, bubbles=None
            )
        session.commit()

        assert "chart-path" not in client.get(f"/jars/{jar.id}").text

    def test_the_dashboard_overlays_the_jars_against_each_other(
        self, client, session, frozen_now
    ):
        homemade = make_jar(session, name="Homemade rye")
        control = make_jar(session, name="Soviet", is_control=True)
        for jar, height in ((homemade, 55.0), (control, 80.0)):
            jar_service.log_observation(
                session, jar, observed_at=frozen_now - timedelta(hours=6),
                start_height_mm=35.0, height_mm=height,
            )
        session.commit()

        body = client.get("/").text

        assert "chart-key" in body
        assert "slot-1" in body and "slot-2" in body
        assert "Homemade rye" in body and "Soviet" in body

    def test_the_control_is_dashed_as_well_as_coloured(
        self, client, session, frozen_now
    ):
        """So which line is which survives colour blindness."""
        homemade = make_jar(session, name="Homemade rye")
        control = make_jar(session, name="Soviet", is_control=True)
        for jar, height in ((homemade, 55.0), (control, 80.0)):
            jar_service.log_observation(
                session, jar, observed_at=frozen_now - timedelta(hours=6),
                start_height_mm=35.0, height_mm=height,
            )
        session.commit()

        body = client.get("/").text

        assert "chart-line slot-2 is-control" in body

    def test_an_empty_dashboard_draws_no_chart(self, client):
        assert "chart-path" not in client.get("/").text
