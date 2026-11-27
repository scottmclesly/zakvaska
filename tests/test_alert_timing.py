"""When the app interrupts you, on the days the clock misbehaves.

Every alert here is derived from a time: a feed from the jar's rhythm, a
bake step from the plan, the preheat from the bake step. The ordinary cases
have their own files (test_alerts, test_stage_alerts, test_preheat,
test_ribbon). This one is about the edges, where a time that is right on a
Wednesday afternoon can be an hour out:

- a feed that falls on the far side of midnight, or of New Year;
- the two Sundays a year the clocks change, in both directions;
- the kitchen itself moving to another timezone.

The rule the tests hold the app to is the one busy blocks already follow
(services/busy.py): **a rhythm is a pattern on the wall clock, a duration is
real elapsed time.** A jar fed at eight and eight is fed at eight and eight
the week the clocks change too. A five-hour proof is five hours of proving,
whatever the clock did in the middle of it.

All dates are New York's 2026 changes unless a test says otherwise:
spring forward on Sunday 8 March (02:00 becomes 03:00), fall back on
Sunday 1 November (02:00 becomes 01:00).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.alert import Alert
from app.models.bake import BakeStageLog
from app.models.base import utcnow
from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import (
    AlertKind,
    BakeMethod,
    BakeStatus,
    BusyKind,
    IngredientRole,
    JarOrigin,
    JarState,
    RecipeCategory,
)
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.models.setting import PREHEAT_POT_CHOICES
from app.services import alerts as alert_service
from app.services import bakeplan, followalong, ribbon, settings_store
from app.services import bakes as bake_service
from app.services import recipes as recipe_service
from app.services import hints as hint_service
from app.services import jars as jar_service
from app.services import plan as plan_service
from app.services.bakeplan import PlanInputs
from app.services.recipes import IngredientSpec, StageSpec
from app.services.schedule import last_feeding
from app.templates_env import local_dt

NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


def local(year, month, day, hour=0, minute=0, *, tz=NY, fold=0) -> datetime:
    """A reading off the kitchen clock, as the instant it names."""
    return datetime(year, month, day, hour, minute, tzinfo=tz, fold=fold).astimezone(UTC)


def on_clock(moment: datetime, tz=NY) -> str:
    return moment.astimezone(tz).strftime("%a %H:%M")


@pytest.fixture
def in_zone(monkeypatch):
    """Move the kitchen: change ZAKVASKA_TZ the way editing .env does."""

    def move(name: str) -> ZoneInfo:
        monkeypatch.setenv("ZAKVASKA_TZ", name)
        get_settings.cache_clear()
        return ZoneInfo(name)

    yield move
    monkeypatch.undo()
    get_settings.cache_clear()


# --- Jars ---------------------------------------------------------------


def make_jar(session, *, feeds_per_day: int, name="Homemade rye", **fields):
    jar = jar_service.create_jar(
        session,
        name=name,
        origin=JarOrigin.HOMEMADE,
        feeds_per_day=feeds_per_day,
        **fields,
    )
    session.commit()
    return jar


def feed(session, jar, at: datetime):
    feeding = jar_service.log_feeding(
        session, jar, fed_at=at, starter_g=20, flour_g=40, water_g=40,
        ambient_temp_c=24.0,
    )
    session.commit()
    return feeding


def due(session, jar, now: datetime) -> datetime | None:
    """The moment the app will ask for this jar's next feed."""
    return alert_service.due_at(session, jar, last_feeding(session, jar.id), now)


def planned(session, jar, now: datetime, days: int = 3) -> list[datetime]:
    made = plan_service.jar_plan(
        session, jar, now=now, until=now + timedelta(days=days)
    )
    return [one.at for one in made.planned]


def feed_alerts(session, jar) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert)
            .where(Alert.jar_id == jar.id, Alert.kind == AlertKind.FEED_DUE)
            .order_by(Alert.due_at)
        )
    )


def tick(session, now: datetime):
    result = alert_service.reconcile(session, now)
    session.commit()
    return result


# ========================================================================
# Feed windows
# ========================================================================


class TestFeedWindowsOnAnOrdinaryDay:
    def test_twice_a_day_is_due_twelve_hours_on(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 8))

        assert due(session, jar, local(2026, 6, 10, 9)) == local(2026, 6, 10, 20)

    def test_once_a_day_is_due_the_same_time_tomorrow(self, session):
        jar = make_jar(session, feeds_per_day=1)
        feed(session, jar, local(2026, 6, 10, 8))

        assert due(session, jar, local(2026, 6, 10, 9)) == local(2026, 6, 11, 8)

    def test_twice_a_day_plans_every_twelve_hours(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 8))

        slots = planned(session, jar, local(2026, 6, 10, 9), days=2)

        assert [on_clock(at) for at in slots] == [
            "Wed 20:00", "Thu 08:00", "Thu 20:00", "Fri 08:00",
        ]

    def test_once_a_day_plans_every_twenty_four(self, session):
        jar = make_jar(session, feeds_per_day=1)
        feed(session, jar, local(2026, 6, 10, 8))

        slots = planned(session, jar, local(2026, 6, 10, 9), days=3)

        assert [on_clock(at) for at in slots] == ["Thu 08:00", "Fri 08:00", "Sat 08:00"]

    def test_a_jar_s_own_rhythm_beats_the_app_s(self, session):
        """Two jars side by side, one fed daily and one twice."""
        settings_store.set_setting(session, "feeds_per_day", "2")
        daily = make_jar(session, feeds_per_day=1, name="Daily")
        twice = make_jar(session, feeds_per_day=2, name="Twice")
        fed = local(2026, 6, 10, 8)
        feed(session, daily, fed)
        feed(session, twice, fed)

        assert due(session, daily, fed + HOUR) - fed == timedelta(hours=24)
        assert due(session, twice, fed + HOUR) - fed == timedelta(hours=12)

    @pytest.mark.parametrize("per_day", [1, 2])
    def test_the_alert_fires_on_the_minute_and_not_before(self, session, per_day):
        jar = make_jar(session, feeds_per_day=per_day)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        moment = due(session, jar, fed)

        early = tick(session, moment - MINUTE)
        on_time = tick(session, moment)

        assert early.fired == []
        assert [alert.due_at for alert in on_time.fired] == [moment]


class TestFeedWindowsOvernight:
    def test_an_evening_feed_is_due_tomorrow_morning(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 21, 30))

        moment = due(session, jar, local(2026, 6, 10, 22))

        assert moment == local(2026, 6, 11, 9, 30)
        assert moment.astimezone(NY).date() != local(2026, 6, 10, 21, 30).astimezone(NY).date()

    def test_nothing_fires_as_midnight_goes_by(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 21, 30))

        for now in (
            local(2026, 6, 10, 23, 59),
            local(2026, 6, 11, 0, 0),
            local(2026, 6, 11, 0, 1),
            local(2026, 6, 11, 9, 29),
        ):
            assert tick(session, now).fired == []

        assert len(tick(session, local(2026, 6, 11, 9, 30)).fired) == 1

    def test_a_feed_due_before_midnight_is_still_the_one_owed_after_it(self, session):
        """Missed at 23:00, and at 00:30 the app is still asking about that
        feed — not quietly moving on to tomorrow's."""
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 11))
        owed = local(2026, 6, 10, 23)
        tick(session, owed)

        later = local(2026, 6, 11, 0, 30)
        result = tick(session, later)

        assert due(session, jar, later) == owed
        assert result.created == [] and result.dropped == 0
        assert [alert.due_at for alert in alert_service.showing(session, later)] == [owed]
        assert jar_service.jar_card(session, jar, later).status.is_overdue

    def test_feeding_it_after_midnight_settles_it_and_plans_from_there(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 11))
        tick(session, local(2026, 6, 10, 23))

        fed = local(2026, 6, 11, 0, 30)
        feed(session, jar, fed)
        tick(session, fed + MINUTE)

        assert alert_service.showing(session, fed + MINUTE) == []
        assert due(session, jar, fed + MINUTE) == local(2026, 6, 11, 12, 30)

    def test_the_year_turning_over(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 12, 31, 21, 30))

        assert due(session, jar, local(2026, 12, 31, 22)) == local(2027, 1, 1, 9, 30)

    def test_the_last_night_of_february(self, session):
        jar = make_jar(session, feeds_per_day=1)
        feed(session, jar, local(2027, 2, 28, 22))

        assert due(session, jar, local(2027, 2, 28, 23)) == local(2027, 3, 1, 22)

    def test_a_weekly_fridge_jar_comes_due_on_the_same_weekday(self, session):
        jar = make_jar(session, feeds_per_day=2, state=JarState.FRIDGE)
        feed(session, jar, local(2026, 6, 10, 21))

        moment = due(session, jar, local(2026, 6, 11, 9))

        assert on_clock(moment) == "Wed 21:00"
        assert moment == local(2026, 6, 17, 21)


