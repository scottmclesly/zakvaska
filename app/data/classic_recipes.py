"""Classic breads, each from a published formula with a real source.

Every percentage here is either quoted from the source's own baker's-
percentage table or worked out from the gram weights it gives. Nothing is
invented: where no published formula could be found, the bread is absent
rather than guessed at — see SKIPPED at the bottom of this file.

Two conventions, applied consistently:

* **Total flour** is the lines a baker would call flour, including rye
  meal and chops, and including the malted rye that the Borodinsky source
  itself counts in its flour total. Seeds, nuts and dry milk are carried
  as other ingredients.
* **Preferments** are listed as a single `levain` line at the percentage
  the source gives, rather than being broken back out into flour and
  water, because that is how each source states it.

Every recipe is marked "reference v1 — untested". None of these has been
baked in this kitchen yet.
"""

from __future__ import annotations

RYE_SOUR = "Needs the rye starter."
WHEAT_LEVAIN = "Needs a wheat levain (a stiff-ish 100% hydration starter)."
COMMERCIAL = "Commercial yeast, no starter."
BOTH = "Rye sour for flavour, a little commercial yeast for lift."

OVEN = "Oven."
DUTCH = "Cast-iron pot."
PULLMAN = "Oven, in a lidded Pullman or pain de mie pan."
NOT_MACHINE = "Too wet and too slow for the bread maker."

UNTESTED = "reference v1 — untested."


def _r(
    name: str,
    *,
    category: str,
    source: str,
    source_ref: str,
    equipment: str,
    leaven: str,
    note: str,
    ingredients: list[tuple],
    stages: list[dict] | None = None,
    program: str | None = None,
    loaf_size: str | None = None,
    crust: str | None = None,
) -> dict:
    return {
        "name": name,
        "category": category,
        "source": source,
        "source_ref": source_ref,
        "notes": f"{UNTESTED} {equipment} {leaven} {note}".strip(),
        "ingredients": [
            {"name": n, "role": role, "pct": pct,
             "notes": note_ or None}
            for n, role, pct, note_ in ingredients
        ],
        "stages": stages or [],
        "program": program,
        "loaf_size": loaf_size,
        "crust": crust,
    }


RYE_BAKER = "Stanley Ginsberg, The Rye Baker"
KING_ARTHUR = "King Arthur Baking"
PERFECT_LOAF = "Maurizio Leo, The Perfect Loaf"


