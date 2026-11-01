"""Home page. Grows into the jar dashboard in Phase 1."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templates_env import templates

router = APIRouter()


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"title": "jar-log", "jars": []},
    )