# ========================================================================
# The clocks change
# ========================================================================


class TestSpringForward:
    """Sunday 8 March 2026: 02:00 becomes 03:00, and the day is 23 hours."""

    def test_twice_a_day_stays_at_eight_and_eight(self, session):
        jar = make_jar(session, feeds_per_day=2)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 3, 7, 8), now=local(2026, 3, 7, 6)
        )
        session.commit()

        slots = planned(session, jar, local(2026, 3, 7, 6), days=3)

        assert [on_clock(at) for at in slots][:6] == [
            "Sat 08:00", "Sat 20:00", "Sun 08:00", "Sun 20:00", "Mon 08:00", "Mon 20:00",
        ]

    def test_once_a_day_stays_at_eight(self, session):
        jar = make_jar(session, feeds_per_day=1)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 3, 6, 8), now=local(2026, 3, 6, 6)
        )
        session.commit()

        slots = planned(session, jar, local(2026, 3, 6, 6), days=4)

        assert [on_clock(at) for at in slots] == [
            "Fri 08:00", "Sat 08:00", "Sun 08:00", "Mon 08:00",
        ]

    def test_the_night_s_gap_is_an_hour_short_in_real_time(self, session):
        """Eight to eight on the clock is eleven hours of fermenting that
        night. The plan says so honestly rather than hiding it."""
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 3, 7, 20))

        moment = due(session, jar, local(2026, 3, 7, 21))

        assert on_clock(moment) == "Sun 08:00"
        assert moment - local(2026, 3, 7, 20) == timedelta(hours=11)

    def test_the_alert_fires_at_eight_on_the_new_clock(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 3, 7, 20))

        assert tick(session, local(2026, 3, 8, 7, 59)).fired == []
        fired = tick(session, local(2026, 3, 8, 8, 0)).fired

        assert [on_clock(alert.due_at) for alert in fired] == ["Sun 08:00"]

    def test_it_is_still_at_eight_a_fortnight_later(self, session):
        """The grid is counted from the anchor, so an hour lost on the 8th
        must not still be missing on the 22nd."""
        jar = make_jar(session, feeds_per_day=2)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 3, 1, 8), now=local(2026, 3, 1, 6)
        )
        session.commit()
        feed(session, jar, local(2026, 3, 21, 20))

        slots = planned(session, jar, local(2026, 3, 22, 6), days=1)

        assert [on_clock(at) for at in slots] == ["Sun 08:00", "Sun 20:00"]

    def test_a_feed_planned_for_an_hour_that_does_not_exist(self, session):
        """02:30 never happens on the 8th. The feed lands at the moment the
        clock would have said 02:30, which reads 03:30 — once, and it is back
        at 02:30 the night after."""
        jar = make_jar(session, feeds_per_day=1)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 3, 7, 2, 30), now=local(2026, 3, 7, 1)
        )
        session.commit()

        slots = planned(session, jar, local(2026, 3, 7, 1), days=3)

        assert [on_clock(at) for at in slots] == ["Sat 02:30", "Sun 03:30", "Mon 02:30"]
        assert len(set(slots)) == len(slots)

    def test_the_predicted_peak_is_real_hours_not_clock_hours(self, session):
        """The starter cannot read a clock. Fed at 20:00 with a peak seven
        hours off, it peaks seven hours later, which the clock calls 04:00."""
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 3, 7, 20)
        feed(session, jar, fed)

        made = plan_service.jar_plan(session, jar, now=fed + HOUR, until=fed + 3 * 24 * HOUR)
        cycle = made.last_cycle

        assert cycle.peak_at - fed == timedelta(hours=cycle.peak_h)
        at_peak = made.readiness_at(cycle.peak_at)
        assert at_peak.fraction == pytest.approx(1.0)


class TestFallBack:
    """Sunday 1 November 2026: 02:00 becomes 01:00, and the day is 25 hours."""

    def test_twice_a_day_stays_at_eight_and_eight(self, session):
        jar = make_jar(session, feeds_per_day=2)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 10, 31, 8), now=local(2026, 10, 31, 6)
        )
        session.commit()

        slots = planned(session, jar, local(2026, 10, 31, 6), days=3)

        assert [on_clock(at) for at in slots][:6] == [
            "Sat 08:00", "Sat 20:00", "Sun 08:00", "Sun 20:00", "Mon 08:00", "Mon 20:00",
        ]

    def test_once_a_day_stays_at_eight(self, session):
        jar = make_jar(session, feeds_per_day=1)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 10, 30, 8), now=local(2026, 10, 30, 6)
        )
        session.commit()

        slots = planned(session, jar, local(2026, 10, 30, 6), days=4)

        assert [on_clock(at) for at in slots] == [
            "Fri 08:00", "Sat 08:00", "Sun 08:00", "Mon 08:00",
        ]

    def test_the_night_s_gap_is_an_hour_long_in_real_time(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 10, 31, 20))

        moment = due(session, jar, local(2026, 10, 31, 21))

        assert on_clock(moment) == "Sun 08:00"
        assert moment - local(2026, 10, 31, 20) == timedelta(hours=13)

    def test_the_alert_does_not_fire_an_hour_early(self, session):
        """The bug this guards: a grid kept in UTC rings at seven."""
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 10, 31, 20))

        assert tick(session, local(2026, 11, 1, 7, 0)).fired == []
        assert tick(session, local(2026, 11, 1, 7, 59)).fired == []
        fired = tick(session, local(2026, 11, 1, 8, 0)).fired

        assert [on_clock(alert.due_at) for alert in fired] == ["Sun 08:00"]

    def test_it_is_still_at_eight_a_fortnight_later(self, session):
        jar = make_jar(session, feeds_per_day=2)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 10, 25, 8), now=local(2026, 10, 25, 6)
        )
        session.commit()
        feed(session, jar, local(2026, 11, 14, 20))

        slots = planned(session, jar, local(2026, 11, 15, 6), days=1)

        assert [on_clock(at) for at in slots] == ["Sun 08:00", "Sun 20:00"]

    def test_a_feed_planned_for_the_hour_that_happens_twice(self, session):
        """01:30 comes round twice on the 1st. One feed, at the first of
        them — not two alerts an hour apart."""
        jar = make_jar(session, feeds_per_day=1)
        plan_service.move_next_feed(
            session, jar, to=local(2026, 10, 31, 1, 30), now=local(2026, 10, 31, 1)
        )
        session.commit()

        slots = planned(session, jar, local(2026, 10, 31, 1), days=3)

        assert [on_clock(at) for at in slots] == ["Sat 01:30", "Sun 01:30", "Mon 01:30"]
        assert slots[1] == local(2026, 11, 1, 1, 30, fold=0)

    def test_the_repeated_hour_fires_once(self, session):
        jar = make_jar(session, feeds_per_day=1)
        feed(session, jar, local(2026, 10, 31, 1, 30))
        first = local(2026, 11, 1, 1, 30, fold=0)
        second = local(2026, 11, 1, 1, 30, fold=1)
        assert second - first == HOUR

        fired = []
        now = first - 5 * MINUTE
        while now <= second + 5 * MINUTE:
            fired += tick(session, now).fired
            now += MINUTE

        assert [alert.due_at for alert in fired] == [first]
        assert len(feed_alerts(session, jar)) == 1

    def test_the_predicted_peak_is_real_hours_not_clock_hours(self, session):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 10, 31, 20)
        feed(session, jar, fed)

        made = plan_service.jar_plan(session, jar, now=fed + HOUR, until=fed + 3 * 24 * HOUR)

        assert made.last_cycle.peak_at - fed == timedelta(hours=made.last_cycle.peak_h)


