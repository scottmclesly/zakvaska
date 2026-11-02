"""ORM models. Import every model here so Alembic autogenerate sees them."""

from app.models.alert import Alert
from app.models.bake import Bake, BakeResult, BakeStageLog
from app.models.base import Base
from app.models.enums import (
    AlertKind,
    BakeMethod,
    BakeStatus,
    BubbleLevel,
    IngredientRole,
    JarOrigin,
    JarState,
    PhotoOwner,
    RecipeCategory,
)
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.jar_state_change import JarStateChange
from app.models.observation import Observation
from app.models.photo import Photo
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
    "Bake",
    "BakeMethod",
    "BakeResult",
    "BakeStageLog",
    "BakeStatus",
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
    "Photo",
    "PhotoOwner",
    "Recipe",
    "RecipeCategory",
    "RecipeIngredient",
    "RecipeStage",
    "RecipeVersion",
    "Setting",
]
