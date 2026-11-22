"""Learning how fast each jar really is, from synthetic peaks.

The model says five hours at 1:1:1 and 25.5 °C. These build jars that peak
reliably later or sooner than that and check the factor that comes back, then
check the guards: one forgotten tap, a jar with nothing recorded, a peak with
no feed before it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.bake import Bake, BakeStageLog
from app.models.enums import BakeStatus, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.observation import Observation
from app.models.recipe import Recipe, RecipeVersion
from app.services import learning, timing

#: What the model predicts for the feed these tests use, in hours.
BASELINE_H = timing.predict_peak_h(1.0, timing.REF_TEMP_C)


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def _jar(session, *, name="Old Rye") -> Jar:
    jar = Jar(name=name, origin=JarOrigin.HOMEMADE)
    session.add(jar)
    session.flush()
    return jar


def _cycle(session, jar, *, fed_at, took_h, peaked=True):
    """A feed, and an observation of its peak `took_h` later."""
    session.add(
        Feeding(
            jar_id=jar.id, fed_at=fed_at,
            starter_g=20.0, flour_g=20.0, water_g=20.0,
            ambient_temp_c=timing.REF_TEMP_C,
        )
    )
    session.add(
        Observation(
            jar_id=jar.id,
            observed_at=fed_at + timedelta(hours=took_h),
            peaked=peaked,
        )
    )
    session.flush()


def _levain(session, jar, *, ended, model_min, actual_min, at_peak=True):
    """A bake whose levain rise was answered for."""
    recipe = Recipe(name=f"Loaf {ended:%d%H%M}")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1)
    session.add(version)
    session.flush()
    bake = Bake(
        recipe_version_id=version.id, jar_id=jar.id,
        status=BakeStatus.DONE, started_at=ended - timedelta(hours=8),
    )
    session.add(bake)
    session.flush()
    session.add(
        BakeStageLog(
            bake_id=bake.id, seq=0, name="Levain rises to its peak",
            step_key="levain_rise",
            planned_min=model_min, model_min=model_min,
            actual_start=ended - timedelta(minutes=actual_min),
            actual_end=ended,
            at_peak=at_peak,
            must_be_home=True,
        )
    )
    session.flush()


# --- The arithmetic -----------------------------------------------------


class TestTheFactor:
    def test_a_jar_with_nothing_recorded_does_not_argue(self, session):
        jar = _jar(session)

        learned = learning.learned(session, jar)

        assert learned.factor == 1.0
        assert not learned.has_data
        assert not learned.is_confident

    def test_a_jar_that_peaks_on_time_leaves_the_model_alone(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H)

        assert learning.factor(session, jar) == pytest.approx(1.0, abs=0.01)

    def test_a_slow_jar_stretches_every_prediction(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 1.2)

        assert learning.factor(session, jar) == pytest.approx(1.2, abs=0.01)

    def test_a_fast_jar_shortens_them(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 0.8)

        assert learning.factor(session, jar) == pytest.approx(0.8, abs=0.01)

    def test_the_newest_cycle_carries_the_most_weight(self, session):
        """A jar that has just got faster should not be held to last week."""
        jar = _jar(session)
        for day in (10, 11, 12, 13):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 1.4)
        _cycle(session, jar, fed_at=_at(14), took_h=BASELINE_H * 1.0)

        factor = learning.factor(session, jar)

        # Pulled well below the four slow cycles, but not all the way to the
        # newest one: one cycle is evidence, not proof.
        assert 1.0 < factor < 1.25

    def test_nothing_older_than_five_cycles_has_a_say(self, session):
        jar = _jar(session)
        # Six fast ones, then five slow ones: only the slow ones are inside
        # the window, so the answer should be slow with nothing pulling it.
        for day in range(1, 7):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 0.5)
        for day in range(10, 15):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 1.3)

        learned = learning.learned(session, jar)

        assert learned.count == learning.MAX_PEAKS
        assert learned.factor == pytest.approx(1.3, abs=0.02)

    def test_one_forgotten_tap_cannot_take_the_predictions_with_it(
        self, session
    ):
        """Tapping "peaked" the next morning is a thing that happens."""
        jar = _jar(session)
        for day in (10, 11, 12, 13):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H)
        _cycle(session, jar, fed_at=_at(14), took_h=BASELINE_H * 6)

        factor = learning.factor(session, jar)

        # The wild cycle is reined in to the same bound as the factor, so it
        # pulls hard but cannot run away with it.
        assert factor <= learning.MAX_FACTOR
        assert factor < 1.6

    def test_the_factor_never_leaves_its_bounds(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 20)

        assert learning.factor(session, jar) == learning.MAX_FACTOR

        other = _jar(session, name="Quick")
        for day in (10, 11, 12):
            _cycle(session, other, fed_at=_at(day), took_h=0.2)

        assert learning.factor(session, other) == learning.MIN_FACTOR

    def test_a_single_cycle_being_clamped_is_visible(self, session):
        jar = _jar(session)
        _cycle(session, jar, fed_at=_at(10), took_h=BASELINE_H * 9)

        peak = learning.recorded_peaks(session, jar)[0]

        assert peak.was_clamped
        assert peak.ratio == learning.MAX_FACTOR

    def test_the_weighting_is_the_plain_decaying_mean(self):
        """Checked against the arithmetic, not against the implementation."""
        peaks = tuple(
            learning.Peak(
                at=_at(10 + index), observed_h=hours, predicted_h=5.0,
                source=learning.PeakSource.OBSERVATION,
            )
            for index, hours in enumerate((6.0, 5.0, 5.0))
        )

        weights = [learning.WEIGHT_DECAY**index for index in range(3)]
        ratios = [6 / 5, 1.0, 1.0]
        expected = sum(r * w for r, w in zip(ratios, weights, strict=True))
        expected /= sum(weights)

        assert learning.weighted_factor(peaks) == pytest.approx(expected)


class TestWhatCounts:
    def test_an_observation_that_said_nothing_about_the_peak_is_ignored(
        self, session
    ):
        jar = _jar(session)
        _cycle(session, jar, fed_at=_at(10), took_h=BASELINE_H * 1.5,
               peaked=False)

        assert learning.recorded_peaks(session, jar) == ()
        assert learning.factor(session, jar) == 1.0

    def test_a_peak_with_no_feed_before_it_measures_nothing(self, session):
        jar = _jar(session)
        session.add(
            Observation(jar_id=jar.id, observed_at=_at(10), peaked=True)
        )
        session.flush()

        assert learning.recorded_peaks(session, jar) == ()

    def test_it_is_read_against_the_feed_it_followed(self, session):
        """Not the first feed, and not the next one."""
        jar = _jar(session)
        _cycle(session, jar, fed_at=_at(10), took_h=BASELINE_H * 2)
        _cycle(session, jar, fed_at=_at(12), took_h=BASELINE_H)

        peaks = learning.recorded_peaks(session, jar)

        assert len(peaks) == 2
        assert peaks[0].observed_h == pytest.approx(BASELINE_H, abs=0.01)
        assert peaks[1].observed_h == pytest.approx(BASELINE_H * 2, abs=0.01)

    def test_the_feeds_own_ratio_and_warmth_are_what_it_is_measured_against(
        self, session
    ):
        """A dilute feed in a cool room is meant to take longer."""
        jar = _jar(session)
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=_at(10),
                starter_g=20.0, flour_g=100.0, water_g=100.0,
                ambient_temp_c=20.0,
            )
        )
        slow = timing.predict_peak_h(5.0, 20.0)
        session.add(
            Observation(
                jar_id=jar.id,
                observed_at=_at(10) + timedelta(hours=slow),
                peaked=True,
            )
        )
        session.flush()

        # It took much longer than a 1:1:1 would, and the jar is still
        # exactly on the model.
        assert slow > BASELINE_H * 1.5
        assert learning.factor(session, jar) == pytest.approx(1.0, abs=0.01)

    def test_a_levain_answered_yes_counts_too(self, session):
        jar = _jar(session)
        _levain(session, jar, ended=_at(12), model_min=300, actual_min=360)

        peaks = learning.recorded_peaks(session, jar)

        assert len(peaks) == 1
        assert peaks[0].source is learning.PeakSource.LEVAIN
        assert learning.factor(session, jar) == pytest.approx(1.2, abs=0.01)

    def test_a_levain_answered_no_counts_for_nothing(self, session):
        """"I used it anyway" is not a measurement of its peak."""
        jar = _jar(session)
        _levain(
            session, jar, ended=_at(12), model_min=300, actual_min=200,
            at_peak=False,
        )

        assert learning.recorded_peaks(session, jar) == ()

    def test_a_levain_is_read_against_the_bare_model_not_the_correction(
        self, session
    ):
        """Otherwise the correction would quietly measure itself."""
        jar = _jar(session)
        # The plan already had a 1.5 correction in it: 300 model, 450 planned.
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=_at(10),
                starter_g=20.0, flour_g=20.0, water_g=20.0,
            )
        )
        recipe = Recipe(name="Loaf")
        session.add(recipe)
        session.flush()
        version = RecipeVersion(recipe_id=recipe.id, version=1)
        session.add(version)
        session.flush()
        bake = Bake(
            recipe_version_id=version.id, jar_id=jar.id,
            status=BakeStatus.DONE,
        )
        session.add(bake)
        session.flush()
        session.add(
            BakeStageLog(
                bake_id=bake.id, seq=0, name="Levain rises to its peak",
                step_key="levain_rise", planned_min=450, model_min=300,
                actual_start=_at(12) - timedelta(minutes=450),
                actual_end=_at(12), at_peak=True, must_be_home=True,
            )
        )
        session.flush()

        # It took the 450 the corrected plan expected, which against the
        # bare model's 300 is a factor of 1.5 — not 1.0.
        assert learning.factor(session, jar) == pytest.approx(1.5, abs=0.01)

    def test_both_kinds_are_pooled_newest_first(self, session):
        jar = _jar(session)
        _cycle(session, jar, fed_at=_at(10), took_h=BASELINE_H * 1.5)
        _levain(session, jar, ended=_at(14), model_min=300, actual_min=300)

        peaks = learning.recorded_peaks(session, jar)

        assert [one.source for one in peaks] == [
            learning.PeakSource.LEVAIN, learning.PeakSource.OBSERVATION
        ]

    def test_another_jars_peaks_are_its_own(self, session):
        mine = _jar(session, name="Old Rye")
        theirs = _jar(session, name="Soviet rye")
        for day in (10, 11, 12):
            _cycle(session, mine, fed_at=_at(day), took_h=BASELINE_H * 1.3)

        assert learning.factor(session, theirs) == 1.0
        assert learning.factor(session, mine) > 1.2


class TestWhatItSays:
    def test_it_takes_three_peaks_to_stop_being_an_estimate(self, session):
        jar = _jar(session)
        _cycle(session, jar, fed_at=_at(10), took_h=BASELINE_H)
        assert not learning.learned(session, jar).is_confident

        _cycle(session, jar, fed_at=_at(11), took_h=BASELINE_H)
        assert not learning.learned(session, jar).is_confident

        _cycle(session, jar, fed_at=_at(12), took_h=BASELINE_H)
        assert learning.learned(session, jar).is_confident

    def test_a_slow_jar_is_described_in_plain_words(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 1.2)

        blurb = learning.learned(session, jar).blurb

        assert "Old Rye" in blurb
        assert "20%" in blurb
        assert "later" in blurb

    def test_a_fast_jar_too(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 0.75)

        blurb = learning.learned(session, jar).blurb

        assert "25%" in blurb
        assert "sooner" in blurb

    def test_a_jar_on_the_model_is_not_made_to_sound_interesting(
        self, session
    ):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H * 1.02)

        learned = learning.learned(session, jar)

        assert not learned.is_notable
        assert "about when the model expects" in learned.blurb

    def test_an_unwatched_jar_is_told_what_to_do_about_it(self, session):
        jar = _jar(session)

        learned = learning.learned(session, jar)

        assert learned.blurb is None
        assert "Peaked now" in learned.caveat

    def test_once_it_is_confident_there_is_no_caveat(self, session):
        jar = _jar(session)
        for day in (10, 11, 12):
            _cycle(session, jar, fed_at=_at(day), took_h=BASELINE_H)

        assert learning.learned(session, jar).caveat is None

    def test_one_cycle_is_counted_in_the_singular(self, session):
        jar = _jar(session)
        _cycle(session, jar, fed_at=_at(10), took_h=BASELINE_H * 1.3)

        learned = learning.learned(session, jar)

        assert "1 cycle recorded" in learned.caveat
        assert "cycles" not in learned.blurb
