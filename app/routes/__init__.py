"""HTTP routers."""

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

__all__ = [
    "alerts", "backup", "bakes", "equipment", "health", "home", "jars",
    "photos", "recipes", "settings",
]
