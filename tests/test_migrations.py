"""Migrations must take an empty data dir all the way to the current schema."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

from app.config import PROJECT_ROOT
from app.models import Base


def test_alembic_upgrade_head_from_scratch(tmp_path):
    env = {**os.environ, "ZAKVASKA_DATA_DIR": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    db = tmp_path / "zakvaska.db"
    assert db.is_file()

    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

    assert "alembic_version" in tables
    assert set(Base.metadata.tables) <= tables


def test_models_and_migrations_have_not_drifted(tmp_path):
    """A model change without a migration should fail here."""
    env = {**os.environ, "ZAKVASKA_DATA_DIR": str(tmp_path)}

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, (
        "Models have drifted from the migrations. Run:\n"
        "  .venv/bin/alembic revision --autogenerate -m 'describe the change'\n\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_a_jar_log_database_is_adopted_rather_than_replaced(tmp_path):
    """The rename must not leave an empty database beside the real one.

    Alembic builds its own engine, so it misses the adoption that opening
    the app does — which is exactly how this went wrong once.
    """
    env = {**os.environ, "ZAKVASKA_DATA_DIR": str(tmp_path)}

    first = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert first.returncode == 0, first.stderr

    # Put it back under the old name, as an install from before the rename.
    (tmp_path / "zakvaska.db").rename(tmp_path / "jarlog.db")

    second = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert second.returncode == 0, second.stderr

    assert not (tmp_path / "jarlog.db").exists()
    with sqlite3.connect(tmp_path / "zakvaska.db") as conn:
        stamped = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert stamped is not None
