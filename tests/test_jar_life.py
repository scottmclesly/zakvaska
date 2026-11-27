"""The drawn jar, alive: one value decides how it moves.

`Life` is read off what the notebook already knows — the jar's state, where
it is between feeds, whether its feed has come due — and the drawing carries
it as a class. Everything that moves is in the stylesheet, keyed on that
class, and all of it sits behind `prefers-reduced-motion: no-preference`.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from app.config import PROJECT_ROOT
from app.models.base import utcnow
from app.models.enums import JarOrigin, JarState
from app.services import jars as jar_service
from app.services.jars import Life, life_of
from app.services.timing import Band

CSS = (PROJECT_ROOT / "app" / "static" / "css" / "app.css").read_text()


def make_jar(session, *, name="Homemade rye", state=JarState.ACTIVE, **fields):
    jar = jar_service.create_jar(
        session, name=name, origin=JarOrigin.HOMEMADE, state=state,
        feeds_per_day=2, **fields,
    )
    session.commit()
    return jar


def fed_ago(session, jar, hours: float):
    jar_service.log_feeding(
        session, jar, fed_at=utcnow() - timedelta(hours=hours),
        starter_g=20, flour_g=20, water_g=20, ambient_temp_c=25.5,
    )
    session.commit()


def life_on_page(body: str) -> str:
    match = re.search(r'data-life="(\w+)"', body)
    assert match, body[:400]
    return match.group(1)


class TestTheOneValue:
    @pytest.mark.parametrize(
        "band, overdue, expected",
        [
            (Band.RISING, False, Life.ACTIVE),
            (Band.PEAK, False, Life.ACTIVE),
            (Band.OK, False, Life.HUNGRY),
            (Band.PAST, False, Life.HUNGRY),
            (Band.HUNGRY, False, Life.OVERDUE),
            (Band.PEAK, True, Life.OVERDUE),
            (Band.OK, True, Life.OVERDUE),
            (None, False, Life.ACTIVE),
            (None, True, Life.OVERDUE),
        ],
    )
    def test_an_active_jar(self, session, band, overdue, expected):
        jar = make_jar(session)

        assert life_of(jar, band, overdue) is expected

    @pytest.mark.parametrize(
        "state", [JarState.FRIDGE, JarState.DORMANT, JarState.DRIED]
    )
    def test_a_jar_that_is_asleep_is_resting_whatever_else_is_true(self, session, state):
        """Asleep is not dying: no haze over a jar put away on purpose."""
        jar = make_jar(session, state=state)

        assert life_of(jar, Band.HUNGRY, True) is Life.RESTING

    def test_an_archived_jar_is_resting(self, session):
        jar = make_jar(session)
        jar.archived = True

        assert life_of(jar, Band.PEAK, False) is Life.RESTING

    def test_the_band_may_arrive_as_its_name(self, session):
        """Which is how a template hands it over."""
        jar = make_jar(session)

        assert life_of(jar, "past") is Life.HUNGRY
        assert life_of(jar, "") is Life.ACTIVE


class TestTheDrawingCarriesIt:
    def test_a_jar_just_fed_is_active(self, client, session):
        jar = make_jar(session)
        fed_ago(session, jar, 1)

        body = client.get(f"/jars/{jar.id}").text

        assert life_on_page(body) == "active"
        assert "life-active" in body
        assert 'class="jar-fizz"' in body

    def test_a_jar_past_its_peak_is_hungry(self, client, session):
        jar = make_jar(session)
        fed_ago(session, jar, 7)   # 1:1:1 at 25.5 °C peaks at five hours

        assert life_on_page(client.get(f"/jars/{jar.id}").text) == "hungry"

    def test_a_jar_whose_feed_has_come_due_is_overdue_and_hazy(self, client, session):
        jar = make_jar(session)
        fed_ago(session, jar, 13)  # twice a day: due an hour ago

        body = client.get(f"/jars/{jar.id}").text

        assert life_on_page(body) == "overdue"
        assert 'class="jar-haze"' in body

    def test_only_an_overdue_jar_has_the_haze(self, client, session):
        jar = make_jar(session)
        fed_ago(session, jar, 1)

        assert "jar-haze" not in client.get(f"/jars/{jar.id}").text

    def test_a_jar_in_the_fridge_is_resting(self, client, session):
        jar = make_jar(session, state=JarState.FRIDGE)

        body = client.get(f"/jars/{jar.id}").text

        assert life_on_page(body) == "resting"
        assert "jar-haze" not in body

    def test_the_shelf_and_the_jar_s_own_page_agree(self, client, session):
        jar = make_jar(session)
        fed_ago(session, jar, 13)

        assert life_on_page(client.get("/").text) == life_on_page(
            client.get(f"/jars/{jar.id}").text
        )

    def test_a_put_away_jar_on_the_lower_shelf_is_resting(self, client, session):
        jar = make_jar(session)
        fed_ago(session, jar, 1)
        jar.archived = True
        session.commit()

        body = client.get("/").text

        assert 'data-life="resting"' in body
        assert 'data-life="active"' not in body

    def test_jars_are_staggered_so_a_shelf_does_not_bubble_in_step(self, client, session):
        make_jar(session, name="One")
        make_jar(session, name="Two")

        phases = re.findall(r'style="--j: (\d)', client.get("/").text)

        assert len(phases) == 2 and phases[0] != phases[1]


class TestTheMotion:
    """Read from the stylesheet itself: these are promises about it."""

    def _motion_block(self) -> str:
        start = CSS.index("The jar, alive")
        opens = CSS.index("@media (prefers-reduced-motion: no-preference)", start)
        depth, at = 0, CSS.index("{", opens)
        for at in range(at, len(CSS)):
            depth += {"{": 1, "}": -1}.get(CSS[at], 0)
            if depth == 0:
                break
        return CSS[opens : at + 1]

    def _jar_section(self) -> str:
        start = CSS.index("The jar, alive")
        return CSS[start : CSS.index(".jar-flake", start)]

    def test_every_jar_animation_is_behind_no_preference(self):
        """So a reader who asked for less motion gets the still drawing."""
        section = self._jar_section()
        outside = section.replace(self._motion_block(), "")
        outside = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", outside)
        outside = re.sub(r"/\*.*?\*/", "", outside, flags=re.S)

        assert "animation" not in outside

    def test_each_living_state_moves_in_its_own_way(self):
        block = self._motion_block()

        assert ".life-active .jar-fizz" in block
        assert ".life-hungry .jar-fizz" in block
        assert ".life-overdue .jar-haze" in block

    def test_an_overdue_or_resting_jar_s_bubbles_do_not_move(self):
        block = self._motion_block()

        assert ".life-overdue .jar-fizz" not in block
        assert ".life-overdue .jar-foam" not in block
        assert "life-resting" not in block

    def test_a_hungry_jar_is_slower_than_an_active_one(self):
        block = self._motion_block()
        beat = {
            name: float(seconds)
            for name, seconds in re.findall(
                r"\.life-(\w+) \{ --beat: ([\d.]+)s", block
            )
        }

        assert beat["hungry"] >= 2 * beat["active"]

    def test_only_transform_and_opacity_are_animated(self):
        """Cheap to draw however many jars are on the shelf."""
        section = self._jar_section()
        frames = re.findall(
            r"@keyframes jar-[\w-]+\s*\{((?:[^{}]*\{[^{}]*\})*)", section
        )
        assert len(frames) == 3

        animated = set()
        for body in frames:
            animated |= set(re.findall(r"([a-z-]+)\s*:", body))

        assert animated <= {"transform", "opacity"}

    def test_no_script_is_involved(self):
        js = (PROJECT_ROOT / "app" / "static" / "js" / "app.js").read_text()

        assert "jar-fizz" not in js and "data-life" not in js
