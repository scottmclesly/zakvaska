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
