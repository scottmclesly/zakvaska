"""The dashboard: one card per jar, the ones needing attention first."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.routes.deps import ViewContext, get_view_context
from app.services import jars as jar_service
from app.templates_env import render

router = APIRouter()

Ctx = Annotated[ViewContext, Depends(get_view_context)]


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home(request: Request, ctx: Ctx) -> HTMLResponse:
    cards = jar_service.dashboard(ctx.session, ctx.now)
    return render(
        request=request,
        ctx=ctx,
        name="home.html",
        context={
            "title": "jar-log",
            "cards": cards,
            "archived": [
                jar
                for jar in jar_service.list_jars(ctx.session, include_archived=True)
                if jar.archived
            ],
        },
    )