class TestALateFeedOnAChangeoverNight:
    """Keeping your usual times, or shifting to the new one, is offered after
    a late feed. Both are 'the next one, a cycle on' — on the clock."""

    def _late(self, session, jar, fed_at):
        return plan_service.LateFeed(planned_at=local(2026, 10, 31, 20), fed_at=fed_at)

    def test_keeping_the_usual_times_keeps_them_on_the_clock(self, session):
        jar = make_jar(session, feeds_per_day=2)
        late = self._late(session, jar, local(2026, 10, 31, 23))

        anchor = plan_service.keep_usual_times(session, jar, late=late)

        assert on_clock(anchor) == "Sun 08:00"

    def test_shifting_the_schedule_moves_it_by_the_clock_too(self, session):
        jar = make_jar(session, feeds_per_day=2)
        late = self._late(session, jar, local(2026, 10, 31, 23))

        anchor = plan_service.shift_schedule(session, jar, late=late)

        assert on_clock(anchor) == "Sun 11:00"


# ========================================================================
# The kitchen moves
# ========================================================================


class TestChangingTheTimezone:
    def test_what_is_stored_does_not_move(self, session, in_zone):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)

        in_zone("Europe/London")
        session.expire_all()

        assert last_feeding(session, jar.id).fed_at == fed

    def test_the_same_instant_is_shown_on_the_new_clock(self, session, in_zone):
        fed = local(2026, 6, 10, 8)
        assert local_dt(fed, "%H:%M") == "08:00"

        in_zone("Europe/London")

        assert local_dt(fed, "%H:%M") == "13:00"

    def test_a_pending_alert_is_neither_dropped_nor_duplicated(self, session, in_zone):
        """The feed that was due at eight in New York is due at the same
        instant in London. Reconciling after the move must not treat it as a
        different alert."""
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        tick(session, fed + HOUR)
        (before,) = feed_alerts(session, jar)

        in_zone("Europe/London")
        result = tick(session, fed + 2 * HOUR)

        assert not result.changed
        (after,) = feed_alerts(session, jar)
        assert after.id == before.id
        assert after.due_at == local(2026, 6, 10, 20)

    def test_an_alert_that_was_showing_is_still_showing(self, session, in_zone):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        tick(session, fed + 12 * HOUR)

        in_zone("Asia/Tokyo")
        later = fed + 13 * HOUR
        tick(session, later)

        assert [a.jar_id for a in alert_service.showing(session, later)] == [jar.id]

    def test_the_rhythm_follows_the_new_zone_s_clock_changes(self, session, in_zone):
        """London changes on 29 March, three weeks after New York. A jar
        that has moved there keeps London's eight o'clock, and New York's
        change on the 8th means nothing to it."""
        london = in_zone("Europe/London")
        jar = make_jar(session, feeds_per_day=1)
        plan_service.move_next_feed(
            session, jar,
            to=local(2026, 3, 6, 8, tz=london), now=local(2026, 3, 6, 6, tz=london),
        )
        session.commit()

        over_new_yorks = planned(session, jar, local(2026, 3, 7, 9, tz=london), days=3)
        over_londons = planned(session, jar, local(2026, 3, 28, 9, tz=london), days=3)

        assert {on_clock(at, london)[4:] for at in over_new_yorks} == {"08:00"}
        assert {on_clock(at, london)[4:] for at in over_londons} == {"08:00"}
        # The first is the feed still owed from the 6th; the rhythm is the rest.
        upcoming = over_londons[1:]
        assert [on_clock(at, london) for at in upcoming] == [
            "Sun 08:00", "Mon 08:00", "Tue 08:00",
        ]
        gaps = [b - a for a, b in zip([local(2026, 3, 28, 8, tz=london), *upcoming], upcoming)]
        assert timedelta(hours=23) in gaps

    def test_a_zone_with_no_clock_changes_never_shifts(self, session, in_zone):
        tokyo = in_zone("Asia/Tokyo")
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 3, 7, 8, tz=tokyo))

        slots = planned(session, jar, local(2026, 3, 7, 9, tz=tokyo), days=3)

        assert {b - a for a, b in zip(slots, slots[1:])} == {timedelta(hours=12)}

    def test_a_half_hour_zone(self, session, in_zone):
        kolkata = in_zone("Asia/Kolkata")
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 6, 10, 21, 15, tz=kolkata))

        moment = due(session, jar, local(2026, 6, 10, 22, tz=kolkata))

        assert on_clock(moment, kolkata) == "Thu 09:15"


# ========================================================================
# The ribbon
# ========================================================================


def draw(session, jars, now, span_h=48):
    drawn, plans = plan_service.build_ribbon(
        session, jars, now=now, tz=get_settings().tz, span_h=span_h
    )
    return drawn, plans


def x_at(drawn, moment: datetime) -> float:
    """Where a moment belongs on this ribbon, worked out independently."""
    fraction = (moment - drawn.start) / (drawn.end - drawn.start)
    return drawn.plot.x + fraction * drawn.plot.w


class TestTheRibbonAgreesWithTheAlert:
    """One moment, three places: the mark on the ribbon, the time on the
    card and the alert. Moving a feed has to move all three or none."""

    def _three(self, session, jar, now):
        tick(session, now)
        drawn, plans = draw(session, [jar], now)
        mark = drawn.rows[0].planned[0]
        card = jar_service.jar_card(session, jar, now)
        pending = [a for a in feed_alerts(session, jar) if a.is_pending]
        return drawn, mark, card, pending, plans[jar.id]

    @pytest.mark.parametrize("per_day", [1, 2])
    def test_they_all_name_the_same_moment(self, session, per_day):
        jar = make_jar(session, feeds_per_day=per_day)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        now = fed + 2 * HOUR

        drawn, mark, card, pending, made = self._three(session, jar, now)

        expected = fed + timedelta(hours=24 / per_day)
        assert mark.mark.at == expected
        assert card.status.next_due_at == expected
        assert made.next_feed_at == expected
        assert [a.due_at for a in pending] == [expected]

    @pytest.mark.parametrize("per_day", [1, 2])
    def test_the_mark_is_drawn_where_that_moment_is(self, session, per_day):
        jar = make_jar(session, feeds_per_day=per_day)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)

        drawn, mark, *_ = self._three(session, jar, fed + 2 * HOUR)

        assert mark.x == pytest.approx(x_at(drawn, mark.mark.at))

    @pytest.mark.parametrize("minutes", plan_service.NUDGES)
    def test_nudging_the_feed_moves_all_three_together(self, session, minutes):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        now = fed + 2 * HOUR
        drawn_before, before, *_ = self._three(session, jar, now)

        plan_service.shift_next_feed(
            session, jar, by=timedelta(minutes=minutes), now=now,
            until=now + timedelta(days=3),
        )
        session.commit()
        drawn, mark, card, pending, _ = self._three(session, jar, now)

        moved_to = before.mark.at + timedelta(minutes=minutes)
        assert mark.mark.at == moved_to
        assert card.status.next_due_at == moved_to
        assert [a.due_at for a in pending] == [moved_to]
        per_minute = drawn.plot.w / ((drawn.end - drawn.start) / MINUTE)
        assert mark.x - before.x == pytest.approx(minutes * per_minute)

    def test_the_alert_for_the_old_time_is_gone(self, session):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        now = fed + 2 * HOUR
        tick(session, now)

        plan_service.move_next_feed(session, jar, to=local(2026, 6, 10, 22, 15), now=now)
        session.commit()
        result = tick(session, now)

        assert result.dropped == 1
        assert [on_clock(a.due_at) for a in feed_alerts(session, jar)] == ["Wed 22:15"]

    def test_every_later_feed_follows_the_one_that_moved(self, session):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        now = fed + 2 * HOUR

        plan_service.move_next_feed(session, jar, to=local(2026, 6, 10, 22, 15), now=now)
        session.commit()
        drawn, _ = draw(session, [jar], now)

        marks = drawn.rows[0].planned
        assert [on_clock(m.mark.at) for m in marks] == [
            "Wed 22:15", "Thu 10:15", "Thu 22:15",
        ]
        for one in marks:
            assert one.x == pytest.approx(x_at(drawn, one.mark.at))

    def test_two_jars_on_one_axis_line_up(self, session):
        """A daily jar and a twice-daily one, fed together: where their
        feeds coincide, the two marks are one above the other."""
        daily = make_jar(session, feeds_per_day=1, name="Daily")
        twice = make_jar(session, feeds_per_day=2, name="Twice", is_control=True)
        fed = local(2026, 6, 10, 8)
        feed(session, daily, fed)
        feed(session, twice, fed)

        drawn, _ = draw(session, [daily, twice], fed + 2 * HOUR)

        by_name = {row.name: {m.mark.at: m.x for m in row.planned} for row in drawn.rows}
        shared = set(by_name["Daily"]) & set(by_name["Twice"])
        assert local(2026, 6, 11, 8) in shared
        for moment in shared:
            assert by_name["Daily"][moment] == pytest.approx(by_name["Twice"][moment])

    def test_moving_one_jar_leaves_the_other_where_it_was(self, session):
        daily = make_jar(session, feeds_per_day=1, name="Daily")
        twice = make_jar(session, feeds_per_day=2, name="Twice")
        fed = local(2026, 6, 10, 8)
        feed(session, daily, fed)
        feed(session, twice, fed)
        now = fed + 2 * HOUR
        before, _ = draw(session, [daily, twice], now)

        plan_service.shift_next_feed(
            session, twice, by=timedelta(minutes=60), now=now,
            until=now + timedelta(days=3),
        )
        session.commit()
        after, _ = draw(session, [daily, twice], now)

        def marks(drawn, name):
            row = next(r for r in drawn.rows if r.name == name)
            return [(m.mark.at, m.x) for m in row.planned]

        assert marks(after, "Daily") == marks(before, "Daily")
        assert marks(after, "Twice") != marks(before, "Twice")

    def test_an_overdue_feed_is_drawn_at_the_moment_the_alert_names(self, session):
        jar = make_jar(session, feeds_per_day=2)
        fed = local(2026, 6, 10, 8)
        feed(session, jar, fed)
        now = fed + 15 * HOUR

        drawn, mark, card, _, _ = self._three(session, jar, now)

        (showing,) = alert_service.showing(session, now)
        assert mark.mark.at == showing.due_at == card.status.next_due_at
        assert mark.x < drawn.now_x


