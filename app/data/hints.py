"""What a first loaf teaches, written down where the next one will need it.

Every hint in the app is in this file, and nowhere else. To add one, add a
`Hint` to `HINTS`; to change one, edit its text here. Templates only ask
"what is there to say at this place?" and draw what comes back.

A hint has:

  id         a short, permanent name. Dismissals are remembered by it, so
             rewording a hint keeps it dismissed and renaming it brings it
             back. Never reuse one.
  place      where it shows. One of `PLACES` below.
  text       one or two lines: what to do, and why.
  more       optional. A sentence or two for the "more" expander.
  explainer  optional. The name of a drawing in
             `templates/partials/explainers/`, shown in the same expander.
  methods    optional. The ways of baking it applies to, as
             `BakeMethod` values; empty means all of them.

Most of these come from Scott's first open-crumb boule (26 Nov 2026, bake 7,
cast-iron pot): each one is something that went wrong, was missed, or had to
be asked.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where a hint can show, and what that place is.
#:
#: The step places are matched to a bake's running sheet by the step's key
#: and to a recipe's stages by name: see `services.hints`.
PLACES = {
    # A jar's own page, and the form for feeding it.
    "jar.young": "On the page of a jar less than three weeks old.",
    "feed": "On the Fed-it form.",
    # Steps of a bake, in the order a loaf goes through them.
    "levain": "Building the levain.",
    "levain_rise": "The levain rising to its peak.",
    "autolyse": "The autolyse.",
    "bulk": "Bulk ferment.",
    "preshape": "Pre-shaping.",
    "shape": "Shaping.",
    "final_rise": "The final proof.",
    "preheat": "Preheating.",
    "load": "Getting the loaf into the pot.",
    "bake": "Baking, lid on.",
    "bake_open": "Baking, lid off.",
    "cool": "Cooling.",
}

POT = ("dutch_oven",)
BY_HAND = ("dutch_oven", "oven")


@dataclass(frozen=True)
class Hint:
    id: str
    place: str
    text: str
    more: str = ""
    explainer: str = ""
    methods: tuple[str, ...] = ()


HINTS: tuple[Hint, ...] = (
    # --- Jars and feeding ------------------------------------------------
    Hint(
        id="starter-quiet-days",
        place="jar.young",
        text=(
            "A new white-flour starter often rises hard on day two or "
            "three, then goes quiet for days. That is normal: keep feeding."
        ),
        more=(
            "The early rise is bacteria, not yeast. The yeast takes over "
            "once the jar turns sour enough, usually within two weeks. "
            "Bleached flour is poor for starting a culture; keep it for "
            "doughs."
        ),
    ),
    Hint(
        id="feed-temperature-times-the-peak",
        place="feed",
        text=(
            "Where the jar sits sets when it peaks. The counter at 73°F "
            "peaks hours later than the proofing box at 80°F."
        ),
        more=(
            "So choose the spot by when you want it ready: counter "
            "overnight to peak when you wake, the box to have it by "
            "afternoon."
        ),
    ),
    # --- Levain ------------------------------------------------------------
    Hint(
        id="levain-rye-jar-wheat-loaf",
        place="levain",
        text=(
            "A rye jar can raise a wheat loaf. Build the levain on bread "
            "flour from a small spoon of starter, so the rye is negligible "
            "and the gluten stays strong."
        ),
    ),
    Hint(
        id="levain-pick-the-temperature",
        place="levain",
        text=(
            "Pick the levain's spot to time its peak: the counter at 73°F "
            "overnight peaks when you wake; the proofing box at 80°F peaks "
            "hours earlier."
        ),
    ),
    Hint(
        id="levain-ready",
        place="levain_rise",
        text=(
            "Ready means doubled, domed, bubbly and smelling yeasty. Not "
            "doubled yet? Wait. A weak levain makes a weak loaf."
        ),
        more=(
            "A rubber band at the level you started from makes doubling "
            "easy to see. A dome that has started to sink has just passed "
            "its peak and is still usable."
        ),
        explainer="levain_ready",
    ),
    # --- Autolyse ----------------------------------------------------------
    Hint(
        id="autolyse-what-it-is",
        place="autolyse",
        text=(
            "Autolyse: mix only the flour and the water, then rest. No "
            "levain and no salt yet."
        ),
        more=(
            "The rest lets the flour take up the water and start forming "
            "gluten on its own, so the dough needs less working later."
        ),
    ),
    # --- Bulk ferment ------------------------------------------------------
    Hint(
        id="bulk-is-not-hands-off",
        place="bulk",
        text=(
            "Bulk is not hands-off. It starts with stretch-and-folds, "
            "usually four sets 30 minutes apart, and then you leave it."
        ),
        methods=BY_HAND,
    ),
    Hint(
        id="bulk-in-a-bowl",
        place="bulk",
        text=(
            "Bulk happens in a bowl or tub. The floured basket is for "
            "after shaping."
        ),
        more=(
            "Keep it in the same container for the whole of bulk. Moving "
            "it pushes out the gas you are waiting for."
        ),
        methods=BY_HAND,
    ),
    Hint(
        id="bulk-one-set",
        place="bulk",
        text=(
            "One set is four folds: grab an edge, stretch it up, fold it "
            "over, quarter turn, four times. Fold in the bowl, not out on "
            "the table."
        ),
        more=(
            "It is not a session of working the dough. Over-handling "
            "pushes out the gas that becomes the holes."
        ),
        explainer="fold_set",
        methods=BY_HAND,
    ),
    Hint(
        id="bulk-wet-hands",
        place="bulk",
        text=(
            "Wet hands for folding, and no flour on the mat. Flour is for "
            "shaping; here it stays raw inside the dough and dries it."
        ),
        more="A little water caught in a fold is fine. It gets absorbed.",
        methods=BY_HAND,
    ),
    Hint(
        id="bulk-done",
        place="bulk",
        text=(
            "Done is up 50 to 75%, domed, bubbles on the sides, and it "
            "jiggles. Not doubled: doubled is over-proofed."
        ),
        more=(
            "Use a straight-sided container with a tape mark at the "
            "starting level, so the rise can be read off the side."
        ),
        explainer="bulk_done",
    ),
    Hint(
        id="bulk-dough-not-clock",
        place="bulk",
        text=(
            "Go by the dough, not the clock. Warm dough finishes early; "
            "the planned time is only a guess."
        ),
    ),
    # --- Pre-shape ---------------------------------------------------------
    Hint(
        id="preshape-bare-mat",
        place="preshape",
        text=(
            "Bare mat, because the dough needs grip. Scraper, loose "
            "round, then rest 20 minutes uncovered."
        ),
        more=(
            "A slumped, sticky blob at the end of the rest is normal. A "
            "stone counter is fine: the room is warm and the mat "
            "insulates."
        ),
        methods=BY_HAND,
    ),
    Hint(
        id="preshape-clean-hands",
        place="preshape",
        text=(
            "Dough stuck to your hands: rub with dry flour, then cool "
            "water. Hot water makes it gluier."
        ),
        methods=BY_HAND,
    ),
    # --- Shape -------------------------------------------------------------
    Hint(
        id="shape-flour-the-top",
        place="shape",
        text=(
            "Flour the top of the dough and your hands, not the mat. Move "
            "the dough with the scraper, not your fingers."
        ),
        more="Be quick and firm. Hesitant poking is what makes it sticky.",
        methods=BY_HAND,
    ),
    Hint(
        id="shape-one-method",
        place="shape",
        text=(
            "Use one shaping method and stop when the top is taut or "
            "starts to tear. Shaping it twice does not make it better."
        ),
        explainer="shaping",
        methods=BY_HAND,
    ),
    Hint(
        id="shape-seam-up",
        place="shape",
        text="Into the banneton seam side up.",
        more=(
            "The seam becomes the bottom of the loaf when the basket is "
            "turned over, and the smooth side takes the score."
        ),
        methods=BY_HAND,
    ),
    # --- Final proof, in the banneton --------------------------------------
    Hint(
        id="banneton-flour-the-inside",
        place="final_rise",
        text=(
            "The elastic cloth is a liner inside or a cover on top; both "
            "are fine. What matters is that the inside of the basket is "
            "floured."
        ),
        more="Rice flour releases best. Otherwise rub in plenty of flour.",
        explainer="banneton",
        methods=BY_HAND,
    ),
    Hint(
        id="proof-on-the-counter",
        place="final_rise",
        text=(
            "Proof on the counter, not in the proofing box: slower, and "
            "easier to time against the preheat."
        ),
        methods=BY_HAND,
    ),
    Hint(
        id="proof-poke-test",
        place="final_rise",
        text=(
            "Poke test: a floured fingertip half an inch in. Springs back "
            "slowly leaving a slight dent means ready."
        ),
        more=(
            "Springs right back: wait. Does not spring back at all: bake "
            "now."
        ),
        explainer="poke_test",
    ),
    Hint(
        id="proof-ready-early",
        place="final_rise",
        text=(
            "Ready before the pot is? Put the covered basket in the "
            "fridge. That holds it, and cold dough scores more cleanly."
        ),
        methods=BY_HAND,
    ),
    # --- Preheat -----------------------------------------------------------
    Hint(
        id="preheat-heavy-pot",
        place="preheat",
        text=(
            "A heavy pot needs 45 to 60 minutes. The oven saying it is "
            "hot does not mean the iron is."
        ),
        more=(
            "The 10 qt fryer needed about 60. To check: an infrared "
            "thermometer on the inside bottom reads 450°F or more, or "
            "flicked water drops skitter and vanish in a second or two."
        ),
        methods=POT,
    ),
    Hint(
        id="preheat-lid-knob",
        place="preheat",
        text=(
            "Check the lid knob is metal. Wrap or remove a plastic or "
            "phenolic one before it goes in at this heat."
        ),
        methods=POT,
    ),
    # --- Loading -----------------------------------------------------------
    Hint(
        id="load-sling-and-score",
        place="load",
        text=(
            "Turn the basket over onto a parchment sling, seam down, and "
            "score straight away: one confident slash a quarter inch "
            "deep, blade at a shallow angle."
        ),
        more=(
            "One pass, no sawing. The sling goes on now, at bake time, "
            "not in the basket during the proof."
        ),
        explainer="loading",
        methods=POT,
    ),
    Hint(
        id="load-into-the-pot",
        place="load",
        text=(
            "Mitts on both hands. Pot onto the stovetop, lid upside down "
            "on a burner, lower the loaf in by the sling, lid on."
        ),
        methods=POT,
    ),
    # --- Bake --------------------------------------------------------------
    Hint(
        id="bake-lid-timing",
        place="bake",
        text=(
            "Lid on for 20 minutes at 475°F, then lid off at 450°F for 20 "
            "to 25 more."
        ),
        more=(
            "Lifting the lid lets out a puff of steam. Tilt it away from "
            "your face."
        ),
        methods=POT,
    ),
    Hint(
        id="bake-pale-is-right",
        place="bake_open",
        text=(
            "A pale crust when the lid comes off is correct. The colour "
            "comes next, so bake it darker than you think: pale crusts "
            "taste flat."
        ),
        explainer="lid_on_off",
        methods=POT,
    ),
    Hint(
        id="bake-probe",
        place="bake_open",
        text=(
            "Probe from the side into the very centre: 208 to 210°F. "
            "Confirm with a second thermometer."
        ),
    ),
    # --- Cool --------------------------------------------------------------
    Hint(
        id="cool-an-hour",
        place="cool",
        text=(
            "Cool at least an hour before cutting, or the inside goes "
            "gummy. It is still cooking in there."
        ),
    ),
)
