"""Shared Jinja2 environment, so routes and tests agree on filters."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import get_settings

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def local_dt(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a stored UTC timestamp in JARLOG_TZ."""
    if value is None:
        return "—"
    return value.astimezone(get_settings().tz).strftime(fmt)


templates.env.filters["local_dt"] = local_dt
templates.env.globals["app_version"] = __version__
