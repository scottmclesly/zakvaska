"""The colour of a jar's lid.

Scott's real jars wear different coloured silicone lids, and that is how he
tells them apart on the counter. The column exists so the drawn jar can match
the real one, so the checks that matter are: it survives the form, a bad
colour is refused rather than stored, the colour actually reaches the
drawing, and a jar without one looks exactly as it always did.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.config import PROJECT_ROOT
from app.models.enums import JarOrigin
from app.models.jar import CAP_PRESETS, Jar
from app.routes.forms import opt_color
from app.services import jars as jar_service

import pytest


def _jar(session, name="Old Rye", **fields) -> Jar:
    jar = jar_service.create_jar(
        session, name=name, origin=JarOrigin.HOMEMADE, **fields
    )
    session.commit()
    return jar


def _release(session):
    session.rollback()
    session.expire_all()


def _svg(page: str) -> str:
    found = re.search(r'<svg class="jar-art[^>]*>', page)
    assert found, "no jar drawn on the page"
    return found.group(0)


def _make(client, name, **fields):
    return client.post(
        "/jars/new",
        data={"name": name, "origin": "homemade", "state": "active", **fields},
        follow_redirects=False,
    )


# --- The migration ------------------------------------------------------


def test_the_migration_adds_the_column_to_an_existing_notebook(tmp_path):
    """Upgrading a notebook that predates the colour must keep its jars."""
    env_dir = tmp_path
    one_before = "6360163c0825"

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=PROJECT_ROOT,
            env={"ZAKVASKA_DATA_DIR": str(env_dir), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )

    first = alembic("upgrade", one_before)
    assert first.returncode == 0, first.stderr

    db = Path(env_dir) / "zakvaska.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO jar (name, origin, state, feed_interval_room_h,"
            " feed_interval_fridge_h, is_control, archived, created_at)"
            " VALUES ('Old Rye', 'homemade', 'active', 12, 168, 0, 0,"
            " '2026-01-01 00:00:00')"
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jar)")}
    assert "cap_color" not in columns

    second = alembic("upgrade", "head")
    assert second.returncode == 0, second.stderr

    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jar)")}
        rows = list(conn.execute("SELECT name, cap_color FROM jar"))

    assert "cap_color" in columns
    # The jar is still there, and its colour is simply unset.
    assert rows == [("Old Rye", None)]


def test_the_column_is_nullable_so_no_jar_needs_a_colour():
    column = Jar.__table__.c.cap_color
    assert column.nullable is True
    assert column.type.length == 7


# --- Reading a colour off a form ----------------------------------------


class TestReadingAColour:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("#c0392b", "#c0392b"),
            ("#C0392B", "#c0392b"),   # one spelling is stored
            ("c0392b", "#c0392b"),    # the hash is optional on the way in
            ("#fff", "#ffffff"),      # the short form someone types by hand
            ("  #4a8f5b  ", "#4a8f5b"),
            ("", None),
            (None, None),
        ],
    )
    def test_what_counts_as_a_colour(self, raw, expected):
        assert opt_color(raw, field="Lid colour") == expected

    @pytest.mark.parametrize(
        "raw",
        ["red", "#12345", "#1234567", "rgb(1, 2, 3)", "#ggg", "0x112233"],
    )
    def test_what_does_not(self, raw):
        with pytest.raises(ValueError, match="colour"):
            opt_color(raw, field="Lid colour")


class TestThePresets:
    def test_every_preset_is_a_colour_the_validator_accepts(self):
        for name, value in CAP_PRESETS:
            assert opt_color(value, field="Lid colour") == value, name

    def test_they_are_all_different_and_all_named(self):
        names = [name for name, _ in CAP_PRESETS]
        values = [value for _, value in CAP_PRESETS]
        assert len(set(names)) == len(names)
        assert len(set(values)) == len(values)

    def test_the_ten_the_form_offers(self):
        assert [name for name, _ in CAP_PRESETS] == [
            "black", "white", "grey", "red", "orange",
            "yellow", "green", "blue", "purple", "pink",
        ]


# --- Through the form ---------------------------------------------------


class TestThroughTheForm:
    def test_a_preset_is_stored(self, client, session):
        response = _make(client, "Red Rye", cap_color="#c0392b")

        assert response.status_code == 303
        _release(session)
        jar = session.query(Jar).filter_by(name="Red Rye").one()
        assert jar.cap_color == "#c0392b"

    def test_the_picker_is_read_when_the_radio_points_at_it(
        self, client, session
    ):
        """The swatches and the picker are two controls for one column."""
        response = _make(
            client, "Teal Rye", cap_color="custom", cap_color_custom="#1f8a8a"
        )

        assert response.status_code == 303
        _release(session)
        jar = session.query(Jar).filter_by(name="Teal Rye").one()
        assert jar.cap_color == "#1f8a8a"

    def test_the_picker_is_ignored_when_the_radio_does_not(
        self, client, session
    ):
        """A browser submits the picker whether or not it was touched, so the
        radio has to be what decides."""
        response = _make(
            client, "Red Rye", cap_color="#c0392b", cap_color_custom="#1f8a8a"
        )

        assert response.status_code == 303
        _release(session)
        jar = session.query(Jar).filter_by(name="Red Rye").one()
        assert jar.cap_color == "#c0392b"

    def test_no_colour_stores_null(self, client, session):
        response = _make(client, "Plain Rye", cap_color="")

        assert response.status_code == 303
        _release(session)
        jar = session.query(Jar).filter_by(name="Plain Rye").one()
        assert jar.cap_color is None

    def test_an_invalid_colour_is_refused_and_nothing_is_stored(
        self, client, session
    ):
        response = _make(client, "Bad Rye", cap_color="not-a-colour")

        assert response.status_code == 400
        assert "must be a colour" in response.text
        _release(session)
        assert session.query(Jar).filter_by(name="Bad Rye").count() == 0

    def test_a_refused_colour_leaves_the_rest_of_the_form_filled_in(
        self, client
    ):
        response = _make(
            client, "Bad Rye", cap_color="octarine", culture_name="Soviet rye"
        )

        assert response.status_code == 400
        assert "Soviet rye" in response.text
        assert "Bad Rye" in response.text

    def test_editing_keeps_the_colour_it_was_given(self, client, session):
        jar = _jar(session, cap_color="#c0392b")
        jar_id = jar.id
        _release(session)

        response = client.post(
            f"/jars/{jar_id}/edit",
            data={
                "name": "Old Rye", "origin": "homemade", "state": "active",
                "cap_color": "#4a8f5b",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        _release(session)
        assert session.get(Jar, jar_id).cap_color == "#4a8f5b"

    def test_a_colour_can_be_taken_off_again(self, client, session):
        jar = _jar(session, cap_color="#c0392b")
        jar_id = jar.id
        _release(session)

        client.post(
            f"/jars/{jar_id}/edit",
            data={
                "name": "Old Rye", "origin": "homemade", "state": "active",
                "cap_color": "",
            },
            follow_redirects=False,
        )

        _release(session)
        assert session.get(Jar, jar_id).cap_color is None

    def test_an_unreadable_colour_on_edit_leaves_the_jar_s_own_alone(
        self, client, session
    ):
        jar = _jar(session, cap_color="#c0392b")
        jar_id = jar.id
        _release(session)

        response = client.post(
            f"/jars/{jar_id}/edit",
            data={
                "name": "Old Rye", "origin": "homemade", "state": "active",
                "cap_color": "chartreuse",
            },
            follow_redirects=False,
        )

        assert response.status_code == 400
        _release(session)
        assert session.get(Jar, jar_id).cap_color == "#c0392b"


class TestTheFormShowsWhatIsSet:
    def test_the_matching_preset_comes_back_checked(self, client, session):
        jar = _jar(session, cap_color="#4a8f5b")
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}/edit").text

        after = page.split('name="cap_color" value="#4a8f5b"')[1][:80]
        assert "checked" in after

    def test_a_colour_off_the_presets_checks_the_picker_instead(
        self, client, session
    ):
        jar = _jar(session, cap_color="#1f8a8a")
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}/edit").text

        after = page.split('name="cap_color" value="custom"')[1][:80]
        assert "checked" in after
        # And the picker is holding it, so saving again does not lose it.
        assert 'name="cap_color_custom"' in page
        assert '#1f8a8a' in page.split('name="cap_color_custom"')[1][:120]

    def test_a_jar_with_no_colour_checks_none(self, client, session):
        jar = _jar(session)
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}/edit").text

        after = page.split('name="cap_color" value=""')[1][:80]
        assert "checked" in after

    def test_the_new_jar_form_offers_every_preset(self, client):
        page = client.get("/jars/new").text

        for name, value in CAP_PRESETS:
            assert f'value="{value}"' in page, name
            assert f">{name}<" in page, name


# --- It reaches the drawing ---------------------------------------------


class TestItReachesTheDrawing:
    def test_the_colour_rides_in_on_the_svg_as_a_custom_property(
        self, client, session
    ):
        jar = _jar(session, cap_color="#c0392b")
        jar_id = jar.id
        _release(session)

        svg = _svg(client.get(f"/jars/{jar_id}").text)

        assert "has-cap" in svg
        assert "--cap: #c0392b" in svg

    def test_a_coloured_jar_gets_a_matching_base(self, client, session):
        jar = _jar(session, cap_color="#c0392b")
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}").text

        assert 'class="jar-base"' in page
        assert 'class="jar-base-edge"' in page

    def test_a_jar_with_no_colour_draws_exactly_as_before(
        self, client, session
    ):
        """No class, no custom property, no base: the old picture, untouched."""
        jar = _jar(session)
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}").text
        svg = _svg(page)

        assert "has-cap" not in svg
        assert "--cap" not in svg
        assert "jar-base" not in page

    def test_the_lid_and_the_band_are_left_to_the_stylesheet(
        self, client, session
    ):
        """The colour is data on the <svg>; what is done with it is in
        app.css, so it themes."""
        jar = _jar(session, cap_color="#c0392b")
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}").text
        lid = page.split('class="jar-lid"')[1][:120]

        assert "fill=" not in lid
        css = (PROJECT_ROOT / "app/static/css/app.css").read_text()
        assert ".jar-art.has-cap .jar-lid" in css
        assert ".jar-art.has-cap .jar-band" in css
        assert ".jar-art.has-cap .jar-base" in css


# --- The dot, wherever a jar is named -----------------------------------


class TestTheDot:
    def test_the_dashboard_card_carries_it(self, client, session):
        _jar(session, name="Red Rye", cap_color="#c0392b")
        _release(session)

        page = client.get("/").text

        assert 'class="jar-dot"' in page
        assert "--cap: #c0392b" in page

    def test_a_ribbon_row_carries_it(self, client, session):
        from datetime import timedelta

        from app.models.base import utcnow
        from app.models.feeding import Feeding

        jar = _jar(session, name="Red Rye", cap_color="#c0392b")
        session.add(
            Feeding(
                jar_id=jar.id, fed_at=utcnow() - timedelta(hours=4),
                starter_g=20.0, flour_g=40.0, water_g=40.0,
            )
        )
        session.commit()
        jar_id = jar.id
        _release(session)

        page = client.get(f"/jars/{jar_id}").text

        assert 'class="ribbon-cap"' in page
        row = page.split('class="ribbon-cap"')[1][:160]
        assert "--cap: #c0392b" in row

    def test_an_alert_row_carries_it(self, client, session):
        from datetime import timedelta

        from app.models.alert import Alert
        from app.models.base import utcnow

        jar = _jar(session, name="Red Rye", cap_color="#c0392b")
        due = utcnow() - timedelta(hours=1)
        # Only a fired, unacknowledged alert is on the banner.
        session.add(Alert(jar_id=jar.id, due_at=due, fired_at=due))
        session.commit()
        _release(session)

        page = client.get("/").text

        assert 'class="alert-banner"' in page
        banner = page.split('class="alert-list"')[1].split("</ul>")[0]
        assert 'class="jar-dot"' in banner

    def test_the_plan_form_s_jar_option_carries_the_colour(
        self, client, session
    ):
        _jar(session, name="Red Rye", cap_color="#c0392b")
        _release(session)

        page = client.get("/plan").text

        assert 'style="color: #c0392b"' in page

    def test_the_bake_form_s_jar_option_carries_the_colour(
        self, client, session
    ):
        from tests.test_bake_routes import seed_recipe

        recipe = seed_recipe(session)
        _jar(session, name="Red Rye", cap_color="#c0392b")
        recipe_id = recipe.id
        _release(session)

        page = client.get(f"/bakes/new?recipe_id={recipe_id}&version=1").text

        assert 'style="color: #c0392b"' in page

    def test_a_jar_with_no_colour_gets_no_dot(self, client, session):
        _jar(session, name="Plain Rye")
        _release(session)

        page = client.get("/").text

        assert 'class="jar-dot"' not in page
