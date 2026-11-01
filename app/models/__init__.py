"""ORM models. Import every model here so Alembic autogenerate sees them."""

from app.models.base import Base
from app.models.setting import Setting

__all__ = ["Base", "Setting"]
