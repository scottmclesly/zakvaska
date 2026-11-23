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

import re
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
    "cinnamon": 132.0,
    "garlic powder": 156.0,
    "dried parsley": 21.0,
    "parsley": 21.0,
    "yeast": 149.0,
    # Dairy, eggs and the rest of a bread-machine shelf. Added with the
    # West Bend recipes, which are written in cups and spoons throughout.
    "dry milk": 68.0,
    "nonfat dry milk": 68.0,
    "yogurt": 245.0,
    "cider vinegar": 239.0,
    "vinegar": 239.0,
    "olive oil": 216.0,
    "canola oil": 218.0,
    "vegetable oil": 218.0,
    "agave syrup": 332.0,
    "agave": 332.0,
    "lemon extract": 230.0,
    # Gluten-free flours and starches
    "white rice flour": 142.0,
    "rice flour": 142.0,
    "potato starch": 152.0,
    "tapioca flour": 113.0,
    "tapioca starch": 113.0,
    "xanthan gum": 144.0,
    # Grains, seeds, nuts and fruit
    "oats": 85.0,
    "rolled oats": 85.0,
    "wheat bran": 57.0,
    "bran": 57.0,
    "flax seeds": 115.0,
    "sesame seeds": 144.0,
    "poppy seeds": 145.0,
    "sunflower seeds": 140.0,
    "pumpkin seeds": 125.0,
    "walnut": 113.0,
    "walnuts": 113.0,
    "pecans": 113.0,
    "chopped nuts": 113.0,
    "raisins": 149.0,
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
    numeric: bool = False,
) -> Measure:
    """Cups, tablespoons or teaspoons, whichever gives a number worth reading.

    `numeric` is for a form input rather than a page: "a pinch" reads better
    on a page but cannot be typed back in, so an editable field gets a number.
    """
    per_cup = grams_per_cup(name, role)
    cups = grams / per_cup

    if cups >= 0.25:
        text = f"{_fraction(cups)} {'cup' if cups <= 1 else 'cups'}"
    else:
        tbsp = cups * TBSP_PER_CUP
        # Rounded first: a recipe's percentage is stored to a tenth, so the
        # manual's "1 tbsp." can come back as 0.99 of one and would read as
        # "3 tsp" when the book plainly says a tablespoon.
        if round(tbsp, 1) >= 1:
            text = f"{_fraction(tbsp)} tbsp"
        else:
            tsp = cups * TSP_PER_CUP
            if tsp < 0.125:
                text = f"{_trim(tsp, 2)} tsp" if numeric else "a pinch"
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


def _total_is_flour(unit: str, flour: bool) -> bool:
    """Whether a total reads in cups: only a flour one, only in cups mode.

    A total *flour* weight is flour, so it has a density and a cup of it
    means something — the generic flour one, since a blend's exact density
    is nobody's measurement. A total *dough* weight is a mixture whose
    density nobody measures at all, so it stays a weight.
    """
    return flour and unit == US_VOLUME


def measure_total(
    grams: float | None, unit: str = METRIC, *, flour: bool = False
) -> Measure | None:
    """A total dough or flour weight, as the baker is reading amounts.

    Cups of mixed dough would be a made-up number, so a dough total falls
    back to ounces and pounds in volume mode — still the unit the reader
    asked for. A flour total reads in cups. See `_total_is_flour`.
    """
    if grams is None:
        return None
    if _total_is_flour(unit, flour):
        return in_us_volume(grams, role=IngredientRole.FLOUR)
    if unit in (US_VOLUME, US_WEIGHT):
        return in_us_weight(grams)
    return in_grams(grams)


# --- Reading what the baker typed ------------------------------------------
#
# The other direction. Most of Scott's recipes are written in cups or in
# ounces, so every weight field has to take them as well as grams: a bare
# number means whatever unit the switch is showing, and a number with a unit
# on it means that unit, whichever mode the app happens to be in.

