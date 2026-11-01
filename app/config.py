"""Configuration, read from the environment with .env as a fallback.

Deliberately hand-rolled: CLAUDE.md asks us to stay dependency-light, and a
dozen lines here saves a dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "JARLOG_DATA_DIR": "./data",
    "JARLOG_HOST": "127.0.0.1",
    "JARLOG_PORT": "8420",
    "JARLOG_TZ": "America/New_York",
    "JARLOG_SCHEDULER": "1",
}


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

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarlog.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path}"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)


def _env(key: str) -> str:
    return os.environ.get(key) or DEFAULTS[key]


def build_settings() -> Settings:
    load_dotenv()

    data_dir = Path(_env("JARLOG_DATA_DIR")).expanduser()
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()

    tz_name = _env("JARLOG_TZ")
    ZoneInfo(tz_name)  # fail loudly now rather than at render time

    return Settings(
        data_dir=data_dir,
        host=_env("JARLOG_HOST"),
        port=int(_env("JARLOG_PORT")),
        tz_name=tz_name,
        scheduler_enabled=_env("JARLOG_SCHEDULER") not in ("0", "false", "no"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()
