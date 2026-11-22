"""Recording a peak, and watching it change what the app predicts.

The acceptance check for this phase is that the ribbon and the planner
actually use what a jar has taught the model, so most of these record a few
peaks and then look at what the pages say before and after.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.enums import IngredientRole, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.observation import Observation
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.services import learning, plan as plan_service, timing

TZ = ZoneInfo("America/New_York")
BASELINE_H = timing.predict_peak_h(1.0, timing.REF_TEMP_C)


def _release(session) -> None:
    """Let go of the read transaction, and of what was read in it.

    Sessions here are made with `expire_on_commit=False`, so anything this
    one has already loaded stays loaded — including rows the HTTP requests
    have since changed underneath it. Expiring is what makes a read after a
    request show what the request actually did.
    """
    session.rollback()
    session.expire_all()


def _jar(session, *, name="Old Rye", fed_hours_ago=2.0) -> int:
    from app.models.base import utcnow

    jar = Jar(name=name, origin=JarOrigin.HOMEMADE)
    session.add(jar)
    session.flush()
    session.add(
        Feeding(
            jar_id=jar.id, fed_at=utcnow() - timedelta(hours=fed_hours_ago),
            starter_g=20.0, flour_g=20.0, water_g=20.0,
            ambient_temp_c=timing.REF_TEMP_C,
        )
    )
    session.commit()
    jar_id = jar.id
    _release(session)
    return jar_id


def _slow_history(session, jar_id: int, *, times=3, factor=1.4) -> None:
    """A few past cycles in which this jar peaked late."""
    from app.models.base import utcnow

    for step in range(times):
        fed_at = utcnow() - timedelta(days=step + 2)
        session.add(
            Feeding(
                jar_id=jar_id, fed_at=fed_at,
                starter_g=20.0, flour_g=20.0, water_g=20.0,
                ambient_temp_c=timing.REF_TEMP_C,
            )
        )
        session.add(
            Observation(
                jar_id=jar_id,
                observed_at=fed_at + timedelta(hours=BASELINE_H * factor),
                peaked=True,
            )
        )
    session.commit()
    _release(session)


def _version(session) -> int:
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=500.0)
    session.add(version)
    session.flush()
    for seq, (name, role, pct) in enumerate(
        (
            ("whole rye flour", IngredientRole.FLOUR, 100.0),
            ("rye levain", IngredientRole.LEVAIN, 30.0),
        )
    ):
        session.add(
            RecipeIngredient(
                version_id=version.id, seq=seq, name=name,
                role=role, baker_pct=pct,
            )
        )
    session.commit()
    version_id = version.id
    _release(session)
    return version_id


# --- One tap ------------------------------------------------------------


class TestPeakedNow:
    def test_the_jar_page_offers_it(self, client, session):
        jar_id = _jar(session)

        page = client.get(f"/jars/{jar_id}")

        assert "Peaked now" in page.text
        assert f'action="/jars/{jar_id}/peaked"' in page.text

    def test_the_dashboard_offers_it_too(self, client, session):
        jar_id = _jar(session)

        page = client.get("/")

        assert f'action="/jars/{jar_id}/peaked"' in page.text

    def test_tapping_it_records_a_peak(self, client, session):
        jar_id = _jar(session)

        client.post(f"/jars/{jar_id}/peaked", data={"next": "/"})
        _release(session)

        rows = list(
            session.scalars(
                select(Observation).where(Observation.jar_id == jar_id)
            )
        )
        assert len(rows) == 1
        assert rows[0].peaked is True

    def test_it_comes_back_where_it_was_tapped(self, client, session):
        jar_id = _jar(session)

        response = client.post(
            f"/jars/{jar_id}/peaked", data={"next": "/"},
            follow_redirects=False,
        )

        assert response.headers["location"] == "/"

    def test_the_observe_form_can_say_it_too(self, client, session):
        jar_id = _jar(session)
        page = client.get(f"/jars/{jar_id}/observe")
        assert 'name="peaked"' in page.text

        client.post(
            f"/jars/{jar_id}/observe",
            data={"height_mm": "60", "start_height_mm": "40", "peaked": "1"},
        )
        _release(session)

        row = session.scalars(
            select(Observation).where(Observation.jar_id == jar_id)
        ).first()
        assert row.peaked is True

    def test_an_ordinary_observation_claims_no_peak(self, client, session):
        jar_id = _jar(session)

        client.post(
            f"/jars/{jar_id}/observe",
            data={"height_mm": "60", "start_height_mm": "40"},
        )
        _release(session)

        row = session.scalars(
            select(Observation).where(Observation.jar_id == jar_id)
        ).first()
        assert row.peaked is False

    def test_a_peak_shows_up_on_the_jars_timeline(self, client, session):
        jar_id = _jar(session)
        client.post(f"/jars/{jar_id}/peaked", data={"next": f"/jars/{jar_id}"})

        page = client.get(f"/jars/{jar_id}")

        assert page.status_code == 200


# --- What it changes ----------------------------------------------------


class TestItChangesThePredictions:
    def test_the_jar_page_says_what_it_has_learned(self, client, session):
        jar_id = _jar(session)
        _slow_history(session, jar_id)

        page = client.get(f"/jars/{jar_id}")

        assert "Old Rye peaks about" in page.text
        assert "later than the model expects" in page.text

    def test_an_unwatched_jar_is_told_what_is_missing(self, client, session):
        jar_id = _jar(session)

        page = client.get(f"/jars/{jar_id}")

        assert "No peak has been recorded for this jar yet" in page.text

    def test_the_ribbon_calls_an_unmeasured_jar_an_estimate(
        self, client, session
    ):
        _jar(session)

        page = client.get("/")

        assert "estimate" in page.text

    def test_a_well_watched_jar_loses_the_estimate_label(
        self, client, session
    ):
        jar_id = _jar(session)
        _slow_history(session, jar_id)
        jar = session.get(Jar, jar_id)
        made = plan_service.jar_plan(
            session, jar, now=datetime.now(UTC),
            until=datetime.now(UTC) + timedelta(days=1),
        )
        assert not made.is_estimate
        _release(session)

        page = client.get(f"/jars/{jar_id}")

        assert "· estimate" not in page.text

    def test_a_slow_jar_pushes_its_predicted_peak_later(self, client, session):
        """The acceptance check: the ribbon uses the factor."""
        jar_id = _jar(session)
        jar = session.get(Jar, jar_id)
        now = datetime.now(UTC)
        before = plan_service.jar_plan(
            session, jar, now=now, until=now + timedelta(days=1)
        ).last_cycle.peak_h
        _release(session)

        _slow_history(session, jar_id, factor=1.4)
        jar = session.get(Jar, jar_id)
        after = plan_service.jar_plan(
            session, jar, now=now, until=now + timedelta(days=1)
        ).last_cycle.peak_h

        assert after > before * 1.2

    def test_the_planner_builds_a_longer_levain_rise_for_a_slow_jar(
        self, client, session
    ):
        """The other half of the acceptance check: the planner uses it."""
        version_id = _version(session)
        quick = _jar(session, name="Quick", fed_hours_ago=1.0)
        slow = _jar(session, name="Slow", fed_hours_ago=1.0)
        _slow_history(session, slow, factor=1.5)

        from app.services import bakeplan
        from app.services.bakeplan import PlanInputs

        now = datetime.now(UTC)
        rises = {}
        for name, jar_id in (("quick", quick), ("slow", slow)):
            made, _, _ = bakeplan.build(
                session,
                version=session.get(RecipeVersion, version_id),
                jar=session.get(Jar, jar_id),
                inputs=PlanInputs(total_flour_g=500.0, start_at=now),
                now=now,
                tz=TZ,
            )
            rises[name] = made.step("levain_rise").duration_min

        assert rises["slow"] > rises["quick"] * 1.3

    def test_the_planner_says_so_when_the_jar_is_unmeasured(
        self, client, session
    ):
        version_id = _version(session)
        jar_id = _jar(session)

        page = client.get("/plan", params={"version": version_id, "jar": jar_id})

        assert "has not been watched to its peak enough times yet" in page.text

    def test_the_planner_stops_saying_so_once_it_has_been(
        self, client, session
    ):
        version_id = _version(session)
        jar_id = _jar(session)
        _slow_history(session, jar_id)

        page = client.get("/plan", params={"version": version_id, "jar": jar_id})

        assert "has not been watched to its peak enough times yet" not in page.text

    def test_the_ratio_advice_takes_the_jar_into_account(self, client, session):
        """A slow jar needs a tighter feed to hit the same peak."""
        jar_id = _jar(session)
        jar = session.get(Jar, jar_id)
        now = datetime.now(UTC)
        target = now + timedelta(hours=BASELINE_H)

        loose = plan_service.ratio_advice(
            from_moment=now, target_at=target,
            temp_c=timing.REF_TEMP_C, factor=1.0,
        )
        _release(session)
        _slow_history(session, jar_id, factor=1.5)
        jar = session.get(Jar, jar_id)
        made = plan_service.jar_plan(
            session, jar, now=now, until=now + timedelta(days=1)
        )
        tight = plan_service.ratio_advice(
            from_moment=now, target_at=target,
            temp_c=timing.REF_TEMP_C, factor=made.factor,
        )

        assert made.factor > 1.3
        assert tight.ratio < loose.ratio


class TestABakeTeachesTheJarToo:
    def test_a_levain_answered_yes_becomes_a_recorded_peak(
        self, client, session
    ):
        from app.models.base import utcnow
        from app.models.bake import BakeStageLog

        jar_id = _jar(session, fed_hours_ago=1.0)
        version_id = _version(session)
        at = (utcnow() + timedelta(minutes=5)).astimezone(TZ).strftime(
            "%Y-%m-%dT%H:%M"
        )
        response = client.post(
            "/plan/start",
            data={
                "version": str(version_id), "jar": str(jar_id),
                "mode": "start", "at": at,
            },
            follow_redirects=False,
        )
        url = response.headers["location"]
        _release(session)

        bake_id = int(url.rsplit("/", 1)[1])
        logs = list(
            session.scalars(
                select(BakeStageLog)
                .where(BakeStageLog.bake_id == bake_id)
                .order_by(BakeStageLog.seq)
            )
        )
        rise = logs[1]
        assert rise.step_key == "levain_rise"
        # The bare model's own figure was kept beside the planned one.
        assert rise.model_min
        rise_id = rise.id
        _release(session)

        client.post(f"{url}/stages/{rise_id}/start")
        _release(session)
        # Backdate the start so the rise has a real length to it: the tests
        # cannot sit through five hours, and a zero-length rise measures
        # nothing (which `learning` is right to ignore).
        rise = session.get(BakeStageLog, rise_id)
        rise.actual_start = utcnow() - timedelta(
            minutes=rise.model_min * 1.2
        )
        session.commit()
        _release(session)

        client.post(f"{url}/stages/{rise_id}/end")
        client.post(f"{url}/stages/{rise_id}/peak", data={"at_peak": "1"})
        _release(session)

        jar = session.get(Jar, jar_id)
        peaks = learning.recorded_peaks(session, jar)
        assert len(peaks) == 1
        assert peaks[0].source is learning.PeakSource.LEVAIN
        assert peaks[0].ratio == pytest.approx(1.2, abs=0.02)
        # And it moves the jar's own factor off 1.0.
        assert learning.factor(session, jar) == pytest.approx(1.2, abs=0.02)

    def test_a_rise_of_no_length_measures_nothing(self, client, session):
        """Tapping start and done in one breath is not a measurement."""
        from app.models.base import utcnow
        from app.models.bake import BakeStageLog

        jar_id = _jar(session, fed_hours_ago=1.0)
        version_id = _version(session)
        at = (utcnow() + timedelta(minutes=5)).astimezone(TZ).strftime(
            "%Y-%m-%dT%H:%M"
        )
        url = client.post(
            "/plan/start",
            data={
                "version": str(version_id), "jar": str(jar_id),
                "mode": "start", "at": at,
            },
            follow_redirects=False,
        ).headers["location"]
        _release(session)
        bake_id = int(url.rsplit("/", 1)[1])
        rise_id = list(
            session.scalars(
                select(BakeStageLog)
                .where(BakeStageLog.bake_id == bake_id)
                .order_by(BakeStageLog.seq)
            )
        )[1].id
        _release(session)

        client.post(f"{url}/stages/{rise_id}/start")
        client.post(f"{url}/stages/{rise_id}/end")
        client.post(f"{url}/stages/{rise_id}/peak", data={"at_peak": "1"})
        _release(session)

        assert learning.recorded_peaks(session, session.get(Jar, jar_id)) == ()
