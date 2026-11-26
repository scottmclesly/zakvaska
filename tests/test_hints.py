"""Hints: what a first loaf taught, shown where the next one needs it.

The words are data (`app.data.hints`), the placing is `services.hints`, and
a hint put away with "Got it" stays put away — in one settings row, so there
is no migration and nothing is written by merely looking at a page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data.hints import HINTS, PLACES
from app.models.enums import BakeMethod, JarOrigin, JarState
from app.models.setting import Setting
from app.services import hints as hint_service
from app.services import jars as jar_service
from app.services import plan as plan_service

EXPLAINERS = Path("app/templates/partials/explainers")


def _jar(session, **fields):
    jar = jar_service.create_jar(
        session, name=fields.pop("name", "Rye"), origin=JarOrigin.HOMEMADE,
        state=JarState.ACTIVE, **fields,
    )
    session.commit()
    return jar


def _step(key=None, name="A step"):
    return SimpleNamespace(step_key=key, name=name)


def _bake(method=BakeMethod.DUTCH_OVEN):
    return SimpleNamespace(method=method)


# --- The data ------------------------------------------------------------


class TestTheHintsThemselves:
    def test_every_hint_has_its_own_id(self):
        ids = [hint.id for hint in HINTS]
        assert len(ids) == len(set(ids))

    def test_every_hint_is_somewhere_that_exists(self):
        assert {hint.place for hint in HINTS} <= set(PLACES)

    def test_a_hint_is_a_line_or_two_not_an_essay(self):
        """The detail goes in `more`; the hint itself is read at a glance."""
        for hint in HINTS:
            assert len(hint.text) <= 220, hint.id

    def test_every_drawing_a_hint_names_is_there(self):
        named = {hint.explainer for hint in HINTS if hint.explainer}
        on_disk = {path.stem for path in EXPLAINERS.glob("*.html")}
        assert named <= on_disk
        # And none was drawn for nothing.
        assert on_disk <= named

    def test_the_eight_explainers_are_all_drawn(self):
        assert len(list(EXPLAINERS.glob("*.html"))) == 8

    def test_a_drawing_is_inline_svg_in_the_pages_own_colours(self):
        """No image request, no library, and nothing that ignores the theme."""
        for path in EXPLAINERS.glob("*.html"):
            body = path.read_text()
            assert "<svg" in body and "<img" not in body, path.name
            assert "#" not in body.split("#}", 1)[1], path.name


# --- Which step gets which ----------------------------------------------


class TestPlacing:
    @pytest.mark.parametrize(
        ("key", "place"),
        [
            ("levain", "levain"), ("levain_rise", "levain_rise"),
            ("autolyse", "autolyse"), ("bulk", "bulk"),
            ("preshape", "preshape"), ("shape", "shape"),
            ("final_rise", "final_rise"), ("preheat", "preheat"),
            ("cool", "cool"),
        ],
    )
    def test_a_planned_step_is_placed_by_its_key(self, key, place):
        assert hint_service.places_for(key, "anything at all") == (place,)

    def test_the_bake_step_is_loading_lid_on_and_lid_off(self):
        assert hint_service.places_for("bake", "Bake in the pot") == (
            "load", "bake", "bake_open",
        )

    def test_a_key_outranks_a_misleading_name(self):
        """"Mix in levain, salt and water" is not the levain build."""
        assert hint_service.places_for("mix", "Mix in levain, salt and water") == ()

    @pytest.mark.parametrize(
        ("name", "places"),
        [
            ("levain build", ("levain",)),
            ("levain rise to peak", ("levain_rise",)),
            ("autolyse", ("autolyse",)),
            ("bulk ferment", ("bulk",)),
            ("pre-shape", ("preshape",)),
            ("shape", ("shape",)),
            ("final proof", ("final_rise",)),
            ("bake (covered)", ("load", "bake")),
            ("bake (uncovered)", ("bake_open",)),
            ("cool", ("cool",)),
            ("mix", ()),
            ("scald (zavarka)", ()),
        ],
    )
    def test_a_recipe_stage_is_placed_by_its_name(self, name, places):
        assert hint_service.places_for(None, name) == places

    def test_pot_hints_stay_off_a_bread_maker_bake(self, session):
        book = hint_service.HintBook(session)

        in_the_pot = book.step(_step("preheat"), _bake(BakeMethod.DUTCH_OVEN))
        in_the_machine = book.step(_step("preheat"), _bake(BakeMethod.BREAD_MAKER))

        assert in_the_pot and not in_the_machine

    def test_bulk_is_where_most_of_them_are(self, session):
        """The step that was misunderstood most gets the most said about it."""
        book = hint_service.HintBook(session)

        assert len(book.step(_step("bulk"), _bake())) >= 5


# --- Putting one away ---------------------------------------------------


class TestGotIt:
    def test_a_dismissed_hint_is_gone_from_every_place(self, client, session):
        before = hint_service.HintBook(session).step(_step("autolyse"), _bake())
        assert [hint.id for hint in before] == ["autolyse-what-it-is"]

        answer = client.post(
            "/hints/autolyse-what-it-is/dismiss",
            data={"next": "/recipes"}, follow_redirects=False,
        )

        assert answer.status_code == 303
        assert answer.headers["location"] == "/recipes"
        session.expire_all()
        book = hint_service.HintBook(session)
        assert book.step(_step("autolyse"), _bake()) == []
        assert book.stage("autolyse") == []

    def test_it_is_one_row_in_settings_and_no_new_table(self, client, session):
        client.post("/hints/cool-an-hour/dismiss")
        client.post("/hints/bake-probe/dismiss")

        session.expire_all()
        row = session.get(Setting, hint_service.DISMISSED_KEY)
        assert row.value == "bake-probe,cool-an-hour"

    def test_htmx_gets_nothing_back_and_takes_the_line_off_itself(self, client):
        answer = client.post(
            "/hints/cool-an-hour/dismiss", headers={"HX-Request": "true"}
        )

        assert answer.status_code == 200
        assert answer.text == ""

    def test_there_is_no_dismissing_a_hint_that_does_not_exist(self, client):
        assert client.post("/hints/no-such-hint/dismiss").status_code == 404

    def test_it_only_ever_sends_you_back_to_this_site(self, client):
        answer = client.post(
            "/hints/cool-an-hour/dismiss",
            data={"next": "//elsewhere.example/x"}, follow_redirects=False,
        )

        assert answer.headers["location"] == "/"

    def test_looking_at_a_page_writes_nothing(self, client, session):
        _jar(session)
        client.get("/")
        client.get("/settings")

        session.expire_all()
        assert session.get(Setting, hint_service.DISMISSED_KEY) is None

    def test_settings_can_bring_them_all_back(self, client, session):
        client.post("/hints/cool-an-hour/dismiss")
        page = client.get("/settings").text
        assert "you have put away 1" in page

        client.post("/hints/restore", follow_redirects=False)

        session.expire_all()
        assert hint_service.dismissed(session) == frozenset()
        assert "all of them are showing" in client.get("/settings").text

    def test_an_id_that_was_retired_does_not_linger(self, session):
        session.add(Setting(key=hint_service.DISMISSED_KEY, value="gone,cool-an-hour"))
        session.commit()

        assert hint_service.dismissed(session) == frozenset({"cool-an-hour"})


# --- On the pages -------------------------------------------------------


class TestOnAJarsPage:
    def test_a_new_jar_is_told_about_the_quiet_days(self, client, session):
        jar = _jar(session, flour_type="bread flour")

        page = client.get(f"/jars/{jar.id}").text

        assert 'id="hint-starter-quiet-days"' in page
        assert "goes quiet for days" in page

    def test_an_old_jar_is_not(self, session):
        jar = _jar(session)
        much_later = datetime.now(UTC) + timedelta(days=60)

        assert hint_service.HintBook(session).jar(jar, much_later) == []

    def test_it_says_the_rhythm_is_the_apps_when_the_jar_has_none(
        self, client, session
    ):
        jar = _jar(session)

        page = client.get(f"/jars/{jar.id}").text

        assert "Every 12 hours." in page
        assert "That is the app's setting, 2 a day" in page

    def test_it_says_the_rhythm_is_the_jars_own_when_it_has_one(
        self, client, session
    ):
        """24 hours set on the wrong jar should be obvious at a glance."""
        jar = _jar(session, feeds_per_day=1)

        page = client.get(f"/jars/{jar.id}").text

        assert "Every 24 hours." in page
        assert "this jar's own rhythm (1 a day)" in page
        assert "The app's setting is 2 a day, every\n      12 hours." in page or (
            "The app's setting is 2 a day" in page and "12 hours" in page
        )

    def test_a_moved_feed_is_shown_as_a_fixed_time_still_in_force(
        self, client, session
    ):
        """A stale anchor is what left the jars "16 hours overdue"."""
        jar = _jar(session)
        jar_service.log_feeding(
            session, jar, starter_g=20, flour_g=40, water_g=40,
            fed_at=datetime.now(UTC) - timedelta(hours=2),
        )
        session.commit()
        plan_service.move_next_feed(
            session, jar, to=datetime.now(UTC) + timedelta(hours=5),
            now=datetime.now(UTC),
        )
        session.commit()

        page = client.get(f"/jars/{jar.id}").text

        assert 'class="anchor-note"' in page
        assert "Fixed at" in page
        assert "Back to the usual rhythm" in page

    def test_a_jar_on_its_usual_rhythm_has_no_such_note(self, client, session):
        jar = _jar(session)

        assert 'class="anchor-note"' not in client.get(f"/jars/{jar.id}").text


class TestElsewhere:
    def test_the_feed_form_says_where_the_jar_sits_sets_the_peak(
        self, client, session
    ):
        jar = _jar(session)

        assert 'id="hint-feed-temperature-times-the-peak"' in client.get(
            f"/jars/{jar.id}/feed"
        ).text

    def test_a_page_with_nothing_to_say_draws_no_empty_box(self, client, session):
        jar = _jar(session)
        client.post("/hints/feed-temperature-times-the-peak/dismiss")

        assert 'class="hints"' not in client.get(f"/jars/{jar.id}/feed").text
