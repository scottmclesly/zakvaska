"""The preheat heads-up: turn the oven on before the bake, not at it.

A lidded cast-iron pot wants three quarters of an hour in the oven before
the loaf goes in, and that preheat runs *alongside* the final proof rather
than after it. So it cannot be a step in the chain — a 45-minute step
inserted before the bake would push the bake, and everything after it, back
by 45 minutes. It is a lead time on the bake step instead, which
`followalong.preheat_moment` turns into a moment and reconcile turns into an
alert of its own kind.

What these pin down, in the order the feature was asked for: the moment for
planned and for actual times, that it follows the bake step wherever that
goes, that the bread maker gets nothing, that the setting is obeyed, that
reconcile creates the alert and drops it again, and the words it says.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.alert import Alert
from app.models.bake import BakeStageLog
from app.models.enums import (
    AlertKind,
    BakeMethod,
    BakeStatus,
    IngredientRole,
    JarOrigin,
)
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.services import alerts as alert_service
from app.services import bakeplan, followalong, settings_store
from app.services.bakeplan import PlanInputs

TZ = ZoneInfo("America/New_York")

#: 475 °F, the temperature Scott's pot bakes at, held in Celsius as always.
POT_TEMP_C = 246.1


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


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


def _bake(
    session,
    *,
    method: BakeMethod = BakeMethod.DUTCH_OVEN,
    start: datetime | None = None,
    now: datetime | None = None,
    temp_c: float | None = POT_TEMP_C,
    lead: int | None = None,
):
    """A bake written down from a plan, the way /plan writes one down."""
    version = _version(session)
    start = start or _at(16, 14)
    now = now or start
    made, _, _ = bakeplan.build(
        session,
        version=version,
        jar=None,
        inputs=PlanInputs(total_flour_g=500.0, start_at=start, method=method),
        now=now,
        tz=TZ,
    )
    bake = followalong.start_from_plan(
        session,
        version=version,
        plan=made,
        now=now,
        method=method,
        oven_temp_c=temp_c,
        total_flour_g=500.0,
        preheat_lead_min=lead,
    )
    session.commit()
    return bake


def _step(bake, key: str) -> BakeStageLog:
    return next(log for log in bake.stage_logs if log.step_key == key)


def _preheat_alerts(session) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert)
            .where(Alert.kind == AlertKind.PREHEAT_DUE)
            .order_by(Alert.due_at)
        )
    )


# --- The lead time, written down ----------------------------------------


class TestWhatTheBakeCarries:
    def test_a_pot_bake_puts_the_lead_on_the_bake_step(self, session):
        bake = _bake(session)

        assert _step(bake, "bake").preheat_lead_min == 45

    def test_nothing_else_carries_one(self, session):
        """It is the bake step's lead, so only the bake step has it."""
        bake = _bake(session)

        leads = {
            log.step_key: log.preheat_lead_min
            for log in bake.stage_logs
            if log.preheat_lead_min is not None
        }

        assert leads == {"bake": 45}

    def test_a_plain_oven_bake_gets_the_shorter_default(self, session):
        bake = _bake(session, method=BakeMethod.OVEN)

        assert _step(bake, "bake").preheat_lead_min == 20

    def test_the_bread_maker_gets_no_preheat_at_all(self, session):
        """The machine heats itself; there is nothing to be reminded of."""
        bake = _bake(session, method=BakeMethod.BREAD_MAKER)

        assert all(
            log.preheat_lead_min is None for log in bake.stage_logs
        )
        assert followalong.preheat_log(bake) is None
        assert followalong.preheat_span(bake) is None

    def test_the_setting_is_what_decides_it(self, session):
        settings_store.set_setting(session, "preheat_pot_min", "60")
        session.commit()

        bake = _bake(session)

        assert _step(bake, "bake").preheat_lead_min == 60

    def test_each_choice_is_obeyed(self, session):
        for minutes in (30, 45, 60):
            settings_store.set_setting(
                session, "preheat_pot_min", str(minutes)
            )
            session.commit()
            assert settings_store.preheat_lead_min(
                session, BakeMethod.DUTCH_OVEN
            ) == minutes

    def test_a_hand_edited_nonsense_setting_falls_back(self, session):
        """A bad row in settings must not take a bake day down."""
        settings_store.set_setting(session, "preheat_pot_min", "soon")
        session.commit()

        assert settings_store.preheat_lead_min(
            session, BakeMethod.DUTCH_OVEN
        ) == 45

    def test_the_lead_does_not_lengthen_the_day(self, session):
        """The whole point: a preheat is not a step, so nothing moves.

        The same plan with a pot and with a bread maker — which gets no
        preheat — has to end at the same minute.
        """
        pot = _bake(session, method=BakeMethod.DUTCH_OVEN, start=_at(16, 14))
        machine = _bake(
            session, method=BakeMethod.BREAD_MAKER, start=_at(16, 14)
        )

        assert _step(pot, "bake").planned_start == _step(
            machine, "bake"
        ).planned_start


