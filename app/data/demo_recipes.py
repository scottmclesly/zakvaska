"""The Borodinsky that used to live only in the test fixtures.

`tests/test_recipe_routes.py` posts a Borodinsky through the new-recipe
form in order to have something to click on, and it was the only
Borodinsky in the project. It is worth having in the notebook itself: it
is the shape of the bread Scott is working towards, and it is the one
seasoned with coriander rather than caraway.

Kept line for line the same as the fixture, with the stage temperatures
converted out of the Fahrenheit the form takes and into the Celsius the
database stores — through the app's own converter, so it cannot drift
from what typing the same numbers into the form would produce.
"""

from __future__ import annotations

from app.services.units import f_to_c


def _c(fahrenheit: float | None) -> float | None:
    return None if fahrenheit is None else round(f_to_c(fahrenheit), 2)


RECIPES: list[dict] = [
    {
        "name": "Borodinsky (demo)",
        "category": "rye",
        "source": "zakvaska",
        "source_ref": "tests/test_recipe_routes.py",
        "notes": "reference v1 — untested. first attempt. Cast-iron pot."
                 " Needs the rye starter. The demo recipe this notebook was"
                 " built around: 100% rye, a coriander-seasoned scald, and"
                 " round numbers rather than a published formula. Compare it"
                 " with the traditional scald version, which is Auerman's"
                 " actual proportions.",
        "ingredients": [
            {"name": "Whole rye flour", "role": "flour", "pct": 100.0, "notes": None},
            {"name": "Water", "role": "water", "pct": 80.0, "notes": None},
            {"name": "Rye levain", "role": "levain", "pct": 30.0,
             "notes": "100% hydration"},
            {"name": "Red rye malt", "role": "other", "pct": 5.0, "notes": None},
            {"name": "Molasses", "role": "sweetener", "pct": 5.0, "notes": None},
            {"name": "Salt", "role": "salt", "pct": 2.0, "notes": None},
            {"name": "Coriander", "role": "other", "pct": 1.0, "notes": "ground"},
        ],
        "stages": [
            {"name": "scald (zavarka)", "min": 240, "temp_c": _c(150),
             "notes": "malt, flour and boiling water"},
            {"name": "sponge", "min": 240, "temp_c": _c(84), "notes": None},
            {"name": "final dough", "min": 30, "temp_c": None, "notes": None},
            {"name": "proof", "min": 120, "temp_c": _c(82), "notes": None},
            {"name": "bake", "min": 60, "temp_c": _c(400), "notes": "steam first"},
        ],
        "program": None,
        "loaf_size": None,
        "crust": None,
    },
]
