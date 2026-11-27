"""The demo notebook: only into an empty one, and through the services."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.alert import Alert
from app.models.bake import Bake
from app.models.enums import BakeStatus
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import Recipe
from app.services import alerts, demo
from app.services import jars as jar_service


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


class TestLoad:
    def test_fills_an_empty_notebook(self, session, frozen_now):
        assert demo.can_load(session)
        assert demo.load(session, frozen_now) is True
        session.commit()

        jars = jar_service.list_jars(session)
        assert sorted(jar.name for jar in jars) == [
            "Rye (demo)", "Soviet rye (demo)",
        ]
        # One homemade jar and one control: the comparison is the point.
        assert [jar.is_control for jar in sorted(jars, key=lambda j: j.name)] == [
            False, True,
        ]
        assert _count(session, Feeding) == 2 * demo.FEEDINGS
        assert _count(session, Recipe) > 1

        bake = session.scalars(select(Bake)).one()
        assert bake.status is BakeStatus.DONE
        assert bake.result is not None and bake.result.rating == 3
        assert all(log.actual_end is not None for log in bake.stage_logs)
        assert bake.finished_at < frozen_now

    def test_nothing_is_dated_in_the_future(self, session, frozen_now):
        demo.load(session, frozen_now)
        for jar in jar_service.list_jars(session):
            assert all(f.fed_at <= frozen_now for f in jar.feedings)
            assert all(o.observed_at <= frozen_now for o in jar.observations)

    def test_jars_are_due_soon_but_not_yet(self, session, frozen_now):
        """A newcomer should watch an alert arrive, not open onto a wall of
        overdue ones."""
        demo.load(session, frozen_now)
        session.commit()
        alerts.reconcile(session, frozen_now)
        session.commit()
        assert alerts.showing(session, frozen_now) == []
        assert _count(session, Alert) == 2
        for alert in session.scalars(select(Alert)):
            assert alert.due_at > frozen_now

    def test_refuses_a_notebook_with_a_jar_in_it(self, session, frozen_now):
        demo.load(session, frozen_now)
        session.commit()
        assert demo.can_load(session) is False
        assert demo.load(session, frozen_now) is False
        assert _count(session, Jar) == 2

    def test_an_archived_jar_still_counts_as_a_notebook_in_use(
        self, session, frozen_now
    ):
        demo.load(session, frozen_now)
        for jar in jar_service.list_jars(session):
            jar_service.set_archived(session, jar, True)
        session.commit()
        assert demo.can_load(session) is False


class TestRoutes:
    def test_empty_shelf_offers_the_demo(self, client):
        page = client.get("/")
        assert 'action="/demo/load"' in page.text

    def test_loading_it_takes_the_offer_away(self, client):
        done = client.post("/demo/load", follow_redirects=False)
        assert done.status_code == 303 and done.headers["location"] == "/"
        page = client.get("/")
        assert "Rye (demo)" in page.text
        assert 'action="/demo/load"' not in page.text

    def test_posting_twice_adds_nothing(self, client, session):
        client.post("/demo/load")
        client.post("/demo/load")
        assert _count(session, Jar) == 2

    def test_every_page_of_the_demo_opens(self, client, session):
        client.post("/demo/load")
        bake = session.scalars(select(Bake)).one()
        jar = jar_service.list_jars(session)[0]
        for path in ("/", f"/jars/{jar.id}", "/recipes", "/bakes",
                     f"/bakes/{bake.id}", "/about"):
            assert client.get(path).status_code == 200, path

    def test_library_alone_adds_recipes_and_no_jars(self, client, session):
        assert 'action="/demo/library"' in client.get("/recipes").text
        done = client.post("/demo/library", follow_redirects=False)
        assert done.status_code == 303
        assert _count(session, Recipe) > 1
        assert _count(session, Jar) == 0
        assert 'action="/demo/library"' not in client.get("/recipes").text
