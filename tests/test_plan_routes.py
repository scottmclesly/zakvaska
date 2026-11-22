"""The /plan page: inputs in the query string, an answer on the page.

A plan is not stored — it is recomputed from the URL every time, which is
what makes it both shareable as a link and scrubbable with the slider. These
check that the page survives whatever arrives in the query string, and that
the slider's partial really is just the part that changes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import BusyKind, IngredientRole, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import (
    EquipmentCycle,
    EquipmentProgram,
    Recipe,
    RecipeIngredient,
    RecipeStage,
    RecipeVersion,
)
from app.services.units import f_to_c


def _recipe(session, *, stages=(), with_levain=True, name="Borodinsky"):
    recipe = Recipe(name=name)
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=500.0)
    session.add(version)
    session.flush()
    lines = [("whole rye flour", IngredientRole.FLOUR, 100.0)]
    if with_levain:
        lines.append(("rye levain", IngredientRole.LEVAIN, 30.0))
    for seq, (line_name, role, pct) in enumerate(lines):
        session.add(
            RecipeIngredient(
                version_id=version.id, seq=seq, name=line_name,
                role=role, baker_pct=pct,
            )
        )
    for seq, (stage_name, minutes) in enumerate(stages):
        session.add(
            RecipeStage(
                version_id=version.id, seq=seq, name=stage_name,
                duration_min=minutes,
            )
        )
    session.commit()
    return version.id


def _jar(session, *, hours_ago=5, ratio=1.0, temp_c=None, name="Old Rye"):
    from app.models.base import utcnow

    jar = Jar(name=name, origin=JarOrigin.HOMEMADE)
    session.add(jar)
    session.flush()
    session.add(
        Feeding(
            jar_id=jar.id,
            fed_at=utcnow() - timedelta(hours=hours_ago),
            starter_g=20.0, flour_g=20.0 * ratio, water_g=20.0 * ratio,
            ambient_temp_c=temp_c,
        )
    )
    session.commit()
    return jar.id


def _program(session):
    program = EquipmentProgram(
        name="Basic", device="West Bend", menu_no=1, total_min=215
    )
    session.add(program)
    session.flush()
    session.add(
        EquipmentCycle(
            program_id=program.id, loaf_lb=2.0,
            knead1_min=12, rest_min=5, knead2_min=18, total_min=215,
        )
    )
    session.commit()
    return program.id


def _sleep(session):
    session.add(
        BusyBlock(
            label="Sleep", kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
            start_minute=120, end_minute=600,
        )
    )
    session.commit()


# --- The page -----------------------------------------------------------


def test_the_planner_opens_with_nothing_chosen(client):
    page = client.get("/plan")

    assert page.status_code == 200
    assert "Plan a bake" in page.text
    assert "Step by step" in page.text


def test_it_is_reachable_from_the_nav(client):
    assert 'href="/plan"' in client.get("/").text


def test_a_recipe_version_offers_to_plan_a_bake(client, session):
    version_id = _recipe(session)
    version = session.get(RecipeVersion, version_id)

    page = client.get(f"/recipes/{version.recipe_id}/v/1")

    assert f"/plan?version={version_id}" in page.text


def test_choosing_a_recipe_fills_the_plan_in(client, session):
    version_id = _recipe(session, stages=(("bake", 50),))

    page = client.get("/plan", params={"version": version_id})

    assert page.status_code == 200
    assert "Borodinsky" in page.text
    assert "Build the levain" in page.text
    assert "Cool on a rack" in page.text


def test_the_steps_come_out_in_order_with_clock_times(client, session):
    version_id = _recipe(session)

    page = client.get("/plan", params={"version": version_id})

    order = [
        page.text.index(name)
        for name in (
            "Build the levain", "Levain rises", "Mix, and load",
            "Shape into the greased pan", "Final rise in the pan",
            "Cool on a rack", "Bag it",
        )
    ]
    assert order == sorted(order)


def test_a_jar_puts_its_own_curve_above_the_steps(client, session):
    version_id = _recipe(session)
    jar_id = _jar(session, hours_ago=5, ratio=1.0, temp_c=f_to_c(78.0))

    page = client.get("/plan", params={"version": version_id, "jar": jar_id})

    assert "ribbon-path band-" in page.text
    # And the levain build is marked against it.
    assert "levain-mark" in page.text


def test_the_recipes_levain_line_becomes_an_amount(client, session):
    version_id = _recipe(session, with_levain=True)

    page = client.get("/plan", params={"version": version_id})

    # 30% of 500 g.
    assert "150 g" in page.text


def test_a_recipe_stage_shows_as_coming_from_the_recipe(client, session):
    version_id = _recipe(session, stages=(("bake", 50),))

    page = client.get("/plan", params={"version": version_id})

    assert "from the recipe" in page.text


# --- The two directions -------------------------------------------------


def test_starting_at_a_time_lays_the_steps_out_from_it(client, session):
    version_id = _recipe(session)
    start = datetime.now(UTC) + timedelta(hours=3)

    page = client.get(
        "/plan",
        params={
            "version": version_id, "mode": "start",
            "at": start.astimezone(
                __import__("zoneinfo").ZoneInfo("America/New_York")
            ).strftime("%Y-%m-%dT%H:%M"),
        },
    )

    assert page.status_code == 200
    assert "Start at" in page.text


def test_asking_for_bread_by_a_time_works_backwards_to_it(client, session):
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    version_id = _recipe(session)
    want = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )

    page = client.get(
        "/plan",
        params={
            "version": version_id, "mode": "ready",
            "at": want.strftime("%Y-%m-%dT%H:%M"),
        },
    )

    assert page.status_code == 200
    assert "Bread out at 18:00" in page.text


# --- Conflicts and the way out -----------------------------------------


def test_a_plan_landing_in_the_night_says_which_steps_clash(client, session):
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    version_id = _recipe(session)
    _sleep(session)
    # Start at 20:00 local: the long final rise ends in the small hours.
    start = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )

    page = client.get(
        "/plan",
        params={
            "version": version_id, "mode": "start",
            "at": start.strftime("%Y-%m-%dT%H:%M"),
        },
    )

    assert "land" in page.text and "where you are busy" in page.text
    assert "inside Sleep" in page.text


def test_a_clashing_plan_offers_a_time_that_works(client, session):
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    version_id = _recipe(session)
    _sleep(session)
    start = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )

    page = client.get(
        "/plan",
        params={
            "version": version_id, "mode": "start",
            "at": start.strftime("%Y-%m-%dT%H:%M"),
        },
    )

    assert "Find a time that works" in page.text


def test_the_offered_time_keeps_the_rest_of_the_plan(client, session):
    """Jumping to a workable start must not throw away the recipe."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    version_id = _recipe(session)
    jar_id = _jar(session)
    _sleep(session)
    start = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )

    page = client.get(
        "/plan",
        params={
            "version": version_id, "jar": jar_id, "cool": "90",
            "mode": "start", "at": start.strftime("%Y-%m-%dT%H:%M"),
        },
    )

    form = page.text.split("Find a time that works")[0]
    block = form[form.rindex("<form method=\"get\" action=\"/plan\">"):]
    assert f'value="{version_id}"' in block
    assert f'value="{jar_id}"' in block
    assert 'value="90"' in block