class TestTheRibbonAcrossAClockChange:
    @pytest.mark.parametrize(
        "saturday, sunday",
        [((2026, 3, 7), (2026, 3, 8)), ((2026, 10, 31), (2026, 11, 1))],
        ids=["spring-forward", "fall-back"],
    )
    def test_the_noon_feed_sits_on_the_noon_tick(self, session, saturday, sunday):
        """The axis is labelled in clock time and the feeds are planned in
        clock time. If either were an hour out after the change, the mark
        for noon would stand beside the tick for noon instead of on it."""
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(*saturday, 12))
        now = local(*saturday, 14)

        drawn, _ = draw(session, [jar], now, span_h=48)

        sunday_noon = local(*sunday, 12)
        mark = next(m for m in drawn.rows[0].planned if m.mark.at == sunday_noon)
        tick_ = next(t for t in drawn.ticks if t.at == sunday_noon)
        assert tick_.label == "12:00"
        assert mark.x == pytest.approx(tick_.x)

    @pytest.mark.parametrize(
        "saturday", [(2026, 3, 7), (2026, 10, 31)], ids=["spring-forward", "fall-back"]
    )
    def test_the_axis_itself_is_real_time(self, session, saturday):
        """Marks are placed by elapsed time, so the short night is drawn
        short and the long one long: nothing is stretched to look even."""
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(*saturday, 12))

        drawn, _ = draw(session, [jar], local(*saturday, 14), span_h=48)

        for one in drawn.rows[0].planned:
            assert one.x == pytest.approx(x_at(drawn, one.mark.at))
        assert drawn.now_x == pytest.approx(x_at(drawn, drawn.now))

    def test_midnight_ticks_stay_at_midnight(self, session):
        jar = make_jar(session, feeds_per_day=2)
        feed(session, jar, local(2026, 10, 31, 12))

        drawn, _ = draw(session, [jar], local(2026, 10, 31, 14), span_h=72)

        day_starts = [t.at for t in drawn.ticks if t.is_day_start]
        assert day_starts == [local(2026, 11, 1), local(2026, 11, 2), local(2026, 11, 3)]
        assert day_starts[1] - day_starts[0] == timedelta(hours=25)


# ========================================================================
# Bake day
# ========================================================================


def _version(session, flour: float = 500.0) -> RecipeVersion:
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=flour)
    session.add(version)
    session.flush()
    session.add(
        RecipeIngredient(
            version_id=version.id, seq=0, name="whole rye flour",
            role=IngredientRole.FLOUR, baker_pct=100.0,
        )
    )
    session.commit()
    return version


def make_plan(session, *, start=None, ready_by=None, now=None,
              method=BakeMethod.DUTCH_OVEN, version=None):
    version = version or _version(session)
    now = now or start or ready_by - timedelta(days=1)
    made, specs, workable = bakeplan.build(
        session,
        version=version,
        jar=None,
        inputs=PlanInputs(
            total_flour_g=500.0, start_at=start, ready_by=ready_by, method=method
        ),
        now=now,
        tz=get_settings().tz,
    )
    return version, made, specs, workable


def make_bake(session, *, start, now=None, method=BakeMethod.DUTCH_OVEN, lead=None):
    """A bake written down from a plan, the way /plan writes one down."""
    version, made, _, _ = make_plan(session, start=start, now=now or start, method=method)
    bake = followalong.start_from_plan(
        session,
        version=version,
        plan=made,
        now=now or start,
        method=method,
        oven_temp_c=246.1,
        total_flour_g=500.0,
        preheat_lead_min=lead,
    )
    session.commit()
    return bake


def step(bake, key: str) -> BakeStageLog:
    return next(log for log in bake.stage_logs if log.step_key == key)


def stage_alerts(session, kind=AlertKind.STAGE_DUE) -> list[Alert]:
    return list(
        session.scalars(select(Alert).where(Alert.kind == kind).order_by(Alert.due_at))
    )


def sleep_block(session, start="23:00", end="07:00"):
    h, m = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    block = BusyBlock(
        label="Sleep", kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
        start_minute=h * 60 + m, end_minute=eh * 60 + em,
    )
    session.add(block)
    session.commit()
    return block


CHANGEOVERS = pytest.mark.parametrize(
    "saturday, sunday, shift",
    [
        ((2026, 6, 13), (2026, 6, 14), timedelta(0)),
        ((2026, 3, 7), (2026, 3, 8), -HOUR),
        ((2026, 10, 31), (2026, 11, 1), +HOUR),
    ],
    ids=["ordinary-night", "spring-forward", "fall-back"],
)


