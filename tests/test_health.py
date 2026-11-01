from app import __version__


def test_health_is_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["timezone"] == "America/New_York"
    assert body["checks"] == {
        "database": True,
        "data_dir_writable": True,
        "photos_dir_writable": True,
    }


def test_health_answers_head(client):
    # Uptime checks often use HEAD; FastAPI does not add it to @get for free.
    assert client.head("/health").status_code == 200
