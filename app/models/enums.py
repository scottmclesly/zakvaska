"""Controlled vocabularies.

CLAUDE.md: "the data must be structured, not free text" — anything we expect
to filter, group or compare two jars by is an enum. Fields whose vocabulary is
genuinely open (smell, texture) stay short strings with suggestions in the UI.
"""

from __future__ import annotations

import enum


class JarOrigin(enum.StrEnum):
    HOMEMADE = "homemade"
    PURCHASED = "purchased"


class JarState(enum.StrEnum):
    ACTIVE = "active"      # on the counter, fed often
    FRIDGE = "fridge"      # cold storage, fed rarely
    DORMANT = "dormant"    # neglected on purpose; no alerts
    DRIED = "dried"        # dried down for keeps; no alerts

    @property
    def wants_feeding(self) -> bool:
        return self in (JarState.ACTIVE, JarState.FRIDGE)

    @property
    def label(self) -> str:
        return {
            JarState.ACTIVE: "Active",
            JarState.FRIDGE: "In the fridge",
            JarState.DORMANT: "Dormant",
            JarState.DRIED: "Dried",
        }[self]


class RecipeCategory(enum.StrEnum):
    RYE = "rye"
    WHEAT = "wheat"
    ENRICHED = "enriched"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class IngredientRole(enum.StrEnum):
    """What a line does in the dough.

    Roles matter for more than tidiness: FLOUR lines are the 100% that every
    other percentage is measured against.
    """

    FLOUR = "flour"
    WATER = "water"
    LEVAIN = "levain"
    SALT = "salt"
    SWEETENER = "sweetener"
    FAT = "fat"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class AlertKind(enum.StrEnum):
    FEED_DUE = "feed_due"


class BubbleLevel(enum.StrEnum):
    """Ordinal on purpose, so two jars can be compared at a glance."""

    NONE = "none"
    FEW = "few"
    SOME = "some"
    MANY = "many"
    VIGOROUS = "vigorous"

    @property
    def rank(self) -> int:
        return list(BubbleLevel).index(self)

    @property
    def label(self) -> str:
        return self.value.capitalize()


# Borodinsky's own shape, offered as suggestions on the stage form.
STAGE_SUGGESTIONS = (
    "scald (zavarka)",
    "sponge",
    "final dough",
    "bulk ferment",
    "proof",
    "bake",
    "cool",
)

INGREDIENT_SUGGESTIONS = (
    "whole rye flour",
    "bread flour",
    "water",
    "rye levain",
    "salt",
    "rye malt",
    "molasses",
    "honey",
    "coriander",
)

# Suggestions offered via <datalist>; users may type anything.
SMELL_SUGGESTIONS = (
    "sour", "sharp", "tangy", "yeasty", "bready", "sweet",
    "acetone", "alcoholic", "vinegary", "musty", "cheesy",
)

TEXTURE_SUGGESTIONS = (
    "thick", "thin", "runny", "stiff", "webby", "foamy", "stringy", "hooch",
)
