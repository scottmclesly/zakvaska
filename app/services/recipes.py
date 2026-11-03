"""Recipe CRUD and versioning.

Editing never changes a version in place. Every edit writes a new one, so a
bake recorded against v1 still describes what was actually made after v2
exists (CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import IngredientRole, RecipeCategory
from app.models.recipe import (
    EquipmentCycle,
    EquipmentProgram,
    Recipe,
    RecipeIngredient,
    RecipeStage,
    RecipeVersion,
)
from app.services import charts


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


# --- Phases laid out along a bar -------------------------------------------
#
# A program's cycle and a recipe's stages are both "these phases, in this
# order, for these many minutes", so both go through charts.time_bar. These
# are registered as template globals: the templates already walk the cycles
# and stages themselves, and threading a dict of bars through every route
# that renders one would be worse than letting the page ask.


def cycle_bar(cycle: EquipmentCycle) -> charts.TimeBar | None:
    """The machine's own clock for one loaf size, to scale.

    Keep-warm is left out on purpose: it is what happens if the bread is not
    taken out, not part of the run, and counting it would make every program
    look an hour longer than it is.
    """
    stir_min = (
        cycle.stir_down_sec / 60 if cycle.stir_down_sec else None
    )
    return charts.time_bar(
        [
            ("Knead 1", "knead", cycle.knead1_min),
            ("Rest", "rest", cycle.rest_min),
            ("Knead 2", "knead", cycle.knead2_min),
            ("Rise 2", "rise", cycle.rise2_min),
            ("Stir", "stir", stir_min),
            ("Rise 3", "rise", cycle.rise3_min),
            ("Bake", "bake", cycle.bake_min),
        ],
        total_min=cycle.total_min,
    )


_STAGE_KEYS = (
    ("scald", "scald"),
    ("zavarka", "scald"),
    ("sponge", "sponge"),
    ("levain", "sponge"),
    ("mix", "knead"),
    ("knead", "knead"),
    ("autolyse", "rest"),
    ("rest", "rest"),
    ("bulk", "rise"),
    ("ferment", "rise"),
    ("proof", "rise"),
    ("rise", "rise"),
    ("bake", "bake"),
    ("cool", "cool"),
)


def stage_key(name: str) -> str:
    """Which kind of phase a stage is, read off its name.

    Stage names are the baker's own words (CLAUDE.md keeps that vocabulary
    open), so the colour is guessed from the name rather than stored. A
    guess that misses lands on "other", which is only a colour.
    """
    lowered = name.lower()
    for needle, key in _STAGE_KEYS:
        if needle in lowered:
            return key
    return "other"


def stage_bar(stages: Sequence[RecipeStage]) -> charts.TimeBar | None:
    """A version's stages to scale, so the shape of the day is visible.

    Untimed stages are kept: a stage with no minutes against it is still a
    step that happens, and the bar marks it as having no time rather than
    dropping it and quietly rewriting the method.
    """
    return charts.time_bar(
        [(stage.name, stage_key(stage.name), stage.duration_min) for stage in stages],
        keep_unknown=True,
    )
