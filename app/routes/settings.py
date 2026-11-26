"""Settings: display units, the feeding rhythm, and when the baker is busy.

Everything here is set on the page itself. The two display units used to be
chips in the top bar that stepped to the next value on each tap; they are
picked by name on this page now, so there is one way to set them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models.busy_block import (
    EVERY_DAY,
    MINUTES_PER_DAY,
    WEEKDAY_NAMES,
    BusyBlock,
)
from app.models.enums import BusyKind
from app.models.setting import (
    FEEDS_PER_DAY_CHOICES,
    PREHEAT_OVEN_CHOICES,
    PREHEAT_POT_CHOICES,
    RIBBON_SPAN_CHOICES,
)
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import busy as busy_service
from app.services import measures
from app.services import settings_store
from app.services.units import temp_in, temp_to_celsius
from app.templates_env import render

router = APIRouter(prefix="/settings")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _see_other(url: str = "/settings") -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# --- The page -----------------------------------------------------------


def _page_context(ctx: ViewContext, errors: list[str] | None = None) -> dict:
    session = ctx.session
    return {
        "title": "Settings",
        "errors": errors or [],
        "feeds_per_day": settings_store.feeds_per_day(session),
        "feeds_per_day_choices": FEEDS_PER_DAY_CHOICES,
        "ribbon_span_h": settings_store.ribbon_span_h(session),
        "ribbon_span_choices": RIBBON_SPAN_CHOICES,
        "preheat_pot_min": settings_store.preheat_pot_min(session),
        "preheat_pot_choices": PREHEAT_POT_CHOICES,
        "preheat_oven_min": settings_store.preheat_oven_min(session),
        "preheat_oven_choices": PREHEAT_OVEN_CHOICES,
        # Held in Celsius, typed in whichever unit is on display.
        "ferment_temp": temp_in(
            settings_store.default_ferment_temp_c(session), ctx.temp_unit
        ),
        "blocks": busy_service.list_blocks(session),
        "archived_blocks": [
            block
            for block in busy_service.list_blocks(session, include_archived=True)
            if block.archived
        ],
        "weekday_names": WEEKDAY_NAMES,
        "every_day": EVERY_DAY,
        "unit_cycle": measures.UNIT_CYCLE,
        "temp_units": TEMP_UNITS,
    }


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, ctx: Ctx) -> HTMLResponse:
    return render(
        request=request, ctx=ctx, name="settings/index.html",
        context=_page_context(ctx),
    )


# --- Display units ------------------------------------------------------


#: The two a temperature can be shown in. Held here rather than inferred
#: from a toggle, because the settings page picks one by name.
TEMP_UNITS = ("F", "C")


@router.post("/units")
def save_units(
    request: Request,
    ctx: Ctx,
    weight_unit: Annotated[str, Form()] = "",
    temp_unit: Annotated[str, Form()] = "",
):
    """Both display units at once, each named rather than stepped to.

    These are the only two settings that reach every page: a weight is
    typed and read in whichever unit is chosen here (CLAUDE.md), so one
    place to pick them, naming what you get.
    """
    errors: list[str] = []

    if weight_unit and weight_unit not in measures.UNIT_CYCLE:
        errors.append("That is not a unit amounts can be shown in.")
    if temp_unit and temp_unit.upper() not in TEMP_UNITS:
        errors.append("Temperatures are shown in °C or °F.")

    if errors:
        return render(
            request=request, ctx=ctx, name="settings/index.html",
            context=_page_context(ctx, errors), status_code=400,
        )

    if weight_unit:
        settings_store.set_setting(ctx.session, "weight_unit", weight_unit)
    if temp_unit:
        settings_store.set_setting(
            ctx.session, "temp_unit", temp_unit.upper()
        )
    ctx.session.commit()
    return _see_other()


# --- The feeding rhythm -------------------------------------------------


@router.post("/timing")
def save_timing(
    request: Request,
    ctx: Ctx,
    feeds_per_day: Annotated[str, Form()] = "",
    ribbon_span_h: Annotated[str, Form()] = "",
    ferment_temp: Annotated[str, Form()] = "",
):
    errors: list[str] = []

    try:
        feeds = f.opt_int(feeds_per_day, field="Feeds a day")
        if feeds is not None and feeds not in FEEDS_PER_DAY_CHOICES:
            errors.append("Feeds a day must be one or two.")
        elif feeds is not None:
            settings_store.set_setting(ctx.session, "feeds_per_day", str(feeds))
    except ValueError as exc:
        errors.append(str(exc))

    try:
        span = f.opt_int(ribbon_span_h, field="Ribbon span")
        if span is not None and span not in RIBBON_SPAN_CHOICES:
            errors.append("The ribbon can show 24, 48 or 72 hours.")
        elif span is not None:
            settings_store.set_setting(ctx.session, "ribbon_span_h", str(span))
    except ValueError as exc:
        errors.append(str(exc))

    try:
        typed = f.opt_float(ferment_temp, field="Fermentation temperature")
        celsius = temp_to_celsius(typed, ctx.temp_unit)
        if celsius is not None:
            if not 0.0 <= celsius <= 60.0:
                errors.append("That is not a temperature a starter survives.")
            else:
                settings_store.set_setting(
                    ctx.session, "default_ferment_temp_c", f"{celsius:.2f}"
                )
    except ValueError as exc:
        errors.append(str(exc))

    if errors:
        ctx.session.rollback()
        return render(
            request=request, ctx=ctx, name="settings/index.html",
            context=_page_context(ctx, errors), status_code=400,
        )

    ctx.session.commit()
    return _see_other()


# --- The preheat heads-up -----------------------------------------------


@router.post("/preheat")
def save_preheat(
    request: Request,
    ctx: Ctx,
    preheat_pot_min: Annotated[str, Form()] = "",
    preheat_oven_min: Annotated[str, Form()] = "",
):
    """How much warning the oven needs, per method.

    Two keys rather than one, because the numbers are not the same kind of
    number: a cast-iron pot has to be hot all the way through and a bare
    oven only has to be hot.
    """
    errors: list[str] = []
    wanted: list[tuple[str, str, tuple[int, ...], str]] = [
        (
            "preheat_pot_min",
            preheat_pot_min,
            PREHEAT_POT_CHOICES,
            "The pot preheat must be 30, 45 or 60 minutes.",
        ),
        (
            "preheat_oven_min",
            preheat_oven_min,
            PREHEAT_OVEN_CHOICES,
            "The oven preheat must be 10, 15, 20 or 30 minutes.",
        ),
    ]

    for key, raw, choices, complaint in wanted:
        try:
            minutes = f.opt_int(raw, field="Preheat")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if minutes is None:
            continue
        if minutes not in choices:
            errors.append(complaint)
        else:
            settings_store.set_setting(ctx.session, key, str(minutes))

    if errors:
        ctx.session.rollback()
        return render(
            request=request, ctx=ctx, name="settings/index.html",
            context=_page_context(ctx, errors), status_code=400,
        )

    ctx.session.commit()
    return _see_other()


# --- Busy blocks --------------------------------------------------------


def _minutes(value: str | None, *, field: str) -> int | None:
    """Read an `<input type=time>` — "02:00" — as minutes from midnight."""
    cleaned = f.opt_str(value)
    if cleaned is None:
        return None
    try:
        hours, _, minutes = cleaned.partition(":")
        total = int(hours) * 60 + int(minutes or 0)
    except ValueError:
        raise ValueError(f"{field} must be a time like 02:00") from None
    if not 0 <= total < MINUTES_PER_DAY:
        raise ValueError(f"{field} must be a time of day")
    return total


def _weekday_mask(values: list[str]) -> int:
    mask = 0
    for raw in values:
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(WEEKDAY_NAMES):
            mask |= 1 << index
    return mask


async def _read_block_form(request: Request, ctx: ViewContext) -> tuple[dict, list[str]]:
    """Pull one busy block out of a submission.

    The weekday checkboxes arrive as repeated fields, which FastAPI's `Form`
    does not unpack, so the raw form is read here instead.
    """
    data = await request.form()
    errors: list[str] = []

    label = f.opt_str(str(data.get("label") or ""))
    if label is None:
        errors.append("A busy block needs a name, so the ribbon can say what it is.")

    raw_kind = str(data.get("kind") or BusyKind.RECURRING.value)
    kind = (
        BusyKind.ONCE if raw_kind == BusyKind.ONCE.value else BusyKind.RECURRING
    )

    fields: dict = {"label": label or "", "kind": kind}

    if kind is BusyKind.RECURRING:
        mask = _weekday_mask(
            [str(one) for one in data.getlist("weekdays")]
        )
        if not mask:
            errors.append("Pick at least one day for a block that repeats.")
        try:
            start = _minutes(str(data.get("start_minute") or ""), field="Start")
            end = _minutes(str(data.get("end_minute") or ""), field="End")
        except ValueError as exc:
            errors.append(str(exc))
            start = end = None
        if start is None or end is None:
            errors.append("A block that repeats needs a start and an end time.")
        fields.update(
            weekday_mask=mask, start_minute=start, end_minute=end,
            start_utc=None, end_utc=None,
        )
    else:
        try:
            start_utc = f.local_to_utc(
                str(data.get("start_utc") or ""), ctx.tz, default=ctx.now
            )
            end_utc = f.local_to_utc(
                str(data.get("end_utc") or ""), ctx.tz, default=ctx.now
            )
        except ValueError as exc:
            errors.append(str(exc))
            start_utc = end_utc = ctx.now
        if end_utc <= start_utc:
            errors.append("A one-off block has to end after it starts.")
        fields.update(
            start_utc=start_utc, end_utc=end_utc,
            weekday_mask=None, start_minute=None, end_minute=None,
        )

    return fields, errors


@router.post("/busy")
async def add_busy_block(request: Request, ctx: Ctx):
    fields, errors = await _read_block_form(request, ctx)
    if errors:
        return render(
            request=request, ctx=ctx, name="settings/index.html",
            context=_page_context(ctx, errors), status_code=400,
        )

    ctx.session.add(BusyBlock(**fields))
    ctx.session.commit()
    return _see_other()


@router.post("/busy/{block_id}/edit")
async def edit_busy_block(request: Request, ctx: Ctx, block_id: int):
    block = busy_service.get_block(ctx.session, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="No such busy block")

    fields, errors = await _read_block_form(request, ctx)
    if errors:
        return render(
            request=request, ctx=ctx, name="settings/index.html",
            context=_page_context(ctx, errors), status_code=400,
        )

    for key, value in fields.items():
        setattr(block, key, value)
    ctx.session.commit()
    return _see_other()


@router.post("/busy/{block_id}/archive")
def archive_busy_block(
    ctx: Ctx,
    block_id: int,
    restore: Annotated[str | None, Form()] = None,
):
    """Archived, never deleted — the same bargain as jars and recipes."""
    block = busy_service.get_block(ctx.session, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="No such busy block")

    block.archived = not f.checkbox(restore)
    ctx.session.commit()
    return _see_other()
