"""The things a release depends on that nothing else would notice breaking."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parent.parent


class TestVersion:
    """One version, written in three places; a release with two is a mess."""

    def test_desktop_app_matches(self):
        cargo = tomllib.loads(
            (ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
        )
        assert cargo["package"]["version"] == app.__version__

    def test_cargo_lock_matches(self):
        lock = tomllib.loads(
            (ROOT / "desktop/src-tauri/Cargo.lock").read_text(encoding="utf-8")
        )
        ours = next(p for p in lock["package"] if p["name"] == "zakvaska-desktop")
        assert ours["version"] == app.__version__

    def test_changelog_leads_with_it(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        newest = re.search(r"^## \[([^\]]+)\]", text, flags=re.MULTILINE)
        assert newest and newest.group(1) == app.__version__

    def test_release_notes_come_out_of_the_changelog(self):
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/release_notes.py"),
             f"v{app.__version__}"],
            capture_output=True, text=True,
        )
        assert done.returncode == 0, done.stderr
        assert "## [" not in done.stdout
        assert len(done.stdout.strip()) > 100

    def test_no_notes_stops_the_release(self):
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/release_notes.py"), "0.0.0"],
            capture_output=True, text=True,
        )
        assert done.returncode == 1


class TestPackaging:
    def test_alembic_ini_is_plain_ascii(self):
        """configparser reads it in the system's encoding. On Windows, and in
        the frozen desktop server, that is not UTF-8, and one typographic
        dash in a comment stops the app starting."""
        (ROOT / "alembic.ini").read_bytes().decode("ascii")

    def test_the_image_carries_no_test_tools(self):
        runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "pytest" not in runtime
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "requirements-dev" not in dockerfile

    def test_compose_needs_no_editing(self):
        """Every ${VARIABLE} in the compose file has a default."""
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for variable in re.findall(r"\$\{([^}]+)\}", compose):
            assert ":-" in variable, variable
        assert "restart: unless-stopped" in compose
        assert "healthcheck:" in compose

    def test_the_frozen_server_ships_what_the_app_reads_from_disk(self):
        spec = (ROOT / "desktop/zakvaska-server.spec").read_text(encoding="utf-8")
        for needed in ("alembic.ini", "migrations", "templates", "static", "tzdata"):
            assert needed in spec, needed


class TestUpdateCheck:
    def test_about_offers_it_and_the_server_does_not_call_out(self, client):
        page = client.get("/about").text
        assert "data-update-check" in page
        assert f'data-current="{app.__version__}"' in page
        assert "api.github.com/repos/scottmclesly/zakvaska/releases/latest" in page
