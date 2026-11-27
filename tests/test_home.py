def test_home_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "zakvaska" in response.text


def test_home_is_mobile_first(client):
    html = client.get("/").text

    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_home_has_no_jars_yet(client):
    assert "No jars yet" in client.get("/").text


def test_home_links_the_vendored_htmx_not_a_cdn(client):
    html = client.get("/").text

    assert "/static/js/htmx.min.js" in html
    for cdn in ("unpkg.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"):
        assert cdn not in html


# --- The section in the header is the page's heading ----------------------


def test_a_section_page_has_no_visible_title_of_its_own(client):
    """The highlighted section says where you are, so a title under it only
    said it twice. The heading is still there for a screen reader."""
    for path, heading in (
        ("/", "Starter jars"), ("/recipes", "Recipes"), ("/bakes", "Bakes"),
    ):
        page = client.get(path).text
        assert f'<h1 class="sr-only">{heading}</h1>' in page, path
        assert page.count("<h1") == 1, path


def test_a_page_the_header_does_not_name_says_its_own_name(client):
    """Planning is reached from Bakes and equipment is a tab of Settings, so
    neither has a menu item to be its heading."""
    assert "<h1>Plan a bake</h1>" in client.get("/plan").text
    for path in ("/settings", "/equipment"):
        assert "<h1>Settings</h1>" in client.get(path).text, path


def test_the_header_has_three_sections_and_settings(client):
    """Jars, recipes, bakes: what the notebook is. Settings stands apart."""
    page = client.get("/").text
    nav = page.split('<nav class="sectionnav"')[1].split("</nav>")[0]

    assert [
        part.split('"')[0] for part in nav.split('href="')[1:]
    ] == ["/", "/recipes", "/bakes", "/settings"]
    assert nav.count('class="navlink') == 4
    assert 'class="navlink nav-settings' in nav


def test_each_section_explains_itself_in_its_tooltip(client):
    """What used to be the line under the title."""
    page = client.get("/").text
    for blurb in (
        "logged properly",
        "Baker&#39;s percentages, versioned",
        "how it turned out",
        "the bread maker's programs",
    ):
        assert blurb in page, blurb


def test_the_section_you_are_in_is_marked(client):
    for path, label in (
        ("/", "Jars"), ("/recipes", "Recipes"), ("/bakes", "Bakes"),
        # Planning is part of baking; equipment is part of settings.
        ("/plan", "Bakes"), ("/equipment", "Settings"), ("/settings", "Settings"),
    ):
        page = client.get(path).text
        marked = page.split(" is-here\"")[1].split("</a>")[0]
        assert 'aria-current="page"' in marked, path
        assert f"<span>{label}</span>" in marked, path
        assert page.count(" is-here\"") == 1, path


def test_the_header_is_set_in_one_typeface():
    """Two faces side by side in one bar is what this was changed to stop:
    the section you are in is bigger and bolder, never a different font."""
    import re
    from pathlib import Path

    css = re.sub(r"/\*.*?\*/", "", Path("app/static/css/app.css").read_text(), flags=re.S)

    def block(selector):
        found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert found, selector
        return found.group(1)

    assert "font-family: var(--display)" in block("\n.navlink")
    assert "font-family" not in block(".navlink.is-here")
    assert "font-family" not in block(".nav-settings.is-here")


def test_settings_and_equipment_are_tabs_of_one_another(client):
    for path, current in (
        ("/settings", "General"), ("/equipment", "Equipment"), ("/backup", "Backup"),
    ):
        page = client.get(path).text
        tabs = page.split('<nav class="tabs"')[1].split("</nav>")[0]
        for href in ("/settings", "/equipment", "/backup"):
            assert f'href="{href}"' in tabs, (path, href)
        on = tabs.split('class="tab is-current"')[1].split("</a>")[0]
        assert on.rstrip().endswith(current), path


def test_the_planner_is_a_button_on_the_bakes_page(client):
    page = client.get("/bakes").text
    top = page.split('class="bakes-top"')[1].split("</div>")[0]
    assert 'class="form card filters"' in top
    assert 'class="card plan-cta" href="/plan"' in page


# --- The kitchen clock ----------------------------------------------------


