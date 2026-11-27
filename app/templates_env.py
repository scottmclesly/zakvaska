"""Shared Jinja2 environment, so routes and tests agree on filters."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from app import __version__
from app.config import get_settings
from app import buildinfo
from app.services import alerts as alert_service
from app.services import hints as hint_service
from app.services import settings_store
from app.services import measures
from app.services import bakeplan
from app.services import plan as plan_service
from app.services import timing
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


def weigh_total(
    value: float | None, unit: str = measures.METRIC, flour: bool = False
) -> str:
    """A total. Flour reads in cups, dough never does. See measure_total."""
    if value is None:
        return "\u2014"
    shown = measures.measure_total(value, unit, flour=flour)
    return shown.text if shown else "\u2014"


def weigh_input(
    value: object = None,
    unit: str = measures.METRIC,
    name: str | None = None,
    role: object | None = None,
) -> str:
    """A stored weight as an editable field value. See measures.input_text.

    A string comes straight back: after a failed submission the value is
    still what the user typed, and showing them their own words — "1 cuup"
    included — beats showing them a reformatted guess. Same bargain as `num`.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return measures.input_text(value, unit, name=name, role=role)


def weigh_total_input(
    value: object = None, unit: str = measures.METRIC, flour: bool = False
) -> str:
    """The editable form of a total, in the unit its label claims."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return measures.input_total_text(float(value), unit, flour=flour)


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
    weigh_input=weigh_input,
    weigh_total_input=weigh_total_input,
    filesize=filesize,
    mm=mm,
    num=num,
    percent=percent,
    since=since,
    until=until,
    temp=format_temp,
    temp_value=temp_value,
    headline=alert_service.headline,
)
templates.env.globals["app_version"] = __version__
#: The commit this copy runs from, or None where there is no git to ask.
templates.env.globals["app_build"] = buildinfo.build()


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
# What a weight field accepts, said once so every hint agrees.
templates.env.globals["amount_examples"] = measures.EXAMPLES
# A total's unit: cups for flour, never for dough. See measure_total.
templates.env.globals["total_unit_label"] = measures.total_unit_label
# The pages that draw these walk the cycles and stages themselves, so they
# ask for the bar rather than having one threaded through every route.
# The nudge buttons beside a planned feed name themselves.
templates.env.globals["nudge_label"] = plan_service.nudge_label
# "4.5 h", "2 d 2 h" — a span of hours as a person says it.
templates.env.globals["hours_label"] = timing.hours_label
#: The glyph a step or stage is drawn with: see services.hints.icon_for.
templates.env.globals["step_icon"] = hint_service.icon_for
# "1:4:4" — a feed ratio as a baker writes it.
templates.env.filters["ratio_label"] = timing.ratio_label
# The planner's slider labels its own ends, which needs arithmetic on `now`.
templates.env.globals["timedelta_minutes"] = lambda minutes: timedelta(
    minutes=minutes
)
# The silhouette of a jar, said once. Three templates draw it — the jar
# itself, the outline on an empty shelf, and the ghost slot that adds one —
# and they have to be the same shape or the ghost stops reading as a jar.
templates.env.globals["jar_body_path"] = (
    "M24 18 h24 v4 q0 3 5 6 q5 3 5 10 v52 q0 8 -8 8 h-28 "
    "q-8 0 -8 -8 v-52 q0 -7 5 -10 q5 -3 5 -6 z"
)
# --- Regions that tell the time -----------------------------------------
#
# Every relative time on every page — "due in 55 min", "fed 3 h ago", the
# `now` line down a ribbon — is worked out from one `now`, captured when the
# request arrived. Left alone it is a clock that stopped: you glance at "55
# min" and you are a quarter of an hour late. So the handful of regions that
# carry one ask the server again, on a timer and whenever the window comes
# back to the front. Server-rendered, which is the point: the words come
# from `humanize_delta` either way, so a refreshed countdown and a reloaded
# one cannot word the same span differently.

#: How often such a region asks again. Half a minute: a countdown shown to
#: the minute is never more than 30 seconds stale, and on a LAN against
#: SQLite the request costs less than drawing the page it lands in.
LIVE_REFRESH_S = 30

#: Skipped while you are typing, so a refresh never takes a half-written
#: note or a time you were in the middle of picking. `zakvaskaIdle` is in
#: app.js; a browser with no JS gets no refresh and no broken page.
_IDLE = "zakvaskaIdle()"
_VISIBLE = f"document.visibilityState==='visible'&&{_IDLE}"


def live(get: str, select: str | None = None) -> Markup:
    """The attributes that make one region refresh itself.

    `select` names the region inside the full page it is pulled out of, so
    most of these need no endpoint of their own: the page re-renders and the
    region picks itself out of it. Without one, `get` is expected to be a
    partial and its whole answer goes inside.
    """
    trigger = (
        f"every {LIVE_REFRESH_S}s[{_IDLE}], "
        f"visibilitychange[{_VISIBLE}] from:document"
    )
    parts = [f'hx-get="{escape(get)}"']
    if select:
        parts.append(f'hx-select="{escape(select)}" hx-swap="outerHTML"')
    else:
        parts.append('hx-swap="innerHTML"')
    parts.append(f'hx-trigger="{escape(trigger)}"')
    return Markup(" ".join(parts))


templates.env.globals["live"] = live
templates.env.globals["live_refresh_s"] = LIVE_REFRESH_S
templates.env.globals["bakeplan_default_knead"] = bakeplan.DEFAULT_KNEAD_MIN
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
        # The hints, less the ones put away: any page can ask for its own.
        merged.setdefault("hints", hint_service.HintBook(ctx.session))
        # What "the app's setting" is, wherever a jar's rhythm is explained.
        merged.setdefault(
            "app_feeds_per_day", settings_store.feeds_per_day(ctx.session)
        )
    return templates.TemplateResponse(
        request=request, name=name, context=merged, status_code=status_code
    )
