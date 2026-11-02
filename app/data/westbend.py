"""The West Bend L5951 bread maker, as its manual describes it.

Timings are transcribed from the cycle chart on the manual's last page and
checked against the PDF in docs/reference/. A `None` segment is the chart's
"x": the program does not have that phase at all, which is not the same as
a phase of zero minutes.

The chart's "Rest" column is the machine's own RISE1 — the display and the
CUSTOM ranges both call it that. The name here follows the chart.
"""

from __future__ import annotations

DEVICE = "West Bend L5951"

#: The three settings behind the machine's LOAF button.
LOAF_SIZES_LB = (2.0, 2.5, 3.0)

#: The pan takes this much dough; the baked loaf comes out about a tenth
#: lighter, having left the difference behind as steam.
SIZE_NOTE = (
    "Loaf sizes are 2, 2.5 and 3 lb — the dough the pan takes, not the "
    "weight of the baked loaf."
)

DELAY_NOTE = "Delay start up to 13 hours."
NO_DELAY_NOTE = "Delay start is not available on this program."
NO_SIZE_NOTE = "The LOAF button does nothing here; there is one timing."

CUSTOM_RANGES = (
    "Every phase is adjustable: KNEAD1 3-14 min, RISE1 (rest) 20-60 min, "
    "KNEAD2 0-24 min, RISE2 1-60 min, RISE3 0-120 min, BAKE 0-80 min, "
    "WARM 0-120 min. Stir down is fixed at 30 seconds. The default when "
    "CUSTOM is first selected is the same as BASIC, and the chart's "
    "default total is 3:05."
)

BAKE_RANGE = "Bake time is set in 10-minute increments, 10 to 60 minutes."


def _sized(rows: dict[float, tuple]) -> list[dict]:
    """knead1, rest, knead2, rise2, stir_down_s, rise3, bake, total, warm, delay."""
    return [
        {
            "loaf_lb": size,
            "knead1_min": row[0],
            "rest_min": row[1],
            "knead2_min": row[2],
            "rise2_min": row[3],
            "stir_down_sec": row[4],
            "rise3_min": row[5],
            "bake_min": row[6],
            "total_min": row[7],
            "keep_warm_min": row[8],
            "delay_max_h": row[9],
        }
        for size, row in rows.items()
    ]


