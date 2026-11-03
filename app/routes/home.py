"""The dashboard: one card per jar, the ones needing attention first."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.routes.deps import ViewContext, get_view_context
from app.services import charts, jars as jar_service
from app.templates_env import render

router = APIRouter()

Ctx = Annotated[ViewContext, Depends(get_view_context)]


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home(request: Request, ctx: Ctx) -> HTMLResponse:
    cards = jar_service.dashboard(ctx.session, ctx.now)
    # Two jars side by side is the point of the notebook (CLAUDE.md), so
    # the dashboard overlays them rather than making you open each one.
    rise = charts.rise_chart(
        jar_service.rise_series(ctx.session, [card.jar for card in cards]),
        tz=ctx.tz,
    )
    return render(
        request=request,
        ctx=ctx,
        name="home.html",
        context={
            "title": "zakvaska",
            "cards": cards,
            "rise_chart": rise,
            "archived": [
                jar
                for jar in jar_service.list_jars(ctx.session, include_archived=True)
                if jar.archived
            ],
        },
    )
