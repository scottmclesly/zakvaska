"""Reference recipes, as baker's percentages against total flour.

Three sets, assembled here so the seeder has one list to walk:

* `westbend_recipes` — every from-scratch recipe in the bread maker's
  manual, measured in cups and converted (the manual is the authority,
  the percentage is derived).
* `demo_recipes` — the Borodinsky this notebook was built around.
* `classic_recipes` — published formulas for the breads worth working
  through, each with a real source. Nothing invented; see that module's
  `SKIPPED` for what was asked for and left out.

Each entry is a dict:

    name, category, source, source_ref, notes,
    ingredients [{name, role, pct, notes}],
    stages [{name, min, temp_c, notes}],
    flour_g                        # the batch it was written at, optional
    program, loaf_size, crust      # bread-maker defaults, all optional
"""

from __future__ import annotations

from app.data.classic_recipes import RECIPES as CLASSICS
from app.data.classic_recipes import SKIPPED
from app.data.demo_recipes import RECIPES as DEMO
from app.data.westbend_recipes import RECIPES as WESTBEND

RECIPES: list[dict] = [*WESTBEND, *DEMO, *CLASSICS]

__all__ = ["CLASSICS", "DEMO", "RECIPES", "SKIPPED", "WESTBEND"]
