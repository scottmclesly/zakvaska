"""Display settings that every page carries."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse

from app.routes.deps import ViewContext, get_view_context
from app.services import measures
from app.services import settings_store

router = APIRouter(prefix="/settings")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _safe_next(value: str | None) -> str:
    """Only ever redirect back inside this app.

    The target comes from a form field, so an absolute URL in it would be an
    open redirect. A path is all we ever need.
    """
    if not value:
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not value.startswith("/"):
        return "/"
    return value


@router.post("/weight-unit")
def cycle_weight_unit(
    ctx: Ctx,
    next: Annotated[str, Form()] = "/",
    unit: Annotated[str, Form()] = "",
):
    """Step to the next unit, or jump straight to a named one."""
    chosen = (
        unit
        if unit in measures.UNIT_CYCLE
        else measures.next_unit(ctx.weight_unit)
    )
    settings_store.set_setting(ctx.session, "weight_unit", chosen)
    ctx.session.commit()
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/temp-unit")
def toggle_temp_unit(ctx: Ctx, next: Annotated[str, Form()] = "/"):
    settings_store.set_setting(
        ctx.session, "temp_unit", "C" if ctx.temp_unit == "F" else "F"
    )
    ctx.session.commit()
    return RedirectResponse(_safe_next(next), status_code=303)