def _bake_underway(client, session, *, with_a_jar=True):
    from app.models.enums import JarOrigin
    from app.services import jars as jar_service
    from tests.test_bake_routes import seed_recipe, start

    if with_a_jar:
        jar_service.create_jar(session, name="Rye", origin=JarOrigin.HOMEMADE)
        session.commit()
    return start(client, seed_recipe(session))


def test_a_loaf_underway_shows_its_clock_even_with_no_jars(client, session):
    """A yeasted loaf has no starter behind it; its clock still matters."""
    bake_id = _bake_underway(client, session, with_a_jar=False)

    assert f'class="card bake-clock" href="/bakes/{bake_id}"' in client.get("/").text


def test_a_loaf_underway_puts_a_clock_above_the_slate(client, session):
    bake_id = _bake_underway(client, session)

    page = client.get("/").text
    side = page.split('id="dash-now"')[1]

    assert f'class="card bake-clock" href="/bakes/{bake_id}"' in side
    assert 'class="clock-art"' in side
    # Above the chalkboard, not written on it.
    assert side.index('class="card bake-clock') < side.index('class="chalkboard"')
    assert "bake-clock" not in side.split('class="chalkboard"')[1].split("</aside>")[0]


def test_no_loaf_underway_no_clock(client, session):
    from app.models.enums import JarOrigin
    from app.services import jars as jar_service

    jar_service.create_jar(session, name="Rye", origin=JarOrigin.HOMEMADE)
    session.commit()

    page = client.get("/").text

    assert "bake-clock" not in page
    assert 'class="chalkboard"' in page


def test_the_clock_refreshes_with_the_rest_of_right_now(client, session):
    """Its hands are worked out by the server, so it has to be inside the
    region that asks the server again."""
    _bake_underway(client, session)

    page = client.get("/").text
    region = page.split('id="dash-now"')[1].split('<div class="dash-charts"')[0]

    assert 'hx-select="#dash-now"' in page
    assert "bake-clock" in region


def test_a_finished_loaf_takes_the_clock_down(client, session):
    bake_id = _bake_underway(client, session)
    client.post(f"/bakes/{bake_id}/finish", data={"status": "done"})

    assert "bake-clock" not in client.get("/").text


def test_the_sections_stand_centre_with_the_current_one_in_the_middle():
    """Wider than a phone the header is five tracks, the outer two equal, and
    the current section is placed in the third. The links' order in the page
    does not change: the phone's tab bar and the Tab key rely on it."""
    from pathlib import Path

    css = (
        Path(__file__).resolve().parent.parent / "app/static/css/app.css"
    ).read_text(encoding="utf-8")
    assert "minmax(0, 1fr) var(--side-w) auto var(--side-w) minmax(0, 1fr)" in css
    assert ".sectionnav > .navlink.is-here:not(.nav-settings) { grid-column: 3; }" in css


def test_nav_links_keep_their_order_in_the_page(client):
    for path in ("/", "/recipes", "/bakes", "/settings"):
        nav = client.get(path).text.split('<nav class="sectionnav"')[1].split("</nav>")[0]
        order = [nav.index(f"<span>{label}</span>")
                 for label in ("Jars", "Recipes", "Bakes", "Settings")]
        assert order == sorted(order), path


def test_a_jar_is_edited_from_the_jar_itself_not_the_header(client):
    """Settings has the far end of the header to itself. The way to a jar's
    edit page is the jar: a link around the drawing, with a pencil and a
    caption that the stylesheet shows when it is pointed at."""
    made = client.post(
        "/jars/new",
        data={"name": "Old Rye", "origin": "homemade", "state": "active"},
        follow_redirects=False,
    )
    jar_url = made.headers["location"]
    page = client.get(jar_url).text

    header = page.split('<header class="topbar">')[1].split("</header>")[0]
    assert "/edit" not in header

    link = page.split('<a class="jar-edit"')[1].split("</a>")[0]
    assert f'href="{jar_url}/edit"' in link
    assert 'aria-label="Edit Old Rye"' in link
    assert 'data-tip="Edit this jar"' in link
    assert "jar-edit-pencil" in link and "<svg" in link


def test_settings_is_an_icon_that_names_itself_when_pointed_at():
    from pathlib import Path

    css = (
        Path(__file__).resolve().parent.parent / "app/static/css/app.css"
    ).read_text(encoding="utf-8")
    assert ".nav-settings > span {\n    max-width: 0;" in css
    assert ".nav-settings:focus-visible > span { max-width: 6rem; opacity: 1; }" in css
