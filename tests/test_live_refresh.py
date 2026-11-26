"""Pages that tell the time keep telling it, without being reloaded.

Every relative time in this app — "due in 55 min", "fed 3 h ago", the `now`
line down a ribbon — is worked out from one `now`, captured when the request
arrived. Rendered once and left alone it is a clock that stopped, and a
stopped countdown is worse than none: you glance at "55 min" and you are a
quarter of an hour late.

So the regions carrying one refresh themselves, server-rendered, through
htmx. These check the three things that can be got wrong: that each region
asks for something that contains it (a refresh that selects a region absent
from the answer wipes it), that the words really do change when the clock
moves, and that a refresh cannot land on top of something half typed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models.base import utcnow
from app.models.enums import IngredientRole, JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import Recipe, RecipeIngredient, RecipeVersion
from app.services import alerts as alert_service
from app.templates_env import LIVE_REFRESH_S

APP_JS = Path("app/static/js/app.js").read_text()
TZ = ZoneInfo("America/New_York")


def _release(session) -> None:
    session.rollback()
    session.expire_all()


def _jar(session, *, hours_ago: float = 11.0) -> int:
    """A jar fed long enough ago to be close to due, so it has a countdown."""
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


def _bake(client, session) -> str:
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(
        recipe_id=recipe.id, version=1, batch_flour_g=500.0
    )
    session.add(version)
    session.flush()
    session.add(
        RecipeIngredient(
            version_id=version.id, seq=0, name="whole rye flour",
            role=IngredientRole.FLOUR, baker_pct=100.0,
        )
    )
    session.commit()
    version_id = version.id
    _release(session)

    at = (utcnow() + timedelta(minutes=30)).astimezone(TZ).strftime(
        "%Y-%m-%dT%H:%M"
    )
    response = client.post(
        "/plan/start",
        data={"version": str(version_id), "mode": "start", "at": at},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"]


# --- Reading one region out of a page -----------------------------------


class _Region(HTMLParser):
    """The markup inside the element with a given id, tags and all.

    A refresh replaces exactly this, so "is the note field inside it?" is a
    question about this text and not about the page around it.
    """

    #: A void element never opens a level to be closed again.
    VOID = frozenset(
        {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "source", "track", "wbr",
        }
    )

    def __init__(self, wanted: str) -> None:
        super().__init__(convert_charrefs=False)
        self.wanted = wanted
        self.inside = False
        self.found = False
        self.done = False
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if not self.inside:
            if dict(attrs).get("id") == self.wanted:
                self.inside = True
                self.found = True
                self.depth = 0
            return
        self.parts.append(self.get_starttag_text() or "")
        if tag not in self.VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.inside and not self.done:
            self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if self.done or not self.inside:
            return
        if self.depth == 0:
            # The matched element's own close: everything after is outside.
            self.inside = False
            self.done = True
            return
        self.depth -= 1
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.inside and not self.done:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def _inside(html: str, element_id: str) -> str:
    parser = _Region(element_id)
    parser.feed(html)
    assert parser.found, f"no element with id {element_id!r}"
    return "".join(parser.parts)


def test_the_region_reader_finds_a_nested_region():
    """The helper above, checked, so a false negative cannot pass as a pass."""
    html = '<div id="a">one<div id="b">two</div>three</div>after'

    assert _inside(html, "b") == "two"
    assert _inside(html, "a") == 'one<div id="b">two</div>three'
    assert "after" not in _inside(html, "a")


# --- Every region asks for something that contains it -------------------

#: Each live region, and the page it pulls itself out of.
REGIONS = (
    ("/", "home-ribbon"),
    ("/", "dash-now"),
    ("/jars/{jar}", "jar-status"),
    ("/jars/{jar}", "jar-cycle"),
    ("/bakes/{bake}", "bake-live"),
)


class TestEveryRegionRefreshesItself:
    def test_each_one_is_in_the_page_it_asks_for(self, client, session):
        """Otherwise the refresh selects nothing and empties the region."""
        jar = _jar(session)
        bake = _bake(client, session).rsplit("/", 1)[1]

        for path, element_id in REGIONS:
            page = client.get(path.format(jar=jar, bake=bake))
            assert page.status_code == 200, path
            markup = page.text
            assert f'id="{element_id}"' in markup, (path, element_id)
            assert f'hx-select="#{element_id}"' in markup, (path, element_id)
            # And the page it asks for is the one it is on.
            asked = path.format(jar=jar, bake=bake)
            assert f'hx-get="{asked}"' in markup, (path, element_id)

    def test_each_one_swaps_itself_whole(self, client, session):
        jar = _jar(session)
        bake = _bake(client, session).rsplit("/", 1)[1]

        for path, element_id in REGIONS:
            page = client.get(path.format(jar=jar, bake=bake)).text
            attrs = page[: page.index(f'id="{element_id}"') + 400]
            assert 'hx-swap="outerHTML"' in attrs, element_id

    def test_the_banner_wrapper_is_on_every_page(self, client, session):
        jar = _jar(session)
        bake = _bake(client, session)

        for path in ("/", "/plan", "/recipes", "/bakes", "/settings",
                     "/equipment", f"/jars/{jar}", bake):
            page = client.get(path)
            assert page.status_code == 200, path
            assert 'id="alerts-live"' in page.text, path
            assert 'hx-get="/partials/alerts"' in page.text, path

    def test_the_wrapper_is_there_even_with_nothing_to_show(self, client):
        """There has to be something on the page to refresh into."""
        page = client.get("/")

        assert 'id="alerts-live"' in page.text
        assert "alert-banner" not in page.text
        assert _inside(page.text, "alerts-live").strip() == ""


class TestHowOften:
    def test_every_region_is_on_the_same_timer(self, client, session):
        jar = _jar(session)

        page = client.get(f"/jars/{jar}").text

        assert f"every {LIVE_REFRESH_S}s" in page
        # One interval, said once in Python, so no two regions can drift.
        assert "every " in page
        assert page.count(f"every {LIVE_REFRESH_S}s") == page.count("hx-trigger")

    def test_it_also_refreshes_when_the_window_comes_back(
        self, client, session
    ):
        """Chrome slows timers in a hidden window, so looking at it asks.

        This is the one that answers the complaint: whatever the timer did
        while the app was behind something else, bringing it to the front
        fetches the truth before you have finished reading the number.
        """
        jar = _jar(session)

        page = client.get(f"/jars/{jar}").text

        assert "visibilitychange" in page
        assert "document.visibilityState===&#39;visible&#39;" in page
        assert "from:document" in page


# --- The words actually change ------------------------------------------


class TestTheClockMoves:
    """The point of all of it: the same region, later, says something else.

    `now` is taken per request in `routes.deps`, so moving what that returns
    is exactly what moving the wall clock would do to a refresh.
    """

    def _at(self, monkeypatch, moment: datetime) -> None:
        monkeypatch.setattr("app.routes.deps.utcnow", lambda: moment)

    def test_a_jar_card_counts_down(self, client, session, monkeypatch):
        jar = _jar(session, hours_ago=11)
        start = utcnow()

        self._at(monkeypatch, start)
        before = _inside(client.get("/").text, "jar-cards")
        self._at(monkeypatch, start + timedelta(minutes=20))
        after = _inside(client.get("/").text, "jar-cards")

        assert "Next feed" in before
        assert before != after

    def test_a_jar_card_turns_overdue_on_its_own(
        self, client, session, monkeypatch
    ):
        """Not just the words: the state the card is drawn in."""
        jar = _jar(session, hours_ago=11)
        start = utcnow()

        self._at(monkeypatch, start)
        assert "is-overdue" not in _inside(client.get("/").text, "jar-cards")

        self._at(monkeypatch, start + timedelta(hours=3))
        assert "is-overdue" in _inside(client.get("/").text, "jar-cards")

    def test_the_jar_page_keeps_up_too(self, client, session, monkeypatch):
        jar = _jar(session, hours_ago=11)
        start = utcnow()

        self._at(monkeypatch, start)
        before = _inside(client.get(f"/jars/{jar}").text, "jar-status")
        self._at(monkeypatch, start + timedelta(minutes=25))
        after = _inside(client.get(f"/jars/{jar}").text, "jar-status")

        assert "Last fed" in before
        assert before != after

    def test_the_bake_panel_keeps_up(self, client, session, monkeypatch):
        url = _bake(client, session)
        start = utcnow()

        self._at(monkeypatch, start)
        before = _inside(client.get(url).text, "bake-live")
        self._at(monkeypatch, start + timedelta(minutes=40))
        after = _inside(client.get(url).text, "bake-live")

        assert before != after

    def test_the_banner_fills_in_once_an_alert_has_fired(
        self, client, session, monkeypatch
    ):
        """Empty, then the banner — with no reload in between."""
        jar = _jar(session, hours_ago=11)
        start = utcnow()

        self._at(monkeypatch, start)
        assert client.get("/partials/alerts").text.strip() == ""

        # The scheduler is what fires alerts; this is it having run.
        alert_service.reconcile(session, start + timedelta(hours=3))
        session.commit()
        _release(session)

        self._at(monkeypatch, start + timedelta(hours=3))
        filled = client.get("/partials/alerts")

        assert "alert-banner" in filled.text
        assert "Old Rye" in filled.text

    def test_the_banner_counts_up_while_it_is_ignored(
        self, client, session, monkeypatch
    ):
        jar = _jar(session, hours_ago=11)
        start = utcnow()
        alert_service.reconcile(session, start + timedelta(hours=3))
        session.commit()
        _release(session)

        self._at(monkeypatch, start + timedelta(hours=3))
        before = client.get("/partials/alerts").text
        self._at(monkeypatch, start + timedelta(hours=3, minutes=30))
        after = client.get("/partials/alerts").text

        assert before != after


# --- And never lands on top of your typing ------------------------------


class TestNothingTypedIsLost:
    def test_every_refresh_waits_for_an_idle_page(self, client, session):
        jar = _jar(session)

        page = client.get(f"/jars/{jar}").text

        # The filter htmx checks before each tick.
        assert "zakvaskaIdle()" in page

    def test_the_guard_is_served_and_knows_what_a_field_is(self, client):
        response = client.get("/static/js/app.js")

        assert response.status_code == 200
        assert "window.zakvaskaIdle" in response.text
        for tag in ('"INPUT"', '"TEXTAREA"', '"SELECT"'):
            assert tag in APP_JS
        assert "isContentEditable" in APP_JS

    def test_the_guard_cannot_freeze_the_clock(self):
        """The failure that matters more than the one it is guarding.

        A guard that only asked "is the cursor in a field?" would stop every
        refresh for good the moment you clicked a box and switched windows:
        `document.activeElement` goes on naming that field once the window
        loses the keyboard, so the countdown would sit there being wrong —
        the exact bug this all exists to fix. Two things stop that: a quiet
        window measured from the last keystroke, and `hasFocus`, because
        nobody is typing into a window that has not got the keyboard.
        """
        assert "QUIET_MS" in APP_JS
        assert "document.hasFocus()" in APP_JS
        # Measured from the keystroke, so it expires on its own.
        assert "typedAt = Date.now()" in APP_JS
        assert "Date.now() - typedAt < QUIET_MS" in APP_JS

    def test_the_guard_keeps_listening_through_a_swap(self):
        """Its own listeners are replaced by every refresh otherwise."""
        assert 'document.addEventListener(name, function () {' in APP_JS
        # Captured on the document, which no swap replaces.
        assert "}, true);" in APP_JS

    def test_the_running_sheet_is_not_refreshed(self, client, session):
        """Its rows carry a note field each, holding what you typed.

        A note is saved by its own button, so an unsaved one lives only in
        the DOM — and a refresh that replaced it would throw it away while
        you were looking at something else. The countdowns it duplicates
        are all in the Now panel, which does refresh.
        """
        url = _bake(client, session)

        page = client.get(url).text
        live = _inside(page, "bake-live")

        assert 'name="notes"' in page
        assert 'name="notes"' not in live
        assert "stage-run" not in live

    def test_the_now_panel_is_refreshed(self, client, session):
        """The half of the bake page that is nothing but countdowns."""
        url = _bake(client, session)

        live = _inside(client.get(url).text, "bake-live")

        assert "bake-now" in live
        assert "Right now" in live

    def test_no_live_region_holds_a_text_field(self, client, session):
        """The general rule, checked rather than remembered.

        A time field is allowed — the feeding plan has one to move a feed
        to, and the idle guard is what protects it — but a free-text field
        inside a refreshing region would be a sentence waiting to be lost.
        """
        jar = _jar(session)
        bake = _bake(client, session).rsplit("/", 1)[1]

        for path, element_id in REGIONS + (("/", "alerts-live"),):
            markup = _inside(
                client.get(path.format(jar=jar, bake=bake)).text, element_id
            )
            assert "<textarea" not in markup, element_id
            for kind in ('type="text"', 'type="search"'):
                assert kind not in markup, (element_id, kind)
