"""Application entry point: uvicorn app.main:app"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.logging_config import setup_logging
from app.routes import (
    alerts,
    backup,
    bakes,
    equipment,
    health,
    home,
    jars,
    photos,
    recipes,
    settings,
)
from app.services import scheduler

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    get_settings().ensure_dirs()
    # Alert state is rebuilt from the database here, so nothing is lost
    # across a restart.
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="zakvaska",
        description="A baking lab notebook: starter jars, feedings, recipes, bakes.",
        version=__version__,
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(health.router)
    app.include_router(home.router)
    app.include_router(jars.router)
    app.include_router(alerts.router)
    app.include_router(recipes.router)
    app.include_router(equipment.router)
    app.include_router(bakes.router)
    app.include_router(photos.router)
    app.include_router(backup.router)
    app.include_router(settings.router)

    # Served from the root so the service worker's scope covers the whole app.
    @app.api_route("/sw.js", methods=["GET", "HEAD"], include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "js" / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.api_route(
        "/manifest.webmanifest", methods=["GET", "HEAD"], include_in_schema=False
    )
    def manifest() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> Response:
        return FileResponse(STATIC_DIR / "icons" / "icon-192.png")

    return app


app = create_app()
