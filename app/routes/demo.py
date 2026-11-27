"""Filling an empty notebook: the demo, and the recipe library on its own."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.routes.deps import ViewContext, get_view_context
from app.services import demo as demo_service

router = APIRouter(prefix="/demo")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


@router.post("/load")
def load(ctx: Ctx) -> RedirectResponse:
    """Two jars, their feedings, the recipes and a loaf. Empty notebooks only:
    asked of one with a jar in it, this does nothing and says nothing."""
    if demo_service.load(ctx.session, ctx.now):
        ctx.session.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/library")
def library(ctx: Ctx) -> RedirectResponse:
    """The reference recipes and the bread maker's programs. Add-only, so
    asking twice adds nothing the second time."""
    demo_service.load_library(ctx.session)
    ctx.session.commit()
    return RedirectResponse("/recipes", status_code=303)