class TestTheBakeDayTimeline:
    @CHANGEOVERS
    def test_one_step_ends_where_the_next_begins(self, session, saturday, sunday, shift):
        _, made, _, _ = make_plan(session, start=local(*saturday, 18))

        for before, after in zip(made.steps, made.steps[1:]):
            assert before.end == after.start
        assert made.steps[0].start == made.start
        assert made.steps[-1].end == made.end

    @CHANGEOVERS
    def test_every_step_lasts_as_long_as_it_takes(self, session, saturday, sunday, shift):
        """A plan started on Saturday evening runs through the changeover.
        Its steps are durations: none of them gains or loses the hour."""
        _, made, specs, _ = make_plan(session, start=local(*saturday, 18))

        for laid, spec in zip(made.steps, specs):
            assert laid.end - laid.start == timedelta(minutes=spec.duration_min)
        assert made.end - made.start == timedelta(minutes=bakeplan.chain_minutes(specs))

    @CHANGEOVERS
    def test_the_clock_at_the_end_shows_the_hour_that_changed(
        self, session, saturday, sunday, shift
    ):
        """The same plan started at the same clock time finishes an hour
        later by the clock after spring forward and an hour earlier after
        fall back: the bread is ready when it is ready."""
        _, ordinary, _, _ = make_plan(session, start=local(2026, 6, 13, 18))
        _, made, _, _ = make_plan(session, start=local(*saturday, 18))

        def clock(moment):
            return moment.astimezone(NY).replace(tzinfo=None)

        usual = clock(ordinary.end) - clock(ordinary.start)
        this_night = clock(made.end) - clock(made.start)
        assert this_night - usual == -shift

    @CHANGEOVERS
    def test_bread_asked_for_at_nine_is_ready_at_nine(self, session, saturday, sunday, shift):
        ready = local(*sunday, 9)

        _, made, specs, _ = make_plan(session, ready_by=ready, now=local(*saturday, 8))

        assert made.end == ready
        assert on_clock(made.end) == "Sun 09:00"
        assert made.start == ready - timedelta(minutes=bakeplan.chain_minutes(specs))

    @CHANGEOVERS
    def test_planning_backward_is_planning_forward_from_earlier(
        self, session, saturday, sunday, shift
    ):
        version, back, _, _ = make_plan(
            session, ready_by=local(*sunday, 9), now=local(*saturday, 8)
        )
        _, fwd, _, _ = make_plan(
            session, start=back.start, now=local(*saturday, 8), version=version
        )

        assert [(s.key, s.start, s.end) for s in fwd.steps] == [
            (s.key, s.start, s.end) for s in back.steps
        ]

    @CHANGEOVERS
    def test_the_plan_knows_what_is_on_at_any_moment(self, session, saturday, sunday, shift):
        _, made, _, _ = make_plan(session, start=local(*saturday, 18))

        for laid in made.steps:
            middle = laid.start + (laid.end - laid.start) / 2
            assert made.at(middle).key == laid.key

    @CHANGEOVERS
    def test_written_down_the_steps_still_join_up(self, session, saturday, sunday, shift):
        bake = make_bake(session, start=local(*saturday, 18))

        logs = list(bake.stage_logs)
        for before, after in zip(logs, logs[1:]):
            assert before.planned_end == after.planned_start
        assert all(log.planned_start.second == 0 for log in logs)

    @CHANGEOVERS
    def test_the_bars_are_drawn_where_their_times_are(self, session, saturday, sunday, shift):
        _, made, _, _ = make_plan(session, start=local(*saturday, 18))
        start, end = made.start - HOUR, made.end + HOUR

        drawn = ribbon.timeline(
            made.steps, start=start, end=end, now=made.start, tz=NY
        )

        def x(moment):
            return drawn.plot.x + (moment - start) / (end - start) * drawn.plot.w

        assert [bar.key for bar in drawn.bars] == [s.key for s in made.steps]
        for bar, laid in zip(drawn.bars, made.steps):
            assert bar.x1 == pytest.approx(x(laid.start))
            assert bar.x2 == pytest.approx(x(laid.end))
        for before, after in zip(drawn.bars, drawn.bars[1:]):
            assert before.x2 == pytest.approx(after.x1)

    def test_sleep_is_an_hour_shorter_on_the_spring_night(self, session):
        """23:00 to 07:00 is seven hours on 8 March. A step at 07:10 is
        clear of it; one in the small hours is not."""
        sleep_block(session)
        _, made, specs, _ = make_plan(session, start=local(2026, 3, 7, 18))

        in_the_night = bakeplan.lay_out(
            specs, local(2026, 3, 8, 3, 30),
            busy=_busy(session, local(2026, 3, 7, 12), local(2026, 3, 9, 12)),
        )
        after_waking = bakeplan.lay_out(
            specs, local(2026, 3, 8, 7, 10),
            busy=_busy(session, local(2026, 3, 7, 12), local(2026, 3, 9, 12)),
        )

        assert in_the_night.steps[0].clashes
        assert not after_waking.steps[0].clashes

    def test_sleep_is_an_hour_longer_on_the_autumn_night(self, session):
        """On 1 November there are two 01:30s and both of them are asleep."""
        sleep_block(session)
        _, _, specs, _ = make_plan(session, start=local(2026, 10, 31, 18))
        busy = _busy(session, local(2026, 10, 31, 12), local(2026, 11, 2, 12))

        for moment in (
            local(2026, 11, 1, 1, 30, fold=0),
            local(2026, 11, 1, 1, 30, fold=1),
            local(2026, 11, 1, 6, 50),
        ):
            assert bakeplan.lay_out(specs, moment, busy=busy).steps[0].clashes
        assert not bakeplan.lay_out(
            specs, local(2026, 11, 1, 7, 10), busy=busy
        ).steps[0].clashes

    def test_the_time_it_suggests_instead_is_a_time_you_are_up(self, session):
        sleep_block(session)

        _, made, specs, workable = make_plan(
            session, start=local(2026, 10, 31, 23, 30), now=local(2026, 10, 31, 20)
        )

        assert not made.works
        assert workable is not None
        assert workable.plan.works
        assert workable.start.astimezone(NY).minute % 15 == 0


def _busy(session, start, end):
    from app.services import busy as busy_service

    return busy_service.busy_intervals(session, start, end, NY)


# --- Step alerts --------------------------------------------------------


