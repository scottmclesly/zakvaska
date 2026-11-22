"""The from-scratch recipes in the West Bend L5951 manual, English section.

Every one is transcribed from the 2 lb column — the manual's base loaf —
and each line keeps the manual's own wording in its notes, because the
cups are the authority and the percentage is derived (see volumes.py).

Where the manual offers active dry *or* bread-machine yeast, the active
dry figure is the one converted and the alternative is in the note. Where
it gives a range ("1 - 1 1/2 tsp. Garlic Powder") the middle is used and
the range is in the note.

A straight machine loaf gets no stages: the program *is* the schedule, and
its segment times live on the equipment program rather than being copied
here to go stale. The two recipes that leave the machine part-way — pizza
dough and dinner rolls — carry the stages the manual spells out.
"""

from __future__ import annotations

from app.data.volumes import CUP, EGG_G, EGG_YOLK_G, TBSP, TSP, YEAST_PACKET_G, Item
from app.data.volumes import batch_flour_g, to_ingredients
from app.models.enums import IngredientRole as R

SOURCE = "West Bend L5951 manual"
UNTESTED = "reference v1 — untested."
BASE = "Transcribed from the 2 lb column; the manual also gives {other}."


def _recipe(
    name: str,
    *,
    page: int,
    category: str,
    program: str,
    items: list[Item],
    loaf_size: str = "2 lb",
    crust: str | None = None,
    stages: list[dict] | None = None,
    note: str = "",
) -> dict:
    return {
        "name": name,
        "category": category,
        "source": SOURCE,
        "source_ref": f"p. {page}",
        "notes": f"{UNTESTED} {note}".strip(),
        "ingredients": to_ingredients(items),
        # The manual's own batch, so the recipe reads in cups without being
        # asked to scale first.
        "flour_g": batch_flour_g(items),
        "stages": stages or [],
        "program": program,
        "loaf_size": loaf_size,
        "crust": crust,
    }


# Yeast, the way the manual keeps writing it.
def _adry(amount: float, original: str, instead: str) -> Item:
    return Item("Active Dry Yeast", R.OTHER, amount,
                original=f"{original} (or {instead} bread machine/fast rise)")


