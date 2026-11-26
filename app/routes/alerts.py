"""Acknowledge and snooze alerts, plus the JSON feed the page polls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.models.alert import Alert
from app.routes.deps import ViewContext, get_view_context
from app.services import alerts as alert_service
from app.services.units import humanize_until
from app.templates_env import render

router = APIRouter()

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _load(ctx: ViewContext, alert_id: int) -> Alert:
    alert = ctx.session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="No such alert")
    return alert


def _back(next_url: str) -> RedirectResponse:
    # Keep the user where they were; default to the dashboard.
    return RedirectResponse(next_url or "/", status_code=303)


@router.get("/partials/alerts", response_class=HTMLResponse)
def alerts_partial(request: Request, ctx: Ctx) -> HTMLResponse:
    """The banner on its own, for the page to refresh itself with.

    Read-only, like every other GET here: the scheduler decides when an
    alert fires, and this only shows what it has already decided. Its own
    endpoint rather than a slice of whichever page you are on, because the
    banner is on every page and re-rendering a dashboard every half minute
    to find out whether a jar wants feeding would be work for nothing.
    """
    return render(
        request=request, ctx=ctx, name="partials/alerts_live.html",
        context={},
    )


@router.get("/api/alerts")
def alerts_json(ctx: Ctx) -> JSONResponse:
    """Polled by the page so an open tab can raise a notification.

    Deliberately read-only: firing is the scheduler's job, so a browser tab
    being open or shut never changes whether an alert happens.
    """
    showing = alert_service.showing(ctx.session, ctx.now)
    return JSONResponse(
        {
            "count": len(showing),
            "alerts": [
                {
                    "id": alert.id,
                    "jar_id": alert.jar_id,
                    # Kept for the jar case the browser already knows about;
                    # `subject` is the one that works for every kind — and
                    # for a preheat it is the whole sentence, so the phone
                    # notification says how hot and how long you have got.
                    "jar_name": alert.jar.name if alert.jar else None,
                    "subject": alert_service.headline(alert, ctx.temp_unit),
                    "bake_id": (
                        alert.stage_log.bake_id if alert.stage_log else None
                    ),
                    "kind": alert.kind.value,
                    "due_at": alert.due_at.isoformat(),
                    "overdue_by": humanize_until(alert.due_at, ctx.now),
                    "url": alert.url,
                }
                for alert in showing
            ],
        }
    )


@router.post("/alerts/{alert_id}/ack")
def acknowledge(
    ctx: Ctx, alert_id: int, next_url: Annotated[str, Form(alias="next")] = "/"
):
    alert_service.acknowledge(ctx.session, _load(ctx, alert_id), ctx.now)
    ctx.session.commit()
    return _back(next_url)


@router.post("/alerts/{alert_id}/snooze")
def snooze(
    ctx: Ctx,
    alert_id: int,
    minutes: Annotated[str, Form()] = "30",
    next_url: Annotated[str, Form(alias="next")] = "/",
):
    try:
        delay = int(float(minutes))
    except ValueError:
        raise HTTPException(status_code=400, detail="Snooze must be a number") from None

    try:
        alert_service.snooze(ctx.session, _load(ctx, alert_id), ctx.now, delay)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    ctx.session.commit()
    return _back(next_url)
