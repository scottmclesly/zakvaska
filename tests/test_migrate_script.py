"""Bringing the notebook up to date before the app opens it.

This exists because of a real failure: the cap-colour migration shipped with
its commit, but nothing ran it against the live notebook, so the next
`./scripts/run.sh` died on `no such column: jar.cap_color`. run.sh now calls
`scripts/migrate.py` first.

The checks that matter are that it is silent and harmless when there is
nothing to do, that it migrates and backs up when there is, that the backup
is genuinely the state from before, and that run.sh actually calls it —
a guard nothing invokes is not a guard.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "migrate.py"

#: The revision before the one that added jar.cap_color — a real "one behind"
#: rather than a made-up one.
ONE_BEHIND = "6360163c0825"

OLD_JAR_INSERT = (
    "INSERT INTO jar (name, origin, state, feed_interval_room_h,"
    " feed_interval_fridge_h, is_control, archived, created_at)"
    " VALUES ('Old Rye', 'homemade', 'active', 12, 168, 0, 0,"
    " '2026-01-01 00:00:00')"
)


def _run(args, data_dir):
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        env={"ZAKVASKA_DATA_DIR": str(data_dir), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


def _alembic(data_dir, *args):
    result = _run(["-m", "alembic", *args], data_dir)
    assert result.returncode == 0, result.stderr
    return result


def _migrate(data_dir, *args):
    return _run([str(SCRIPT), *args], data_dir)


def _columns(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(jar)")}


def _revision(db: Path) -> str:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


@pytest.fixture
def behind(tmp_path):
    """A notebook one migration behind, with a jar already in it."""
    _alembic(tmp_path, "upgrade", ONE_BEHIND)
    with sqlite3.connect(tmp_path / "zakvaska.db") as conn:
        conn.execute(OLD_JAR_INSERT)
    return tmp_path


@pytest.fixture
def current(tmp_path):
    _alembic(tmp_path, "upgrade", "head")
    return tmp_path


def _backups(data_dir) -> list[Path]:
    return sorted(data_dir.glob("zakvaska.db.before-*"))


# --- Nothing to do ------------------------------------------------------


class TestWhenThereIsNothingToDo:
    def test_it_says_nothing_at_all(self, current):
        result = _migrate(current)

        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_it_does_not_leave_a_backup_behind(self, current):
        """Otherwise every start of the app would drop another copy."""
        _migrate(current)

        assert _backups(current) == []

    def test_check_reports_it(self, current):
        result = _migrate(current, "--check")

        assert result.returncode == 0
        assert "up to date" in result.stdout


# --- Something to do ----------------------------------------------------


class TestWhenTheNotebookIsBehind:
    def test_check_says_so_and_fails(self, behind):
        """A non-zero exit is what lets a script stop on it."""
        result = _migrate(behind, "--check")

        assert result.returncode == 1
        assert "behind" in result.stdout
        assert ONE_BEHIND in result.stdout

    def test_check_changes_nothing(self, behind):
        _migrate(behind, "--check")

        assert _revision(behind / "zakvaska.db") == ONE_BEHIND
        assert _backups(behind) == []

    def test_it_migrates(self, behind):
        result = _migrate(behind)

        assert result.returncode == 0, result.stderr
        assert "cap_color" in _columns(behind / "zakvaska.db")
        assert _revision(behind / "zakvaska.db") != ONE_BEHIND

    def test_the_jars_survive(self, behind):
        _migrate(behind)

        with sqlite3.connect(behind / "zakvaska.db") as conn:
            rows = conn.execute("SELECT name, cap_color FROM jar").fetchall()

        assert rows == [("Old Rye", None)]

    def test_it_backs_the_notebook_up_first(self, behind):
        _migrate(behind)

        assert len(_backups(behind)) == 1

    def test_the_backup_is_the_state_from_before(self, behind):
        """A copy taken after the fact would be no use at all."""
        _migrate(behind)

        backup = _backups(behind)[0]
        assert "cap_color" not in _columns(backup)
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT name FROM jar").fetchall() == [("Old Rye",)]

    def test_it_says_what_it_did(self, behind):
        result = _migrate(behind)

        assert "Backing up" in result.stdout
        assert "Migrating" in result.stdout
        # Its own two lines, not alembic's logging underneath them.
        assert "INFO" not in result.stdout


# --- A notebook that does not exist yet ---------------------------------


class TestAFreshDataDir:
    def test_it_creates_the_database(self, tmp_path):
        result = _migrate(tmp_path)

        assert result.returncode == 0, result.stderr
        assert (tmp_path / "zakvaska.db").is_file()
        assert "cap_color" in _columns(tmp_path / "zakvaska.db")

    def test_there_is_nothing_to_back_up(self, tmp_path):
        _migrate(tmp_path)

        assert _backups(tmp_path) == []


# --- Keeping the backups from piling up ---------------------------------


class TestPruningBackups:
    def _fake(self, data_dir, stamp, *, with_sidecars=False):
        stem = f"zakvaska.db.before-{stamp}"
        (data_dir / stem).write_text("db")
        if with_sidecars:
            (data_dir / f"{stem}-wal").write_text("wal")
            (data_dir / f"{stem}-shm").write_text("shm")

    def test_only_the_newest_few_are_kept(self, behind):
        from scripts.migrate import KEEP_BACKUPS

        for n in range(1, 9):
            self._fake(behind, f"20200101-0000{n:02d}")

        _migrate(behind)

        stems = {
            path.name.split("-wal")[0].split("-shm")[0]
            for path in _backups(behind)
        }
        assert len(stems) == KEEP_BACKUPS

    def test_the_one_just_taken_is_among_them(self, behind):
        for n in range(1, 9):
            self._fake(behind, f"20200101-0000{n:02d}")

        _migrate(behind)

        # The fakes are dated 2020; the real one is dated today.
        assert any("2020" not in path.name for path in _backups(behind))

    def test_a_backup_s_write_ahead_log_goes_with_it(self, behind):
        """A .db without its -wal can be an older notebook than the one the
        app last saw, so the two must be kept and dropped together."""
        for n in range(1, 9):
            self._fake(behind, f"20200101-0000{n:02d}", with_sidecars=True)

        _migrate(behind)

        for path in _backups(behind):
            if path.name.endswith(("-wal", "-shm")):
                stem = path.name.rsplit("-", 1)[0]
                assert (behind / stem).exists(), f"{path.name} outlived its db"


# --- The scripts actually call it ---------------------------------------


class TestTheScriptsCallIt:
    def test_run_sh_migrates_before_it_starts_the_server(self):
        """The whole point: run.sh used to start straight into a crash."""
        text = (PROJECT_ROOT / "scripts" / "run.sh").read_text()

        assert "scripts/migrate.py" in text
        assert text.index("scripts/migrate.py") < text.index("uvicorn")

    def test_run_sh_stops_rather_than_starting_on_a_stale_database(self):
        text = (PROJECT_ROOT / "scripts" / "run.sh").read_text()
        guard = text.split("scripts/migrate.py")[1].split("HOST=")[0]

        assert "exit 1" in guard

    def test_setup_sh_uses_the_same_path(self):
        """Two ways of migrating is two ideas of what up to date means."""
        text = (PROJECT_ROOT / "scripts" / "setup.sh").read_text()

        assert "scripts/migrate.py" in text
        assert "alembic upgrade head" not in text
