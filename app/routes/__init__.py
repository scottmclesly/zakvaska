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
    plan,
    recipes,
    settings,
)

__all__ = [
    "alerts", "backup", "bakes", "equipment", "health", "home", "jars",
    "photos", "plan", "recipes", "settings",
]