#: Weight words, and what one of them weighs in grams.
GRAMS_PER_WORD: dict[str, float] = {
    "g": 1.0,
    "gm": 1.0,
    "gr": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "gramme": 1.0,
    "grammes": 1.0,
    "kg": 1000.0,
    "kilo": 1000.0,
    "kilos": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
    "oz": GRAMS_PER_OUNCE,
    "ozs": GRAMS_PER_OUNCE,
    "ounce": GRAMS_PER_OUNCE,
    "ounces": GRAMS_PER_OUNCE,
    "lb": GRAMS_PER_OUNCE * OUNCES_PER_POUND,
    "lbs": GRAMS_PER_OUNCE * OUNCES_PER_POUND,
    "pound": GRAMS_PER_OUNCE * OUNCES_PER_POUND,
    "pounds": GRAMS_PER_OUNCE * OUNCES_PER_POUND,
}

#: Volume words, and how many US cups one of them is. These need a density
#: before they are grams, which is why they are kept apart.
CUPS_PER_WORD: dict[str, float] = {
    "c": 1.0,
    "cup": 1.0,
    "cups": 1.0,
    "tbsp": 1 / TBSP_PER_CUP,
    "tbsps": 1 / TBSP_PER_CUP,
    "tbs": 1 / TBSP_PER_CUP,
    "tbl": 1 / TBSP_PER_CUP,
    "tblsp": 1 / TBSP_PER_CUP,
    "tablespoon": 1 / TBSP_PER_CUP,
    "tablespoons": 1 / TBSP_PER_CUP,
    "tsp": 1 / TSP_PER_CUP,
    "tsps": 1 / TSP_PER_CUP,
    "teaspoon": 1 / TSP_PER_CUP,
    "teaspoons": 1 / TSP_PER_CUP,
    "pt": 2.0,
    "pint": 2.0,
    "pints": 2.0,
    "qt": 4.0,
    "quart": 4.0,
    "quarts": 4.0,
    "floz": 0.125,
    "ml": 1 / 236.588,
    "mls": 1 / 236.588,
    "milliliter": 1 / 236.588,
    "milliliters": 1 / 236.588,
    "millilitre": 1 / 236.588,
    "millilitres": 1 / 236.588,
    "cc": 1 / 236.588,
    "dl": 100 / 236.588,
    "l": 1000 / 236.588,
    "liter": 1000 / 236.588,
    "liters": 1000 / 236.588,
    "litre": 1000 / 236.588,
    "litres": 1000 / 236.588,
    # A stick of butter, which is how an American recipe says half a cup.
    "stick": 0.5,
    "sticks": 0.5,
    # The small end, because the manual's recipes use both.
    "dash": 0.125 / TSP_PER_CUP,
    "dashes": 0.125 / TSP_PER_CUP,
    "pinch": 0.0625 / TSP_PER_CUP,
    "pinches": 0.0625 / TSP_PER_CUP,
}

#: Words that carry no quantity and are simply skipped.
FILLER_WORDS = frozenset(
    {
        "a",
        "an",
        "about",
        "approx",
        "approximately",
        "and",
        "plus",
        "of",
        "scant",
        "heaping",
        "heaped",
        "rounded",
        "level",
        "generous",
        "packed",
        "sifted",
        "each",
        "total",
    }
)

#: What the keypad cannot type but a cookbook always does.
FRACTION_GLYPHS: dict[str, float] = {
    "½": 0.5,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "¼": 0.25,
    "¾": 0.75,
    "⅕": 0.2,
    "⅖": 0.4,
    "⅗": 0.6,
    "⅘": 0.8,
    "⅙": 1 / 6,
    "⅚": 5 / 6,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
}

#: The unit a bare number is in, per display mode.
DEFAULT_WORD = {METRIC: "g", US_WEIGHT: "oz", US_VOLUME: "cup"}


#: Shown whenever a field cannot be read, so the answer is in the error.
EXAMPLES = "250 g, 8 oz, 1 lb 2 oz or 1 \u00bd cups"


class QuantityError(ValueError):
    """What the user typed is not a weight anyone could act on."""