class TestStepAlerts:
    """Stretch-and-folds, shaping, loading: the hands-on steps ring when the
    work starts. The long waits ring when they end.

    Sets of stretch-and-folds have alerts of their own, part-way through a
    bulk ferment: see TestFoldSets further down.
    """

    def test_a_hands_on_step_rings_as_it_starts(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        shaping = step(bake, "shape")
        assert shaping.hands_on

        assert shaping.planned_start in followalong.stage_due_moments(shaping)

    def test_a_short_hands_on_step_does_not_ring_again_as_it_ends(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        shaping = step(bake, "shape")

        assert followalong.stage_due_moments(shaping) == (shaping.planned_start,)

    def test_a_long_wait_rings_when_it_is_over(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        proof = step(bake, "final_rise")

        assert followalong.stage_due_moments(proof) == (proof.planned_end,)

    def test_a_step_you_need_not_be_there_for_does_not_ring(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))

        assert followalong.stage_due_moments(step(bake, "cool")) == ()

    def test_the_folding_hints_ride_on_a_bulk_step(self):
        """Where a recipe has a bulk ferment, its stretch-and-fold guidance
        is found by that step — as words, not as alerts of their own."""
        places = hint_service.places_for(None, "bulk ferment")

        assert any("bulk" in place for place in places)

    @CHANGEOVERS
    def test_they_fire_at_their_planned_instants_through_the_night(
        self, session, saturday, sunday, shift
    ):
        bake = make_bake(session, start=local(*saturday, 18))
        wanted = sorted(
            moment
            for log in bake.stage_logs
            for moment in followalong.stage_due_moments(log)
        )
        assert wanted[0] < local(*sunday, 0) < wanted[-1], "must cross midnight"

        fired: list[datetime] = []
        now = local(*saturday, 17, 55)
        while now <= wanted[-1] + 5 * MINUTE:
            for alert in tick(session, now).fired:
                if alert.kind is AlertKind.STAGE_DUE:
                    # Fired on the very minute it was due, not the tick after.
                    assert alert.due_at == now
                    fired.append(alert.due_at)
            now += MINUTE

        assert fired == wanted

    @CHANGEOVERS
    def test_a_five_hour_proof_is_five_hours(self, session, saturday, sunday, shift):
        """Started so that it spans the changeover. The alert for its end
        comes five hours of proving later; the clock reads four or six."""
        bake = make_bake(session, start=local(*saturday, 14))
        proof = step(bake, "final_rise")
        assert proof.planned_start < local(*sunday, 1, 59) < proof.planned_end

        tick(session, proof.planned_start)
        (end_alert,) = [
            a for a in stage_alerts(session) if a.stage_log_id == proof.id
        ]

        assert end_alert.due_at - proof.planned_start == timedelta(minutes=300)
        clock_hours = (
            end_alert.due_at.astimezone(NY).replace(tzinfo=None)
            - proof.planned_start.astimezone(NY).replace(tzinfo=None)
        )
        assert clock_hours == timedelta(hours=5) - shift

    def test_replanning_after_a_late_start_moves_every_later_alert(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        tick(session, local(2026, 6, 13, 18))
        before = {a.stage_log_id: a.due_at for a in stage_alerts(session) if a.is_pending}

        late = local(2026, 6, 13, 18, 40)
        first = bake.stage_logs[0]
        first.actual_start = late
        followalong.replan(session, bake, now=late)
        session.commit()
        tick(session, late)

        after = {a.stage_log_id: a.due_at for a in stage_alerts(session) if a.is_pending}
        moved = {key for key in before if key in after and after[key] != before[key]}
        assert moved, "nothing moved"
        assert {after[key] - before[key] for key in moved} == {timedelta(minutes=40)}

    def test_changing_timezone_mid_bake_moves_nothing(self, session, in_zone):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        tick(session, local(2026, 6, 13, 18))
        before = [(a.id, a.due_at) for a in stage_alerts(session)]

        in_zone("Europe/London")
        result = tick(session, local(2026, 6, 13, 18, 1))

        assert result.created == [] and result.dropped == 0
        assert [(a.id, a.due_at) for a in stage_alerts(session)] == before


# --- The cast-iron preheat ----------------------------------------------


class TestThePotPreheat:
    def test_the_default_is_three_quarters_of_an_hour(self, session):
        assert settings_store.preheat_pot_min(session) >= 45

        bake = make_bake(session, start=local(2026, 6, 13, 18))

        assert step(bake, "bake").preheat_lead_min >= 45

    def test_a_setting_nobody_offered_falls_back_to_at_least_that(self, session):
        for nonsense in ("5", "0", "-45", "soon", ""):
            settings_store.set_setting(session, "preheat_pot_min", nonsense)
            session.commit()

            assert settings_store.preheat_pot_min(session) >= 45

    def test_the_longest_choice_is_longer_still(self):
        assert max(PREHEAT_POT_CHOICES) >= 60
        assert 45 in PREHEAT_POT_CHOICES

    @CHANGEOVERS
    def test_the_oven_goes_on_that_many_real_minutes_before_the_loaf(
        self, session, saturday, sunday, shift
    ):
        bake = make_bake(session, start=local(*saturday, 14))
        baking = step(bake, "bake")
        lead = timedelta(minutes=baking.preheat_lead_min)

        tick(session, local(*saturday, 14))
        (alert,) = stage_alerts(session, AlertKind.PREHEAT_DUE)

        assert alert.due_at == baking.planned_start - lead
        assert lead >= timedelta(minutes=45)

    @CHANGEOVERS
    def test_it_fires_then_and_the_bake_alert_fires_after_the_full_lead(
        self, session, saturday, sunday, shift
    ):
        bake = make_bake(session, start=local(*saturday, 14))
        baking = step(bake, "bake")
        preheat_at = baking.planned_start - timedelta(minutes=baking.preheat_lead_min)

        assert not [
            a for a in tick(session, preheat_at - MINUTE).fired
            if a.kind is AlertKind.PREHEAT_DUE
        ]
        fired = tick(session, preheat_at).fired
        assert [a.kind for a in fired if a.stage_log_id == baking.id] == [
            AlertKind.PREHEAT_DUE
        ]

        fired_later = tick(session, baking.planned_start).fired
        into_the_oven = [
            a for a in fired_later
            if a.kind is AlertKind.STAGE_DUE and a.stage_log_id == baking.id
        ]
        assert len(into_the_oven) == 1
        assert into_the_oven[0].due_at - preheat_at >= timedelta(minutes=45)

    def test_a_preheat_that_straddles_the_spring_change(self, session):
        """Loaf in at 03:10 on the new clock. Forty-five minutes before that
        is 01:25 on the old one — an hour and three quarters by the clock,
        and still only forty-five minutes of heating."""
        loaf_in = local(2026, 3, 8, 3, 10)
        bake = self._bake_with_loaf_in_at(session, loaf_in)
        baking = step(bake, "bake")

        moment = followalong.preheat_moment(baking)

        assert baking.planned_start == loaf_in
        assert loaf_in - moment == timedelta(minutes=45)
        assert on_clock(moment) == "Sun 01:25"

    def test_a_preheat_that_straddles_the_autumn_change(self, session):
        """Loaf in at 01:20, the second time round. The oven goes on at
        01:35 the first time: later by the clock, earlier in fact."""
        loaf_in = local(2026, 11, 1, 1, 20, fold=1)
        bake = self._bake_with_loaf_in_at(session, loaf_in)
        baking = step(bake, "bake")

        moment = followalong.preheat_moment(baking)

        assert loaf_in - moment == timedelta(minutes=45)
        assert moment == local(2026, 11, 1, 1, 35, fold=0)

    def test_a_loaf_going_in_just_after_midnight(self, session):
        loaf_in = local(2026, 6, 14, 0, 20)
        bake = self._bake_with_loaf_in_at(session, loaf_in)

        moment = followalong.preheat_moment(step(bake, "bake"))

        assert on_clock(moment) == "Sat 23:35"
        assert AlertKind.PREHEAT_DUE not in [
            a.kind for a in tick(session, local(2026, 6, 13, 23, 34)).fired
        ]
        assert AlertKind.PREHEAT_DUE in [
            a.kind for a in tick(session, local(2026, 6, 13, 23, 35)).fired
        ]

    def test_the_bread_maker_is_never_told_to_preheat(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18), method=BakeMethod.BREAD_MAKER)
        tick(session, local(2026, 6, 13, 18))

        assert stage_alerts(session, AlertKind.PREHEAT_DUE) == []

    def _bake_with_loaf_in_at(self, session, loaf_in: datetime):
        version, probe, _, _ = make_plan(session, start=local(2026, 6, 1, 12))
        offset = probe.step("bake").start - probe.start
        # Planned times live on whole minutes, so the start is put on one.
        start = (loaf_in - offset).replace(second=0, microsecond=0)
        now = start - HOUR
        _, made, _, _ = make_plan(session, start=start, now=now, version=version)
        bake = followalong.start_from_plan(
            session, version=version, plan=made, now=now,
            method=BakeMethod.DUTCH_OVEN, oven_temp_c=246.1, total_flour_g=500.0,
        )
        session.commit()
        baking = step(bake, "bake")
        # Rounding each step to the minute can leave the bake step a minute
        # or two off the target; put it exactly there, as a nudge would.
        baking.planned_start = loaf_in
        session.commit()
        return bake


# --- Lid on, lid off ----------------------------------------------------


class TestLidOnLidOff:
    """The pot bake is one step with two halves. The app rings to put the
    loaf in, rings when the lid comes off, and rings to take it out.
    """

    def test_it_rings_to_put_the_loaf_in_and_to_take_it_out(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        baking = step(bake, "bake")

        assert followalong.stage_due_moments(baking) == (
            baking.planned_start,
            baking.planned_end,
        )

    @CHANGEOVERS
    def test_in_and_out_are_the_bake_time_apart(self, session, saturday, sunday, shift):
        bake = make_bake(session, start=local(*saturday, 14))
        baking = step(bake, "bake")

        goes_in, comes_out = followalong.stage_due_moments(baking)

        assert comes_out - goes_in == timedelta(minutes=baking.planned_min)

    def test_the_bake_step_carries_both_halves_guidance(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        baking = step(bake, "bake")

        places = hint_service.places_for(baking.step_key, baking.name)

        assert "bake" in places          # lid on
        assert "bake_open" in places     # lid off

    def test_the_lid_timing_is_told_on_the_pot_s_bake_step(self, session):
        pot = make_bake(session, start=local(2026, 6, 13, 18))
        book = hint_service.HintBook(session)

        said = {hint.id for hint in book.step(step(pot, "bake"), pot)}

        assert "bake-lid-timing" in said

    def test_a_recipe_s_own_covered_and_uncovered_stages_are_told_apart(self):
        covered = hint_service.places_for(None, "bake covered")
        uncovered = hint_service.places_for(None, "bake uncovered")

        assert "bake" in covered and "bake_open" not in covered
        assert uncovered == ("bake_open",)

    def test_the_lid_coming_off_has_an_alert_of_its_own(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        baking = step(bake, "bake")
        tick(session, local(2026, 6, 13, 18))

        (lid,) = stage_alerts(session, AlertKind.LID_OFF_DUE)

        assert lid.stage_log_id == baking.id
        assert lid.due_at == baking.planned_start + timedelta(minutes=20)
        assert len([a for a in stage_alerts(session) if a.stage_log_id == baking.id]) == 2

    def test_it_says_how_long_is_left(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        tick(session, local(2026, 6, 13, 18))
        (lid,) = stage_alerts(session, AlertKind.LID_OFF_DUE)

        assert alert_service.headline(lid) == "Take the lid off — 25 min to go"
        assert lid.subject == "Take the lid off"
        assert lid.url == f"/bakes/{bake.id}"

    def test_it_counts_from_when_the_loaf_really_went_in(self, session):
        """In twelve minutes late, lid off twelve minutes late."""
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        baking = step(bake, "bake")
        tick(session, local(2026, 6, 13, 18))
        went_in = baking.planned_start + timedelta(minutes=12)

        baking.actual_start = went_in
        session.commit()
        result = tick(session, went_in)

        (lid,) = stage_alerts(session, AlertKind.LID_OFF_DUE)
        assert lid.due_at == went_in + timedelta(minutes=20)
        assert result.dropped >= 1

    def test_it_fires_on_its_minute_between_in_and_out(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        baking = step(bake, "bake")
        goes_in, comes_out = followalong.stage_due_moments(baking)
        lid_off = followalong.lid_off_moment(baking)
        assert goes_in < lid_off < comes_out

        early = tick(session, lid_off - MINUTE).fired
        on_time = tick(session, lid_off).fired

        assert AlertKind.LID_OFF_DUE not in [a.kind for a in early]
        assert [a.kind for a in on_time if a.stage_log_id == baking.id] == [
            AlertKind.LID_OFF_DUE
        ]

    def test_taking_the_loaf_out_ends_it(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        baking = step(bake, "bake")
        tick(session, local(2026, 6, 13, 18))

        baking.actual_start = baking.planned_start
        baking.actual_end = baking.planned_start + timedelta(minutes=10)
        session.commit()
        tick(session, baking.actual_end)

        assert followalong.lid_off_moment(baking) is None
        assert [a for a in stage_alerts(session, AlertKind.LID_OFF_DUE) if a.is_pending] == []

    @pytest.mark.parametrize("method", [BakeMethod.OVEN, BakeMethod.BREAD_MAKER])
    def test_a_bake_with_no_lid_gets_none(self, session, method):
        bake = make_bake(session, start=local(2026, 6, 13, 18), method=method)
        tick(session, local(2026, 6, 13, 18))

        assert step(bake, "bake").lid_off_after_min is None
        assert stage_alerts(session, AlertKind.LID_OFF_DUE) == []

    def test_the_setting_decides_when_and_can_turn_it_off(self, session):
        settings_store.set_setting(session, "lid_off_after_min", "30")
        session.commit()
        later = make_bake(session, start=local(2026, 6, 13, 18))
        assert step(later, "bake").lid_off_after_min == 30

        settings_store.set_setting(session, "lid_off_after_min", "0")
        session.commit()
        off = make_bake(session, start=local(2026, 6, 20, 18))
        assert step(off, "bake").lid_off_after_min is None

    def test_changing_the_setting_leaves_a_bake_underway_alone(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))

        settings_store.set_setting(session, "lid_off_after_min", "30")
        session.commit()
        session.refresh(bake)

        assert step(bake, "bake").lid_off_after_min == 20

    @CHANGEOVERS
    def test_twenty_minutes_is_twenty_minutes_on_any_night(
        self, session, saturday, sunday, shift
    ):
        bake = make_bake(session, start=local(*saturday, 14))
        baking = step(bake, "bake")

        assert followalong.lid_off_moment(baking) - baking.planned_start == timedelta(
            minutes=20
        )

    def test_a_lid_that_comes_off_across_the_autumn_change(self, session):
        """Loaf in at 01:50, the first time round. Twenty minutes later the
        clock says 01:10 — and that is when it rings, not at 02:10."""
        bake = make_bake(session, start=local(2026, 10, 31, 14))
        baking = step(bake, "bake")
        baking.planned_start = local(2026, 11, 1, 1, 50, fold=0)
        session.commit()

        moment = followalong.lid_off_moment(baking)

        assert moment == local(2026, 11, 1, 1, 10, fold=1)
        assert AlertKind.LID_OFF_DUE not in [
            a.kind for a in tick(session, moment - MINUTE).fired
        ]
        assert AlertKind.LID_OFF_DUE in [a.kind for a in tick(session, moment).fired]

    def test_a_recipe_that_splits_the_bake_itself_gets_no_extra_reminder(self, session):
        """Covered and uncovered as two stages: the change of stage is the
        reminder, and a second one would be noise."""
        bake = recipe_bake(
            session,
            [("bake covered", 20), ("bake uncovered", 25)],
            method=BakeMethod.DUTCH_OVEN,
        )

        assert [log.lid_off_after_min for log in bake.stage_logs] == [None, None]

    def test_a_recipe_s_single_bake_stage_gets_one_once_it_is_started(self, session):
        bake = recipe_bake(session, [("bake", 45)], method=BakeMethod.DUTCH_OVEN)
        (baking,) = bake.stage_logs
        assert followalong.lid_off_moment(baking) is None   # no start yet

        went_in = local(2026, 6, 13, 19)
        bake_service.start_stage(session, bake, baking, went_in)
        session.commit()
        tick(session, went_in)

        (lid,) = stage_alerts(session, AlertKind.LID_OFF_DUE)
        assert lid.due_at == went_in + timedelta(minutes=20)


# --- Stretch-and-folds --------------------------------------------------


def recipe_bake(session, stages, *, method=BakeMethod.DUTCH_OVEN):
    """A bake started straight from a recipe, whose stages are its steps."""
    recipe = recipe_service.create_recipe(
        session, name="Country loaf", category=RecipeCategory.WHEAT,
        ingredients=[
            IngredientSpec("Bread flour", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 75.0),
        ],
        stages=[StageSpec(name, duration_min=minutes) for name, minutes in stages],
    )
    session.commit()
    bake = bake_service.start_bake(
        session, recipe.versions[-1], method=method,
        started_at=local(2026, 6, 13, 12), status=BakeStatus.IN_PROGRESS,
    )
    session.commit()
    return bake


def bulk_of(bake) -> BakeStageLog:
    return next(log for log in bake.stage_logs if "bulk" in log.name)


class TestFoldSets:
    """Four sets, half an hour apart, from when the bulk began — unless the
    settings say otherwise, or the bulk is too short to hold them."""

    STAGES = [("autolyse", 30), ("bulk ferment", 270), ("shape", 10), ("bake", 45)]

    def _started(self, session, minutes=270, at=None):
        stages = [(n, minutes if n == "bulk ferment" else m) for n, m in self.STAGES]
        bake = recipe_bake(session, stages)
        bulk = bulk_of(bake)
        began = at or local(2026, 6, 13, 13)
        bake_service.start_stage(session, bake, bulk, began)
        session.commit()
        return bake, bulk, began

    def test_the_bulk_step_carries_the_sets_and_the_spacing(self, session):
        bake = recipe_bake(session, self.STAGES)

        carried = {
            log.name: (log.fold_sets, log.fold_every_min) for log in bake.stage_logs
        }

        assert carried == {
            "autolyse": (None, None),
            "bulk ferment": (4, 30),
            "shape": (None, None),
            "bake": (None, None),
        }

    def test_nothing_is_due_until_the_bulk_has_a_start(self, session):
        bake = recipe_bake(session, self.STAGES)
        tick(session, local(2026, 6, 13, 13))

        assert followalong.fold_moments(bulk_of(bake)) == ()
        assert stage_alerts(session, AlertKind.FOLD_DUE) == []

    def test_four_sets_half_an_hour_apart_from_the_start(self, session):
        _, bulk, began = self._started(session)

        assert followalong.fold_moments(bulk) == tuple(
            began + timedelta(minutes=30 * n) for n in (1, 2, 3, 4)
        )

    def test_each_one_fires_on_its_minute(self, session):
        _, bulk, began = self._started(session)

        fired = []
        now = began
        while now <= began + timedelta(minutes=150):
            fired += [
                (a.due_at - began) // MINUTE
                for a in tick(session, now).fired
                if a.kind is AlertKind.FOLD_DUE
            ]
            now += MINUTE

        assert fired == [30, 60, 90, 120]

    def test_each_one_says_which_set_it_is(self, session):
        _, bulk, began = self._started(session)
        tick(session, began)

        said = [alert_service.headline(a) for a in stage_alerts(session, AlertKind.FOLD_DUE)]

        assert said == [
            "Stretch and fold — set 1 of 4",
            "Stretch and fold — set 2 of 4",
            "Stretch and fold — set 3 of 4",
            "Stretch and fold — set 4 of 4",
        ]

    def test_reconciling_again_and_again_makes_no_more_of_them(self, session):
        _, bulk, began = self._started(session)

        for _ in range(4):
            tick(session, began)

        assert len(stage_alerts(session, AlertKind.FOLD_DUE)) == 4

    def test_a_fold_does_not_sweep_away_the_bulk_s_own_alerts(self, session):
        """Different kinds against one step, each with its own sweep."""
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        proof = step(bake, "final_rise")
        proof.fold_sets, proof.fold_every_min = 2, 30
        session.commit()

        for _ in range(3):
            tick(session, local(2026, 6, 13, 18))

        kinds = sorted(
            a.kind.value
            for a in session.scalars(select(Alert).where(Alert.stage_log_id == proof.id))
        )
        assert kinds == ["fold_due", "fold_due", "stage_due"]

    @pytest.mark.parametrize(
        "bulk_min, expected",
        [(270, 4), (150, 4), (149, 3), (120, 3), (75, 1), (60, 1), (59, 0), (35, 0)],
    )
    def test_a_set_is_only_planned_if_a_rest_follows_it(self, session, bulk_min, expected):
        _, bulk, _ = self._started(session, minutes=bulk_min)

        assert len(followalong.fold_moments(bulk)) == expected

    def test_a_bulk_started_late_is_folded_late(self, session):
        bake = make_bake(session, start=local(2026, 6, 13, 18))
        proof = step(bake, "final_rise")
        proof.fold_sets, proof.fold_every_min = 2, 30
        session.commit()
        tick(session, local(2026, 6, 13, 18))
        planned = [a.due_at for a in stage_alerts(session, AlertKind.FOLD_DUE)]

        late = proof.planned_start + timedelta(minutes=20)
        proof.actual_start = late
        session.commit()
        tick(session, late)

        moved = [a.due_at for a in stage_alerts(session, AlertKind.FOLD_DUE)]
        assert [b - a for a, b in zip(planned, moved)] == [timedelta(minutes=20)] * 2

    def test_ending_the_bulk_early_drops_the_folds_still_to_come(self, session):
        bake, bulk, began = self._started(session)
        tick(session, began + timedelta(minutes=45))   # set 1 has fired

        # What the page does when "done" is tapped: end it, and settle
        # whatever was showing for it.
        bake_service.end_stage(session, bake, bulk, began + timedelta(minutes=50))
        alert_service.acknowledge_for_stage(
            session, bulk.id, began + timedelta(minutes=50)
        )
        session.commit()
        tick(session, began + timedelta(minutes=50))

        left = stage_alerts(session, AlertKind.FOLD_DUE)
        assert [a.is_pending for a in left] == [False]
        assert alert_service.showing(session, began + timedelta(minutes=50)) == []

    def test_a_fold_can_be_snoozed_like_anything_else(self, session):
        _, bulk, began = self._started(session)
        now = began + timedelta(minutes=30)
        tick(session, now)
        (showing,) = alert_service.showing(session, now)

        alert_service.snooze(session, showing, now, 10)
        session.commit()

        assert alert_service.showing(session, now + 5 * MINUTE) == []
        assert alert_service.showing(session, now + 10 * MINUTE) == [showing]

    def test_the_settings_decide_how_many_and_how_far_apart(self, session):
        settings_store.set_setting(session, "fold_sets", "3")
        settings_store.set_setting(session, "fold_every_min", "45")
        session.commit()

        _, bulk, began = self._started(session)

        assert followalong.fold_moments(bulk) == tuple(
            began + timedelta(minutes=45 * n) for n in (1, 2, 3)
        )

    def test_no_sets_means_no_reminders(self, session):
        settings_store.set_setting(session, "fold_sets", "0")
        session.commit()

        _, bulk, began = self._started(session)
        tick(session, began)

        assert bulk.fold_sets is None
        assert stage_alerts(session, AlertKind.FOLD_DUE) == []

    def test_changing_the_setting_leaves_a_bulk_underway_alone(self, session):
        _, bulk, began = self._started(session)

        settings_store.set_setting(session, "fold_sets", "1")
        session.commit()
        session.refresh(bulk)

        assert len(followalong.fold_moments(bulk)) == 4

    def test_a_bake_laid_out_by_the_planner_has_no_bulk_to_fold(self, session):
        """The planner's chain goes from kneading to shaping. Stated so that
        giving it a bulk step is a decision and not a surprise."""
        bake = make_bake(session, start=local(2026, 6, 13, 18))

        assert all(log.fold_sets is None for log in bake.stage_logs)

    def test_a_bulk_through_the_night_folds_across_midnight(self, session):
        _, bulk, began = self._started(session, at=local(2026, 6, 13, 23, 10))

        assert [on_clock(at) for at in followalong.fold_moments(bulk)] == [
            "Sat 23:40", "Sun 00:10", "Sun 00:40", "Sun 01:10",
        ]

    def test_thirty_minutes_is_thirty_minutes_when_the_clocks_go_forward(self, session):
        _, bulk, began = self._started(session, at=local(2026, 3, 8, 1, 10))

        moments = followalong.fold_moments(bulk)

        assert [on_clock(at) for at in moments] == [
            "Sun 01:40", "Sun 03:10", "Sun 03:40", "Sun 04:10",
        ]
        assert {b - a for a, b in zip((began, *moments), moments)} == {
            timedelta(minutes=30)
        }

    def test_and_when_they_go_back(self, session):
        _, bulk, began = self._started(session, at=local(2026, 11, 1, 0, 40))

        moments = followalong.fold_moments(bulk)

        assert [on_clock(at) for at in moments] == [
            "Sun 01:10", "Sun 01:40", "Sun 01:10", "Sun 01:40",
        ]
        assert len(set(moments)) == 4
        fired = []
        now = began
        while now <= moments[-1]:
            fired += [a.due_at for a in tick(session, now).fired]
            now += MINUTE
        assert fired == list(moments)

    def test_moving_the_kitchen_mid_bulk_moves_nothing(self, session, in_zone):
        _, bulk, began = self._started(session)
        tick(session, began)
        before = [(a.id, a.due_at) for a in stage_alerts(session, AlertKind.FOLD_DUE)]

        in_zone("Europe/London")
        result = tick(session, began + MINUTE)

        assert not result.changed
        assert [(a.id, a.due_at) for a in stage_alerts(session, AlertKind.FOLD_DUE)] == before


class TestTheRemindersSettings:
    def test_the_page_offers_them(self, client):
        body = client.get("/settings").text

        assert 'action="/settings/reminders"' in body
        for name in ("fold_sets", "fold_every_min", "lid_off_after_min"):
            assert f'name="{name}"' in body

    def test_saving_them(self, client, session):
        response = client.post(
            "/settings/reminders",
            data={"fold_sets": "3", "fold_every_min": "45", "lid_off_after_min": "25"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert settings_store.fold_sets(session) == 3
        assert settings_store.fold_every_min(session) == 45
        assert settings_store.lid_stays_on_min(session) == 25

    def test_turning_both_off(self, client, session):
        client.post(
            "/settings/reminders", data={"fold_sets": "0", "lid_off_after_min": "0"}
        )

        assert settings_store.fold_sets(session) == 0
        assert settings_store.lid_off_after_min(session, BakeMethod.DUTCH_OVEN) is None

    @pytest.mark.parametrize(
        "field, value",
        [("fold_sets", "9"), ("fold_every_min", "7"), ("lid_off_after_min", "90")],
    )
    def test_a_value_that_was_not_offered_is_refused(self, client, session, field, value):
        response = client.post("/settings/reminders", data={field: value})

        assert response.status_code == 400
        assert settings_store.fold_sets(session) == 4
        assert settings_store.fold_every_min(session) == 30
        assert settings_store.lid_stays_on_min(session) == 20

    def test_the_banner_shows_a_fold_with_its_set_number(self, client, session):
        bake = recipe_bake(session, TestFoldSets.STAGES)
        bulk = bulk_of(bake)
        began = utcnow() - timedelta(minutes=31)
        bake_service.start_stage(session, bake, bulk, began)
        session.commit()
        tick(session, utcnow())

        body = client.get("/").text

        assert "Stretch and fold — set 1 of 4" in body

    def test_the_running_sheet_says_when_the_folds_and_the_lid_are(self, client, session):
        bake = recipe_bake(session, TestFoldSets.STAGES)
        bulk = bulk_of(bake)

        waiting = client.get(f"/bakes/{bake.id}").text
        assert "4 sets of folds, 30 min apart" in waiting
        assert "Lid off 20 min after the loaf goes in" in waiting

        began = local(2026, 6, 13, 13)
        bake_service.start_stage(session, bake, bulk, began)
        session.commit()

        assert "Stretch and fold at\n      13:30, 14:00, 14:30, 15:00" in client.get(
            f"/bakes/{bake.id}"
        ).text
