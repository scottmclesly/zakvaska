"""Feeding plans: the anchor, moving a feed, and a feed logged late.

The anchor is the whole mechanism, so it gets the most attention here. The
property that matters is that moving one planned feed moves every later one
by exactly the same offset — a schedule nudged an hour earlier on Tuesday
must not have drifted back by Thursday.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import JarOrigin, JarState
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.services import plan, settings_store, timing
from app.services.timing import Band
from app.services.units import f_to_c

HOUR = timedelta(hours=1)


def _jar(session, *, state=JarState.ACTIVE, **fields) -> Jar:
    jar = Jar(name="Old Rye", origin=JarOrigin.HOMEMADE, state=state, **fields)
    session.add(jar)
    session.flush()
    return jar


def _feed(session, jar, *, at, starter=20.0, flour=40.0, water=40.0, temp_c=None):
    feeding = Feeding(
        jar_id=jar.id, fed_at=at,
        starter_g=starter, flour_g=flour, water_g=water,
        ambient_temp_c=temp_c,
    )
    session.add(feeding)
    session.flush()
    return feeding


def _utc(day, hour=12, minute=0):
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


# --- Cycle length -------------------------------------------------------


def test_an_active_jar_takes_its_cycle_from_feeds_a_day(session):
    jar = _jar(session)

    assert plan.cycle_hours(session, jar) == 12.0

    settings_store.set_setting(session, "feeds_per_day", "1")
    assert plan.cycle_hours(session, jar) == 24.0


def test_a_jars_own_rhythm_beats_the_app_setting(session):
    jar = _jar(session, feeds_per_day=1)

    assert plan.cycle_hours(session, jar) == 24.0


def test_the_room_interval_no_longer_sets_the_cycle(session):
    """The answer to the question Scott settled: feeds a day owns it."""
    jar = _jar(session, feed_interval_room_h=8)

    assert plan.cycle_hours(session, jar) == 12.0


def test_a_fridge_jar_keeps_its_own_interval(session):
    jar = _jar(session, state=JarState.FRIDGE, feed_interval_fridge_h=168)

    assert plan.cycle_hours(session, jar) == 168.0


# --- Planning from the last feed ----------------------------------------


def test_a_jar_with_no_anchor_plans_one_cycle_after_its_last_feed(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(3))

    assert not made.anchored
    assert made.next_feed_at == _utc(1, 20)  # 08:00 + 12 h


def test_later_feeds_come_a_cycle_apart(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(3, 10))

    times = [one.at for one in made.planned]
    assert times[0] == _utc(1, 20)
    gaps = {later - earlier for earlier, later in zip(times, times[1:])}
    assert gaps == {timedelta(hours=12)}


def test_planned_feeds_are_numbered_from_the_next_one(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(2, 10))

    assert [one.index for one in made.planned] == list(
        range(1, len(made.planned) + 1)
    )
    assert made.planned[0].is_next


def test_a_feed_already_overdue_is_still_the_next_planned_one(session):
    """An owed feed does not stop being owed because its hour has passed.

    Rolling forward to the next future slot here would mean a jar twenty
    hours without a feed on a twelve-hour cycle never got asked about.
    """
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    # 12 h cycle, so 20:00 was due and it is now 23:00.
    made = plan.jar_plan(session, jar, now=_utc(1, 23), until=_utc(3))

    assert made.next_feed_at == _utc(1, 20)
    # And the ones after it carry on from the present, not from the backlog.
    assert [one.at for one in made.planned][1] == _utc(2, 8)


def test_a_long_neglected_jar_names_one_missed_feed_not_a_fortnight_of_them(
    session,
):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(6, 9), until=_utc(7))

    assert made.next_feed_at == _utc(1, 20)
    past = [one.at for one in made.planned if one.at < _utc(6, 9)]
    assert past == [_utc(1, 20)], "a backlog is history, not a plan"


def test_a_jar_never_fed_has_no_plan(session):
    jar = _jar(session)

    made = plan.jar_plan(session, jar, now=_utc(1), until=_utc(3))

    assert not made.has_plan
    assert made.next_feed_at is None


@pytest.mark.parametrize("state", [JarState.DORMANT, JarState.DRIED])
def test_a_sleeping_jar_has_no_plan(session, state):
    jar = _jar(session, state=state)
    _feed(session, jar, at=_utc(1, 8))

    assert not plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(3)).has_plan


# --- The anchor ---------------------------------------------------------


def test_an_anchor_puts_the_plan_on_its_own_grid(session):
    jar = _jar(session, schedule_anchor_utc=_utc(1, 13))
    _feed(session, jar, at=_utc(1, 8))  # would otherwise plan 20:00

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(2, 10))

    assert made.anchored
    assert made.next_feed_at == _utc(1, 13)


def test_an_anchor_in_the_past_still_sets_the_grid(session):
    """The anchor is a phase, not a date: it says 01:00 and 13:00, forever.

    Set days ago and fed on through, the jar should still be on those hours
    rather than having drifted onto the last feed's.
    """
    jar = _jar(session, schedule_anchor_utc=_utc(1, 13))
    _feed(session, jar, at=_utc(5, 2))

    made = plan.jar_plan(session, jar, now=_utc(5, 7), until=_utc(6))

    assert made.next_feed_at == _utc(5, 13)


def test_an_anchored_jar_left_unfed_still_names_the_feed_it_owes(session):
    jar = _jar(session, schedule_anchor_utc=_utc(1, 13))
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(5, 7), until=_utc(6))

    # Four days without a feed: the one missed at 13:00 is what is owed.
    assert made.next_feed_at == _utc(1, 13)


def test_an_anchor_in_the_future_is_not_skipped_past(session):
    jar = _jar(session, schedule_anchor_utc=_utc(4, 13))
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(5))

    assert made.next_feed_at == _utc(4, 13)


def test_a_feed_exactly_on_the_anchor_counts_as_now_not_next(session):
    jar = _jar(session, schedule_anchor_utc=_utc(1, 13))
    _feed(session, jar, at=_utc(1, 8))

    made = plan.jar_plan(session, jar, now=_utc(1, 13), until=_utc(2))

    assert made.next_feed_at == _utc(1, 13)


# --- Moving a feed ------------------------------------------------------


def test_moving_the_next_feed_moves_every_later_one_by_the_same_offset(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))
    now, until = _utc(1, 10), _utc(4)

    before = [one.at for one in plan.jar_plan(session, jar, now=now, until=until).planned]
    plan.shift_next_feed(session, jar, by=-2 * HOUR, now=now, until=until)
    after = [one.at for one in plan.jar_plan(session, jar, now=now, until=until).planned]

    assert len(before) == len(after)
    offsets = {later - earlier for earlier, later in zip(before, after)}
    assert offsets == {-2 * HOUR}, "the whole chain has to move together"


def test_nudging_twice_adds_up_rather_than_drifting(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))
    now, until = _utc(1, 10), _utc(4)

    first = plan.jar_plan(session, jar, now=now, until=until).next_feed_at
    for _ in range(4):
        plan.shift_next_feed(session, jar, by=-timedelta(minutes=30), now=now, until=until)

    assert plan.jar_plan(session, jar, now=now, until=until).next_feed_at == (
        first - timedelta(hours=2)
    )


def test_a_feed_can_be_moved_to_an_exact_time(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    plan.move_next_feed(session, jar, to=_utc(1, 22, 15), now=_utc(1, 10))

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(2, 10))
    assert made.next_feed_at == _utc(1, 22, 15)
    assert made.anchored


def test_clearing_the_anchor_goes_back_to_following_the_last_feed(session):
    jar = _jar(session, schedule_anchor_utc=_utc(1, 13))
    _feed(session, jar, at=_utc(1, 8))

    plan.clear_anchor(session, jar)

    made = plan.jar_plan(session, jar, now=_utc(1, 10), until=_utc(2))
    assert not made.anchored
    assert made.next_feed_at == _utc(1, 20)


def test_moving_a_feed_on_a_jar_with_no_plan_does_nothing(session):
    jar = _jar(session)

    moved = plan.shift_next_feed(
        session, jar, by=HOUR, now=_utc(1), until=_utc(3)
    )

    assert moved is None
    assert jar.schedule_anchor_utc is None


# --- A feed logged late -------------------------------------------------


def test_a_feed_on_time_is_not_flagged(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    late = plan.feed_against_plan(session, jar, fed_at=_utc(1, 20), now=_utc(1, 20))

    assert late is not None
    assert not late.is_off_plan
    assert late.planned_at == _utc(1, 20)


def test_a_feed_three_hours_late_is_flagged_as_late(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    late = plan.feed_against_plan(session, jar, fed_at=_utc(1, 23), now=_utc(1, 23))

    assert late.is_late
    assert late.hours_late == pytest.approx(3.0)


def test_a_feed_three_hours_early_is_flagged_as_early(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    early = plan.feed_against_plan(session, jar, fed_at=_utc(1, 17), now=_utc(1, 17))

    assert early.is_early
    assert early.planned_at == _utc(1, 20)


def test_a_feed_inside_the_grace_window_is_on_time(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    for minutes in (-45, 0, 45):
        late = plan.feed_against_plan(
            session, jar, fed_at=_utc(1, 20) + timedelta(minutes=minutes),
            now=_utc(1, 20),
        )
        assert not late.is_off_plan


def test_a_jars_first_ever_feed_has_no_plan_to_be_off(session):
    jar = _jar(session)

    assert plan.feed_against_plan(
        session, jar, fed_at=_utc(1, 8), now=_utc(1, 8)
    ) is None


def test_keeping_usual_times_leaves_the_schedule_where_it_was(session):
    """The default after a late feed: the next feed stays on the old grid."""
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))
    late = plan.feed_against_plan(session, jar, fed_at=_utc(1, 23), now=_utc(1, 23))

    plan.keep_usual_times(session, jar, late=late)
    _feed(session, jar, at=_utc(1, 23))

    made = plan.jar_plan(session, jar, now=_utc(1, 23), until=_utc(3))
    # 20:00 was the planned feed, so the next stays 08:00, not 11:00.
    assert made.next_feed_at == _utc(2, 8)


def test_shifting_the_schedule_moves_the_grid_to_the_real_feed(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))
    late = plan.feed_against_plan(session, jar, fed_at=_utc(1, 23), now=_utc(1, 23))

    plan.shift_schedule(session, jar, late=late)
    _feed(session, jar, at=_utc(1, 23))

    made = plan.jar_plan(session, jar, now=_utc(1, 23), until=_utc(3))
    assert made.next_feed_at == _utc(2, 11)  # 23:00 + 12 h


def test_keeping_usual_times_survives_a_second_late_feed(session):
    """Two late feeds in a row must not walk the schedule along with them."""
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    for fed_at in (_utc(1, 23), _utc(2, 10)):
        late = plan.feed_against_plan(session, jar, fed_at=fed_at, now=fed_at)
        plan.keep_usual_times(session, jar, late=late)
        _feed(session, jar, at=fed_at)

    made = plan.jar_plan(session, jar, now=_utc(2, 10), until=_utc(4))
    # Still on the 08:00/20:00 grid the jar started on.
    assert made.next_feed_at.hour in (8, 20)


# --- The rise a feed set off --------------------------------------------


def test_a_logged_feeding_becomes_a_cycle_with_a_predicted_peak(session):
    jar = _jar(session)
    feeding = _feed(session, jar, at=_utc(1, 8), starter=20, flour=100, water=100,
                    temp_c=f_to_c(78.0))

    cycle = plan.cycle_for_feeding(session, feeding, jar)

    assert cycle.ratio == 5.0
    assert cycle.ratio_label == "1:5:5"
    assert not cycle.temp_assumed
    assert cycle.peak_h == pytest.approx(
        timing.predict_peak_h(5.0, f_to_c(78.0)), rel=1e-9
    )
    assert cycle.peak_at == cycle.fed_at + timedelta(hours=cycle.peak_h)


def test_a_feeding_with_no_temperature_uses_the_setting_and_says_so(session):
    jar = _jar(session)
    feeding = _feed(session, jar, at=_utc(1, 8))

    cycle = plan.cycle_for_feeding(session, feeding, jar)

    assert cycle.temp_assumed
    assert cycle.temp_c == pytest.approx(26.7, abs=0.1)


def test_a_build_with_no_starter_still_gets_drawn(session):
    """No ratio to take, but a curve is better than a gap on the ribbon."""
    jar = _jar(session)
    feeding = _feed(session, jar, at=_utc(1, 8), starter=0.0)

    cycle = plan.cycle_for_feeding(session, feeding, jar)

    assert cycle.ratio is None
    assert cycle.ratio_label is None
    assert cycle.peak_h > 0


def test_the_plan_reports_which_band_the_jar_is_in_now(session):
    jar = _jar(session)
    # 1:1:1 at 78 F peaks in about 5 h.
    _feed(session, jar, at=_utc(1, 8), starter=20, flour=20, water=20,
          temp_c=f_to_c(78.0))

    made = plan.jar_plan(session, jar, now=_utc(1, 13), until=_utc(2))

    assert made.readiness_at(_utc(1, 13)).band is Band.PEAK
    assert plan.band_of(made, _utc(1, 9)) is Band.RISING
    assert plan.band_of(made, _utc(1, 23)) is Band.HUNGRY


def test_a_jar_never_fed_has_no_band(session):
    jar = _jar(session)

    made = plan.jar_plan(session, jar, now=_utc(1), until=_utc(2))

    assert made.readiness_at(_utc(1)) is None
    assert plan.band_of(made, _utc(1)) is None


def test_recent_cycles_keeps_the_feed_whose_curve_is_still_running(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 20))   # before the window, curve overlaps
    _feed(session, jar, at=_utc(2, 8))

    cycles = plan.recent_cycles(session, jar, since=_utc(2, 0), until=_utc(3))

    assert [one.fed_at for one in cycles] == [_utc(1, 20), _utc(2, 8)]


def test_recent_cycles_drops_feeds_whose_curves_are_long_over(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))
    _feed(session, jar, at=_utc(8, 8))

    cycles = plan.recent_cycles(session, jar, since=_utc(8, 0), until=_utc(9))

    assert [one.fed_at for one in cycles] == [_utc(8, 8)]


def test_recent_cycles_drops_a_cycle_the_next_feed_cut_off(session):
    """Its curve looks like it overlaps the window, but it ended at 20:00."""
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 14))
    _feed(session, jar, at=_utc(1, 20))

    cycles = plan.recent_cycles(session, jar, since=_utc(2, 0), until=_utc(3))

    assert [one.fed_at for one in cycles] == [_utc(1, 20)]


def test_recent_cycles_keeps_one_feed_rather_than_drawing_nothing(session):
    """An old jar still shows where it last got to, not a blank ribbon."""
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8))

    cycles = plan.recent_cycles(session, jar, since=_utc(20), until=_utc(21))

    assert len(cycles) == 1


# --- Advice -------------------------------------------------------------


def test_the_plan_suggests_a_ratio_that_lands_the_peak_on_the_next_feed(session):
    jar = _jar(session)
    _feed(session, jar, at=_utc(1, 8), temp_c=f_to_c(80.0))
    now = _utc(1, 10)

    made = plan.jar_plan(session, jar, now=now, until=_utc(3))
    ratio = made.suggested_ratio(now)

    assert ratio is not None
    hours = (made.next_feed_at - now).total_seconds() / 3600
    assert timing.predict_peak_h(ratio, f_to_c(80.0)) == pytest.approx(hours, abs=1.0)


def test_there_is_no_ratio_advice_without_a_plan(session):
    jar = _jar(session)

    made = plan.jar_plan(session, jar, now=_utc(1), until=_utc(3))

    assert made.suggested_ratio(_utc(1)) is None


def test_ratio_advice_says_what_to_feed_and_when_it_peaks(session):
    advice = plan.ratio_advice(
        from_moment=_utc(1, 10), target_at=_utc(1, 20), temp_c=f_to_c(80.0)
    )

    assert advice is not None
    assert advice.hours == pytest.approx(10.0)
    assert advice.label.startswith("1:")
    assert advice.clamped_note is None


def test_ratio_advice_owns_up_when_no_feedable_ratio_reaches(session):
    """Asking for a peak two days out: say so rather than imply it works."""
    advice = plan.ratio_advice(
        from_moment=_utc(1, 10), target_at=_utc(3, 10), temp_c=f_to_c(80.0)
    )

    assert advice is not None
    assert advice.ratio == timing.MAX_RATIO
    assert advice.clamped_note is not None


def test_there_is_no_advice_for_a_time_already_gone(session):
    assert plan.ratio_advice(
        from_moment=_utc(1, 20), target_at=_utc(1, 10), temp_c=25.0
    ) is None
