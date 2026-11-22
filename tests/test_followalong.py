"""Following a bake along: the plan written down, and read back.

The arithmetic here is all about one thing — a plan is a suggestion until it
is written down, and from then on it is a record that drifts. These check
that writing it down loses nothing, that reading it back says something true
about the clock, and that re-planning moves only what has not happened yet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.bake import BakeStageLog
from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import (
    BakeMethod,
    BakeStatus,
    BusyKind,
    IngredientRole,
    JarOrigin,
)
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import Recipe, RecipeIngredient, RecipeStage, RecipeVersion
from app.services import bakeplan, followalong
from app.services import busy as busy_service
from app.services.bakeplan import PlanInputs

TZ = "America/New_York"


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in March 2026, in UTC. 12:00 UTC is 08:00 in New York."""
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def _version(session, *, stages=(), with_levain=True, flour=500.0):
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=flour)
    session.add(version)
    session.flush()
    lines = [("whole rye flour", IngredientRole.FLOUR, 100.0)]
    if with_levain:
        lines.append(("rye levain", IngredientRole.LEVAIN, 30.0))
    for seq, (name, role, pct) in enumerate(lines):
        session.add(
            RecipeIngredient(
                version_id=version.id, seq=seq, name=name,
                role=role, baker_pct=pct,
            )
        )
    for seq, (name, minutes) in enumerate(stages):
        session.add(
            RecipeStage(
                version_id=version.id, seq=seq, name=name, duration_min=minutes
            )
        )
    session.commit()
    return version


def _jar(session, *, fed_at, ratio=1.0, name="Old Rye"):
    jar = Jar(name=name, origin=JarOrigin.HOMEMADE)
    session.add(jar)
    session.flush()
    session.add(
        Feeding(
            jar_id=jar.id, fed_at=fed_at,
            starter_g=20.0, flour_g=20.0 * ratio, water_g=20.0 * ratio,
        )
    )
    session.commit()
    return jar


def _sleep(session, label="Sleep", start=120, end=600):
    """Asleep 02:00 to 10:00 local, every night."""
    session.add(
        BusyBlock(
            label=label, kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
            start_minute=start, end_minute=end,
        )
    )
    session.commit()


def _plan(session, version, *, start, now=None, jar=None):
    made, _, _ = bakeplan.build(
        session,
        version=version,
        jar=jar,
        inputs=PlanInputs(total_flour_g=500.0, start_at=start),
        now=now or start,
        tz=__import__("zoneinfo").ZoneInfo(TZ),
    )
    return made


def _started(session, *, start=None, now=None, jar=None, stages=()):
    """A bake begun from a plan, and the version it came from."""
    version = _version(session, stages=stages)
    start = start or _at(15, 14)
    made = _plan(session, version, start=start, now=now or start, jar=jar)
    bake = followalong.start_from_plan(
        session,
        version=version,
        plan=made,
        now=now or start,
        jar_id=jar.id if jar else None,
        method=BakeMethod.OVEN,
        total_flour_g=500.0,
    )
    session.commit()
    return bake, made


# --- Writing a plan down ------------------------------------------------


class TestStartingFromAPlan:
    def test_every_step_arrives_with_the_time_it_was_planned_for(
        self, session
    ):
        bake, made = _started(session)

        assert bake.stage_logs
        for log in bake.stage_logs:
            assert log.planned_start is not None
            assert log.planned_min is not None

    def test_the_first_step_starts_when_the_plan_said(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)

        assert bake.stage_logs[0].planned_start == start

    def test_the_steps_come_out_in_the_plans_order(self, session):
        bake, made = _started(session)

        planned = [one.key for one in made.steps if one.key != "wait"]
        assert [log.step_key for log in bake.stage_logs] == planned

    def test_each_step_ends_exactly_where_the_next_one_starts(self, session):
        """No fifteen-second gaps, or "what is on now" would find nothing."""
        bake, _ = _started(session)

        logs = list(bake.stage_logs)
        for earlier, later in zip(logs, logs[1:], strict=False):
            assert earlier.planned_end == later.planned_start

    def test_planned_times_land_on_whole_minutes(self, session):
        bake, _ = _started(session)

        for log in bake.stage_logs:
            assert log.planned_start.second == 0
            assert log.planned_start.microsecond == 0

    def test_it_remembers_which_steps_need_someone_there(self, session):
        bake, _ = _started(session)

        levain = next(log for log in bake.stage_logs if log.step_key == "levain")
        cool = next(log for log in bake.stage_logs if log.step_key == "cool")
        assert levain.hands_on and levain.must_be_home
        assert not cool.hands_on and not cool.must_be_home

    def test_a_bake_starting_now_is_already_in_progress(self, session):
        now = _at(15, 14)
        bake, _ = _started(session, start=now, now=now)

        assert bake.status is BakeStatus.IN_PROGRESS
        assert bake.started_at == now

    def test_a_bake_planned_for_tomorrow_has_not_begun(self, session):
        now = _at(15, 8)
        bake, _ = _started(session, start=_at(16, 10), now=now)

        assert bake.status is BakeStatus.PLANNED
        assert bake.started_at is None
        # But its times are written down, so the alerts can still fire.
        assert bake.stage_logs[0].planned_start == _at(16, 10)

    def test_the_wait_for_the_jar_is_not_written_down_as_a_step(self, session):
        """Waiting is the gap before the bake, not a step of it."""
        now = _at(15, 12)
        # Fed an hour ago on a 1:1:1, so it is still rising at `now` and the
        # planner puts a wait in front of the levain build.
        jar = _jar(session, fed_at=now - timedelta(hours=1))
        bake, made = _started(session, start=now, now=now, jar=jar)

        assert any(one.key == "wait" for one in made.steps)
        assert all(log.step_key != "wait" for log in bake.stage_logs)
        # And the bake begins when the first real step does, not at the wait.
        assert bake.stage_logs[0].planned_start > now

    def test_the_bake_carries_the_baking_time_from_the_plan(self, session):
        bake, _ = _started(session, stages=(("bake", 55),))

        assert bake.bake_min == 55


