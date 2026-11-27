"""What the two browsing pages show on a card: the recipes and the bakes.

A list of thirty recipes that all look alike is a list nobody reads, and a
loaf with a photograph deserves to be seen by it. So each card is worked
out here, once per page, in a handful of queries rather than one per card:

* a recipe gets the shape it is drawn as, the two numbers a baker reads a
  formula by (hydration and how long it takes), how often it has been
  baked and how well, and the photograph of its best loaf if there is one;
* a bake gets its cover photograph and a count of the rest.

Nothing here is stored. It is all derived from what the notebook holds.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.bake import Bake
from app.models.enums import IngredientRole, PhotoOwner, RecipeCategory
from app.models.photo import Photo
from app.models.recipe import Recipe, RecipeVersion
from app.services import bakes as bake_service
from app.services import photos as photo_service

# --- The shape a loaf is drawn as ---------------------------------------------

#: A word in the name that says what the bread looks like, whatever family
#: it belongs to. First match wins, so the more particular come first.
_NAMED_SHAPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("baguette", ("baguette",)),
    ("ring", ("ring", "ruisleip", "bagel")),
    ("rolls", ("rolls", "bread sticks", "buns", "bun ")),
    ("flat", ("focaccia", "ciabatta", "pizza", "flatbread", "pita", "naan")),
)

#: Bread-maker programs that hand the dough back rather than baking it.
_DOUGH_ONLY = ("dough", "mix")

SHAPE_LABELS = {
    "rye": "a dark rye brick",
    "wheat": "a scored round loaf",
    "enriched": "a plaited loaf",
    "other": "a slashed loaf",
    "tin": "a tall tin loaf",
    "baguette": "a baguette",
    "flat": "a flat bread",
    "rolls": "a tray of rolls",
    "ring": "a ring loaf",
}


def loaf_shape(recipe: Recipe) -> str:
    """How to draw this recipe's bread.

    The family decides the colour and, by default, the shape: a rye brick,
    a wheat boule, a plait, a batard. A name that says otherwise (a
    baguette is not a boule) or a bread maker's pan (which makes one shape
    of loaf whatever goes in it) overrides the default.
    """
    name = f" {recipe.name.lower()} "
    for shape, words in _NAMED_SHAPES:
        if any(word in name for word in words):
            return shape
    family = recipe.category.value
    # Rye from a tin is already drawn as a brick.
    if recipe.category is RecipeCategory.RYE:
        return family
    latest = recipe.latest_version
    program = latest.default_program if latest else None
    if program is not None and program.name.strip().lower() not in _DOUGH_ONLY:
        return "tin"
    return family


# --- Recipes -------------------------------------------------------------------

#: The span of hydrations a card shows. See _hydration.
HYDRATION_SHOWN = (45, 110)


@dataclass(frozen=True)
class RecipeCard:
    recipe: Recipe
    latest: RecipeVersion | None
    shape: str
    #: Water as a percentage of flour, or None when the recipe has no water
    #: line (an enriched dough wetted with milk, say).
    hydration: float | None
    #: Every stage's minutes added up, or None when none are given.
    total_min: int | None
    #: Loaves baked from any version of it, planned ones not counted.
    baked: int
    best_rating: int | None
    #: The photograph of its best-rated loaf (the newest, among equals).
    cover: Photo | None


def _hydration(version: RecipeVersion | None) -> float | None:
    if version is None:
        return None
    flour = sum(i.baker_pct for i in version.ingredients if i.role is IngredientRole.FLOUR)
    water = sum(i.baker_pct for i in version.ingredients if i.role is IngredientRole.WATER)
    if not flour or not water:
        return None
    pct = round(water / flour * 100)
    # Only where water is what wets the dough. A brioche is wetted with eggs
    # and butter and a pasta with eggs alone, and "9% water" on the card
    # would be true and say nothing; a figure well over 100 is a batter.
    return pct if HYDRATION_SHOWN[0] <= pct <= HYDRATION_SHOWN[1] else None


def time_label(minutes: int | None) -> str | None:
    """How long a recipe takes, short enough for a card: '45 min', '3.5 h',
    '16 h', '2 days'. Rounder as it gets longer, as people say it."""
    if not minutes:
        return None
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    if hours < 10:
        return f"{hours:.1f}".rstrip("0").rstrip(".") + " h"
    if hours < 48:
        return f"{round(hours)} h"
    return f"{round(hours / 24)} days"


def _total_min(version: RecipeVersion | None) -> int | None:
    if version is None:
        return None
    total = sum(stage.duration_min or 0 for stage in version.stages)
    return total or None


def recipe_cards(session: Session, recipes: list[Recipe]) -> list[RecipeCard]:
    bakes = [b for b in bake_service.list_bakes(session) if b.started_at is not None]
    covers = _covers(session, bakes)

    by_recipe: dict[int, list[Bake]] = {}
    for bake in bakes:
        by_recipe.setdefault(bake.version.recipe_id, []).append(bake)

    cards = []
    for recipe in recipes:
        mine = by_recipe.get(recipe.id, [])
        ratings = [b.result.rating for b in mine if b.result and b.result.rating]
        # Best loaf first, newest among equals; the first with a photo wins.
        ranked = sorted(
            mine,
            key=lambda b: ((b.result.rating or 0) if b.result else 0, b.at),
            reverse=True,
        )
        cover = next((covers[b.id] for b in ranked if b.id in covers), None)
        latest = recipe.latest_version
        cards.append(
            RecipeCard(
                recipe=recipe,
                latest=latest,
                shape=loaf_shape(recipe),
                hydration=_hydration(latest),
                total_min=_total_min(latest),
                baked=len(mine),
                best_rating=max(ratings) if ratings else None,
                cover=cover,
            )
        )
    return cards


@dataclass(frozen=True)
class RecipeShelf:
    """One row of the recipes page: a family of bread, or your own bakes."""

    key: str
    label: str
    blurb: str
    cards: tuple[RecipeCard, ...]


#: The families in the order they are shelved, and a line for each.
_FAMILY_BLURBS = {
    RecipeCategory.RYE: "Dense, dark and sour: scalds, sponges and long proofs.",
    RecipeCategory.WHEAT: "Boules, tins and baguettes, lean and crusty.",
    RecipeCategory.ENRICHED: "Butter, eggs, milk and sugar: soft and golden.",
    RecipeCategory.OTHER: "Everything that is not quite a loaf.",
}


def recipe_shelves(cards: list[RecipeCard]) -> list[RecipeShelf]:
    """The cards arranged for browsing.

    What you have baked comes first, best loaf first, because that row has
    your own photographs in it and is the reason to open the page. Then one
    shelf per family, in the same order as everywhere else. A recipe you
    have baked is on both: once as yours, once where it belongs.
    """
    shelves: list[RecipeShelf] = []
    baked = sorted(
        (card for card in cards if card.baked),
        key=lambda card: (card.best_rating or 0, card.baked),
        reverse=True,
    )
    if baked:
        shelves.append(
            RecipeShelf(
                key="baked",
                label="Baked by you",
                blurb="The ones you have made, best loaf first.",
                cards=tuple(baked),
            )
        )
    for family in RecipeCategory:
        mine = tuple(card for card in cards if card.recipe.category is family)
        if mine:
            shelves.append(
                RecipeShelf(
                    key=family.value,
                    label=family.label,
                    blurb=_FAMILY_BLURBS.get(family, ""),
                    cards=mine,
                )
            )
    return shelves


# --- Bakes ---------------------------------------------------------------------


@dataclass(frozen=True)
class BakeCard:
    bake: Bake
    cover: Photo | None
    photos: int
    shape: str


@dataclass(frozen=True)
class BakeSummary:
    """One line over the wall of loaves: what there is to be pleased about."""

    loaves: int
    photographed: int
    rated: int
    average: float | None


def _covers(session: Session, bakes: list[Bake]) -> dict[int, Photo]:
    """Each bake's first photograph, which is the one its own page leads with."""
    grouped = photo_service.photos_by_owner(
        session, PhotoOwner.BAKE, [bake.id for bake in bakes]
    )
    return {bake_id: photos[0] for bake_id, photos in grouped.items() if photos}


def bake_cards(session: Session, bakes: list[Bake]) -> list[BakeCard]:
    grouped = photo_service.photos_by_owner(
        session, PhotoOwner.BAKE, [bake.id for bake in bakes]
    )
    return [
        BakeCard(
            bake=bake,
            cover=(grouped.get(bake.id) or [None])[0],
            photos=len(grouped.get(bake.id, ())),
            shape=loaf_shape(bake.recipe),
        )
        for bake in bakes
    ]


def bake_summary(cards: list[BakeCard]) -> BakeSummary:
    ratings = [
        c.bake.result.rating
        for c in cards
        if c.bake.result is not None and c.bake.result.rating
    ]
    return BakeSummary(
        loaves=len(cards),
        photographed=sum(1 for c in cards if c.cover is not None),
        rated=len(ratings),
        average=round(sum(ratings) / len(ratings), 1) if ratings else None,
    )
