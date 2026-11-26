"""Alerts for the steps of a bake, down the same path as the feeding ones.

The point of these is that nothing about the lifecycle is new: a stage alert
is created by reconcile, fires when its moment comes, snoozes, acknowledges,
and disappears when the thing it was chasing stops being true. What is new is
only what it is *about*, so most of these check that the old guarantees still
hold with a bake in the picture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.alert import Alert
from app.models.enums import AlertKind, BakeStatus, IngredientRole, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.services import alerts as alert_service
from app.services import bakeplan, followalong
from app.services.bakeplan import PlanInputs

TZ = __import__("zoneinfo").ZoneInfo("America/New_York")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def _bake(session, *, start, now=None):
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=500.0)
    session.add(version)
    session.flush()
    session.add(
        RecipeIngredient(
            version_id=version.id, seq=0, name="whole rye flour",
            role=IngredientRole.FLOUR, baker_pct=100.0,
        )
    )
    session.commit()

    made, _, _ = bakeplan.build(
        session,
        version=version,
        jar=None,
        inputs=PlanInputs(total_flour_g=500.0, start_at=start),
        now=now or start,
        tz=TZ,
    )
    bake = followalong.start_from_plan(
        session, version=version, plan=made, now=now or start
    )
    session.commit()
    return bake


def _stage_alerts(session) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert)
            .where(Alert.stage_log_id.is_not(None))
            .order_by(Alert.due_at)
        )
    )


def _showing(session, now) -> list[Alert]:
    return alert_service.showing(session, now)


# --- Created, fired, cleared --------------------------------------------


class TestStageAlertsAppear:
    def test_a_planned_bake_gets_alerts_for_its_steps(self, session):
        start = _at(16, 14)
        _bake(session, start=start, now=_at(15, 8))

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        found = _stage_alerts(session)
        assert found
        # Every one is about a bake rather than a jar, and every one is a
        # step's own moment — bar the one preheat, which an oven bake now
        # gets as well. `test_preheat.py` is where that one is pinned down.
        assert all(one.jar_id is None for one in found)
        assert {one.kind for one in found} == {
            AlertKind.STAGE_DUE,
            AlertKind.PREHEAT_DUE,
        }
        assert [one.kind for one in found].count(AlertKind.PREHEAT_DUE) == 1

    def test_every_one_of_them_points_at_the_bake(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        for one in _stage_alerts(session):
            assert one.url == f"/bakes/{bake.id}"
            assert one.is_about_a_bake

    def test_reconciling_twice_creates_nothing_new(self, session):
        _bake(session, start=_at(16, 14), now=_at(15, 8))

        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        before = len(_stage_alerts(session))

        again = alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert again.created == []
        assert len(_stage_alerts(session)) == before

    def test_an_alert_fires_when_its_moment_comes(self, session):
        start = _at(16, 14)
        _bake(session, start=start, now=_at(15, 8))

        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        assert _showing(session, _at(15, 8)) == []

        result = alert_service.reconcile(session, start)
        session.commit()

        assert result.fired
        showing = _showing(session, start)
        assert showing
        assert showing[0].subject.startswith("Build the levain")

    def test_it_keeps_showing_until_it_is_dealt_with(self, session):
        start = _at(16, 14)
        _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, start)
        session.commit()

        later = start + timedelta(minutes=5)
        alert_service.reconcile(session, later)
        session.commit()

        assert _showing(session, later)

    def test_doing_the_step_clears_its_alert(self, session):
        start = _at(16, 14)
        bake = _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, start)
        session.commit()
        assert _showing(session, start)

        first = bake.stage_logs[0]
        cleared = alert_service.acknowledge_for_stage(session, first.id, start)
        session.commit()

        assert cleared == 1
        assert _showing(session, start) == []

    def test_a_step_ticked_off_stops_being_chased(self, session):
        """A done step's pending alerts are dropped, not left waiting."""
        start = _at(16, 14)
        bake = _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        before = len(_stage_alerts(session))

        bake.stage_logs[0].actual_start = start
        bake.stage_logs[0].actual_end = start + timedelta(minutes=9)
        session.flush()

        result = alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert result.dropped >= 1
        assert len(_stage_alerts(session)) < before

    def test_snoozing_one_hides_it_for_a_while(self, session):
        start = _at(16, 14)
        _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, start)
        session.commit()
        alert = _showing(session, start)[0]

        alert_service.snooze(session, alert, start, 30)
        session.commit()

        assert _showing(session, start) == []
        assert _showing(session, start + timedelta(minutes=31))


