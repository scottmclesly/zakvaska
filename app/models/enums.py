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


class BakeMethod(enum.StrEnum):
    """How the loaf is actually cooked. Scott uses all three."""

    OVEN = "oven"
    DUTCH_OVEN = "dutch_oven"
    BREAD_MAKER = "bread_maker"

    @property
    def label(self) -> str:
        return {
            BakeMethod.OVEN: "Oven",
            BakeMethod.DUTCH_OVEN: "Cast-iron pot",
            BakeMethod.BREAD_MAKER: "Bread maker",
        }[self]

    @property
    def uses_program(self) -> bool:
        """Only the bread maker runs a named program from its manual."""
        return self is BakeMethod.BREAD_MAKER


class BakeStatus(enum.StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return {
            BakeStatus.PLANNED: "Planned",
            BakeStatus.IN_PROGRESS: "In progress",
            BakeStatus.DONE: "Done",
            BakeStatus.FAILED: "Failed",
        }[self]

    @property
    def is_finished(self) -> bool:
        return self in (BakeStatus.DONE, BakeStatus.FAILED)


class PhotoOwner(enum.StrEnum):
    """What a photo is attached to.

    A plain type/id pair rather than four nullable foreign keys: photos hang
    off four unrelated tables, and nothing else needs to join through them.
    """

    JAR = "jar"
    FEEDING = "feeding"
    OBSERVATION = "observation"
    BAKE = "bake"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class AlertKind(enum.StrEnum):
    """What an alert is chasing.

    Both kinds go down the same reconcile / fire / acknowledge / snooze path:
    a stage alert is a feeding alert that happens to be about a bake, which
    is what lets one banner and one notification permission cover both.
    """

    FEED_DUE = "feed_due"
    #: A bake-day step is due to be started, or a rise is due to be used.
    STAGE_DUE = "stage_due"
    #: The oven (and the pot in it) has to go on now to be hot when the
    #: bake step comes round. Its own kind rather than an early STAGE_DUE,
    #: because the two say different things and the banner, the phone
    #: notification and the JSON all have to tell them apart.
    PREHEAT_DUE = "preheat_due"
    #: A set of stretch-and-folds is due, part-way through a bulk ferment.
    FOLD_DUE = "fold_due"
    #: The lid comes off the pot, part-way through the bake.
    LID_OFF_DUE = "lid_off_due"

    @property
    def label(self) -> str:
        return {
            AlertKind.FEED_DUE: "Feed due",
            AlertKind.STAGE_DUE: "Bake step due",
            AlertKind.PREHEAT_DUE: "Preheat due",
            AlertKind.FOLD_DUE: "Fold due",
            AlertKind.LID_OFF_DUE: "Lid off",
        }[self]

    @property
    def is_about_a_bake(self) -> bool:
        return self is not AlertKind.FEED_DUE

    @property
    def is_preheat(self) -> bool:
        return self is AlertKind.PREHEAT_DUE


class BusyKind(enum.StrEnum):
    """Whether a busy block repeats every week or happens once."""

    RECURRING = "recurring"
    ONCE = "once"

    @property
    def label(self) -> str:
        return {
            BusyKind.RECURRING: "Every week",
            BusyKind.ONCE: "Just once",
        }[self]


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

CRUST_SUGGESTIONS = (
    "thin", "thick", "chewy", "crisp", "soft", "pale", "dark", "blistered",
    "burnt",
)

CRUMB_SUGGESTIONS = (
    "dense", "tight", "even", "open", "gummy", "moist", "dry", "crumbly",
    "sticky",
)

TASTE_SUGGESTIONS = (
    "sour", "mildly sour", "sweet", "malty", "molasses", "coriander",
    "bitter", "bland", "boozy",
)

RISE_SUGGESTIONS = (
    "flat", "modest", "good", "tall", "over-proofed", "under-proofed",
    "blew out the side",
)