# --- The moment ---------------------------------------------------------


class TestTheMoment:
    def test_it_is_the_lead_before_the_bake_step(self, session):
        bake = _bake(session)
        baking = _step(bake, "bake")

        moment = followalong.preheat_moment(baking)

        assert moment == baking.planned_start - timedelta(minutes=45)

    def test_it_lands_inside_the_final_rise(self, session):
        """Which is the thing that makes it worth having at all."""
        bake = _bake(session)
        rise = _step(bake, "final_rise")

        moment = followalong.preheat_moment(_step(bake, "bake"))

        assert rise.planned_start < moment < rise.planned_end

    def test_moving_the_bake_step_moves_it(self, session):
        bake = _bake(session)
        baking = _step(bake, "bake")

        baking.planned_start = baking.planned_start + timedelta(minutes=90)
        session.flush()

        assert followalong.preheat_moment(baking) == baking.planned_start - (
            timedelta(minutes=45)
        )

    def test_a_late_start_carries_it_along(self, session):
        """Start the final proof two hours late, re-plan, and it follows.

        The heads-up is counted off the planned start every time it is
        asked for, so re-planning the rest of the day moves it with the
        bake rather than leaving it where the morning thought it would be.
        """
        bake = _bake(session, start=_at(16, 14), now=_at(16, 14))
        before = followalong.preheat_moment(_step(bake, "bake"))

        rise = _step(bake, "final_rise")
        rise.actual_start = rise.planned_start + timedelta(hours=2)
        session.flush()
        followalong.replan(session, bake, now=rise.actual_start)
        session.commit()

        after = followalong.preheat_moment(_step(bake, "bake"))

        assert after > before
        assert after == _step(bake, "bake").planned_start - timedelta(
            minutes=45
        )

    def test_a_step_before_it_running_long_pushes_it_back(self, session):
        bake = _bake(session, start=_at(16, 14))
        before = followalong.preheat_moment(_step(bake, "bake"))

        rise = _step(bake, "final_rise")
        rise.planned_min = (rise.planned_min or 0) + 60
        session.flush()
        followalong.replan(session, bake, now=_at(16, 14))
        session.commit()

        assert followalong.preheat_moment(_step(bake, "bake")) > before

    def test_once_the_loaf_is_in_there_is_nothing_to_say(self, session):
        bake = _bake(session)
        baking = _step(bake, "bake")

        baking.actual_start = baking.planned_start
        session.flush()

        assert followalong.preheat_moment(baking) is None

    def test_a_finished_bake_step_has_no_moment(self, session):
        bake = _bake(session)
        baking = _step(bake, "bake")

        baking.actual_start = baking.planned_start
        baking.actual_end = baking.planned_end
        session.flush()

        assert followalong.preheat_moment(baking) is None

    def test_a_step_with_no_lead_has_no_moment(self, session):
        """Bake #7's shape: a pot bake whose preheat was laid out by hand.

        Its bake step carries no lead, because the column was added null
        and nothing backfills it — so the app says nothing about preheating
        a bake that already has a preheat step in its chain.
        """
        bake = _bake(session, lead=0)
        baking = _step(bake, "bake")
        baking.preheat_lead_min = None
        session.flush()

        assert followalong.preheat_moment(baking) is None
        assert followalong.preheat_span(bake) is None

    def test_the_span_runs_from_the_oven_to_the_loaf(self, session):
        bake = _bake(session)
        baking = _step(bake, "bake")

        span = followalong.preheat_span(bake)

        assert span == (
            baking.planned_start - timedelta(minutes=45),
            baking.planned_start,
        )