class TestWhichBakesAreChased:
    def test_a_finished_bake_is_left_alone(self, session):
        start = _at(16, 14)
        bake = _bake(session, start=start, now=_at(15, 8))
        bake.status = BakeStatus.DONE
        session.flush()

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert _stage_alerts(session) == []

    def test_an_archived_bake_is_left_alone(self, session):
        bake = _bake(session, start=_at(16, 14), now=_at(15, 8))
        bake.archived = True
        session.flush()

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert _stage_alerts(session) == []

    def test_finishing_a_bake_clears_what_was_showing(self, session):
        start = _at(16, 14)
        bake = _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, start)
        session.commit()
        assert _showing(session, start)

        alert_service.acknowledge_for_bake(session, bake, start)
        session.commit()

        assert _showing(session, start) == []

    def test_a_bake_abandoned_days_ago_is_not_a_pile_of_alerts(self, session):
        """Past the grace period a missed step is missed, not nagged about."""
        start = _at(10, 14)
        _bake(session, start=start, now=start)

        alert_service.reconcile(session, _at(16, 14))
        session.commit()

        assert _stage_alerts(session) == []

    def test_a_bake_with_no_planned_times_is_not_chased(self, session):
        from app.services import bakes as bake_service

        recipe = Recipe(name="Plain rye")
        session.add(recipe)
        session.flush()
        version = RecipeVersion(recipe_id=recipe.id, version=1)
        session.add(version)
        session.commit()
        bake_service.start_bake(session, version)
        session.commit()

        alert_service.reconcile(session, _at(15, 8))
        session.commit()

        assert _stage_alerts(session) == []


class TestReplanningMovesTheAlerts:
    def test_the_old_moment_is_dropped_and_the_new_one_created(self, session):
        start = _at(16, 14)
        bake = _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, _at(15, 8))
        session.commit()
        was = {one.due_at for one in _stage_alerts(session)}

        followalong.replan(session, bake, now=_at(16, 18))
        alert_service.reconcile(session, _at(16, 17))
        session.commit()

        now_due = {one.due_at for one in _stage_alerts(session)}
        assert now_due
        assert now_due.isdisjoint(was)


class TestFeedingAlertsStillWork:
    """The point of one table is that the old kind is untouched."""

    def test_a_jar_and_a_bake_can_both_be_due_at_once(self, session):
        start = _at(16, 14)
        jar = Jar(name="Soviet rye", origin=JarOrigin.PURCHASED)
        session.add(jar)
        session.flush()
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=_at(14, 14),
                starter_g=20.0, flour_g=20.0, water_g=20.0,
            )
        )
        session.commit()
        _bake(session, start=start, now=_at(15, 8))

        alert_service.reconcile(session, start)
        session.commit()

        showing = _showing(session, start)
        kinds = {one.kind for one in showing}
        assert AlertKind.FEED_DUE in kinds
        assert AlertKind.STAGE_DUE in kinds

    def test_feeding_the_jar_does_not_clear_the_bake(self, session):
        start = _at(16, 14)
        jar = Jar(name="Soviet rye", origin=JarOrigin.PURCHASED)
        session.add(jar)
        session.flush()
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=_at(14, 14),
                starter_g=20.0, flour_g=20.0, water_g=20.0,
            )
        )
        session.commit()
        _bake(session, start=start, now=_at(15, 8))
        alert_service.reconcile(session, start)
        session.commit()

        alert_service.acknowledge_for_jar(session, jar.id, start)
        session.commit()

        left = _showing(session, start)
        assert left
        assert all(one.kind is AlertKind.STAGE_DUE for one in left)