def _normalize(text: str) -> str:
    """Lowercase, with the cookbook's typography spelled out."""
    cleaned = text.strip().lower()
    cleaned = cleaned.replace(" ", " ")
    for glyph, value in FRACTION_GLYPHS.items():
        # Spaces around it, so "1½" becomes two numbers that then add up.
        cleaned = cleaned.replace(glyph, f" {value!r} ")
    cleaned = cleaned.replace("fluid ounce", "floz").replace("fl oz", "floz")
    cleaned = cleaned.replace("fl. oz", "floz").replace("fl.oz", "floz")
    # Thousands separators, and the dash in "1-1/2".
    cleaned = cleaned.replace(",", "")
    for char in "-+/()":
        if char == "/":
            continue
        cleaned = cleaned.replace(char, " ")
    # A period that is not a decimal point is punctuation: "2 tbsp." .
    cleaned = re.sub(r"\.(?!\d)", " ", cleaned)
    # "3 / 4" is one fraction, however it was spaced.
    cleaned = re.sub(r"\s*/\s*", "/", cleaned)
    return " ".join(cleaned.split())


def _tokens(text: str) -> list[str]:
    """Numbers, fractions and words, each on its own — "250g" is two."""
    out: list[str] = []
    buffer = ""
    kind = ""
    for char in text + " ":
        this = (
            "num"
            if char.isdigit() or char in "./"
            else "word"
            if char.isalpha()
            else ""
        )
        if this != kind and buffer:
            out.append(buffer)
            buffer = ""
        kind = this
        if this:
            buffer += char
    if buffer:
        out.append(buffer)
    return out


def _number(token: str) -> float:
    """A token as a number: "2", "1.5" or "3/4"."""
    if "/" in token:
        top, _, bottom = token.partition("/")
        try:
            divisor = float(bottom)
            if divisor == 0:
                raise ZeroDivisionError
            return float(top) / divisor
        except (ValueError, ZeroDivisionError):
            raise QuantityError(f'"{token}" is not a number') from None
    try:
        return float(token)
    except ValueError:
        raise QuantityError(f'"{token}" is not a number') from None


