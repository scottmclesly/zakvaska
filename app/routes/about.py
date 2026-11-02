"""What this notebook is, and what this particular install is holding."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import __version__
from app.config import get_settings
from app.routes.deps import ViewContext, get_view_context
from app.services import backup as backup_service
from app.templates_env import render

router = APIRouter(prefix="/about")

Ctx = Annotated[ViewContext, Depends(get_view_context)]

# The tables worth naming on the page. The rest are counted in the total.
HEADLINE = (
    ("jar", "Jars"),
    ("feeding", "Feedings"),
    ("recipe", "Recipes"),
    ("bake", "Bakes"),
)


def _db_bytes() -> int:
    """Size of the database file, WAL included — it can be the larger half."""
    path = get_settings().db_path
    total = 0
    for suffix in ("", "-wal", "-shm"):
        beside = path.with_name(path.name + suffix)
        if beside.exists():
            total += beside.stat().st_size
    return total


@router.get("", response_class=HTMLResponse)
def index(request: Request, ctx: Ctx) -> HTMLResponse:
    settings = get_settings()
    counts = backup_service.current_counts(ctx.session)
    return render(
        request=request,
        ctx=ctx,
        name="about/index.html",
        context={
            "title": "About zakvaska",
            "version": __version__,
            "headline": [(label, counts.get(name, 0)) for name, label in HEADLINE],
            "rows": sum(counts.values()),
            "photos": len(backup_service.photo_files()),
            "photo_bytes": backup_service.photo_bytes(),
            "db_bytes": _db_bytes(),
            "revision": backup_service.alembic_revision(ctx.session),
            "data_dir": settings.data_dir,
            "tz_name": settings.tz_name,
        },
    )