# --- Through reconcile --------------------------------------------------


class TestTheAlert:
    def test_reconcile_creates_it(self, session):
        _bake(session, start=_at(16, 14), now=_at(15, 8))

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        found = _preheat_alerts(session)
        assert len(found) == 1
        assert found[0].kind is AlertKind.PREHEAT_DUE
        assert found[0].is_about_a_bake

    def test_it_is_due_the_lead_before_the_bake(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        baking = _step(bake, "bake")

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert _preheat_alerts(session)[0].due_at == (
            baking.planned_start - timedelta(minutes=45)
        )

    def test_reconciling_twice_creates_nothing_new(self, session):
        _bake(session, start=_at(16, 14), now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        again = alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert [one for one in again.created if one.kind.is_preheat] == []
        assert len(_preheat_alerts(session)) == 1

    def test_the_bread_maker_gets_none(self, session):
        _bake(
            session, method=BakeMethod.BREAD_MAKER,
            start=_at(16, 14), now=_at(15, 8),
        )

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert _preheat_alerts(session) == []

    def test_it_fires_when_its_moment_comes(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        due = _step(bake, "bake").planned_start - timedelta(minutes=45)

        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        assert _preheat_alerts(session)[0].fired_at is None

        alert_service.reconcile(session, due)
        session.commit()

        assert _preheat_alerts(session)[0].fired_at == due

    def test_it_does_not_fire_at_the_bake_step_s_own_hour(self, session):
        """It is early or it is useless: an oven told at the bake is late."""
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        baking = _step(bake, "bake")

        alert_service.reconcile(
            session, baking.planned_start - timedelta(minutes=46)
        )
        session.commit()

        assert _preheat_alerts(session)[0].fired_at is None

    def test_moving_the_bake_moves_the_alert(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        was = _preheat_alerts(session)[0].due_at

        baking = _step(bake, "bake")
        baking.planned_start = baking.planned_start + timedelta(hours=1)
        session.flush()
        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        found = _preheat_alerts(session)
        assert len(found) == 1
        assert found[0].due_at == was + timedelta(hours=1)

    def test_it_is_dropped_once_the_loaf_is_in(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        assert _preheat_alerts(session)

        baking = _step(bake, "bake")
        baking.actual_start = baking.planned_start
        session.flush()
        result = alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert result.dropped >= 1
        assert _preheat_alerts(session) == []

    def test_a_fired_one_survives_the_next_tick(self, session):
        """Dropping only ever takes alerts that never went off."""
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        due = _step(bake, "bake").planned_start - timedelta(minutes=45)
        alert_service.reconcile(session, due)
        session.commit()

        alert_service.reconcile(session, due + timedelta(minutes=1))
        session.commit()

        assert len(_preheat_alerts(session)) == 1

    def test_the_step_s_own_alerts_are_untouched_by_it(self, session):
        """Two kinds against one step, and neither sweeps the other away."""
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        baking = _step(bake, "bake")

        for _ in range(3):
            alert_service.reconcile(session, _at(15, 8))
            session.commit()

        kinds = sorted(
            one.kind.value
            for one in session.scalars(
                select(Alert).where(Alert.stage_log_id == baking.id)
            )
        )

        # The bake's own start and end, the preheat before them, and the
        # lid coming off in the middle, which a pot bake now also has.
        assert kinds == ["lid_off_due", "preheat_due", "stage_due", "stage_due"]

    def test_doing_the_step_clears_it(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        due = _step(bake, "bake").planned_start - timedelta(minutes=45)
        alert_service.reconcile(session, due)
        session.commit()

        alert_service.acknowledge_for_stage(
            session, _step(bake, "bake").id, due
        )
        session.commit()

        one = _preheat_alerts(session)[0]
        assert one.is_acknowledged
        assert one not in alert_service.showing(session, due)

    def test_it_can_be_snoozed_like_any_other(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        due = _step(bake, "bake").planned_start - timedelta(minutes=45)
        alert_service.reconcile(session, due)
        session.commit()

        one = _preheat_alerts(session)[0]
        alert_service.snooze(session, one, due, 10)
        session.commit()

        assert one not in alert_service.showing(session, due)
        assert one in alert_service.showing(
            session, due + timedelta(minutes=11)
        )

    def test_an_abandoned_bake_day_stops_nagging(self, session):
        """Past the grace period the app has been left behind; let it go."""
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        due = _step(bake, "bake").planned_start - timedelta(minutes=45)
        alert_service.reconcile(
            session,
            due + timedelta(hours=followalong.STAGE_GRACE_H + 1),
        )
        session.commit()

        assert _preheat_alerts(session) == []

    def test_a_finished_bake_is_not_chased(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        bake.status = BakeStatus.DONE
        session.commit()

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert _preheat_alerts(session) == []


# --- The words ----------------------------------------------------------


class TestWhatItSays:
    def _fired(self, session, **kwargs) -> Alert:
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8), **kwargs)
        due = _step(bake, "bake").planned_start - timedelta(minutes=45)
        alert_service.reconcile(session, due)
        session.commit()
        return _preheat_alerts(session)[0]

    def test_the_pot_is_named_with_the_temperature_and_the_minutes(
        self, session
    ):
        alert = self._fired(session)

        assert alert_service.headline(alert, "F") == (
            "Preheat the oven and pot to 475°F now — bake in 45 min"
        )

    def test_it_reads_in_celsius_for_a_celsius_kitchen(self, session):
        alert = self._fired(session)

        assert alert_service.headline(alert, "C") == (
            "Preheat the oven and pot to 246°C now — bake in 45 min"
        )

    def test_a_plain_oven_bake_has_no_pot_to_mention(self, session):
        bake = _bake(
            session, method=BakeMethod.OVEN, start=_at(16, 14),
            now=_at(15, 8), temp_c=232.2,
        )
        due = _step(bake, "bake").planned_start - timedelta(minutes=20)
        alert_service.reconcile(session, due)
        session.commit()

        assert alert_service.headline(_preheat_alerts(session)[0], "F") == (
            "Preheat the oven to 450°F now — bake in 20 min"
        )

    def test_a_bake_with_no_temperature_still_says_the_useful_part(
        self, session
    ):
        alert = self._fired(session, temp_c=None)

        assert alert_service.headline(alert, "F") == (
            "Preheat the oven and pot now — bake in 45 min"
        )

    def test_the_configured_lead_is_the_one_it_quotes(self, session):
        settings_store.set_setting(session, "preheat_pot_min", "30")
        session.commit()
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        due = _step(bake, "bake").planned_start - timedelta(minutes=30)
        alert_service.reconcile(session, due)
        session.commit()

        assert "bake in 30 min" in alert_service.headline(
            _preheat_alerts(session)[0], "F"
        )

    def test_it_does_not_borrow_the_bake_step_s_name(self, session):
        """"Bake" three quarters of an hour early would read as the bake."""
        alert = self._fired(session)

        assert alert.subject == "Preheat the oven"
        assert alert.stage_log.name != alert.subject

    def test_a_step_alert_still_says_what_it_always_said(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        step_alert = session.scalars(
            select(Alert).where(Alert.kind == AlertKind.STAGE_DUE)
        ).first()

        assert alert_service.headline(step_alert, "F") == (
            step_alert.stage_log.name
        )

    def test_a_feed_alert_is_untouched(self, session):
        jar = Jar(name="Old Rye", origin=JarOrigin.HOMEMADE)
        session.add(jar)
        session.flush()
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=_at(15, 8),
                starter_g=20.0, flour_g=20.0, water_g=20.0,
            )
        )
        session.commit()
        alert_service.reconcile(session, _at(16, 8))
        session.commit()

        feed = session.scalars(
            select(Alert).where(Alert.kind == AlertKind.FEED_DUE)
        ).first()

        assert alert_service.headline(feed, "F") == "Old Rye"
