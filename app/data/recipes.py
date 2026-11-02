"""Reference recipes, as baker's percentages against total flour.

Filled in by Job 3. Each entry is a dict:

    name, category, source, source_ref, notes,
    ingredients [{name, role, pct, notes}],
    stages [{name, min, temp_c, notes}],
    program, loaf_size, crust      # bread-maker defaults, all optional
"""

from __future__ import annotations

RECIPES: list[dict] = []
