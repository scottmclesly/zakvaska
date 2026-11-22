"""Turning a volume-measured recipe into baker's percentages.

American bread-machine books are written in cups and spoons, and this app
stores baker's percentages against total flour (CLAUDE.md). Doing that
conversion by hand across twenty recipes is a hundred chances to fat-finger
a number, so it happens here instead, from the same per-ingredient
densities the app uses to *display* cups — `app/services/measures.py`.

Two things worth being straight about:

* A cup of flour is not a fixed weight. These densities are the usual
  reference figures and the result is a good working formula, not a
  measurement. That is why every seeded ingredient keeps the manual's own
  wording in its notes: the original is the authority, the percentage is
  the convenience.
* "Total flour" means the lines actually called flour, including the
  starches that stand in for it in a gluten-free loaf. Oats, bran, seeds
  and nuts are carried as other ingredients, so hydration reads the way a
  baker expects rather than being diluted by a cup of pecans.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import IngredientRole
from app.services import measures

#: Fractions of a US cup.
CUP = 1.0
TBSP = 1.0 / 16.0
TSP = 1.0 / 48.0

#: A US large egg, shelled: white plus yolk.
EGG_G = 50.0
EGG_YOLK_G = 18.0
#: One envelope of dry yeast, as sold.
YEAST_PACKET_G = 7.0


@dataclass(frozen=True)
class Item:
    """One line of a recipe as the book writes it."""

    name: str
    role: IngredientRole
    #: How much, in cups. Use the CUP / TBSP / TSP constants.
    cups: float | None = None
    #: For what cups cannot say: eggs, packets of yeast.
    grams: float | None = None
    #: The book's own words, kept verbatim for the ingredient's notes.
    original: str = ""
    #: When the line's name is not in the density table — "Potato Starch
    #: Flour" is listed there as "potato starch".
    density_as: str | None = None

    def weight(self) -> float:
        if self.grams is not None:
            return self.grams
        if self.cups is None:
            raise ValueError(f"{self.name}: needs cups or grams")
        key = self.density_as or self.name
        return self.cups * measures.grams_per_cup(key, role=self.role)


def total_flour_g(items: list[Item]) -> float:
    return sum(i.weight() for i in items if i.role is IngredientRole.FLOUR)


def batch_flour_g(items: list[Item]) -> float:
    """The flour weight the percentages are against, rounded to a gram.

    Kept on the seeded version so the recipe page can show the manual's own
    amounts straight away rather than asking how much flour to scale to.
    """
    return round(total_flour_g(items), 1)


def to_ingredients(items: list[Item]) -> list[dict]:
    """Baker's percentages, rounded to a tenth — finer is false precision."""
    flour = total_flour_g(items)
    if flour <= 0:
        raise ValueError("a recipe with no flour has no percentages")
    return [
        {
            "name": item.name,
            "role": item.role.value,
            "pct": round(item.weight() / flour * 100, 1),
            "notes": item.original or None,
        }
        for item in items
    ]
