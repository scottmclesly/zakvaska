"""Configuration, read from the environment with .env as a fallback.

Deliberately hand-rolled: CLAUDE.md asks us to stay dependency-light, and a
dozen lines here saves a dependency.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "ZAKVASKA_DATA_DIR": "./data",
    "ZAKVASKA_HOST": "127.0.0.1",
    "ZAKVASKA_PORT": "8420",
    "ZAKVASKA_TZ": "America/New_York",
    "ZAKVASKA_SCHEDULER": "1",
    "ZAKVASKA_MIGRATE": "1",
}

# This app used to be called jar-log. An .env written then still works.
LEGACY_PREFIX = "JARLOG_"
PREFIX = "ZAKVASKA_"

DB_NAME = "zakvaska.db"
LEGACY_DB_NAME = "jarlog.db"

log = logging.getLogger("zakvaska.config")


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=value lines. Supports comments, blank lines, quoted values."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Load .env into os.environ without overriding what is already set."""
    path = path or PROJECT_ROOT / ".env"
    if not path.is_file():
        return {}
    values = parse_dotenv(path.read_text(encoding="utf-8"))
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str
    port: int
    tz_name: str
    # Off in tests, which drive the alert pass themselves.
    scheduler_enabled: bool = True
    # Off in tests, which build the schema straight from the models.
    migrate_on_start: bool = True

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_NAME

    @property
    def legacy_db_path(self) -> Path:
        return self.data_dir / LEGACY_DB_NAME

    @property
    def db_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path}"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)

    def adopt_legacy_db(self) -> bool:
        """Move a jar-log database to its new name, WAL files and all.

        Opening the new name would otherwise create an empty database beside
        a full one, which looks exactly like losing everything.
        """
        if self.db_path.exists() or not self.legacy_db_path.exists():
            return False
        for suffix in ("", "-wal", "-shm"):
            old = self.legacy_db_path.with_name(LEGACY_DB_NAME + suffix)
            if old.exists():
                old.rename(self.db_path.with_name(DB_NAME + suffix))
        log.info("renamed %s to %s", LEGACY_DB_NAME, DB_NAME)
        return True


def _env(key: str) -> str:
    """Read ZAKVASKA_X, falling back to the old JARLOG_X, then the default."""
    legacy = LEGACY_PREFIX + key.removeprefix(PREFIX)
    return os.environ.get(key) or os.environ.get(legacy) or DEFAULTS[key]


def build_settings() -> Settings:
    load_dotenv()

    data_dir = Path(_env("ZAKVASKA_DATA_DIR")).expanduser()
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()

    tz_name = _env("ZAKVASKA_TZ")
    ZoneInfo(tz_name)  # fail loudly now rather than at render time

    return Settings(
        data_dir=data_dir,
        host=_env("ZAKVASKA_HOST"),
        port=int(_env("ZAKVASKA_PORT")),
        tz_name=tz_name,
        scheduler_enabled=_env("ZAKVASKA_SCHEDULER") not in ("0", "false", "no"),
        migrate_on_start=_env("ZAKVASKA_MIGRATE") not in ("0", "false", "no"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()
