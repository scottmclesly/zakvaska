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
    from app.models.bake import Bake


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
    # Where the formula came from: a book, a manual, a site. Null means it
    # is Scott's own. `source_ref` narrows it down — a page or a URL.
    source: Mapped[str | None] = mapped_column(String(200))
    source_ref: Mapped[str | None] = mapped_column(String(300))
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

    # The total flour this version was written at, in grams, when it was
    # written as real amounts rather than percentages — a manual's recipe in
    # cups, say. The percentages are still what the recipe *is*; this is the
    # batch they were worked out from, so the page can show the amounts
    # straight away and the edit form can hand back the cups that were typed.
    # Null means the recipe was given as percentages and has no natural size.
    batch_flour_g: Mapped[float | None] = mapped_column(Float)

    # What this recipe expects of the bread maker, so starting a bake does
    # not mean looking the program up in the manual every time. SET NULL
    # rather than CASCADE: archiving a program must not delete a version.
    default_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment_program.id", ondelete="SET NULL")
    )
    default_loaf_size: Mapped[str | None] = mapped_column(String(40))
    default_crust: Mapped[str | None] = mapped_column(String(40))

    created_at = created_at_column()

    recipe: Mapped[Recipe] = relationship(back_populates="versions")
    default_program: Mapped[EquipmentProgram | None] = relationship()
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
    # No cascade: a version with bakes against it is never deleted.
    bakes: Mapped[list[Bake]] = relationship(
        back_populates="version", order_by="Bake.created_at.desc()"
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
    # The number on the machine's menu, 1-12 on the West Bend. Null for a
    # program typed in by hand from some other device.
    menu_no: Mapped[int | None] = mapped_column(Integer)
    # The headline figure. Kept because it is what a list wants to show;
    # the real per-size timings live in `cycles`.
    total_min: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # Archived rather than deleted, like everything else here.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = created_at_column()

    cycles: Mapped[list[EquipmentCycle]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="EquipmentCycle.loaf_lb",
    )

    @property
    def sized(self) -> bool:
        """Whether the LOAF button applies — Mix, Dough, Custom and Bake say no."""
        return any(cycle.loaf_lb is not None for cycle in self.cycles)

    def cycle_for(self, loaf_lb: float | None) -> EquipmentCycle | None:
        for cycle in self.cycles:
            if cycle.loaf_lb == loaf_lb:
                return cycle
        return None

    def __repr__(self) -> str:
        return f"EquipmentProgram(name={self.name!r}, device={self.device!r})"


class EquipmentCycle(Base):
    """One program at one loaf size, segment by segment.

    The machine runs a different clock for a 2 lb loaf than a 3 lb one, so a
    single total on the program cannot say when the bread comes out. These
    are the manual's own numbers, and they are what v2's back-scheduling
    will work backwards from.

    A null segment means the program does not have that phase at all — the
    manual's "x" — rather than a phase of zero minutes. Programs with no
    LOAF button (Mix, Dough, Custom, Bake) carry a single row with a null
    `loaf_lb`.
    """

    __tablename__ = "equipment_cycle"
    __table_args__ = (
        UniqueConstraint("program_id", "loaf_lb", name="one_per_program_size"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_program.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 2.0, 2.5, 3.0 — or null where the size button does nothing.
    loaf_lb: Mapped[float | None] = mapped_column(Float)

    knead1_min: Mapped[int | None] = mapped_column(Integer)
    rest_min: Mapped[int | None] = mapped_column(Integer)
    knead2_min: Mapped[int | None] = mapped_column(Integer)
    rise2_min: Mapped[int | None] = mapped_column(Integer)
    # Seconds, not minutes: the machine knocks the dough back for 30 of them.
    stir_down_sec: Mapped[int | None] = mapped_column(Integer)
    rise3_min: Mapped[int | None] = mapped_column(Integer)
    bake_min: Mapped[int | None] = mapped_column(Integer)
    keep_warm_min: Mapped[int | None] = mapped_column(Integer)
    # The manual's own total, which is not always the segments added up.
    total_min: Mapped[int | None] = mapped_column(Integer)
    delay_max_h: Mapped[int | None] = mapped_column(Integer)

    program: Mapped[EquipmentProgram] = relationship(back_populates="cycles")

    @property
    def label(self) -> str:
        return f"{self.loaf_lb:g} lb" if self.loaf_lb is not None else "any size"

    @property
    def total_label(self) -> str:
        if self.total_min is None:
            return "—"
        hours, minutes = divmod(self.total_min, 60)
        return f"{hours}:{minutes:02d}"

    def __repr__(self) -> str:
        return f"EquipmentCycle(program_id={self.program_id!r}, {self.label})"
