"""Putting a hint away, and getting them all back.

The hints are data (`app.data.hints`); these two routes only keep the list
of the ones not to show again.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app.routes.deps import ViewContext, get_view_context
from app.services import hints as hint_service

router = APIRouter(prefix="/hints")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _back(target: str) -> str:
    """Somewhere on this site to go back to; never off it."""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


@router.post("/{hint_id}/dismiss")
def dismiss(
    request: Request,
    ctx: Ctx,
    hint_id: str,
    next: Annotated[str, Form()] = "/",
):
    """"Got it": this one is not shown again, anywhere."""
    if not hint_service.dismiss(ctx.session, hint_id):
        raise HTTPException(status_code=404, detail="No such hint")
    ctx.session.commit()
    # HTMX takes the hint off the page itself; a plain form goes back to
    # the page it was on, which now draws without it.
    if request.headers.get("HX-Request"):
        return Response(status_code=200)
    return RedirectResponse(_back(next), status_code=303)


@router.post("/restore")
def restore(ctx: Ctx, next: Annotated[str, Form()] = "/settings"):
    """Every hint back, for the next first loaf."""
    hint_service.restore_all(ctx.session)
    ctx.session.commit()
    return RedirectResponse(_back(next), status_code=303)
