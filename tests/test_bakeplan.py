"""The bake-day planner.

Phase C's acceptance checks: with fixed inputs and a fixed "now" the step
times match figures worked out by hand, conflicts and the earliest-workable
search behave, and back-scheduling produces the same plan as the equivalent
forward one.

The hand-computed chain used throughout, from a jar sitting at its peak:

    build the levain            10 min
    levain rises           2:2 at 26.7 °C  -> predict_peak_h
    mix and load                 5 min
    knead                       25 min   (no program chosen)
    shape                       10 min
    final rise                 300 min   (starter only)
    bake                        45 min
    cool                       120 min
    bag                          2 min
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import BusyKind, IngredientRole, JarOrigin, JarState
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
from app.services import bakeplan, busy as busy_service, plan as plan_service, timing
from app.services.bakeplan import PlanInputs
from app.services.units import f_to_c

TZ = ZoneInfo("America/New_York")


def _at(day, hour=0, minute=0):
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


#: 10:00 local on 1 June — the one start, on the hour, from which the whole
#: fifteen-hour chain clears a 02:00-10:00 sleep block. Worth naming, because
#: it is the answer the planner exists to find, and it is also the hour Scott
#: actually gets up.
WORKS_AT = _at(1, 14)


def _inputs(**kw) -> PlanInputs:
    """Fixed inputs: 1:2:2 levain at 26.7 °C, no program, starter only."""
    base = dict(
        total_flour_g=500.0,
        start_at=_at(1, 12),
        levain_ratio=2.0,
        levain_temp_c=26.7,
        knead_only=True,
    )
    base.update(kw)
    return PlanInputs(**base)


def _specs(version=None, program=None, inputs=None):
    return bakeplan.step_specs(
        inputs or _inputs(), version=version, program=program
    )


def _recipe(session, *, stages=(), ingredients=(("whole rye flour", "flour", 100.0),)):
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=500.0)
    session.add(version)
    session.flush()
    for seq, (name, role, pct) in enumerate(ingredients):
        session.add(
            RecipeIngredient(
                version_id=version.id, seq=seq, name=name,
                role=IngredientRole(role), baker_pct=pct,
            )
        )
    for seq, (name, minutes) in enumerate(stages):
        session.add(
            RecipeStage(
                version_id=version.id, seq=seq, name=name, duration_min=minutes
            )
        )
    session.flush()
    session.refresh(version)
    return version


def _jar(session, *, fed_at=None, ratio=1.0, temp_c=None, state=JarState.ACTIVE):
    jar = Jar(name="Old Rye", origin=JarOrigin.HOMEMADE, state=state)
    session.add(jar)
    session.flush()
    if fed_at is not None:
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=fed_at, starter_g=20.0,
                flour_g=20.0 * ratio, water_g=20.0 * ratio, ambient_temp_c=temp_c,
            )
        )
        session.flush()
    return jar


def _sleep(session, start_min=120, end_min=600, label="Sleep"):
    session.add(
        BusyBlock(
            label=label, kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
            start_minute=start_min, end_minute=end_min,
        )
    )
    session.flush()


def _intervals(session, start, end):
    return busy_service.busy_intervals(session, start, end, TZ)


# --- The chain ----------------------------------------------------------


def test_the_chain_is_the_steps_the_plan_calls_for():
    keys = [one.key for one in _specs()]

    assert keys == [
        "levain", "levain_rise", "load", "knead",
        "shape", "final_rise", "bake", "cool", "bag",
    ]


def test_the_hands_on_steps_are_the_ones_that_need_doing():
    specs = {one.key: one for one in _specs()}

    for key in ("levain", "load", "shape", "bake", "bag"):
        assert specs[key].hands_on, key
    for key in ("levain_rise", "knead", "final_rise", "cool"):
        assert not specs[key].hands_on, key


def test_a_rise_needs_you_there_at_the_end_of_it():
    specs = {one.key: one for one in _specs()}

    assert specs["levain_rise"].must_be_home
    assert specs["final_rise"].must_be_home
    # Cooling and bagging mind nobody.
    assert not specs["cool"].must_be_home


def test_the_levain_rise_comes_from_the_timing_model():
    rise = next(one for one in _specs() if one.key == "levain_rise")

    assert rise.duration_min == pytest.approx(
        timing.predict_peak_h(2.0, 26.7) * 60
    )


def test_a_tighter_levain_shortens_the_day():
    tight = bakeplan.chain_minutes(_specs(inputs=_inputs(levain_ratio=1.0)))
    loose = bakeplan.chain_minutes(_specs(inputs=_inputs(levain_ratio=5.0)))

    assert tight < loose


def test_a_warmer_levain_shortens_the_day():
    warm = bakeplan.chain_minutes(_specs(inputs=_inputs(levain_temp_c=30.0)))
    cool = bakeplan.chain_minutes(_specs(inputs=_inputs(levain_temp_c=20.0)))

    assert warm < cool


def test_a_starter_only_loaf_gets_the_longer_final_rise(session):
    version = _recipe(session)

    rise = next(
        one for one in _specs(version=version) if one.key == "final_rise"
    )

    assert rise.duration_min == bakeplan.FINAL_RISE_STARTER_MIN


def test_a_recipe_with_instant_yeast_gets_the_shorter_one(session):
    version = _recipe(
        session,
        ingredients=(
            ("whole rye flour", "flour", 100.0),
            ("instant yeast", "other", 1.0),
        ),
    )

    rise = next(
        one for one in _specs(version=version) if one.key == "final_rise"
    )

    assert rise.duration_min == bakeplan.FINAL_RISE_YEAST_MIN


# --- The recipe overrides where it says so ------------------------------


def test_a_recipe_stage_beats_the_generated_estimate(session):
    version = _recipe(session, stages=(("bake", 55), ("cool", 90)))

    specs = {one.key: one for one in _specs(version=version)}

    assert specs["bake"].duration_min == 55
    assert specs["bake"].from_recipe
    assert specs["cool"].duration_min == 90


def test_a_stage_name_does_not_have_to_match_exactly(session):
    version = _recipe(session, stages=(("final proof (in the pan)", 180),))

    rise = next(
        one for one in _specs(version=version) if one.key == "final_rise"
    )

    assert rise.duration_min == 180


def test_a_stage_with_no_time_against_it_does_not_override(session):
    version = _recipe(session, stages=(("bake", None),))

    bake = next(one for one in _specs(version=version) if one.key == "bake")

    assert bake.duration_min == bakeplan.DEFAULT_BAKE_MIN
    assert not bake.from_recipe


def test_what_the_form_says_beats_what_the_recipe_says(session):
    """A typed-in figure is the most recent intent, so it wins."""
    version = _recipe(session, stages=(("bake", 55),))

    bake = next(
        one
        for one in _specs(version=version, inputs=_inputs(bake_min=40))
        if one.key == "bake"
    )

    assert bake.duration_min == 40


# --- The bread maker ----------------------------------------------------


def _program(session, *, knead1=12, rest=5, knead2=18, total=215, loaf_lb=2.0):
    program = EquipmentProgram(name="Basic", device="West Bend", menu_no=1,
                               total_min=total)
    session.add(program)
    session.flush()
    session.add(
        EquipmentCycle(
            program_id=program.id, loaf_lb=loaf_lb,
            knead1_min=knead1, rest_min=rest, knead2_min=knead2,
            total_min=total,
        )
    )
    session.flush()
    session.refresh(program)
    return program


def test_kneading_comes_from_the_manuals_own_figures(session):
    program = _program(session, knead1=12, rest=5, knead2=18)

    knead = next(
        one
        for one in _specs(program=program, inputs=_inputs(loaf_lb=2.0))
        if one.key == "knead"
    )

    assert knead.duration_min == 35  # 12 + 5 + 18
    assert "Basic" in knead.note


def test_the_loaf_size_picks_the_right_clock(session):
    program = EquipmentProgram(name="Basic", device="West Bend")
    session.add(program)
    session.flush()
    for loaf_lb, knead1 in ((2.0, 10), (3.0, 20)):
        session.add(
            EquipmentCycle(
                program_id=program.id, loaf_lb=loaf_lb,
                knead1_min=knead1, rest_min=5, knead2_min=5, total_min=200,
            )
        )
    session.flush()
    session.refresh(program)

    def knead_for(loaf_lb):
        return next(
            one
            for one in _specs(program=program, inputs=_inputs(loaf_lb=loaf_lb))
            if one.key == "knead"
        ).duration_min

    assert knead_for(2.0) == 20
    assert knead_for(3.0) == 30


def test_knead_only_leaves_the_shaping_and_baking_to_you(session):
    program = _program(session)

    keys = [
        one.key
        for one in _specs(program=program, inputs=_inputs(knead_only=True))
    ]

    assert "shape" in keys and "bake" in keys and "final_rise" in keys
    assert "program" not in keys


def test_letting_the_machine_run_the_whole_program_replaces_those_steps(session):
    program = _program(session, total=215)

    specs = _specs(program=program, inputs=_inputs(knead_only=False, loaf_lb=2.0))
    keys = [one.key for one in specs]

    assert "program" in keys
    for gone in ("shape", "final_rise", "bake", "knead"):
        assert gone not in keys
    whole = next(one for one in specs if one.key == "program")
    assert whole.duration_min == 215


def test_with_no_program_the_knead_is_an_estimate_that_says_so():
    knead = next(one for one in _specs() if one.key == "knead")

    assert knead.duration_min == bakeplan.DEFAULT_KNEAD_MIN
    assert "estimate" in knead.note


def test_a_hand_typed_knead_time_is_used():
    knead = next(
        one for one in _specs(inputs=_inputs(knead_min=40)) if one.key == "knead"
    )

    assert knead.duration_min == 40


# --- Laid out on the clock ----------------------------------------------


def test_the_step_times_match_the_figures_worked_out_by_hand(session):
    """The acceptance check: fixed inputs, fixed now, hand-computed times."""
    jar = _jar(session, fed_at=_at(1, 7), ratio=1.0, temp_c=f_to_c(78.0))
    # 1:1:1 at 78 F peaks in about 5 h, so at 12:00 it is at its peak.
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))
    assert made_jar.readiness_at(_at(1, 12)).band.is_usable

    start = _at(1, 12)
    made = bakeplan.forward(_specs(), start, jar_plan=made_jar)

    levain_rise_min = timing.predict_peak_h(2.0, 26.7) * 60
    want = [
        ("levain", 0.0, 10.0),
        ("levain_rise", 10.0, 10.0 + levain_rise_min),
        ("load", 10.0 + levain_rise_min, 15.0 + levain_rise_min),
        ("knead", 15.0 + levain_rise_min, 40.0 + levain_rise_min),
        ("shape", 40.0 + levain_rise_min, 50.0 + levain_rise_min),
        ("final_rise", 50.0 + levain_rise_min, 350.0 + levain_rise_min),
        ("bake", 350.0 + levain_rise_min, 395.0 + levain_rise_min),
        ("cool", 395.0 + levain_rise_min, 515.0 + levain_rise_min),
        ("bag", 515.0 + levain_rise_min, 517.0 + levain_rise_min),
    ]

    assert [one.key for one in made.steps] == [key for key, _, _ in want]
    for step, (key, from_min, to_min) in zip(made.steps, want):
        assert step.start == start + timedelta(minutes=from_min), key
        assert step.end == start + timedelta(minutes=to_min), key

    assert made.end == start + timedelta(minutes=517.0 + levain_rise_min)
    assert made.total_min == pytest.approx(517.0 + levain_rise_min)


def test_the_steps_run_end_to_end_with_no_gaps():
    made = bakeplan.forward(_specs(), _at(1, 12))

    for earlier, later in zip(made.steps, made.steps[1:]):
        assert earlier.end == later.start


def test_the_hands_on_total_is_the_time_actually_spent_working():
    made = bakeplan.forward(_specs(), _at(1, 12))

    # 10 build + 5 load + 10 shape + 45 bake + 2 bag
    assert made.hands_on_min == pytest.approx(72.0)


def test_a_step_can_be_found_by_key_and_by_the_clock():
    made = bakeplan.forward(_specs(), _at(1, 12))

    assert made.step("bake") is not None
    assert made.step("nonsense") is None
    assert made.at(_at(1, 12, 5)).key == "levain"
    assert made.at(_at(9, 0)) is None


# --- Waiting for the jar ------------------------------------------------


def test_a_jar_still_rising_adds_a_wait_before_anything_else(session):
    # Fed at 11:00, 1:1:1 at 78 F peaks about 16:00, so at 12:00 it is rising.
    jar = _jar(session, fed_at=_at(1, 11), ratio=1.0, temp_c=f_to_c(78.0))
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))

    made = bakeplan.forward(_specs(), _at(1, 12), jar_plan=made_jar)

    assert made.steps[0].key == "wait"
    assert made.steps[0].duration_min > 0
    assert not made.steps[0].hands_on
    # It waits until the peak window opens, not until the peak itself.
    peak_h = made_jar.last_cycle.peak_h
    opens = made_jar.last_cycle.fed_at + timedelta(hours=peak_h * timing.PEAK_FROM)
    assert made.steps[0].end == opens


def test_a_jar_at_its_peak_needs_no_wait(session):
    jar = _jar(session, fed_at=_at(1, 7), ratio=1.0, temp_c=f_to_c(78.0))
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))

    made = bakeplan.forward(_specs(), _at(1, 12), jar_plan=made_jar)

    assert made.steps[0].key == "levain"


def test_a_jar_gone_over_is_a_warning_not_a_wait(session):
    """It cannot be waited into usefulness: it needs feeding."""
    jar = _jar(session, fed_at=_at(1, 0), ratio=1.0, temp_c=f_to_c(78.0))
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))

    made = bakeplan.forward(_specs(), _at(1, 12), jar_plan=made_jar)

    assert made.steps[0].key == "levain"
    assert made.warnings
    assert "feed it" in made.warnings[0].lower()


def test_no_jar_means_no_waiting_and_no_warning():
    made = bakeplan.forward(_specs(), _at(1, 12), jar_plan=None)

    assert made.steps[0].key == "levain"
    assert made.warnings == ()


# --- Conflicts ----------------------------------------------------------


def test_a_hands_on_step_inside_a_busy_block_is_a_conflict(session):
    _sleep(session)  # 02:00-10:00 local
    intervals = _intervals(session, _at(1), _at(4))

    # 03:00 local on 2 June is 07:00 UTC: squarely inside Sleep.
    made = bakeplan.forward(_specs(), _at(2, 7), busy=intervals)

    first = made.steps[0]
    assert first.key == "levain"
    assert first.clashes
    assert first.conflict.label == "Sleep"


def test_a_hands_on_step_in_the_clear_is_not_a_conflict(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(4))

    # 14:00 local is 18:00 UTC.
    made = bakeplan.forward(_specs(), _at(1, 18), busy=intervals)

    assert not made.steps[0].clashes


def test_a_rise_ending_inside_a_busy_block_is_a_conflict(session):
    """A rise minds nobody being there until the moment it is ready."""
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(4))
    specs = (
        bakeplan.StepSpec(
            key="final_rise", name="Final rise", duration_min=120,
            must_be_home=True,
        ),
    )

    # Starts 00:00 local (04:00 UTC), ends 02:00 local — inside Sleep.
    made = bakeplan.forward(specs, _at(2, 4), busy=intervals)

    assert made.steps[0].clashes


def test_a_rise_running_through_a_block_but_ending_clear_is_fine(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(4))
    specs = (
        bakeplan.StepSpec(
            key="final_rise", name="Final rise", duration_min=60 * 10,
            must_be_home=True,
        ),
    )

    # 01:00 local to 11:00 local: runs right through Sleep, ends after it.
    made = bakeplan.forward(specs, _at(2, 5), busy=intervals)

    assert not made.steps[0].clashes


def test_a_passive_step_entirely_inside_a_block_is_not_a_conflict(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(4))
    specs = (
        bakeplan.StepSpec(key="cool", name="Cool", duration_min=60),
    )

    made = bakeplan.forward(specs, _at(2, 7), busy=intervals)

    assert not made.steps[0].clashes


def test_the_plan_gathers_its_conflicts_and_knows_if_it_works(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(5))

    bad = bakeplan.forward(_specs(), _at(2, 7), busy=intervals)
    good = bakeplan.forward(_specs(), WORKS_AT, busy=intervals)

    assert bad.conflicts and not bad.works
    assert not good.conflicts and good.works


def test_an_hour_later_than_workable_pushes_the_last_step_into_the_night(
    session,
):
    """Why the planner earns its keep: the window is genuinely that tight.

    A fifteen-hour bake day started at ten in the morning finishes at ten
    past one; started at eleven, bagging the loaf lands inside Sleep.
    """
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(5))

    made = bakeplan.forward(
        _specs(), WORKS_AT + timedelta(hours=1), busy=intervals
    )

    assert [one.key for one in made.conflicts] == ["bag"]


# --- Finding a time that works -----------------------------------------


def test_the_search_finds_the_earliest_start_with_nothing_clashing(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(6))

    found = bakeplan.find_workable(
        _specs(), from_moment=_at(2, 7), busy=intervals
    )

    assert found is not None
    assert found.plan.works
    assert found.start >= _at(2, 7)


def test_the_search_lands_on_a_quarter_hour(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(6))

    found = bakeplan.find_workable(
        _specs(), from_moment=_at(2, 7, 7), busy=intervals
    )

    assert found.start.minute % bakeplan.SEARCH_STEP_MIN == 0


def test_the_search_returns_now_when_now_already_works(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(6))

    found = bakeplan.find_workable(
        _specs(), from_moment=WORKS_AT, busy=intervals
    )

    assert found.start == WORKS_AT


def test_the_search_is_honest_when_nothing_in_range_works(session):
    # Busy every hour of every day: no start can avoid it.
    _sleep(session, start_min=0, end_min=0)
    intervals = _intervals(session, _at(1), _at(8))

    found = bakeplan.find_workable(
        _specs(), from_moment=_at(1, 12), busy=intervals, hours=24
    )

    assert found is None


def test_the_search_finds_the_earliest_not_merely_a_later_one(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(6))

    found = bakeplan.find_workable(
        _specs(), from_moment=_at(2, 7), busy=intervals
    )

    # Nothing earlier on the grid should have worked.
    step = timedelta(minutes=bakeplan.SEARCH_STEP_MIN)
    at = _at(2, 7)
    while at < found.start:
        assert not bakeplan.forward(_specs(), at, busy=intervals).works
        at += step


# --- Back-scheduling ----------------------------------------------------


def test_back_scheduling_produces_the_same_plan_as_the_forward_one(session):
    """The acceptance check, and the reason there is one layout function."""
    jar = _jar(session, fed_at=_at(1, 7), ratio=1.0, temp_c=f_to_c(78.0))
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))
    specs = _specs()

    ahead = bakeplan.forward(specs, _at(1, 12), jar_plan=made_jar)
    behind = bakeplan.backward(specs, ahead.end, jar_plan=made_jar)

    assert behind.start == ahead.start
    assert behind.end == ahead.end
    assert [one.key for one in behind.steps] == [one.key for one in ahead.steps]
    assert [one.start for one in behind.steps] == [
        one.start for one in ahead.steps
    ]


def test_back_scheduling_puts_the_bread_out_when_it_was_asked_for():
    want = _at(2, 22)  # six in the evening, local

    made = bakeplan.backward(_specs(), want)

    assert made.end == want
    assert made.start == want - timedelta(
        minutes=bakeplan.chain_minutes(_specs())
    )


def test_back_scheduling_carries_the_conflicts_too(session):
    _sleep(session)
    intervals = _intervals(session, _at(1), _at(6))

    # Work back from a time that forces the levain build into the night.
    made = bakeplan.backward(_specs(), _at(2, 16), busy=intervals)

    assert made.conflicts


def test_back_scheduling_warns_rather_than_missing_the_deadline(session):
    """A plan that quietly misses what was asked for is worse than a warning."""
    jar = _jar(session, fed_at=_at(1, 11), ratio=1.0, temp_c=f_to_c(78.0))
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))
    specs = _specs()

    # Asking for bread so soon the levain would have to be built while the
    # jar is still rising.
    made = bakeplan.backward(
        specs,
        _at(1, 12) + timedelta(minutes=bakeplan.chain_minutes(specs)),
        jar_plan=made_jar,
    )

    assert made.warnings
    assert "still be rising" in made.warnings[0]
    # And the deadline is still met, rather than a wait being slipped in.
    assert "wait" not in [one.key for one in made.steps]


def test_back_scheduling_from_a_jar_gone_over_says_to_feed_it(session):
    jar = _jar(session, fed_at=_at(1, 0), ratio=1.0, temp_c=f_to_c(78.0))
    made_jar = plan_service.jar_plan(session, jar, now=_at(1, 12), until=_at(3))

    made = bakeplan.backward(_specs(), _at(2, 12), jar_plan=made_jar)

    assert made.warnings
    assert "feed it" in made.warnings[0].lower()


# --- Putting it together ------------------------------------------------


def test_the_defaults_fill_the_form_in_sensibly(session):
    version = _recipe(session, stages=(("bake", 50),))

    inputs = bakeplan.default_inputs(session, version, now=_at(1, 12))

    assert inputs.total_flour_g == 500.0
    assert inputs.start_at == _at(1, 12)
    assert inputs.levain_ratio == bakeplan.DEFAULT_LEVAIN_RATIO
    assert inputs.levain_temp_c == pytest.approx(26.7, abs=0.1)
    assert inputs.bake_min == 50
    assert inputs.knead_only


def test_the_levain_amount_comes_from_the_recipes_levain_line(session):
    version = _recipe(
        session,
        ingredients=(
            ("whole rye flour", "flour", 100.0),
            ("rye levain", "levain", 30.0),
        ),
    )

    inputs = bakeplan.default_inputs(session, version, now=_at(1, 12))

    assert inputs.levain_g == pytest.approx(150.0)  # 30% of 500 g


def test_a_recipe_with_no_levain_line_has_no_amount_to_offer(session):
    version = _recipe(session)

    assert bakeplan.default_inputs(session, version, now=_at(1, 12)).levain_g is None


def test_build_returns_a_plan_its_chain_and_a_way_out(session):
    _sleep(session)
    version = _recipe(session)
    jar = _jar(session, fed_at=_at(1, 7), ratio=1.0, temp_c=f_to_c(78.0))

    made, specs, workable = bakeplan.build(
        session, version=version, jar=jar,
        inputs=_inputs(start_at=_at(2, 7)),  # 03:00 local, in Sleep
        now=_at(2, 7), tz=TZ,
    )

    assert made.conflicts
    assert specs
    assert workable is not None and workable.plan.works


def test_build_offers_no_alternative_when_the_plan_already_works(session):
    version = _recipe(session)

    made, _, workable = bakeplan.build(
        session, version=version, jar=None,
        inputs=_inputs(start_at=WORKS_AT), now=WORKS_AT, tz=TZ,
    )

    assert made.works
    assert workable is None


def test_build_works_backwards_when_given_a_deadline(session):
    version = _recipe(session)
    want = _at(2, 22)

    made, _, _ = bakeplan.build(
        session, version=version, jar=None,
        inputs=_inputs(start_at=None, ready_by=want), now=_at(1, 18), tz=TZ,
    )

    assert made.end == want


def test_build_carries_the_levain_figures_through(session):
    version = _recipe(session)

    made, _, _ = bakeplan.build(
        session, version=version, jar=None,
        inputs=_inputs(levain_g=150.0), now=_at(1, 12), tz=TZ,
    )

    assert made.levain_g == 150.0
    assert made.levain_peak_h == pytest.approx(timing.predict_peak_h(2.0, 26.7))


def test_a_loaf_size_label_reads_back_as_a_number():
    assert bakeplan._loaf_lb("2 lb") == 2.0
    assert bakeplan._loaf_lb("2.5 lb") == 2.5
    assert bakeplan._loaf_lb(None) is None
    assert bakeplan._loaf_lb("any size") is None
