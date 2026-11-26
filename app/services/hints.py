"""Which hints to show where, and which ones have been put away.

The hints themselves are data (`app.data.hints`). This decides where each
belongs — a bake's step by its key, a recipe's stage by its name — and
remembers the ones dismissed with "Got it".

Dismissals are one row in the settings table: the ids, comma-separated,
under `hints_dismissed`. A hint is dismissed everywhere at once, because it
is the same lesson wherever it is printed; and it is a setting rather than a
table of its own because that is all it is — a list of things not to say
again — and it needs no migration.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.data.hints import HINTS, Hint
from app.services import settings_store

DISMISSED_KEY = "hints_dismissed"

#: How long a jar counts as new enough for the hint about its first weeks.
YOUNG_JAR = timedelta(days=21)

BY_ID: dict[str, Hint] = {hint.id: hint for hint in HINTS}
assert len(BY_ID) == len(HINTS), "two hints share an id"


# --- Which places a step belongs to -------------------------------------

#: A planned bake's steps carry a key (`services.bakeplan`). One key may
#: cover more than one place: the bake step is loading, lid on and lid off.
STEP_PLACES: dict[str, tuple[str, ...]] = {
    "levain": ("levain",),
    "levain_rise": ("levain_rise",),
    "autolyse": ("autolyse",),
    "bulk": ("bulk",),
    "preshape": ("preshape",),
    "shape": ("shape",),
    "final_rise": ("final_rise",),
    "preheat": ("preheat",),
    "bake": ("load", "bake", "bake_open"),
    "cool": ("cool",),
}

#: A recipe's stages, and the steps of a bake started without a plan, have
#: only a name. First match wins, so the particular come before the general:
#: "bake (uncovered)" has to be seen before "bake".
NAME_PLACES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(pattern, re.I), places)
    for pattern, places in (
        # Mixing the levain in is not building it.
        (r"^mix\b", ()),
        (r"levain.*(rise|peak)", ("levain_rise",)),
        (r"levain", ("levain",)),
        (r"autolyse", ("autolyse",)),
        (r"bulk", ("bulk",)),
        (r"pre-?\s?shape|bench rest", ("preshape",)),
        (r"shape", ("shape",)),
        (r"final (proof|rise)|^proof$", ("final_rise",)),
        (r"preheat", ("preheat",)),
        (r"bake.*(uncovered|lid off)", ("bake_open",)),
        (r"bake.*(covered|lid on|in the pot)", ("load", "bake")),
        (r"^bake$", ("load", "bake", "bake_open")),
        (r"^cool\b", ("cool",)),
    )
)


def places_for(step_key: str | None, name: str | None) -> tuple[str, ...]:
    """The places a step or stage stands for; none if it is not one we know."""
    # A step with a key is whatever its key says, and nothing else: "Mix in
    # levain, salt and water" has the key `mix`, and must not be taken for
    # the levain build because the word is in its name.
    if step_key:
        return STEP_PLACES.get(step_key, ())
    for pattern, places in NAME_PLACES:
        if name and pattern.search(name.strip()):
            return places
    return ()


# --- What has been put away ---------------------------------------------


def dismissed(session: Session) -> frozenset[str]:
    raw = settings_store.get_setting(session, DISMISSED_KEY) or ""
    # Ids that no longer exist are dropped on the way in, so a hint removed
    # from the data does not linger in the count on the settings page.
    return frozenset(one for one in raw.split(",") if one in BY_ID)


def _store(session: Session, ids: Iterable[str]) -> None:
    settings_store.set_setting(session, DISMISSED_KEY, ",".join(sorted(ids)))


def dismiss(session: Session, hint_id: str) -> bool:
    """Put one away. False if there is no such hint."""
    if hint_id not in BY_ID:
        return False
    _store(session, dismissed(session) | {hint_id})
    return True


def restore_all(session: Session) -> None:
    _store(session, ())


# --- Asking, from a page ------------------------------------------------


@dataclass
class HintBook:
    """The hints, as one page sees them: with the dismissed ones left out.

    Built once per request and handed to every template, so a page asks
    `hints.step(log, bake)` and gets a list back without a query apiece.
    """

    session: Session
    _dismissed: frozenset[str] | None = field(default=None, repr=False)

    @property
    def put_away(self) -> frozenset[str]:
        if self._dismissed is None:
            self._dismissed = dismissed(self.session)
        return self._dismissed

    def at(self, places: Iterable[str], method: str | None = None) -> list[Hint]:
        """Hints for these places, in the order the data lists them."""
        wanted = tuple(places)
        return [
            hint
            for hint in HINTS
            if hint.place in wanted
            and hint.id not in self.put_away
            and (not hint.methods or method is None or method in hint.methods)
        ]

    def step(self, log, bake=None) -> list[Hint]:
        """For one step on a bake's running sheet."""
        method = bake.method.value if bake is not None else None
        return self.at(
            places_for(getattr(log, "step_key", None), log.name), method
        )

    def stage(self, name: str) -> list[Hint]:
        """For one stage of a recipe, which has no method yet."""
        return self.at(places_for(None, name))

    def jar(self, jar, now: datetime) -> list[Hint]:
        """For a jar's own page."""
        places = []
        if jar.created_at is not None and now - jar.created_at <= YOUNG_JAR:
            places.append("jar.young")
        return self.at(places)

    @property
    def total(self) -> int:
        return len(HINTS)

    @property
    def put_away_count(self) -> int:
        return len(self.put_away)
