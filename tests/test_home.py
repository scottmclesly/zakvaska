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
        ("/plan", "Plan a bake"), ("/equipment", "Equipment programs"),
    ):
        page = client.get(path).text
        assert f'<h1 class="sr-only">{heading}</h1>' in page, path
        assert page.count("<h1") == 1, path


def test_each_section_explains_itself_in_its_tooltip(client):
    """What used to be the line under the title."""
    page = client.get("/").text
    for blurb in (
        "logged properly",
        "Baker&#39;s percentages, versioned",
        "how it turned out",
        "does it fit your day",
        "typed in from the manual",
    ):
        assert blurb in page, blurb
    assert page.count('class="navlink') == 5
    assert page.count('title="') >= 5


def test_the_section_you_are_in_is_marked(client):
    for path, label in (("/", "Jars"), ("/recipes", "Recipes"), ("/plan", "Plan")):
        page = client.get(path).text
        marked = page.split('class="navlink is-here"')[1].split("</a>")[0]
        assert 'aria-current="page"' in marked
        assert f"<span>{label}</span>" in marked
