"""The feed being typed, drawn before it is logged.

The point of the panel is that the cycle length is controllable: change the
amounts and the peak moves. So the checks here are mostly about movement —
more flour, a later peak — and about the one judgement the panel makes, which
is whether the peak lands on the feed it is aimed at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import BusyKind, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.services import plan as plan_service
from app.services import timing
from app.services.units import f_to_c

TZ = "America/New_York"


def _tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo(TZ)


def _jar(session, name="Old Rye", **fields) -> Jar:
    jar = Jar(name=name, origin=JarOrigin.HOMEMADE, **fields)
    session.add(jar)
    session.commit()
    return jar


def _feed(session, jar, *, at, starter=20.0, flour=40.0, water=40.0, temp_c=None):
    session.add(
        Feeding(
            jar_id=jar.id, fed_at=at, starter_g=starter,
            flour_g=flour, water_g=water, ambient_temp_c=temp_c,
        )
    )
    session.commit()


def _sleep_block(session, label="Sleep", start_min=120, end_min=600):
    session.add(
        BusyBlock(
            label=label, kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
            start_minute=start_min, end_minute=end_min,
        )
    )
    session.commit()


def _release(session):
    session.rollback()
    session.expire_all()


def _preview(session, jar, *, starter, flour, now, temp_c=None, fed_at=None):
    return plan_service.feed_preview(
        session, jar,
        starter_g=starter, flour_g=flour,
        fed_at=fed_at or now, now=now, tz=_tz(), ambient_temp_c=temp_c,
    )


NOON = datetime(2026, 3, 14, 16, 0, tzinfo=UTC)   # noon in New York


# --- The peak moves with the ratio --------------------------------------


class TestTheRatioMovesThePeak:
    def test_more_flour_pushes_the_peak_later(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        peaks = [
            _preview(session, jar, starter=20, flour=flour, now=NOON,
                     temp_c=24.0).peak_at
            for flour in (20, 40, 100, 200)
        ]

        assert all(a < b for a, b in zip(peaks, peaks[1:], strict=False)), peaks

    def test_warmer_brings_the_peak_sooner(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        cool = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=18.0)
        warm = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=30.0)

        assert warm.peak_at < cool.peak_at

    def test_the_peak_is_the_model_with_the_jar_s_factor_in_it(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=20, flour=60, now=NOON, temp_c=24.0)
        factor = plan_service.jar_factor(session, jar)

        assert made.ratio == 3.0
        assert made.peak_h == timing.predict_peak_h(3.0, 24.0, factor)
        assert made.peak_at == NOON + timedelta(hours=made.peak_h)


# --- What it is aimed at ------------------------------------------------


class TestWhatThePeakIsAimedAt:
    def test_it_aims_at_the_feed_after_the_slot_it_fills(self, session):
        """Not at the slot this feed *is*: that is an hour away, and nothing
        feedable peaks in an hour."""
        jar = _jar(session, feeds_per_day=2)
        # Fed 11 h ago on a 12 h cycle: the next planned feed is an hour off,
        # and this feed is the one that fills it.
        _feed(session, jar, at=NOON - timedelta(hours=11))

        made = plan_service.jar_plan(
            session, jar, now=NOON, until=NOON + timedelta(days=2)
        )
        preview = _preview(session, jar, starter=20, flour=40, now=NOON)

        assert made.next_feed_at is not None
        assert preview.target_at is not None
        assert preview.target_at > made.next_feed_at
        # A whole cycle past the slot being filled.
        assert abs(
            (preview.target_at - made.next_feed_at) - timedelta(hours=12)
        ) < timedelta(minutes=2)

    def test_it_agrees_with_the_late_feed_card_about_which_slot(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=16))

        late = plan_service.feed_against_plan(
            session, jar, fed_at=NOON, now=NOON
        )
        preview = _preview(session, jar, starter=20, flour=40, now=NOON)

        assert late is not None
        assert late.is_late
        # The card says this feed answers `planned_at`; the panel aims past it.
        assert preview.target_at is not None
        assert preview.target_at > late.planned_at

    def test_a_jar_with_nothing_planned_has_nothing_to_aim_at(self, session):
        jar = _jar(session)  # never fed, no anchor

        preview = _preview(session, jar, starter=20, flour=40, now=NOON)

        assert preview.target_at is None
        assert preview.gap_h is None
        assert preview.lands_well is False
        assert preview.better_ratio_label is None


# --- The judgement ------------------------------------------------------


class TestWhetherItLands:
    def _aimed(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=11), temp_c=24.0)
        return jar

    def test_the_advised_ratio_lands_well(self, session):
        jar = self._aimed(session)
        rough = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=24.0)
        assert rough.advice is not None

        # Feed what it advises, and the judgement flips.
        landed = _preview(
            session, jar, starter=20, flour=20 * rough.advice.ratio,
            now=NOON, temp_c=24.0,
        )

        assert landed.lands_well
        assert landed.better_ratio_label is None

    def test_a_peak_too_early_says_so_and_offers_a_ratio(self, session):
        jar = self._aimed(session)

        made = _preview(session, jar, starter=20, flour=20, now=NOON, temp_c=24.0)

        assert made.is_early
        assert made.is_late is False
        assert made.gap_h is not None and made.gap_h < 0
        assert made.better_ratio_label is not None

    def test_the_tolerance_is_the_peak_band_not_a_fixed_hour(self, session):
        """A long cycle may be a bit further out and still count as landing:
        the jar is at its peak for longer."""
        jar = self._aimed(session)

        made = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=24.0)

        assert made.peak_h is not None
        assert made.tolerance_h == (timing.PEAK_TO - 1.0) * made.peak_h

    def test_it_does_not_offer_the_ratio_already_typed(self, session):
        jar = self._aimed(session)
        rough = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=24.0)
        assert rough.advice is not None

        same = _preview(
            session, jar, starter=20, flour=20 * rough.advice.ratio,
            now=NOON, temp_c=24.0,
        )

        assert same.better_ratio_label is None

    def test_it_says_nothing_when_no_feedable_ratio_reaches(self, session):
        """The advice card above the form has room for the caveat; a bare
        ratio under the chart that cannot work would only mislead."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))
        # Anchored so the slot being filled is 14 h out and the one it aims
        # at is 26 h out. Nothing feedable peaks 26 h away in a warm room:
        # even 1:10:10 at 24 °C is a 13 h cycle.
        jar.schedule_anchor_utc = NOON + timedelta(hours=14)
        session.commit()

        made = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=24.0)

        assert made.target_at == NOON + timedelta(hours=26)
        assert made.advice is not None
        assert made.advice.clamped_note is not None
        assert made.better_ratio_label is None


