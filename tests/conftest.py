"""Test setup.

The data dir is redirected to a temp directory *before* anything under `app`
is imported, so no test can ever touch the real ./data.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="jarlog-tests-"))
os.environ["JARLOG_DATA_DIR"] = str(_TMP_DATA_DIR)
os.environ.setdefault("JARLOG_TZ", "America/New_York")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, reset_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    assert get_settings().data_dir == _TMP_DATA_DIR, "tests must not use ./data"
    get_settings().ensure_dirs()
    Base.metadata.create_all(get_engine())
    yield
    reset_engine()


@pytest.fixture
def data_dir() -> Path:
    return _TMP_DATA_DIR


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c
