"""The app brings its own notebook up to date as it starts.

`run.sh` has always migrated first. But uvicorn can be started without it —
the editor's launch config does, and a systemd unit on the Pi will — and
then a pull that added a column met the next start as `no such column`.
So the runner is called from the app's own startup too.

Each test starts the real app in a subprocess against its own data
directory: the schema version is a property of a database file, and the
test suite's own database is built from the models and has none.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT

#: The revision before the one that added jar.cap_color.
ONE_BEHIND = "6360163c0825"

OLD_JAR_INSERT = (
    "INSERT INTO jar (name, origin, state, feed_interval_room_h,"
    " feed_interval_fridge_h, is_control, archived, created_at)"
    " VALUES ('Old Rye', 'HOMEMADE', 'ACTIVE', 12, 168, 0, 0,"
    " '2026-01-01 00:00:00')"
)

#: Start the app the way uvicorn does, ask it for a page, and stop.
START_THE_APP = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    response = client.get("/")
    print("status", response.status_code)
    print("has-jar", "Old Rye" in response.text)
"""


def _run(args, data_dir, **extra):
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        env={
            "ZAKVASKA_DATA_DIR": str(data_dir),
            "ZAKVASKA_SCHEDULER": "0",
            "PATH": "/usr/bin:/bin",
            **extra,
        },
        capture_output=True,
        text=True,
    )


def _start(data_dir, **extra):
    return _run(["-c", START_THE_APP], data_dir, **extra)


def _alembic(data_dir, *args):
    result = _run(["-m", "alembic", *args], data_dir)
    assert result.returncode == 0, result.stderr


def _columns(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(jar)")}


def _revision(db: Path) -> str:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _head(data_dir) -> str:
    result = _run(["-m", "alembic", "heads"], data_dir)
    return result.stdout.split()[0]


def _backups(data_dir) -> list[Path]:
    return sorted(
        one
        for one in data_dir.glob("zakvaska.db.before-*")
        if not one.name.endswith(("-wal", "-shm"))
    )


@pytest.fixture
def behind(tmp_path):
    """A notebook one migration behind, with a jar already in it."""
    _alembic(tmp_path, "upgrade", ONE_BEHIND)
    with sqlite3.connect(tmp_path / "zakvaska.db") as conn:
        conn.execute(OLD_JAR_INSERT)
    return tmp_path


class TestStartingOnANotebookThatIsBehind:
    def test_the_app_starts_and_serves_the_page(self, behind):
        result = _start(behind)

        assert result.returncode == 0, result.stderr
        assert "status 200" in result.stdout

    def test_the_schema_is_at_head_afterwards(self, behind):
        _start(behind)

        assert "cap_color" in _columns(behind / "zakvaska.db")
        assert _revision(behind / "zakvaska.db") == _head(behind)

    def test_what_was_in_it_is_still_there(self, behind):
        """The promise that matters: an update never costs a jar."""
        result = _start(behind)

        assert "has-jar True" in result.stdout
        with sqlite3.connect(behind / "zakvaska.db") as conn:
            assert conn.execute("SELECT name FROM jar").fetchall() == [("Old Rye",)]

    def test_a_copy_from_before_is_left_beside_it(self, behind):
        _start(behind)

        (backup,) = _backups(behind)
        assert "cap_color" not in _columns(backup)
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT name FROM jar").fetchall() == [("Old Rye",)]


class TestStartingOnANotebookThatIsCurrent:
    def test_a_second_start_changes_nothing_and_copies_nothing(self, behind):
        _start(behind)
        before = _backups(behind)

        result = _start(behind)

        assert result.returncode == 0, result.stderr
        assert _backups(behind) == before

    def test_a_brand_new_data_dir_gets_a_schema_and_no_backup(self, tmp_path):
        result = _start(tmp_path)

        assert result.returncode == 0, result.stderr
        assert "status 200" in result.stdout
        assert _revision(tmp_path / "zakvaska.db") == _head(tmp_path)
        assert _backups(tmp_path) == []


class TestADatabaseItCannotPlace:
    """Tables, but no schema version: refuse, and touch nothing."""

    @pytest.fixture
    def unversioned(self, tmp_path):
        _alembic(tmp_path, "upgrade", ONE_BEHIND)
        with sqlite3.connect(tmp_path / "zakvaska.db") as conn:
            conn.execute(OLD_JAR_INSERT)
            conn.execute("DROP TABLE alembic_version")
        return tmp_path

    def test_the_app_refuses_to_start(self, unversioned):
        result = _start(unversioned)

        assert result.returncode != 0
        assert "no schema version" in result.stderr

    def test_the_notebook_is_left_exactly_as_it_was(self, unversioned):
        _start(unversioned)

        with sqlite3.connect(unversioned / "zakvaska.db") as conn:
            assert conn.execute("SELECT name FROM jar").fetchall() == [("Old Rye",)]
        assert "cap_color" not in _columns(unversioned / "zakvaska.db")

    def test_the_script_says_why_in_one_line(self, unversioned):
        result = _run([str(PROJECT_ROOT / "scripts" / "migrate.py")], unversioned)

        assert result.returncode == 2
        assert result.stderr.startswith("error:")
        assert "Traceback" not in result.stderr


class TestTheSwitch:
    def test_it_can_be_turned_off(self, behind):
        """For the test suite, whose schema comes from the models."""
        _start(behind, ZAKVASKA_MIGRATE="0")

        assert _revision(behind / "zakvaska.db") == ONE_BEHIND
        assert _backups(behind) == []
