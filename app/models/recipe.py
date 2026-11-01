"""Recipes, their versions, ingredients and stages.

Recipes are versioned rather than edited in place: a bake points at the exact
version it was made from, so last month's loaf still means something after
this month's tweak (CLAUDE.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column
from app.models.enums import IngredientRole, RecipeCategory

if TYPE_CHECKING:
    pass


def _enum(python_enum: type, length: int = 16) -> Enum:
    return Enum(
        python_enum, native_enum=False, validate_strings=True, length=length
    )


class Recipe(Base):
    __tablename__ = "recipe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[RecipeCategory] = mapped_column(
        _enum(RecipeCategory), nullable=False, default=RecipeCategory.OTHER
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = created_at_column()

    versions: Mapped[list[RecipeVersion]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeVersion.version.desc()",
    )

    @property
    def latest_version(self) -> RecipeVersion | None:
        # versions is ordered newest-first.
        return self.versions[0] if self.versions else None

    def __repr__(self) -> str:
        return f"Recipe(id={self.id!r}, name={self.name!r})"


class RecipeVersion(Base):
    __tablename__ = "recipe_version"
    __table_args__ = (
        UniqueConstraint("recipe_id", "version", name="one_per_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_column()

    recipe: Mapped[Recipe] = relationship(back_populates="versions")
    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.seq",
    )
    stages: Mapped[list[RecipeStage]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="RecipeStage.seq",
    )

    @property
    def label(self) -> str:
        return f"v{self.version}"

    def __repr__(self) -> str:
        return f"RecipeVersion(recipe_id={self.recipe_id!r}, v{self.version})"


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("recipe_version.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Display order. Bakers write flour first, and a shuffled list reads as
    # a different recipe even when the numbers match.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[IngredientRole] = mapped_column(
        _enum(IngredientRole), nullable=False, default=IngredientRole.OTHER
    )
    # Percentage of total flour weight. Flour lines themselves sum to 100.
    baker_pct: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    version: Mapped[RecipeVersion] = relationship(back_populates="ingredients")

    def __repr__(self) -> str:
        return f"RecipeIngredient({self.name!r}, {self.baker_pct}%)"


class RecipeStage(Base):
    __tablename__ = "recipe_stage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("recipe_version.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    temp_c: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    version: Mapped[RecipeVersion] = relationship(back_populates="stages")

    def __repr__(self) -> str:
        return f"RecipeStage(seq={self.seq!r}, name={self.name!r})"


class EquipmentProgram(Base):
    """A bread maker program, copied out of the manual."""

    __tablename__ = "equipment_program"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    device: Mapped[str | None] = mapped_column(String(120))
    total_min: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # Archived rather than deleted, like everything else here.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = created_at_column()

    def __repr__(self) -> str:
        return f"EquipmentProgram(name={self.name!r}, device={self.device!r})"