RECIPES: list[dict] = [
    # --- Russian and Baltic ------------------------------------------
    _r(
        "Borodinsky (traditional scald)",
        category="rye",
        source=RYE_BAKER,
        source_ref="theryebaker.com — Auerman Borodinsky (Revised), 100% rye",
        equipment=PULLMAN,
        leaven=RYE_SOUR,
        note="Ginsberg's revision of Auerman's 1935 formula: 100% rye, a"
             " scald of medium rye and toasted red rye malt, a rye sponge,"
             " then the two combined before the final dough. The scald is"
             " what makes it Borodinsky. This one seasons the scald with"
             " caraway or anise; the coriander most people expect is what"
             " the demo Borodinsky in this notebook uses. " + NOT_MACHINE,
        ingredients=[
            ("Whole rye flour", "flour", 63.6, "final dough"),
            ("Medium rye flour", "flour", 31.3, "60 g in the sponge, 255 g in the scald"),
            ("Red rye malt", "flour", 5.1, "toasted 4-5 min until deep rose, then ground"),
            ("Water", "water", 79.5, "60 g warm in the sponge, 740 g boiling in the scald"),
            ("Rye sour culture", "levain", 0.9, ""),
            ("Sugar", "sweetener", 4.3, ""),
            ("Salt", "salt", 1.0, ""),
            ("Caraway or anise seed", "other", 0.4, "toasted and ground, into the scald"),
        ],
        stages=[
            {"name": "sponge", "min": 840, "temp_c": 21.0,
             "notes": "12-16 h, until bubbly and falling back"},
            {"name": "scald (zavarka)", "min": 840, "temp_c": 21.0,
             "notes": "12-16 h; mix the ground malt with boiling water to a thick porridge"},
            {"name": "scald-sponge", "min": 300, "temp_c": 21.0,
             "notes": "4-6 h, until half again its volume and bubbling"},
            {"name": "final dough", "min": 10,
             "notes": "low speed 8-10 min to a firm, slightly sticky mass"},
            {"name": "bulk ferment", "min": 35, "notes": "30-40 min, visibly expanded"},
            {"name": "proof", "min": 55,
             "notes": "50-60 min, above the pan rim, surface like pinpricks"},
            {"name": "bake", "min": 10, "temp_c": 230.0, "notes": "brush with water first"},
            {"name": "bake (lower)", "min": 58, "temp_c": 190.0,
             "notes": "55-60 min more, to at least 92°C inside"},
        ],
    ),
    _r(
        "Latvian rupjmaize (coarse rye)",
        category="rye",
        source=RYE_BAKER,
        source_ref="theryebaker.com — Latvian Coarse Rye / Rudzu Rupjā Maize",
        equipment="Oven, free-form on a sheet.",
        leaven=RYE_SOUR,
        note="100% rye at 100% hydration — a batter rather than a dough,"
             " shaped wet and baked without a final proof. Sweetened with"
             " dark brown sugar and seasoned with caraway. Stand it 24-48 h"
             " before slicing; it is not ready the day it is baked. " + NOT_MACHINE,
        ingredients=[
            ("Coarse rye meal", "flour", 63.9, ""),
            ("Medium rye meal", "flour", 27.4, ""),
            ("Whole rye flour", "flour", 8.7, "in the sponge"),
            ("Water", "water", 100.0, "warm, 41°C"),
            ("Dark brown sugar", "sweetener", 4.6, ""),
            ("Salt", "salt", 1.1, ""),
            ("Rye sour culture", "levain", 0.9, ""),
            ("Caraway seed", "other", 0.9, ""),
        ],
        stages=[
            {"name": "sponge", "min": 660, "temp_c": 21.0,
             "notes": "10-12 h, until doubled with broken bubbles"},
            {"name": "final dough", "min": 8,
             "notes": "paddle on the lowest speed 7-8 min; it stays batter-loose"},
            {"name": "bulk ferment", "min": 180,
             "notes": "until visibly expanded and bubbling"},
            {"name": "shape", "min": 10,
             "notes": "wet hands, an oblong about 15 cm x 35-40 cm; no final proof"},
            {"name": "bake", "min": 45, "temp_c": 220.0, "notes": ""},
            {"name": "bake (lower)", "min": 43, "temp_c": 180.0,
             "notes": "40-45 min more, to at least 92°C inside"},
            {"name": "rest", "min": 2160, "notes": "24-48 h before slicing"},
        ],
    ),
    # --- Nordic -------------------------------------------------------
    _r(
        "Danish rugbrød",
        category="rye",
        source=RYE_BAKER,
        source_ref="theryebaker.com — Sourdough Danish Rye / Rugbrød på surdej",
        equipment=PULLMAN,
        leaven=RYE_SOUR,
        note="84% rye in two sponge stages, with coarse rye meal, four kinds"
             " of seed and beer in the final dough. Half the flour is"
             " prefermented. " + NOT_MACHINE,
        ingredients=[
            ("Whole rye flour", "flour", 51.2, "all of it prefermented"),
            ("Coarse rye meal", "flour", 33.2, "final dough"),
            ("Whole wheat flour", "flour", 15.6, "final dough"),
            ("Water", "water", 51.2, "warm, 41°C"),
            ("Beer", "water", 21.3, "final dough"),
            ("Pumpkin seeds", "other", 6.6, "raw"),
            ("Sunflower seeds", "other", 6.6, "raw"),
            ("Flaxseed", "other", 4.7, "brown"),
            ("Dark corn syrup or light molasses", "sweetener", 3.3, ""),
            ("Sesame seed", "other", 2.3, ""),
            ("Salt", "salt", 2.7, ""),
            ("Rye sour culture", "levain", 0.7, ""),
        ],
        stages=[
            {"name": "stage 1 sponge", "min": 660, "temp_c": 21.0,
             "notes": "10-12 h, doubled and sharply sour"},
            {"name": "stage 2 sponge", "min": 660, "temp_c": 21.0,
             "notes": "10-12 h; a stiff dough with the salt, syrup and seeds in it"},
            {"name": "final dough", "min": 5,
             "notes": "low speed 4-5 min to a soft, sticky dough"},
            {"name": "proof", "min": 240,
             "notes": "3-5 h in the pans, two-thirds full, to the rim"},
            {"name": "bake", "min": 82, "temp_c": 225.0,
             "notes": "75-90 min, no steam, to at least 92°C inside"},
        ],
    ),
    _r(
        "Finnish ruisleipä (ring rye)",
        category="rye",
        source=RYE_BAKER,
        source_ref="theryebaker.com — Halme Bakery's Ring Rye / Ruisreikäleipä",
        equipment="Oven with steam, flat rings on a stone or sheet.",
        leaven=BOTH,
        note="91% rye at 97% hydration, from a very loose overnight sponge."
             " Rolled flat, a hole cut in the middle and docked all over —"
             " the shape is the point, and it is what keeps it thin enough"
             " to bake through. " + NOT_MACHINE,
        ingredients=[
            ("Whole rye flour", "flour", 90.9, "275 g of it in the sponge"),
            ("Bread flour", "flour", 9.1, "final dough"),
            ("Water", "water", 97.1, ""),
            ("Salt", "salt", 1.9, ""),
            ("Rye starter culture", "levain", 1.4, ""),
            ("Instant yeast", "other", 0.1, ""),
        ],
        stages=[
            {"name": "sponge", "min": 960, "temp_c": 21.0,
             "notes": "14-18 h, very loose, more than doubled"},
            {"name": "final dough", "min": 8, "notes": "low speed 7-8 min"},
            {"name": "bulk ferment", "min": 75, "temp_c": 30.0,
             "notes": "1-1.5 h, until doubled"},
            {"name": "shape", "min": 10,
             "notes": "two rounds, flattened to about 36 cm across and 2 cm thick"},
            {"name": "proof", "min": 52, "temp_c": 30.0,
             "notes": "45-60 min, until the surface cracks"},
            {"name": "bake", "min": 10, "temp_c": 225.0,
             "notes": "with steam; cut an 8 cm hole and dock deeply first"},
            {"name": "bake (dry)", "min": 32, "temp_c": 225.0,
             "notes": "30-35 min more, to at least 95°C inside"},
        ],
    ),
    # --- Rye deli -----------------------------------------------------
    _r(
        "Jewish rye with caraway",
        category="rye",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/pro/formulas/deli-rye",
        equipment="Oven with steam.",
        leaven=BOTH,
        note="A deli rye: 20% rye, all of it prefermented as a rye sour"
             " built 16 hours ahead, with commercial yeast in the final"
             " dough for lift. Caraway at 1.25% is what makes it taste"
             " like a deli counter.",
        ingredients=[
            ("Bread flour", "flour", 80.0, ""),
            ("Whole rye flour", "flour", 20.0, "all of it in the sour"),
            ("Water", "water", 70.0, ""),
            ("Salt", "salt", 2.0, ""),
            ("Yeast", "other", 1.25, ""),
            ("Caraway", "other", 1.25, ""),
            ("Rye sour culture", "levain", 2.0, "10% of the sour's rye flour"),
        ],
        stages=[
            {"name": "rye sour", "min": 960, "temp_c": 21.0,
             "notes": "about 16 h; rye at 83% hydration with 10% culture"},
            {"name": "final dough", "min": 6,
             "notes": "3 min first speed, 3 min second; moderate gluten"},
            {"name": "bulk ferment", "min": 60, "temp_c": 25.0,
             "notes": "dough temperature 24-26°C"},
            {"name": "proof", "min": 55, "notes": "50-60 min"},
            {"name": "bake", "min": 38, "temp_c": 232.0,
             "notes": "36-40 min for a 750 g loaf, steamed oven"},
        ],
    ),
    _r(
        "Vollkornbrot",
        category="rye",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/recipes/vollkornbrot-recipe",
        equipment=PULLMAN,
        leaven=RYE_SOUR,
        note="Wholegrain rye: a pumpernickel-flour starter and an overnight"
             " soaker of rye chops, which are about a third of the grain."
             " The 2 tsp of instant yeast is converted here at about 3 g a"
             " teaspoon — the recipe gives no weight for it. Rest it a day"
             " or two before slicing. " + NOT_MACHINE,
        ingredients=[
            ("Pumpernickel flour", "flour", 68.3, "397 g in the starter, 213 g in the dough"),
            ("Rye chops", "flour", 31.7, "soaked overnight; cracked wheat or steel-cut oats also work"),
            ("Water", "water", 82.5, "397 g starter, 283 g soaker, 57 g final"),
            ("Sunflower seeds", "other", 8.0, ""),
            ("Ripe sourdough starter", "levain", 2.4, ""),
            ("Salt", "salt", 2.0, ""),
            ("Instant yeast", "other", 0.7, "2 tsp"),
        ],
        stages=[
            {"name": "starter", "min": 720, "temp_c": 21.0, "notes": "overnight"},
            {"name": "soaker", "min": 720, "temp_c": 21.0,
             "notes": "rye chops and water, overnight"},
            {"name": "final dough", "min": 10,
             "notes": "dense and sticky but still loose"},
            {"name": "proof", "min": 60,
             "notes": "in a 33 cm pain de mie pan, floured on top, until it cracks"},
            {"name": "bake", "min": 15, "temp_c": 232.0, "notes": "uncovered"},
            {"name": "bake (lower)", "min": 55, "temp_c": 218.0,
             "notes": "50-60 min more, then 5-10 min out of the pan, to at least 96°C"},
            {"name": "rest", "min": 2160,
             "notes": "24-48 h wrapped in a towel or paper bag"},
        ],
    ),
    # --- Wheat sourdough ----------------------------------------------
    _r(
        "Country loaf (Tartine-style)",
        category="wheat",
        source=PERFECT_LOAF,
        source_ref="theperfectloaf.com/tartine-sourdough-country-loaf-bread-recipe",
        equipment=DUTCH,
        leaven=WHEAT_LEVAIN,
        note="Maurizio Leo's working of the Tartine country loaf. The"
             " percentages are against the 1,000 g of flour in the main"
             " mix, which is how the source states them; counting the"
             " levain's own flour in puts the real hydration a little"
             " higher. An overnight retard in the fridge does most of the"
             " flavour. " + NOT_MACHINE,
        ingredients=[
            ("Unbleached all-purpose flour", "flour", 70.0, ""),
            ("Whole wheat flour", "flour", 30.0, ""),
            ("Water", "water", 79.0, "740 g in the mix, 50 g with the salt"),
            ("Levain", "levain", 25.0, "built overnight: 110 g whole wheat, 116 g water, 31 g starter"),
            ("Salt", "salt", 2.0, ""),
        ],
        stages=[
            {"name": "levain build", "min": 540, "temp_c": 21.0, "notes": "overnight"},
            {"name": "autolyse", "min": 30, "notes": "levain, water and flour; no salt yet"},
            {"name": "bulk ferment", "min": 270, "temp_c": 24.0,
             "notes": "4 sets of folds 30 min apart, then rest until risen 20-30%"},
            {"name": "pre-shape", "min": 30, "notes": "loose boules, bench rest"},
            {"name": "shape", "min": 10, "notes": "tight boules, seam up in baskets"},
            {"name": "retard", "min": 1140, "temp_c": 4.0, "notes": "18-20 h in the fridge"},
            {"name": "bake (covered)", "min": 20, "temp_c": 230.0, "notes": "straight from the fridge"},
            {"name": "bake (uncovered)", "min": 35, "temp_c": 230.0, "notes": "until the crust is dark"},
        ],
    ),
    _r(
        "Pain de campagne",
        category="wheat",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/recipes/pain-de-campagne-country-bread-recipe",
        equipment=DUTCH,
        leaven=WHEAT_LEVAIN,
        note="A plain country loaf: 10% whole wheat, 80% hydration, and"
             " only 4% unfed starter, so the ferment is long and slow."
             " " + NOT_MACHINE,
        ingredients=[
            ("Bread flour", "flour", 90.0, ""),
            ("Whole wheat flour", "flour", 10.0, "golden wheat flour also works"),
            ("Water", "water", 80.0, "tepid"),
            ("Unfed sourdough starter", "levain", 4.0, ""),
            ("Salt", "salt", 2.0, ""),
        ],
        stages=[
            {"name": "bulk ferment", "min": 720, "temp_c": 21.0, "notes": "with folds"},
            {"name": "shape", "min": 10, "notes": ""},
            {"name": "proof", "min": 150, "notes": "until puffy"},
            {"name": "bake (covered)", "min": 20, "temp_c": 232.0, "notes": ""},
            {"name": "bake (uncovered)", "min": 23, "temp_c": 232.0, "notes": "20-25 min more"},
        ],
    ),
    # --- Classics -----------------------------------------------------
    _r(
        "Baguette with poolish",
        category="wheat",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/pro/formulas/french-bread-with-poolish",
        equipment="Oven with steam.",
        leaven=COMMERCIAL,
        note="A third of the flour goes into a poolish at 100% hydration"
             " and ripens before the mix — all the flavour of a long"
             " ferment, on commercial yeast. " + NOT_MACHINE,
        ingredients=[
            ("Bread flour", "flour", 100.0, "a third of it in the poolish"),
            ("Water", "water", 67.0, "3.3 of the 6.7 parts in the poolish"),
            ("Salt", "salt", 2.0, ""),
            ("Yeast", "other", 1.1, "0.2% of the poolish flour, the rest in the dough"),
        ],
        stages=[
            {"name": "poolish", "min": 720, "temp_c": 21.0, "notes": "until ripe"},
            {"name": "final dough", "min": 6,
             "notes": "3 min first speed, 3 min second; dough temperature 24°C"},
            {"name": "bulk ferment", "min": 120, "notes": "fold after 1 h"},
            {"name": "pre-shape", "min": 20, "notes": "divide, pre-shape, relax"},
            {"name": "shape", "min": 10, "notes": ""},
            {"name": "proof", "min": 60, "notes": ""},
            {"name": "bake", "min": 25, "temp_c": 238.0,
             "notes": "steam, load, steam again; time depends on the shape"},
        ],
    ),
    _r(
        "Ciabatta",
        category="wheat",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/pro/formulas/ciabatta",
        equipment="Oven with steam.",
        leaven=COMMERCIAL,
        note="76% hydration off a 16-hour biga at 60%. Handled wet and"
             " barely shaped — divided into rectangles and left good side"
             " down on a floured board. " + NOT_MACHINE,
        ingredients=[
            ("Bread flour", "flour", 100.0, "30% of it prefermented in the biga"),
            ("Water", "water", 76.0, "the biga is at 60% hydration"),
            ("Salt", "salt", 2.0, ""),
            ("Yeast", "other", 1.2, "0.1% of the biga flour, the rest in the dough"),
        ],
        stages=[
            {"name": "biga", "min": 960, "temp_c": 21.0, "notes": "about 16 h, until ripe"},
            {"name": "final dough", "min": 8,
             "notes": "3 min first speed, 4-5 min second; dough temperature 24°C"},
            {"name": "bulk ferment", "min": 120, "notes": "fold after 1 h"},
            {"name": "shape", "min": 10, "notes": "divide into 570 g rectangles"},
            {"name": "proof", "min": 60, "notes": ""},
            {"name": "bake", "min": 36, "temp_c": 238.0,
             "notes": "steam, load, steam again"},
        ],
    ),
    _r(
        "Focaccia",
        category="wheat",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/recipes/focaccia-recipe",
        equipment="Oven, a 35 cm round on a greased sheet.",
        leaven=COMMERCIAL,
        note="The 14-inch round. Note the salt: half a teaspoon to 357 g of"
             " flour is under 1%, which is low for bread and is what the"
             " recipe says — the oil and herbs go on after baking, not in"
             " the dough. Teaspoon measures are converted at about 3 g for"
             " instant yeast, 6 g for salt and 4 g for sugar.",
        ingredients=[
            ("All-purpose flour", "flour", 84.0, "2 1/2 cups"),
            ("Whole wheat flour", "flour", 16.0, "1/2 cup"),
            ("Water", "water", 63.6, "1 cup, warm"),
            ("Extra-virgin olive oil", "fat", 7.0, "2 tbsp., drizzled on after baking"),
            ("Yeast", "other", 1.3, "1 1/2 tsp. active dry or instant"),
            ("Salt", "salt", 0.8, "1/2 tsp."),
            ("Sugar", "sweetener", 0.6, "1/2 tsp., to start the yeast"),
        ],
        stages=[
            {"name": "sponge", "min": 10,
             "notes": "yeast, sugar, water and 1/4 cup of the flour"},
            {"name": "bulk ferment", "min": 105, "notes": "1.5-2 h, until doubled"},
            {"name": "shape", "min": 5, "notes": "stretch to a 35 cm circle"},
            {"name": "proof", "min": 30, "notes": "then dimple all over"},
            {"name": "bake", "min": 25, "temp_c": 218.0, "notes": "until lightly browned"},
        ],
    ),
    _r(
        "Challah",
        category="enriched",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/recipes/classic-challah-recipe",
        equipment="Oven, braided on a sheet.",
        leaven=COMMERCIAL,
        note="Enriched with oil rather than butter, and sweetened with"
             " honey. Eggs are counted at 50 g each and the yolk at 18 g."
             " The bread maker's Dough program can do the mixing; the"
             " braid and the bake are yours.",
        program="Dough",
        ingredients=[
            ("All-purpose flour", "flour", 100.0, "4 cups, 480 g"),
            ("Water", "water", 35.4, "3/4 cup, lukewarm"),
            ("Eggs", "other", 20.8, "2 large"),
            ("Vegetable oil", "fat", 15.4, "6 tbsp."),
            ("Honey", "sweetener", 13.1, "3 tbsp."),
            ("Egg yolk", "other", 3.8, "1 large; keep the white for the wash"),
            ("Instant yeast", "other", 2.5, "4 tsp."),
            ("Salt", "salt", 1.9, "1 1/2 tsp."),
        ],
        stages=[
            {"name": "bulk ferment", "min": 120, "notes": "until puffy"},
            {"name": "shape", "min": 20,
             "notes": "divide, roll 50 cm ropes, braid in three, four or six"},
            {"name": "proof", "min": 75, "notes": "60-90 min, very puffy"},
            {"name": "bake", "min": 28, "temp_c": 190.0,
             "notes": "25-30 min, egg-white wash first, to 88°C inside"},
        ],
    ),
    _r(
        "Brioche",
        category="enriched",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/pro/formulas/brioche",
        equipment="Oven, in a tin.",
        leaven=COMMERCIAL,
        note="50% butter and 50% egg — a dough that is half enrichment."
             " Butter goes in last, pliable, once the gluten is fully"
             " developed. The 7% yeast reads as fresh yeast rather than"
             " instant; scale it down if yours is instant. Retard it"
             " overnight and de-gas until it is properly cold. " + NOT_MACHINE,
        ingredients=[
            ("Bread flour", "flour", 100.0, ""),
            ("Butter, pliable", "fat", 50.0, "added last, in chunks"),
            ("Eggs", "other", 50.0, ""),
            ("Sugar", "sweetener", 12.0, ""),
            ("Yeast", "other", 7.0, "reads as fresh yeast"),
            ("Water, cold", "water", 9.0, ""),
            ("Salt", "salt", 2.5, ""),
        ],
        stages=[
            {"name": "mix", "min": 20,
             "notes": "everything but the butter, to full gluten development"},
            {"name": "butter", "min": 10, "notes": "in chunks, until the dough sheets"},
            {"name": "bench rest", "min": 60, "notes": "then fold"},
            {"name": "retard", "min": 720, "temp_c": 4.0,
             "notes": "overnight; de-gas two or three times until cold through"},
            {"name": "shape", "min": 15, "notes": ""},
            {"name": "proof", "min": 120, "notes": "until full"},
            {"name": "bake", "min": 30, "temp_c": 190.0, "notes": ""},
        ],
    ),
    _r(
        "Japanese milk bread (tangzhong)",
        category="enriched",
        source=KING_ARTHUR,
        source_ref="kingarthurbaking.com/recipes/japanese-milk-bread-recipe",
        equipment="Oven, four logs in a 23 x 13 cm tin.",
        leaven=COMMERCIAL,
        note="Tangzhong: 14 g of the flour is cooked with the water and"
             " milk to a paste first, which gelatinises the starch and lets"
             " the dough carry more liquid and stay soft for days. The same"
             " trick is worth trying on a Russian baton. The bread maker's"
             " Dough program can knead it — it wants nearly 15 minutes.",
        program="Dough",
        ingredients=[
            ("Bread flour", "flour", 100.0, "300 g in the dough, 14 g in the tangzhong"),
            ("Milk", "water", 49.7, "43 g in the tangzhong, 113 g in the dough"),
            ("Butter, melted", "fat", 18.2, "4 tbsp."),
            ("Sugar", "sweetener", 15.9, "1/4 cup"),
            ("Egg", "other", 15.9, "1 large"),
            ("Water", "water", 13.7, "3 tbsp., in the tangzhong"),
            ("Dry milk", "other", 4.5, "2 tbsp."),
            ("Instant yeast", "other", 2.9, "1 tbsp."),
            ("Salt", "salt", 1.9, "1 tsp."),
        ],
        stages=[
            {"name": "tangzhong", "min": 4, "temp_c": 65.0,
             "notes": "whisk over low heat 3-5 min, until the whisk leaves lines"},
            {"name": "mix", "min": 15, "notes": "until smooth and elastic"},
            {"name": "bulk ferment", "min": 75, "notes": "1-1.5 h, until puffy"},
            {"name": "shape", "min": 15,
             "notes": "four 170 g pieces, each flattened, folded and rolled into a log"},
            {"name": "proof", "min": 45, "notes": "40-50 min, until puffy"},
            {"name": "bake", "min": 32, "temp_c": 177.0,
             "notes": "30-35 min, milk wash first, to at least 88°C inside"},
        ],
    ),
]


#: Asked for but not seeded: no published formula could be found that gave
#: either a baker's-percentage table or gram weights to work one out from.
#: Forum threads and blog adaptations exist for all of these and disagree
#: with each other, which is exactly why none of them is in the list above.
SKIPPED: list[tuple[str, str]] = [
    ("Darnitsky",
     "60/40 rye-wheat is widely quoted but no source gives the GOST"
     " formula itself; the home versions found disagree on both the rye"
     " grade and the wheat share."),
    ("Riga / Rizhsky rye",
     "Named in passing in several places, with no formula attached."),
    ("Roggenmischbrot",
     "A category rather than a formula — sources do not even agree on the"
     " rye share that earns the name. Nothing published with gram weights"
     " turned up."),
    ("Westphalian pumpernickel",
     "Sources agree on the method — 16-24 h at about 100-120°C in a"
     " lidded pan — but none gives hydration or ratios, and they disagree"
     " on whether it is leavened at all."),
    ("Russian white baton (nareznoy)",
     "The formula lives in GOST 27844-88, whose recipe tables were not"
     " reachable. Only one home adaptation turned up, which is not enough"
     " to call it the standard."),
]
