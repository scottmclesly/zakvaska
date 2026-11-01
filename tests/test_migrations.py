"""Migrations must take an empty data dir all the way to the current schema."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

from app.config import PROJECT_ROOT
from app.models import Base


def test_alembic_upgrade_head_from_scratch(tmp_path):
    env = {**os.environ, "JARLOG_DATA_DIR": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    db = tmp_path / "jarlog.db"
    assert db.is_file()

    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

    assert "alembic_version" in tables
    assert set(Base.metadata.tables) <= tables


def test_models_and_migrations_have_not_drifted(tmp_path):
    """A model change without a migration should fail here."""
    env = {**os.environ, "JARLOG_DATA_DIR": str(tmp_path)}

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
