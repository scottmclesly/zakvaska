"""Baker's percentages into grams.

The convention, and the one thing to keep straight: **total flour is 100%**,
and every other ingredient is a percentage of that flour weight — not of the
finished dough. So a 500 g flour recipe at 80% water uses 400 g of water, and
the dough ends up heavier than 500 g.

Levain is treated as its own line rather than being broken back down into the
flour and water it contains. That keeps the arithmetic honest about what was
actually weighed out, which is what a lab notebook is for; it does mean the
hydration figure here is the dough's added water, not its true total.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.models.enums import IngredientRole
from app.models.recipe import RecipeIngredient


@dataclass(frozen=True)
class ScaledIngredient:
    name: str
    role: IngredientRole
    baker_pct: float
    grams: float
    notes: str | None = None


@dataclass(frozen=True)
class ScaledRecipe:
    total_flour_g: float
    total_dough_g: float
    ingredients: list[ScaledIngredient]
    flour_pct: float
    total_pct: float
    warnings: list[str] = field(default_factory=list)

    @property
    def hydration_pct(self) -> float | None:
        """Added water as a percentage of flour. Levain is not decomposed."""
        if self.flour_pct <= 0:
            return None
        water = sum(
            i.baker_pct for i in self.ingredients if i.role is IngredientRole.WATER
        )
        return water / self.flour_pct * 100


def flour_percentage(ingredients: Iterable[RecipeIngredient]) -> float:
    return sum(
        i.baker_pct for i in ingredients if i.role is IngredientRole.FLOUR
    )


def total_percentage(ingredients: Iterable[RecipeIngredient]) -> float:
    return sum(i.baker_pct for i in ingredients)


def _warnings(ingredients: Sequence[RecipeIngredient], flour_pct: float) -> list[str]:
    notes: list[str] = []
    if not ingredients:
        return ["This version has no ingredients yet."]
    if flour_pct <= 0:
        notes.append(
            "No ingredient is marked as flour, so there is nothing for the "
            "percentages to be a percentage of."
        )
    elif abs(flour_pct - 100) > 0.01:
        # Not an error: a half-written recipe is allowed to be wrong.
        notes.append(
            f"Flour adds up to {flour_pct:g}%, not 100%. "
            "Baker's percentages are measured against total flour, so the "
            "grams below will be off until that is fixed."
        )
    return notes


def scale_to_flour(
    ingredients: Sequence[RecipeIngredient], total_flour_g: float
) -> ScaledRecipe:
    """Grams for every line, given how much flour you want to use."""
    if total_flour_g < 0:
        raise ValueError("Flour weight cannot be negative")

    flour_pct = flour_percentage(ingredients)
    total_pct = total_percentage(ingredients)

    scaled = [
        ScaledIngredient(
            name=i.name,
            role=i.role,
            baker_pct=i.baker_pct,
            grams=i.baker_pct / 100 * total_flour_g,
            notes=i.notes,
        )
        for i in ingredients
    ]

    return ScaledRecipe(
        total_flour_g=total_flour_g,
        total_dough_g=sum(i.grams for i in scaled),
        ingredients=scaled,
        flour_pct=flour_pct,
        total_pct=total_pct,
        warnings=_warnings(ingredients, flour_pct),
    )


def scale_to_dough_weight(
    ingredients: Sequence[RecipeIngredient], target_dough_g: float
) -> ScaledRecipe:
    """Work backwards from a finished dough weight to the flour it needs.

    Useful when the tin, not the flour bag, is what is fixed.
    """
    if target_dough_g < 0:
        raise ValueError("Dough weight cannot be negative")

    total_pct = total_percentage(ingredients)
    if total_pct <= 0:
        raise ValueError(
            "The percentages add up to nothing, so no flour weight can be "
            "worked out from a dough weight."
        )

    return scale_to_flour(ingredients, target_dough_g * 100 / total_pct)
