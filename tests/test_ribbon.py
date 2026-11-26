"""Ribbon geometry: where everything lands, without parsing an SVG.

Same bargain as test_charts.py — the service works out coordinates, so the
awkward cases are testable from a list of numbers: a curve that starts before
the window, a feed at the very edge, a jar with nothing logged at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services import ribbon, timing
from app.services.timing import Band

TZ = ZoneInfo("America/New_York")


def _at(day, hour=0, minute=0):
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def _series(feeds=(), planned=(), observations=(), name="Old Rye", **kw):
    return ribbon.RibbonSeries(
        name=name, jar_id=1, feeds=feeds, planned=planned,
        observations=observations, **kw,
    )


def _draw(series, *, start=None, end=None, now=None, busy=()):
    start = start or _at(1, 0)
    end = end or _at(3, 0)
    return ribbon.ribbon(
        series, start=start, end=end, now=now or _at(1, 12),
        tz=TZ, busy=busy,
    )


# --- The frame ----------------------------------------------------------


def test_no_jars_draws_nothing():
    assert _draw([]) is None


def test_a_window_with_no_width_draws_nothing():
    assert _draw([_series()], start=_at(1), end=_at(1)) is None


def test_one_row_per_jar():
    drawn = _draw([_series(name="Old Rye"), _series(name="Soviet")])

    assert [row.name for row in drawn.rows] == ["Old Rye", "Soviet"]
    assert [row.slot for row in drawn.rows] == [1, 2]


def test_rows_do_not_overlap_and_stack_downwards():
    drawn = _draw([_series(name="A"), _series(name="B"), _series(name="C")])

    tops = [row.top for row in drawn.rows]
    assert tops == sorted(tops)
    for earlier, later in zip(drawn.rows, drawn.rows[1:]):
        assert earlier.bottom <= later.top


def test_the_viewbox_grows_with_the_number_of_rows():
    one = _draw([_series()])
    three = _draw([_series(name="A"), _series(name="B"), _series(name="C")])

    def height(drawn):
        return float(drawn.viewbox.split()[-1])

    assert height(three) > height(one)
    assert one.viewbox.startswith("0 0 360")


def test_a_jar_with_nothing_logged_still_gets_a_row():
    """An empty row says "never fed"; a missing row says nothing at all."""
    drawn = _draw([_series(note="Never fed")])

    assert len(drawn.rows) == 1
    assert drawn.rows[0].note == "Never fed"
    assert drawn.rows[0].curves == ()


def test_now_sits_where_it_belongs_along_the_axis():
    drawn = _draw([_series()], start=_at(1), end=_at(3), now=_at(2))

    plot = drawn.plot
    assert drawn.now_x == pytest.approx(plot.x + plot.w / 2, abs=0.01)


# --- The time axis ------------------------------------------------------


def test_ticks_land_on_round_local_hours():
    drawn = _draw([_series()], start=_at(1), end=_at(3))

    for tick in drawn.ticks:
        local = tick.at.astimezone(TZ)
        assert local.minute == 0


def test_ticks_stay_inside_the_window():
    drawn = _draw([_series()], start=_at(1, 5), end=_at(2, 7))

    for tick in drawn.ticks:
        assert _at(1, 5) <= tick.at <= _at(2, 7)


def test_there_are_enough_ticks_to_read_but_not_so_many_they_collide():
    for span in (24, 48, 72):
        drawn = _draw(
            [_series()], start=_at(1), end=_at(1) + timedelta(hours=span)
        )
        assert 2 <= len(drawn.ticks) <= ribbon.MAX_TICKS + 1, span


def test_local_midnight_is_marked_and_named():
    # Midnight local on 2 June is 04:00 UTC.
    drawn = _draw([_series()], start=_at(1, 12), end=_at(3, 12))

    days = [tick for tick in drawn.ticks if tick.is_day_start]
    assert days, "a two-day ribbon should name its days"
    for tick in days:
        assert tick.at.astimezone(TZ).hour == 0
        assert tick.day_label
        # Not %-d, which is not portable; charts.py spells it out the same way.
        assert "%" not in tick.day_label


def test_day_labels_survive_the_clocks_going_forward():
    """Midnight stays midnight rather than drifting to 23:00."""
    drawn = ribbon.ribbon(
        [_series()],
        start=datetime(2026, 3, 7, 12, tzinfo=UTC),
        end=datetime(2026, 3, 10, 12, tzinfo=UTC),
        now=datetime(2026, 3, 8, 12, tzinfo=UTC),
        tz=TZ,
    )

    for tick in drawn.ticks:
        if tick.is_day_start:
            assert tick.at.astimezone(TZ).hour == 0


def test_ticks_are_not_doubled_on_the_hour_that_does_not_exist():
    """2026-03-08 02:00 local never happens; it must not make two ticks."""
    drawn = ribbon.ribbon(
        [_series()],
        start=datetime(2026, 3, 8, 4, tzinfo=UTC),
        end=datetime(2026, 3, 8, 16, tzinfo=UTC),
        now=datetime(2026, 3, 8, 8, tzinfo=UTC),
        tz=TZ,
    )

    xs = [round(tick.x, 4) for tick in drawn.ticks]
    assert len(xs) == len(set(xs))


# --- The rise curve -----------------------------------------------------


def test_a_feed_draws_a_curve_cut_into_readiness_bands():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0, ratio_label="1:1:1")
    drawn = _draw([_series(feeds=(feed,))])

    curve = drawn.rows[0].curves[0]
    bands = [segment.band for segment in curve.segments]
    # A full cycle passes through all five, in order.
    assert bands == [Band.RISING, Band.PEAK, Band.OK, Band.PAST, Band.HUNGRY]


def test_the_segments_join_up_rather_than_leaving_gaps():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    curve = _draw([_series(feeds=(feed,))]).rows[0].curves[0]

    for earlier, later in zip(curve.segments, curve.segments[1:]):
        assert earlier.points[-1] == later.points[0]


def test_the_curve_peaks_at_the_predicted_peak():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    row = _draw([_series(feeds=(feed,))]).rows[0]
    curve = row.curves[0]

    points = [point for one in curve.segments for point in one.points]
    # SVG counts down, so the peak is the smallest y.
    highest = min(points, key=lambda point: point[1])
    assert highest[0] == pytest.approx(curve.peak_x, abs=2.0)
    assert highest[1] == pytest.approx(row.top, abs=1.0)


def test_the_curve_starts_and_ends_on_the_baseline():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    row = _draw([_series(feeds=(feed,))]).rows[0]
    curve = row.curves[0]
    points = [point for one in curve.segments for point in one.points]

    assert points[0][1] == pytest.approx(row.bottom, abs=0.01)
    assert points[-1][1] == pytest.approx(row.bottom, abs=0.5)


def test_the_curve_never_leaves_its_own_row():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    row = _draw([_series(feeds=(feed,))]).rows[0]

    for segment in row.curves[0].segments:
        for _, y in segment.points:
            assert row.top - 0.01 <= y <= row.bottom + 0.01


def test_a_curve_that_began_before_the_window_is_clipped_not_dropped():
    """The rise now underway is the most interesting one on the ribbon."""
    feed = ribbon.FeedMark(at=_at(1, 0) - timedelta(hours=3), peak_h=5.0)
    drawn = _draw([_series(feeds=(feed,))], start=_at(1, 0), end=_at(2, 0))

    curve = drawn.rows[0].curves[0]
    assert curve.has_shape
    points = [point for one in curve.segments for point in one.points]
    assert min(x for x, _ in points) >= drawn.plot.x - 0.01


def test_a_curve_entirely_past_the_window_is_not_drawn():
    feed = ribbon.FeedMark(at=_at(5, 0), peak_h=5.0)
    drawn = _draw([_series(feeds=(feed,))], start=_at(1), end=_at(2))

    assert not drawn.rows[0].curves[0].has_shape


def test_a_feed_with_no_peak_to_predict_draws_no_curve():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=0.0)
    drawn = _draw([_series(feeds=(feed,))])

    assert drawn.rows[0].curves[0].segments == ()
    assert not drawn.rows[0].curves[0].has_shape


def test_a_peak_outside_the_window_gets_no_marker():
    feed = ribbon.FeedMark(at=_at(1, 20), peak_h=10.0)
    drawn = _draw([_series(feeds=(feed,))], start=_at(1), end=_at(1, 23))

    assert drawn.rows[0].curves[0].peak_x is None


def test_a_cycle_stops_where_the_next_feed_begins():
    """Feeding discards what was rising, so the old curve ends there."""
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0, ends_at=_at(1, 10))
    drawn = _draw([_series(feeds=(feed,))])

    curve = drawn.rows[0].curves[0]
    points = [point for one in curve.segments for point in one.points]
    cut = drawn.plot.x + (10 / 48) * drawn.plot.w   # 10:00 in a 48 h window

    assert curve.has_shape
    assert max(x for x, _ in points) == pytest.approx(cut, abs=0.5)


def test_two_feeds_in_the_window_do_not_draw_over_each_other():
    """The doubled-up humps: the first curve used to run on past the second."""
    first = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0, ends_at=_at(1, 10))
    second = ribbon.FeedMark(at=_at(1, 10), peak_h=5.0)
    row = _draw([_series(feeds=(first, second))]).rows[0]

    earlier = [point for one in row.curves[0].segments for point in one.points]
    later = [point for one in row.curves[1].segments for point in one.points]

    assert max(x for x, _ in earlier) <= min(x for x, _ in later) + 0.01


def test_a_cycle_cut_short_keeps_the_bands_it_got_to():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0, ends_at=_at(1, 9))
    curve = _draw([_series(feeds=(feed,))]).rows[0].curves[0]

    # Three hours into a five-hour rise: on its way up, and no further.
    assert [segment.band for segment in curve.segments] == [Band.RISING]


def test_a_peak_the_jar_never_reached_is_not_claimed():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0, ends_at=_at(1, 9))
    curve = _draw([_series(feeds=(feed,))]).rows[0].curves[0]

    assert curve.peak_pre_empted


def test_a_peak_reached_before_the_next_feed_still_counts():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0, ends_at=_at(1, 14))
    curve = _draw([_series(feeds=(feed,))]).rows[0].curves[0]

    assert not curve.peak_pre_empted
    assert curve.peak_x is not None


def test_the_latest_cycle_runs_its_full_course():
    """Nothing has ended it yet, so it is drawn all the way back down."""
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    row = _draw([_series(feeds=(feed,))]).rows[0]
    points = [point for one in row.curves[0].segments for point in one.points]

    assert points[-1][1] == pytest.approx(row.bottom, abs=0.5)


def test_the_fill_closes_back_along_the_baseline():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    row = _draw([_series(feeds=(feed,))]).rows[0]

    area = row.curves[0].area
    assert area
    first, last = area.split()[0], area.split()[-1]
    assert first.endswith(f"{row.bottom:.2f}")
    assert last.endswith(f"{row.bottom:.2f}")


def test_the_polyline_is_ready_to_drop_into_the_template():
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=5.0)
    segment = _draw([_series(feeds=(feed,))]).rows[0].curves[0].segments[0]

    for pair in segment.polyline.split():
        x, _, y = pair.partition(",")
        float(x), float(y)


# --- Planned feeds ------------------------------------------------------


def test_planned_feeds_are_placed_along_the_axis():
    planned = (
        ribbon.PlannedMark(at=_at(1, 18), index=1),
        ribbon.PlannedMark(at=_at(2, 6), index=2),
    )
    row = _draw([_series(planned=planned)]).rows[0]

    assert len(row.planned) == 2
    assert row.planned[0].x < row.planned[1].x


def test_a_planned_feed_outside_the_window_is_left_off():
    planned = (ribbon.PlannedMark(at=_at(9, 18), index=1),)

    assert _draw([_series(planned=planned)]).rows[0].planned == ()


def test_a_planned_feed_in_a_busy_block_is_flagged_with_its_way_out():
    planned = (
        ribbon.PlannedMark(
            at=_at(1, 7), index=1, busy_label="Sleep",
            move_to=_at(1, 14), move_ratio_label="1:5:5",
        ),
    )
    row = _draw([_series(planned=planned)]).rows[0]

    assert row.planned[0].clashes
    assert row.clashes == row.planned
    assert row.planned[0].mark.move_ratio_label == "1:5:5"


def test_a_planned_feed_in_the_clear_is_not_flagged():
    planned = (ribbon.PlannedMark(at=_at(1, 18), index=1),)
    row = _draw([_series(planned=planned)]).rows[0]

    assert not row.planned[0].clashes
    assert row.clashes == ()


def test_the_ribbon_gathers_every_clash_across_every_jar():
    clash = ribbon.PlannedMark(at=_at(1, 7), index=1, busy_label="Sleep")
    clear = ribbon.PlannedMark(at=_at(1, 18), index=1)
    drawn = _draw([
        _series(planned=(clash,), name="A"),
        _series(planned=(clear,), name="B"),
    ])

    assert len(drawn.clashes) == 1


# --- Observations -------------------------------------------------------


def test_a_measured_rise_sits_against_the_prediction():
    marks = (ribbon.ObservationMark(at=_at(1, 10), rise_pct=100.0),)
    row = _draw([_series(observations=marks)]).rows[0]

    # A doubling reads as the top of the band.
    assert row.observations[0].y == pytest.approx(row.top, abs=0.01)


def test_a_jar_that_sank_is_drawn_on_the_floor_not_off_the_row():
    marks = (ribbon.ObservationMark(at=_at(1, 10), rise_pct=-40.0),)
    row = _draw([_series(observations=marks)]).rows[0]

    assert row.observations[0].y == pytest.approx(row.bottom, abs=0.01)


def test_a_jar_that_beat_the_model_is_drawn_above_its_curve_but_on_the_card():
    marks = (ribbon.ObservationMark(at=_at(1, 10), rise_pct=400.0),)
    row = _draw([_series(observations=marks)]).rows[0]

    assert row.observations[0].y < row.top
    assert row.observations[0].y > row.top - ribbon.ROW_CURVE_H


def test_an_observation_outside_the_window_is_left_off():
    marks = (ribbon.ObservationMark(at=_at(9, 10), rise_pct=80.0),)

    assert _draw([_series(observations=marks)]).rows[0].observations == ()


# --- Busy blocks --------------------------------------------------------


def test_busy_blocks_are_shaded_across_every_row():
    busy = (ribbon.BusyMark(start=_at(1, 6), end=_at(1, 14), label="Sleep"),)
    drawn = _draw([_series(name="A"), _series(name="B")], busy=busy)

    assert len(drawn.busy) == 1
    shade = drawn.busy[0]
    assert shade.width > 0
    assert shade.label == "Sleep"
    # One band down the whole plot, not one per row.
    assert drawn.plot.h >= ribbon.ROW_H * 2


def test_a_busy_block_is_clipped_to_the_window():
    busy = (
        ribbon.BusyMark(
            start=_at(1) - timedelta(hours=10),
            end=_at(1) + timedelta(hours=4),
            label="Sleep",
        ),
    )
    drawn = _draw([_series()], start=_at(1), end=_at(2), busy=busy)

    assert drawn.busy[0].x1 == pytest.approx(drawn.plot.x, abs=0.01)
    assert drawn.busy[0].x2 > drawn.plot.x


def test_a_busy_block_outside_the_window_is_not_shaded():
    busy = (ribbon.BusyMark(start=_at(9), end=_at(9, 8), label="Sleep"),)

    assert _draw([_series()], start=_at(1), end=_at(2), busy=busy).busy == ()


# --- The window ---------------------------------------------------------


@pytest.mark.parametrize("span", [24, 48, 72])
def test_the_window_is_the_asked_for_span_weighted_to_the_future(span):
    now = _at(2, 12)
    start, end = ribbon.window(now, span)

    assert (end - start) == timedelta(hours=span)
    assert start < now < end
    assert (end - now) > (now - start), "the ribbon is for what comes next"


def test_the_window_still_shows_the_rise_already_underway():
    now = _at(2, 12)
    start, _ = ribbon.window(now, 48)

    assert now - start >= timedelta(hours=4)


def test_a_short_window_does_not_spend_all_of_itself_on_the_past():
    now = _at(2, 12)
    start, end = ribbon.window(now, 6)

    assert now - start <= timedelta(hours=2)
    assert end > now


# --- Bands line up with the model ---------------------------------------


def test_the_bands_drawn_are_the_bands_the_model_defines():
    """The ribbon must not keep its own copy of where the peak window is."""
    feed = ribbon.FeedMark(at=_at(1, 6), peak_h=10.0)
    curve = _draw(
        [_series(feeds=(feed,))], start=_at(1), end=_at(2, 12)
    ).rows[0].curves[0]

    peak_segment = next(
        one for one in curve.segments if one.band is Band.PEAK
    )
    span_x = peak_segment.points[-1][0] - peak_segment.points[0][0]
    whole = _draw([_series(feeds=(feed,))], start=_at(1), end=_at(2, 12)).plot.w
    # The peak band is 0.85-1.15 of a 10 h peak, so 3 h of a 30 h window.
    assert span_x / whole == pytest.approx(3.0 / 30.0, abs=0.02)
    assert timing.PEAK_TO - timing.PEAK_FROM == pytest.approx(0.3)


# --- Head to head --------------------------------------------------------


def _two_series():
    from app.services.ribbon import FeedMark, RibbonSeries

    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    return now, [
        RibbonSeries(name="Homemade", jar_id=1,
                     feeds=(FeedMark(at=now - timedelta(hours=2), peak_h=6.0),)),
        RibbonSeries(name="Control", jar_id=2, is_control=True,
                     feeds=(FeedMark(at=now - timedelta(hours=2), peak_h=8.0),)),
    ]


def test_head_to_head_puts_every_jar_on_one_baseline():
    """Stacked rows cannot show which jar is ahead; one baseline can."""
    from app.services import ribbon as ribbon_service

    now, series = _two_series()
    drawn = ribbon_service.head_to_head(
        series, start=now - timedelta(hours=6), end=now + timedelta(hours=18),
        now=now, tz=UTC,
    )

    first, second = drawn.rows
    assert first.bottom == second.bottom and first.top == second.top
    # The quicker jar's peak is to the left of the slower one's.
    assert first.curves[0].peak_x < second.curves[0].peak_x
    assert tuple(one.width for one in drawn.sizes) == ribbon_service.SIZES


def test_head_to_head_needs_two_jars():
    from app.services import ribbon as ribbon_service

    now, series = _two_series()

    assert ribbon_service.head_to_head(
        series[:1], start=now, end=now + timedelta(hours=24), now=now, tz=UTC
    ) is None
