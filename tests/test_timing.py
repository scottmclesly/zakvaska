"""The timing heuristic: when a jar peaks, and what to feed it so it peaks then.

The sanity targets are the rule-of-thumb figures for rye the model was fitted
to. They are the contract: a refactor that drifts off them has changed the
advice the app gives, which is the one thing that must not happen by accident.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services import timing
from app.services.timing import Band
from app.services.units import f_to_c


def _pct_off(got: float, want: float) -> float:
    return abs(got - want) / want * 100


# --- The fitted figures -------------------------------------------------


@pytest.mark.parametrize(
    "ratio, temp_f, want_h",
    [
        (1.0, 78.0, 5.0),
        (2.0, 78.0, 7.0),
        (5.0, 78.0, 10.0),
        (5.0, 73.0, 12.0),
    ],
)
def test_the_rules_of_thumb_for_rye(ratio, temp_f, want_h):
    got = timing.predict_peak_h(ratio, f_to_c(temp_f))

    assert _pct_off(got, want_h) <= 15, f"{got:.2f} h is not within 15% of {want_h} h"


def test_a_warm_proofing_box_peaks_rye_inside_six_hours():
    # 80 °F is Scott's proofing box, 1:1:1 his quick feed.
    assert 4.0 <= timing.predict_peak_h(1.0, f_to_c(80.0)) <= 6.0


def test_a_dilute_feed_buys_most_of_a_working_day():
    # The premise of the whole feature: a tight feed gives a short cycle and
    # a dilute one a long cycle, far enough apart to schedule around.
    quick = timing.predict_peak_h(1.0, f_to_c(80.0))
    slow = timing.predict_peak_h(5.0, f_to_c(80.0))

    assert 9.0 <= slow <= 14.0
    assert slow - quick >= 4.0, "the ratio has to be worth reaching for"


# --- Monotonicity -------------------------------------------------------


def test_more_flour_means_a_later_peak():
    peaks = [timing.predict_peak_h(r, 25.0) for r in (0.5, 1, 2, 3, 5, 8, 10)]

    assert peaks == sorted(peaks)
    assert len(set(peaks)) == len(peaks), "every step should move the answer"


def test_warmer_means_an_earlier_peak():
    peaks = [timing.predict_peak_h(3.0, t) for t in (15, 18, 21, 25, 30, 35)]

    assert peaks == sorted(peaks, reverse=True)


def test_ten_degrees_warmer_roughly_halves_the_time():
    cool = timing.predict_peak_h(2.0, 20.0)
    warm = timing.predict_peak_h(2.0, 30.0)

    assert cool / warm == pytest.approx(2.0, rel=1e-9)


def test_a_slow_jar_factor_stretches_the_prediction():
    base = timing.predict_peak_h(2.0, 25.0)

    assert timing.predict_peak_h(2.0, 25.0, 1.2) == pytest.approx(base * 1.2)
    assert timing.predict_peak_h(2.0, 25.0, 0.8) == pytest.approx(base * 0.8)


# --- Clamping -----------------------------------------------------------


def test_an_absurd_ratio_is_held_at_the_edge_of_the_range():
    assert timing.predict_peak_h(50.0, 25.0) == timing.predict_peak_h(
        timing.MAX_RATIO, 25.0
    )
    assert timing.predict_peak_h(0.01, 25.0) == timing.predict_peak_h(
        timing.MIN_RATIO, 25.0
    )


def test_a_freezer_temperature_is_held_at_the_edge_of_the_range():
    assert timing.predict_peak_h(2.0, -5.0) == timing.predict_peak_h(
        2.0, timing.MIN_TEMP_C
    )
    assert timing.predict_peak_h(2.0, 60.0) == timing.predict_peak_h(
        2.0, timing.MAX_TEMP_C
    )


def test_clamping_says_so_rather_than_extrapolating_in_silence():
    held = timing.clamp_inputs(40.0, 5.0)

    assert held.clamped
    assert held.ratio == timing.MAX_RATIO
    assert held.temp_c == timing.MIN_TEMP_C
    assert held.note is not None
    assert "1:10" in held.note and "15 °C" in held.note


def test_sensible_numbers_come_through_untouched_and_unremarked():
    held = timing.clamp_inputs(5.0, 26.7)

    assert not held.clamped
    assert held.note is None
    assert (held.ratio, held.temp_c) == (5.0, 26.7)


# --- Solving backwards --------------------------------------------------


@pytest.mark.parametrize("target_h", [4.0, 5.5, 7.0, 9.0, 10.0, 11.0])
def test_solve_and_predict_round_trip(target_h):
    """Feeding the suggested ratio lands as near the target as a half-step can.

    The suggestion is rounded to a ratio someone would actually weigh out, so
    the round trip cannot be exact — and how inexact depends on where in the
    range it lands, because a half-step of flour is worth two hours down at
    1:0.5:0.5 and ten minutes up at 1:10:10. The contract is that the answer
    is within half a step, not within a flat number of minutes.
    """
    temp_c = f_to_c(80.0)

    ratio = timing.solve_ratio(target_h, temp_c)
    got = timing.predict_peak_h(ratio, temp_c)

    step_h = abs(
        timing.predict_peak_h(ratio + timing.RATIO_STEP, temp_c)
        - timing.predict_peak_h(max(ratio - timing.RATIO_STEP, timing.MIN_RATIO), temp_c)
    )
    assert abs(got - target_h) <= max(step_h / 2, 0.1)


def test_solve_is_honest_about_what_a_temperature_can_reach():
    """At one temperature the feedable ratios only span so many hours.

    Asking for a peak outside that span is not an error — it is a question
    the answer to which is "the closest I can get", and the UI says so by
    showing the clamped ratio. Worth pinning: this is why the planner offers
    a different temperature as well as a different ratio.
    """
    temp_c = f_to_c(80.0)

    soonest = timing.predict_peak_h(timing.MIN_RATIO, temp_c)
    latest = timing.predict_peak_h(timing.MAX_RATIO, temp_c)

    assert soonest < 3.0 < 11.0 < latest
    # Beyond either end, the suggestion sits at the end rather than wandering.
    assert timing.solve_ratio(soonest / 2, temp_c) == timing.MIN_RATIO
    assert timing.solve_ratio(latest * 2, temp_c) == timing.MAX_RATIO


def test_solve_returns_a_ratio_someone_would_weigh_out():
    for target_h in (4.0, 6.3, 8.7, 11.2, 13.0):
        ratio = timing.solve_ratio(target_h, 25.0)

        assert ratio % timing.RATIO_STEP == pytest.approx(0.0, abs=1e-9)


def test_solve_clamps_rather_than_suggesting_the_impossible():
    # Two hours is sooner than rye peaks at any feedable ratio.
    assert timing.solve_ratio(2.0, 20.0) == timing.MIN_RATIO
    # Three days is longer than any ratio will stretch to.
    assert timing.solve_ratio(72.0, 30.0) == timing.MAX_RATIO


def test_solve_survives_nonsense_without_raising():
    assert timing.solve_ratio(0.0, 25.0) == timing.MIN_RATIO
    assert timing.solve_ratio(-3.0, 25.0) == timing.MIN_RATIO


def test_a_cooler_room_needs_less_flour_for_the_same_target():
    warm = timing.solve_ratio(10.0, 28.0)
    cool = timing.solve_ratio(10.0, 20.0)

    assert cool < warm


def test_a_jar_factor_feeds_back_into_the_suggestion():
    # A jar that runs 20% slow needs a tighter feed to peak at the same hour.
    assert timing.solve_ratio(10.0, 25.0, 1.2) < timing.solve_ratio(10.0, 25.0)


# --- Readiness bands ----------------------------------------------------


@pytest.mark.parametrize(
    "fraction, want",
    [
        (0.0, Band.RISING),
        (0.5, Band.RISING),
        (0.84, Band.RISING),
        (0.85, Band.PEAK),      # the window opens
        (1.0, Band.PEAK),
        (1.14, Band.PEAK),
        (1.15, Band.OK),        # and closes
        (1.49, Band.OK),
        (1.5, Band.PAST),
        (1.99, Band.PAST),
        (2.0, Band.HUNGRY),
        (5.0, Band.HUNGRY),
    ],
)
def test_band_edges(fraction, want):
    assert timing.readiness(fraction * 10.0, 10.0).band is want


def test_the_peak_window_is_the_best_time_to_feed():
    assert Band.PEAK.is_usable
    assert Band.OK.is_usable
    assert not Band.RISING.is_usable
    assert not Band.PAST.is_usable
    assert not Band.HUNGRY.is_usable


def test_the_curve_starts_flat_tops_out_at_the_peak_and_comes_back_down():
    assert timing.rise_score(0.0) == 0.0
    assert timing.rise_score(1.0) == pytest.approx(1.0)
    assert timing.rise_score(2.0) == 0.0
    assert timing.rise_score(4.0) == 0.0


def test_the_curve_is_flat_enough_at_the_top_that_the_peak_is_a_window():
    # Both edges of the peak band sit high: being an hour out barely matters.
    assert timing.rise_score(timing.PEAK_FROM) > 0.95
    assert timing.rise_score(timing.PEAK_TO) > 0.95


def test_the_curve_rises_then_falls_without_a_kink():
    scores = [timing.rise_score(f / 20) for f in range(0, 41)]
    peak_at = scores.index(max(scores))

    assert scores[:peak_at] == sorted(scores[:peak_at])
    assert scores[peak_at:] == sorted(scores[peak_at:], reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_readiness_reports_the_time_left_to_the_peak():
    ready = timing.readiness(4.0, 10.0)

    assert ready.hours_to_peak == 6.0
    assert ready.fraction == pytest.approx(0.4)

    gone = timing.readiness(14.0, 10.0)

    assert gone.hours_to_peak == -4.0


def test_a_peak_of_zero_hours_is_a_programming_error_not_a_band():
    with pytest.raises(ValueError):
        timing.readiness(1.0, 0.0)


def test_time_before_a_feed_reads_as_just_fed_rather_than_going_negative():
    # Clock skew or an edited timestamp should not invert the curve.
    assert timing.readiness(-3.0, 10.0).fraction == 0.0
    assert timing.readiness(-3.0, 10.0).band is Band.RISING


# --- The language the forms use -----------------------------------------


def test_peak_at_puts_the_prediction_on_the_clock(frozen_now):
    peak = timing.peak_at(frozen_now, 1.0, f_to_c(78.0))

    assert peak - frozen_now == timedelta(
        hours=timing.predict_peak_h(1.0, f_to_c(78.0))
    )


def test_cycle_hours_from_feeds_a_day():
    assert timing.cycle_hours(1) == 24.0
    assert timing.cycle_hours(2) == 12.0

    with pytest.raises(ValueError):
        timing.cycle_hours(0)


def test_the_ratio_of_a_logged_feeding_is_flour_over_starter():
    assert timing.feed_ratio(20.0, 100.0) == 5.0
    assert timing.feed_ratio(20.0, 20.0) == 1.0


def test_a_build_from_nothing_has_no_ratio_to_take():
    assert timing.feed_ratio(0.0, 100.0) is None
    assert timing.feed_ratio(None, 100.0) is None


def test_a_ratio_reads_back_the_way_a_baker_writes_it():
    assert timing.ratio_label(5.0) == "1:5:5"
    assert timing.ratio_label(4.5) == "1:4.5:4.5"
    assert timing.ratio_label(1.0) == "1:1:1"
