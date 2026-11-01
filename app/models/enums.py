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


# Suggestions offered via <datalist>; users may type anything.
SMELL_SUGGESTIONS = (
    "sour", "sharp", "tangy", "yeasty", "bready", "sweet",
    "acetone", "alcoholic", "vinegary", "musty", "cheesy",
)

TEXTURE_SUGGESTIONS = (
    "thick", "thin", "runny", "stiff", "webby", "foamy", "stringy", "hooch",
)
