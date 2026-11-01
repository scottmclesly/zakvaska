"""Test setup.

The data dir is redirected to a temp directory *before* anything under `app`
is imported, so no test can ever touch the real ./data.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="jarlog-tests-"))
os.environ["JARLOG_DATA_DIR"] = str(_TMP_DATA_DIR)
os.environ.setdefault("JARLOG_TZ", "America/New_York")
# No background ticking in tests: every test drives reconcile itself, so
# timing is explicit rather than a race with a real clock.
os.environ["JARLOG_SCHEDULER"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker, reset_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    assert get_settings().data_dir == _TMP_DATA_DIR, "tests must not use ./data"
    get_settings().ensure_dirs()
    Base.metadata.create_all(get_engine())
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _clean_tables(_schema):
    """Every test starts from an empty database."""
    engine = get_engine()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def data_dir() -> Path:
    return _TMP_DATA_DIR


@pytest.fixture
def session() -> Iterator[Session]:
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def frozen_now():
    """A fixed instant, so time-based assertions cannot flake."""
    from datetime import UTC, datetime

    return datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