# --- Reading it back ----------------------------------------------------


class TestWhatIsOnNow:
    def test_before_it_begins_the_first_step_is_what_is_next(self, session):
        start = _at(16, 10)
        bake, _ = _started(session, start=start, now=_at(15, 8))

        view = followalong.now_view(bake, now=_at(15, 8))

        assert view.running is None
        assert view.due_now is None
        assert view.next_up.step_key == "levain"
        assert view.current.step_key == "levain"

    def test_the_step_the_clock_is_inside_is_the_one_due_now(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)

        # Twenty minutes in: past the ten-minute levain build, into the rise.
        view = followalong.now_view(bake, now=start + timedelta(minutes=20))

        assert view.due_now.step_key == "levain_rise"

    def test_a_step_actually_ticked_started_wins_over_the_clock(self, session):
        """What really happened beats what was planned to happen."""
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        log = bake.stage_logs[0]
        log.actual_start = start + timedelta(hours=3)
        session.flush()

        view = followalong.now_view(bake, now=start + timedelta(hours=3, minutes=5))

        assert view.running is log
        assert view.current is log

    def test_the_next_thing_to_do_skips_the_waiting_about(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        # Levain built; the rise is what is on now, and it needs nothing done.
        bake.stage_logs[0].actual_start = start
        bake.stage_logs[0].actual_end = start + timedelta(minutes=10)
        session.flush()

        view = followalong.now_view(bake, now=start + timedelta(minutes=20))

        assert view.due_now.step_key == "levain_rise"
        assert view.next_hands_on.step_key == "load"

    def test_an_overrunning_step_says_how_far_behind_the_day_is(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        log = bake.stage_logs[0]
        log.actual_start = start
        session.flush()

        # The build was ten minutes; it is forty minutes later.
        view = followalong.now_view(bake, now=start + timedelta(minutes=40))

        assert view.is_behind
        assert view.behind_min == pytest.approx(30.0, abs=0.5)

    def test_a_step_whose_hour_has_gone_by_unstarted_is_behind_too(
        self, session
    ):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)

        view = followalong.now_view(bake, now=start + timedelta(minutes=25))

        # Nothing ticked at all, and the first step was due 25 minutes ago.
        assert view.is_behind
        assert view.behind_min == pytest.approx(25.0, abs=0.5)

    def test_a_bake_on_schedule_is_not_behind(self, session):
        start = _at(16, 10)
        bake, _ = _started(session, start=start, now=_at(15, 8))

        view = followalong.now_view(bake, now=_at(15, 8))

        assert not view.is_behind
        assert view.behind_min is None

    def test_when_every_step_is_done_it_says_so(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        for log in bake.stage_logs:
            log.actual_start = start
            log.actual_end = start + timedelta(minutes=5)
        session.flush()

        view = followalong.now_view(bake, now=start + timedelta(hours=20))

        assert view.is_done
        assert view.next_up is None
        assert view.current is None

    def test_it_names_the_steps_that_land_while_he_is_asleep(self, session):
        _sleep(session)
        # 20:00 local on the 15th: the long final rise ends in the small hours.
        start = _at(16, 0)
        bake, _ = _started(session, start=start)

        intervals = busy_service.busy_intervals(
            session, start - timedelta(days=1), start + timedelta(days=2),
            __import__("zoneinfo").ZoneInfo(TZ),
        )
        view = followalong.now_view(bake, now=start, busy=intervals)

        assert view.clashes
        assert all(one.label == "Sleep" for one in view.clashes)

    def test_a_step_already_done_cannot_clash(self, session):
        _sleep(session)
        start = _at(16, 0)
        bake, _ = _started(session, start=start)
        for log in bake.stage_logs:
            log.actual_start = start
            log.actual_end = start + timedelta(minutes=1)
        session.flush()

        intervals = busy_service.busy_intervals(
            session, start - timedelta(days=1), start + timedelta(days=2),
            __import__("zoneinfo").ZoneInfo(TZ),
        )
        view = followalong.now_view(bake, now=start, busy=intervals)

        assert view.clashes == ()

    def test_the_same_rule_decides_clashes_for_a_plan_and_a_bake(
        self, session
    ):
        """A bake underway must not disagree with the plan it came from."""
        _sleep(session)
        start = _at(16, 0)
        bake, made = _started(session, start=start)

        intervals = busy_service.busy_intervals(
            session, start - timedelta(days=1), start + timedelta(days=2),
            __import__("zoneinfo").ZoneInfo(TZ),
        )
        steps = followalong.planned_steps(bake, busy=intervals)

        clashing = {one.key for one in steps if one.clashes}
        from_plan = {one.key for one in made.conflicts}
        assert clashing == from_plan


class TestPlannedStepsReadBack:
    def test_they_come_back_as_the_planners_own_steps(self, session):
        bake, made = _started(session)

        steps = followalong.planned_steps(bake)

        assert [one.name for one in steps] == [
            one.name for one in made.steps if one.key != "wait"
        ]

    def test_a_bake_with_no_planned_times_has_no_plan(self, session):
        from app.services import bakes as bake_service

        version = _version(session, stages=(("bake", 45),))
        bake = bake_service.start_bake(session, version)
        session.commit()

        assert not followalong.has_plan(bake)
        assert followalong.planned_steps(bake) == ()


# --- Moving what has not happened yet -----------------------------------


class TestReplan:
    def test_it_shifts_every_step_still_to_come(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        before = [log.planned_start for log in bake.stage_logs]

        later = start + timedelta(hours=2)
        moved = followalong.replan(session, bake, now=later)

        assert moved == len(bake.stage_logs)
        assert bake.stage_logs[0].planned_start == later
        after = [log.planned_start for log in bake.stage_logs]
        assert all(new > old for new, old in zip(after, before, strict=True))

    def test_the_gaps_between_the_steps_are_unchanged(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        gaps = [log.planned_min for log in bake.stage_logs]

        followalong.replan(session, bake, now=start + timedelta(hours=5))

        logs = list(bake.stage_logs)
        assert [log.planned_min for log in logs] == gaps
        for earlier, later in zip(logs, logs[1:], strict=False):
            assert earlier.planned_end == later.planned_start

    def test_a_step_already_done_is_never_touched(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        first = bake.stage_logs[0]
        first.actual_start = start
        first.actual_end = start + timedelta(minutes=8)
        was = first.planned_start
        session.flush()

        followalong.replan(session, bake, now=start + timedelta(hours=2))

        assert first.planned_start == was
        assert first.actual_end == start + timedelta(minutes=8)

    def test_a_rise_part_way_through_pushes_the_evening_back_by_what_is_left(
        self, session
    ):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        rise = next(log for log in bake.stage_logs if log.step_key == "levain_rise")
        rise.actual_start = start + timedelta(minutes=10)
        session.flush()

        # One hour into a rise of `planned_min`: the rest of the day should
        # pick up when the rise was due to end, not now.
        now = rise.actual_start + timedelta(hours=1)
        followalong.replan(session, bake, now=now)

        after_it = next(log for log in bake.stage_logs if log.step_key == "load")
        assert after_it.planned_start == rise.actual_start + timedelta(
            minutes=rise.planned_min
        )

    def test_a_rise_that_has_already_overrun_pushes_everything_to_now(
        self, session
    ):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        rise = next(log for log in bake.stage_logs if log.step_key == "levain_rise")
        rise.actual_start = start + timedelta(minutes=10)
        session.flush()

        now = rise.actual_start + timedelta(minutes=rise.planned_min + 90)
        followalong.replan(session, bake, now=now)

        after_it = next(log for log in bake.stage_logs if log.step_key == "load")
        assert after_it.planned_start == now

    def test_a_running_step_keeps_the_start_it_really_had(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        first = bake.stage_logs[0]
        first.actual_start = start + timedelta(minutes=37)
        session.flush()

        followalong.replan(session, bake, now=start + timedelta(hours=1))

        assert first.planned_start == first.actual_start

    def test_replanning_twice_at_the_same_moment_changes_nothing(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        later = start + timedelta(hours=3)

        followalong.replan(session, bake, now=later)
        again = followalong.replan(session, bake, now=later)

        assert again == 0

    def test_it_lays_an_unplanned_bake_out_on_the_clock(self, session):
        """A bake begun the old way can still be followed along."""
        from app.services import bakes as bake_service

        version = _version(session, stages=(("sponge", 240), ("bake", 45)))
        bake = bake_service.start_bake(session, version)
        session.commit()

        followalong.replan(session, bake, now=_at(15, 14))

        assert followalong.has_plan(bake)
        assert bake.stage_logs[0].planned_start == _at(15, 14)
        assert bake.stage_logs[1].planned_start == _at(15, 18)


# --- The levain question ------------------------------------------------


class TestAskingAboutThePeak:
    def test_nothing_is_asked_until_the_rise_has_ended(self, session):
        bake, _ = _started(session)

        assert followalong.peak_to_ask(bake) is None

    def test_a_finished_levain_rise_is_asked_about(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        rise = next(log for log in bake.stage_logs if log.step_key == "levain_rise")
        rise.actual_start = start
        rise.actual_end = start + timedelta(hours=6)
        session.flush()

        assert followalong.peak_to_ask(bake) is rise

    def test_once_answered_it_is_not_asked_again(self, session):
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        rise = next(log for log in bake.stage_logs if log.step_key == "levain_rise")
        rise.actual_start = start
        rise.actual_end = start + timedelta(hours=6)
        session.flush()

        followalong.answer_peak(session, rise, at_peak=True)

        assert rise.at_peak is True
        assert followalong.peak_to_ask(bake) is None

    def test_no_is_recorded_as_firmly_as_yes(self, session):
        """"I used it anyway" is data; a null would mean nobody looked."""
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        rise = next(log for log in bake.stage_logs if log.step_key == "levain_rise")
        rise.actual_start = start
        rise.actual_end = start + timedelta(hours=3)
        session.flush()

        followalong.answer_peak(session, rise, at_peak=False)

        assert rise.at_peak is False
        assert followalong.peak_to_ask(bake) is None

    def test_an_answered_peak_measures_the_jar(self, session):
        """What Phase E will read: predicted against observed."""
        start = _at(15, 14)
        bake, _ = _started(session, start=start)
        rise = next(log for log in bake.stage_logs if log.step_key == "levain_rise")
        rise.actual_start = start
        rise.actual_end = start + timedelta(
            minutes=round(rise.planned_min * 1.2)
        )
        session.flush()
        followalong.answer_peak(session, rise, at_peak=True)

        assert rise.actual_min / rise.planned_min == pytest.approx(1.2, abs=0.01)


# --- What the alerts ask for --------------------------------------------


class TestDueMoments:
    def _log(self, **fields) -> BakeStageLog:
        base = {
            "bake_id": 0, "seq": 0, "name": "A step",
            "planned_start": _at(15, 14), "planned_min": 30,
            "hands_on": False, "must_be_home": False,
        }
        return BakeStageLog(**(base | fields))

    def test_a_hands_on_step_is_due_at_its_start(self):
        log = self._log(hands_on=True, planned_min=10)

        assert followalong.stage_due_moments(log) == (_at(15, 14),)

    def test_a_long_rise_is_due_at_its_end(self):
        log = self._log(must_be_home=True, planned_min=300)

        assert followalong.stage_due_moments(log) == (_at(15, 19),)

    def test_baking_is_worth_both_ends(self):
        """One alert to put it in, another to take it out."""
        log = self._log(hands_on=True, must_be_home=True, planned_min=45)

        assert followalong.stage_due_moments(log) == (
            _at(15, 14), _at(15, 14, 45),
        )

    def test_a_ten_minute_job_is_not_announced_twice(self):
        """You are still standing there when it ends."""
        log = self._log(hands_on=True, must_be_home=True, planned_min=10)

        assert followalong.stage_due_moments(log) == (_at(15, 14),)

    def test_a_step_with_nothing_to_do_is_due_never(self):
        log = self._log(planned_min=120)

        assert followalong.stage_due_moments(log) == ()

    def test_a_step_already_done_is_due_never(self):
        log = self._log(hands_on=True, actual_start=_at(15, 14),
                        actual_end=_at(15, 15))

        assert followalong.stage_due_moments(log) == ()

    def test_a_step_with_no_planned_time_is_due_never(self):
        log = self._log(hands_on=True, planned_start=None)

        assert followalong.stage_due_moments(log) == ()
