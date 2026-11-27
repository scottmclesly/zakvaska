"""The dashboard: one card per jar, the ones needing attention first."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.routes.deps import ViewContext, get_view_context
from app.services import (
    charts,
    demo as demo_service,
    followalong,
    jars as jar_service,
    plan as plan_service,
)
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
    # Stacked ribbons on one time axis: the jars can be read against each
    # other, and a feed planned at four in the morning is visible as such.
    feeding_ribbon, plans = plan_service.build_ribbon(
        ctx.session, [card.jar for card in cards], now=ctx.now, tz=ctx.tz
    )
    # The experiment itself: the jars on the same flour, on one axis.
    duel = plan_service.build_head_to_head(
        ctx.session,
        plan_service.rivals([card.jar for card in cards]),
        now=ctx.now,
        tz=ctx.tz,
    )
    # A loaf underway is the other thing worth knowing at a glance. Read
    # only: the same Now view the bake's own page works out.
    underway = []
    for bake in followalong.live_bakes(ctx.session):
        view = None
        if followalong.has_plan(bake):
            view = followalong.now_view(
                bake,
                now=ctx.now,
                busy=followalong.busy_for(
                    ctx.session, bake, now=ctx.now, tz=ctx.tz
                ),
            )
        underway.append({"bake": bake, "view": view})
    return render(
        request=request,
        ctx=ctx,
        name="home.html",
        context={
            "title": "zakvaska",
            "cards": cards,
            "rise_chart": rise,
            "ribbon": feeding_ribbon,
            "plans": plans,
            "underway": underway,
            "duel": duel,
            # Offered on the empty shelf only, and only until the first jar.
            "demo_offer": not cards and demo_service.can_load(ctx.session),
            "archived": [
                jar
                for jar in jar_service.list_jars(ctx.session, include_archived=True)
                if jar.archived
            ],
        },
    )
