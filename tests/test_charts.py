"""The arithmetic behind the plots.

Charts are the easiest thing in the app to get quietly wrong: a bar can be
drawn in the wrong proportion and still look like a bar. These check the
numbers, so the templates only have to draw them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import charts

NY = ZoneInfo("America/New_York")
START = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def samples(*pairs: tuple[float, float]) -> list[charts.Sample]:
    """(hours from START, value) → samples."""
    return [
        charts.Sample(at=START + timedelta(hours=hours), value=value)
        for hours, value in pairs
    ]


def one(name: str = "Homemade rye", *pairs, control: bool = False):
    return charts.SeriesInput(
        name=name, samples=samples(*pairs), is_control=control
    )


class TestWhetherThereIsAChartAtAll:
    def test_nothing_logged_draws_nothing(self):
        assert charts.rise_chart([], tz=NY) is None

    def test_a_series_with_no_samples_draws_nothing(self):
        assert charts.rise_chart([one("Rye")], tz=NY) is None

    def test_a_single_reading_is_not_a_trend(self):
        chart = charts.rise_chart([one("Rye", (0, 80))], tz=NY)

        assert chart is None

    def test_two_readings_across_two_jars_are_enough(self):
        chart = charts.rise_chart(
            [one("Rye", (0, 80)), one("Soviet", (0, 90))], tz=NY
        )

        assert chart is not None
        assert chart.sample_count == 2


class TestTheVerticalAxis:
    def test_it_always_shows_zero_and_doubled(self):
        chart = charts.rise_chart([one("Rye", (0, 12), (6, 20))], tz=NY)

        assert chart.y_min == 0
        assert chart.y_max == 100
        assert [band.value for band in chart.gridlines] == [0, 25, 50, 75, 100]

    def test_exactly_one_line_is_marked_as_doubled(self):
        chart = charts.rise_chart([one("Rye", (0, 12), (6, 20))], tz=NY)

        doubled = [band for band in chart.gridlines if band.is_doubled]
        assert [band.value for band in doubled] == [100]

    def test_it_stretches_to_a_round_number_above_the_best_rise(self):
        chart = charts.rise_chart([one("Rye", (0, 40), (6, 160))], tz=NY)

        assert chart.y_max == 200
        assert chart.gridlines[-1].value == 200

    def test_a_starter_that_sank_gets_room_below_zero(self):
        chart = charts.rise_chart([one("Rye", (0, 60), (6, -30))], tz=NY)

        assert chart.y_min == -50
        assert any(band.is_baseline for band in chart.gridlines)

    def test_it_never_draws_more_than_a_handful_of_rules(self):
        chart = charts.rise_chart([one("Rye", (0, 0), (6, 920))], tz=NY)

        assert len(chart.gridlines) <= 7

    def test_a_higher_rise_sits_higher_up_the_picture(self):
        chart = charts.rise_chart([one("Rye", (0, 20), (6, 90))], tz=NY)
        low, high = chart.lines[0].points

        # SVG counts downwards, so the bigger rise has the smaller y.
        assert high.y < low.y
        assert chart.plot.y <= high.y <= chart.plot.bottom


class TestTheTimeAxis:
    def test_the_first_reading_is_at_the_left_and_the_last_at_the_right(self):
        chart = charts.rise_chart([one("Rye", (0, 10), (48, 90))], tz=NY)
        first, last = chart.lines[0].points

        assert first.x == chart.plot.x
        assert last.x == chart.plot.right

    def test_readings_arrive_in_order_however_they_were_handed_over(self):
        jumbled = charts.SeriesInput(
            name="Rye", samples=samples((48, 90), (0, 10), (24, 50))
        )
        chart = charts.rise_chart([jumbled], tz=NY)

        values = [point.value for point in chart.lines[0].points]
        assert values == [10, 50, 90]

    def test_ticks_land_on_the_local_clock(self):
        chart = charts.rise_chart([one("Rye", (0, 10), (240, 90))], tz=NY)

        assert chart.ticks
        for tick in chart.ticks:
            local = tick.at.astimezone(NY)
            assert (local.hour, local.minute) == (0, 0)

    def test_a_short_span_is_labelled_by_the_hour(self):
        chart = charts.rise_chart([one("Rye", (0, 10), (8, 90))], tz=NY)

        assert all(":" in tick.label for tick in chart.ticks)

    def test_a_long_span_is_labelled_by_the_day(self):
        chart = charts.rise_chart([one("Rye", (0, 10), (240, 90))], tz=NY)

        assert all(":" not in tick.label for tick in chart.ticks)

    def test_everything_at_one_instant_lands_in_the_middle(self):
        chart = charts.rise_chart(
            [one("Rye", (0, 10)), one("Soviet", (0, 90))], tz=NY
        )

        middle = chart.plot.x + chart.plot.w / 2
        assert [line.points[0].x for line in chart.lines] == [middle, middle]
        assert len(chart.ticks) == 1


class TestTheLines:
    def test_each_jar_gets_its_own_colour_slot(self):
        chart = charts.rise_chart(
            [one("Rye", (0, 10), (6, 20)), one("Soviet", (0, 80), (6, 90))],
            tz=NY,
        )

        assert [line.slot for line in chart.lines] == [1, 2]

    def test_the_control_says_so(self):
        chart = charts.rise_chart(
            [
                one("Rye", (0, 10), (6, 20)),
                one("Soviet", (0, 80), (6, 90), control=True),
            ],
            tz=NY,
        )

        assert [line.is_control for line in chart.lines] == [False, True]

    def test_the_polyline_is_ready_to_draw(self):
        chart = charts.rise_chart([one("Rye", (0, 10), (6, 90))], tz=NY)
        points = chart.lines[0].polyline.split(" ")

        assert len(points) == 2
        assert all(part.count(",") == 1 for part in points)

    def test_last_and_best_are_not_the_same_question(self):
        chart = charts.rise_chart([one("Rye", (0, 110), (6, 40))], tz=NY)
        line = chart.lines[0]

        assert line.last.value == 40
        assert line.best.value == 110


class TestBarsOfElapsedTime:
    def test_nothing_timed_draws_nothing(self):
        assert charts.time_bar([("Bake", "bake", None)]) is None

    def test_segments_are_in_proportion(self):
        bar = charts.time_bar(
            [("Knead", "knead", 30.0), ("Bake", "bake", 90.0)]
        )

        assert [round(seg.pct) for seg in bar.segments] == [25, 75]
        assert bar.total_min == 120

    def test_a_phase_the_machine_does_not_have_is_left_out(self):
        bar = charts.time_bar(
            [("Rest", "rest", None), ("Bake", "bake", 60.0)]
        )

        assert [seg.name for seg in bar.segments] == ["Bake"]

    def test_an_untimed_recipe_stage_is_kept_and_marked(self):
        bar = charts.time_bar(
            [("Bulk", "rise", 120.0), ("Shape", "other", None)],
            keep_unknown=True,
        )

        shape = bar.segments[1]
        assert shape.unknown
        assert shape.minutes is None
        assert shape.duration_label == "no time set"
        assert bar.has_unknown

    def test_segments_know_where_they_start(self):
        bar = charts.time_bar(
            [("Knead", "knead", 10.0), ("Rest", "rest", 20.0), ("Bake", "bake", 60.0)]
        )

        assert [seg.start_min for seg in bar.segments] == [0, 10, 30]

    def test_a_half_minute_stir_down_reads_in_seconds(self):
        bar = charts.time_bar(
            [("Stir", "stir", 0.5), ("Bake", "bake", 60.0)]
        )

        assert bar.segments[0].duration_label == "30 sec"
        assert "Stir — 30 sec" == bar.segments[0].title

    def test_long_phases_read_in_hours(self):
        bar = charts.time_bar([("Bake", "bake", 69.0), ("Rest", "rest", 30.0)])

        assert bar.segments[0].duration_label == "1 h 09 min"
        assert bar.total_label == "1:39"

    def test_time_the_manual_does_not_break_down_gets_its_own_segment(self):
        bar = charts.time_bar(
            [("Knead 1", "knead", 15.0), ("Bake", "bake", 75.0)],
            total_min=100,
        )

        last = bar.segments[-1]
        assert last.key == "unlisted"
        assert last.minutes == 10
        assert bar.total_min == 100

    def test_rounding_in_the_manual_does_not_earn_a_segment(self):
        bar = charts.time_bar(
            [("Knead", "knead", 10.0), ("Bake", "bake", 69.0)], total_min=80
        )

        assert [seg.key for seg in bar.segments] == ["knead", "bake"]

    def test_a_program_that_is_barely_broken_down_draws_no_bar(self):
        # The West Bend's Custom program: 185 minutes, of which the manual
        # itemises a thirty-second stir-down. A bar would be a lie.
        assert charts.time_bar([("Stir", "stir", 0.5)], total_min=185) is None
