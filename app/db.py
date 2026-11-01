"""Engine and session plumbing.

SQLite needs two nudges: foreign keys are off by default, and WAL makes
concurrent reads (phone + laptop) far less bite-y.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def make_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    settings.ensure_dirs()
    return create_engine(settings.db_url, future=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_sessionmaker()() as session:
        yield session


def reset_engine() -> None:
    """Drop cached engine/sessionmaker. Used by tests after changing config."""
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
