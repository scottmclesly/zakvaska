"""Setting jars against each other: the list, and the page that draws it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models.jar import Jar
from app.routes.deps import ViewContext, get_view_context
from app.services import charts
from app.services import compare as compare_service
from app.services import jars as jar_service
from app.services import plan as plan_service
from app.templates_env import render

router = APIRouter(prefix="/compare")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _back(target: str, fallback: str) -> str:
    """Somewhere on this site to go back to; never off it."""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return fallback


def _jar(ctx: ViewContext, jar_id: int) -> Jar:
    jar = ctx.session.get(Jar, jar_id)
    if jar is None:
        raise HTTPException(status_code=404, detail="No such jar")
    return jar


@router.get("", response_class=HTMLResponse)
def page(request: Request, ctx: Ctx) -> HTMLResponse:
    jars = compare_service.chosen_jars(ctx.session)
    duel = plan_service.build_head_to_head(
        ctx.session, jars, now=ctx.now, tz=ctx.tz
    )
    flours = {(jar.flour_type or "").strip().lower() for jar in jars}
    # With nothing chosen yet, the pair the notebook was built around is a
    # fair place to start: the jars being fed on the same flour.
    suggestion = []
    if not jars:
        suggestion = plan_service.rivals(jar_service.list_jars(ctx.session))
    return render(
        request=request,
        ctx=ctx,
        name="jars/compare.html",
        context={
            "title": "Compare jars",
            "jars": jars,
            "duel": duel,
            "duel_note": (
                "same flour, same clock"
                if len(flours) == 1 and "" not in flours
                else "same clock"
            ),
            "rise_chart": charts.rise_chart(
                jar_service.rise_series(ctx.session, jars), tz=ctx.tz
            ) if len(jars) >= 2 else None,
            "suggestion": suggestion,
            "most": compare_service.MOST,
        },
    )


@router.post("/clear")
def clear(ctx: Ctx) -> RedirectResponse:
    compare_service.clear(ctx.session)
    ctx.session.commit()
    return RedirectResponse("/compare", status_code=303)


@router.post("/suggested")
def take_suggestion(ctx: Ctx) -> RedirectResponse:
    """Start with the jars being fed on the same flour."""
    if not compare_service.chosen_ids(ctx.session):
        for jar in plan_service.rivals(jar_service.list_jars(ctx.session)):
            compare_service.add(ctx.session, jar)
        ctx.session.commit()
    return RedirectResponse("/compare", status_code=303)


@router.post("/{jar_id}/add")
def add(
    ctx: Ctx, jar_id: int, next: Annotated[str, Form()] = ""
) -> RedirectResponse:
    jar = _jar(ctx, jar_id)
    compare_service.add(ctx.session, jar)
    ctx.session.commit()
    return RedirectResponse(_back(next, f"/jars/{jar_id}"), status_code=303)


@router.post("/{jar_id}/remove")
def remove(
    ctx: Ctx, jar_id: int, next: Annotated[str, Form()] = ""
) -> RedirectResponse:
    compare_service.remove(ctx.session, jar_id)
    ctx.session.commit()
    return RedirectResponse(_back(next, "/compare"), status_code=303)