def test_a_plan_that_works_says_so_plainly(client, session):
    version_id = _recipe(session)

    page = client.get("/plan", params={"version": version_id})

    # No busy blocks at all, so nothing can clash.
    assert "Nothing lands anywhere you are busy" in page.text


# --- The slider ---------------------------------------------------------


def test_the_slider_swaps_in_only_the_part_that_changed(client, session):
    version_id = _recipe(session)

    response = client.get(
        "/plan/steps", params={"version": version_id, "offset": "180"}
    )

    assert response.status_code == 200
    assert 'id="plan-result"' in response.text
    assert "<html" not in response.text
    assert "Step by step" in response.text


def test_moving_the_slider_moves_the_steps(client, session):
    version_id = _recipe(session)

    early = client.get(
        "/plan/steps", params={"version": version_id, "offset": "0"}
    ).text
    later = client.get(
        "/plan/steps", params={"version": version_id, "offset": "240"}
    ).text

    assert early != later


def test_the_slider_works_backwards_too(client, session):
    version_id = _recipe(session)

    response = client.get(
        "/plan/steps",
        params={"version": version_id, "mode": "ready", "offset": "600"},
    )

    assert response.status_code == 200
    assert "Bread out at" in response.text


# --- The bread maker ----------------------------------------------------


def test_choosing_a_program_uses_the_manuals_knead_times(client, session):
    version_id = _recipe(session)
    program_id = _program(session)

    page = client.get(
        "/plan",
        params={"version": version_id, "program": program_id, "loaf": "2"},
    )

    assert "Basic — knead, rest, knead" in page.text


def test_letting_the_machine_run_it_all_replaces_the_hand_steps(client, session):
    version_id = _recipe(session)
    program_id = _program(session)

    page = client.get(
        "/plan",
        params={
            "version": version_id, "program": program_id,
            "loaf": "2", "whole": "1",
        },
    )

    assert "Basic runs" in page.text
    assert "Shape into the greased pan" not in page.text


# --- It survives whatever arrives in the query string -------------------


def test_nonsense_numbers_fall_back_rather_than_erroring(client, session):
    version_id = _recipe(session)

    page = client.get(
        "/plan",
        params={
            "version": version_id, "ratio": "banana", "temp": "",
            "cool": "???", "loaf": "x",
        },
    )

    assert page.status_code == 200
    assert "Step by step" in page.text
    assert "was not a number" in page.text


def test_an_unreadable_time_falls_back_and_says_so(client, session):
    version_id = _recipe(session)

    page = client.get(
        "/plan", params={"version": version_id, "at": "half past tuesday"}
    )

    assert page.status_code == 200
    assert "not a time I could read" in page.text


def test_a_version_that_does_not_exist_is_not_a_crash(client):
    page = client.get("/plan", params={"version": "99999"})

    assert page.status_code == 200
    assert "Plan a bake" in page.text


def test_a_jar_that_does_not_exist_is_not_a_crash(client, session):
    version_id = _recipe(session)

    page = client.get("/plan", params={"version": version_id, "jar": "99999"})

    assert page.status_code == 200


def test_the_levain_ratio_can_be_changed_and_shows_its_working(client, session):
    version_id = _recipe(session)

    tight = client.get(
        "/plan/steps", params={"version": version_id, "ratio": "1"}
    ).text
    loose = client.get(
        "/plan/steps", params={"version": version_id, "ratio": "5"}
    ).text

    assert "1:1:1" in tight
    assert "1:5:5" in loose
    assert tight != loose


def test_the_temperature_is_read_in_the_unit_on_display(client, session):
    version_id = _recipe(session)

    # 68 °F is 20 °C: a cool room, so a slower levain than the 80 °F default.
    cool = client.get(
        "/plan/steps", params={"version": version_id, "temp": "68"}
    ).text
    warm = client.get(
        "/plan/steps", params={"version": version_id, "temp": "86"}
    ).text

    assert cool != warm