RECIPES: list[dict] = [
    # --- Setting 1, Basic ---------------------------------------------
    _recipe(
        "Old Fashioned White Bread", page=14, category="wheat", program="Basic",
        note=BASE.format(other="a 3 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1 + 1 / 3 * CUP + 1 * TBSP,
                 original="1 1/3 cups + 1 tbsp.", density_as="water"),
            Item("Butter or Margarine", R.FAT, 2 * TBSP + 2 * TSP,
                 original="2 tbsp. + 2 tsp.", density_as="butter"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Dry Milk", R.OTHER, 2 * TBSP + 2 * TSP,
                 original="2 tbsp. + 2 tsp.", density_as="dry milk"),
            Item("Sugar", R.SWEETENER, 2 * TSP, original="2 tsp."),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Bread Machine/Fast Rise Yeast", R.OTHER, 1.5 * TSP,
                 original="1 1/2 tsp.", density_as="yeast"),
        ],
    ),
    _recipe(
        "Garlic Bread", page=14, category="wheat", program="Basic",
        note=BASE.format(other="a 2.5 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1.5 * CUP, original="1 1/2 cups",
                 density_as="water"),
            Item("Butter or Margarine", R.FAT, 2 * TBSP, original="2 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Dried Parsley Flakes", R.OTHER, 1.5 * TBSP,
                 original="1 1/2 tbsp.", density_as="dried parsley"),
            Item("Sugar", R.SWEETENER, 1.5 * TBSP, original="1 1/2 tbsp."),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Garlic Powder", R.OTHER, 1.25 * TSP,
                 original="1 - 1 1/2 tsp. (the middle of the range)",
                 density_as="garlic powder"),
            _adry(2.25 * TSP, "2 1/4 tsp.", "2 tsp."),
        ],
    ),
    _recipe(
        "Walnut Bread", page=15, category="wheat", program="Basic",
        note=BASE.format(other="a 2.5 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP + 1.25 * TBSP,
                 original="1 cup + 1 1/4 tbsp.", density_as="water"),
            Item("Egg", R.OTHER, grams=EGG_G, original="1 egg"),
            Item("Butter or Margarine", R.FAT, 4 * TBSP, original="4 tbsp.",
                 density_as="butter"),
            Item("Dry Milk", R.OTHER, 0.25 * CUP, original="1/4 cup",
                 density_as="dry milk"),
            Item("Honey", R.SWEETENER, 2 * TBSP, original="2 tbsp."),
            Item("Walnut", R.OTHER, 1 / 3 * CUP, original="1/3 cup",
                 density_as="walnuts"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Sugar", R.SWEETENER, 0.25 * CUP, original="1/4 cup"),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Active Dry Yeast", R.OTHER, 2 * TSP, original="2 tsp.",
                 density_as="yeast"),
        ],
    ),
    _recipe(
        "Classic Rye Bread", page=15, category="rye", program="Basic",
        note=BASE.format(other="a 2.5 lb loaf")
        + " The manual's own rye — a light one: rye is under a third of the flour.",
        items=[
            Item("Water, 80°F", R.WATER, 1.5 * CUP, original="1 1/2 cups",
                 density_as="water"),
            Item("Butter or Margarine", R.FAT, 1 * TBSP, original="1 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 3 * CUP, original="3 cups"),
            Item("Medium Rye Flour", R.FLOUR, 1.25 * CUP, original="1 1/4 cups"),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Sugar", R.SWEETENER, 1.5 * TBSP, original="1 1/2 tbsp."),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Caraway Seed", R.OTHER, 2 * TSP, original="2 tsp., optional",
                 density_as="caraway"),
            _adry(2.25 * TSP, "2 1/4 tsp.", "2 tsp."),
        ],
    ),
    _recipe(
        "Sesame Bread", page=15, category="wheat", program="Basic",
        note=BASE.format(other="a 2.5 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1.25 * CUP + 3 * TBSP,
                 original="1 1/4 cups + 3 tbsp.", density_as="water"),
            Item("Butter or Margarine", R.FAT, 4 * TBSP, original="4 tbsp.",
                 density_as="butter"),
            Item("Dry Milk", R.OTHER, 0.25 * CUP, original="1/4 cup",
                 density_as="dry milk"),
            Item("Sesame Seeds", R.OTHER, 0.25 * CUP, original="1/4 cup"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Sugar", R.SWEETENER, 0.25 * CUP, original="1/4 cup"),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Active Dry Yeast", R.OTHER, 2 * TSP, original="2 tsp.",
                 density_as="yeast"),
        ],
    ),
    # --- Setting 2, French --------------------------------------------
    _recipe(
        "French Bread", page=16, category="wheat", program="French",
        note=BASE.format(other="a 2.5 lb loaf")
        + " No milk and almost no fat, which is what the French program expects.",
        items=[
            Item("Water, 80°F", R.WATER, 1.25 * CUP + 3 * TBSP,
                 original="1 1/4 cups + 3 tbsp.", density_as="water"),
            Item("Butter or Margarine", R.FAT, 2 * TBSP, original="2 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Sugar", R.SWEETENER, 2 * TBSP, original="2 tbsp."),
            Item("Salt", R.SALT, 2 * TSP, original="2 tsp."),
            Item("Active Dry Yeast", R.OTHER, 2 * TSP, original="2 tsp.",
                 density_as="yeast"),
        ],
    ),
    # --- Setting 3, Whole Wheat ---------------------------------------
    _recipe(
        "100% Whole Wheat Bread", page=16, category="wheat",
        program="Whole Wheat",
        note=BASE.format(other="a 2.5 lb loaf")
        + " If it collapses while baking, add 1 to 1 1/2 tbsp. vital wheat gluten.",
        items=[
            Item("Water, 80°F", R.WATER, 1.25 * CUP + 3 * TBSP,
                 original="1 1/4 cups + 3 tbsp.", density_as="water"),
            Item("Egg, Large", R.OTHER, grams=EGG_G, original="1 large egg"),
            Item("Molasses", R.SWEETENER, 1.5 * TBSP, original="1 1/2 tbsp."),
            Item("Honey", R.SWEETENER, 1.5 * TBSP, original="1 1/2 tbsp."),
            Item("Butter or Margarine", R.FAT, 2 * TBSP, original="2 tbsp.",
                 density_as="butter"),
            Item("Whole wheat Flour", R.FLOUR, 4.25 * CUP, original="4 1/4 cups"),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            _adry(2.25 * TSP, "2 1/4 tsp.", "2 tsp."),
        ],
    ),
    _recipe(
        "Wheat 'N Yogurt Bread", page=16, category="wheat",
        program="Whole Wheat",
        note=BASE.format(other="a 2.5 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP + 2 * TBSP,
                 original="1 cup + 2 tbsp.", density_as="water"),
            Item("Plain Nonfat Yogurt", R.WATER, 2 / 3 * CUP, original="2/3 cup",
                 density_as="yogurt"),
            Item("Butter or Margarine", R.FAT, 2 * TBSP, original="2 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 1.5 * CUP, original="1 1/2 cups"),
            Item("Whole wheat Flour", R.FLOUR, 2.75 * CUP, original="2 3/4 cups"),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Brown Sugar, Packed", R.SWEETENER, 2 * TBSP, original="2 tbsp.",
                 density_as="brown sugar"),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            _adry(2.25 * TSP, "2 1/4 tsp.", "2 tsp."),
        ],
    ),
    # --- Setting 4, Sweet ---------------------------------------------
    _recipe(
        "Oatmeal Maple Pecan Bread", page=17, category="enriched", program="Sweet",
        note=BASE.format(other="a 2.5 lb loaf")
        + " Nuts can go in at the alert or at the start with everything else.",
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP + 2.5 * TBSP,
                 original="1 cup + 2 1/2 tbsp.", density_as="water"),
            Item("Maple Syrup", R.SWEETENER, 0.5 * CUP, original="1/2 cup"),
            Item("Butter or Margarine", R.FAT, 3 * TBSP, original="3 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 1 / 3 * CUP + 3 * CUP,
                 original="3 1/3 cups"),
            Item("Oats, quick or old-fashioned", R.OTHER, 1 * CUP, original="1 cup",
                 density_as="oats"),
            Item("Dry Milk", R.OTHER, 2.5 * TBSP, original="2 1/2 tbsp.",
                 density_as="dry milk"),
            Item("Salt", R.SALT, 2 * TSP, original="2 tsp."),
            _adry(2.5 * TSP, "2 1/2 tsp.", "2 tsp."),
            Item("Chopped Pecans", R.OTHER, 2 / 3 * CUP, original="2/3 cup",
                 density_as="pecans"),
        ],
    ),
    _recipe(
        "Raisin Bread", page=17, category="enriched", program="Sweet",
        note=BASE.format(other="a 2.5 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1.5 * CUP + 2 * TBSP,
                 original="1 1/2 cups + 2 tbsp.", density_as="water"),
            Item("Butter or Margarine", R.FAT, 2 * TBSP, original="2 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Sugar", R.SWEETENER, 2.5 * TBSP, original="2 1/2 tbsp."),
            Item("Salt", R.SALT, 1.75 * TSP, original="1 3/4 tsp."),
            Item("Ground Cinnamon", R.OTHER, 1.25 * TSP, original="1 1/4 tsp.",
                 density_as="cinnamon"),
            _adry(2.25 * TSP, "2 1/4 tsp.", "2 tsp."),
            Item("Raisins", R.OTHER, 1 * CUP, original="1 cup"),
            Item("Chopped Nuts", R.OTHER, 1 / 3 * CUP, original="1/3 cup"),
        ],
    ),
    # --- Setting 5, Super Rapid ---------------------------------------
    _recipe(
        "Basic Super Rapid Bread", page=18, category="wheat",
        program="Super Rapid",
        note=BASE.format(other="a 2.5 lb loaf")
        + " Super Rapid wants an extra teaspoon of yeast over the same recipe"
          " on another setting, and no quick-bread recipes at all.",
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP + 2 * TBSP,
                 original="1 cup + 2 tbsp.", density_as="water"),
            Item("Egg", R.OTHER, grams=EGG_G, original="1 egg"),
            Item("Butter or Margarine", R.FAT, 2 * TBSP, original="2 tbsp.",
                 density_as="butter"),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Bread Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Sugar", R.SWEETENER, 0.25 * CUP, original="1/4 cup"),
            Item("Salt", R.SALT, 2 * TSP, original="2 tsp."),
            Item("Active Dry Yeast", R.OTHER, 1 * TBSP + 1 * TSP,
                 original="1 tbsp. + 1 tsp.", density_as="yeast"),
        ],
    ),
    # --- Setting 6, Sandwich ------------------------------------------
    _recipe(
        "Sandwich White Bread", page=18, category="wheat", program="Sandwich",
        note=BASE.format(other="a 2.5 lb loaf"),
        items=[
            Item("Water, 80°F", R.WATER, 1 + 1 / 3 * CUP, original="1 1/3 cups",
                 density_as="water"),
            Item("Butter or Margarine", R.FAT, 2.5 * TBSP, original="2 1/2 tbsp.",
                 density_as="butter"),
            Item("Dry Milk", R.OTHER, 2.5 * TBSP, original="2 1/2 tbsp.",
                 density_as="dry milk"),
            Item("Bread Flour", R.FLOUR, 3.75 * CUP, original="3 3/4 cups"),
            Item("Sugar", R.SWEETENER, 3 * TBSP, original="3 tbsp."),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            _adry(1.25 * TSP, "1 1/4 tsp.", "1 tsp."),
        ],
    ),
    # --- Setting 7, Gluten Free ---------------------------------------
    _recipe(
        "Gluten free Bread", page=19, category="other", program="Gluten Free",
        note="reference v1 — untested. The manual gives only a 2 lb loaf."
             " Whisk the liquids together separately first; break the eggs into"
             " a 2-cup measure and top up with water to 1 3/4 cup. Add the yeast"
             " and dry ingredients first, then half the wet, then start the"
             " cycle and add the rest as it mixes. Done at 205-210°F inside.",
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP + 2 * TBSP,
                 original="1 cup + 2 tbsp. (eggs in the cup, topped to 1 3/4 cup)",
                 density_as="water"),
            Item("Eggs", R.OTHER, grams=3 * EGG_G, original="3 eggs"),
            Item("Melted Butter or Canola Oil", R.FAT, 0.25 * CUP,
                 original="1/4 cup", density_as="melted butter"),
            Item("Cider Vinegar", R.OTHER, 1 * TSP, original="1 tsp."),
            Item("White Rice Flour", R.FLOUR, 2 * CUP, original="2 cups"),
            Item("Potato Starch Flour", R.FLOUR, 0.75 * CUP, original="3/4 cup",
                 density_as="potato starch"),
            Item("Tapioca Flour", R.FLOUR, 0.25 * CUP, original="1/4 cup"),
            Item("Non-fat Dry Milk", R.OTHER, 2 / 3 * CUP, original="2/3 cup",
                 density_as="dry milk"),
            Item("Sugar", R.SWEETENER, 3 * TBSP, original="3 tbsp."),
            Item("Xanthan Gum", R.OTHER, 1 * TBSP, original="1 tbsp."),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Active Dry Yeast", R.OTHER, 1 * TBSP, original="1 tbsp.",
                 density_as="yeast"),
        ],
    ),
    _recipe(
        "Lemon Poppyseed Gluten free Bread", page=19, category="other",
        program="Gluten Free",
        note="reference v1 — untested. The manual gives only a 2 lb loaf."
             " Same method as the plain gluten free loaf on the same page.",
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP + 2 * TBSP,
                 original="1 cup + 2 tbsp. (eggs in the cup, topped to 1 3/4 cup)",
                 density_as="water"),
            Item("Eggs", R.OTHER, grams=3 * EGG_G, original="3 eggs"),
            Item("Melted Butter or Canola Oil", R.FAT, 0.25 * CUP,
                 original="1/4 cup", density_as="melted butter"),
            Item("Lemon Extract", R.OTHER, 2 * TSP,
                 original="2 tsp., gluten free"),
            Item("White Rice Flour", R.FLOUR, 2 * CUP, original="2 cups"),
            Item("Potato Starch Flour", R.FLOUR, 0.75 * CUP, original="3/4 cups",
                 density_as="potato starch"),
            Item("Tapioca Flour", R.FLOUR, 0.25 * CUP, original="1/4 cup"),
            Item("Non-fat Dry Milk", R.OTHER, 2 / 3 * CUP, original="2/3 cup",
                 density_as="dry milk"),
            Item("Sugar", R.SWEETENER, 3 * TBSP, original="3 tbsp."),
            Item("Xanthan Gum", R.OTHER, 1 * TBSP, original="1 tbsp."),
            Item("Salt", R.SALT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Poppy Seeds", R.OTHER, 1 * TBSP, original="1 tbsp."),
            Item("Active Dry Yeast", R.OTHER, 1 * TBSP, original="1 tbsp.",
                 density_as="yeast"),
        ],
    ),
    _recipe(
        "Whole Wheat & Seed Low Carb Bread", page=20, category="wheat",
        program="Gluten Free",
        note="reference v1 — untested. The manual gives only a 2 lb loaf."
             " Filed under its Low Carb & Gluten free heading and run on"
             " setting 7 or on Custom — but it is wheat and bran, so it is"
             " low carb, not gluten free.",
        items=[
            Item("Water, 80°F", R.WATER, 2.5 * CUP, original="2 1/2 cups",
                 density_as="water"),
            Item("Olive Oil", R.FAT, 0.25 * CUP, original="1/4 cup"),
            Item("Agave Syrup", R.SWEETENER, 1 * TSP, original="1 tsp."),
            Item("Salt", R.SALT, 1 * TSP, original="1 tsp."),
            Item("Unprocessed Wheat Bran", R.OTHER, 1 * CUP, original="1 cup",
                 density_as="wheat bran"),
            Item("Whole wheat Flour", R.FLOUR, 4 * CUP, original="4 cups"),
            Item("Bread Machine/Fast Rise Yeast", R.OTHER,
                 grams=2 * YEAST_PACKET_G, original="2 pkg."),
            Item("Flax Seeds, roughly ground", R.OTHER, 0.5 * CUP,
                 original="1/2 cup", density_as="flax seeds"),
            Item("Sunflower Seeds, Hulled", R.OTHER, 0.25 * CUP,
                 original="1/4 cup", density_as="sunflower seeds"),
            Item("Pumpkin Seeds, Roasted", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="pumpkin seeds"),
        ],
    ),
    # --- Setting 8, Mix -----------------------------------------------
    _recipe(
        "Basic Pasta Dough", page=20, category="other", program="Mix",
        loaf_size=None,
        note="reference v1 — untested. Not bread: the Mix setting kneads and"
             " stops. Rest the ball in a bag or under a damp towel for 30"
             " minutes, quarter it, then roll it thin.",
        stages=[
            {"name": "mix", "min": 15, "notes": "setting 8, Mix"},
            {"name": "rest", "min": 30,
             "notes": "in a plastic bag or under a damp towel"},
            {"name": "roll", "notes": "quarter, then roll thin"},
        ],
        items=[
            Item("All-purpose Flour", R.FLOUR, 2 / 3 * CUP + 1 * TBSP,
                 original="2/3 cup + 1 tbsp."),
            Item("Semolina Flour", R.FLOUR, 0.5 * CUP + 2 * TBSP,
                 original="1/2 cup + 2 tbsp.", density_as="semolina"),
            Item("Egg Yolks", R.OTHER, grams=6 * EGG_YOLK_G, original="6 egg yolks"),
            Item("Large Egg", R.OTHER, grams=EGG_G, original="1 large egg"),
            Item("Olive Oil", R.FAT, 1.5 * TSP, original="1 1/2 tsp."),
            Item("Milk", R.WATER, 2 * TBSP, original="2 tbsp."),
        ],
    ),
    # --- Setting 9, Dough ---------------------------------------------
    _recipe(
        "Pizza Dough", page=20, category="wheat", program="Dough",
        loaf_size=None,
        note="reference v1 — untested. The manual's double-crust quantity.",
        stages=[
            {"name": "machine dough cycle", "min": 110, "notes": "setting 9, Dough"},
            {"name": "knead and rest", "min": 15,
             "notes": "knead a minute on a floured surface, then rest"},
            {"name": "shape", "notes": "roll to fit 12- or 14-inch pans"},
            {"name": "rise", "min": 25,
             "notes": "20-25 min in a warm, draft-free place"},
            {"name": "bake", "min": 23, "temp_c": 218.3,
             "notes": "425°F for 20-25 min, until browned on top"},
            {"name": "rest", "min": 5, "notes": "before cutting"},
        ],
        items=[
            Item("Water, 80°F", R.WATER, 1 * CUP, original="1 cup",
                 density_as="water"),
            Item("All-Purpose Flour", R.FLOUR, 3.25 * CUP, original="3 1/4 cups"),
            Item("Sugar", R.SWEETENER, 1 * TSP, original="1 tsp."),
            Item("Salt", R.SALT, 1 * TSP, original="1 tsp."),
            Item("Vegetable Oil", R.FAT, 4 * TBSP, original="4 tbsp."),
            _adry(2.25 * TSP, "2 1/4 tsp.", "2 tsp."),
        ],
    ),
    _recipe(
        "Basic Dinner Rolls / Bread Sticks", page=21, category="enriched",
        program="Dough", loaf_size=None,
        note="reference v1 — untested. Brush the tops with softened butter or"
             " lightly beaten egg white before baking.",
        stages=[
            {"name": "machine dough cycle", "min": 110, "notes": "setting 9, Dough"},
            {"name": "rest", "min": 15, "notes": "on a lightly floured surface"},
            {"name": "shape", "notes": "rolls or sticks, on a greased sheet"},
            {"name": "rise", "min": 45,
             "notes": "warm, draft-free, until doubled"},
            {"name": "bake", "min": 18, "temp_c": 176.7,
             "notes": "350°F for 15-20 min, until golden"},
        ],
        items=[
            Item("Water, 80°F", R.WATER, 0.75 * CUP + 1 * TBSP,
                 original="3/4 cup + 1 tbsp.", density_as="water"),
            Item("Butter or Margarine", R.FAT, 3 * TBSP, original="3 tbsp.",
                 density_as="butter"),
            Item("Bread Flour", R.FLOUR, 3 * CUP, original="3 cups"),
            Item("Sugar", R.SWEETENER, 3.5 * TBSP, original="3 1/2 tbsp."),
            Item("Dry Milk", R.OTHER, 2 * TBSP, original="2 tbsp.",
                 density_as="dry milk"),
            Item("Salt", R.SALT, 1 * TSP, original="1 tsp."),
            _adry(2 * TSP, "2 tsp.", "1 1/2 tsp."),
        ],
    ),
]
