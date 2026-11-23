"""The empty slot on the shelf that makes a new jar.

It replaced the header button, so the checks that matter are that it is on
the shelf a jar is added to and not the one jars are put away on, that it is
a real link rather than a drawing, and that it is there when the shelf is
empty — because then it is the only way in.

What it looks like is CSS, and CSS is not testable here; what is testable is
that the rules exist and say what they have to say, since "hidden until you
hover" is one typo away from "hidden".
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import PROJECT_ROOT
from app.models.enums import JarOrigin
from app.services import jars as jar_service
from app.templates_env import templates

CSS = (PROJECT_ROOT / "app/static/css/app.css").read_text()


def _jar(session, name="Old Rye", **fields):
    jar = jar_service.create_jar(
        session, name=name, origin=JarOrigin.HOMEMADE, **fields
    )
    session.commit()
    return jar


def _release(session):
    session.rollback()
    session.expire_all()


def _shelves(page: str) -> list[str]:
    """Each <section class="shelf …"> on the page, as its own string."""
    return re.findall(r'<section class="shelf[^"]*".*?</section>', page, re.S)


# --- Where it is --------------------------------------------------------


class TestWhereTheGhostIs:
    def test_it_is_on_the_live_shelf(self, client, session):
        _jar(session)
        _release(session)

        page = client.get("/").text

        assert 'class="shelf-slot shelf-ghost"' in page

    def test_it_is_not_on_the_put_away_shelf(self, client, session):
        """Jars are archived there, never added."""
        jar = _jar(session, name="Old Rye")
        jar_service.set_archived(session, jar, True)
        session.commit()
        _release(session)

        page = client.get("/").text
        shelves = _shelves(page)

        put_away = [one for one in shelves if "shelf-put-away" in one]
        assert put_away, "expected a put-away shelf"
        assert "shelf-ghost" not in put_away[0]

    def test_a_page_with_both_shelves_has_exactly_one_ghost(
        self, client, session
    ):
        _jar(session, name="Living Rye")
        gone = _jar(session, name="Old Rye")
        jar_service.set_archived(session, gone, True)
        session.commit()
        _release(session)

        page = client.get("/").text

        assert len(_shelves(page)) == 2
        assert page.count("shelf-ghost") == 1

    def test_it_is_the_last_slot_before_the_sprig(self, client, session):
        _jar(session)
        _release(session)

        shelf = _shelves(client.get("/").text)[0]

        assert shelf.index("shelf-ghost") > shelf.index("shelf-jar")
        assert shelf.index("shelf-ghost") < shelf.index("shelf-prop")


# --- What it is ---------------------------------------------------------


class TestWhatTheGhostIs:
    def test_it_is_a_real_link_to_the_new_jar_page(self, client, session):
        _jar(session)
        _release(session)

        page = client.get("/").text
        anchor = page.split("shelf-ghost")[1].split(">")[1]

        assert 'href="/jars/new"' in page.split("shelf-ghost")[1][:200]
        assert 'aria-label="New jar"' in page.split("shelf-ghost")[1][:200]
        assert anchor is not None

    def test_the_new_jar_page_itself_is_untouched(self, client):
        assert client.get("/jars/new").status_code == 200

    def test_it_is_drawn_in_the_same_shape_as_a_real_jar(
        self, client, session
    ):
        """A different silhouette and the gap stops reading as a jar."""
        _jar(session)
        _release(session)

        page = client.get("/").text
        body = templates.env.globals["jar_body_path"]

        # Once for the real jar, once for the ghost.
        assert page.count(body) >= 2
        ghost = page.split("shelf-ghost")[1][:600]
        assert body in ghost
        assert "jar-art-shelf" in ghost

    def test_the_shape_is_shared_rather_than_copied(self):
        """Two copies of the path is how the two drift apart."""
        body = templates.env.globals["jar_body_path"]
        templates_dir = PROJECT_ROOT / "app/templates"
        copies = [
            path.relative_to(PROJECT_ROOT)
            for path in templates_dir.rglob("*.html")
            if body in path.read_text()
        ]
        assert copies == [], f"the jar path is written out in {copies}"

    def test_it_carries_a_plus(self, client, session):
        _jar(session)
        _release(session)

        ghost = client.get("/").text.split("shelf-ghost")[1][:600]

        assert "ghost-plus" in ghost

    def test_it_is_hidden_from_a_screen_reader_twice_over(
        self, client, session
    ):
        """The drawing is decoration; the link's aria-label is the name."""
        _jar(session)
        _release(session)

        ghost = client.get("/").text.split("shelf-ghost")[1][:600]

        assert 'aria-hidden="true"' in ghost
        assert 'focusable="false"' in ghost


# --- With no jars at all ------------------------------------------------


class TestWithNoJars:
    def test_the_ghost_is_there(self, client):
        page = client.get("/").text

        assert "shelf-ghost" in page
        assert 'href="/jars/new"' in page

    def test_the_shelf_says_it_is_empty_so_the_ghost_stays_visible(
        self, client
    ):
        page = client.get("/").text

        assert "shelf-is-empty" in page

    def test_the_shelf_is_no_longer_hidden_from_a_screen_reader(self, client):
        """It used to be pure decoration. It now holds the only way in."""
        shelf = _shelves(client.get("/").text)[0]

        assert 'aria-hidden="true"' not in shelf.split(">")[0]
        assert "aria-label=" in shelf.split(">")[0]

    def test_a_shelf_with_jars_on_it_is_not_marked_empty(
        self, client, session
    ):
        _jar(session)
        _release(session)

        assert "shelf-is-empty" not in client.get("/").text


# --- The header button is gone ------------------------------------------


class TestTheHeaderButton:
    def test_the_home_page_no_longer_carries_one(self, client, session):
        _jar(session)
        _release(session)

        page = client.get("/").text
        header = page.split("</header>")[0]

        assert ">New jar<" not in header

    def test_the_shelf_carries_that_job_instead(self, client, session):
        _jar(session)
        _release(session)

        page = client.get("/").text

        assert page.count('href="/jars/new"') >= 1


# --- The rules that decide when it shows --------------------------------


class TestWhenItShows:
    def test_a_pointer_hides_it_until_the_shelf_is_hovered(self):
        block = re.search(
            r"@media \(hover: hover\) \{(.*?)\n\}", CSS, re.S
        )
        assert block, "no (hover: hover) block"
        body = block.group(1)

        assert ".ghost-jar { opacity: 0; }" in body
        assert ".shelf:hover .ghost-jar" in body

    def test_a_touch_screen_always_shows_it(self):
        """A phone cannot hover, so hiding it there would hide it for good."""
        block = re.search(r"@media \(hover: none\) \{(.*?)\n\}", CSS, re.S)
        assert block, "no (hover: none) block"

        assert "opacity: 0.45" in block.group(1)

    def test_an_empty_shelf_shows_it_whatever_the_pointer(self):
        for block in re.findall(r"@media \(hover: [a-z]+\) \{(.*?)\n\}", CSS, re.S):
            assert ".shelf-is-empty .ghost-jar" in block

    def test_the_keyboard_brings_it_back(self):
        assert ".ghost-jar:focus-visible" in CSS
        hover = re.search(r"@media \(hover: hover\) \{(.*?)\n\}", CSS, re.S)
        # Inside the block that hid it, or it stays hidden when tabbed to.
        assert ".ghost-jar:focus-visible" in hover.group(1)

    def test_it_fades_rather_than_appears(self):
        rule = CSS.split(".ghost-jar {")[1].split("}")[0]

        assert "transition" in rule
        assert "opacity" in rule
