"""Showing a weight the way the recipe in front of you writes it.

Everything is stored in grams (CLAUDE.md), which is the only sane way to
keep a lab notebook. But Scott's recipes come from everywhere: a Russian
Borodinsky in grams, an American bread-machine book in cups, a bread-maker
manual in pounds. This turns the stored grams into whichever of those he is
reading at the time.

Cups and spoons are volume, so they need a density per ingredient — a cup of
rye flour is 103 g and a cup of water is 237 g. The table below is the usual
baking reference (King Arthur's, mostly). It is approximate by nature: how
hard you pack a cup of flour changes it by 20%, which is exactly why the
grams are what we store and the cups are only a reading.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import IngredientRole

# Display modes. The value is what goes in the settings table.
METRIC = "g"
US_VOLUME = "us_volume"
US_WEIGHT = "us_weight"

UNIT_LABELS = {
    METRIC: "grams",
    US_VOLUME: "cups",
    US_WEIGHT: "oz / lb",
}

# The order the control cycles in.
UNIT_CYCLE = (METRIC, US_VOLUME, US_WEIGHT)

GRAMS_PER_OUNCE = 28.349523125
OUNCES_PER_POUND = 16

TBSP_PER_CUP = 16
TSP_PER_CUP = 48

# Grams per US cup. Keys are matched against a lowercased ingredient name:
# the longest key contained in the name wins, so "whole rye flour" beats
# "flour".
DENSITIES: dict[str, float] = {
    # Flours
    "whole rye flour": 103.0,
    "dark rye flour": 103.0,
    "medium rye flour": 103.0,
    "light rye flour": 110.0,
    "rye flour": 103.0,
    "pumpernickel": 103.0,
    "whole wheat flour": 113.0,
    "whole wheat": 113.0,
    "bread flour": 120.0,
    "all-purpose flour": 120.0,
    "plain flour": 120.0,
    "spelt flour": 99.0,
    "semolina": 163.0,
    "flour": 120.0,
    # A feeding's flour type is written the short way: "whole rye", "spelt".
    "whole rye": 103.0,
    "dark rye": 103.0,
    "light rye": 110.0,
    "rye": 103.0,
    "whole grain": 113.0,
    "wheat": 120.0,
    "spelt": 99.0,
    "einkorn": 96.0,
    # Malts and other powders
    "red rye malt": 100.0,
    "rye malt": 100.0,
    "diastatic malt": 112.0,
    "malt": 100.0,
    "cocoa": 85.0,
    "vital wheat gluten": 136.0,
    # Liquids
    "water": 236.0,
    "milk": 244.0,
    "buttermilk": 242.0,
    "kvass": 240.0,
    "beer": 236.0,
    "oil": 218.0,
    "melted butter": 227.0,
    "butter": 227.0,
    # Levain
    "levain": 240.0,
    "starter": 240.0,
    "zakvaska": 240.0,
    "sponge": 240.0,
    "scald": 240.0,
    "zavarka": 240.0,
    # Sweeteners
    "molasses": 325.0,
    "honey": 340.0,
    "maple syrup": 322.0,
    "brown sugar": 213.0,
    "sugar": 198.0,
    # Salt and spices
    "kosher salt": 145.0,
    "sea salt": 288.0,
    "table salt": 288.0,
    "salt": 288.0,
    "coriander": 96.0,
    "caraway": 100.0,
    "fennel": 96.0,
    "yeast": 149.0,
}

# When the name says nothing, the role does.
ROLE_DENSITIES: dict[IngredientRole, float] = {
    IngredientRole.FLOUR: 120.0,
    IngredientRole.WATER: 236.0,
    IngredientRole.LEVAIN: 240.0,
    IngredientRole.SALT: 288.0,
    IngredientRole.SWEETENER: 300.0,
    IngredientRole.FAT: 218.0,
    IngredientRole.OTHER: 120.0,
}

FALLBACK_DENSITY = 120.0

# Snapped to, because no one measures 0.41 of a cup.
FRACTIONS: tuple[tuple[float, str], ...] = (
    (0.0, ""),
    (0.125, "⅛"),
    (0.25, "¼"),
    (0.333333, "⅓"),
    (0.5, "½"),
    (0.666667, "⅔"),
    (0.75, "¾"),
    (0.875, "⅞"),
    (1.0, "1"),
)


def as_role(role: IngredientRole | str | None) -> IngredientRole | None:
    """Templates can only pass a string; take either."""
    if role is None or isinstance(role, IngredientRole):
        return role
    try:
        return IngredientRole(str(role))
    except ValueError:
        return None


def grams_per_cup(
    name: str | None = None, role: IngredientRole | str | None = None
) -> float:
    """How much a cup of this weighs."""
    role = as_role(role)
    if name:
        lowered = name.strip().lower()
        matches = [key for key in DENSITIES if key in lowered]
        if matches:
            return DENSITIES[max(matches, key=len)]
    if role is not None:
        return ROLE_DENSITIES.get(role, FALLBACK_DENSITY)
    return FALLBACK_DENSITY


def _fraction(value: float) -> str:
    """A number as a cook would write it: 1 ½, ¾, 2."""
    whole = int(value)
    rest = value - whole
    nearest, glyph = min(FRACTIONS, key=lambda pair: abs(pair[0] - rest))
    if nearest == 1.0:
        whole += 1
        glyph = ""
    if whole and glyph:
        return f"{whole} {glyph}"
    if glyph:
        return glyph
    return str(whole)


@dataclass(frozen=True)
class Measure:
    """A weight, said in some unit, with the grams kept for the tooltip."""

    text: str
    grams: float
    approximate: bool = False

    def __str__(self) -> str:
        return self.text


def _trim(value: float, places: int = 1) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".") or "0"


def in_grams(grams: float) -> Measure:
    return Measure(text=f"{_trim(grams)} g", grams=grams)


def in_us_weight(grams: float) -> Measure:
    """Ounces, and pounds once there are enough of them."""
    ounces = grams / GRAMS_PER_OUNCE
    if ounces < 1:
        return Measure(text=f"{_trim(ounces, 2)} oz", grams=grams)
    # Round first, then decide. 453 g is 15.98 oz, which has to read "1 lb"
    # rather than "16 oz" — the rounding is what crosses the boundary.
    ounces = round(ounces, 1)
    if ounces < OUNCES_PER_POUND:
        return Measure(text=f"{_trim(ounces)} oz", grams=grams)
    pounds, rest = divmod(ounces, OUNCES_PER_POUND)
    if rest < 0.05:
        return Measure(text=f"{int(pounds)} lb", grams=grams)
    return Measure(text=f"{int(pounds)} lb {_trim(rest)} oz", grams=grams)


def in_us_volume(
    grams: float,
    *,
    name: str | None = None,
    role: IngredientRole | str | None = None,
) -> Measure:
    """Cups, tablespoons or teaspoons, whichever gives a number worth reading."""
    per_cup = grams_per_cup(name, role)
    cups = grams / per_cup

    if cups >= 0.25:
        text = f"{_fraction(cups)} {'cup' if cups <= 1 else 'cups'}"
    else:
        tbsp = cups * TBSP_PER_CUP
        if tbsp >= 1:
            text = f"{_fraction(tbsp)} tbsp"
        else:
            tsp = cups * TSP_PER_CUP
            if tsp < 0.125:
                text = "a pinch"
            else:
                text = f"{_fraction(tsp)} tsp"
    return Measure(text=text, grams=grams, approximate=True)


def measure(
    grams: float | None,
    unit: str = METRIC,
    *,
    name: str | None = None,
    role: IngredientRole | str | None = None,
) -> Measure | None:
    """The one entry point: grams in, whatever the user is reading out."""
    if grams is None:
        return None
    if unit == US_WEIGHT:
        return in_us_weight(grams)
    if unit == US_VOLUME:
        return in_us_volume(grams, name=name, role=role)
    return in_grams(grams)


def measure_total(grams: float | None, unit: str = METRIC) -> Measure | None:
    """A total dough or flour weight, which has no sensible volume.

    Cups of mixed dough would be a made-up number, so volume mode falls back
    to ounces and pounds — still the unit the reader asked for.
    """
    if grams is None:
        return None
    if unit in (US_VOLUME, US_WEIGHT):
        return in_us_weight(grams)
    return in_grams(grams)


def next_unit(unit: str) -> str:
    """What the cycle button switches to."""
    try:
        return UNIT_CYCLE[(UNIT_CYCLE.index(unit) + 1) % len(UNIT_CYCLE)]
    except ValueError:
        return UNIT_CYCLE[0]
