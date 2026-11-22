"""Starting a bake from a plan, and following it along on the page.

The bake page is read standing in the kitchen, so these check the words that
actually have to be on it: what is on now, what to do next, and the buttons
that record what really happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.alert import Alert
from app.models.bake import Bake, BakeStageLog
from app.models.base import utcnow
from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import BakeStatus, BusyKind, IngredientRole, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.services import alerts as alert_service

TZ = ZoneInfo("America/New_York")


def _release(session) -> None:
    """Let go of the read transaction so the request can write."""
    session.rollback()


def _version(session, *, name="Borodinsky", levain=True) -> int:
    recipe = Recipe(name=name)
    session.add(recipe)
    session.flush()
    version = RecipeVersion(recipe_id=recipe.id, version=1, batch_flour_g=500.0)
    session.add(version)
    session.flush()
    lines = [("whole rye flour", IngredientRole.FLOUR, 100.0)]
    if levain:
        lines.append(("rye levain", IngredientRole.LEVAIN, 30.0))
    for seq, (line, role, pct) in enumerate(lines):
        session.add(
            RecipeIngredient(
                version_id=version.id, seq=seq, name=line,
                role=role, baker_pct=pct,
            )
        )
    session.commit()
    version_id = version.id
    _release(session)
    return version_id


def _jar(session, *, hours_ago=5) -> int:
    jar = Jar(name="Old Rye", origin=JarOrigin.HOMEMADE)
    session.add(jar)
    session.flush()
    session.add(
        Feeding(
            jar_id=jar.id, fed_at=utcnow() - timedelta(hours=hours_ago),
            starter_g=20.0, flour_g=20.0, water_g=20.0,
        )
    )
    session.commit()
    jar_id = jar.id
    _release(session)
    return jar_id


def _sleep(session) -> None:
    session.add(
        BusyBlock(
            label="Sleep", kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
            start_minute=120, end_minute=600,
        )
    )
    session.commit()
    _release(session)


def _start(client, session, **extra) -> str:
    """Start a bake from a plan and return its URL."""
    version_id = extra.pop("version", None) or _version(session)
    at = (utcnow() + timedelta(minutes=30)).astimezone(TZ).strftime(
        "%Y-%m-%dT%H:%M"
    )
    data = {"version": str(version_id), "mode": "start", "at": at} | extra
    response = client.post("/plan/start", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


def _logs(session, bake_url: str) -> list[BakeStageLog]:
    bake_id = int(bake_url.rsplit("/", 1)[1])
    return list(
        session.scalars(
            select(BakeStageLog)
            .where(BakeStageLog.bake_id == bake_id)
            .order_by(BakeStageLog.seq)
        )
    )


# --- Starting one -------------------------------------------------------


class TestStartingFromThePlan:
    def test_the_planner_offers_to_start_the_bake(self, client, session):
        version_id = _version(session)

        page = client.get("/plan", params={"version": version_id})

        assert "Start this bake" in page.text
        assert 'action="/plan/start"' in page.text

    def test_a_plan_with_no_recipe_has_nothing_to_start(self, client):
        assert "Start this bake" not in client.get("/plan").text

    def test_starting_it_lands_on_the_bake(self, client, session):
        url = _start(client, session)

        page = client.get(url)

        assert page.status_code == 200
        assert "Borodinsky" in page.text
        assert "Right now" in page.text

    def test_the_bake_carries_the_planned_times(self, client, session):
        url = _start(client, session)
        _release(session)

        logs = _logs(session, url)

        assert logs
        assert all(log.planned_start is not None for log in logs)
        assert all(log.planned_min for log in logs)

    def test_the_jar_comes_with_it(self, client, session):
        jar_id = _jar(session)
        url = _start(client, session, jar=str(jar_id))
        _release(session)

        bake = session.get(Bake, int(url.rsplit("/", 1)[1]))
        assert bake.jar_id == jar_id

    def test_a_bake_starting_in_half_an_hour_has_not_begun(
        self, client, session
    ):
        url = _start(client, session)
        _release(session)

        bake = session.get(Bake, int(url.rsplit("/", 1)[1]))
        assert bake.status is BakeStatus.PLANNED

    def test_starting_without_a_recipe_is_refused_rather_than_guessed(
        self, client
    ):
        response = client.post("/plan/start", data={"mode": "start"})

        assert response.status_code == 400

    def test_a_plan_worked_backwards_can_be_started_too(self, client, session):
        """Asking for bread by six and then committing to it."""
        version_id = _version(session)
        want = (utcnow() + timedelta(days=1)).astimezone(TZ).replace(
            hour=18, minute=0
        ).strftime("%Y-%m-%dT%H:%M")

        response = client.post(
            "/plan/start",
            data={"version": str(version_id), "mode": "ready", "at": want},
            follow_redirects=False,
        )
        assert response.status_code == 303
        url = response.headers["location"]
        _release(session)

        logs = _logs(session, url)
        assert logs
        # The last step ends when the bread was asked for, give or take the
        # rounding of each step to whole minutes.
        asked = datetime.strptime(want, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
        assert abs((logs[-1].planned_end - asked).total_seconds()) < 120

    def test_the_rest_of_the_plan_survives_the_post(self, client, session):
        """A longer cool typed on the form must reach the bake."""
        version_id = _version(session)
        url = _start(client, session, version=version_id, cool="200")
        _release(session)

        cool = next(
            log for log in _logs(session, url) if log.step_key == "cool"
        )
        assert cool.planned_min == 200


# --- The page -----------------------------------------------------------


class TestTheNowPanel:
    def test_it_names_the_next_thing_to_do(self, client, session):
        url = _start(client, session)

        page = client.get(url)

        assert "Next thing to do" in page.text or "Build the levain" in page.text

    def test_it_draws_the_day(self, client, session):
        url = _start(client, session)

        page = client.get(url)

        assert "baketimeline" in page.text

    def test_it_offers_to_re_plan(self, client, session):
        url = _start(client, session)

        page = client.get(url)

        assert "Re-plan from now" in page.text
        assert f'action="{url}/replan"' in page.text

    def test_it_says_which_steps_land_in_the_night(self, client, session):
        _sleep(session)
        url = _start(client, session)

        page = client.get(url)

        assert "inside Sleep" in page.text

    def test_a_bake_with_no_plan_gets_no_panel(self, client, session):
        """An old bake started before any of this still reads fine."""
        from app.services import bakes as bake_service

        version_id = _version(session)
        version = session.get(RecipeVersion, version_id)
        bake = bake_service.start_bake(session, version)
        session.commit()
        bake_id = bake.id
        _release(session)

        page = client.get(f"/bakes/{bake_id}")

        assert page.status_code == 200
        assert "Right now" not in page.text

    def test_a_finished_bake_shows_the_write_up_not_the_panel(
        self, client, session
    ):
        url = _start(client, session)
        client.post(f"{url}/finish", data={"status": "done"})

        page = client.get(url)

        assert "Right now" not in page.text
        assert "Record the result" in page.text


class TestTickingStepsOff:
    def test_starting_a_step_records_when(self, client, session):
        url = _start(client, session)
        _release(session)
        first = _logs(session, url)[0]
        log_id = first.id
        _release(session)

        client.post(f"{url}/stages/{log_id}/start")
        _release(session)

        again = session.get(BakeStageLog, log_id)
        assert again.actual_start is not None
        assert again.actual_end is None

    def test_finishing_a_step_records_when(self, client, session):
        url = _start(client, session)
        _release(session)
        log_id = _logs(session, url)[0].id
        _release(session)

        client.post(f"{url}/stages/{log_id}/start")
        client.post(f"{url}/stages/{log_id}/end")
        _release(session)

        again = session.get(BakeStageLog, log_id)
        assert again.actual_end is not None
        assert again.actual_min is not None

    def test_the_panel_offers_to_finish_what_is_running(self, client, session):
        url = _start(client, session)
        _release(session)
        log_id = _logs(session, url)[0].id
        _release(session)
        client.post(f"{url}/stages/{log_id}/start")

        page = client.get(url)

        assert "Done with" in page.text

    def test_doing_a_step_clears_its_alert(self, client, session):
        url = _start(client, session)
        _release(session)
        log_id = _logs(session, url)[0].id
        # Fire it by reconciling from well past its moment.
        alert_service.reconcile(session, utcnow() + timedelta(hours=1))
        session.commit()
        showing = len(alert_service.showing(session, utcnow() + timedelta(hours=1)))
        assert showing >= 1
        _release(session)

        client.post(f"{url}/stages/{log_id}/start")
        _release(session)

        left = alert_service.showing(session, utcnow() + timedelta(hours=1))
        assert all(one.stage_log_id != log_id for one in left)

    def test_a_fired_step_alert_shows_in_the_banner(self, client, session):
        _start(client, session)
        _release(session)
        alert_service.reconcile(session, utcnow() + timedelta(hours=1))
        session.commit()
        _release(session)

        page = client.get("/")

        assert "Build the levain" in page.text
        assert "Open the bake" in page.text

    def test_the_alerts_api_describes_a_step_alert(self, client, session):
        url = _start(client, session)
        _release(session)
        alert_service.reconcile(session, utcnow() + timedelta(hours=1))
        session.commit()
        _release(session)

        payload = client.get("/api/alerts").json()

        steps = [one for one in payload["alerts"] if one["kind"] == "stage_due"]
        assert steps
        assert steps[0]["jar_id"] is None
        assert steps[0]["url"] == url
        assert "levain" in steps[0]["subject"].lower()


class TestReplanning:
    def test_it_moves_every_step_still_to_come(self, client, session):
        url = _start(client, session)
        _release(session)
        before = [log.planned_start for log in _logs(session, url)]
        _release(session)

        client.post(f"{url}/replan")
        _release(session)

        after = [log.planned_start for log in _logs(session, url)]
        # The plan started half an hour out, so re-planning from now pulls
        # everything earlier.
        assert all(new < old for new, old in zip(after, before, strict=True))

    def test_a_step_already_finished_keeps_its_times(self, client, session):
        url = _start(client, session)
        _release(session)
        log_id = _logs(session, url)[0].id
        _release(session)
        client.post(f"{url}/stages/{log_id}/start")
        client.post(f"{url}/stages/{log_id}/end")
        _release(session)
        was = session.get(BakeStageLog, log_id)
        recorded = (was.actual_start, was.actual_end, was.planned_start)
        _release(session)

        client.post(f"{url}/replan")
        _release(session)

        again = session.get(BakeStageLog, log_id)
        assert (again.actual_start, again.actual_end, again.planned_start) == recorded

    def test_it_can_be_pressed_twice(self, client, session):
        url = _start(client, session)

        assert client.post(f"{url}/replan").status_code == 200
        assert client.post(f"{url}/replan").status_code == 200


class TestTheLevainQuestion:
    def _finish_the_rise(self, client, session, url) -> int:
        logs = _logs(session, url)
        build, rise = logs[0].id, logs[1].id
        _release(session)
        client.post(f"{url}/stages/{build}/start")
        client.post(f"{url}/stages/{build}/end")
        client.post(f"{url}/stages/{rise}/start")
        client.post(f"{url}/stages/{rise}/end")
        return rise

    def test_it_is_not_asked_before_the_rise_is_over(self, client, session):
        url = _start(client, session)

        assert "Was the levain at its peak?" not in client.get(url).text

    def test_a_finished_rise_is_asked_about(self, client, session):
        url = _start(client, session)
        _release(session)
        self._finish_the_rise(client, session, url)

        page = client.get(url)

        assert "Was the levain at its peak?" in page.text

    def test_yes_is_recorded_and_the_question_goes_away(self, client, session):
        url = _start(client, session)
        _release(session)
        rise = self._finish_the_rise(client, session, url)

        client.post(f"{url}/stages/{rise}/peak", data={"at_peak": "1"})
        _release(session)

        assert session.get(BakeStageLog, rise).at_peak is True
        _release(session)
        page = client.get(url)
        assert "Was the levain at its peak?" not in page.text
        assert "At its peak when it was used." in page.text

    def test_no_is_recorded_just_as_firmly(self, client, session):
        url = _start(client, session)
        _release(session)
        rise = self._finish_the_rise(client, session, url)

        client.post(f"{url}/stages/{rise}/peak", data={"at_peak": "0"})
        _release(session)

        assert session.get(BakeStageLog, rise).at_peak is False

    def test_a_step_from_another_bake_cannot_be_answered(self, client, session):
        first = _start(client, session)
        second = _start(client, session, version=_version(session, name="Rye"))
        _release(session)
        theirs = _logs(session, second)[1].id
        _release(session)

        response = client.post(f"{first}/stages/{theirs}/peak", data={"at_peak": "1"})

        assert response.status_code == 404


class TestNothingIsLeftBehind:
    def test_finishing_the_bake_clears_its_alerts(self, client, session):
        url = _start(client, session)
        _release(session)
        alert_service.reconcile(session, utcnow() + timedelta(hours=1))
        session.commit()
        _release(session)

        client.post(f"{url}/finish", data={"status": "done"})
        _release(session)

        left = alert_service.showing(session, utcnow() + timedelta(hours=1))
        assert [one for one in left if one.is_about_a_bake] == []

    def test_archiving_the_bake_clears_its_alerts(self, client, session):
        url = _start(client, session)
        _release(session)
        alert_service.reconcile(session, utcnow() + timedelta(hours=1))
        session.commit()
        _release(session)

        client.post(f"{url}/archive", data={"archived": "1"})
        _release(session)

        left = alert_service.showing(session, utcnow() + timedelta(hours=1))
        assert [one for one in left if one.is_about_a_bake] == []

    def test_deleting_a_stage_takes_its_alerts_with_it(self, client, session):
        """The alert table is derived, so nothing should outlive its subject."""
        url = _start(client, session)
        _release(session)
        alert_service.reconcile(session, utcnow())
        session.commit()
        bake_id = int(url.rsplit("/", 1)[1])
        bake = session.get(Bake, bake_id)
        session.delete(bake)
        session.commit()

        left = list(
            session.scalars(
                select(Alert).where(Alert.stage_log_id.is_not(None))
            )
        )
        assert left == []
