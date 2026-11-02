"""Recipe CRUD and versioning.

Editing never changes a version in place. Every edit writes a new one, so a
bake recorded against v1 still describes what was actually made after v2
exists (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import IngredientRole, RecipeCategory
from app.models.recipe import (
    EquipmentProgram,
    Recipe,
    RecipeIngredient,
    RecipeStage,
    RecipeVersion,
)


@dataclass
class IngredientSpec:
    name: str
    role: IngredientRole
    baker_pct: float
    notes: str | None = None


@dataclass
class StageSpec:
    name: str
    duration_min: int | None = None
    temp_c: float | None = None
    notes: str | None = None


# --- Reading ---------------------------------------------------------------


def list_recipes(session: Session, *, include_archived: bool = False) -> list[Recipe]:
    stmt = (
        select(Recipe)
        .options(selectinload(Recipe.versions))
        .order_by(Recipe.archived, Recipe.name)
    )
    if not include_archived:
        stmt = stmt.where(Recipe.archived.is_(False))
    return list(session.scalars(stmt))


def get_recipe(session: Session, recipe_id: int) -> Recipe | None:
    return session.scalars(
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(
            selectinload(Recipe.versions).selectinload(RecipeVersion.ingredients),
            selectinload(Recipe.versions).selectinload(RecipeVersion.stages),
        )
    ).first()


def get_version(
    session: Session, recipe_id: int, version: int
) -> RecipeVersion | None:
    return session.scalars(
        select(RecipeVersion)
        .where(RecipeVersion.recipe_id == recipe_id, RecipeVersion.version == version)
        .options(
            selectinload(RecipeVersion.ingredients),
            selectinload(RecipeVersion.stages),
            selectinload(RecipeVersion.recipe),
        )
    ).first()


def next_version_number(session: Session, recipe_id: int) -> int:
    highest = session.scalar(
        select(func.max(RecipeVersion.version)).where(
            RecipeVersion.recipe_id == recipe_id
        )
    )
    return (highest or 0) + 1


# --- Writing ---------------------------------------------------------------


def _populate(
    session: Session,
    version: RecipeVersion,
    ingredients: list[IngredientSpec],
    stages: list[StageSpec],
) -> None:
    for seq, spec in enumerate(ingredients):
        session.add(
            RecipeIngredient(
                version_id=version.id,
                seq=seq,
                name=spec.name,
                role=spec.role,
                baker_pct=spec.baker_pct,
                notes=spec.notes,
            )
        )
    for seq, spec in enumerate(stages):
        session.add(
            RecipeStage(
                version_id=version.id,
                seq=seq,
                name=spec.name,
                duration_min=spec.duration_min,
                temp_c=spec.temp_c,
                notes=spec.notes,
            )
        )
    session.flush()


def create_recipe(
    session: Session,
    *,
    name: str,
    category: RecipeCategory,
    ingredients: list[IngredientSpec] | None = None,
    stages: list[StageSpec] | None = None,
    notes: str | None = None,
    source: str | None = None,
    source_ref: str | None = None,
) -> Recipe:
    recipe = Recipe(
        name=name, category=category, source=source, source_ref=source_ref
    )
    session.add(recipe)
    session.flush()

    version = RecipeVersion(recipe_id=recipe.id, version=1, notes=notes)
    session.add(version)
    session.flush()

    _populate(session, version, ingredients or [], stages or [])
    session.refresh(recipe)
    return recipe


def add_version(
    session: Session,
    recipe: Recipe,
    *,
    ingredients: list[IngredientSpec],
    stages: list[StageSpec],
    notes: str | None = None,
) -> RecipeVersion:
    """Record an edit as a new version, leaving the old one untouched."""
    version = RecipeVersion(
        recipe_id=recipe.id,
        version=next_version_number(session, recipe.id),
        notes=notes,
    )
    session.add(version)
    session.flush()

    _populate(session, version, ingredients, stages)
    session.refresh(recipe)
    return version


def update_recipe_meta(
    session: Session, recipe: Recipe, *, name: str, category: RecipeCategory
) -> Recipe:
    """Name and category are not versioned: they label the whole recipe."""
    recipe.name = name
    recipe.category = category
    session.flush()
    return recipe


def set_archived(session: Session, recipe: Recipe, archived: bool) -> Recipe:
    recipe.archived = archived
    session.flush()
    return recipe


def specs_from_version(
    version: RecipeVersion,
) -> tuple[list[IngredientSpec], list[StageSpec]]:
    """Turn a stored version back into editable input, to pre-fill the form."""
    ingredients = [
        IngredientSpec(
            name=i.name, role=i.role, baker_pct=i.baker_pct, notes=i.notes
        )
        for i in version.ingredients
    ]
    stages = [
        StageSpec(
            name=s.name,
            duration_min=s.duration_min,
            temp_c=s.temp_c,
            notes=s.notes,
        )
        for s in version.stages
    ]
    return ingredients, stages


# --- Equipment programs ----------------------------------------------------


def list_programs(
    session: Session, *, include_archived: bool = False
) -> list[EquipmentProgram]:
    stmt = select(EquipmentProgram).order_by(
        EquipmentProgram.archived, EquipmentProgram.device, EquipmentProgram.name
    )
    if not include_archived:
        stmt = stmt.where(EquipmentProgram.archived.is_(False))
    return list(session.scalars(stmt))


def create_program(session: Session, **fields: Any) -> EquipmentProgram:
    program = EquipmentProgram(**fields)
    session.add(program)
    session.flush()
    return program


def update_program(
    session: Session, program: EquipmentProgram, **fields: Any
) -> EquipmentProgram:
    for key, value in fields.items():
        setattr(program, key, value)
    session.flush()
    return program