def parse_quantity(
    text: str | None,
    unit: str = METRIC,
    *,
    name: str | None = None,
    role: IngredientRole | str | None = None,
) -> float | None:
    """Grams, from however the baker wrote it down.

    A bare number is read in whatever unit is on display, so the field agrees
    with the label above it. A unit written out wins over that, in either
    direction: "250 g" is grams while the app is showing cups, and "1 ½ cups"
    is cups while it is showing grams. Several run-on amounts add up, because
    that is how both a scale ("1 lb 4 oz") and a manual ("2 tbsp + 2 tsp")
    write them.

    Returns None for an empty field. Anything it cannot read raises
    QuantityError, which is a ValueError, so routes handle it as they handle
    every other bad field.
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    # A hyphen is the mixed-number separator in "1-1/2", so it cannot simply
    # be stripped: a minus sign — one that starts an amount — is caught here
    # before normalizing turns it into a space and loses the sign.
    if re.search(r"(?:^|[\s(])-\s*[\d.]", raw):
        raise QuantityError("an amount cannot be negative")

    default = DEFAULT_WORD.get(unit, "g")
    per_cup = grams_per_cup(name, role)
    grams = 0.0
    pending: float | None = None
    seen = False

    def flush(word: str) -> None:
        nonlocal grams, pending, seen
        amount = 1.0 if pending is None else pending
        if word in GRAMS_PER_WORD:
            grams += amount * GRAMS_PER_WORD[word]
        else:
            grams += amount * CUPS_PER_WORD[word] * per_cup
        pending = None
        seen = True

    for token in _tokens(_normalize(raw)):
        if token[0].isdigit() or token[0] in "./":
            value = _number(token)
            pending = value if pending is None else pending + value
        elif token in GRAMS_PER_WORD or token in CUPS_PER_WORD:
            flush(token)
        elif token in FILLER_WORDS:
            continue
        else:
            raise QuantityError(
                f'could not read "{raw}" as an amount '
                f'("{token}" is not a unit I know) — try {EXAMPLES}'
            )

    if pending is not None:
        flush(default)

    if not seen:
        raise QuantityError(
            f'could not read "{raw}" as an amount — try {EXAMPLES}'
        )
    if grams < 0:
        raise QuantityError("An amount cannot be negative")
    return grams


def parse_total(
    text: str | None, unit: str = METRIC, *, flour: bool = False
) -> float | None:
    """A total flour or dough weight, read the way it is shown.

    See measure_total: a bare number in a dough total is ounces in either
    US mode, because cups of dough would be a made-up number; a bare number
    in a flour total is cups while cups are on display. Writing the unit
    out still wins over both.
    """
    if _total_is_flour(unit, flour):
        return parse_quantity(text, US_VOLUME, role=IngredientRole.FLOUR)
    mode = US_WEIGHT if unit in (US_VOLUME, US_WEIGHT) else METRIC
    return parse_quantity(text, mode)


def _ounce_text(ounces: float) -> str:
    """Ounces with as few decimals as still weigh the right thing.

    An ounce is a coarse unit for 2 g of salt: two decimals of one is a
    quarter of a gram, so a small amount gets a third decimal rather than
    being quietly rounded away on the way back in. 1.41 oz stays 1.41 oz.
    """
    for places in (1, 2, 3):
        text = _trim(ounces, places)
        if abs(float(text) * GRAMS_PER_OUNCE - ounces * GRAMS_PER_OUNCE) <= 0.05:
            return text
    return _trim(ounces, 3)


def input_text(
    grams: float | None,
    unit: str = METRIC,
    *,
    name: str | None = None,
    role: IngredientRole | str | None = None,
) -> str:
    """A stored weight as something editable, in the unit on display.

    Not the same as `measure`: this has to go back through `parse_quantity`
    unchanged, and grams are left bare so a gram field still reads as the
    plain number it always did.

    The round trip is only as exact as the unit allows — re-saving a form in
    cups snaps the value to the nearest spoon. That is the deal with volume
    measurement, and the reason grams are what gets stored.
    """
    if grams is None:
        return ""
    if unit == US_WEIGHT:
        ounces = grams / GRAMS_PER_OUNCE
        if ounces < OUNCES_PER_POUND:
            return f"{_ounce_text(ounces)} oz"
        pounds, rest = divmod(round(ounces, 1), OUNCES_PER_POUND)
        if rest < 0.05:
            return f"{int(pounds)} lb"
        return f"{int(pounds)} lb {_trim(rest)} oz"
    if unit == US_VOLUME:
        return in_us_volume(grams, name=name, role=role, numeric=True).text
    return _trim(grams, 1)


def input_total_text(
    grams: float | None, unit: str = METRIC, *, flour: bool = False
) -> str:
    """The editable form of a total, in the unit its label claims."""
    if _total_is_flour(unit, flour):
        return input_text(grams, US_VOLUME, role=IngredientRole.FLOUR)
    mode = US_WEIGHT if unit in (US_VOLUME, US_WEIGHT) else METRIC
    return input_text(grams, mode)


def input_placeholder(unit: str = METRIC) -> str:
    """An example in the unit on display, for an empty field."""
    return {METRIC: "500", US_WEIGHT: "1 lb 2 oz", US_VOLUME: "3 cups"}.get(
        unit, "500"
    )


def input_total_placeholder(unit: str = METRIC, *, flour: bool = False) -> str:
    """The same for a total: a weight, unless it is flour read in cups."""
    if _total_is_flour(unit, flour):
        return input_placeholder(US_VOLUME)
    mode = US_WEIGHT if unit in (US_VOLUME, US_WEIGHT) else METRIC
    return input_placeholder(mode)


def total_unit_label(unit: str = METRIC, *, flour: bool = False) -> str:
    """What to print above a total, so the field says how it is read."""
    if _total_is_flour(unit, flour):
        return UNIT_LABELS[US_VOLUME]
    if unit == METRIC:
        return UNIT_LABELS[METRIC]
    return UNIT_LABELS[US_WEIGHT]