# --- A build with no starter --------------------------------------------


class TestABuildWithNoStarter:
    def test_no_starter_means_no_ratio_and_no_peak(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=0, flour=40, now=NOON)

        assert made.has_ratio is False
        assert made.ratio_label is None
        assert made.peak_at is None
        assert made.lands_well is False

    def test_it_still_draws_the_plan(self, session):
        """An empty curve with the planned feeds on it still says something."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=None, flour=None, now=NOON)

        assert made.drawn is not None
        assert len(made.drawn.rows) == 1
        assert made.drawn.rows[0].curves == ()
        assert made.drawn.rows[0].note


# --- The picture --------------------------------------------------------


class TestThePicture:
    def test_it_draws_one_row_for_this_jar_only(self, session):
        jar = _jar(session, feeds_per_day=2)
        _jar(session, name="Soviet Rye", is_control=True)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=20, flour=40, now=NOON)

        assert made.drawn is not None
        assert [row.name for row in made.drawn.rows] == ["Old Rye"]

    def test_the_window_holds_the_peak_and_the_target(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=24.0)

        assert made.drawn is not None
        assert made.peak_at is not None and made.target_at is not None
        assert made.drawn.start <= made.peak_at <= made.drawn.end
        assert made.drawn.start <= made.target_at <= made.drawn.end

    def test_the_window_only_steps_between_set_spans(self, session):
        """So that nudging a ratio slides the peak instead of rescaling the
        picture underneath it."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        spans = {
            round(_preview(
                session, jar, starter=20, flour=flour, now=NOON, temp_c=24.0
            ).drawn.span_h)
            for flour in range(20, 200, 10)
        }

        assert spans <= set(plan_service.PREVIEW_SPANS_H), spans

    def test_the_drawn_feed_carries_the_ratio_and_the_assumed_temperature(
        self, session
    ):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))  # no temp logged

        made = _preview(session, jar, starter=20, flour=40, now=NOON)

        assert made.temp_assumed is True
        curve = made.drawn.rows[0].curves[0]
        assert curve.feed.ratio_label == "1:2:2"
        assert curve.feed.temp_assumed is True

    def test_a_typed_temperature_is_not_assumed(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=20, flour=40, now=NOON, temp_c=24.0)

        assert made.temp_assumed is False
        assert made.temp_c == 24.0

    def test_a_peak_in_the_night_is_named_as_such(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12), temp_c=24.0)
        _sleep_block(session)  # 02:00–10:00 local, every day

        # A thick feed at noon in a cool room peaks in the small hours.
        made = _preview(session, jar, starter=20, flour=200, now=NOON, temp_c=20.0)

        assert made.busy_label == "Sleep"

    def test_only_feeds_after_this_one_are_drawn_as_planned(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(session, jar, starter=20, flour=40, now=NOON)

        assert made.drawn is not None
        assert all(
            point.mark.at > NOON for point in made.drawn.rows[0].planned
        )


# --- Nothing falls off the edge -----------------------------------------
#
# The panel is there to be swung: the amounts get nudged until the peak
# lands where it is wanted. So whatever they are swung to, the window has
# to hold the whole of what it is being asked about — the curve down to the
# baseline, and the feeds it is being read against. A curve cut off at the
# right edge is the picture failing at the one job it has.


#: A sweep wide enough to reach both clamps of the model, and both ends of
#: the temperature range with them: the window must hold every one of them.
_SWINGS = [
    (starter, flour, temp_c)
    for starter, flour in ((20, 10), (20, 20), (20, 60), (20, 120), (20, 400))
    for temp_c in (16.0, 24.0, 34.0)
]


class TestNothingFallsOffTheEdge:
    def test_the_window_holds_the_whole_curve_whatever_is_fed(self, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        for starter, flour, temp_c in _SWINGS:
            made = _preview(
                session, jar, starter=starter, flour=flour, now=NOON,
                temp_c=temp_c,
            )

            assert made.peak_h is not None
            ends = NOON + timedelta(hours=made.peak_h * timing.PAST_TO)
            assert made.drawn is not None
            assert made.drawn.end >= ends, (starter, flour, temp_c)

    def test_the_curve_stops_short_of_the_frame_whatever_is_fed(self, session):
        """Drawn, not merely in the window: the ribbon clamps anything past
        the edge onto it, so a clipped curve ends exactly at plot.right."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        for starter, flour, temp_c in _SWINGS:
            made = _preview(
                session, jar, starter=starter, flour=flour, now=NOON,
                temp_c=temp_c,
            )

            curve = made.drawn.rows[0].curves[0]
            last_x = curve.segments[-1].points[-1][0]
            assert last_x < made.drawn.plot.right - 1.0, (
                starter, flour, temp_c, last_x,
            )

    def test_the_window_holds_the_next_planned_feed_whatever_is_fed(self, session):
        """Even a feed so thin that the curve is over before the next slot:
        the planned feed is what the peak is being aimed at, so it is on the
        picture even when nothing else reaches it."""
        jar = _jar(session, feeds_per_day=1)  # a slot a whole day out
        _feed(session, jar, at=NOON - timedelta(hours=24))

        for starter, flour, temp_c in _SWINGS:
            made = _preview(
                session, jar, starter=starter, flour=flour, now=NOON,
                temp_c=temp_c,
            )

            assert made.drawn is not None
            assert made.drawn.rows[0].planned, (starter, flour, temp_c)
            if made.target_at is not None:
                assert made.drawn.end >= made.target_at, (starter, flour, temp_c)

    def test_a_long_cycle_lengthens_the_axis(self, session):
        """1:10:10 in a cold room takes days to come back down, and the days
        are drawn rather than the curve being cut at two of them."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=12))

        made = _preview(
            session, jar, starter=20, flour=400, now=NOON, temp_c=15.0
        )

        assert made.drawn is not None
        assert made.peak_h is not None
        assert made.drawn.span_h > 48
        assert made.drawn.end >= NOON + timedelta(
            hours=made.peak_h * timing.PAST_TO
        )

    def test_the_ladder_is_not_a_ceiling(self):
        """Past the last rung it steps in whole days. A jar measured slow
        enough can want more than the longest rung, and a span that stopped
        there would go back to clipping."""
        longest = max(plan_service.PREVIEW_SPANS_H)

        assert plan_service._preview_span_h(longest) == longest
        assert plan_service._preview_span_h(longest + 0.5) >= longest + 0.5
        assert plan_service._preview_span_h(200.0) >= 200.0
        assert plan_service._preview_span_h(200.0) % 24 == 0


# --- On the page --------------------------------------------------------


class TestOnThePage:
    def test_the_form_arrives_with_the_panel_already_drawn(self, client, session):
        """No JavaScript needed for the first picture."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=4), temp_c=f_to_c(80.0))
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}/feed")

        assert page.status_code == 200
        assert 'id="feed-preview"' in page.text
        assert "If you feed it this" in page.text
        assert 'class="ribbon"' in page.text

    def test_the_panel_refetches_on_the_fields_the_peak_depends_on(
        self, client, session
    ):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=4))
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}/feed")
        panel = page.text.split('id="feed-preview"')[1].split(">")[0]

        assert f"/jars/{jar_id}/feed/preview" in panel
        for field in ("starter_g", "flour_g", "ambient_temp", "fed_at"):
            assert field in panel

    def test_the_route_redraws_for_new_amounts(self, client, session):
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=4))
        jar_id = jar.id
        _release(session)

        thin = client.get(
            f"/jars/{jar_id}/feed/preview",
            params={"starter_g": "20", "flour_g": "20", "ambient_temp": "75"},
        )
        thick = client.get(
            f"/jars/{jar_id}/feed/preview",
            params={"starter_g": "20", "flour_g": "200", "ambient_temp": "75"},
        )

        assert thin.status_code == thick.status_code == 200
        assert "1:1:1" in thin.text
        assert "1:10:10" in thick.text
        # A panel, not a page: no card around it and no page furniture.
        assert "<html" not in thick.text
        assert 'class="feed-preview"' in thick.text

    def test_a_half_typed_number_leaves_a_picture_standing(
        self, client, session
    ):
        """It runs on every keystroke. "2o" must not 500 or blank the panel."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=4))
        jar_id = jar.id
        _release(session)

        page = client.get(
            f"/jars/{jar_id}/feed/preview",
            params={
                "starter_g": "2o", "flour_g": "", "ambient_temp": "warm",
                "fed_at": "not-a-date",
            },
        )

        assert page.status_code == 200
        assert 'class="feed-preview"' in page.text
        assert "no ratio to take" in page.text

    def test_the_panel_reads_amounts_the_way_the_form_does(
        self, client, session
    ):
        """Through parse_quantity, so a written-out unit beats the setting."""
        jar = _jar(session, feeds_per_day=2)
        _feed(session, jar, at=NOON - timedelta(hours=4))
        jar_id = jar.id
        _release(session)

        # Off grams, so a bare number would be read as something else.
        client.post("/settings/units", data={"weight_unit": "us_volume"})

        page = client.get(
            f"/jars/{jar_id}/feed/preview",
            params={"starter_g": "20 g", "flour_g": "40 g"},
        )

        assert page.status_code == 200
        assert "1:2:2" in page.text

    def test_there_is_no_panel_for_a_jar_that_does_not_exist(
        self, client, session
    ):
        page = client.get("/jars/9999/feed/preview", params={"starter_g": "20"})

        assert page.status_code == 404
