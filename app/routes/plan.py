"""The bake-day planner: /plan.

Nothing is stored. The whole plan is recomputed from the query string on
every request, which is what lets the start-time slider scrub it live over
HTMX and what makes a plan shareable as a link. Phase D is where a plan
becomes a bake with its times written down.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.models.jar import Jar
from app.models.recipe import EquipmentProgram, RecipeVersion
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import bakeplan
from app.services import busy as busy_service
from app.services import jars as jar_service
from app.services import plan as plan_service
from app.services import recipes as recipe_service
from app.services import ribbon as ribbon_service
from app.services import settings_store
from app.services.bakeplan import PlanInputs
from app.services.units import temp_in, temp_to_celsius
from app.templates_env import render

router = APIRouter(prefix="/plan")

Ctx = Annotated[ViewContext, Depends(get_view_context)]

#: How far the start-time slider reaches, and how finely it moves.
SLIDER_HOURS = 48
SLIDER_STEP_MIN = 15


def _version(ctx: ViewContext, version_id: int | None) -> RecipeVersion | None:
    if version_id is None:
        return None
    return ctx.session.get(RecipeVersion, version_id)


def _jar(ctx: ViewContext, jar_id: int | None) -> Jar | None:
    if jar_id is None:
        return None
    return ctx.session.get(Jar, jar_id)


def _program(ctx: ViewContext, program_id: int | None) -> EquipmentProgram | None:
    if program_id is None:
        return None
    return ctx.session.get(EquipmentProgram, program_id)


def _read_inputs(
    ctx: ViewContext, params, *, version: RecipeVersion | None
) -> tuple[PlanInputs, list[str]]:
    """Build the inputs from the query string, over the sensible defaults.

    Every field is optional and anything unreadable falls back rather than
    erroring: the planner is a thing to fiddle with, and a half-typed number
    should not take the page away.
    """
    inputs = bakeplan.default_inputs(
        ctx.session, version, now=ctx.now, jar=_jar(ctx, _int(params, "jar"))
    )
    notes: list[str] = []

    def number(name: str) -> float | None:
        raw = params.get(name)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            notes.append(f"{name} was not a number, so the usual value was used.")
            return None

    total_flour = None
    if params.get("flour") not in (None, ""):
        try:
            total_flour = f.opt_total_weight(
                params.get("flour"), ctx.weight_unit, field="Total flour"
            )
        except ValueError as exc:
            notes.append(str(exc))

    levain_ratio = number("ratio")
    levain_temp = number("temp")
    knead_min = number("knead")
    final_rise = number("rise")
    bake_min = number("bake_min")
    bake_temp = number("bake_temp")
    cool_min = number("cool")

    mode = params.get("mode") or "start"
    start_at = inputs.start_at
    ready_by = None
    when = params.get("at")
    if when:
        try:
            moment = f.local_to_utc(when, ctx.tz, default=ctx.now)
        except ValueError:
            notes.append("That was not a time I could read.")
            moment = ctx.now
        if mode == "ready":
            ready_by = moment
            start_at = None
        else:
            start_at = moment

    # The slider sends an offset in minutes from now, which keeps it a plain
    # <input type=range> with no date arithmetic in the browser.
    offset = params.get("offset")
    if offset not in (None, ""):
        try:
            moved = ctx.now + timedelta(minutes=int(float(offset)))
        except (TypeError, ValueError):
            moved = None
        if moved is not None:
            if mode == "ready":
                ready_by, start_at = moved, None
            else:
                start_at, ready_by = moved, None

    program_id = _int(params, "program")
    loaf = number("loaf")

    return (
        replace(
            inputs,
            total_flour_g=(
                total_flour if total_flour is not None else inputs.total_flour_g
            ),
            start_at=start_at,
            ready_by=ready_by,
            levain_ratio=(
                levain_ratio if levain_ratio is not None else inputs.levain_ratio
            ),
            levain_temp_c=(
                temp_to_celsius(levain_temp, ctx.temp_unit)
                if levain_temp is not None
                else inputs.levain_temp_c
            ),
            levain_g=bakeplan._levain_grams(
                version,
                total_flour if total_flour is not None else inputs.total_flour_g,
            ),
            program_id=program_id if program_id is not None else inputs.program_id,
            loaf_lb=loaf if loaf is not None else inputs.loaf_lb,
            knead_only=params.get("whole") != "1",
            knead_min=knead_min,
            final_rise_min=final_rise,
            bake_temp_c=(
                temp_to_celsius(bake_temp, ctx.temp_unit)
                if bake_temp is not None
                else inputs.bake_temp_c
            ),
            bake_min=bake_min if bake_min is not None else inputs.bake_min,
            cool_min=cool_min if cool_min is not None else inputs.cool_min,
        ),
        notes,
    )


def _int(params, name: str) -> int | None:
    raw = params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _context(request: Request, ctx: ViewContext) -> dict:
    params = request.query_params
    version = _version(ctx, _int(params, "version"))
    jar = _jar(ctx, _int(params, "jar"))
    inputs, notes = _read_inputs(ctx, params, version=version)
    program = _program(ctx, inputs.program_id)

    made, specs, workable = bakeplan.build(
        ctx.session,
        version=version,
        jar=jar,
        inputs=inputs,
        now=ctx.now,
        tz=ctx.tz,
        program=program,
    )

    # The same busy blocks the plan was checked against, so the shading and
    # the conflict flags cannot disagree.
    window_start, window_end = ribbon_service.timeline_window(
        made.start, made.end, ctx.now
    )
    intervals = busy_service.busy_intervals(
        ctx.session, window_start, window_end, ctx.tz
    )

    jar_feed = None
    jar_plan = None
    if jar is not None:
        jar_plan = plan_service.jar_plan(
            ctx.session, jar, now=ctx.now, until=ctx.now + timedelta(days=3)
        )
        if jar_plan.last_cycle is not None:
            cycle = jar_plan.last_cycle
            jar_feed = ribbon_service.FeedMark(
                at=cycle.fed_at,
                peak_h=cycle.peak_h,
                ratio_label=cycle.ratio_label,
                temp_assumed=cycle.temp_assumed,
            )

    levain = made.step("levain")
    drawn = ribbon_service.timeline(
        made.steps,
        start=window_start,
        end=window_end,
        now=ctx.now,
        tz=ctx.tz,
        busy=tuple(
            ribbon_service.BusyMark(start=one.start, end=one.end, label=one.label)
            for one in intervals
        ),
        jar_feed=jar_feed,
        jar_name=jar.name if jar else None,
        levain_at=levain.start if levain else None,
    )

    return {
        "title": "Plan a bake",
        # Carried through the "find a time that works" link so the rest of
        # the plan survives jumping to a different start.
        "keep_params": {
            key: value
            for key, value in params.items()
            if key not in ("at", "mode", "offset")
        },
        "plan": made,
        "inputs": inputs,
        "notes": notes,
        "workable": workable,
        "timeline": drawn,
        "version": version,
        "recipe": version.recipe if version else None,
        "jar": jar,
        "jar_plan": jar_plan,
        "program": program,
        "versions": recipe_service.plannable_versions(ctx.session),
        "jars": jar_service.list_jars(ctx.session),
        "programs": recipe_service.list_programs(ctx.session),
        "mode": "ready" if inputs.is_backward else "start",
        # The slider is an offset in minutes from now, so the browser needs
        # no date arithmetic and the control stays a plain range input.
        "slider_min": -int(SLIDER_HOURS * 60 / 4),
        "slider_max": SLIDER_HOURS * 60,
        "slider_step": SLIDER_STEP_MIN,
        "slider_value": int(
            (
                (made.end if inputs.is_backward else made.start) - ctx.now
            ).total_seconds()
            // 60
        ),
        "temp_display": temp_in(inputs.levain_temp_c, ctx.temp_unit),
        "bake_temp_display": temp_in(inputs.bake_temp_c, ctx.temp_unit),
        "ferment_default_c": settings_store.default_ferment_temp_c(ctx.session),
    }


@router.get("", response_class=HTMLResponse)
def plan_page(request: Request, ctx: Ctx) -> HTMLResponse:
    return render(
        request=request, ctx=ctx, name="plan/index.html",
        context=_context(request, ctx),
    )


@router.get("/steps", response_class=HTMLResponse)
def plan_steps(request: Request, ctx: Ctx) -> HTMLResponse:
    """Just the timeline and the table, for the slider to swap in."""
    return render(
        request=request, ctx=ctx, name="plan/result.html",
        context=_context(request, ctx),
    )
