"""Liveness/readiness endpoint. Handy when this moves to a Raspberry Pi."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.db import get_engine

router = APIRouter()


# HEAD too: uptime checks and load balancers reach for it.
@router.api_route("/health", methods=["GET", "HEAD"])
def health() -> JSONResponse:
    settings = get_settings()

    checks: dict[str, bool] = {}

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    checks["data_dir_writable"] = os.access(settings.data_dir, os.W_OK)
    checks["photos_dir_writable"] = os.access(settings.photos_dir, os.W_OK)

    ok = all(checks.values())
    body = {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "timezone": settings.tz_name,
        "checks": checks,
    }
    return JSONResponse(body, status_code=200 if ok else 503)
