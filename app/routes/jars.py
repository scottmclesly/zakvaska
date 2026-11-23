"""Jar pages: list, create, edit, archive, feed, observe."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models.setting import FEEDS_PER_DAY_CHOICES
from app.models.enums import (
    PhotoOwner,
    SMELL_SUGGESTIONS,
    TEXTURE_SUGGESTIONS,
    BubbleLevel,
    IngredientRole,
    JarOrigin,
    JarState,
)
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import alerts as alert_service
from app.services import (
    bakes as bake_service,
    busy as busy_service,
    charts,
    derived,
    jars as jar_service,
    learning,
    plan as plan_service,
)
from app.services import photos as photo_service
from app.services import settings_store
from app.services.units import temp_to_celsius
from app.templates_env import render

log = logging.getLogger("zakvaska.photos")

router = APIRouter(prefix="/jars")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _see_other(url: str) -> RedirectResponse:
    # 303 so a refresh after POST does not re-submit.
    return RedirectResponse(url, status_code=303)


def _load(ctx: ViewContext, jar_id: int):
    jar = jar_service.get_jar(ctx.session, jar_id)
    if jar is None:
        raise HTTPException(status_code=404, detail="No such jar")
    return jar


def _attach_photo(
    ctx: ViewContext, owner: PhotoOwner, owner_id: int, data: bytes | None
) -> None:
    """Attach a photo taken while logging, if one came with the form.

    A photo that will not decode must not lose the feeding it came with, so
    the failure is swallowed here rather than raised.
    """
    if not data:
        return
    try:
        photo_service.attach(
            ctx.session, owner_type=owner, owner_id=owner_id,
            data=data, now=ctx.now,
        )
    except photo_service.PhotoError:
        log.warning("ignored an unreadable photo on a %s", owner.value)


def _feeds_per_day(raw: str) -> int | None:
    """Blank means "follow the app setting", which is a null in the row."""
    value = f.opt_int(raw, field="Feeds a day")
    if value is None:
        return None
    if value not in FEEDS_PER_DAY_CHOICES:
        raise ValueError("Feeds a day must be one or two.")
    return value


def _jar_form_context(ctx: ViewContext, jar=None, errors=None, values=None) -> dict:
    return {
        "jar": jar,
        "feeds_per_day_choices": FEEDS_PER_DAY_CHOICES,
        "app_feeds_per_day": settings_store.feeds_per_day(ctx.session),
        "errors": errors or [],
        "values": values or {},
        "origins": list(JarOrigin),
        "states": list(JarState),
        "parents": [
            candidate
            for candidate in jar_service.list_jars(ctx.session)
            if jar is None or candidate.id != jar.id
        ],
        "title": "Edit jar" if jar else "New jar",
    }


@router.get("/new", response_class=HTMLResponse)
def new_jar_form(request: Request, ctx: Ctx) -> HTMLResponse:
    return render(
        request=request,
        ctx=ctx, name="jars/form.html", context=_jar_form_context(ctx)
    )


@router.post("/new")
def create_jar(
    request: Request,
    ctx: Ctx,
    name: Annotated[str, Form()] = "",
    origin: Annotated[str, Form()] = JarOrigin.HOMEMADE.value,
    culture_name: Annotated[str, Form()] = "",
    flour_type: Annotated[str, Form()] = "",
    state: Annotated[str, Form()] = JarState.ACTIVE.value,
    feeds_per_day: Annotated[str, Form()] = "",
    feed_interval_room_h: Annotated[str, Form()] = "12",
    feed_interval_fridge_h: Annotated[str, Form()] = "168",
    parent_jar_id: Annotated[str, Form()] = "",
    is_control: Annotated[str | None, Form()] = None,
    notes: Annotated[str, Form()] = "",
):
    values = {
        "name": name, "origin": origin, "culture_name": culture_name,
        "flour_type": flour_type, "state": state,
        "feeds_per_day": feeds_per_day,
        "feed_interval_room_h": feed_interval_room_h,
        "feed_interval_fridge_h": feed_interval_fridge_h,
        "parent_jar_id": parent_jar_id,
        "is_control": f.checkbox(is_control), "notes": notes,
    }
    errors: list[str] = []

    if not f.opt_str(name):
        errors.append("A jar needs a name.")
    try:
        room_h = f.opt_int(feed_interval_room_h, field="Room interval") or 12
        fridge_h = f.opt_int(feed_interval_fridge_h, field="Fridge interval") or 168
    except ValueError as exc:
        errors.append(str(exc))
        room_h, fridge_h = 12, 168
    try:
        per_day = _feeds_per_day(feeds_per_day)
    except ValueError as exc:
        errors.append(str(exc))
        per_day = None

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="jars/form.html",
            context=_jar_form_context(ctx, errors=errors, values=values),
            status_code=400,
        )

    jar = jar_service.create_jar(
        ctx.session,
        name=f.opt_str(name),
        origin=JarOrigin(origin),
        culture_name=f.opt_str(culture_name),
        flour_type=f.opt_str(flour_type),
        state=JarState(state),
        feeds_per_day=per_day,
        feed_interval_room_h=room_h,
        feed_interval_fridge_h=fridge_h,
        parent_jar_id=f.opt_int(parent_jar_id, field="Parent jar"),
        is_control=f.checkbox(is_control),
        notes=f.opt_str(notes),
    )
    ctx.session.commit()
    return _see_other(f"/jars/{jar.id}")


@router.get("/{jar_id}", response_class=HTMLResponse)
def jar_detail(request: Request, ctx: Ctx, jar_id: int) -> HTMLResponse:
    jar = _load(ctx, jar_id)
    card = jar_service.jar_card(ctx.session, jar, ctx.now)
    last = (
        derived.describe_feeding(card.last_feeding) if card.last_feeding else {}
    )
    events = jar_service.timeline(ctx.session, jar)
    # Two queries for the whole timeline rather than one per entry.
    feeding_photos = photo_service.photos_by_owner(
        ctx.session,
        PhotoOwner.FEEDING,
        [e.obj.id for e in events if e.kind == "feeding"],
    )
    observation_photos = photo_service.photos_by_owner(
        ctx.session,
        PhotoOwner.OBSERVATION,
        [e.obj.id for e in events if e.kind == "observation"],
    )
    # The drawn jar fills to the last rise that was actually measured, so
    # the picture says something rather than just decorating.
    latest_rise = next(
        (
            e.detail.get("rise_pct")
            for e in events
            if e.kind == "observation" and e.detail.get("rise_pct") is not None
        ),
        None,
    )
    feeding_ribbon, plans = plan_service.build_ribbon(
        ctx.session, [jar], now=ctx.now, tz=ctx.tz
    )
    made = plans[jar.id]
    return render(
        request=request,
        ctx=ctx,
        name="jars/detail.html",
        context={
            "title": jar.name,
            "jar": jar,
            "rise_pct": latest_rise,
            "ribbon": feeding_ribbon,
            "plan": made,
            "learning": learning.learned(ctx.session, jar),
            "readiness": made.readiness_at(ctx.now),
            "nudges": plan_service.NUDGES,
            "next_feed_local": (
                f.utc_to_local_input(made.next_feed_at, ctx.tz)
                if made.next_feed_at else ""
            ),
            "next_feed_clash": _next_feed_clash(ctx, jar, made),
            "rise_chart": charts.rise_chart(
                jar_service.rise_series(ctx.session, [jar]), tz=ctx.tz
            ),
            "card": card,
            "last_ratio": last.get("ratio"),
            "last_hydration": last.get("hydration_pct"),
            "events": events,
            "states": list(JarState),
            "bakes": bake_service.list_bakes(ctx.session, jar_id=jar.id),
            "photos": photo_service.list_for(ctx.session, PhotoOwner.JAR, jar.id),
            "feeding_photos": feeding_photos,
            "observation_photos": observation_photos,
        },
    )


@router.get("/{jar_id}/edit", response_class=HTMLResponse)
def edit_jar_form(request: Request, ctx: Ctx, jar_id: int) -> HTMLResponse:
    jar = _load(ctx, jar_id)
    return render(
        request=request,
        ctx=ctx,
        name="jars/form.html",
        context=_jar_form_context(ctx, jar=jar),
    )


@router.post("/{jar_id}/edit")
def edit_jar(
    request: Request,
    ctx: Ctx,
    jar_id: int,
    name: Annotated[str, Form()] = "",
    origin: Annotated[str, Form()] = JarOrigin.HOMEMADE.value,
    culture_name: Annotated[str, Form()] = "",
    flour_type: Annotated[str, Form()] = "",
    state: Annotated[str, Form()] = JarState.ACTIVE.value,
    feeds_per_day: Annotated[str, Form()] = "",
    feed_interval_room_h: Annotated[str, Form()] = "12",
    feed_interval_fridge_h: Annotated[str, Form()] = "168",
    parent_jar_id: Annotated[str, Form()] = "",
    is_control: Annotated[str | None, Form()] = None,
    notes: Annotated[str, Form()] = "",
):
    jar = _load(ctx, jar_id)
    errors: list[str] = []

    if not f.opt_str(name):
        errors.append("A jar needs a name.")
    try:
        per_day = _feeds_per_day(feeds_per_day)
    except ValueError as exc:
        errors.append(str(exc))
        per_day = jar.feeds_per_day

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="jars/form.html",
            context=_jar_form_context(ctx, jar=jar, errors=errors),
            status_code=400,
        )

    jar_service.update_jar(
        ctx.session,
        jar,
        name=f.opt_str(name),
        origin=JarOrigin(origin),
        culture_name=f.opt_str(culture_name),
        flour_type=f.opt_str(flour_type),
        state=JarState(state),
        feeds_per_day=per_day,
        feed_interval_room_h=f.opt_int(feed_interval_room_h, field="Room interval") or 12,
        feed_interval_fridge_h=f.opt_int(feed_interval_fridge_h, field="Fridge interval") or 168,
        parent_jar_id=f.opt_int(parent_jar_id, field="Parent jar"),
        is_control=f.checkbox(is_control),
        notes=f.opt_str(notes),
        state_note="Changed on the jar's edit page",
    )
    ctx.session.commit()
    return _see_other(f"/jars/{jar.id}")


@router.post("/{jar_id}/state")
def change_state(
    ctx: Ctx,
    jar_id: int,
    state: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
):
    jar = _load(ctx, jar_id)
    jar_service.set_state(ctx.session, jar, JarState(state), f.opt_str(note))
    ctx.session.commit()
    return _see_other(f"/jars/{jar.id}")


@router.post("/{jar_id}/archive")
def archive_jar(ctx: Ctx, jar_id: int, archived: Annotated[str, Form()] = "1"):
    jar = _load(ctx, jar_id)
    jar_service.set_archived(ctx.session, jar, archived == "1")
    ctx.session.commit()
    return _see_other(f"/jars/{jar.id}")


# --- Feeding ---------------------------------------------------------------


def _feed_context(
    ctx: ViewContext,
    jar,
    *,
    fed_at=None,
    starter_g: float | None = None,
    flour_g: float | None = None,
    ambient_temp_c: float | None = None,
) -> dict:
    """The advice and the picture that go with the Fed-it form.

    `advice` is what to feed it so the peak lands on the feed after the slot
    this one fills — the whole payoff of the cycle being controllable, and
    see `plan.peak_target_from` for why it is that feed and not the next one
    on the plan. `late` is how far off
    the plan this feed is, which decides whether the two schedule choices
    are offered. `preview` is the same thing drawn: the amounts as they
    stand, the rise they would set off, and the planned feed to land on.

    The preview is built here as well as on the HTMX route so the form
    arrives with its chart already on it, rather than blank until the first
    keystroke.
    """
    moment = fed_at or ctx.now
    made = plan_service.jar_plan(
        ctx.session, jar, now=moment, until=moment + timedelta(days=14)
    )
    temp_c = (
        made.last_cycle.temp_c
        if made.last_cycle
        else settings_store.default_ferment_temp_c(ctx.session)
    )
    # Aimed at the feed after the slot this one fills, not at that slot: the
    # feed going in now should be at its peak when it is next fed.
    target_at = plan_service.peak_target_from(made)
    advice = None
    if target_at is not None:
        advice = plan_service.ratio_advice(
            from_moment=moment,
            target_at=target_at,
            temp_c=temp_c,
            factor=made.factor,
        )
    return {
        "plan": made,
        "advice": advice,
        "late": plan_service.feed_against_plan(
            ctx.session, jar, fed_at=moment, now=ctx.now
        ),
        "preview": plan_service.feed_preview(
            ctx.session,
            jar,
            starter_g=starter_g,
            flour_g=flour_g,
            fed_at=moment,
            now=ctx.now,
            tz=ctx.tz,
            ambient_temp_c=ambient_temp_c,
        ),
    }


@router.get("/{jar_id}/feed", response_class=HTMLResponse)
def feed_form(request: Request, ctx: Ctx, jar_id: int) -> HTMLResponse:
    jar = _load(ctx, jar_id)
    defaults = jar_service.feeding_defaults(ctx.session, jar)
    return render(
        request=request,
        ctx=ctx,
        name="jars/feed.html",
        context={
            "title": f"Feed {jar.name}",
            "jar": jar,
            "defaults": defaults,
            "now_local": f.utc_to_local_input(ctx.now, ctx.tz),
            "errors": [],
            **_feed_context(
                ctx,
                jar,
                starter_g=defaults["starter_g"],
                flour_g=defaults["flour_g"],
                ambient_temp_c=defaults["ambient_temp_c"],
            ),
        },
    )


@router.get("/{jar_id}/feed/preview", response_class=HTMLResponse)
def feed_preview(
    request: Request,
    ctx: Ctx,
    jar_id: int,
    starter_g: str = "",
    flour_g: str = "",
    ambient_temp: str = "",
    fed_at: str = "",
) -> HTMLResponse:
    """The live picture under the Fed-it form's amounts.

    Swapped in by HTMX on every change to the amounts, which is what makes
    the peak slide as the ratio is adjusted. Everything is read leniently and
    nothing here can fail: a half-typed "1" or a cleared field should leave a
    picture standing, so an unreadable value falls back rather than erroring.

    Water is not a parameter because the model does not use hydration: the
    ratio that moves the peak is flour per gram of starter.
    """
    jar = _load(ctx, jar_id)

    def grams(raw: str, name: str, role) -> float | None:
        try:
            return f.opt_weight(
                raw, ctx.weight_unit, field="Amount", name=name, role=role
            )
        except ValueError:
            return None

    try:
        when = f.local_to_utc(fed_at, ctx.tz, default=ctx.now)
    except ValueError:
        when = ctx.now

    try:
        room = temp_to_celsius(
            f.opt_float(ambient_temp, field="Room temperature"), ctx.temp_unit
        )
    except ValueError:
        room = None

    return render(
        request=request,
        ctx=ctx,
        name="partials/feed_preview.html",
        context={
            "jar": jar,
            "preview": plan_service.feed_preview(
                ctx.session,
                jar,
                starter_g=grams(starter_g, "starter", IngredientRole.LEVAIN),
                flour_g=grams(
                    flour_g, jar.flour_type or "flour", IngredientRole.FLOUR
                ),
                fed_at=when,
                now=ctx.now,
                tz=ctx.tz,
                ambient_temp_c=room,
            ),
        },
    )


@router.post("/{jar_id}/feed")
async def log_feeding(
    request: Request,
    ctx: Ctx,
    jar_id: int,
    starter_g: Annotated[str, Form()] = "",
    flour_g: Annotated[str, Form()] = "",
    water_g: Annotated[str, Form()] = "",
    flour_type: Annotated[str, Form()] = "",
    water_temp: Annotated[str, Form()] = "",
    ambient_temp: Annotated[str, Form()] = "",
    fed_at: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    schedule_choice: Annotated[str, Form()] = "keep",
    photo: Annotated[UploadFile | None, File()] = None,
):
    jar = _load(ctx, jar_id)
    errors: list[str] = []
    # Read before anything can fail, so the error page still has the form.
    shot = await photo.read() if photo is not None and photo.filename else None

    # Read in whatever unit the switch is showing, and in whatever unit the
    # baker wrote out if they wrote one. Stored in grams either way.
    flour_name = f.opt_str(flour_type) or jar.flour_type or "flour"
    try:
        starter = f.req_weight(
            starter_g, ctx.weight_unit,
            field="Starter", name="starter", role=IngredientRole.LEVAIN,
        )
        flour = f.req_weight(
            flour_g, ctx.weight_unit,
            field="Flour", name=flour_name, role=IngredientRole.FLOUR,
        )
        water = f.req_weight(
            water_g, ctx.weight_unit,
            field="Water", name="water", role=IngredientRole.WATER,
        )
    except ValueError as exc:
        errors.append(str(exc))
        starter = flour = water = 0.0

    for label, value in (("Starter", starter), ("Flour", flour), ("Water", water)):
        if value < 0:
            errors.append(f"{label} cannot be negative.")

    try:
        when = f.local_to_utc(fed_at, ctx.tz, default=ctx.now)
    except ValueError as exc:
        errors.append(str(exc))
        when = ctx.now

    # Parsed before the error check so a failed submission can re-render with
    # whatever the user already typed, rather than throwing it away.
    water_temp_c = ambient_temp_c = None
    for label, raw, attr in (
        ("Water temperature", water_temp, "water_temp_c"),
        ("Room temperature", ambient_temp, "ambient_temp_c"),
    ):
        try:
            parsed = temp_to_celsius(f.opt_float(raw, field=label), ctx.temp_unit)
        except ValueError as exc:
            errors.append(str(exc))
            parsed = None
        if attr == "water_temp_c":
            water_temp_c = parsed
        else:
            ambient_temp_c = parsed

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="jars/feed.html",
            context={
                "title": f"Feed {jar.name}",
                "jar": jar,
                "defaults": {
                    "starter_g": starter_g, "flour_g": flour_g,
                    "water_g": water_g, "flour_type": flour_type,
                    "water_temp_c": water_temp_c,
                    "ambient_temp_c": ambient_temp_c,
                },
                "now_local": fed_at or f.utc_to_local_input(ctx.now, ctx.tz),
                "errors": errors,
                **_feed_context(
                    ctx,
                    jar,
                    fed_at=when,
                    starter_g=starter or None,
                    flour_g=flour or None,
                    ambient_temp_c=ambient_temp_c,
                ),
            },
            status_code=400,
        )

    # Judged on the time actually submitted, not the one the form was
    # opened at: the two can differ by hours if a feed is logged after the
    # fact, and the schedule must follow what happened.
    late = plan_service.feed_against_plan(
        ctx.session, jar, fed_at=when, now=ctx.now
    )
    if late is not None and late.is_off_plan:
        # "Keep my usual times" is the default, here and in the form: a feed
        # that slipped once should not drag the whole rhythm after it.
        if schedule_choice == "shift":
            plan_service.shift_schedule(ctx.session, jar, late=late)
        else:
            plan_service.keep_usual_times(ctx.session, jar, late=late)

    feeding = jar_service.log_feeding(
        ctx.session,
        jar,
        fed_at=when,
        starter_g=starter,
        flour_g=flour,
        water_g=water,
        flour_type=f.opt_str(flour_type),
        # Typed in the user's unit, stored in Celsius (parsed above).
        water_temp_c=water_temp_c,
        ambient_temp_c=ambient_temp_c,
        notes=f.opt_str(notes),
    )
    _attach_photo(ctx, PhotoOwner.FEEDING, feeding.id, shot)
    # The alert follows the plan, and both just moved.
    alert_service.reconcile(ctx.session, ctx.now)
    ctx.session.commit()
    return _see_other(f"/jars/{jar.id}")


# --- Observations ----------------------------------------------------------


@router.get("/{jar_id}/observe", response_class=HTMLResponse)
def observe_form(request: Request, ctx: Ctx, jar_id: int) -> HTMLResponse:
    jar = _load(ctx, jar_id)
    return render(
        request=request,
        ctx=ctx,
        name="jars/observe.html",
        context={
            "title": f"Observe {jar.name}",
            "jar": jar,
            "bubble_levels": list(BubbleLevel),
            "smells": SMELL_SUGGESTIONS,
            "textures": TEXTURE_SUGGESTIONS,
            "now_local": f.utc_to_local_input(ctx.now, ctx.tz),
            "values": {},
            "errors": [],
        },
    )


@router.post("/{jar_id}/observe")
async def log_observation(
    request: Request,
    ctx: Ctx,
    jar_id: int,
    start_height_mm: Annotated[str, Form()] = "",
    height_mm: Annotated[str, Form()] = "",
    bubbles: Annotated[str, Form()] = "",
    smell: Annotated[str, Form()] = "",
    texture: Annotated[str, Form()] = "",
    observed_at: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    peaked: Annotated[str | None, Form()] = None,
    photo: Annotated[UploadFile | None, File()] = None,
):
    jar = _load(ctx, jar_id)
    errors: list[str] = []
    shot = await photo.read() if photo is not None and photo.filename else None

    try:
        start_mm = f.opt_float(start_height_mm, field="Starting height")
        now_mm = f.opt_float(height_mm, field="Current height")
    except ValueError as exc:
        errors.append(str(exc))
        start_mm = now_mm = None

    try:
        when = f.local_to_utc(observed_at, ctx.tz, default=ctx.now)
    except ValueError as exc:
        errors.append(str(exc))
        when = ctx.now

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="jars/observe.html",
            context={
                "title": f"Observe {jar.name}",
                "jar": jar,
                "bubble_levels": list(BubbleLevel),
                "smells": SMELL_SUGGESTIONS,
                "textures": TEXTURE_SUGGESTIONS,
                "now_local": observed_at or f.utc_to_local_input(ctx.now, ctx.tz),
                "values": {
                    "start_height_mm": start_height_mm,
                    "height_mm": height_mm, "bubbles": bubbles,
                    "smell": smell, "texture": texture, "notes": notes,
                    "peaked": f.checkbox(peaked),
                },
                "errors": errors,
            },
            status_code=400,
        )

    observation = jar_service.log_observation(
        ctx.session,
        jar,
        observed_at=when,
        start_height_mm=start_mm,
        height_mm=now_mm,
        bubbles=BubbleLevel(bubbles) if f.opt_str(bubbles) else None,
        smell=f.opt_str(smell),
        texture=f.opt_str(texture),
        notes=f.opt_str(notes),
        peaked=f.checkbox(peaked),
    )
    _attach_photo(ctx, PhotoOwner.OBSERVATION, observation.id, shot)
    ctx.session.commit()
    return _see_other(f"/jars/{jar.id}")


@router.post("/{jar_id}/peaked")
def mark_peaked(
    ctx: Ctx, jar_id: int, next_url: Annotated[str, Form(alias="next")] = ""
):
    """One tap: this jar is at its peak, now.

    The whole of the app's ground truth about how fast a jar really is comes
    from someone saying this, so it has to cost nothing — no form, no fields,
    one button wherever the jar is on screen. It is an ordinary observation
    with the peak flag set, so it lands on the timeline like any other.
    """
    jar = _load(ctx, jar_id)
    jar_service.log_observation(
        ctx.session, jar, observed_at=ctx.now, peaked=True
    )
    ctx.session.commit()
    return _see_other(next_url or f"/jars/{jar.id}")


# --- The feeding plan ------------------------------------------------------
#
# Moving a planned feed writes the jar's schedule anchor, and every later
# planned feed is counted from it — so one write moves the whole chain and
# nothing drifts. See services/plan.py.


def _next_feed_clash(ctx: ViewContext, jar, made):
    """The busy block the next planned feed lands in, and the way out of it.

    None when it is clear. Returned as a small dict because it is only ever
    read by the template.
    """
    target = made.next_feed_at
    if target is None:
        return None

    start, end = ctx.now, target + timedelta(hours=24)
    intervals = busy_service.busy_intervals(ctx.session, start, end, ctx.tz)
    clash = busy_service.covering(intervals, target)
    if clash is None:
        return None

    free = busy_service.next_free(intervals, target)
    advice = None
    if free is not None:
        advice = plan_service.ratio_advice(
            from_moment=ctx.now,
            target_at=free,
            temp_c=(
                made.last_cycle.temp_c
                if made.last_cycle
                else settings_store.default_ferment_temp_c(ctx.session)
            ),
            factor=made.factor,
        )
    return {"label": clash.label, "move_to": free, "advice": advice}


@router.post("/{jar_id}/plan/nudge")
def nudge_planned_feed(
    request: Request,
    ctx: Ctx,
    jar_id: int,
    minutes: Annotated[str, Form()] = "0",
):
    """Shift the next planned feed, and every later one, by a few minutes."""
    jar = _load(ctx, jar_id)
    try:
        offset = f.opt_int(minutes, field="Nudge") or 0
    except ValueError:
        offset = 0
    if offset:
        plan_service.shift_next_feed(
            ctx.session, jar,
            by=timedelta(minutes=offset),
            now=ctx.now,
            until=ctx.now + timedelta(days=14),
        )
        # The alert follows the plan, so it has to be rebuilt now rather
        # than whenever the scheduler next happens to tick.
        alert_service.reconcile(ctx.session, ctx.now)
        ctx.session.commit()
    return _plan_response(request, ctx, jar_id)


@router.post("/{jar_id}/plan/move")
def move_planned_feed(
    request: Request,
    ctx: Ctx,
    jar_id: int,
    at: Annotated[str, Form()] = "",
):
    """Put the next planned feed at a chosen time."""
    jar = _load(ctx, jar_id)
    errors: list[str] = []
    try:
        when = f.local_to_utc(at, ctx.tz, default=ctx.now)
    except ValueError as exc:
        errors.append(str(exc))
        when = None

    if when is not None:
        plan_service.move_next_feed(ctx.session, jar, to=when, now=ctx.now)
        alert_service.reconcile(ctx.session, ctx.now)
        ctx.session.commit()
    return _plan_response(request, ctx, jar_id, errors=errors)


@router.post("/{jar_id}/plan/reset")
def reset_planned_feed(request: Request, ctx: Ctx, jar_id: int):
    """Go back to planning a cycle on from the last feed."""
    jar = _load(ctx, jar_id)
    plan_service.clear_anchor(ctx.session, jar)
    alert_service.reconcile(ctx.session, ctx.now)
    ctx.session.commit()
    return _plan_response(request, ctx, jar_id)


def _plan_response(
    request: Request, ctx: Ctx, jar_id: int, errors: list[str] | None = None
):
    """Swap the plan panel back in for HTMX; redirect for a plain post."""
    jar = _load(ctx, jar_id)
    if request.headers.get("HX-Request"):
        _, plans = plan_service.build_ribbon(
            ctx.session, [jar], now=ctx.now, tz=ctx.tz
        )
        made = plans[jar.id]
        return render(
            request=request,
            ctx=ctx,
            name="partials/feed_plan.html",
            context={
                "jar": jar,
                "plan": made,
                "nudges": plan_service.NUDGES,
                "next_feed_local": (
                    f.utc_to_local_input(made.next_feed_at, ctx.tz)
                    if made.next_feed_at else ""
                ),
                "next_feed_clash": _next_feed_clash(ctx, jar, made),
                "errors": errors or [],
            },
        )
    return _see_other(f"/jars/{jar.id}")