PROGRAMS: list[dict] = [
    {
        "menu_no": 1,
        "name": "Basic",
        "notes": (
            "White, rye, potato, egg and garlic breads, and nearly any recipe "
            "built mostly on bread flour. " + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (10, 25, 15, 20, 30, 41, 69, 180, 60, 13),
            2.5: (10, 25, 15, 20, 30, 41, 74, 185, 60, 13),
            3.0: (10, 25, 15, 20, 30, 41, 79, 190, 60, 13),
        }),
    },
    {
        "menu_no": 2,
        "name": "French",
        "notes": (
            "Particularly light white and Italian loaves. Not suitable for "
            "recipes with butter, margarine or milk. " + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (11, 38, 11, 34, 30, 36, 68, 198, 60, 13),
            2.5: (11, 38, 13, 35, 30, 36, 72, 205, 60, 13),
            3.0: (11, 40, 13, 35, 30, 36, 75, 210, 60, 13),
        }),
    },
    {
        "menu_no": 3,
        "name": "Whole Wheat",
        "notes": (
            "Breads with 50% or more whole wheat, cracked wheat, buttermilk "
            "wheat and the like. " + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (10, 35, 10, 41, 30, 51, 58, 205, 60, 13),
            2.5: (10, 40, 13, 41, 30, 51, 60, 210, 60, 13),
            3.0: (10, 40, 13, 41, 30, 51, 65, 220, 60, 13),
        }),
    },
    {
        "menu_no": 4,
        "name": "Sweet",
        "notes": (
            "Breads with raisins, cinnamon, apricots and similar. "
            + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (10, 30, 13, 30, 30, 36, 56, 175, 60, 13),
            2.5: (10, 30, 13, 33, 30, 36, 58, 180, 60, 13),
            3.0: (10, 30, 13, 36, 30, 36, 60, 185, 60, 13),
        }),
    },
    {
        "menu_no": 5,
        "name": "Super Rapid",
        "notes": (
            "A loaf in under two hours. No rest, no second rise and no stir "
            "down. " + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (9, None, 7, None, None, 20, 50, 85, 60, 13),
            2.5: (9, None, 7, None, None, 20, 53, 88, 60, 13),
            3.0: (9, None, 7, None, None, 20, 55, 90, 60, 13),
        }),
    },
    {
        "menu_no": 6,
        "name": "Sandwich",
        "notes": (
            "Lightly textured loaves with a thinner crust, for sandwiches. "
            + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (10, 33, 12, 30, 30, 36, 59, 180, 60, 13),
            2.5: (10, 34, 13, 30, 30, 36, 62, 185, 60, 13),
            3.0: (10, 36, 13, 30, 30, 36, 65, 190, 60, 13),
        }),
    },
    {
        "menu_no": 7,
        "name": "Gluten Free",
        "notes": (
            "Gluten-free recipes: one knead, one rise, no stir down. Some "
            "loaves need extra time on (12) Bake — check the internal "
            "temperature, 205-210°F. " + SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (10, None, None, None, None, 48, 66, 124, 60, 13),
            2.5: (10, None, None, None, None, 48, 68, 126, 60, 13),
            3.0: (10, None, None, None, None, 48, 70, 128, 60, 13),
        }),
    },
    {
        "menu_no": 8,
        "name": "Mix",
        "notes": (
            "Mixing only, for doughs with no yeast and no baking. "
            + NO_SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": [{
            "loaf_lb": None,
            "knead1_min": 15, "rest_min": None, "knead2_min": None,
            "rise2_min": None, "stir_down_sec": None, "rise3_min": None,
            "bake_min": None, "total_min": 15, "keep_warm_min": None,
            "delay_max_h": 13,
        }],
    },
    {
        "menu_no": 9,
        "name": "Dough",
        "notes": (
            "Dough only — kneaded and risen, not baked. This is the one for "
            "a rye that finishes in the cast-iron pot. " + NO_SIZE_NOTE
            + " " + DELAY_NOTE
        ),
        "cycles": [{
            "loaf_lb": None,
            "knead1_min": 12, "rest_min": 20, "knead2_min": 8,
            "rise2_min": 25, "stir_down_sec": None, "rise3_min": 45,
            "bake_min": None, "total_min": 110, "keep_warm_min": None,
            "delay_max_h": 13,
        }],
    },
    {
        "menu_no": 10,
        "name": "Cake",
        "notes": (
            "Mix and bake, for boxed cake mixes and quick breads. Some need "
            "extra time on (12) Bake. " + SIZE_NOTE + " " + NO_DELAY_NOTE
        ),
        "cycles": _sized({
            2.0: (15, None, None, None, None, None, 75, 100, 60, None),
            2.5: (15, None, None, None, None, None, 80, 105, 60, None),
            3.0: (15, None, None, None, None, None, 85, 110, 60, None),
        }),
    },
    {
        "menu_no": 11,
        "name": "Custom",
        "notes": CUSTOM_RANGES + " " + NO_SIZE_NOTE + " " + DELAY_NOTE,
        "cycles": [{
            "loaf_lb": None,
            "knead1_min": None, "rest_min": None, "knead2_min": None,
            "rise2_min": None, "stir_down_sec": 30, "rise3_min": None,
            "bake_min": None, "total_min": 185, "keep_warm_min": None,
            "delay_max_h": 13,
        }],
    },
    {
        "menu_no": 12,
        "name": "Bake",
        "notes": (
            "Baking and browning only, with no knead or rest cycle. Good for "
            "a loaf that came out too pale or underdone. " + BAKE_RANGE
            + " " + NO_SIZE_NOTE + " " + DELAY_NOTE
        ),
        "cycles": [{
            "loaf_lb": None,
            "knead1_min": None, "rest_min": None, "knead2_min": None,
            "rise2_min": None, "stir_down_sec": None, "rise3_min": None,
            "bake_min": None, "total_min": 60, "keep_warm_min": 60,
            "delay_max_h": 13,
        }],
    },
]
