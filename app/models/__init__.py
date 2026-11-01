"""ORM models. Import every model here so Alembic autogenerate sees them."""

from app.models.alert import Alert
from app.models.base import Base
from app.models.enums import (
    AlertKind,
    BubbleLevel,
    IngredientRole,
    JarOrigin,
    JarState,
    RecipeCategory,
)
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.jar_state_change import JarStateChange
from app.models.observation import Observation
from app.models.recipe import (
    EquipmentProgram,
    Recipe,
    RecipeIngredient,
    RecipeStage,
    RecipeVersion,
)
from app.models.setting import Setting

__all__ = [
    "Alert",
    "AlertKind",
    "Base",
    "BubbleLevel",
    "EquipmentProgram",
    "Feeding",
    "IngredientRole",
    "Jar",
    "JarOrigin",
    "JarState",
    "JarStateChange",
    "Observation",
    "Recipe",
    "RecipeCategory",
    "RecipeIngredient",
    "RecipeStage",
    "RecipeVersion",
    "Setting",
]
