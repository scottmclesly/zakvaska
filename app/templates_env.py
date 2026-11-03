"""Shared Jinja2 environment, so routes and tests agree on filters."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import get_settings
from app.services import alerts as alert_service
from app.services import measures
from app.services import recipes as recipe_service
from app.services.units import (
    format_temp,
    humanize_since,
    humanize_until,
    temp_in,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def local_dt(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a stored UTC timestamp in ZAKVASKA_TZ."""
    if value is None:
        return "—"
    return value.astimezone(get_settings().tz).strftime(fmt)


def local_day(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(get_settings().tz).strftime("%a %d %b")


def local_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(get_settings().tz).strftime("%H:%M")


def grams(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} g"


def num(value: object) -> str:
    """Bare number without pointless decimals, for form inputs.

    Takes whatever the form round-trip hands back: on a validation error the
    value is still the raw string the user typed, and echoing that unchanged
    is exactly right — they should see their own input, mistakes included.
    """
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.2f}".rstrip("0").rstrip(".") or "0"


def mm(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} mm"


def percent(value: float | None, places: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{places}f}%"


def temp_value(celsius: float | None, unit: str) -> str:
    """Bare number in the display unit, for a form input's value."""
    converted = temp_in(celsius, unit)
    return "" if converted is None else f"{converted:.0f}"


def weigh(
    value: float | None,
    unit: str = measures.METRIC,
    name: str | None = None,
    role: object | None = None,
) -> str:
    """A stored weight in whichever unit the reader has chosen."""
    if value is None:
        return "\u2014"
    shown = measures.measure(value, unit, name=name, role=role)
    return shown.text if shown else "\u2014"


def weigh_total(value: float | None, unit: str = measures.METRIC) -> str:
    """A total, which never makes sense in cups. See measures.measure_total."""
    if value is None:
        return "\u2014"
    shown = measures.measure_total(value, unit)
    return shown.text if shown else "\u2014"


def filesize(value: int | None) -> str:
    """Bytes in the units a person reads, not the ones a disk counts in."""
    if not value:
        return "0 KB"
    size = float(value)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:.1f}".rstrip("0").rstrip(".") + f" {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def since(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "never"
    return humanize_since(value, now)


def until(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "—"
    return humanize_until(value, now)


templates.env.filters.update(
    local_dt=local_dt,
    local_day=local_day,
    local_time=local_time,
    grams=grams,
    weigh=weigh,
    weigh_total=weigh_total,
    filesize=filesize,
    mm=mm,
    num=num,
    percent=percent,
    since=since,
    until=until,
    temp=format_temp,
    temp_value=temp_value,
)
templates.env.globals["app_version"] = __version__


def _asset_version() -> str:
    """Changes whenever the CSS or JS does, so caches let go of the old one.

    The version number alone is not enough: it does not move between
    releases, and a Raspberry Pi that has been running for a month will
    happily keep serving last month's stylesheet.
    """
    newest = 0.0
    static = Path(__file__).resolve().parent / "static"
    for folder in ("css", "js"):
        for asset in (static / folder).glob("*"):
            if asset.is_file():
                newest = max(newest, asset.stat().st_mtime)
    return f"{__version__}-{int(newest)}"


templates.env.globals["asset_version"] = _asset_version()
templates.env.globals["unit_label"] = lambda unit: measures.UNIT_LABELS.get(
    unit, measures.UNIT_LABELS[measures.METRIC]
)
templates.env.globals["next_unit"] = measures.next_unit
# The pages that draw these walk the cycles and stages themselves, so they
# ask for the bar rather than having one threaded through every route.
templates.env.globals["cycle_bar"] = recipe_service.cycle_bar
templates.env.globals["stage_bar"] = recipe_service.stage_bar


def render(
    *,
    request: Request,
    name: str,
    ctx: Any = None,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
):
    """TemplateResponse plus the per-request bits every page needs.

    Saves threading `now`, `tz` and the display temperature unit through every
    route by hand, and keeps them impossible to forget.
    """
    merged: dict[str, Any] = dict(context or {})
    if ctx is not None:
        merged.setdefault("now", ctx.now)
        merged.setdefault("tz", ctx.tz)
        merged.setdefault("temp_unit", ctx.temp_unit)
        merged.setdefault("weight_unit", ctx.weight_unit)
        # Every page carries the alert banner, so no page can forget it.
        merged.setdefault(
            "alerts", alert_service.showing(ctx.session, ctx.now)
        )
        merged.setdefault("snooze_choices", alert_service.SNOOZE_CHOICES)
    return templates.TemplateResponse(
        request=request, name=name, context=merged, status_code=status_code
    )
