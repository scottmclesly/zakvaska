"""Bake pages: the list, starting one, the running sheet, and the result."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models.enums import (
    CRUMB_SUGGESTIONS,
    CRUST_SUGGESTIONS,
    RISE_SUGGESTIONS,
    TASTE_SUGGESTIONS,
    BakeMethod,
    BakeStatus,
    PhotoOwner,
)
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import alerts as alert_service
from app.services import bakes as bake_service
from app.services import followalong
from app.services import jars as jar_service
from app.services import measures
from app.services import photos as photo_service
from app.services import recipes as recipe_service
from app.services import ribbon as ribbon_service
from app.services import scaling
from app.services.units import temp_to_celsius
from app.templates_env import render

router = APIRouter(prefix="/bakes")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _load(ctx: ViewContext, bake_id: int):
    bake = bake_service.get_bake(ctx.session, bake_id)
    if bake is None:
        raise HTTPException(status_code=404, detail="No such bake")
    return bake


def _load_stage(ctx: ViewContext, bake, log_id: int):
    log = bake_service.get_stage(ctx.session, bake, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="No such stage on this bake")
    return log


# --- The list --------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_bakes(
    request: Request,
    ctx: Ctx,
    recipe: int | None = None,
    jar: int | None = None,
    rating: int | None = None,
    status: str | None = None,
) -> HTMLResponse:
    chosen_status = BakeStatus(status) if f.opt_str(status) else None
    found = bake_service.list_bakes(
        ctx.session,
        recipe_id=recipe,
        jar_id=jar,
        min_rating=rating,
        status=chosen_status,
    )
    return render(
        request=request,
        ctx=ctx,
        name="bakes/list.html",
        context={
            "title": "Bakes",
            "bakes": found,
            "options": bake_service.filter_options(ctx.session),
            "filters": {
                "recipe": recipe,
                "jar": jar,
                "rating": rating,
                "status": chosen_status.value if chosen_status else None,
            },
            "any_filter": any(
                value is not None for value in (recipe, jar, rating, chosen_status)
            ),
        },
    )


# --- Starting one ----------------------------------------------------------


def _defaults_for(version, unit: str) -> dict[str, str]:
    """What the recipe says to set the machine to, as form values.

    A seeded West Bend recipe knows its program, loaf size and crust, so
    the form opens with them already filled rather than sending the baker
    back to the manual. Anything the recipe does not say is left blank.
    """
    prefilled = {
        "equipment_program_id": version.default_program_id,
        "loaf_size": version.default_loaf_size,
        "crust_setting": version.default_crust,
    }
    filled = {key: str(value) for key, value in prefilled.items() if value}
    if filled:
        # A recipe that names a program is a bread-maker recipe.
        filled.setdefault("method", BakeMethod.BREAD_MAKER.value)
    if version.batch_flour_g:
        # A recipe written as real amounts already says how much flour it
        # makes, in the unit on display. Changing it rescales the bake.
        filled["total_flour_g"] = measures.input_total_text(
            version.batch_flour_g, unit
        )
    return filled


def _start_context(ctx: ViewContext, version, *, values=None, errors=None) -> dict:
    return {
        "title": f"Bake {version.recipe.name} {version.label}",
        "version": version,
        "recipe": version.recipe,
        "methods": list(BakeMethod),
        "programs": recipe_service.list_programs(ctx.session),
        "jars": jar_service.list_jars(ctx.session),
        "loaf_presets": scaling.loaf_presets(version.ingredients),
        # On a first visit the recipe's defaults fill the form; once the
        # form has been submitted, what the baker typed wins outright.
        "values": values
        if values is not None
        else _defaults_for(version, ctx.weight_unit),
        "flour_placeholder": measures.input_total_placeholder(
            ctx.weight_unit, flour=True
        ),
        "errors": errors or [],
        "now_local": f.utc_to_local_input(ctx.now, ctx.tz),
    }


@router.get("/new", response_class=HTMLResponse)
def new_bake_form(
    request: Request, ctx: Ctx, recipe_id: int, version: int
) -> HTMLResponse:
    found = recipe_service.get_version(ctx.session, recipe_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail="No such recipe version")
    return render(
        request=request,
        ctx=ctx,
        name="bakes/start.html",
        context=_start_context(ctx, found),
    )


@router.post("/new")
def create_bake(
    request: Request,
    ctx: Ctx,
    recipe_id: Annotated[int, Form()],
    version: Annotated[int, Form()],
    method: Annotated[str, Form()] = BakeMethod.OVEN.value,
    jar_id: Annotated[str, Form()] = "",
    equipment_program_id: Annotated[str, Form()] = "",
    crust_setting: Annotated[str, Form()] = "",
    loaf_size: Annotated[str, Form()] = "",
    oven_temp: Annotated[str, Form()] = "",
    bake_min: Annotated[str, Form()] = "",
    total_flour_g: Annotated[str, Form()] = "",
    started_at: Annotated[str, Form()] = "",
    start_now: Annotated[str | None, Form()] = None,
):
    found = recipe_service.get_version(ctx.session, recipe_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail="No such recipe version")

    errors: list[str] = []
    values = {
        "method": method, "jar_id": jar_id,
        "equipment_program_id": equipment_program_id,
        "crust_setting": crust_setting, "loaf_size": loaf_size,
        "oven_temp": oven_temp, "bake_min": bake_min,
        "total_flour_g": total_flour_g, "started_at": started_at,
        "start_now": f.checkbox(start_now),
    }

    try:
        flour = f.opt_total_weight(
            total_flour_g, ctx.weight_unit, field="Total flour", flour=True
        )
    except ValueError as exc:
        errors.append(str(exc))
        flour = None
    if flour is not None and flour < 0:
        errors.append("Total flour cannot be negative.")

    try:
        temp_c = temp_to_celsius(
            f.opt_float(oven_temp, field="Oven temperature"), ctx.temp_unit
        )
    except ValueError as exc:
        errors.append(str(exc))
        temp_c = None

    try:
        minutes = f.opt_int(bake_min, field="Bake time")
    except ValueError as exc:
        errors.append(str(exc))
        minutes = None

    begin = None
    if f.checkbox(start_now):
        begin = ctx.now
    elif f.opt_str(started_at):
        try:
            begin = f.local_to_utc(started_at, ctx.tz, default=ctx.now)
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="bakes/start.html",
            context=_start_context(ctx, found, values=values, errors=errors),
            status_code=400,
        )

    bake = bake_service.start_bake(
        ctx.session,
        found,
        method=BakeMethod(method),
        jar_id=f.opt_int(jar_id, field="Jar"),
        equipment_program_id=f.opt_int(
            equipment_program_id, field="Equipment program"
        ),
        crust_setting=f.opt_str(crust_setting),
        loaf_size=f.opt_str(loaf_size),
        oven_temp_c=temp_c,
        bake_min=minutes,
        total_flour_g=flour,
        started_at=begin,
        status=BakeStatus.IN_PROGRESS if begin else BakeStatus.PLANNED,
    )
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


# --- The running sheet -----------------------------------------------------


def _follow_context(ctx: ViewContext, bake) -> dict:
    """The Now panel and the timeline, for a bake laid out on the clock.

    Both are worked out fresh on every render: planned times are stored,
    but what is underway and what clashes are read off the clock and the
    busy blocks, which may have been edited since the bake began.
    """
    if not followalong.has_plan(bake):
        return {
            "now_view": None, "timeline": None,
            "preheat_at": None, "preheat_lead_min": None,
        }

    intervals = followalong.busy_for(ctx.session, bake, now=ctx.now, tz=ctx.tz)
    steps = followalong.planned_steps(bake, busy=intervals)
    first, last = ribbon_service.timeline_window(
        steps[0].start, steps[-1].end, ctx.now
    )

    span = followalong.preheat_span(bake)
    preheat_log = followalong.preheat_log(bake)
    preheat = (
        ribbon_service.PreheatMark(
            start=span[0], end=span[1],
            lead_min=preheat_log.preheat_lead_min,
        )
        if span is not None and preheat_log is not None
        else None
    )
    return {
        "now_view": followalong.now_view(bake, now=ctx.now, busy=intervals),
        "timeline": ribbon_service.timeline(
            steps,
            start=first,
            end=last,
            now=ctx.now,
            tz=ctx.tz,
            busy=tuple(
                ribbon_service.BusyMark(
                    start=one.start, end=one.end, label=one.label
                )
                for one in intervals
            ),
            preheat=preheat,
        ),
        "preheat_at": span[0] if span else None,
        "preheat_lead_min": (
            preheat_log.preheat_lead_min if preheat_log is not None else None
        ),
    }


@router.get("/{bake_id}", response_class=HTMLResponse)
def bake_detail(request: Request, ctx: Ctx, bake_id: int) -> HTMLResponse:
    bake = _load(ctx, bake_id)
    return render(
        request=request,
        ctx=ctx,
        name="bakes/detail.html",
        context={
            "title": bake.label,
            "bake": bake,
            "scaled": bake_service.scaled(bake),
            "progress": bake_service.progress(bake),
            "planned_total_min": bake_service.planned_total_min(bake),
            "elapsed_min": bake_service.elapsed_min(bake, ctx.now),
            "statuses": list(BakeStatus),
            "photos": photo_service.list_for(ctx.session, PhotoOwner.BAKE, bake.id),
            **_follow_context(ctx, bake),
        },
    )


@router.post("/{bake_id}/stages/{log_id}/start")
def stage_start(ctx: Ctx, bake_id: int, log_id: int):
    bake = _load(ctx, bake_id)
    log = _load_stage(ctx, bake, log_id)
    bake_service.start_stage(ctx.session, bake, log, ctx.now)
    # Doing the step is as good an answer to its alert as dismissing it.
    alert_service.acknowledge_for_stage(ctx.session, log.id, ctx.now)
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/stages/{log_id}/end")
def stage_end(ctx: Ctx, bake_id: int, log_id: int):
    bake = _load(ctx, bake_id)
    log = _load_stage(ctx, bake, log_id)
    bake_service.end_stage(ctx.session, bake, log, ctx.now)
    alert_service.acknowledge_for_stage(ctx.session, log.id, ctx.now)
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/replan")
def replan(ctx: Ctx, bake_id: int):
    """Shift everything still to come, chained from this moment."""
    bake = _load(ctx, bake_id)
    followalong.replan(ctx.session, bake, now=ctx.now)
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/stages/{log_id}/peak")
def stage_peak(
    ctx: Ctx, bake_id: int, log_id: int, at_peak: Annotated[str, Form()] = "1"
):
    """Answer "was it at its peak?" about a rise that has just ended."""
    bake = _load(ctx, bake_id)
    followalong.answer_peak(
        ctx.session, _load_stage(ctx, bake, log_id), at_peak=at_peak == "1"
    )
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/stages/{log_id}/clear")
def stage_clear(ctx: Ctx, bake_id: int, log_id: int):
    bake = _load(ctx, bake_id)
    bake_service.clear_stage(ctx.session, _load_stage(ctx, bake, log_id))
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/stages/{log_id}/note")
def stage_note(
    ctx: Ctx, bake_id: int, log_id: int, notes: Annotated[str, Form()] = ""
):
    bake = _load(ctx, bake_id)
    bake_service.annotate_stage(
        ctx.session, _load_stage(ctx, bake, log_id), f.opt_str(notes)
    )
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/finish")
def finish(ctx: Ctx, bake_id: int, status: Annotated[str, Form()] = BakeStatus.DONE.value):
    bake = _load(ctx, bake_id)
    chosen = BakeStatus(status)
    if chosen.is_finished:
        bake_service.finish_bake(ctx.session, bake, ctx.now, status=chosen)
        # Nothing is still due on a bake that is out of the oven.
        alert_service.acknowledge_for_bake(ctx.session, bake, ctx.now)
    else:
        bake_service.reopen_bake(ctx.session, bake)
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


@router.post("/{bake_id}/archive")
def archive(ctx: Ctx, bake_id: int, archived: Annotated[str, Form()] = "1"):
    bake = _load(ctx, bake_id)
    bake_service.set_archived(ctx.session, bake, archived == "1")
    if archived == "1":
        alert_service.acknowledge_for_bake(ctx.session, bake, ctx.now)
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")


# --- The result ------------------------------------------------------------


def _result_values(bake) -> dict:
    """Editing a result starts from what is already recorded."""
    result = bake.result
    if result is None:
        return {}
    return {
        "rating": result.rating,
        "crust": result.crust or "",
        "crumb": result.crumb or "",
        "taste": result.taste or "",
        "rise": result.rise or "",
        "next_time": result.next_time or "",
    }


@router.get("/{bake_id}/result", response_class=HTMLResponse)
def result_form(request: Request, ctx: Ctx, bake_id: int) -> HTMLResponse:
    bake = _load(ctx, bake_id)
    return render(
        request=request,
        ctx=ctx,
        name="bakes/result.html",
        context={
            "title": f"How was {bake.label}?",
            "bake": bake,
            "values": _result_values(bake),
            "errors": [],
            "crusts": CRUST_SUGGESTIONS,
            "crumbs": CRUMB_SUGGESTIONS,
            "tastes": TASTE_SUGGESTIONS,
            "rises": RISE_SUGGESTIONS,
        },
    )


@router.post("/{bake_id}/result")
def save_result(
    request: Request,
    ctx: Ctx,
    bake_id: int,
    rating: Annotated[str, Form()] = "",
    crust: Annotated[str, Form()] = "",
    crumb: Annotated[str, Form()] = "",
    taste: Annotated[str, Form()] = "",
    rise: Annotated[str, Form()] = "",
    next_time: Annotated[str, Form()] = "",
):
    bake = _load(ctx, bake_id)
    errors: list[str] = []

    try:
        stars = f.opt_int(rating, field="Rating")
    except ValueError as exc:
        errors.append(str(exc))
        stars = None
    if stars is not None and not 1 <= stars <= 5:
        errors.append("Rating goes from 1 to 5.")

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="bakes/result.html",
            context={
                "title": f"How was {bake.label}?",
                "bake": bake,
                "values": {
                    "rating": rating, "crust": crust, "crumb": crumb,
                    "taste": taste, "rise": rise, "next_time": next_time,
                },
                "errors": errors,
                "crusts": CRUST_SUGGESTIONS,
                "crumbs": CRUMB_SUGGESTIONS,
                "tastes": TASTE_SUGGESTIONS,
                "rises": RISE_SUGGESTIONS,
            },
            status_code=400,
        )

    bake_service.save_result(
        ctx.session,
        bake,
        rating=stars,
        crust=f.opt_str(crust),
        crumb=f.opt_str(crumb),
        taste=f.opt_str(taste),
        rise=f.opt_str(rise),
        next_time=f.opt_str(next_time),
        now=ctx.now,
    )
    ctx.session.commit()
    return _see_other(f"/bakes/{bake.id}")
