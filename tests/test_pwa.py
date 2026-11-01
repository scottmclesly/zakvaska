import json


def test_manifest_is_served_and_valid(client):
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")

    manifest = json.loads(response.text)
    assert manifest["name"] == "jar-log"
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"

    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])


def test_service_worker_is_served_from_the_root(client):
    # Scope matters: served from /static it could not control the whole app.
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "addEventListener" in response.text


def test_manifest_icons_all_exist(client):
    manifest = client.get("/manifest.webmanifest").json()

    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]


def test_vendored_htmx_is_served(client):
    response = client.get("/static/js/htmx.min.js")

    assert response.status_code == 200
    assert 'version:"2.0.11"' in response.text


def test_pwa_routes_answer_head(client):
    for path in ("/", "/sw.js", "/manifest.webmanifest", "/favicon.ico"):
        assert client.head(path).status_code == 200, path
